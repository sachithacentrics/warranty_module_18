from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.warranty_management_fsm.models.warranty_service_job import _COMPLETION_MARKER

from .repair_order import FINISHED_SERVICE_STATES, INACTIVE_CASE_STATES
from .warranty_replacement import OPEN_STATES

# What the eligibility result of a Goodwill case rests on: it stays as checked (BA decision).
GOODWILL_FROZEN_FIELDS = {'state', 'eligibility_result', 'eligibility_reason', 'product_id',
                          'serial_id', 'warranty_card_id', 'warranty_unit_id'}
# SRS 12 scenario 18 (Figure 6 "On-site resolution possible?"): the Service Mode controls whether
# a Field Service job or a Repair Order / vendor transfer is used. Empty: the behaviour before
# the field (SM1).
SERVICE_MODES = [
    ('onsite', 'On-site'),
    ('workshop', 'Workshop Repair'),
    ('vendor', 'Vendor Repair'),
]
WORKSHOP_MODES = ('workshop', 'vendor')
# Written by the job's Workshop actions only (SM3). Python object: no client can send it.
_SERVICE_MODE_MARKER = object()
# Replacement types whose Done replacement completes an Approved case (approved 2026-11-10).
# Component is reviewed separately; Goodwill keeps its own completion.
COMPLETION_REPLACEMENT_TYPES = ('full', 'indoor', 'outdoor', 'vendor')


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    warranty_repair_ids = fields.One2many('repair.order', 'warranty_case_id',
                                          string='Repair Orders', readonly=True)
    warranty_repair_count = fields.Integer(compute='_compute_warranty_repair_count',
                                           compute_sudo=True)
    warranty_replacement_ids = fields.One2many('warranty.replacement', 'warranty_case_id',
                                               string='Replacements', readonly=True)
    warranty_replacement_count = fields.Integer(compute='_compute_warranty_replacement_count',
                                                compute_sudo=True)
    warranty_goodwill_can_complete = fields.Boolean(compute='_compute_warranty_goodwill_can_complete',
                                                    compute_sudo=True)
    warranty_replacement_can_complete = fields.Boolean(
        compute='_compute_warranty_replacement_can_complete', compute_sudo=True)
    warranty_backup_unit_count = fields.Integer(compute='_compute_warranty_backup_unit_count')
    warranty_service_mode = fields.Selection(
        SERVICE_MODES, string='Service Mode', tracking=True, copy=False,
        help="On-site: a Field Service job (Figures 4 / 5). Workshop Repair: the machine comes in "
             "with the ticket's Return and a Repair Order; no on-site job is created. Vendor "
             "Repair: as Workshop Repair, and the Repair Order sends the machine for repair. "
             "Empty: decided by the actions used.")

    def _compute_warranty_backup_unit_count(self):
        counts = self.env['warranty.backup.unit']._warranty_backup_counts('warranty_case_id', self)
        for case in self:
            case.warranty_backup_unit_count = counts.get(case._origin.id, 0)

    def action_view_warranty_backup_units(self):
        self.ensure_one()
        return self.env['warranty.backup.unit']._warranty_backup_action(
            [('warranty_case_id', '=', self.id)])

    @api.depends('warranty_replacement_ids')
    def _compute_warranty_replacement_count(self):
        for case in self:
            case.warranty_replacement_count = len(case.warranty_replacement_ids)

    @api.depends('state', 'warranty_replacement_ids.state')
    def _compute_warranty_goodwill_can_complete(self):
        for case in self:
            case.warranty_goodwill_can_complete = case.state == 'eligibility_checked' \
                and bool(case._warranty_goodwill_replacements(('done',)))

    def _warranty_goodwill_replacements(self, states):
        """sudo: read for the checks."""
        return self.sudo().warranty_replacement_ids.filtered(
            lambda replacement: replacement.replacement_type == 'goodwill'
            and replacement.state in states)

    def write(self, vals):
        """A case with a Goodwill replacement keeps its eligibility result until it is completed
        (BA decision). The completion carries the marker."""
        if GOODWILL_FROZEN_FIELDS & set(vals) \
                and self.env.context.get('warranty_completion_marker') is not _COMPLETION_MARKER:
            for case in self.filtered(lambda case: case.state == 'eligibility_checked'):
                goodwill = case._warranty_goodwill_replacements(('submitted', 'approved', 'done'))
                if goodwill:
                    raise UserError(_(
                        "Warranty case %(case)s has Goodwill replacement %(ref)s: its status and "
                        "eligibility result stay as checked.", case=case.name,
                        ref=goodwill[0].name))
        if 'warranty_service_mode' in vals \
                and self.env.context.get('warranty_service_mode_marker') is not _SERVICE_MODE_MARKER:
            for case in self.filtered(
                    lambda case: case.warranty_service_mode != vals['warranty_service_mode']):
                case._warranty_check_service_mode(vals['warranty_service_mode'])
        return super().write(vals)

    def _warranty_check_service_mode(self, mode):
        """SM2: a Helpdesk user decides while the case is active. An open service job keeps
        control (its Workshop actions set Workshop Repair, SM3): only Workshop <-> Vendor then. The
        mode leaves Vendor Repair only when no Repair Order of the case is at a vendor."""
        self.ensure_one()
        if not self.env.su and not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can set the Service Mode."))
        case = self.sudo()
        if case.state in ('rejected', 'closed', 'completed'):
            raise UserError(_("Warranty case %s is finished: its Service Mode cannot change.",
                              case.name))
        job = case.open_service_job_id
        if job and not (case.warranty_service_mode in WORKSHOP_MODES and mode in WORKSHOP_MODES):
            raise UserError(_(
                "Service job %(job)s of %(case)s is open: it keeps control. Use its Workshop Repair "
                "hold or Workshop Intake to move the machine to the workshop.", job=job.name,
                case=case.name))
        if case.warranty_service_mode == 'vendor' and mode != 'vendor':
            busy = case._warranty_active_repairs().filtered(
                lambda repair: repair._warranty_vendor_busy())
            if busy:
                raise UserError(_("Repair Order %s has a vendor repair transfer in progress: the "
                                  "Service Mode stays Vendor Repair.",
                                  ', '.join(busy.mapped('name'))))

    def _warranty_set_service_mode(self, mode, reason):
        """SM3: the job's Workshop actions move an On-site / unset case to Workshop Repair."""
        self.ensure_one()
        if self.warranty_service_mode in WORKSHOP_MODES:
            return
        self.sudo().with_context(warranty_service_mode_marker=_SERVICE_MODE_MARKER).write(
            {'warranty_service_mode': mode})
        self.sudo()._message_log(body=Markup('<p>%s</p>') % reason)

    def _compute_vendor_claim_figures(self):
        """The case shows the claim of a replacement, but its recovery does not reduce the material
        cost of the case: the replacement unit is not a Material Request cost."""
        super()._compute_vendor_claim_figures()
        for case in self:
            lines = case.sudo().warranty_replacement_ids.vendor_claim_line_ids.filtered(
                lambda line: line.claim_id.state != 'cancel')
            case.net_warranty_material_cost += sum(lines.mapped('recovered_amount'))

    def action_view_warranty_replacements(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _("Replacements"),
            'res_model': 'warranty.replacement',
            'view_mode': 'list,form',
            'domain': [('warranty_case_id', '=', self.id)],
            'context': {'default_warranty_case_id': self.id},
        }
        if len(self.warranty_replacement_ids) == 1:
            action.update({'view_mode': 'form', 'res_id': self.warranty_replacement_ids.id})
        return action

    def action_warranty_create_replacement(self):
        """Replacement Recommended (Figure 3): opens a new request of this case."""
        self.ensure_one()
        role = self.sudo().warranty_unit_id._warranty_serial_role(self.serial_id)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Replacement"),
            'res_model': 'warranty.replacement',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'context': {'default_warranty_case_id': self.id,
                        'default_replacement_type': role or 'full'},
        }

    def action_warranty_create_goodwill_replacement(self):
        """Goodwill Replacement of a Not Eligible or Out of Warranty case; the Submit checks."""
        action = self.action_warranty_create_replacement()
        action['context'].update(default_replacement_type='goodwill', default_reason='goodwill')
        return action

    def _warranty_goodwill_completion_problems(self):
        """The blockers of the job and repair completion paths. sudo: read for the checks."""
        self.ensure_one()
        problems = []
        if not self.warranty_goodwill_can_complete:
            problems.append(_("Warranty case %s has no Done Goodwill replacement to complete.",
                              self.sudo().name))
        return problems + self._warranty_completion_blockers()

    def _warranty_completion_blockers(self):
        """Shared by the Goodwill and replacement completions: open or unresolved replacements,
        an open service job, Repair Orders whose machine is not back, pending free services and
        Material Request problems. sudo: read for the checks."""
        self.ensure_one()
        case = self.sudo()
        problems = []
        problems.extend(case._warranty_replacement_problems())
        if case.open_service_job_id:
            problems.append(_("Service job %s is open: the case is completed by that job.",
                              case.open_service_job_id.name))
        for repair in case._warranty_active_repairs().filtered(
                lambda repair: not repair.warranty_equipment_returned
                and not case._warranty_replacement_covers(repair)):
            problems.append(_("Repair Order %s of the case: the machine has not been returned.",
                              repair.name))
        pending = case.service_entitlement_ids.filtered(
            lambda service: service.state not in FINISHED_SERVICE_STATES)
        if pending:
            problems.append(_("Free service %s is pending consumption: it needs a service job.",
                              ', '.join(pending.mapped('name'))))
        for mrf in case.material_request_ids:
            issues = mrf._warranty_material_problems()
            if issues:
                problems.append(_("Material Request %(mrf)s: %(issues)s.", mrf=mrf.name,
                                  issues='; '.join(issues)))
        return problems

    def action_warranty_complete_goodwill_case(self):
        """The job and repair paths need an Approved or Chargeable case; a Goodwill case keeps its
        result, so it completes here. Closed stays with the accounting steps (Part 8)."""
        self.ensure_one()
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can complete warranty cases."))
        problems = self._warranty_goodwill_completion_problems()
        if problems:
            raise UserError(_("Warranty case %(case)s:\n%(problems)s", case=self.name,
                              problems='\n'.join('- %s' % problem for problem in problems)))
        case = self.sudo()
        goodwill = case._warranty_goodwill_replacements(('done',))
        case.with_context(warranty_completion_marker=_COMPLETION_MARKER).write(
            {'state': 'completed'})
        goodwill[0]._warranty_replacement_log(_(
            "Warranty case %(case)s completed by %(user)s after Goodwill replacement %(ref)s. "
            "Eligibility result unchanged.", case=case.name, user=self.env.user.name,
            ref=goodwill[0].name))
        return True

    # ------------------------------------------------------------------ replacement completion
    # Approved 2026-11-10 (doc/replacement_case_completion.md): an Approved, Eligible case whose
    # replacement is Done has no service job or Repair Order to complete it, so it completes here
    # by a user action (never automatically). Same marker as the job / repair / Goodwill paths.
    @api.depends('state', 'eligibility_result', 'warranty_replacement_ids.state')
    def _compute_warranty_replacement_can_complete(self):
        for case in self:
            case.warranty_replacement_can_complete = case.state == 'approved' \
                and case.eligibility_result == 'eligible' \
                and bool(case._warranty_completion_replacements())

    def _warranty_completion_replacements(self):
        """Done replacements that complete a case here; Component and Goodwill excluded.
        sudo: read for the checks."""
        return self.sudo().warranty_replacement_ids.filtered(
            lambda replacement: replacement.replacement_type in COMPLETION_REPLACEMENT_TYPES
            and replacement.state == 'done')

    def _warranty_replacement_completion_problems(self):
        """Every blocker, listed at once: the Goodwill blockers, plus the Case Type, the validated
        transfers of the Done replacement and the Repair Orders of the case. Vendor Claims and
        Close Case checks are not completion blockers. sudo: read for the checks."""
        self.ensure_one()
        case = self.sudo()
        problems = []
        if not self.warranty_replacement_can_complete:
            problems.append(_(
                "Warranty case %s must be Approved and Eligible with a Done Full Product, Indoor "
                "Unit, Outdoor Unit or Vendor replacement.", case.name))
        if not case.case_type:
            problems.append(_("The warranty case has no Case Type."))
        for replacement in case._warranty_completion_replacements():
            if replacement.delivery_picking_id.state != 'done' or (
                    replacement.return_required and replacement.return_picking_id.state != 'done'):
                problems.append(_(
                    "Replacement %s: the return of the old serial or the delivery of the new "
                    "serial is not validated.", replacement.name))
        unfinished = case._warranty_active_repairs().filtered(lambda repair: repair.state != 'done')
        if unfinished:
            problems.append(_("Repair Order %s is not finished.",
                              ', '.join(unfinished.mapped('name'))))
        return problems + self._warranty_completion_blockers()

    def action_warranty_complete_replacement_case(self):
        """Complete Warranty Case after a Done replacement. Closed stays with Close Case."""
        self.ensure_one()
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can complete warranty cases."))
        problems = self._warranty_replacement_completion_problems()
        if problems:
            raise UserError(_("Warranty case %(case)s:\n%(problems)s", case=self.sudo().name,
                              problems='\n'.join('- %s' % problem for problem in problems)))
        case = self.sudo()
        replacements = case._warranty_completion_replacements()
        case.with_context(warranty_completion_marker=_COMPLETION_MARKER).write(
            {'state': 'completed'})
        # The Repair Order To-Do "complete the warranty case" of a replaced machine is done.
        for repair in case._warranty_active_repairs().filtered(case._warranty_replacement_covers):
            repair._warranty_repair_close_todos()
        text = _("Warranty case %(case)s completed by %(user)s after replacement %(ref)s.",
                 case=case.name, user=self.env.user.name,
                 ref=', '.join(replacements.mapped('name')))
        # Replacement, ticket, case, card and Repair Orders; further replacements get the note too.
        replacements[0]._warranty_replacement_log(text)
        for replacement in replacements[1:]:
            replacement._message_log(body=Markup('<p>%s</p>') % text)
        return True

    def _warranty_validity_period(self, card, unit):
        """Eligibility of a kit serial: the dates of that serial (SRS 11.3, 13). A replacement of
        the other serial of the unit never extends it."""
        start, end = super()._warranty_validity_period(card, unit)
        role = unit._warranty_serial_role(self.serial_id)
        if not role:
            return start, end
        role_start, role_end = unit._warranty_role_dates(role)
        return role_start or start, role_end or end

    def _warranty_replacement_problems(self):
        """Completion blocker of the job and repair paths: no case completes with an open
        replacement. sudo: read for the checks."""
        self.ensure_one()
        open_records = self.sudo().warranty_replacement_ids.filtered(
            lambda replacement: replacement.state in OPEN_STATES)
        if open_records:
            return [_("Replacement %s of the warranty case is not finished.",
                      ', '.join(open_records.mapped('name')))]
        problems = []
        for replacement in self.sudo().warranty_replacement_ids:
            location = replacement._warranty_replacement_unresolved_location()
            if location:
                problems.append(_(
                    "Rejected replacement %(ref)s: old serial %(serial)s is still in %(location)s. "
                    "Send it back to the customer, or create a new replacement.",
                    ref=replacement.name, serial=replacement.old_serial_id.name,
                    location=location.display_name))
        return problems

    def _warranty_replacement_covers(self, repair):
        """A Not Repairable Repair Order whose machine was replaced by a Done replacement of this
        case: the machine does not go back to the customer. Nothing else is waived."""
        self.ensure_one()
        return bool(
            repair.state == 'done' and repair.warranty_repair_result == 'not_repairable'
            and repair.lot_id and self.sudo().warranty_replacement_ids.filtered(
                lambda replacement: replacement.state == 'done'
                and replacement.old_serial_id == repair.lot_id))

    @api.depends('warranty_repair_ids')
    def _compute_warranty_repair_count(self):
        for case in self:
            case.warranty_repair_count = len(case.warranty_repair_ids)

    def _warranty_active_repairs(self):
        """Not cancelled Repair Orders of the case. sudo: read for the checks; Helpdesk and Sales
        users may have no Repair rights."""
        return self.sudo().warranty_repair_ids.filtered(lambda repair: repair.state != 'cancel')

    def action_view_warranty_repairs(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _("Repair Orders"),
            'res_model': 'repair.order',
            'view_mode': 'list,form',
            'domain': [('warranty_case_id', '=', self.id)],
            'context': {'create': False},
        }
        if len(self.warranty_repair_ids) == 1:
            action.update({'view_mode': 'form', 'res_id': self.warranty_repair_ids.id})
        return action

    # ------------------------------------------------------------------ case hub (UX)
    # The case opens the existing ticket Return / Repair Order / Backup / Field Service records;
    # nothing here creates stock moves or repairs (the standard forms and wizards do).
    warranty_ticket_returns = fields.Boolean(related='helpdesk_ticket_id.use_product_returns')
    warranty_ticket_repairs = fields.Boolean(related='helpdesk_ticket_id.use_product_repairs')
    warranty_return_count = fields.Integer(related='helpdesk_ticket_id.pickings_count',
                                           string='Returns')
    warranty_workshop_repair_count = fields.Integer(
        compute='_compute_warranty_workshop_repair_count', compute_sudo=True)
    warranty_visit_count = fields.Integer(compute='_compute_warranty_visit_count',
                                          compute_sudo=True)

    def _warranty_workshop_repairs(self):
        """Active Repair Orders whose machine is still in the workshop (as the job's Repair Order
        button)."""
        self.ensure_one()
        return self._warranty_active_repairs().filtered(
            lambda repair: not repair.warranty_equipment_returned
            and not self.sudo()._warranty_replacement_covers(repair))

    def _compute_warranty_workshop_repair_count(self):
        for case in self:
            case.warranty_workshop_repair_count = len(case._warranty_workshop_repairs()) \
                if case._origin.id else 0

    def _compute_warranty_visit_count(self):
        counts = dict(self.env['project.task']._read_group(
            [('warranty_case_id', 'in', self._origin.ids)], ['warranty_case_id'], ['__count']))
        for case in self:
            case.warranty_visit_count = counts.get(case._origin, 0)

    def _warranty_case_workshop_ticket(self, team_option):
        """The checks of the job's Workshop actions for the case: through its open job, else
        (Workshop / Vendor Repair cases have no job) for the case itself."""
        self.ensure_one()
        job = self.open_service_job_id
        if job:
            return job._warranty_workshop_ticket(team_option)
        if not self.env.user.has_group('stock.group_stock_user'):
            raise AccessError(_("Only Inventory users can start a workshop repair."))
        ticket = self.helpdesk_ticket_id
        if self.state in INACTIVE_CASE_STATES or not ticket:
            raise UserError(_("Warranty case %s is finished or has no Helpdesk ticket.",
                              self.name))
        if not ticket[team_option]:
            raise UserError(_("Enable %(option)s on Helpdesk team %(team)s.",
                              option=ticket.team_id._fields[team_option].string,
                              team=ticket.team_id.name))
        return ticket

    def _warranty_intake_action(self, ticket):
        """The Return wizard of the ticket (Warranty Repair Intake and its checks unchanged)."""
        action = self.env['ir.actions.act_window']._for_xml_id('stock.act_stock_return_picking')
        action['context'] = {'default_ticket_id': ticket.id,
                             'default_company_id': ticket.company_id.id}
        return action

    def _warranty_open_repair_action(self, ticket):
        """The Repair Order of the case whose machine is still in the workshop, else the Repair
        form of the ticket for this case. A Repair Order whose machine went back (or was
        replaced) is not reopened: a new repair is legitimate."""
        self.ensure_one()
        repairs = self._warranty_workshop_repairs().with_env(self.env)
        if not repairs:
            # F1: product, serial and intake of this case, also with other active cases.
            action = ticket.with_context(warranty_repair_case_id=self.id).action_repair_order_form()
            context = dict(action['context'], default_warranty_case_id=self.id)
            context.pop('warranty_repair_case_id', None)
            action['context'] = context
            return action
        action = {
            'type': 'ir.actions.act_window',
            'name': _("Repair Orders"),
            'res_model': 'repair.order',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', repairs.ids)],
            'context': {'create': False},
        }
        if len(repairs) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')], 'res_id': repairs.id})
        return action

    def action_warranty_case_workshop_intake(self):
        """Workshop Intake from the case (SRS 2.9)."""
        return self._warranty_intake_action(
            self._warranty_case_workshop_ticket('use_product_returns'))

    def action_warranty_case_open_repair(self):
        """Create / Open Repair Order from the case (SRS 2.9)."""
        return self._warranty_open_repair_action(
            self._warranty_case_workshop_ticket('use_product_repairs'))

    def action_warranty_case_issue_backup(self):
        """Issue Backup Unit: the existing action of the Repair Order in the workshop."""
        self.ensure_one()
        repairs = self._warranty_workshop_repairs().with_env(self.env)
        if len(repairs) == 1:
            return repairs.action_warranty_issue_backup()
        return self.action_view_warranty_repairs()

    def action_warranty_view_ticket(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Helpdesk Ticket"),
            'res_model': 'helpdesk.ticket',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'res_id': self.helpdesk_ticket_id.id,
        }

    def action_warranty_view_returns(self):
        self.ensure_one()
        return self.helpdesk_ticket_id.action_view_pickings()

    def action_warranty_view_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Field Service"),
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('warranty_case_id', '=', self.id)],
            'context': {'create': False},
        }

    # ------------------------------------------------------------------ Decision 3
    def _warranty_workshop_repairs_trigger(self):
        """Approved D3: a chargeable repair of a case with a workshop Repair Order and no open
        job needs no Field Service job. Service Mode (S1): Workshop / Vendor Repair need no job
        even before the Repair Order exists; On-site keeps the job. Unset: unchanged."""
        self.ensure_one()
        if self.chargeable_type != 'repair' or self.open_service_job_id \
                or self.warranty_service_mode == 'onsite':
            return False
        return self.warranty_service_mode in WORKSHOP_MODES or bool(self._warranty_active_repairs())

    def _warranty_service_mode_label(self):
        self.ensure_one()
        return dict(SERVICE_MODES).get(self.warranty_service_mode, '')

    def _warranty_create_chargeable_job(self, order, origin):
        """Approved D3: the trigger authorizes Start Repair instead of creating a job. Inspection
        and Excluded Items orders, and orders that already have a job, are unchanged."""
        self.ensure_one()
        if order.warranty_chargeable_purpose == 'repair' \
                and self._warranty_workshop_repairs_trigger() \
                and not self._warranty_chargeable_job(order):
            repairs = self._warranty_active_repairs()
            for repair in repairs.filtered(lambda repair: repair.state in ('draft', 'confirmed')):
                if repair._warranty_repair_todo(_("start the repair"), _(
                        "The Job Trigger is met on %(origin)s of %(order)s.", origin=origin,
                        order=order.name)):
                    self.sudo()._message_log(body=Markup('<p>%s</p>') % _(
                        "Job Trigger met on %(origin)s of %(order)s: Repair Order %(repair)s may "
                        "start; no Field Service job is created.", origin=origin,
                        order=order.name, repair=repair.name))
            if not repairs:
                self.sudo()._warranty_log_service_mode_once(_(
                    "Job Trigger met on %(origin)s of %(order)s. Service Mode %(mode)s: no Field "
                    "Service job is created; receive the machine (Return) and create its Repair "
                    "Order, which may then start.", origin=origin, order=order.name,
                    mode=self._warranty_service_mode_label()), order.name)
            return self.env['warranty.service.job']
        return super()._warranty_create_chargeable_job(order, origin)

    def _warranty_prepare_chargeable_job(self):
        """Prepare Service Job fallback: the existing method would open an empty job form."""
        self.ensure_one()
        if self._warranty_workshop_repairs_trigger():
            repairs = self._warranty_active_repairs()
            if not repairs:
                raise UserError(_(
                    "%(case)s has the Service Mode %(mode)s: the repair runs on a Repair Order "
                    "(ticket Return, then Repair), no Service Job is prepared.", case=self.name,
                    mode=self._warranty_service_mode_label()))
            raise UserError(_(
                "%(case)s has the workshop Repair Order %(repairs)s: the repair runs on it, no "
                "Service Job is prepared.", case=self.name,
                repairs=', '.join(repairs.mapped('name'))))
        return super()._warranty_prepare_chargeable_job()

    def action_prepare_service_job(self):
        """S1: with Service Mode Workshop / Vendor Repair, Prepare Service Job still creates the
        inspection quotation (Figure 4 "Yes"), but no on-site job. Every other case unchanged."""
        self.ensure_one()
        if self.warranty_service_mode in WORKSHOP_MODES and self.state == 'approved' \
                and self.env.user.has_group('helpdesk.group_helpdesk_user') \
                and not self.open_service_job_id \
                and not (self.warranty_inspection_required and not self._warranty_inspection_orders(
                ).filtered(self._warranty_trigger_met)):
            raise UserError(_(
                "%(case)s has the Service Mode %(mode)s: the repair runs on a Repair Order (ticket "
                "Return, then Repair); no on-site Service Job is prepared. Set the Service Mode to "
                "On-site if a visit is needed.", case=self.name,
                mode=self._warranty_service_mode_label()))
        return super().action_prepare_service_job()

    def _warranty_log_service_mode_once(self, text, key):
        """One note per case and key: the triggers are checked again on later payments."""
        self.ensure_one()
        if self.env['mail.message'].sudo().search_count([
                ('model', '=', self._name), ('res_id', '=', self.id), ('body', 'ilike', key),
                ('body', 'ilike', 'no Field Service job is created')]):
            return False
        self.sudo()._message_log(body=Markup('<p>%s</p>') % text)
        return True

    # ------------------------------------------------------------------ Figure 6 Phase 2
    def _warranty_workshop_inspection_repairs(self):
        """Figure 6: an Approved case waiting for its inspection whose machine is already in the
        workshop, with no open service job: its Repair Orders not returned whose validated intake
        received the case's product and serial (the Confirm guard). Else none."""
        self.ensure_one()
        if not self._warranty_inspection_gate() or self.open_service_job_id:
            return self.env['repair.order']
        return self._warranty_active_repairs().filtered(
            lambda repair: not repair.warranty_equipment_returned
            and not repair._warranty_repair_confirm_problems())

    def _warranty_trigger_case_job(self, origin):
        """Figure 6: the Inspection Trigger authorizes Start Repair of the workshop Repair Order
        instead of creating an on-site service job. Every other case keeps the existing behaviour;
        Prepare Service Job still creates a job on request."""
        self.ensure_one()
        mode = self.warranty_service_mode
        if mode == 'onsite':
            return super()._warranty_trigger_case_job(origin)
        repairs = self._warranty_workshop_inspection_repairs()
        orders = self._warranty_inspection_orders().filtered(self._warranty_trigger_met)
        trigger = dict(self._fields['warranty_inspection_trigger']._description_selection(
            self.env)).get(self._warranty_job_trigger())
        if mode in WORKSHOP_MODES:
            # S1: the Service Mode decides; no on-site job, with or without a Repair Order yet.
            repairs = self._warranty_active_repairs().filtered(
                lambda repair: not repair.warranty_equipment_returned)
            if self._warranty_log_service_mode_once(_(
                    "Inspection Trigger (%(trigger)s) met on %(origin)s of %(orders)s. Service Mode "
                    "%(mode)s: no Field Service job is created; the Repair Order may start.",
                    trigger=trigger, origin=origin, orders=', '.join(orders.mapped('name')),
                    mode=self._warranty_service_mode_label()), 'Inspection Trigger'):
                for repair in repairs.filtered(lambda repair: repair.state in ('draft', 'confirmed')):
                    repair._warranty_repair_todo(_("start the repair"), _(
                        "The Inspection Trigger is met on %(origin)s of %(orders)s.",
                        origin=origin, orders=', '.join(orders.mapped('name'))))
            return False
        if not repairs:
            return super()._warranty_trigger_case_job(origin)
        for repair in repairs:
            text = _("Inspection Trigger (%(trigger)s) met on %(origin)s of %(orders)s: the machine "
                     "is in the workshop with Repair Order %(repair)s, no on-site service job is "
                     "created; the repair may start.", trigger=trigger, origin=origin,
                     orders=', '.join(orders.mapped('name')), repair=repair.name)
            # Once per Repair Order: the trigger is checked again on later payments.
            if self.env['mail.message'].sudo().search_count([
                    ('model', '=', self._name), ('res_id', '=', self.id),
                    ('body', 'ilike', repair.name), ('body', 'ilike', 'no on-site service job')]):
                continue
            self.sudo()._message_log(body=Markup('<p>%s</p>') % text)
            if repair.state in ('draft', 'confirmed'):
                repair._warranty_repair_todo(_("start the repair"), text)
        return False

    # ------------------------------------------------------------------ declined repair
    def _warranty_check_decline_repair(self):
        inspection = super()._warranty_check_decline_repair()
        started = self._warranty_active_repairs().filtered(
            lambda repair: repair.state in ('under_repair', 'done'))
        if started:
            raise UserError(_("Repair Order %s has started: the repair can no longer be declined.",
                              ', '.join(started.mapped('name'))))
        return inspection

    def _warranty_decline_repair(self, reason):
        """The existing inspection-only closure, then the Repair Orders that have not started are
        cancelled; a received machine still goes back with the standard Return."""
        repairs = self._warranty_active_repairs()
        result = super()._warranty_decline_repair(reason)
        for repair in repairs:
            repair.action_repair_cancel()
            repair._warranty_repair_log(_("Repair Order %s cancelled: the customer declined the "
                                          "repair.", repair.name))
            if repair.picking_id.state == 'done' and not repair.warranty_equipment_returned:
                repair._warranty_repair_todo(_("return the machine"), _(
                    "The customer declined the repair: return the machine with the Return button "
                    "of %s.", repair.picking_id.name))
        return result
