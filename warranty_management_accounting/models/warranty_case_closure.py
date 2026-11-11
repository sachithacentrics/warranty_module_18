from markupsafe import Markup

from odoo import SUPERUSER_ID, _, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

from odoo.addons.warranty_management_repair.models.repair_order import FINISHED_SERVICE_STATES

# Part 8.5 (doc/part8_5_case_closure_design.md, SRS 2.11, 9.7 steps 8-9, Figure 3, 9.11, D11): Close
# Case on a Completed case. It only reads the operational and billing records; nothing is posted,
# paid, reconciled or closed elsewhere. Vendor claims never block (K-3). Python object: no client
# can send it.
_CASE_CLOSE_MARKER = object()
OPEN_VISIT_STATES = ('1_done', '1_canceled')


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    warranty_case_closed_by_id = fields.Many2one('res.users', string='Closed By', readonly=True,
                                                 copy=False, tracking=True)
    warranty_case_closed_date = fields.Datetime(string='Closed On', readonly=True, copy=False)

    def write(self, vals):
        """Closed comes from Close Case only, and stays until Part 9 adds a controlled reopen."""
        if self.env.uid != SUPERUSER_ID \
                and self.env.context.get('warranty_case_close_marker') is not _CASE_CLOSE_MARKER:
            if vals.get('state') == 'closed':
                raise UserError(_("Warranty cases are closed with Close Case."))
            if {'warranty_case_closed_by_id', 'warranty_case_closed_date'} & set(vals):
                raise UserError(_("The closure details are set by Close Case."))
            if 'state' in vals and any(case.state == 'closed' for case in self):
                raise UserError(_("A closed warranty case cannot change status."))
        return super().write(vals)

    def _warranty_close_operation_problems(self):
        """Jobs, visits, free services, repairs, replacements, cost lines. sudo: read."""
        self.ensure_one()
        case = self.sudo()
        problems = []
        jobs = case.service_job_ids
        if case.open_service_job_id:
            problems.append(_("Service job %s is not finished.", case.open_service_job_id.name))
        visits = jobs.filtered(lambda job: job.state != 'cancelled').visit_ids.filtered(
            lambda task: task.state not in OPEN_VISIT_STATES)
        if visits:
            problems.append(_("Field Service visit %s is not finished.",
                              ', '.join(visits.mapped('name'))))
        services = case.service_entitlement_ids.filtered(
            lambda service: service.state not in FINISHED_SERVICE_STATES)
        if services:
            problems.append(_("Free service %s is pending.", ', '.join(services.mapped('name'))))
        for repair in case._warranty_active_repairs():
            replaced = case._warranty_replacement_covers(repair)
            if repair.state != 'done':
                problems.append(_("Repair Order %s is not finished.", repair.name))
            elif not repair.warranty_equipment_returned and not replaced:
                problems.append(_("Repair Order %s: the machine has not been returned to the "
                                  "customer.", repair.name))
            elif repair.warranty_repair_result == 'not_repairable' and not replaced:
                problems.append(_("Repair Order %s is Not Repairable and has no Done replacement.",
                                  repair.name))
        problems.extend(case._warranty_replacement_problems())
        # Figure 6 (C4): the backup machine comes back before the case closes. Its assessment,
        # charge and disposition are tracked on the backup unit (SRS 17) and do not block.
        units = self.env['warranty.backup.unit'].sudo().search([
            '|', ('warranty_case_id', '=', case.id), ('repair_id', 'in', case.warranty_repair_ids.ids)])
        away = units.filtered(lambda unit: unit.state in ('issued', 'overdue') or (
            unit.state == 'draft' and unit._warranty_backup_active(unit.issue_picking_id))
            or (unit.state == 'lost' and unit.found_date))  # C2 B5f: found, not received yet
        if away:
            problems.append(_("Backup unit %s is still with the customer (or its issue transfer is "
                              "open): receive it first.", ', '.join(away.mapped('name'))))
        lines = case.warranty_cost_entry_ids.filtered(
            lambda line: line.state in ('draft', 'submitted'))
        if lines:
            problems.append(_("Cost line %s is waiting for submission or approval.",
                              ', '.join(lines.mapped('name'))))
        return problems

    def _warranty_close_billing_problems(self):
        """Chargeable orders of the case: invoiced and posted, not necessarily paid. Customer-paid
        parts follow their own Material Request setting, and backup charges their own record."""
        self.ensure_one()
        case = self.sudo()
        problems = []
        orders = self.env['sale.order'].sudo().search(
            [('warranty_case_id', '=', case.id), ('state', '!=', 'cancel')], order='id')
        for order in orders:
            purpose = order.warranty_chargeable_purpose
            if order.state != 'sale':
                if purpose:
                    problems.append(_("Quotation %s must be confirmed or cancelled.", order.name))
                continue
            unbilled = order.order_line.filtered(
                lambda line: not line.display_type and not line.is_downpayment
                and not line.warranty_mrf_line_id and (purpose or line.warranty_excluded_item_id)
                and not line.currency_id.is_zero(line.price_total)
                and not line._warranty_inspection_fee_credited()
                and float_compare(line.qty_invoiced_posted, line.product_uom_qty,
                                  precision_rounding=line.product_uom.rounding) < 0)
            if unbilled:
                problems.append(_("Order %s is not fully invoiced and posted.", order.name))
        return problems

    def _warranty_close_adjustment_problems(self):
        """D10: a customer who went ahead with the repair gets the inspection fee benefit. Declined
        or inspection-only cases keep the fee, so nothing is required of them."""
        self.ensure_one()
        case = self.sudo()
        if case.warranty_chargeable_outcome != 'repair_completed':
            return []
        orders = case._warranty_inspection_orders().filtered(lambda order: order.state == 'sale')
        fee = sum(orders.order_line.filtered(
            lambda line: line.warranty_case_id == case and not line.display_type
            and not line.is_downpayment and not line.warranty_excluded_item_id
        ).mapped('price_total'))
        if not orders or orders.currency_id[:1].is_zero(fee):
            return []
        notes, lines = case._warranty_inspection_effective()
        drafts = notes.filtered(lambda move: move.state == 'draft')
        if drafts:
            return [_("The inspection fee credit note of %s must be posted by Accounting.",
                      case.name)]
        if notes or lines:
            return []
        try:
            case._warranty_inspection_adjustment_plan()
        except UserError as error:
            return [_("Inspection fee adjustment: %s", error.args[0])]
        return [_("Apply the inspection fee adjustment.")]

    def _warranty_close_problems(self):
        """Every blocker, listed at once."""
        self.ensure_one()
        case = self.sudo()
        if case.state == 'closed':
            return [_("Warranty case %s is already closed.", case.name)]
        if case.state != 'completed':
            return [_("Only a Completed warranty case can be closed; %s is not completed.",
                      case.name)]
        problems = []
        if not case.case_type:
            problems.append(_("The warranty case has no Case Type."))
        problems.extend(case._warranty_close_operation_problems())
        try:
            case._warranty_check_requests_closed()
        except UserError as error:
            problems.append(error.args[0])
        problems.extend(case._warranty_close_billing_problems())
        problems.extend(case._warranty_close_adjustment_problems())
        return problems

    def action_warranty_close_case(self):
        self.ensure_one()
        self.check_access('read')
        if not (self.env.uid == SUPERUSER_ID
                or self.env.user.has_group('helpdesk.group_helpdesk_user')):
            raise AccessError(_("Only Helpdesk users can close warranty cases."))
        # Two users on the same case: the second one waits, then finds it closed.
        self.env.cr.execute("SELECT id FROM warranty_case WHERE id = %s FOR UPDATE", (self.id,))
        self.env.invalidate_all()
        problems = self._warranty_close_problems()
        if problems:
            raise UserError(_("Warranty case %(case)s cannot be closed:\n%(problems)s",
                              case=self.sudo().name,
                              problems='\n'.join('- %s' % problem for problem in problems)))
        case = self.sudo()
        case.with_context(warranty_case_close_marker=_CASE_CLOSE_MARKER).write({
            'state': 'closed', 'warranty_case_closed_by_id': self.env.uid,
            'warranty_case_closed_date': fields.Datetime.now()})
        case._message_log(body=Markup('<p><b>%s</b></p>') % _(
            "Warranty case %(case)s closed by %(user)s.", case=case.name,
            user=self.env.user.name))
        return True
