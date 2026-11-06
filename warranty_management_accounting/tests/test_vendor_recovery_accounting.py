from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.warranty_management_repair.tests.test_warranty_replacement import ReplacementCommon

from .test_warranty_cost_lines import _SavepointMixin


@tagged('post_install', '-at_install', 'warranty_cost')
class TestVendorRecoveryAccounting(_SavepointMixin, ReplacementCommon):
    """Part 8.7: what the existing claim and credit note flow does at each accounting event, from
    the claim to the case and both reports. Nothing here adds a recovery rule; F6 stays open."""

    def setUp(self):
        super().setUp()
        self.supplier = self.env['res.partner'].create({'name': 'Recovery Manufacturer'})
        self.single.standard_price = 100.0
        self.single.product_tmpl_id.write({'warranty_vendor_claimable': True,
                                           'warranty_claim_partner_id': self.supplier.id})
        self.recovery_account = self.env['account.account'].create({
            'name': 'Vendor Recovery', 'code': 'WVR870', 'account_type': 'income_other',
            'company_ids': [(6, 0, self.company.ids)]})
        self.payable = self.env['account.account'].create({
            'name': 'Recovery Payable', 'code': 'WVP870', 'account_type': 'liability_payable',
            'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        self.supplier.with_company(self.company).property_account_payable_id = self.payable
        self.company.write({
            'warranty_vendor_claim_enabled': True,
            'warranty_claim_evidence_required': False,
            'warranty_replacement_gm_user_ids': [(6, 0, self.gm.ids)],
            'warranty_claim_approver_ids': [(6, 0, self.gm.ids)],
            'warranty_claim_recovery_account_id': self.recovery_account.id,
        })
        self.accountant = self._user('recovery_accountant', 'account.group_account_invoice')
        self.card = self._card(self.single)
        self.old = self.card.unit_warranty_ids.serial_ids
        self.case = self._eligible_case(self.old)
        self.assertEqual(self.case.eligibility_result, 'eligible', self.case.eligibility_reason)
        self._approved_state(self.case)
        self.replacement = self._request(self.case, 'vendor', self._lot(self.single, 6))
        self.replacement.action_warranty_replacement_submit()
        self.replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = self.replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        action = self.replacement.action_warranty_replacement_create_vendor_claim()
        self.claim = self.env['warranty.vendor.claim'].browse(action['res_id'])

    # ------------------------------------------------------------------ helpers
    def _approve(self):
        self.claim.with_user(self.coordinator).action_submit()
        self.claim.with_user(self.gm).action_approve()

    def _answer(self, accepted=100):
        if self.claim.state == 'draft':
            self._approve()
        self.claim.with_user(self.coordinator).action_mark_sent()
        self.claim.with_user(self.coordinator)._warranty_record_response(
            {self.claim.line_ids: (accepted, 'Vendor reply')}, reference='V-87')

    def _draft_note(self):
        action = self.claim.with_user(self.accountant).action_create_credit_note()
        return self.env['account.move'].browse(action['res_id'])

    def _post(self, move):
        move.invoice_date = fields.Date.today()
        move.action_post()
        self.env.invalidate_all()

    def _vendor_note(self, amount, partner=None, move_type='in_refund', post=True, currency=None):
        move = self.env['account.move'].create({
            'move_type': move_type, 'partner_id': (partner or self.supplier).id,
            'company_id': self.company.id, 'invoice_date': fields.Date.today(),
            'currency_id': (currency or self.company.currency_id).id,
            'invoice_line_ids': [(0, 0, {'name': 'Vendor credit', 'quantity': 1,
                                         'price_unit': amount, 'tax_ids': [(5, 0, 0)],
                                         'account_id': self.recovery_account.id})]})
        if post:
            move.action_post()
        return move

    def _allocate(self, move, amount):
        return self.claim.with_user(self.accountant)._warranty_allocate(move, amount, 'Test')

    def _assert_recovery(self, recovered, outstanding):
        """The claim, the case, the Part 5 report and the Warranty Cost Report agree."""
        self.env.invalidate_all()
        self.assertEqual((self.claim.recovered_amount, self.claim.outstanding_amount),
                         (recovered, outstanding), 'claim')
        case = self.case
        self.assertEqual((case.vendor_recovered_amount, case.vendor_outstanding_amount),
                         (recovered, outstanding), 'case')
        self.assertEqual(case.warranty_net_cost, case.warranty_total_actual - recovered, 'net')
        report = self.env['warranty.vendor.claim.recovery.report'].search(
            [('claim_id', '=', self.claim.id), ('allocation_scope', '=', 'line')])
        self.assertEqual((report.recovered_amount, report.outstanding_amount),
                         (recovered, outstanding), 'recovery report')
        Cost = self.env['warranty.cost.report'].with_user(self.coordinator)
        Cost.action_open_warranty_cost_report()
        rows = Cost.search([('case_id', '=', case.id)])
        self.assertEqual(sum(rows.mapped('recovered_amount')), recovered, 'cost report')
        self.assertEqual(sum(rows.mapped('net_amount')), case.warranty_net_cost, 'cost report net')

    # ------------------------------------------------------------------ the scenarios
    def test_01_approved_claim_without_a_credit_note(self):
        self._approve()
        self.assertEqual(self.claim.state, 'approved')
        self.assertEqual((self.claim.recovered_amount, self.case.vendor_recovered_amount), (0, 0))
        self.assertEqual(self.case.warranty_net_cost, self.case.warranty_total_actual)
        with self.assertRaisesRegex(UserError, 'no accepted amount to recover'):
            self.claim.with_user(self.accountant).action_create_credit_note()

    def test_02_accepted_is_not_recovered_and_a_draft_note_is_not_recovered(self):
        moves = self.env['account.move'].search_count([])
        self._answer()
        self.assertEqual(self.env['account.move'].search_count([]), moves, 'acceptance posts nothing')
        self._assert_recovery(0, 100)
        move = self._draft_note()
        self.assertEqual((move.move_type, move.state, move.partner_id, move.amount_total),
                         ('in_refund', 'draft', self.supplier, 100))
        self.assertEqual(move.invoice_line_ids.account_id, self.recovery_account)
        self.assertEqual(self.claim.allocated_amount, 100)
        self._assert_recovery(0, 100)
        with self.assertRaisesRegex(UserError, 'already allocated'):
            self.claim.with_user(self.accountant).action_create_credit_note()

    def test_03_posted_note_is_recovered_with_no_payment_or_reconciliation(self):
        self._answer()
        move = self._draft_note()
        self._post(move)
        self._assert_recovery(100, 0)
        self.assertEqual(self.claim.recovery_status, 'recovered')
        self.assertEqual(self.claim.settled_amount, 0, 'recovered is not settled')
        self.assertEqual(move.payment_state, 'not_paid')
        self.assertFalse(self.env['account.payment'].search(
            [('reconciled_bill_ids', 'in', move.ids)]))
        self.assertFalse(move.line_ids.filtered('reconciled'))
        self.assertEqual(self.claim.recovery_ids.move_id, move)
        self.assertIn(self.claim, move.warranty_claim_recovery_ids.claim_id)

    def test_04_partial_recovery(self):
        self._answer(60)
        self.assertEqual(self.claim.accepted_amount, 60)
        move = self._draft_note()
        self.assertEqual(move.amount_total, 60, 'the accepted amount, not the claimed one')
        self._post(move)
        self._assert_recovery(60, 0)

    def test_05_multiple_recoveries(self):
        self._answer()
        first = self._vendor_note(40)
        self._allocate(first, 40)
        self._assert_recovery(40, 60)
        self.assertEqual(self.claim.recovery_status, 'partial')
        second = self._vendor_note(60)
        self._allocate(second, 60)
        self._assert_recovery(100, 0)
        self.assertEqual(self.claim.recovery_status, 'recovered')
        self.assertEqual(len(self.claim.recovery_ids), 2)

    def test_06_reversed_note_gives_the_recovery_back(self):
        self._answer()
        move = self._draft_note()
        self._post(move)
        posted = (move.state, move.amount_total)
        reversal = move._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=True)
        self.assertEqual(reversal.state, 'posted')
        self._assert_recovery(0, 100)
        self.assertEqual((move.state, move.amount_total), posted, 'the note is not changed')
        self.assertEqual(self.claim.recovery_ids.filtered('active').move_id, move, 'history stays')
        again = self._draft_note()
        self.assertEqual(again.amount_total, 100, 'it can be recovered again')
        self._assert_recovery(0, 100)
        self._post(again)
        self._assert_recovery(100, 0)

    def test_07_partly_reversed_note(self):
        self._answer()
        move = self._draft_note()
        self._post(move)
        reversal = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        reversal.invoice_line_ids.price_unit = 30
        reversal.action_post()
        self._assert_recovery(70, 30)

    def test_08_a_note_cannot_be_used_twice_or_beyond_its_amount(self):
        self._answer()
        move = self._vendor_note(50)
        with self.assertRaisesRegex(UserError, 'still available'):
            self._allocate(move, 51)
        self._allocate(move, 50)
        with self.assertRaisesRegex(UserError, 'still available'):
            self._allocate(move, 1)
        self.assertEqual(len(self.claim.recovery_ids), 1)
        self._assert_recovery(50, 50)

    def test_09_recovery_cannot_exceed_the_accepted_amount(self):
        self._answer(60)
        move = self._vendor_note(100)
        with self.assertRaisesRegex(UserError, 'not yet recovered'):
            self._allocate(move, 61)
        self._allocate(move, 60)
        self._assert_recovery(60, 0)
        other = self._vendor_note(10)
        with self.assertRaisesRegex(UserError, 'not yet recovered'):
            self._allocate(other, 1)
        self._assert_recovery(60, 0)

    def test_10_unrelated_vendor_documents(self):
        self._answer()
        stranger = self.env['res.partner'].create({'name': 'Other Vendor'})
        stranger.with_company(self.company).property_account_payable_id = self.payable
        with self.assertRaisesRegex(UserError, 'is not from'):
            self._allocate(self._vendor_note(50, partner=stranger), 50)
        with self.assertRaisesRegex(UserError, 'Only posted vendor credit notes'):
            self._allocate(self._vendor_note(50, move_type='in_invoice'), 50)
        with self.assertRaisesRegex(UserError, 'Only posted vendor credit notes'):
            self._allocate(self._vendor_note(50, post=False), 50)
        self._vendor_note(50)
        self._assert_recovery(0, 100)
        self.assertEqual(self.claim.recovery_ids, self.env['warranty.vendor.claim.recovery'],
                         'a credit note entered outside the claim counts for nothing (F6)')

    def test_11_rights_and_protected_records(self):
        self._answer()
        with self.assertRaisesRegex(AccessError, 'Only Accounting'):
            self.claim.with_user(self.coordinator).action_create_credit_note()
        move = self._vendor_note(50)
        with self.assertRaisesRegex(AccessError, 'Only Accounting'):
            self.claim.with_user(self.coordinator)._warranty_allocate(move, 50)
        allocation = self._allocate(move, 50)
        with self.assertRaisesRegex(UserError, 'Remove Allocation'):
            allocation.with_user(self.accountant).write({'amount': 1})
        with self.assertRaisesRegex(UserError, 'never deleted'):
            allocation.with_user(self.accountant).unlink()

    def test_12_company_isolation(self):
        self._answer()
        other = self.env['res.company'].create({'name': 'Recovery Co B'})
        account = self.env['account.account'].with_company(other).create({
            'name': 'B Recovery', 'code': 'WVR871', 'account_type': 'income_other',
            'company_ids': [(6, 0, other.ids)]})
        payable = self.env['account.account'].with_company(other).create({
            'name': 'B Payable', 'code': 'WVP871', 'account_type': 'liability_payable',
            'reconcile': True, 'company_ids': [(6, 0, other.ids)]})
        self.supplier.with_company(other).property_account_payable_id = payable
        journal = self.env['account.journal'].create({
            'name': 'B Purchases', 'code': 'WVB', 'type': 'purchase', 'company_id': other.id,
            'default_account_id': account.id})
        foreign_company = self.env['account.move'].with_company(other).create({
            'move_type': 'in_refund', 'partner_id': self.supplier.id, 'company_id': other.id,
            'journal_id': journal.id, 'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'name': 'Credit', 'quantity': 1, 'price_unit': 50,
                                         'account_id': account.id, 'tax_ids': [(5, 0, 0)]})]})
        foreign_company.action_post()
        with self.assertRaisesRegex(UserError, 'belongs to another company'):
            self._allocate(foreign_company, 50)
        user = self.env['res.users'].create({
            'name': 'Recovery B', 'login': 'recovery_b', 'company_id': other.id,
            'company_ids': [(6, 0, other.ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('account.group_account_invoice')).ids)]})
        with self.assertRaises(AccessError):
            self.claim.with_user(user).read(['recovered_amount'])
        self.assertFalse(self.env['warranty.vendor.claim.recovery.report'].with_user(user).search(
            [('claim_id', '=', self.claim.id)]))

    def test_13_foreign_currency_note_counts_in_company_currency(self):
        self._answer()
        currency = self.env['res.currency'].with_context(active_test=False).search(
            [('id', '!=', self.company.currency_id.id)], limit=1)
        currency.active = True
        self.env['res.currency.rate'].create({'currency_id': currency.id, 'rate': 2.0,
                                              'name': fields.Date.today(),
                                              'company_id': self.company.id})
        move = self._vendor_note(100, currency=currency)
        self.assertEqual(move._warranty_claim_available(), 50, '100 at rate 2')
        with self.assertRaisesRegex(UserError, 'still available'):
            self._allocate(move, 51)
        self._allocate(move, 50)
        self._assert_recovery(50, 50)

    def test_14_open_claim_continues_after_case_closure(self):
        self._approve()
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_case SET state = 'completed' WHERE id = %s",
                            (self.case.id,))
        self.env.invalidate_all()
        self.assertFalse(self.case._warranty_close_problems())
        self.case.with_user(self.coordinator).action_warranty_close_case()
        self.assertEqual((self.case.state, self.claim.state), ('closed', 'approved'),
                         'the claim stays open')
        self.claim.with_user(self.coordinator).action_mark_sent()
        self.claim.with_user(self.coordinator)._warranty_record_response(
            {self.claim.line_ids: (100, 'Vendor reply')}, reference='V-87')
        move = self._draft_note()
        self._post(move)
        self._assert_recovery(100, 0)
        self.assertEqual(self.case.state, 'closed', 'recovery does not reopen the case')
        self.claim.with_user(self.coordinator)._warranty_close()
        self.assertEqual((self.claim.state, self.case.state), ('closed', 'closed'))

    # ------------------------------------------------------------------ F6-A
    def _lowered_note(self, amount=60):
        self._answer()
        move = self._draft_note()
        move.invoice_line_ids.price_unit = amount
        return move

    def test_15_lowered_note_recognises_its_posted_amount(self):
        """F6-A, the approved example: accepted 100, draft 100, lowered to 60 before posting."""
        move = self._lowered_note()
        self._assert_recovery(0, 100)
        self.assertEqual(self.claim.allocated_amount, 100, 'a draft holds its whole allocation')
        with self.assertRaisesRegex(UserError, 'already allocated'):
            self.claim.with_user(self.accountant).action_create_credit_note()
        self._post(move)
        self.assertEqual(move.amount_total, 60)
        self._assert_recovery(60, 40)
        self.assertEqual(self.claim.recovery_status, 'partial')
        self.assertEqual(self.claim.allocated_amount, 60)
        allocation = self.claim.recovery_ids
        self.assertEqual((allocation.amount, allocation.recovered_amount), (100, 60),
                         'the allocation record is not changed')

    def test_16_the_remaining_40_can_be_recovered_later(self):
        first = self._lowered_note()
        self._post(first)
        second = self._draft_note()
        self.assertEqual((second.state, second.amount_total), ('draft', 40), 'only what remains')
        self._assert_recovery(60, 40)
        with self.assertRaisesRegex(UserError, 'already has a draft|already allocated'):
            self.claim.with_user(self.accountant).action_create_credit_note()
        self._post(second)
        self._assert_recovery(100, 0)
        self.assertEqual(self.claim.recovery_status, 'recovered')
        with self.assertRaisesRegex(UserError, 'already allocated'):
            self.claim.with_user(self.accountant).action_create_credit_note()
        self.assertEqual(first.amount_total + second.amount_total, 100)

    def test_17_raised_note_stays_capped_at_its_allocation(self):
        self._answer(60)
        move = self._draft_note()
        move.invoice_line_ids.price_unit = 500
        self._post(move)
        self.assertEqual(move.amount_total, 500)
        self._assert_recovery(60, 0)

    def test_18_lowered_note_then_reversals(self):
        move = self._lowered_note()
        self._post(move)
        partial = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        partial.invoice_line_ids.price_unit = 15
        partial.action_post()
        self._assert_recovery(45, 55)
        rest = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        rest.invoice_line_ids.price_unit = 45
        rest.action_post()
        self._assert_recovery(0, 100)
        again = self._draft_note()
        self.assertEqual(again.amount_total, 100)
        self._post(again)
        self._assert_recovery(100, 0)

    def test_19_lowered_then_cancelled_and_reset(self):
        move = self._lowered_note()
        self._post(move)
        self._assert_recovery(60, 40)
        move.button_draft()
        self._assert_recovery(0, 100)
        self.assertEqual(self.claim.allocated_amount, 100, 'a draft again holds its allocation')
        move.invoice_line_ids.price_unit = 80
        self._post(move)
        self._assert_recovery(80, 20)
        move.button_draft()
        move.button_cancel()
        self._assert_recovery(0, 100)
        self.assertEqual(self.claim.allocated_amount, 0)

    def test_20_settled_and_cost_report_periods_follow_the_posted_amount(self):
        move = self._lowered_note()
        self._post(move)
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create({})
        self.assertEqual(payment.amount, 60)
        Cost = self.env['warranty.cost.report'].with_user(self.coordinator)
        Cost.action_open_warranty_cost_report()
        rows = Cost.search([('case_id', '=', self.case.id), ('cost_type', '=', 'recovery')])
        self.assertEqual({row.cost_date: row.recovered_amount for row in rows}, {move.date: 60})

    def test_21_note_with_two_allocations_shares_a_lowered_amount(self):
        self._answer()
        move = self._vendor_note(100, post=False)
        allocation_vals = {'claim_id': self.claim.id, 'claim_line_id': self.claim.line_ids.id,
                           'move_id': move.id, 'amount': 40}
        Recovery = self.env['warranty.vendor.claim.recovery'].sudo()
        first = Recovery.create(allocation_vals)
        second = Recovery.create(dict(allocation_vals, amount=60))
        move.invoice_line_ids.price_unit = 50
        move.invoice_date = fields.Date.today()
        move.action_post()
        self.env.invalidate_all()
        self.assertEqual((first.recovered_amount, second.recovered_amount), (20, 30))
        self._assert_recovery(50, 50)
