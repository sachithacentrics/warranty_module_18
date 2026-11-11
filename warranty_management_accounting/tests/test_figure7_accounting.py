from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.warranty_management_mrf.tests.common import WarrantyMrfCommon

from .test_warranty_cost_lines import _SavepointMixin


@tagged('post_install', '-at_install', 'warranty_cost', 'warranty_figure7')
class TestFigure7Accounting(_SavepointMixin, WarrantyMrfCommon):
    """Figure 7 / SRS 17 (doc/figure7_accounting_integration.md): covered spare parts follow
    standard Odoo stock accounting (manual valuation: no entry; automated valuation: Odoo's own
    stock entry on the Warranty Consumption location accounts); Finance applies posted warranty
    cost of a completed case against the reserve with a draft standard journal entry."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['account.account']

        def account(code, account_type, **extra):
            return Account.create(dict({'name': code, 'code': code, 'account_type': account_type,
                                        'company_ids': [(6, 0, cls.company.ids)]}, **extra))

        cls.expense = account('WEX7AC', 'expense', reconcile=True)
        cls.provision = account('WPR7AC', 'liability_current', reconcile=True)
        cls.recovery = account('WRC7AC', 'income_other')
        cls.other_cost = account('WOT7AC', 'expense')
        cls.stock_value = account('WSV7AC', 'asset_current')
        cls.stock_in = account('WSI7AC', 'asset_current')
        cls.stock_out = account('WSO7AC', 'asset_current')
        cls.journal = cls.env['account.journal'].search(
            [('company_id', '=', cls.company.id), ('type', '=', 'general')], limit=1)
        cls.stock_journal = cls.env['account.journal'].create({
            'name': 'F7 Inventory Valuation', 'code': 'F7SV', 'type': 'general',
            'company_id': cls.company.id})
        Category = cls.env['product.category']
        cls.parts = Category.create({'name': 'F7 Spare Parts'})
        cls.manual = Category.create({'name': 'F7 Manual Parts'})
        Partner = cls.env['res.partner']
        cls.manufacturer = Partner.create({'name': 'F7 Manufacturer', 'is_company': True})
        Product = cls.env['product.product']
        cls.filter = Product.create({
            'name': 'F7 Air Filter', 'is_storable': True, 'type': 'consu', 'standard_price': 500,
            'categ_id': cls.parts.id, 'warranty_vendor_claimable': True,
            'warranty_claim_partner_id': cls.manufacturer.id, 'warranty_vendor_warranty_months': 12})
        cls.valve = Product.create({'name': 'F7 Valve', 'is_storable': True, 'type': 'consu',
                                    'standard_price': 2000, 'categ_id': cls.parts.id})
        cls.coil = Product.create({'name': 'F7 Coil', 'is_storable': True, 'type': 'consu',
                                   'standard_price': 300, 'categ_id': cls.manual.id})
        cls.policy.covered_item_ids |= cls.env['warranty.coverage.item'].create([
            {'name': product.name, 'product_id': product.id}
            for product in (cls.filter, cls.valve, cls.coil)])
        cls.store = cls._user('f7a_store',
                              'material_purchase_requisitions.group_purchase_requisition_user')
        cls.store.groups_id |= cls.env.ref('stock.group_stock_user')
        cls.coordinator = cls._user('f7a_coordinator', 'helpdesk.group_helpdesk_user')
        cls.coordinator.groups_id |= cls.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        cls.claim_approver = cls._user('f7a_claim_approver')
        cls.finance = cls._user('f7a_finance', 'account.group_account_user')
        cls.billing = cls._user('f7a_billing', 'account.group_account_invoice')
        cls.editor = cls._user('f7a_editor', 'account.group_account_manager')
        cls.editor.groups_id |= cls.env.ref('base.group_system')
        cls.company.write({
            'warranty_mrf_approval_matrix': True,
            'warranty_mrf_dest_location_id': cls.default_tech_location.id,
            'warranty_worksheet_checklist_required': False,
            'warranty_vendor_claim_enabled': True,
            'warranty_claim_approver_ids': [(6, 0, cls.claim_approver.ids)],
            'warranty_claim_evidence_required': False,
            'warranty_claim_recovery_account_id': cls.recovery.id,
            'warranty_accounting_journal_id': cls.journal.id,
            'warranty_expense_account_id': cls.expense.id,
            'warranty_provision_account_id': cls.provision.id,
        })
        cls.env['warranty.mrf.approval.rule'].create({
            'name': 'All free (F7 accounting test)', 'company_id': cls.company.id,
            'no_approval': True})
        cls.today = fields.Date.context_today(cls.env.user)
        cls.stock = cls.warehouse.lot_stock_id
        cls.consumption = cls.company._warranty_mrf_consumption_location()
        cls.Lot = cls.env['stock.lot']
        cls.Move = cls.env['account.move']

    @classmethod
    def _entry(cls, debit, credit, amount, date=None):
        move = cls.env['account.move'].create({
            'move_type': 'entry', 'journal_id': cls.journal.id, 'company_id': cls.company.id,
            'date': date or cls.today,
            'line_ids': [(0, 0, {'name': 'Manual', 'account_id': debit.id, 'debit': amount}),
                         (0, 0, {'name': 'Manual', 'account_id': credit.id, 'credit': amount})]})
        move.action_post()
        return move

    # ------------------------------------------------------------------ helpers
    def _automate(self, location_accounts=True):
        """Finance's choice (never done by the module): automated valuation of the spare-parts
        category and, as policy, Warranty Expense on the Warranty Consumption location."""
        self.parts.with_company(self.company).write({
            'property_cost_method': 'standard', 'property_valuation': 'real_time',
            'property_stock_valuation_account_id': self.stock_value.id,
            'property_stock_account_input_categ_id': self.stock_in.id,
            'property_stock_account_output_categ_id': self.stock_out.id,
            'property_stock_journal': self.stock_journal.id})
        if location_accounts:
            self.consumption.write({'valuation_in_account_id': self.expense.id,
                                    'valuation_out_account_id': self.expense.id})

    def _mrf(self, lines, job=None):
        job = job or self._confirmed_job()
        action = job.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {
                'product_id': product.id, 'description': product.name, 'qty': qty,
                'uom': product.uom_id.id}) for product, qty in lines]})
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual(mrf.state, 'approve')
        return mrf

    def _line(self, mrf, product):
        return mrf.requisition_line_ids.filtered(lambda line: line.product_id == product)

    def _issued(self, lines, job=None):
        for product, qty in lines:
            self.env['stock.quant']._update_available_quantity(product, self.stock, qty)
        mrf = self._mrf(lines, job=job)
        mrf.with_user(self.store).action_warranty_fulfil()
        for picking in self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id),
                                                         ('state', 'not in', ('done', 'cancel'))]):
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.with_user(self.store).button_validate()
        return mrf

    def _use(self, mrf, product, qty):
        return mrf.with_user(self.tech)._warranty_record_usage(
            [(self._line(mrf, product), qty, self.Lot)])

    def _warranty_entries(self):
        return self.Move.search([('warranty_b2_kind', '!=', False),
                                 ('company_id', '=', self.company.id)])

    def _stock_entries(self, usage):
        return usage.move_ids.stock_valuation_layer_ids.account_move_id

    def _completed(self, case):
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_case SET state = 'completed' WHERE id = %s",
                            (case.id,))
        self.env.invalidate_all()

    # ------------------------------------------------------------------ standard stock accounting
    def test_01_manual_valuation_no_entry_cost_on_case(self):
        """Manual (periodic) valuation, as on UAT: no journal entry at issue or use, the actual
        cost comes from stock valuation; nothing custom is created; the removed setup is gone."""
        mrf = self._issued([(self.coil, 2)])
        usage = self._use(mrf, self.coil, 2)
        self.assertEqual(usage.move_ids.stock_valuation_layer_ids.value, -600, 'actual cost')
        self.assertFalse(self._stock_entries(usage), 'standard periodic: no entry')
        self.assertFalse(self._warranty_entries())
        case = mrf.warranty_case_id
        self.assertEqual((case.warranty_reserve_parts_amount,
                          case.warranty_reserve_eligible_amount), (0, 0))
        status = self.env['res.config.settings'].create({}).warranty_b2_readiness
        self.assertIn('Manual valuation (F7 Manual Parts)', status)
        self.assertIn('Reserve utilization: ready', status)
        for model, names in (
                ('res.company', ('warranty_b2_enabled', 'warranty_b2_start_date',
                                 'warranty_b2_opening_move_id', 'warranty_b2_opening_verified',
                                 'warranty_b2_unbilled_reviewed', 'warranty_b2_periodic_confirmed',
                                 'warranty_cost_recognition_account_id')),
                ('warranty.mrf.consumption', ('warranty_b2_state', 'warranty_b2_move_id')),
                ('res.config.settings', ('warranty_b2_enabled',
                                         'warranty_cost_recognition_account_id'))):
            for name in names:
                self.assertNotIn(name, self.env[model]._fields, name)
        self.assertNotIn('warranty.b2.verify.wizard', self.env)

    def test_02_automated_valuation_uses_standard_entries(self):
        """Automated valuation: Odoo posts the use Dr Warranty Expense (the location account) /
        Cr Stock Valuation and the reversal back; the issue transfer, the unused return and the
        Not Covered lines get no warranty entry; the module itself posts nothing."""
        self._automate()
        mrf = self._issued([(self.filter, 3)])
        self.assertFalse(self.Move.search([('stock_move_id.picking_id.custom_requisition_id',
                                            '=', mrf.id)]), 'internal issue: no entry')
        usage = self._use(mrf, self.filter, 2)
        entry = self._stock_entries(usage)
        self.assertEqual((len(entry), entry.state, entry.journal_id, entry.amount_total),
                         (1, 'posted', self.stock_journal, 1000))
        self.assertEqual(entry.line_ids.filtered('debit').account_id, self.expense)
        self.assertEqual(entry.line_ids.filtered('credit').account_id, self.stock_value)
        self.assertFalse(self._warranty_entries(), 'no custom entry, no duplicate')
        case = mrf.warranty_case_id
        self.assertEqual(case._warranty_reserve_figures()['parts'], 1000)
        line = self._line(mrf, self.filter)
        mrf.with_user(self.tech)._warranty_return_unused([(line, 1.0, self.Lot)])
        self.assertEqual(len(self.Move.search([('stock_move_id', 'in', self.env['stock.move'].search(
            [('warranty_consumption_id.requisition_id', '=', mrf.id)]).ids)])), 1,
            'unused return between internal locations: no entry')
        usage.with_user(self.coordinator)._warranty_reverse('Wrong job')
        back = self._stock_entries(usage) - entry
        self.assertEqual(back.line_ids.filtered('debit').account_id, self.stock_value)
        self.assertEqual(back.line_ids.filtered('credit').account_id, self.expense)
        self.assertEqual(case._warranty_reserve_figures()['parts'], 0, 'use minus reversal')
        status = self.company._warranty_accounting_status()
        self.assertIn('Automated valuation (F7 Spare Parts): Odoo posts each use', status)
        # Without the location accounts Odoo uses the category Stock Output: shown to Finance.
        self.consumption.write({'valuation_in_account_id': False,
                                'valuation_out_account_id': False})
        self.assertIn('has no Stock Valuation Accounts', self.company._warranty_accounting_status())

    # ------------------------------------------------------------------ reserve utilization
    def test_03_reserve_utilization_controlled_by_finance(self):
        self._automate()
        self._entry(self.expense, self.provision, 500)  # posted provision: reserve 500
        mrf = self._issued([(self.filter, 2)])
        self._use(mrf, self.filter, 2)
        case = mrf.warranty_case_id
        with self.assertRaisesRegex(UserError, 'completed or closed'):
            case.with_user(self.finance).action_warranty_reserve_utilization()
        self._completed(case)
        with self.assertRaisesRegex(AccessError, 'reserve utilization'):
            case.with_user(self.billing).action_warranty_reserve_utilization()
        self.assertEqual((case.warranty_reserve_parts_amount, case.warranty_reserve_eligible_amount,
                          case.warranty_reserve_available_amount), (1000, 1000, 500))
        action = case.with_user(self.finance).action_warranty_reserve_utilization()
        util = self.Move.browse(action['res_id'])
        self.assertEqual((util.state, util.amount_total, util.warranty_reserve_movement,
                          util.warranty_b2_kind, util.warranty_b2_case_id, util.journal_id),
                         ('draft', 500, 'utilization', 'utilization', case, self.journal))
        self.assertEqual(util.line_ids.filtered('debit').account_id, self.provision)
        self.assertEqual(util.line_ids.filtered('credit').account_id, self.expense)
        self.assertTrue(case.activity_ids.filtered(lambda a: 'shortfall' in (a.summary or '')))
        self.assertEqual(self.company._warranty_reserve_available(), 0, 'the draft is reserved')
        with self.assertRaisesRegex(UserError, 'already has a draft'):
            case.with_user(self.finance).action_warranty_reserve_utilization()
        # The posted reserve falls before Finance posts: posting is refused (recalculated).
        self._entry(self.provision, self.expense, 200)
        with self.assertRaisesRegex(UserError, 'available posted reserve'):
            util.with_user(self.finance).action_post()
        with self.assertRaisesRegex(AccessError, 'Bookkeepers or Administrators'):
            util.with_user(self.billing).action_post()
        util.with_user(self.finance).button_cancel()
        util = self.Move.browse(
            case.with_user(self.finance).action_warranty_reserve_utilization()['res_id'])
        self.assertEqual(util.amount_total, 300)
        util.with_user(self.finance).action_post()
        self.assertEqual((case.warranty_reserve_utilized_amount,
                          case.warranty_reserve_eligible_amount,
                          self.company._warranty_reserve_available()), (300, 700, 0))
        with self.assertRaisesRegex(UserError, 'Nothing to utilize'):
            case.with_user(self.finance).action_warranty_reserve_utilization()
        Report = self.env['warranty.reserve.report'].with_user(self.finance)
        Report.action_open_warranty_reserve_report()
        row = Report.search([('move_id', '=', util.id)])
        self.assertEqual((row.movement_type, row.case_id, row.utilization_amount),
                         ('utilization', case, 300))
        # Standard Reverse of the posted utilization (case reopened): Finance only, capped.
        reversal = util._reverse_moves([{'ref': 'Case reopened'}])
        with self.assertRaisesRegex(AccessError, 'Bookkeepers or Administrators'):
            reversal.with_user(self.billing).action_post()
        reversal.with_user(self.finance).action_post()
        self.assertEqual(case.warranty_reserve_utilized_amount, 0)

    def test_04_manual_valuation_nothing_to_utilize(self):
        """Manual valuation: parts cost is not in Warranty Expense, so it is not reclassified
        against the reserve (no duplicate expense); the message says why."""
        self._entry(self.expense, self.provision, 900)
        mrf = self._issued([(self.coil, 1)])
        self._use(mrf, self.coil, 1)
        case = mrf.warranty_case_id
        self._completed(case)
        with self.assertRaisesRegex(UserError, 'Only cost posted to Warranty Expense counts'):
            case.with_user(self.finance).action_warranty_reserve_utilization()
        self.assertFalse(self._warranty_entries())

    def test_05_eligibility_recovery_goodwill_and_subcontract(self):
        self._automate()
        self._entry(self.expense, self.provision, 10000)
        mrf = self._issued([(self.filter, 2), (self.valve, 1)])
        self._use(mrf, self.filter, 2)
        self._use(mrf, self.valve, 1)
        case = mrf.warranty_case_id
        self.assertEqual(case._warranty_reserve_figures()['eligible'], 3000)
        # Vendor recovery of the filter: posted vendor credit note allocated to the claim line.
        action = mrf.with_user(self.coordinator).action_create_vendor_claim()
        wizard = self.env[action['res_model']].with_user(self.coordinator).browse(
            action['res_id'])
        for row in wizard.line_ids:
            row.write({'selected': row.product_id == self.filter,
                       'qty': 2 if row.product_id == self.filter else 0})
        wizard.partner_id = False
        wizard._propose_partner()
        wizard.write({'failure_description': 'Failed'})
        claim = self.env['warranty.vendor.claim'].browse(wizard.action_apply()['res_id'])
        claim.with_user(self.coordinator).action_submit()
        claim.with_user(self.claim_approver).action_approve()
        claim.with_user(self.coordinator).action_mark_sent()
        claim.with_user(self.coordinator)._warranty_record_response(
            {claim.line_ids: (600, 'ok')}, reference='V-F7')
        note = self.Move.browse(
            claim.with_user(self.billing).action_create_credit_note()['res_id'])
        self.assertEqual((note.move_type, note.state, note.invoice_line_ids.account_id),
                         ('in_refund', 'draft', self.recovery), 'standard vendor credit note')
        self.assertEqual(case._warranty_reserve_figures()['eligible'], 3000, 'draft note')
        note.invoice_date = self.today
        note.with_user(self.billing).action_post()
        self.env.invalidate_all()
        figures = case._warranty_reserve_figures()
        self.assertEqual((figures['recovered'], figures['eligible']), (600, 2400))
        # Goodwill: separately identified, reserve-ineligible unless the policy allows it.
        self.env.flush_all()
        self.env.cr.execute("UPDATE material_purchase_requisition_line SET goodwill = true "
                            "WHERE id = %s", (self._line(mrf, self.valve).id,))
        self.env.invalidate_all()
        figures = case._warranty_reserve_figures()
        self.assertEqual((figures['goodwill'], figures['eligible']), (2000, 400))
        self.company.warranty_reserve_goodwill_eligible = True
        self.assertEqual(case._warranty_reserve_figures()['eligible'], 2400)
        self.company.warranty_reserve_goodwill_eligible = False
        # Subcontract: approved cost line, posted bill line on Warranty Expense only, policy on.
        vendor = self.env['res.partner'].create({'name': 'F7 Subcontractor'})
        bill = self.Move.create({
            'move_type': 'in_invoice', 'partner_id': vendor.id, 'invoice_date': self.today,
            'invoice_line_ids': [
                (0, 0, {'name': 'Coil rewinding', 'quantity': 1, 'price_unit': 800,
                        'account_id': self.expense.id, 'tax_ids': [(5, 0, 0)]}),
                (0, 0, {'name': 'Transport', 'quantity': 1, 'price_unit': 100,
                        'account_id': self.other_cost.id, 'tax_ids': [(5, 0, 0)]})]})
        bill.action_post()
        self.company.warranty_cost_approver_ids = [(6, 0, self.coordinator.ids)]
        Cost = self.env['warranty.cost.line']
        for bill_line in bill.invoice_line_ids:
            cost = Cost.with_user(self.helpdesk_user).create({
                'case_id': case.id, 'cost_type': 'subcontract', 'reason': 'F7',
                'estimated_amount': bill_line.price_subtotal, 'bill_line_id': bill_line.id})
            cost.with_user(self.helpdesk_user).action_submit()
            cost.with_user(self.coordinator).action_approve()
        self.assertEqual(case._warranty_reserve_figures()['eligible'], 400, 'policy off')
        self.company.warranty_reserve_subcontract_eligible = True
        figures = case._warranty_reserve_figures()
        self.assertEqual((figures['subcontract'], figures['eligible']), (800, 1200),
                         'only the posted line on Warranty Expense')

    # ------------------------------------------------------------------ protection and rights
    def test_06_protection_lock_dates_and_settings_rights(self):
        self._automate()
        self._entry(self.expense, self.provision, 1000)
        mrf = self._issued([(self.filter, 1)])
        self._use(mrf, self.filter, 1)
        case = mrf.warranty_case_id
        self._completed(case)
        with patch.object(type(self.company), '_warranty_b2_locked',
                          return_value=[(self.today, 'fiscalyear_lock_date')]):
            util = self.Move.browse(
                case.with_user(self.finance).action_warranty_reserve_utilization()['res_id'])
        self.assertEqual(util.date, self.today + timedelta(days=1), 'first open day')
        self.assertIn('locked period', str(util.narration))
        line = util.line_ids.filtered('debit')
        with self.assertRaisesRegex(UserError, 'cannot be changed'):
            line.with_user(self.finance).write({'account_id': self.other_cost.id})
        with self.assertRaisesRegex(UserError, 'cannot be changed'):
            util.with_user(self.finance).write({'line_ids': [(1, line.id, {'debit': 1})]})
        with self.assertRaisesRegex(UserError, 'never deleted'):
            util.with_user(self.finance).unlink()
        with self.assertRaisesRegex(UserError, 'created from the warranty case'):
            self.Move.with_user(self.finance).create({
                'move_type': 'entry', 'journal_id': self.journal.id,
                'warranty_b2_kind': 'utilization'})
        with self.assertRaisesRegex(UserError, 'cannot be changed'):
            util.with_user(self.finance).write({'warranty_b2_case_id': False})
        # Reserve policy: Settings and Accounting Manager users only.
        with self.assertRaisesRegex(AccessError, 'Settings and Accounting Manager'):
            self.company.with_user(self.finance).write(
                {'warranty_reserve_goodwill_eligible': True})
        settings = self.env['res.config.settings'].with_user(self.editor).create({})
        settings.warranty_reserve_goodwill_eligible = True
        settings.execute()
        self.assertTrue(self.company.warranty_reserve_goodwill_eligible)

    def test_07_company_isolation(self):
        self._entry(self.expense, self.provision, 700)
        other = self.env['res.company'].create({'name': 'F7 Company B'})
        self.assertEqual(other._warranty_reserve_available(), 0, 'reserve per company')
        self.assertEqual(self.company._warranty_reserve_available(), 700)
        self.assertIn('Reserve utilization needs', other._warranty_accounting_status())
        self._automate()
        mrf = self._issued([(self.filter, 1)])
        self._use(mrf, self.filter, 1)
        case = mrf.warranty_case_id
        self._completed(case)
        util = self.Move.browse(
            case.with_user(self.finance).action_warranty_reserve_utilization()['res_id'])
        self.assertEqual((util.company_id, util.journal_id.company_id), (self.company, self.company))
        user_b = self._user('f7a_finance_b', 'account.group_account_user', company=other)
        with self.assertRaises(AccessError):
            util.with_user(user_b).read(['amount_total'])

    # ------------------------------------------------------------------ automated, end to end
    def test_08_automated_valuation_one_standard_entry_per_event(self):
        """UAT-like policy (Anglo-Saxon, own stock journal, Warranty Consumption location accounts
        = Warranty Expense): every covered use gives exactly ONE standard Odoo entry Dr Warranty
        Expense / Cr Stock Valuation linked to the stock move, case, request and job; the internal
        issue and the unused return give none; a usage reversal gives one reversing entry; the Not
        Covered delivery and invoice use standard COGS accounts only; the vendor credit note and
        the reserve utilization never duplicate the expense."""
        Account = self.env['account.account']
        cogs = Account.create({'name': 'F7 COGS', 'code': 'WCG7AC',
                               'account_type': 'expense_direct_cost',
                               'company_ids': [(6, 0, self.company.ids)]})
        income = Account.create({'name': 'F7 Sales', 'code': 'WIC7AC', 'account_type': 'income',
                                 'company_ids': [(6, 0, self.company.ids)]})
        self.company.anglo_saxon_accounting = True
        self._automate()
        self.parts.with_company(self.company).write({
            'property_account_expense_categ_id': cogs.id,
            'property_account_income_categ_id': income.id})
        oil = self.env['product.product'].create({
            'name': 'F7 Refrigerant Oil', 'is_storable': True, 'type': 'consu',
            'standard_price': 1000, 'list_price': 4000, 'invoice_policy': 'order',
            'categ_id': self.parts.id, 'taxes_id': [(5, 0, 0)]})
        self.item_gas.product_id = oil  # an excluded item: Not Covered
        self.helpdesk_user.groups_id |= self.env.ref('sales_team.group_sale_salesman')
        self._entry(self.expense, self.provision, 5000)  # posted reserve 5,000
        start = self.Move.search([], order='id desc', limit=1).id

        def new(domain=()):
            return self.Move.search([('id', '>', start)] + list(domain))

        def balance(account):
            return sum(new([('state', '=', 'posted')]).line_ids.filtered(
                lambda line: line.account_id == account).mapped('balance'))

        def validate(pickings):
            for picking in pickings:
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                picking.button_validate()

        job = self._confirmed_job()
        mrf = self._issued([(self.filter, 3), (self.valve, 1), (oil, 1)], job=job)
        case = mrf.warranty_case_id
        self.assertFalse(new([('stock_move_id', '!=', False)]), 'internal issue: no entry')

        # Covered use: exactly one standard stock entry, linked end to end.
        used = self._use(mrf, self.filter, 2)
        entry = new([('stock_move_id', '!=', False)])
        self.assertEqual(len(entry), 1)
        self.assertEqual((entry.state, entry.journal_id, entry.amount_total, entry.stock_move_id),
                         ('posted', self.stock_journal, 1000, used.move_ids))
        self.assertEqual([(line.account_id, line.debit, line.credit)
                          for line in entry.line_ids.sorted('debit', reverse=True)],
                         [(self.expense, 1000, 0), (self.stock_value, 0, 1000)])
        layer = used.move_ids.stock_valuation_layer_ids
        self.assertEqual((layer.value, layer.account_move_id), (-1000, entry))
        self.assertEqual((used.case_id, used.job_id, used.requisition_id), (case, job, mrf),
                         'cost linked to case, job and request')
        self.assertEqual(self._line(mrf, self.filter).actual_cost, 1000, 'actual cost on the line')
        self.assertEqual(case._warranty_reserve_figures()['parts'], 1000)

        # Unused return (technician -> stock, both internal): no entry.
        mrf.with_user(self.tech)._warranty_return_unused(
            [(self._line(mrf, self.filter), 1.0, self.Lot)])
        validate(self.env['stock.picking'].search([
            ('custom_requisition_id', '=', mrf.id), ('state', 'not in', ('done', 'cancel'))]))
        self.assertEqual(len(new([('stock_move_id', '!=', False)])), 1, 'return: no entry')

        # Usage reversal: one reversing standard entry.
        valve = self._use(mrf, self.valve, 1)
        valve.with_user(self.coordinator)._warranty_reverse('Wrong unit')
        both = valve.move_ids.stock_valuation_layer_ids.account_move_id
        self.assertEqual(len(both), 2, 'use + reversal, one each')
        reversal = both.filtered(lambda move: move.line_ids.filtered(
            lambda line: line.account_id == self.stock_value and line.debit))
        self.assertEqual(reversal.line_ids.filtered('credit').account_id, self.expense)
        self.assertEqual(balance(self.expense), 1000, 'filter 1,000; valve 2,000 - 2,000')

        # Not Covered: quotation -> delivery -> invoice, standard COGS, no Warranty Expense.
        action = mrf.with_user(self.helpdesk_user).action_create_parts_quotation()
        order = self.env['sale.order'].browse(action['res_id'])
        order.action_confirm()
        validate(order.picking_ids)
        out = order.picking_ids.move_ids.stock_valuation_layer_ids.account_move_id
        self.assertEqual(len(out), 1)
        self.assertEqual(sorted(out.line_ids.mapped('account_id.code')),
                         sorted([self.stock_out.code, self.stock_value.code]))
        invoice = order._create_invoices()
        invoice.action_post()
        cogs_lines = invoice.line_ids.filtered(lambda line: line.display_type == 'cogs')
        self.assertEqual(sorted(cogs_lines.mapped('account_id.code')),
                         sorted([cogs.code, self.stock_out.code]), 'Anglo-Saxon COGS')
        self.assertFalse((out | invoice).line_ids.filtered(
            lambda line: line.account_id == self.expense), 'never Warranty Expense')

        # Vendor reimbursement of the used filter: standard vendor credit note only.
        action = mrf.with_user(self.coordinator).action_create_vendor_claim()
        wizard = self.env[action['res_model']].with_user(self.coordinator).browse(
            action['res_id'])
        for row in wizard.line_ids:
            row.write({'selected': row.product_id == self.filter,
                       'qty': 2 if row.product_id == self.filter else 0})
        wizard.partner_id = False
        wizard._propose_partner()
        wizard.write({'failure_description': 'Failed'})
        claim = self.env['warranty.vendor.claim'].browse(wizard.action_apply()['res_id'])
        claim.with_user(self.coordinator).action_submit()
        claim.with_user(self.claim_approver).action_approve()
        claim.with_user(self.coordinator).action_mark_sent()
        claim.with_user(self.coordinator)._warranty_record_response(
            {claim.line_ids: (600, 'ok')}, reference='V-F7-08')
        note = self.Move.browse(
            claim.with_user(self.billing).action_create_credit_note()['res_id'])
        note.invoice_date = self.today
        note.with_user(self.billing).action_post()
        self.assertFalse(note.line_ids.filtered(
            lambda line: line.account_id in (self.expense, self.stock_value)))
        self.assertEqual(balance(self.recovery), -600)

        # Reserve utilization: posted expense 1,000 - recovery 600 = 400; no double expense.
        self._completed(case)
        util = self.Move.browse(
            case.with_user(self.finance).action_warranty_reserve_utilization()['res_id'])
        self.assertEqual(util.amount_total, 400)
        util.with_user(self.finance).action_post()
        self.assertEqual(balance(self.expense), 600, '1,000 used - 400 applied to the reserve')
        self.assertEqual(len(new([('stock_move_id', '!=', False)])), 4,
                         'filter use, valve use, valve reversal, Not Covered delivery')
        self.assertEqual(len(new([('journal_id', '=', self.stock_journal.id)])), 4,
                         'no other stock-journal entry')
