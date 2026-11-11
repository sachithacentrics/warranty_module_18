from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.warranty_management_fsm.models.warranty_service_job import _COMPLETION_MARKER
from odoo.addons.warranty_management_mrf.models.material_purchase_requisition import MRF_JOB_STATES

from .stock_move import MRF_ONLY_LINE_TYPES

INSPECTION_JOB_TYPES = ('chargeable_inspection', 'warranty_inspection')
# Same states as the Prepare Service Job / Material Request rules.
INACTIVE_CASE_STATES = ('rejected', 'closed', 'completed')
JOB_CASE_STATES = ('job_created', 'in_progress')
# Pending = could still be consumed by a service job (approved D2).
FINISHED_SERVICE_STATES = ('completed', 'cancelled', 'expired')
REPAIR_RESULTS = [
    ('repaired', 'Repaired'),
    ('no_fault', 'No Fault Found'),
    ('not_repairable', 'Not Repairable'),
]


class RepairOrder(models.Model):
    """Standard Repair Order linked to the warranty case (SRS 2.9, 2.16). Every rule applies only
    when warranty_case_id is set: other Repair Orders stay fully standard."""
    _inherit = 'repair.order'

    warranty_case_id = fields.Many2one(
        'warranty.case', string='Warranty Case', copy=False, tracking=True, check_company=True,
        index='btree_not_null', ondelete='restrict',
        domain="[('state', 'not in', ('rejected', 'closed', 'completed')), "
               "('company_id', '=', company_id)]"
               " + ([('helpdesk_ticket_id', '=', ticket_id)] if ticket_id else [])")
    warranty_case_state = fields.Selection(related='warranty_case_id.state',
                                           string='Warranty Case Status')
    warranty_service_job_id = fields.Many2one(
        'warranty.service.job', string='Service Job', compute='_compute_warranty_service_job_id',
        store=True)
    warranty_card_id = fields.Many2one(related='warranty_case_id.warranty_card_id')
    warranty_unit_id = fields.Many2one(related='warranty_case_id.warranty_unit_id')
    warranty_repair_result = fields.Selection(REPAIR_RESULTS, string='Repair Result', copy=False,
                                              tracking=True)
    warranty_equipment_returned = fields.Boolean(
        string='Machine Returned', compute='_compute_warranty_equipment_returned', store=True)
    warranty_intake_state = fields.Selection([
        ('awaiting_receipt', 'Awaiting Receipt'),
        ('received', 'Received'),
        ('under_repair', 'Under Repair'),
        ('at_vendor', 'Away for Repair'),
        ('repaired', 'Repaired'),
        ('returned', 'Returned'),
        ('cancelled', 'Cancelled'),
    ], string='Intake Status', compute='_compute_warranty_intake_state', store=True)
    warranty_mrf_ids = fields.One2many('material.purchase.requisition', 'warranty_repair_id',
                                       string='Material Requests', readonly=True)
    warranty_mrf_line_ids = fields.Many2many(
        'material.purchase.requisition.line', string='Material Request Lines',
        compute='_compute_warranty_mrf_line_ids')
    warranty_machine_replaced = fields.Boolean(string='Machine Replaced',
                                               compute='_compute_warranty_machine_replaced')
    # Figure 6 navigation (display only).
    warranty_backup_unit_count = fields.Integer(compute='_compute_warranty_backup_units')
    warranty_backup_open = fields.Boolean(compute='_compute_warranty_backup_units')
    warranty_next_step = fields.Char(string='Next Step', compute='_compute_warranty_next_step')

    def _compute_warranty_backup_units(self):
        counts = self.env['warranty.backup.unit']._warranty_backup_counts('repair_id', self)
        open_units = self._warranty_open_backup_units()
        for repair in self:
            repair.warranty_backup_unit_count = counts.get(repair._origin.id, 0)
            repair.warranty_backup_open = repair._origin in open_units.repair_id

    def _warranty_open_backup_units(self):
        """Backup units of these Repair Orders not issued yet or with the customer."""
        return self.env['warranty.backup.unit'].search([
            ('repair_id', 'in', self._origin.ids), ('state', 'in', ('draft', 'issued', 'overdue'))])

    def _compute_warranty_next_step(self):
        for repair in self:
            repair.warranty_next_step = repair._warranty_next_step() \
                if repair.warranty_case_id and repair._origin else False

    def _compute_warranty_machine_replaced(self):
        for repair in self:
            case = repair.warranty_case_id
            repair.warranty_machine_replaced = bool(case) \
                and case.sudo()._warranty_replacement_covers(repair)

    @api.depends('warranty_case_id.service_job_ids.state',
                 'warranty_case_id.service_job_ids.job_type')
    def _compute_warranty_service_job_id(self):
        for repair in self:
            jobs = repair.warranty_case_id.service_job_ids.filtered(
                lambda job: job.state != 'cancelled' and job.job_type not in INSPECTION_JOB_TYPES)
            repair.warranty_service_job_id = jobs.sorted('id')[-1:]

    @api.depends('warranty_case_id', 'lot_id', 'picking_id.move_ids.returned_move_ids.state')
    def _compute_warranty_equipment_returned(self):
        for repair in self:
            moves = repair.picking_id.move_ids.returned_move_ids.filtered(
                lambda move: move.state == 'done' and move.location_dest_id.usage == 'customer')
            repair.warranty_equipment_returned = bool(
                repair.warranty_case_id and moves
                and (not repair.lot_id or repair.lot_id in moves.move_line_ids.lot_id))

    @api.depends('state', 'warranty_case_id', 'picking_id.state', 'warranty_equipment_returned',
                 'product_id', 'lot_id', 'picking_id.move_line_ids.lot_id',
                 'warranty_vendor_picking_ids.state')
    def _compute_warranty_intake_state(self):
        """C5: Received = the linked Warranty Repair Intake is validated and received exactly
        this product and serial (the Confirm guard); Away for Repair = the last validated vendor
        repair transfer sent the machine away (it shows until the receive is validated)."""
        states = {'cancel': 'cancelled', 'done': 'repaired', 'under_repair': 'under_repair'}
        for repair in self:
            picking = repair.picking_id
            if not repair.warranty_case_id:
                repair.warranty_intake_state = False
            elif repair.warranty_equipment_returned:
                repair.warranty_intake_state = 'returned'
            elif repair.state != 'cancel' and repair._origin and repair._warranty_vendor_away():
                repair.warranty_intake_state = 'at_vendor'
            elif repair.state in states:
                repair.warranty_intake_state = states[repair.state]
            else:
                received = picking.warranty_repair_intake and picking.state == 'done' \
                    and picking._warranty_repair_received(repair.product_id, repair.lot_id)
                repair.warranty_intake_state = 'received' if received else 'awaiting_receipt'

    @api.depends('warranty_mrf_ids.requisition_line_ids')
    def _compute_warranty_mrf_line_ids(self):
        for repair in self:
            # sudo: shown read-only, like the Materials tab of the service job.
            repair.warranty_mrf_line_ids = repair.sudo().warranty_mrf_ids.requisition_line_ids

    # The repaired machine stays where the intake return received it, never WH/Stock (the
    # default of the Repairs operation type).
    @api.depends('picking_type_id', 'picking_id')
    def _compute_product_location_src_id(self):
        super()._compute_product_location_src_id()
        for repair in self.filtered(lambda repair: repair.picking_id.warranty_repair_intake):
            repair.product_location_src_id = repair.picking_id.location_dest_id

    @api.depends('picking_type_id', 'picking_id')
    def _compute_product_location_dest_id(self):
        super()._compute_product_location_dest_id()
        for repair in self.filtered(lambda repair: repair.picking_id.warranty_repair_intake):
            repair.product_location_dest_id = repair.picking_id.location_dest_id

    @api.constrains('warranty_case_id', 'ticket_id', 'sale_order_id')
    def _check_warranty_repair_case(self):
        for repair in self.filtered('warranty_case_id'):
            case = repair.warranty_case_id.sudo()
            if repair.ticket_id != case.helpdesk_ticket_id:
                raise ValidationError(_(
                    "Warranty case %(case)s belongs to another Helpdesk ticket than Repair Order "
                    "%(repair)s.", case=case.name, repair=repair.name))
            order = repair.sudo().sale_order_id
            if order and order.warranty_case_id != case:
                # Protects the customer's original Sales Order (approved constraint 4).
                raise ValidationError(_(
                    "Repair Order %(repair)s is linked to Sales Order %(order)s, which is not a "
                    "quotation of warranty case %(case)s.", repair=repair.name, order=order.name,
                    case=case.name))
            if repair.move_ids.filtered(lambda move: move.state != 'cancel'
                                        and move.repair_line_type in MRF_ONLY_LINE_TYPES):
                raise ValidationError(_(
                    "Repair Order %s has part lines: remove them before linking it to a warranty "
                    "case (its parts come from Material Requests).", repair.name))

    @api.constrains('warranty_case_id')
    def _check_warranty_repair_case_state(self):
        for repair in self.filtered('warranty_case_id'):
            if repair.warranty_case_id.sudo().state in INACTIVE_CASE_STATES:
                raise ValidationError(_("Warranty case %s is finished: no new Repair Order can be "
                                        "linked to it.", repair.warranty_case_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('warranty_case_id') and not vals.get('ticket_id'):
                vals['ticket_id'] = self.env['warranty.case'].sudo().browse(
                    vals['warranty_case_id']).helpdesk_ticket_id.id
        repairs = super().create(vals_list)
        repairs.filtered('warranty_case_id')._warranty_repair_linked()
        return repairs

    def write(self, vals):
        if vals.get('warranty_case_id') and 'ticket_id' not in vals:
            vals = dict(vals, ticket_id=self.env['warranty.case'].sudo().browse(
                vals['warranty_case_id']).helpdesk_ticket_id.id)
        result = super().write(vals)
        if vals.get('warranty_case_id'):
            self._warranty_repair_linked()
        return result

    def _warranty_repair_linked(self):
        """History note; an open Final Repair Quotation of the case becomes the order of the
        repair (no second quotation)."""
        for repair in self:
            case = repair.warranty_case_id.sudo()
            if not repair.sale_order_id and case.chargeable_type == 'repair':
                order = self.env['sale.order'].sudo().search([
                    ('warranty_case_id', '=', case.id), ('state', '!=', 'cancel'),
                    ('warranty_chargeable_purpose', '=', 'repair')], order='id desc', limit=1)
                if order:
                    repair.sudo().sale_order_id = order
            repair._warranty_repair_log(_(
                "Repair Order %(repair)s linked to warranty case %(case)s by %(user)s.",
                repair=repair.name, case=case.name, user=self.env.user.name))
            job = case.open_service_job_id
            if job and job.job_type not in INSPECTION_JOB_TYPES:
                # SM3: a job-led workshop repair; the job keeps control of the completion.
                case._warranty_set_service_mode('workshop', _(
                    "Service Mode set to Workshop Repair: Repair Order %(repair)s was created for "
                    "the open service job %(job)s.", repair=repair.name, job=job.name))

    # ------------------------------------------------------------------ history and To-Dos
    def _warranty_repair_log(self, text):
        """Warranty history notes (SRS 2.13): Repair Order, case, card and service job, naming the
        unit. sudo: the repair user may not read or write them; notes only."""
        self.ensure_one()
        repair = self.sudo()
        unit = repair.warranty_unit_id.name
        body = Markup('<p>%s</p>') % ('%s (%s)' % (text, unit) if unit else text)
        for record in (repair, repair.warranty_case_id, repair.warranty_card_id,
                       repair.warranty_service_job_id):
            if record:
                record._message_log(body=body)

    def _warranty_repair_todo_prefix(self):
        self.ensure_one()
        return _("Repair Order %s: ", self.name)

    def _warranty_repair_close_todos(self):
        """Closes the open Repair Order To-Dos of this module. sudo: To-Dos of other users."""
        self.ensure_one()
        prefix = self._warranty_repair_todo_prefix()
        self.sudo().activity_ids.filtered(
            lambda activity: (activity.summary or '').startswith(prefix)
        ).action_feedback(feedback=_("Next step reached."))

    def _warranty_repair_todo(self, step, note):
        """The next step for the ticket's assigned user, else the creator; the previous step is
        closed; no duplicate. Returns whether a To-Do was created."""
        self.ensure_one()
        repair = self.sudo()
        summary = '%s%s' % (self._warranty_repair_todo_prefix(), step)
        if repair.activity_ids.filtered(lambda activity: activity.summary == summary):
            return False
        self._warranty_repair_close_todos()
        user = repair.ticket_id.user_id or repair.create_uid
        if not user:
            return False
        repair.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=summary,
                                 note=note)
        return True

    # ------------------------------------------------------------------ guards
    def _warranty_repair_confirm_problems(self):
        """Linked Repair Order: the machine was received by an intake return, with exactly this
        product and serial record, and the serial of the case (kit Indoor / Outdoor serials of the
        unit included). BA-1: no intake return."""
        self.ensure_one()
        problems = []
        picking = self.picking_id
        if self.lot_id and self.lot_id.product_id != self.product_id:
            problems.append(_("Serial %(serial)s belongs to product %(serial_product)s, not to "
                              "%(product)s.", serial=self.lot_id.name,
                              serial_product=self.lot_id.product_id.display_name,
                              product=self.product_id.display_name))
        if not picking.warranty_repair_intake:
            problems.append(_("Link the Warranty Repair Intake return of the machine (Return "
                              "button of the Helpdesk ticket)."))
        elif picking.state != 'done':
            problems.append(_("The machine has not been received: validate %s.", picking.name))
        elif not picking._warranty_repair_received(self.product_id, self.lot_id):
            problems.append(_("Return %(picking)s did not receive product %(product)s, serial "
                              "%(serial)s: link the return of this machine.",
                              picking=picking.name, product=self.product_id.display_name,
                              serial=self.lot_id.name or '-'))
        case = self.warranty_case_id.sudo()
        unit = case.warranty_unit_id
        serials = case.serial_id | unit.serial_ids | unit.indoor_serial_id | unit.outdoor_serial_id
        if serials and self.lot_id not in serials:
            problems.append(_("Serial %(serial)s is not the serial of warranty case %(case)s "
                              "(%(serials)s).", serial=self.lot_id.name or '-', case=case.name,
                              serials=', '.join(serials.mapped('name'))))
        return problems

    def _warranty_repair_start_problems(self):
        """Approval before the work: a job keeps control when it exists; a chargeable repair waits
        for the Job Trigger (approved D3); a warranty repair follows the Prepare Service Job rule,
        and the inspection quotation of Figure 4 when the case requires one (BA-6)."""
        self.ensure_one()
        case = self.warranty_case_id.sudo()
        if self.warranty_equipment_returned:
            return [_("The machine has already been returned to the customer.")]
        if not case.case_type:
            return [_("Warranty case %s has no Case Type yet: complete the inspection first.",
                      case.name)]
        if case.state in JOB_CASE_STATES:
            job = case.open_service_job_id
            if not job or job.job_type in INSPECTION_JOB_TYPES:
                return [_("Warranty case %s: complete its inspection job first.", case.name)]
            return []
        if case.state == 'chargeable':
            if case.chargeable_type != 'repair':
                return [_("Warranty case %s is not at its chargeable repair step yet.", case.name)]
            if not case._warranty_trigger_orders():
                return [_("The Job Trigger of warranty case %s is not met: the repair quotation "
                          "must be confirmed (On Sales Order Confirmation) or fully invoiced and "
                          "paid (On Payment).", case.name)]
            return []
        if case.state != 'approved' or case.eligibility_result != 'eligible':
            return [_("Warranty repairs start from Approved, Eligible warranty cases (%s).",
                      case.name)]
        if case._warranty_inspection_gate() and not case._warranty_inspection_orders().filtered(
                case._warranty_trigger_met):
            return [_("Warranty case %s requires an inspection quotation: wait for its Inspection "
                      "Trigger.", case.name)]
        return []

    def _warranty_repair_raise(self, problems):
        self.ensure_one()
        if problems:
            raise UserError(_("Repair Order %(repair)s:\n%(problems)s", repair=self.name,
                              problems='\n'.join('- %s' % problem for problem in problems)))

    def action_validate(self):
        self.ensure_one()
        if self.warranty_case_id:
            self._warranty_repair_raise(self._warranty_repair_confirm_problems())
        elif self.ticket_id and self.ticket_id.sudo()._warranty_active_cases():
            raise UserError(_("Helpdesk ticket %s has an active warranty case: select the "
                              "Warranty Case of this Repair Order.", self.ticket_id.name))
        return super().action_validate()

    def action_repair_start(self):
        linked = self.filtered('warranty_case_id')
        for repair in linked:
            repair._warranty_repair_raise(repair._warranty_repair_confirm_problems()
                                          + repair._warranty_repair_start_problems())
        result = super().action_repair_start()
        for repair in linked:
            # sudo: value follows the case; no part lines to reprice (approved D1).
            repair.sudo().under_warranty = not repair.warranty_case_id.sudo().chargeable_type
            repair._warranty_repair_close_todos()
            repair._warranty_repair_log(_("Repair Order %(repair)s started by %(user)s.",
                                          repair=repair.name, user=self.env.user.name))
        return result

    def action_repair_done(self):
        linked = self.filtered('warranty_case_id')
        for repair in linked:
            problems = []
            if not repair.warranty_repair_result:
                problems.append(_("Set the Repair Result."))
            if repair.warranty_equipment_returned:
                problems.append(_("The machine has already been returned to the customer."))
            repair._warranty_repair_raise(problems)
        result = super().action_repair_done()
        results = dict(REPAIR_RESULTS)
        for repair in linked:
            repair._warranty_repair_log(_(
                "Repair Order %(repair)s ended by %(user)s: %(result)s.", repair=repair.name,
                user=self.env.user.name, result=results[repair.warranty_repair_result]))
            repair._warranty_repair_todo(_("return the machine"), _(
                "Return the machine to the customer with the Return button of %s; a delivery "
                "visit of the service job follows its usual steps.", repair.picking_id.name))
        return result

    def action_create_sale_order(self):
        """Create Quotation: only a chargeable repair of the case bills through this button; the
        existing create hook sets its purpose. Warranty parts are quoted by the Material Request."""
        linked = self.filtered('warranty_case_id')
        if not linked:
            return super().action_create_sale_order()
        self.ensure_one()
        case = self.warranty_case_id.sudo()
        if case.state != 'chargeable' or case.chargeable_type != 'repair':
            raise UserError(_("Warranty case %s is not at its chargeable repair step: no repair "
                              "quotation is needed.", case.name))
        return super(RepairOrder, self.with_context(
            default_warranty_case_id=case.id)).action_create_sale_order()

    # ------------------------------------------------------------------ Decision 2
    def _warranty_repair_completion_problems(self):
        """Approved D2: workshop-only completion; every problem, listed at once."""
        self.ensure_one()
        case = self.warranty_case_id.sudo()
        problems = []
        if self.state != 'done':
            problems.append(_("The repair is not finished (Repaired)."))
        # Part 7: a machine replaced by a Done replacement does not go back; every other check stays.
        replaced = case._warranty_replacement_covers(self)
        if not self.warranty_equipment_returned and not replaced:
            problems.append(_("The machine has not been returned to the customer."))
        if self.warranty_repair_result == 'not_repairable' and not replaced:
            problems.append(_("Result Not Repairable: the next step needs a business decision "
                              "(BA-2)."))
        others = case._warranty_active_repairs() - self
        for repair in others.filtered(lambda repair: not repair.warranty_equipment_returned
                                      and not case._warranty_replacement_covers(repair)):
            problems.append(_("Repair Order %s of the case: the machine has not been returned.",
                              repair.name))
        problems.extend(case._warranty_replacement_problems())
        if case.open_service_job_id:
            problems.append(_("Service job %s is open: the case is completed by that job.",
                              case.open_service_job_id.name))
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
        if not case.case_type:
            problems.append(_("The warranty case has no Case Type."))
        if case.state != 'approved' and not (case.state == 'chargeable'
                                             and case.chargeable_type == 'repair'):
            problems.append(_("The warranty case must be Approved or Chargeable (Repair)."))
        return problems

    def action_warranty_complete_case(self):
        """Complete Warranty Case: the narrow exception to approved K6 (decision 2026-11-02);
        Closed stays with the accounting steps (Part 8)."""
        self.ensure_one()
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can complete warranty cases."))
        if not self.warranty_case_id:
            raise UserError(_("Repair Order %s has no warranty case.", self.name))
        self._warranty_repair_raise(self._warranty_repair_completion_problems())
        case = self.warranty_case_id.sudo()
        vals = {'state': 'completed'}
        if case.state == 'chargeable':
            vals['warranty_chargeable_outcome'] = 'repair_completed'
        # sudo + marker: the case status follows the validated completion (like the existing
        # Customer Declined Repair).
        case.with_context(warranty_completion_marker=_COMPLETION_MARKER).write(vals)
        self._warranty_repair_close_todos()
        self._warranty_repair_log(_(
            "Warranty case %(case)s completed by %(user)s from Repair Order %(repair)s "
            "(workshop repair, no service job).", case=case.name, user=self.env.user.name,
            repair=self.name))
        return True

    # ------------------------------------------------------------------ Figure 6 navigation
    def _warranty_next_step(self):
        """Repair Order Next Step: read only, from the existing guards (the first problem they
        would raise), the backup units and the case status. Nothing is checked or changed here."""
        self.ensure_one()
        case = self.warranty_case_id.sudo()
        if self.state == 'cancel':
            return False
        returned = self.warranty_equipment_returned or self.warranty_machine_replaced
        if self.state in ('draft', 'confirmed', 'under_repair'):
            if self.state == 'under_repair' and self._warranty_vendor_open_pickings():
                step = _("Validate the vendor repair transfer %s.",
                         self._warranty_vendor_open_pickings()[:1].name)
            elif self.state == 'under_repair' and self._warranty_vendor_away():
                step = _("The machine is away for repair: Receive from Repair when it comes back.")
            elif self.state == 'under_repair' and case.warranty_service_mode == 'vendor' \
                    and not self.warranty_vendor_picking_ids:
                step = _("Send for Repair.")
            elif self.state == 'under_repair':
                step = _("Set the Repair Result, then End Repair.") \
                    if not self.warranty_repair_result else _("End Repair.")
            else:
                problems = self._warranty_repair_confirm_problems()
                if self.state == 'confirmed' and not problems:
                    problems = self._warranty_repair_start_problems()
                step = problems[0] if problems else (
                    _("Confirm the Repair Order.") if self.state == 'draft' else _("Start Repair."))
            if not self.warranty_backup_unit_count:
                step = _("%s Optional: Issue Backup Machine.", step)
            return step
        if not returned:
            return _("Return Machine to Customer.")
        backup_step = self.env['warranty.backup.unit'].sudo().search(
            [('repair_id', '=', self.id)])._warranty_backup_next_step()
        if backup_step:
            return backup_step
        if case.state in ('approved', 'chargeable'):
            problems = self._warranty_repair_completion_problems()
            return problems[0] if problems else _("Complete Warranty Case.")
        if case.state in JOB_CASE_STATES:
            return _("Complete service job %s: it completes the warranty case.",
                     case.open_service_job_id.name or '-')
        if case.state == 'completed':
            return _("Warranty case completed: it is closed with the accounting steps.")
        return False

    def action_warranty_create_material_request(self):
        """Figure 7 D9 (Helpdesk / Service Job / Repair Order -> MRF): the existing Create
        Material Request form of the case, linked to exactly this Repair Order. The service job
        is linked only when the case has exactly one job that accepts requests (never guessed);
        no Field Service visit (workshop work). Customer, product and serial follow the case."""
        self.ensure_one()
        case = self.warranty_case_id
        if not case:
            raise UserError(_("Repair Order %s has no warranty case.", self.name))
        if self.state in ('done', 'cancel') or self.warranty_equipment_returned:
            raise UserError(_("Repair Order %s is closed: request parts on an open Repair Order.",
                              self.name))
        # sudo: jobs are read for the link only; repair users may have no Field Service rights.
        jobs = case.sudo().service_job_ids.filtered(
            lambda job: job.state in MRF_JOB_STATES and job.job_type not in INSPECTION_JOB_TYPES)
        job = jobs if len(jobs) == 1 else False
        action = self.env['material.purchase.requisition']._warranty_mrf_form_action(case, job)
        action['context']['default_warranty_repair_id'] = self.id
        return action

    def action_warranty_issue_backup(self):
        """Issue Backup Machine: the Backup Unit form prefilled with ticket, case and Repair
        Order (customer, card and service job follow them). Nothing is created or issued here:
        the user saves the form and uses Create Issue Transfer. A unit not issued yet or with the
        customer is opened instead of a second one."""
        self.ensure_one()
        self.env['warranty.backup.unit']._warranty_backup_check_coordinator()
        if not self.warranty_case_id or not self.ticket_id:
            raise UserError(_("Repair Order %s has no warranty case.", self.name))
        if self.state == 'cancel' or self.warranty_equipment_returned \
                or self.warranty_machine_replaced:
            raise UserError(_("The machine of Repair Order %s is no longer in the workshop: no "
                              "backup machine is needed.", self.name))
        units = self._warranty_open_backup_units()
        if units:
            return self.env['warranty.backup.unit']._warranty_backup_action(
                [('id', 'in', units.ids)])
        return {
            'type': 'ir.actions.act_window',
            'name': _("Issue Backup Machine"),
            'res_model': 'warranty.backup.unit',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_ticket_id': self.ticket_id.id,
                'default_warranty_case_id': self.warranty_case_id.id,
                'default_repair_id': self.id,
            },
        }

    def action_view_warranty_backup_units(self):
        self.ensure_one()
        return self.env['warranty.backup.unit']._warranty_backup_action(
            [('repair_id', '=', self.id)])

    def action_warranty_return_machine(self):
        """Return Machine to Customer: the standard Return of the Warranty Repair Intake receipt
        (as its Return button: serial, quantity, locations and Sales Order quantities unchanged).
        A return not validated yet is opened instead of a second one."""
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_user'):
            raise AccessError(_("Only Inventory users can return the machine."))
        picking = self.picking_id
        if not self.warranty_case_id or self.state != 'done':
            raise UserError(_("Repair Order %s is not a finished warranty repair.", self.name))
        if self.warranty_equipment_returned or self.warranty_machine_replaced:
            raise UserError(_("The machine of Repair Order %s has already been returned or "
                              "replaced.", self.name))
        if not picking.warranty_repair_intake or picking.state != 'done':
            raise UserError(_("Repair Order %s has no validated Warranty Repair Intake.",
                              self.name))
        pending = picking.move_ids.returned_move_ids.filtered(
            lambda move: move.state not in ('done', 'cancel')
            and move.location_dest_id.usage == 'customer').picking_id
        if pending:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_id': pending[:1].id,
            }
        action = self.env['ir.actions.act_window']._for_xml_id('stock.act_stock_return_picking')
        action['context'] = {'active_id': picking.id, 'active_ids': picking.ids,
                             'active_model': 'stock.picking'}
        return action
