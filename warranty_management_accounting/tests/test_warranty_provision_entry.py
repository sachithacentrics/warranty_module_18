from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, RedirectWarning, UserError
from odoo.tests import TransactionCase, tagged

from .test_warranty_cost_lines import _SavepointMixin


@tagged('post_install', '-at_install', 'warranty_cost')
class TestWarrantyProvisionEntry(_SavepointMixin, TransactionCase):
    """Part 8.6: one draft provision entry per warranty sale line of a posted invoice."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Provision Entry Co', 'warranty_scope_mode': 'warranty_only',
            'default_warranty_basis': 'period', 'default_start_criterion': 'delivery',
            'default_card_grouping_mode': 'per_so', 'default_warranty_duration': 12,
            'default_warranty_duration_unit': 'months'})
        cls.other = cls.env['res.company'].create({'name': 'Provision Entry Co B'})
        both = cls.company | cls.other
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=both.ids,
                                       tracking_disable=True))
        cls.company = cls.company.with_env(cls.env)
        cls.other = cls.other.with_env(cls.env)
        cls.expense = cls._account(cls.company, 'WPE01', 'expense')
        cls.provision = cls._account(cls.company, 'WPL01', 'liability_current')
        cls.income = cls._account(cls.company, 'WPI01', 'income')
        cls.receivable = cls._account(cls.company, 'WPR01', 'asset_receivable')
        cls.misc = cls.env['account.journal'].create({
            'name': 'Warranty', 'code': 'WPV', 'type': 'general', 'company_id': cls.company.id})
        cls.sales = cls.env['account.journal'].create({
            'name': 'Warranty Sales', 'code': 'WPS', 'type': 'sale', 'company_id': cls.company.id,
            'default_account_id': cls.income.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Provision Customer'})
        cls.partner.with_company(cls.company).property_account_receivable_id = cls.receivable
        cls.parent = cls.env['product.category'].create({'name': 'Cooling'})
        cls.category = cls.env['product.category'].create({'name': 'AC', 'parent_id': cls.parent.id})
        cls.policy = cls.env['warranty.policy'].create({
            'name': 'Provision Policy', 'company_id': cls.company.id, 'warranty_duration': 12,
            'warranty_duration_unit': 'months'})
        cls.product = cls.env['product.product'].create({
            'name': 'Split AC', 'type': 'consu', 'categ_id': cls.category.id,
            'warranty_applicable': True, 'list_price': 1000})
        cls.plain = cls.env['product.product'].create({
            'name': 'Cable', 'type': 'consu', 'warranty_applicable': False, 'list_price': 100})
        cls.company.write({'warranty_accounting_journal_id': cls.misc.id,
                           'warranty_expense_account_id': cls.expense.id,
                           'warranty_provision_account_id': cls.provision.id})

    @classmethod
    def _account(cls, company, code, account_type):
        return cls.env['account.account'].with_company(company).create({
            'name': code, 'code': code, 'account_type': account_type,
            'company_ids': [(6, 0, company.ids)]})

    def _enable(self, method='percentage', **vals):
        self.company.write(dict({'warranty_provision_enabled': True,
                                 'warranty_provision_method': method,
                                 'warranty_provision_rate': 5,
                                 'warranty_provision_amount': 20}, **vals))

    def _invoice(self, product=None, quantity=1, price=1000, post=True, **vals):
        invoice = self.env['account.move'].with_company(self.company).create(dict({
            'move_type': 'out_invoice', 'partner_id': self.partner.id,
            'company_id': self.company.id, 'journal_id': self.sales.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'product_id': (product or self.product).id,
                                         'quantity': quantity, 'price_unit': price,
                                         'account_id': self.income.id, 'tax_ids': [(5, 0, 0)]})]},
            **vals))
        if post:
            invoice.action_post()
        return invoice

    def _entry(self, invoice):
        return invoice.warranty_provision_move_ids

    def _amount(self, invoice):
        return sum(self._entry(invoice).mapped('amount_total'))

    # ------------------------------------------------------------------ 1, 2, 8, 9, 10
    def test_01_disabled_creates_nothing(self):
        moves = self.env['account.move'].search_count([])
        invoice = self._invoice()
        self.assertFalse(self._entry(invoice))
        self.assertEqual(self.env['account.move'].search_count([]), moves + 1)

    def test_02_percentage_company_default_debits_and_credits(self):
        self._enable()
        invoice = self._invoice(quantity=2, price=1000)
        entry = self._entry(invoice)
        self.assertEqual(len(entry), 1)
        self.assertEqual((entry.state, entry.move_type, entry.journal_id, entry.company_id),
                         ('draft', 'entry', self.misc, self.company), 'Finance posts it')
        self.assertEqual(entry.date, invoice.date)
        debit = entry.line_ids.filtered('debit')
        credit = entry.line_ids.filtered('credit')
        self.assertEqual((debit.account_id, debit.debit), (self.expense, 100), '5% of 2,000')
        self.assertEqual((credit.account_id, credit.credit), (self.provision, 100))
        self.assertEqual((entry.warranty_provision_method, entry.warranty_provision_rate,
                          entry.warranty_provision_level), ('percentage', 5, 'company'))
        self.assertEqual(entry.warranty_provision_invoice_line_id, invoice.invoice_line_ids)
        self.assertIn(invoice.name, entry.ref)
        self.assertEqual(invoice.warranty_provision_move_count, 1)
        self.assertEqual(invoice.action_open_warranty_provision_entries()['res_id'], entry.id)
        self.assertEqual(entry.action_open_warranty_provision_invoice()['res_id'], invoice.id)
        entry.action_post()
        self.assertEqual(entry.state, 'posted')
        self.assertEqual((invoice.state, invoice.amount_total), ('posted', 2000), 'unchanged')

    def test_03_fixed_is_per_unit(self):
        self._enable('fixed')
        entry = self._entry(self._invoice(quantity=3, price=999))
        self.assertEqual((entry.amount_total, entry.warranty_provision_method,
                          entry.warranty_provision_unit_amount), (60, 'fixed', 20))

    def test_04_tax_is_not_in_the_base(self):
        self._enable()
        country = self.env.ref('base.us')
        group = self.env['account.tax.group'].create({'name': 'Provision Taxes',
                                                      'company_id': self.company.id,
                                                      'country_id': country.id})
        tax = self.env['account.tax'].create({'name': 'Provision Tax', 'amount': 15,
                                              'amount_type': 'percent', 'tax_group_id': group.id,
                                              'country_id': country.id,
                                              'company_id': self.company.id})
        invoice = self._invoice(post=False)
        invoice.invoice_line_ids.tax_ids = tax
        invoice.action_post()
        self.assertEqual(invoice.amount_total, 1150)
        self.assertEqual(self._amount(invoice), 50, '5% of the untaxed 1,000')

    # ------------------------------------------------------------------ 3 to 7: precedence
    def test_05_rule_levels(self):
        self._enable(warranty_provision_rate=5)
        self.category.warranty_policy_id = self.policy
        self.assertEqual(self._amount(self._invoice()), 50, 'company')
        self.policy.write({'warranty_provision_method': 'percentage', 'warranty_provision_rate': 4})
        entry = self._entry(self._invoice())
        self.assertEqual((entry.amount_total, entry.warranty_provision_level,
                          entry.warranty_provision_source), (40, 'policy', self.policy.display_name))
        self.parent.with_company(self.company).write({'warranty_provision_method': 'percentage',
                                                      'warranty_provision_rate': 3})
        self.assertEqual(self._amount(self._invoice()), 30, 'parent category')
        self.category.with_company(self.company).write({'warranty_provision_method': 'percentage',
                                                         'warranty_provision_rate': 2})
        entry = self._entry(self._invoice())
        self.assertEqual((entry.amount_total, entry.warranty_provision_level), (20, 'category'))
        template = self.product.product_tmpl_id.with_company(self.company)
        template.write({'warranty_provision_method': 'fixed', 'warranty_provision_amount': 7})
        entry = self._entry(self._invoice())
        self.assertEqual((entry.amount_total, entry.warranty_provision_level), (7, 'product'))
        template.warranty_provision_method = 'inherit'
        self.assertEqual(self._amount(self._invoice()), 20, 'Use Next Level')
        template.warranty_provision_method = 'none'
        self.assertFalse(self._entry(self._invoice()), 'No Provision')
        self.assertEqual(template.warranty_provision_method, 'none')

    def test_06_past_entries_keep_their_rule(self):
        self._enable()
        entry = self._entry(self._invoice())
        self.company.warranty_provision_rate = 9
        self.assertEqual((entry.amount_total, entry.warranty_provision_rate), (50, 5))
        self.assertEqual(self._amount(self._invoice()), 90)

    def test_07_only_warranty_sale_lines(self):
        self._enable()
        self.assertFalse(self._entry(self._invoice(product=self.plain)), 'not a warranty product')
        invoice = self._invoice(post=False)
        invoice.write({'invoice_line_ids': [(0, 0, {
            'product_id': self.plain.id, 'quantity': 1, 'price_unit': 100,
            'account_id': self.income.id, 'tax_ids': [(5, 0, 0)]})]})
        invoice.action_post()
        self.assertEqual(self._amount(invoice), 50, 'only the warranty line')
        order = self.env['sale.order'].with_company(self.company).create({
            'partner_id': self.partner.id, 'company_id': self.company.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1,
                                   'price_unit': 1000, 'tax_id': [(5, 0, 0)]})]})
        order.action_confirm()
        billed = self._invoice(post=False)
        billed.invoice_line_ids.sale_line_ids = order.order_line
        billed.action_post()
        self.assertEqual(self._amount(billed), 50, 'an ordinary sale')
        case = self.env['warranty.case'].search([], limit=1)
        if case:
            self.env.flush_all()
            self.env.cr.execute("UPDATE sale_order SET warranty_case_id = %s WHERE id = %s",
                                (case.id, order.id))
            self.env.invalidate_all()
            work = self._invoice(post=False)
            work.invoice_line_ids.sale_line_ids = order.order_line
            work.action_post()
            self.assertFalse(self._entry(work), 'chargeable work of a case is not a warranty sale')

    def test_08_pricelist_policy_is_the_selected_policy(self):
        self._enable()
        self.policy.write({'warranty_provision_method': 'percentage', 'warranty_provision_rate': 8})
        pricelist = self.env['product.pricelist'].create({
            'name': 'Warranty List', 'company_id': self.company.id, 'warranty_applicable': True,
            'warranty_policy_id': self.policy.id})
        order = self.env['sale.order'].with_company(self.company).create({
            'partner_id': self.partner.id, 'company_id': self.company.id,
            'pricelist_id': pricelist.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1,
                                   'price_unit': 1000, 'tax_id': [(5, 0, 0)]})]})
        order.action_confirm()
        invoice = self._invoice(post=False)
        invoice.invoice_line_ids.sale_line_ids = order.order_line
        invoice.action_post()
        entry = self._entry(invoice)
        self.assertEqual((entry.amount_total, entry.warranty_provision_level), (80, 'policy'))

    # ------------------------------------------------------------------ 11, 12: duplicates, source
    def test_09_no_duplicate_on_repeated_triggers(self):
        self._enable()
        invoice = self._invoice()
        entry = self._entry(invoice)
        invoice._warranty_create_provision_entries()
        invoice.invalidate_recordset()
        self.assertEqual(self._entry(invoice), entry)
        with self.env.cr.savepoint(), self.assertRaises(Exception):
            self.env['account.move'].create(
                invoice._warranty_provision_entry_vals(
                    invoice.invoice_line_ids, {'method': 'fixed', 'rate': 0, 'amount': 1,
                                               'level': 'company', 'source': 'x'}, 1.0))
            self.env.flush_all()
        self.assertEqual(self.env['account.move'].search_count(
            [('warranty_provision_invoice_id', '=', invoice.id)]), 1)

    def test_10_draft_and_cancelled_invoices(self):
        self._enable()
        draft = self._invoice(post=False)
        self.assertFalse(self._entry(draft), 'a draft invoice gives no provision')
        draft.button_cancel()
        self.assertFalse(self._entry(draft), 'a cancelled invoice gives no provision')
        invoice = self._invoice()
        self.assertEqual(len(self._entry(invoice)), 1)
        invoice.button_draft()
        invoice.invalidate_recordset()
        self.assertFalse(self._entry(invoice), 'the draft provision goes with the invoice')
        invoice.action_post()
        invoice.invalidate_recordset()
        self.assertEqual(len(self._entry(invoice)), 1, 'one again after posting')

    def test_11_posted_provision_is_never_changed(self):
        self._enable()
        invoice = self._invoice()
        entry = self._entry(invoice)
        entry.action_post()
        invoice.button_draft()
        self.assertEqual((entry.state, entry.amount_total), ('posted', 50), 'no automatic reversal')
        self.assertTrue(invoice.message_ids.filtered(lambda m: 'Finance should review' in m.body))
        invoice.action_post()
        invoice.invalidate_recordset()
        self.assertEqual(self._entry(invoice), entry, 'no second provision')

    # ------------------------------------------------------------------ 13: controls
    def test_13_other_company_and_foreign_currency(self):
        self._enable()
        self.assertFalse(self.other.warranty_provision_enabled)
        receivable = self._account(self.other, 'WPR02', 'asset_receivable')
        self.partner.with_company(self.other).property_account_receivable_id = receivable
        income = self._account(self.other, 'WPI02', 'income')
        journal = self.env['account.journal'].create({
            'name': 'Sales B', 'code': 'WPB', 'type': 'sale', 'company_id': self.other.id,
            'default_account_id': income.id})
        foreign = self.env['account.move'].with_company(self.other).create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id, 'company_id': self.other.id,
            'journal_id': journal.id, 'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'product_id': self.product.id, 'quantity': 1,
                                         'price_unit': 1000, 'account_id': income.id,
                                         'tax_ids': [(5, 0, 0)]})]})
        foreign.action_post()
        self.assertFalse(self._entry(foreign), 'that company has provision off')
        currency = self.env['res.currency'].with_context(active_test=False).search(
            [('id', '!=', self.company.currency_id.id)], limit=1)
        currency.active = True
        self.env['res.currency.rate'].create({'currency_id': currency.id, 'rate': 2.0,
                                              'name': fields.Date.today(),
                                              'company_id': self.company.id})
        invoice = self._invoice(price=1000, currency_id=currency.id)
        entry = self._entry(invoice)
        self.assertEqual(entry.currency_id, self.company.currency_id)
        self.assertEqual(entry.amount_total, 25, '5% of 500 in company currency')
        self.assertEqual(entry.company_id, self.company)

    def test_14_access_and_links_are_protected(self):
        self._enable()
        billing = self.env['res.users'].create({
            'name': 'Provision Billing', 'login': 'provision_billing',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('account.group_account_invoice')).ids)]})
        invoice = self._invoice(post=False).with_user(billing).with_context(
            allowed_company_ids=self.company.ids)
        invoice.action_post()
        entry = invoice.sudo().warranty_provision_move_ids.with_user(billing)
        self.assertEqual(entry.sudo().state, 'draft', 'posting the invoice does not post it')
        for vals in ({'warranty_provision_invoice_id': False},
                     {'warranty_provision_invoice_line_id': False},
                     {'warranty_provision_rate': 1}):
            with self.assertRaisesRegex(UserError, 'cannot be changed'):
                entry.write(vals)
        with self.assertRaisesRegex(UserError, 'created when the invoice is posted'):
            self.env['account.move'].with_user(billing).create(
                {'move_type': 'entry', 'warranty_provision_invoice_id': invoice.id})

    def test_15_a_problem_never_stops_the_invoice(self):
        self._enable()
        with patch.object(type(self.env['account.move']), '_warranty_provision_line_values',
                          side_effect=UserError('Accounting problem')):
            invoice = self._invoice()
        self.assertEqual(invoice.state, 'posted')
        self.assertFalse(self._entry(invoice))
        self.assertTrue(invoice.message_ids.filtered(lambda m: 'could not be created' in m.body))

    # ------------------------------------------------------------------ 14, 15
    def test_16_cost_totals_unchanged_and_nothing_posted(self):
        self._enable()
        posted = self.env['account.move'].search_count([('state', '=', 'posted')])
        layers = self.env['stock.valuation.layer'].search_count([])
        self._invoice()
        self.assertEqual(self.env['account.move'].search_count([('state', '=', 'posted')]),
                         posted + 1, 'only the invoice')
        self.assertEqual(self.env['stock.valuation.layer'].search_count([]), layers)
        self.assertFalse(self.env['warranty.cost.line'].search(
            [('case_id.company_id', '=', self.company.id)]), 'no operational cost is created')
        self.assertFalse(self.env['warranty.cost.report']._fields.get('warranty_provision_method'))

    # ------------------------------------------------------------------ R1: reversals
    def _posted_provision(self, **vals):
        self._enable()
        invoice = self._invoice(**vals)
        entry = invoice.warranty_provision_move_ids
        entry.action_post()
        return invoice, entry

    def _refund(self, invoice, price=None, post=True, quantity=None):
        refund = invoice._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=False)
        if price is not None:
            refund.invoice_line_ids.price_unit = price
        if quantity is not None:
            refund.invoice_line_ids.quantity = quantity
        if post:
            refund.action_post()
        self.env.invalidate_all()
        return refund

    def _reversals(self, entry):
        entry.invalidate_recordset()
        return entry.reversal_move_ids

    def test_18_full_credit_note_gives_one_linked_draft_reversal(self):
        invoice, entry = self._posted_provision()
        posted = self.env['account.move'].search_count([('state', '=', 'posted')])
        refund = invoice._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=True)
        self.assertEqual(refund.state, 'posted')
        reversal = self._reversals(entry)
        self.assertEqual(len(reversal), 1)
        self.assertEqual((reversal.state, reversal.move_type, reversal.reversed_entry_id,
                          reversal.warranty_provision_invoice_id,
                          reversal.warranty_provision_refund_id),
                         ('draft', 'entry', entry, invoice, refund))
        self.assertEqual(reversal.date, refund.date)
        self.assertEqual(reversal.journal_id, entry.journal_id)
        debit = reversal.line_ids.filtered('debit')
        credit = reversal.line_ids.filtered('credit')
        self.assertEqual((debit.account_id, debit.debit), (self.provision, 50))
        self.assertEqual((credit.account_id, credit.credit), (self.expense, 50))
        self.assertEqual((entry.state, entry.amount_total), ('posted', 50), 'the original stays')
        self.assertEqual(self.env['account.move'].search_count([('state', '=', 'posted')]),
                         posted + 1, 'only the credit note is posted')
        self.assertFalse(entry.line_ids.filtered('reconciled'), 'nothing reconciled')
        self.assertIn(reversal, invoice.warranty_provision_move_ids)

    def test_19_partial_and_several_credit_notes(self):
        invoice, entry = self._posted_provision(quantity=2, price=1000)
        self.assertEqual(entry.amount_total, 100)
        first = self._refund(invoice, price=500, quantity=1)
        reversal = self._reversals(entry)
        self.assertEqual((reversal.amount_total, reversal.warranty_provision_refund_id),
                         (25, first), '500 of 2,000')
        reversal.action_post()
        second = self._refund(invoice, price=500, quantity=1)
        reversals = self._reversals(entry)
        self.assertEqual(sorted(reversals.mapped('amount_total')), [25, 25])
        self.assertEqual(reversals.filtered(lambda m: m.state == 'draft'
                                            ).warranty_provision_refund_id, second)
        reversals.filtered(lambda m: m.state == 'draft').action_post()
        self._refund(invoice, price=1000, quantity=1)
        reversals = self._reversals(entry)
        self.assertEqual(sum(reversals.mapped('amount_total')), 100)
        # Refunding beyond the invoice never goes beyond the provision.
        self._refund(invoice, price=5000, quantity=1)
        self.assertEqual(sum(self._reversals(entry).mapped('amount_total')), 100, 'capped')

    def test_20_repeat_gives_no_duplicate(self):
        invoice, entry = self._posted_provision()
        self._refund(invoice, price=400)
        reversal = self._reversals(entry)
        self.assertEqual(reversal.amount_total, 20)
        invoice._warranty_provision_sync_reversals()
        invoice._warranty_provision_sync_reversals()
        self.assertEqual(self._reversals(entry), reversal)

    def test_21_unrelated_credit_notes_change_nothing(self):
        invoice, entry = self._posted_provision()
        unlinked = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_refund', 'partner_id': self.partner.id, 'company_id': self.company.id,
            'journal_id': self.sales.id, 'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'product_id': self.product.id, 'quantity': 1,
                                         'price_unit': 1000, 'account_id': self.income.id,
                                         'tax_ids': [(5, 0, 0)]})]})
        unlinked.action_post()
        self.assertFalse(self._reversals(entry), 'not linked to the invoice')
        other = self._invoice()
        self._refund(other)
        self.assertFalse(self._reversals(entry), 'a credit note of another invoice')
        # On a mixed invoice, a credit note of the other product does not affect the provision.
        mixed = self._invoice(post=False)
        mixed.write({'invoice_line_ids': [(0, 0, {
            'product_id': self.plain.id, 'quantity': 1, 'price_unit': 100,
            'account_id': self.income.id, 'tax_ids': [(5, 0, 0)]})]})
        mixed.action_post()
        provision = mixed.warranty_provision_move_ids
        provision.action_post()
        refund = mixed._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=False)
        refund.invoice_line_ids.filtered(lambda l: l.product_id == self.product).unlink()
        refund.action_post()
        self.assertFalse(self._reversals(provision))

    def test_22_cancelled_invoice_reverses_what_remains(self):
        invoice, entry = self._posted_provision()
        self._refund(invoice, price=200)
        self._reversals(entry).action_post()
        invoice.button_draft()
        self.assertEqual(sum(self._reversals(entry).mapped('amount_total')), 10, 'reset alone: none')
        invoice.button_cancel()
        reversals = self._reversals(entry)
        self.assertEqual(sum(reversals.mapped('amount_total')), 50, 'the remaining 40')
        new = reversals.filtered(lambda m: m.state == 'draft')
        self.assertEqual(new.amount_total, 40)
        self.assertFalse(new.warranty_provision_refund_id)

    def test_23_draft_provision_catches_up_when_posted(self):
        self._enable()
        invoice = self._invoice()
        entry = invoice.warranty_provision_move_ids
        self._refund(invoice, price=500)
        self.assertFalse(self._reversals(entry), 'only a posted provision is reversed')
        entry.action_post()
        self.assertEqual(self._reversals(entry).amount_total, 25)

    def test_24_credit_note_taken_back(self):
        invoice, entry = self._posted_provision()
        refund = self._refund(invoice, price=500)
        self.assertEqual(self._reversals(entry).amount_total, 25)
        refund.button_draft()
        self.assertFalse(self._reversals(entry), 'its draft reversal goes')
        refund.action_post()
        reversal = self._reversals(entry)
        self.assertEqual(reversal.amount_total, 25)
        reversal.action_post()
        refund.button_draft()
        self.assertEqual((self._reversals(entry), reversal.state), (reversal, 'posted'),
                         'a posted reversal stays, for Finance')
        self.assertTrue(refund.message_ids.filtered(lambda m: 'Finance should review' in m.body))

    def test_25_excess_reversal_is_refused_at_posting(self):
        invoice, entry = self._posted_provision()
        self._refund(invoice, price=500)
        reversal = self._reversals(entry)
        reversal.write({'line_ids': [
            (1, reversal.line_ids.filtered('debit').id, {'debit': 60}),
            (1, reversal.line_ids.filtered('credit').id, {'credit': 60})]})
        with self.assertRaisesRegex(UserError, 'above what remains'):
            reversal.action_post()
        self.assertEqual(reversal.state, 'draft')

    def test_26_reversal_respects_lock_dates_and_links(self):
        invoice, entry = self._posted_provision()
        self._refund(invoice, price=500)
        reversal = self._reversals(entry)
        finance = self.env['res.users'].create({
            'name': 'Reversal Finance', 'login': 'reversal_finance',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('account.group_account_manager')).ids)]})
        with self.assertRaisesRegex(UserError, 'cannot be changed'):
            reversal.with_user(finance).write({'warranty_provision_refund_id': False})
        self.company.sudo().fiscalyear_lock_date = fields.Date.today()
        self.env.invalidate_all()
        with self.assertRaisesRegex(UserError, 'prior to and inclusive of'):
            reversal.with_user(finance).with_context(
                allowed_company_ids=self.company.ids).action_post()
        self.assertEqual(reversal.state, 'draft')

    def test_27_foreign_currency_credit_note(self):
        currency = self.env['res.currency'].with_context(active_test=False).search(
            [('id', '!=', self.company.currency_id.id)], limit=1)
        currency.active = True
        self.env['res.currency.rate'].create({'currency_id': currency.id, 'rate': 2.0,
                                              'name': fields.Date.today(),
                                              'company_id': self.company.id})
        invoice, entry = self._posted_provision(price=1000, currency_id=currency.id)
        self.assertEqual(entry.amount_total, 25)
        self._refund(invoice, price=500)
        reversal = self._reversals(entry)
        self.assertEqual((reversal.amount_total, reversal.currency_id),
                         (12.5, self.company.currency_id))

    # ------------------------------------------------------------------ reserve report
    def _report(self, user=None):
        report = self.env['warranty.reserve.report'].with_user(user or self.env.user).with_context(
            allowed_company_ids=self.company.ids)
        report.action_open_warranty_reserve_report()
        return report.search([('company_id', '=', self.company.id)])

    def _gl_balance(self):
        lines = self.env['account.move.line'].search([('account_id', '=', self.provision.id),
                                                      ('parent_state', '=', 'posted')])
        return sum(lines.mapped('credit')) - sum(lines.mapped('debit'))

    def _manual(self, amount, movement=False):
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': 'entry', 'company_id': self.company.id, 'journal_id': self.misc.id,
            'date': fields.Date.today(), 'warranty_reserve_movement': movement,
            'line_ids': [(0, 0, {'account_id': self.provision.id, 'debit': amount}),
                         (0, 0, {'account_id': self.expense.id, 'credit': amount})]})
        move.action_post()
        return move

    def test_28_report_separates_every_movement_and_matches_the_ledger(self):
        invoice, entry = self._posted_provision(quantity=2, price=1000)
        self._invoice()  # A second provision stays draft.
        self._refund(invoice, price=400, quantity=1)
        self._reversals(entry).action_post()
        self._refund(invoice, price=200, quantity=1)  # This reversal stays draft.
        self._manual(5, 'utilization')
        self._manual(3, 'release')
        self._manual(2)
        rows = self._report()
        posted = rows.filtered(lambda row: row.move_state == 'posted')
        self.assertEqual(sum(posted.mapped('provision_amount')), 100)
        self.assertEqual(sum(posted.mapped('reversal_amount')), 20, '400 of 2,000')
        self.assertEqual(sum(posted.mapped('utilization_amount')), 5)
        self.assertEqual(sum(posted.mapped('release_amount')), 3)
        self.assertEqual(sum(posted.mapped('other_amount')), 2, 'unclassified, not guessed')
        reserve = sum(rows.mapped('reserve_amount'))
        self.assertEqual(reserve, 100 - 20 - 5 - 3 - 2)
        self.assertEqual(reserve, self._gl_balance(), 'equals the posted balance of the account')
        self.assertEqual(sum(rows.mapped('draft_amount')), 50 - 10, 'drafts are shown, not counted')
        types = set(rows.mapped('movement_type'))
        self.assertLessEqual({'provision', 'reversal', 'utilization', 'release', 'other'}, types)
        row = rows.filtered(lambda r: r.movement_type == 'provision' and r.move_id == entry)
        self.assertEqual((row.invoice_id, row.product_id, row.category_id),
                         (invoice, self.product, self.category))

    def test_29_report_invents_no_utilization_and_filters(self):
        self.category.warranty_policy_id = self.policy
        self._posted_provision()
        rows = self._report()
        self.assertFalse(sum(rows.mapped('utilization_amount')))
        self.assertFalse(sum(rows.mapped('release_amount')))
        Report = self.env['warranty.reserve.report'].with_context(
            allowed_company_ids=self.company.ids)
        self.assertEqual(Report.search([('id', 'in', rows.ids), ('policy_id', '=', self.policy.id)]),
                         rows.filtered('move_id'))
        self.assertEqual(Report.search([('id', 'in', rows.ids),
                                        ('category_id', '=', self.category.id)]),
                         rows.filtered('move_id'))
        today = fields.Date.today()
        self.assertFalse(Report.search([('id', 'in', rows.ids),
                                        ('date', '<', fields.Date.subtract(today, days=400))]))

    def test_30_report_read_only_and_access(self):
        self._posted_provision()
        tech = self.env['res.users'].create({
            'name': 'Reserve Tech', 'login': 'reserve_tech', 'company_id': self.company.id,
            'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('industry_fsm.group_fsm_user')).ids)]})
        with self.assertRaises(AccessError):
            self.env['warranty.reserve.report'].with_user(tech).action_open_warranty_reserve_report()
        reader = self.env['res.users'].create({
            'name': 'Reserve Reader', 'login': 'reserve_reader', 'company_id': self.company.id,
            'company_ids': [(6, 0, (self.company | self.other).ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('account.group_account_readonly')).ids)]})
        rows = self._report(reader)
        self.assertTrue(rows)
        with self.assertRaises(AccessError):
            rows.write({'reserve_amount': 1})
        with self.assertRaises(AccessError):
            rows.unlink()
        Report = self.env['warranty.reserve.report'].with_user(reader).with_context(
            allowed_company_ids=self.other.ids)
        self.assertFalse(Report.search([('id', 'in', rows.ids)]), 'company isolation')
        moves = self.env['account.move'].search_count([])
        self._report(reader)
        self.assertEqual(self.env['account.move'].search_count([]), moves, 'the report posts nothing')

    def test_31_reserve_label_is_valid_only_on_a_reserve_debit(self):
        self._enable()
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': 'entry', 'company_id': self.company.id, 'journal_id': self.misc.id,
            'date': fields.Date.today(), 'warranty_reserve_movement': 'release',
            'line_ids': [(0, 0, {'account_id': self.expense.id, 'debit': 5}),
                         (0, 0, {'account_id': self.income.id, 'credit': 5})]})
        with self.assertRaisesRegex(UserError, 'debits the Warranty Provision account'):
            move.action_post()
        self.assertEqual(move.state, 'draft')

    def test_17_lock_date(self):
        self._enable()
        invoice = self._invoice()
        entry = self._entry(invoice)
        finance = self.env['res.users'].create({
            'name': 'Provision Finance', 'login': 'provision_finance',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('account.group_account_manager')).ids)]})
        with self.assertRaisesRegex(RedirectWarning, 'draft entries'):
            self.company.sudo().hard_lock_date = fields.Date.today()
        self.company.sudo().fiscalyear_lock_date = fields.Date.today()
        self.env.invalidate_all()
        date_before = entry.date
        with self.assertRaisesRegex(UserError, 'prior to and inclusive of'):
            entry.with_user(finance).with_context(allowed_company_ids=self.company.ids).action_post()
        entry.invalidate_recordset()
        self.assertEqual((entry.state, entry.date), ('draft', date_before),
                         'it stays draft, on its date')
