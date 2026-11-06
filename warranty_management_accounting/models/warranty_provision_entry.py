import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

# Part 8.6 (doc/part8_6_provision_entry_design.md, SRS 17, D1, D3, D5, D17): when a customer invoice
# posts, one DRAFT entry per warranty sale line, Dr Warranty Expense, Cr Warranty Provision. A posted
# credit note or cancellation of the invoice gives a linked, proportional, capped DRAFT reversal.
# Finance posts both. No utilization, reclassification (F1 B1, F4) or release (F8) is created here.
PROVISION_MOVE_FIELDS = {'warranty_provision_invoice_id', 'warranty_provision_invoice_line_id',
                         'warranty_provision_method', 'warranty_provision_rate',
                         'warranty_provision_unit_amount', 'warranty_provision_level',
                         'warranty_provision_source', 'warranty_provision_policy_id',
                         'warranty_provision_refund_id'}
RESERVE_MOVEMENTS = [('utilization', 'Reserve Utilization'), ('release', 'Reserve Release')]
PROVISION_METHODS = [('fixed', 'Fixed Amount per Unit'), ('percentage', 'Percentage of Sales Value')]
PROVISION_LEVELS = [('product', 'Product'), ('category', 'Product Category'),
                    ('policy', 'Warranty Policy'), ('company', 'Company Default')]


