from markupsafe import Markup

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_amount

from odoo.addons.warranty_management_mrf.models.material_purchase_requisition_cost import \
    COST_GROUPS

# Part 8.4 (doc/part8_4_inspection_adjustment_design.md, SRS 2.11, 9.7, 13, 17, D10): the inspection
# fee benefit of a repair the customer proceeds with. A posted inspection invoice gets one draft
# credit note through the standard reversal; otherwise one deduction line on the repair quotation.
# Nothing is posted, paid, reconciled or refunded here.
ADJUSTMENT_STATUSES = [
    ('none', 'No Adjustment'),
    ('credit_draft', 'Draft Credit Note'),
    ('credit_posted', 'Posted Credit Note'),
    ('quotation', 'Repair Quotation Adjustment'),
]
BLOCKED_OUTCOMES = ('inspection_only', 'repair_declined')
INSPECTION_MOVE_FIELDS = {'warranty_inspection_case_id', 'warranty_inspection_credit_limit'}
DEDUCTION_LINE_FIELDS = {'product_id', 'product_uom_qty', 'product_uom', 'price_unit', 'discount',
                         'tax_id', 'warranty_inspection_deduction_case_id'}


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    warranty_inspection_credit_note_ids = fields.One2many(
        'account.move', 'warranty_inspection_case_id', string='Inspection Credit Notes',
        groups=COST_GROUPS)
    warranty_inspection_deduction_line_ids = fields.One2many(
        'sale.order.line', 'warranty_inspection_deduction_case_id',
        string='Inspection Deduction Lines', groups=COST_GROUPS)
    warranty_inspection_adjustment_status = fields.Selection(
        ADJUSTMENT_STATUSES, string='Inspection Fee Adjustment',
        compute='_compute_warranty_inspection_adjustment', compute_sudo=True, groups=COST_GROUPS)
    warranty_inspection_adjustment_ref = fields.Char(
        string='Adjustment Document', compute='_compute_warranty_inspection_adjustment',
        compute_sudo=True, groups=COST_GROUPS)
    warranty_inspection_can_adjust = fields.Boolean(
        compute='_compute_warranty_inspection_can_adjust')

    def _warranty_inspection_effective(self):
        """(credit notes, deduction lines) that currently give the fee benefit. A cancelled or
        fully reversed credit note and a line of a cancelled order do not. sudo: read."""
        self.ensure_one()
        case = self.sudo()
        notes = case.warranty_inspection_credit_note_ids.filtered(
            lambda move: move.state != 'cancel' and move._warranty_reversed_ratio() < 1.0)
        lines = case.warranty_inspection_deduction_line_ids.filtered(
            lambda line: line.order_id.state != 'cancel')
        return notes, lines

    def _compute_warranty_inspection_adjustment(self):
        for case in self:
            notes, lines = case._warranty_inspection_effective()
            if notes:
                status = 'credit_posted' if 'posted' in notes.mapped('state') else 'credit_draft'
                ref = notes[:1].name if notes[:1].name != '/' else notes[:1].display_name
            elif lines:
                status, ref = 'quotation', lines[:1].order_id.name
            else:
                status, ref = 'none', False
            case.warranty_inspection_adjustment_status = status
            case.warranty_inspection_adjustment_ref = ref

    @api.depends_context('uid')
    def _compute_warranty_inspection_can_adjust(self):
        allowed = self._warranty_inspection_billing_user()
        for case in self:
            record = case.sudo()
            notes, lines = case._warranty_inspection_effective()
            case.warranty_inspection_can_adjust = not notes and not lines \
                and record.state != 'closed' \
                and (allowed or case._warranty_inspection_named_approver()) \
                and record.warranty_chargeable_outcome not in BLOCKED_OUTCOMES \
                and bool(record._warranty_inspection_orders()) \
                and bool(record._warranty_repair_orders())

    def _warranty_repair_orders(self):
        """Repair quotations of the case, not cancelled. sudo: read for the check."""
        self.ensure_one()
        return self.env['sale.order'].sudo().search([
            ('warranty_case_id', '=', self.id), ('warranty_chargeable_purpose', '=', 'repair'),
            ('state', '!=', 'cancel')], order='id')

    def _warranty_inspection_billing_user(self):
        return self.env.uid == SUPERUSER_ID \
            or self.env.user.has_group('account.group_account_invoice')

    def _warranty_inspection_named_approver(self):
        self.ensure_one()
        company = self.sudo().company_id
        return self.env.user in (company.warranty_cost_approver_ids
                                 | company.warranty_cost_finance_approver_ids)

    def _warranty_inspection_fee_line(self, order):
        """The fee line of an inspection order: the case line, not an excluded item or a down
        payment."""
        lines = order.order_line.filtered(
            lambda line: line.warranty_case_id == self and not line.display_type
            and not line.is_downpayment and not line.warranty_excluded_item_id)
        if len(lines) != 1:
            raise UserError(_("Inspection order %s must have exactly one inspection fee line for "
                              "this adjustment. Accounting should review it.", order.name))
        return lines

    def _warranty_inspection_adjustment_plan(self):
        """D10: which route applies, or a UserError naming the reason. Read only, sudo."""
        self.ensure_one()
        case = self.sudo()
        notes, lines = case._warranty_inspection_effective()
        if notes or lines:
            raise UserError(_("Warranty case %(case)s already has an inspection fee adjustment: "
                              "%(document)s.", case=case.name,
                              document=(notes[:1].display_name or lines[:1].order_id.name)))
        if case.warranty_chargeable_outcome in BLOCKED_OUTCOMES:
            raise UserError(_("Warranty case %s ended without a repair: the inspection fee stays "
                              "charged.", case.name))
        if case.state in ('rejected', 'closed'):
            raise UserError(_("Warranty case %s is rejected or closed.", case.name))
        orders = case._warranty_inspection_orders().filtered(lambda order: order.state == 'sale')
        if not orders:
            raise UserError(_("Warranty case %s has no confirmed inspection order: no inspection "
                              "fee was charged.", case.name))
        if len(orders) > 1:
            raise UserError(_("Warranty case %s has more than one confirmed inspection order. "
                              "Accounting should review them.", case.name))
        repairs = case._warranty_repair_orders()
        if len(repairs) != 1:
            raise UserError(_("Warranty case %s needs exactly one active final repair quotation.",
                              case.name))
        fee_line = case._warranty_inspection_fee_line(orders)
        fee_total = fee_line.price_total
        currency = fee_line.currency_id
        company = case.company_id
        if {orders.company_id, repairs.company_id} != {company}:
            raise UserError(_("The inspection and repair orders of %s must belong to its company.",
                              case.name))
        if repairs.currency_id != currency:
            raise UserError(_("The inspection and repair orders of %s have different currencies.",
                              case.name))
        posted = orders.invoice_ids.filtered(
            lambda move: move.state == 'posted' and move.move_type == 'out_invoice')
        if posted.invoice_line_ids.sale_line_ids.filtered('is_downpayment') \
                or orders.order_line.filtered('is_downpayment'):
            raise UserError(_("Inspection order %s has a down payment. This adjustment does not "
                              "handle it: Accounting should review it.", orders.name))
        if posted:
            invoice = posted.filtered(lambda move: fee_line in move.invoice_line_ids.sale_line_ids)
            if len(posted) != 1 or len(invoice) != 1:
                raise UserError(_("Inspection order %s has more than one posted invoice. "
                                  "Accounting should review them.", orders.name))
            if invoice.currency_id != currency:
                raise UserError(_("Inspection invoice %s has a different currency.", invoice.name))
            if invoice.company_id != company:
                raise UserError(_("Inspection invoice %s belongs to another company.", invoice.name))
            if invoice.payment_state == 'reversed' or orders.invoice_ids.filtered(
                    lambda move: move.move_type == 'out_refund' and move.state != 'cancel'):
                raise UserError(_("Inspection invoice %s already has a credit note. Accounting "
                                  "should review it, so the fee is not credited twice.",
                                  invoice.name))
            if invoice.reversal_move_ids.filtered(lambda move: move.state != 'cancel'):
                raise UserError(_("Inspection invoice %s already has a reversal. Accounting should "
                                  "review it, so the fee is not credited twice.", invoice.name))
            if repairs.state != 'sale':
                raise UserError(_("Repair quotation %s must be confirmed first: the credit note "
                                  "applies when the customer proceeds with the repair.",
                                  repairs.name))
            route = 'credit'
            fee_total = sum(invoice.invoice_line_ids.filtered(
                lambda aml: fee_line in aml.sale_line_ids).mapped('price_total'))
        else:
            invoice = self.env['account.move']
            route = 'quotation'
            if repairs.state not in ('draft', 'sent'):
                raise UserError(_("Repair order %(order)s is confirmed, and no inspection invoice "
                                  "is posted. Post the inspection invoice first, so the adjustment "
                                  "uses a credit note.", order=repairs.name))
            done = case.service_job_ids.filtered(
                lambda job: job.job_type == 'chargeable_inspection' and job.state == 'completed')
            if not done:
                raise UserError(_("Warranty case %s has no completed inspection job: the fee is "
                                  "not eligible for deduction.", case.name))
            product = case.helpdesk_ticket_id.team_id.warranty_inspection_deduction_product_id
            if not product:
                raise UserError(_("Set the Inspection Deduction Product of Helpdesk team %s.",
                                  case.helpdesk_ticket_id.team_id.name))
            if product.invoice_policy != 'order':
                raise UserError(_("Inspection Deduction Product %s must be invoiced on ordered "
                                  "quantities, or the deduction would not reach the invoice.",
                                  product.display_name))
            if repairs.fiscal_position_id != orders.fiscal_position_id:
                raise UserError(_("The inspection and repair orders of %s have different fiscal "
                                  "positions: the tax of the deduction cannot be decided safely.",
                                  case.name))
        if currency.compare_amounts(fee_total, 0.0) <= 0:
            raise UserError(_("Inspection order %s has no fee to adjust.", orders.name))
        if currency.compare_amounts(fee_total, repairs.amount_total) > 0:
            raise UserError(_(
                "The inspection fee %(fee)s is above the repair total %(repair)s of %(order)s. No "
                "adjustment is created: Finance decides this case (F5). Check that the repair is "
                "priced.", fee=format_amount(self.env, fee_total, currency),
                repair=format_amount(self.env, repairs.amount_total, currency),
                order=repairs.name))
        return {'route': route, 'order': orders, 'repair': repairs, 'fee_line': fee_line,
                'invoice': invoice, 'fee_total': fee_total}

    def _warranty_inspection_create_credit_note(self, plan):
        """Standard reversal, left in draft. Other lines of the invoice stay out of it, and the
        total is checked against the fee. sudo: the checked action of an authorized user."""
        case = self.sudo()
        invoice, fee_line = plan['invoice'], plan['fee_line']
        today = fields.Date.context_today(self)
        note = invoice.with_company(case.company_id)._reverse_moves([{
            'ref': _("Inspection fee adjustment %(case)s: %(invoice)s", case=case.name,
                     invoice=invoice.name),
            'invoice_date': today,
            'invoice_origin': invoice.invoice_origin,
            'warranty_inspection_case_id': case.id,
            'warranty_inspection_credit_limit': plan['fee_total'],
        }], cancel=False)
        note.invoice_line_ids.filtered(
            lambda aml: aml.display_type == 'product' and fee_line not in aml.sale_line_ids
        ).with_context(check_move_validity=False).unlink()
        if note.state != 'draft' or note.currency_id.compare_amounts(
                note.amount_total, plan['fee_total']) != 0:
            raise UserError(_("The credit note of %(invoice)s does not match the inspection fee "
                              "%(fee)s. Accounting should review the invoice.", invoice=invoice.name,
                              fee=format_amount(self.env, plan['fee_total'], note.currency_id)))
        invoice._message_log(body=_("Draft credit note created for the inspection fee of warranty "
                                    "case %s.", case.name))
        return note

    def _warranty_inspection_add_deduction(self, plan):
        """One negative line with the inspection line's tax. sudo: the checked action."""
        case = self.sudo()
        fee_line, repair = plan['fee_line'], plan['repair']
        product = case.helpdesk_ticket_id.team_id.warranty_inspection_deduction_product_id
        return self.env['sale.order.line'].sudo().with_company(case.company_id).create({
            'order_id': repair.id,
            'product_id': product.id,
            'name': _("Inspection fee deduction (%s)", plan['order'].name),
            'product_uom_qty': 1.0,
            'price_unit': -fee_line.price_subtotal,
            'discount': 0.0,
            'tax_id': [(6, 0, fee_line.tax_id.ids)],
            'warranty_case_id': case.id,
            'warranty_inspection_deduction_case_id': case.id,
        })

    def action_apply_inspection_fee_adjustment(self):
        self.ensure_one()
        self.check_access('read')
        if not (self._warranty_inspection_billing_user()
                or self._warranty_inspection_named_approver()):
            raise AccessError(_("Only Billing users and named Cost Approvers can apply an "
                                "inspection fee adjustment."))
        # Two users on the same case: the second one waits, then finds the adjustment.
        self.env.cr.execute("SELECT id FROM warranty_case WHERE id = %s FOR UPDATE", (self.id,))
        self.env.invalidate_all()
        plan = self._warranty_inspection_adjustment_plan()
        if plan['route'] == 'credit':
            document = self._warranty_inspection_create_credit_note(plan)
            text = _("Draft credit note created from inspection invoice %s; Accounting posts and "
                     "reconciles it.", plan['invoice'].name)
        else:
            document = self._warranty_inspection_add_deduction(plan)
            text = _("Deduction line added to repair quotation %s.", plan['repair'].name)
        self.sudo()._message_log(body=Markup('<p><b>%s</b></p><p>%s</p>') % (
            _("Inspection fee adjustment of %(amount)s by %(user)s.",
              amount=format_amount(self.env, plan['fee_total'], plan['fee_line'].currency_id),
              user=self.env.user.name), text))
        self.invalidate_recordset()
        record = document.order_id if plan['route'] == 'quotation' else document
        # A named approver may have no Sales or Accounting rights: the status shows on the case.
        if not record.with_env(self.env).has_access('read'):
            return True
        return self._warranty_inspection_open(record)

    def _warranty_inspection_open(self, record):
        record = record.with_env(self.env)
        record.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': record._name, 'res_id': record.id,
                'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current'}

    def action_open_inspection_fee_adjustment(self):
        """The standard document, with the user's own access rights."""
        self.ensure_one()
        self.check_access('read')
        notes, lines = self._warranty_inspection_effective()
        if not notes and not lines:
            raise UserError(_("Warranty case %s has no inspection fee adjustment.", self.name))
        return self._warranty_inspection_open(notes[:1] or lines[:1].order_id)

    def write(self, vals):
        if not self.env.su and {'warranty_inspection_credit_note_ids',
                                'warranty_inspection_deduction_line_ids'} & set(vals):
            raise UserError(_("The inspection fee adjustment is set by its action."))
        return super().write(vals)

    def _warranty_check_decline_repair(self):
        inspection = super()._warranty_check_decline_repair()
        notes = self._warranty_inspection_effective()[0]
        if notes:
            raise UserError(_("Warranty case %(case)s has the inspection fee credit note "
                              "%(note)s: a declined repair keeps the fee, so Accounting must "
                              "remove it first.", case=self.name, note=notes[:1].display_name))
        return inspection


