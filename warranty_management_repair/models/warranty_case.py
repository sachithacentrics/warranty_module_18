from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.warranty_management_fsm.models.warranty_service_job import _COMPLETION_MARKER

from .repair_order import FINISHED_SERVICE_STATES
from .warranty_replacement import OPEN_STATES

# What the eligibility result of a Goodwill case rests on: it stays as checked (BA decision).
GOODWILL_FROZEN_FIELDS = {'state', 'eligibility_result', 'eligibility_reason', 'product_id',
                          'serial_id', 'warranty_card_id', 'warranty_unit_id'}


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
        return super().write(vals)

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
        case = self.sudo()
        problems = []
        if not self.warranty_goodwill_can_complete:
            problems.append(_("Warranty case %s has no Done Goodwill replacement to complete.",
                              case.name))
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

    # ------------------------------------------------------------------ Decision 3
    def _warranty_workshop_repairs_trigger(self):
        """Approved D3: a chargeable repair of a case with a workshop Repair Order and no open
        job needs no Field Service job. Every other case keeps the existing behaviour."""
        self.ensure_one()
        return self.chargeable_type == 'repair' and self._warranty_active_repairs() \
            and not self.open_service_job_id

    def _warranty_create_chargeable_job(self, order, origin):
        """Approved D3: the trigger authorizes Start Repair instead of creating a job. Inspection
        and Excluded Items orders, and orders that already have a job, are unchanged."""
        self.ensure_one()
        if order.warranty_chargeable_purpose == 'repair' \
                and self._warranty_workshop_repairs_trigger() \
                and not self._warranty_chargeable_job(order):
            for repair in self._warranty_active_repairs().filtered(
                    lambda repair: repair.state in ('draft', 'confirmed')):
                if repair._warranty_repair_todo(_("start the repair"), _(
                        "The Job Trigger is met on %(origin)s of %(order)s.", origin=origin,
                        order=order.name)):
                    self.sudo()._message_log(body=Markup('<p>%s</p>') % _(
                        "Job Trigger met on %(origin)s of %(order)s: Repair Order %(repair)s may "
                        "start; no Field Service job is created.", origin=origin,
                        order=order.name, repair=repair.name))
            return self.env['warranty.service.job']
        return super()._warranty_create_chargeable_job(order, origin)

    def _warranty_prepare_chargeable_job(self):
        """Prepare Service Job fallback: the existing method would open an empty job form."""
        self.ensure_one()
        if self._warranty_workshop_repairs_trigger():
            raise UserError(_(
                "%(case)s has the workshop Repair Order %(repairs)s: the repair runs on it, no "
                "Service Job is prepared.", case=self.name,
                repairs=', '.join(self._warranty_active_repairs().mapped('name'))))
        return super()._warranty_prepare_chargeable_job()

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