class AccountMove(models.Model):
    _inherit = 'account.move'

    warranty_provision_invoice_id = fields.Many2one(
        'account.move', string='Provision of Invoice', readonly=True, copy=False,
        index='btree_not_null', ondelete='restrict')
    warranty_provision_invoice_line_id = fields.Many2one(
        'account.move.line', string='Provision of Invoice Line', readonly=True, copy=False,
        index='btree_not_null', ondelete='set null')
    warranty_provision_method = fields.Selection(PROVISION_METHODS, string='Provision Method',
                                                 readonly=True, copy=False)
    warranty_provision_rate = fields.Float(string='Provision Percentage', digits=(16, 4),
                                           readonly=True, copy=False)
    warranty_provision_unit_amount = fields.Monetary(
        string='Provision Amount per Unit', readonly=True, copy=False,
        currency_field='company_currency_id')
    warranty_provision_level = fields.Selection(PROVISION_LEVELS, string='Provision Rule Level',
                                                readonly=True, copy=False)
    warranty_provision_source = fields.Char(string='Provision Rule Source', readonly=True,
                                            copy=False)
    warranty_provision_policy_id = fields.Many2one(
        'warranty.policy', string='Warranty Policy', readonly=True, copy=False,
        ondelete='set null', help="The warranty policy of the invoiced line, for reporting.")
    warranty_provision_refund_id = fields.Many2one(
        'account.move', string='Source Credit Note', readonly=True, copy=False,
        index='btree_not_null', ondelete='set null',
        help="The credit note this provision reversal comes from. Empty when the invoice was "
             "cancelled.")
    warranty_reserve_movement = fields.Selection(
        RESERVE_MOVEMENTS, string='Warranty Reserve Movement', copy=False, tracking=True,
        help="Set by Finance on a manual journal entry that debits the Warranty Provision account, "
             "so the Warranty Reserve report can show it as utilization or release.")
    warranty_provision_move_ids = fields.One2many('account.move', 'warranty_provision_invoice_id',
                                                  string='Warranty Provision Entries')
    warranty_provision_move_count = fields.Integer(compute='_compute_warranty_provision_links',
                                                   compute_sudo=True)
    warranty_provision_card_ids = fields.Many2many(
        'warranty.card', string='Warranty Cards', compute='_compute_warranty_provision_links',
        compute_sudo=True, help="Warranty cards of the sales order of the invoiced line.")

    def init(self):
        # Second line of defence: one active provision entry per invoice line.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS account_move_warranty_provision_line_uniq
                ON account_move (warranty_provision_invoice_line_id)
             WHERE warranty_provision_invoice_line_id IS NOT NULL AND state != 'cancel'""")

    @api.depends('warranty_provision_move_ids', 'warranty_provision_invoice_line_id')
    def _compute_warranty_provision_links(self):
        for move in self:
            move.warranty_provision_move_count = len(move.warranty_provision_move_ids)
            source = move.reversed_entry_id if move.reversed_entry_id else move
            orders = source.warranty_provision_invoice_line_id.sale_line_ids.order_id
            move.warranty_provision_card_ids = orders.warranty_card_ids

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(PROVISION_MOVE_FIELDS & set(vals) for vals in vals_list):
            raise UserError(_("Warranty provision entries are created when the invoice is posted."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and PROVISION_MOVE_FIELDS & set(vals):
            raise UserError(_("The warranty provision link of a journal entry cannot be changed."))
        if not self.env.su and 'warranty_reserve_movement' in vals \
                and self.filtered(lambda move: move.state != 'draft'):
            raise UserError(_("The warranty reserve movement is set before the entry is posted."))
        return super().write(vals)

    def _warranty_provision_lines(self):
        """The warranty sales of this invoice: product lines of warranty products. Work billed on a
        warranty case, parts, backup charges, AMC and down payments are not warranty sales."""
        self.ensure_one()

        def is_sale(line):
            if line.display_type != 'product' or not line.product_id.warranty_applicable:
                return False
            sale_lines = line.sale_line_ids
            orders = sale_lines.order_id
            return not (
                sale_lines.filtered('is_downpayment') or sale_lines.filtered('warranty_mrf_line_id')
                or orders.filtered('warranty_case_id')
                or orders.filtered('warranty_chargeable_purpose')
                or any(order._warranty_backup_charge_units() for order in orders)
                or ('amc_contract_id' in orders._fields and orders.filtered('amc_contract_id')))

        return self.invoice_line_ids.filtered(is_sale)

    def _warranty_provision_line_values(self, line):
        """(rule, amount) of one invoice line, in company currency. D1: the line's untaxed value;
        decision P1: quantity x fixed amount, in the product's unit of measure."""
        self.ensure_one()
        company = self.company_id
        product = line.product_id
        sale_line = line.sale_line_ids[:1]
        policy = sale_line._warranty_selected_policy()[0] if sale_line else None
        rule = company._warranty_provision_rule(product=product, policy=policy)
        rule['policy'] = policy or product.with_company(company).warranty_applied_policy_id
        if not rule['enabled'] or rule['method'] == 'none':
            return rule, 0.0
        quantity = line.product_uom_id._compute_quantity(line.quantity, product.uom_id) \
            if line.product_uom_id else line.quantity
        sales_value = -line.balance
        amount = quantity * rule['amount'] if rule['method'] == 'fixed' \
            else sales_value * rule['rate'] / 100.0
        return rule, company.currency_id.round(amount)

    def _warranty_provision_entry_vals(self, line, rule, amount):
        self.ensure_one()
        company = self.company_id
        name = _("Warranty provision: %(invoice)s, %(product)s", invoice=self.name,
                 product=line.product_id.display_name)
        partner = self.commercial_partner_id.id
        return {
            'move_type': 'entry',
            'company_id': company.id,
            'journal_id': company.warranty_accounting_journal_id.id,
            'date': self.date,
            'ref': name,
            'currency_id': company.currency_id.id,
            'warranty_provision_invoice_id': self.id,
            'warranty_provision_invoice_line_id': line.id,
            'warranty_provision_method': rule['method'],
            'warranty_provision_rate': rule['rate'] if rule['method'] == 'percentage' else 0.0,
            'warranty_provision_unit_amount': rule['amount'] if rule['method'] == 'fixed' else 0.0,
            'warranty_provision_level': rule['level'],
            'warranty_provision_source': rule['source'],
            'warranty_provision_policy_id': rule['policy'].id if rule.get('policy') else False,
            'line_ids': [
                (0, 0, {'name': name, 'partner_id': partner, 'debit': amount, 'credit': 0.0,
                        'account_id': company.warranty_expense_account_id.id}),
                (0, 0, {'name': name, 'partner_id': partner, 'debit': 0.0, 'credit': amount,
                        'account_id': company.warranty_provision_account_id.id}),
            ],
        }

    def _warranty_create_provision_entries(self):
        """Draft entries of posted customer invoices. A problem never stops the invoice: it is
        noted on the invoice for Finance. sudo: the checked result of posting an invoice."""
        for invoice in self.sudo():
            company = invoice.company_id
            if not company.warranty_provision_enabled:
                continue
            invoice = invoice.with_company(company)
            active = invoice.warranty_provision_move_ids.filtered(
                lambda move: move.state != 'cancel' and not move.reversed_entry_id)
            if active.filtered(lambda move: move.state == 'posted'):
                # Posted again after a reset: its posted provision stays, Finance reviews it.
                invoice._message_log(body=_(
                    "Invoice posted again: its posted warranty provision %s was not changed and no "
                    "new provision was created. Finance should review it.",
                    ', '.join(active.mapped('name'))))
                continue
            created = self.browse()
            try:
                with self.env.cr.savepoint():
                    for line in invoice._warranty_provision_lines():
                        if active.filtered(
                                lambda move: move.warranty_provision_invoice_line_id == line):
                            continue
                        rule, amount = invoice._warranty_provision_line_values(line)
                        if company.currency_id.compare_amounts(amount, 0.0) <= 0:
                            continue
                        created |= invoice.create(
                            invoice._warranty_provision_entry_vals(line, rule, amount))
            except (UserError, ValidationError, AccessError) as error:
                invoice._message_log(body=_(
                    "The warranty provision of this invoice could not be created. Finance should "
                    "check the Warranty Accounting settings. %s", error.args[0]))
                continue
            if created:
                invoice._message_log(body=_(
                    "%(count)s draft warranty provision entry(ies) created, total %(total)s. "
                    "Finance posts them.", count=len(created),
                    total=sum(created.mapped('amount_total_signed'))))

    def _warranty_provision_invoice_reset(self):
        """D5: an unposted provision goes with its invoice. A posted one is never changed here."""
        for invoice in self.sudo().filtered(lambda move: move.move_type == 'out_invoice'):
            moves = invoice.warranty_provision_move_ids.filtered(
                lambda move: not move.reversed_entry_id)
            drafts = moves.filtered(lambda move: move.state == 'draft')
            if drafts:
                drafts.unlink()
                invoice._message_log(body=_("The draft warranty provision of this invoice was "
                                            "removed, because the invoice is no longer posted."))
            posted = moves.exists().filtered(lambda move: move.state == 'posted')
            if posted:
                invoice._message_log(body=_(
                    "This invoice is no longer posted, but its warranty provision %s is posted "
                    "and stays as it is. Finance should review it.",
                    ', '.join(posted.mapped('name'))))

    def _warranty_provision_affected_ratio(self):
        """The share of this provision affected by the invoice's cancellation or its posted credit
        notes, 0 to 1. A credit note line has no link to one invoice line, so lines of the same
        product share it by value. Only credit notes linked to this invoice count."""
        self.ensure_one()
        invoice = self.warranty_provision_invoice_id
        if invoice.state == 'cancel':
            return 1.0
        refunds = invoice.reversal_move_ids.filtered(
            lambda move: move.move_type == 'out_refund' and move.state == 'posted')
        product = self.warranty_provision_invoice_line_id.product_id
        if product:
            def same(aml):
                return aml.display_type == 'product' and aml.product_id == product

            total = -sum(invoice.invoice_line_ids.filtered(same).mapped('balance'))
            refunded = sum(refunds.invoice_line_ids.filtered(same).mapped('balance'))
        else:
            total = abs(invoice.amount_untaxed_signed)
            refunded = sum(abs(move.amount_untaxed_signed) for move in refunds)
        return max(min(refunded / total, 1.0), 0.0) if total else 0.0

    def _warranty_provision_reversal_entry_vals(self, amount, refund):
        self.ensure_one()
        invoice = self.warranty_provision_invoice_id
        name = _("Reversal of warranty provision %(entry)s: %(origin)s", entry=self.name,
                 origin=refund.name if refund else _("invoice %s cancelled", invoice.name))
        lines = []
        for line in self.line_ids:
            lines.append((0, 0, {'name': name, 'partner_id': line.partner_id.id,
                                 'account_id': line.account_id.id,
                                 'debit': amount if line.credit else 0.0,
                                 'credit': amount if line.debit else 0.0}))
        return {
            'move_type': 'entry',
            'company_id': self.company_id.id,
            'journal_id': self.journal_id.id,
            'date': refund.date if refund else fields.Date.context_today(self),
            'ref': name,
            'currency_id': self.company_id.currency_id.id,
            'reversed_entry_id': self.id,
            'warranty_provision_invoice_id': invoice.id,
            'warranty_provision_refund_id': refund.id if refund else False,
            'warranty_provision_policy_id': self.warranty_provision_policy_id.id,
            'line_ids': lines,
        }

    def _warranty_provision_sync_reversals(self, refund=None):
        """R1: the draft reversal each posted provision of these invoices still needs. Cumulative:
        the target is the affected share of the provision minus every reversal already made, so
        repeats and several credit notes can't exceed it. A provision that is still draft gets its
        reversal when Finance posts it. sudo: the checked result of an accounting event."""
        for invoice in self.sudo():
            provisions = invoice.warranty_provision_move_ids.filtered(
                lambda move: move.state == 'posted' and not move.reversed_entry_id)
            for provision in provisions:
                provision = provision.with_company(provision.company_id)
                currency = provision.company_id.currency_id
                total = provision.amount_total
                target = currency.round(total * provision._warranty_provision_affected_ratio())
                drafts = provision.reversal_move_ids.filtered(lambda move: move.state == 'draft')
                made = provision._warranty_reversed_amount() + sum(drafts.mapped('amount_total'))
                amount = currency.round(min(target, total) - made)
                if currency.compare_amounts(amount, 0.0) <= 0:
                    continue
                last = refund or invoice.reversal_move_ids.filtered(
                    lambda move: move.move_type == 'out_refund' and move.state == 'posted'
                ).sorted('id')[-1:]
                if invoice.state == 'cancel':
                    last = self.browse()
                reversal = provision.create(
                    provision._warranty_provision_reversal_entry_vals(amount, last))
                note = _("Draft reversal of warranty provision %(entry)s created for %(amount)s. "
                         "Finance reviews and posts it.", entry=provision.name, amount=amount)
                invoice._message_log(body=note)
                provision._message_log(body=note)
                if reversal.warranty_provision_refund_id:
                    reversal.warranty_provision_refund_id._message_log(body=note)

    def _warranty_provision_refund_reset(self):
        """A credit note taken back: its draft reversal goes, a posted one stays for Finance."""
        for refund in self.sudo().filtered(lambda move: move.move_type == 'out_refund'):
            reversals = refund.search([('warranty_provision_refund_id', '=', refund.id)])
            reversals.filtered(lambda move: move.state == 'draft').unlink()
            posted = reversals.exists().filtered(lambda move: move.state == 'posted')
            if posted:
                refund._message_log(body=_(
                    "This credit note is no longer posted, but its provision reversal %s is "
                    "posted and stays as it is. Finance should review it.",
                    ', '.join(posted.mapped('name'))))
            refund.reversed_entry_id._warranty_provision_sync_reversals()

    def _warranty_provision_check_post(self):
        """Before posting: lock dates, no reversal above its provision, a valid reserve label."""
        # Standard posting does not recheck the lock dates of a draft entry: a provision is never
        # posted into a locked period on its old date. Finance changes the date of the draft.
        self.filtered('warranty_provision_invoice_id')._check_fiscal_lock_dates()
        for move in self.sudo().filtered('reversed_entry_id'):
            provision = move.reversed_entry_id
            if not provision.warranty_provision_invoice_id or provision.reversed_entry_id:
                continue
            currency = move.company_id.currency_id
            remaining = provision.amount_total - provision._warranty_reversed_amount()
            if currency.compare_amounts(move.amount_total, remaining) > 0:
                raise UserError(_("Reversal of warranty provision %(entry)s is above what remains "
                                  "of it (%(remaining)s).", entry=provision.name,
                                  remaining=remaining))
        for move in self.sudo().filtered('warranty_reserve_movement'):
            account = move.company_id.warranty_provision_account_id
            if move.warranty_provision_invoice_id or move.reversed_entry_id or not account \
                    or not move.line_ids.filtered(
                        lambda line: line.account_id == account and line.debit):
                raise UserError(_("A warranty reserve movement must be a manual entry that debits "
                                  "the Warranty Provision account."))

    def _post(self, soft=True):
        self._warranty_provision_check_post()
        posted = super()._post(soft=soft)
        posted.filtered(lambda move: move.move_type == 'out_invoice' and move.state == 'posted'
                        and not move.reversed_entry_id)._warranty_create_provision_entries()
        for refund in posted.filtered(lambda move: move.move_type == 'out_refund'
                                      and move.state == 'posted' and move.reversed_entry_id):
            refund.sudo().reversed_entry_id._warranty_provision_sync_reversals(refund.sudo())
        # A provision posted after its invoice was refunded or cancelled catches up.
        posted.sudo().filtered(
            lambda move: move.warranty_provision_invoice_id and not move.reversed_entry_id
        ).warranty_provision_invoice_id._warranty_provision_sync_reversals()
        return posted

    def button_draft(self):
        result = super().button_draft()
        self._warranty_provision_invoice_reset()
        self._warranty_provision_refund_reset()
        return result

    def button_cancel(self):
        result = super().button_cancel()
        self.filtered(lambda move: move.move_type == 'out_invoice' and move.state == 'cancel'
                      )._warranty_provision_sync_reversals()
        return result

    def action_open_warranty_provision_entries(self):
        self.ensure_one()
        moves = self.warranty_provision_move_ids
        action = {'type': 'ir.actions.act_window', 'name': _("Warranty Provision Entries"),
                  'res_model': 'account.move', 'view_mode': 'list,form',
                  'domain': [('id', 'in', moves.ids)], 'context': {'create': False}}
        if len(moves) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')], 'res_id': moves.id})
        return action

    def action_open_warranty_provision_invoice(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move',
                'res_id': self.warranty_provision_invoice_id.id, 'view_mode': 'form',
                'views': [(False, 'form')]}