class AccountMove(models.Model):
    _inherit = 'account.move'

    warranty_inspection_case_id = fields.Many2one(
        'warranty.case', string='Inspection Fee Case', readonly=True, copy=False,
        index='btree_not_null', ondelete='restrict')
    warranty_inspection_credit_limit = fields.Monetary(
        string='Inspection Fee Credit Limit', readonly=True, copy=False,
        help="The inspection fee this credit note may credit.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(INSPECTION_MOVE_FIELDS & set(vals) for vals in vals_list):
            raise UserError(_("The inspection fee credit note is created from the warranty case."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and INSPECTION_MOVE_FIELDS & set(vals):
            raise UserError(_("The inspection fee link of a credit note cannot be changed."))
        return super().write(vals)

    def _post(self, soft=True):
        for move in self.filtered('warranty_inspection_case_id'):
            if move.currency_id.compare_amounts(move.amount_total,
                                                move.warranty_inspection_credit_limit) > 0:
                raise UserError(_("Credit note of warranty case %(case)s is above the inspection "
                                  "fee %(fee)s.", case=move.warranty_inspection_case_id.sudo().name,
                                  fee=format_amount(self.env, move.warranty_inspection_credit_limit,
                                                    move.currency_id)))
        # A new invoice of a credited fee would charge it again. The original invoice and a
        # standard reversal of the credit note are not new charges.
        for move in self.filtered(lambda move: move.move_type == 'out_invoice'
                                  and not move.reversed_entry_id):
            lines = move.sudo().invoice_line_ids.sale_line_ids.filtered(
                lambda line: line._warranty_inspection_fee_credited(move))
            if lines:
                raise UserError(_("The inspection fee of order %s has a credit note, so it cannot "
                                  "be invoiced again. Accounting should remove this line.",
                                  lines[:1].order_id.name))
        return super()._post(soft=soft)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_copiable_order_lines(self):
        """A duplicated quotation does not carry the deduction: the case keeps one adjustment."""
        return super()._get_copiable_order_lines().filtered(
            lambda line: not line.warranty_inspection_deduction_case_id)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    warranty_inspection_deduction_case_id = fields.Many2one(
        'warranty.case', string='Inspection Deduction of Case', readonly=True, copy=False,
        index='btree_not_null', ondelete='set null')

    def _warranty_inspection_fee_credited(self, invoice=None):
        """The inspection fee line with a credit note that still gives the benefit. `invoice`: the
        invoice being checked, which is fine if it is the one that was credited. sudo: read."""
        self.ensure_one()
        line = self.sudo()
        if line.order_id.warranty_chargeable_purpose != 'inspection' or not line.warranty_case_id \
                or line.display_type or line.is_downpayment or line.warranty_excluded_item_id:
            return False
        notes = line.warranty_case_id._warranty_inspection_effective()[0]
        credited = notes.reversed_entry_id
        return line in credited.invoice_line_ids.sale_line_ids \
            and not (invoice and invoice in credited)

    @api.depends('warranty_case_id.warranty_inspection_credit_note_ids.state',
                 'warranty_case_id.warranty_inspection_credit_note_ids.reversal_move_ids.state')
    def _compute_qty_to_invoice(self):
        """A credited inspection fee is finished: standard Odoo would show it as to invoice again,
        and invoicing it would charge the fee a second time."""
        super()._compute_qty_to_invoice()
        for line in self.filtered('warranty_case_id'):
            if line._warranty_inspection_fee_credited():
                line.qty_to_invoice = 0.0

    def write(self, vals):
        """The deduction stays at the fee: it can be removed and applied again, not changed."""
        if not self.env.su and DEDUCTION_LINE_FIELDS & set(vals) \
                and self.filtered('warranty_inspection_deduction_case_id'):
            raise UserError(_("The inspection fee deduction line cannot be changed. Delete it and "
                              "apply the adjustment again."))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any('warranty_inspection_deduction_case_id' in vals
                                   for vals in vals_list):
            raise UserError(_("The inspection fee deduction is added from the warranty case."))
        return super().create(vals_list)
