from datetime import date
from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .test_warranty_case import TestWarrantyCase


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCasePayment(TestWarrantyCase):
    """Part 3.3 - payment eligibility and overdue claim handling (approved Q15-Q21)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approver = cls._user('wcase_approver')
        cls.approver_two = cls._user('wcase_approver_two')
        cls.company.warranty_overdue_approver_ids = cls.approver | cls.approver_two | cls.helpdesk_user

    def setUp(self):
        super().setUp()
        self.card = self._card()
        self.order = self.card.sale_order_id
        self.policy.payment_check_required = True
        self.ticket = self._ticket(warranty_product_id=self.product.id)

    # ------------------------------------------------------------------ helpers
    def _invoice(self, state='paid'):
        invoice = self.order._create_invoices()
        invoice.action_post()
        invoice.payment_state = state
        return invoice

    def _overdue(self, partner=None, company=None, state='not_paid', due=date(2026, 9, 1)):
        company = company or self.company
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'out_invoice', 'partner_id': (partner or self.customer).id,
            'invoice_date': due, 'invoice_date_due': due,
            'invoice_line_ids': [(0, 0, {'name': 'Service visit', 'quantity': 1,
                                         'price_unit': 1000.0})]})
        move.action_post()
        move.payment_state = state
        return move

    def _check(self, case, user=None):
        with self._today(date(2026, 11, 1)):
            case.with_user(user or self.helpdesk_user).action_check_eligibility()
        # False: the payment step passed through to the end (Eligible, Part 3.5).
        result = False if case.eligibility_result == 'eligible' else case.eligibility_result
        return result, case.payment_eligibility, case.payment_hold

    def _log(self, case):
        return case.message_ids.filtered(lambda m: 'Eligibility check' in (m.body or ''))[:1].body

    # ------------------------------------------------------------------ tests
    def test_21_payment_not_required_and_warning_info(self):
        """Payment Check Required off: Not Required, the check continues; the Overdue Warning
        is shown on case and ticket but only informational (Q16)."""
        self.policy.payment_check_required = False
        self._overdue()
        case = self._create_case(self.ticket)
        self.assertEqual(self._check(case), (False, 'not_required', False))
        with self._today(date(2026, 11, 1)):
            case.invalidate_recordset(['overdue_warning'])
            self.ticket.invalidate_recordset(['warranty_overdue_warning'])
            self.assertIn('Customer has 1 overdue invoice(s)', case.overdue_warning)
            self.assertEqual(self.ticket.warranty_overdue_warning, case.overdue_warning)
        self.assertIn('information only', self._log(case))
        self.assertIn('the coverage check follows', self._log(case))

    def test_22_payment_passed(self):
        """Every warranty sale invoice Paid and no overdue receivables: Passed."""
        self._invoice('paid')
        self._overdue(state='paid')
        self._overdue(state='not_paid', due=date(2026, 12, 1))  # not yet due
        case = self._create_case(self.ticket)
        self.assertEqual(self._check(case), (False, 'passed', False))

    def test_23_payment_failures_with_warning(self):
        """No posted invoice / In Payment / Partially Paid / Not Paid / Blocked / Reversed are
        not settled (Q15); Warning Only: Failed, the check continues."""
        self.policy.overdue_claim_handling = 'warning'
        case = self._create_case(self.ticket)
        self.assertEqual(self._check(case), (False, 'failed', False))
        self.assertIn('No posted invoice', self._log(case))
        invoice = self._invoice('paid')
        self.assertEqual(self._check(case)[1], 'passed')
        for state, text in (('in_payment', 'In Payment'), ('partial', 'Partially Paid'),
                            ('not_paid', 'Not Paid'), ('blocked', 'Blocked'),
                            ('reversed', 'warranty sale refunded')):
            invoice.payment_state = state
            self.assertEqual(self._check(case), (False, 'failed', False), state)
            self.assertIn(text, self._log(case))
        self.assertIn('Warning Only', self._log(case))

    def test_24_hold_and_block_cleared_after_payment(self):
        """Hold / Block: Pending Payment + indicator, never rejected; cleared by the next
        check once the conditions pass (Q20)."""
        invoice = self._invoice('not_paid')
        for handling, hold in (('hold', 'on_hold'), ('block', 'blocked')):
            self.policy.overdue_claim_handling = handling
            invoice.payment_state = 'not_paid'
            case = self._create_case(self.ticket)
            self.assertEqual(self._check(case), ('pending_payment', 'failed', hold))
            self.assertNotEqual(case.state, 'rejected')
            invoice.payment_state = 'paid'
            self.assertEqual(self._check(case), (False, 'passed', False))

    def test_25_approval_required_and_case_waiver(self):
        """Approval Required: activities for the configured approvers (not the requester), no
        duplicates; only approvers, never the requester; waiver stored on this case only;
        Check Eligibility must be run again (Q18 / Q19)."""
        self.policy.overdue_claim_handling = 'approval'
        invoice = self._invoice('in_payment')
        case = self._create_case(self.ticket)
        self.assertEqual(self._check(case), ('pending_payment', 'pending', 'pending_approval'))
        self.assertEqual(case.payment_approval_requested_by_id, self.helpdesk_user)
        activities = case.payment_approval_activity_ids
        self.assertEqual(activities.user_id, self.approver | self.approver_two)
        self._check(case)
        self.assertEqual(case.payment_approval_activity_ids, activities, 'no duplicates')
        for user in (self.helpdesk_user, self.internal_user):
            with self.assertRaises(AccessError):
                case.with_user(user).action_approve_payment_exception()
        self.assertTrue(case.with_user(self.approver).can_approve_payment)
        self.assertFalse(case.with_user(self.helpdesk_user).can_approve_payment)
        with self._today(date(2026, 11, 1)):
            case.with_user(self.approver).action_approve_payment_exception()
        self.assertEqual((case.payment_eligibility, case.payment_hold, case.payment_waiver_user_id,
                          case.eligibility_result), ('waived', False, self.approver,
                                                     'pending_payment'))
        self.assertIn('In Payment', case.payment_waiver_conditions)
        self.assertTrue(case.payment_waiver_date)
        self.assertFalse(activities.exists().filtered('active'), 'approver activities closed')
        # Next check: still failing, but the waiver of this case applies.
        self.assertEqual(self._check(case), (False, 'waived', False))
        self.assertIn('Payment exception approved by', self._log(case))
        # Another case of the same ticket is not covered by the waiver.
        other = self._create_case(self.ticket)
        self.assertEqual(self._check(other), ('pending_payment', 'pending', 'pending_approval'))
        # Payment fixed later: Passed (waiver kept in the history).
        invoice.payment_state = 'paid'
        self.assertEqual(self._check(case), (False, 'passed', False))
        self.assertEqual(case.payment_waiver_user_id, self.approver)
        # Pending approval no longer needed: activities closed, indicator removed.
        self.assertEqual(self._check(other), (False, 'passed', False))
        self.assertFalse(other.payment_approval_activity_ids.exists().filtered('active'))

    def test_26_missing_handling_is_warning(self):
        """Overdue Claim Handling not configured: Warning Only (Q17)."""
        self.policy.overdue_claim_handling = False
        self._invoice('not_paid')
        case = self._create_case(self.ticket)
        self.assertEqual(self._check(case), (False, 'failed', False))

    def test_27_overdue_receivables_scope(self):
        """Overdue = posted customer invoices of the same commercial customer and company, due
        before today, not Paid / Reversed (In Payment counts, Q15)."""
        self._invoice('paid')
        self._overdue(partner=self.other_customer)
        self._overdue(state='reversed')
        overdue = self._overdue(partner=self.contact, due=date(2026, 9, 2))
        with self._today(date(2026, 11, 1)):
            Case = self.env['warranty.case']
            self.assertEqual(Case._warranty_overdue_invoices(self.customer, self.company)[0],
                             overdue)
            self.assertFalse(Case._warranty_overdue_invoices(self.customer, self.other_company)[0])
        overdue.payment_state = 'paid'
        case = self._create_case(self.ticket)
        self.assertEqual(self._check(case)[1], 'passed')
        self._overdue(partner=self.site_a, state='in_payment')  # no payment linked
        self.assertEqual(self._check(case)[1], 'failed')
        self.assertIn('Customer has 1 overdue invoice(s)', self._log(case))

    def test_28_settings_and_31_stops_before_payment(self):
        """Approvers must be internal users of the company; a 3.2 failure stops before the
        payment step; free service Payment Eligibility is not changed (Q21)."""
        with self.assertRaises(ValidationError):
            self.company.warranty_overdue_approver_ids = [(4, self.foreign_user.id)]
        self._invoice('not_paid')
        self.policy.overdue_claim_handling = 'hold'
        case = self._create_case(self.ticket, case_type='amc')
        self.assertEqual(self._check(case), ('manual_review', False, False))
        service = self.card.service_entitlement_ids[:1]
        with self._today(date(2026, 11, 1)):
            linked = self._create_case(self.ticket, service_entitlement_ids=[(6, 0, service.ids)])
        self._check(linked)
        self.assertEqual(linked.payment_hold, 'on_hold')
        self.assertFalse(service.payment_eligibility)

    def test_29_multi_company_approval(self):
        """Another company's users cannot see or approve the case."""
        self.policy.overdue_claim_handling = 'approval'
        self._invoice('not_paid')
        case = self._create_case(self.ticket)
        self._check(case)
        with self.assertRaises(AccessError):
            case.with_user(self.foreign_user).action_approve_payment_exception()
        self.assertFalse(self.env['warranty.case'].with_user(self.foreign_user).search(
            [('id', '=', case.id)]))

    # ------------------------------------------------- Q15 rev. B: registered payments
    def _register(self, invoices, amount, currency=None, group=True):
        """Register a payment without journal entry (bank journal without outstanding
        account): In Payment until the bank reconciliation, residual unchanged."""
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoices.ids).create({
                'journal_id': self.bank.id, 'amount': amount, 'group_payment': group,
                'payment_date': date(2026, 10, 20),
                'currency_id': (currency or self.company.currency_id).id})
        return wizard._create_payments()

    def _in_payment(self):
        """warranty_test has no 'accountant': make registered payments In Payment as there."""
        return patch.object(type(self.env['account.move']), '_get_invoice_in_payment_state',
                            lambda move: 'in_payment')

    def _bank_without_outstanding(self):
        bank = self.env['account.journal'].search([
            ('type', '=', 'bank'), ('company_id', '=', self.company.id)], limit=1)
        bank.inbound_payment_method_line_ids.payment_account_id = False
        return bank

    def test_30_in_payment_fully_covered_passes(self):
        """In Payment fully covered by registered payments (residual unchanged): Passed, not
        overdue, no approval; invoice and payment records are not changed by the check."""
        self.bank = self._bank_without_outstanding()
        self.policy.overdue_claim_handling = 'approval'
        with self._in_payment():
            invoice = self._invoice('not_paid')
            overdue = self._overdue()
            payment = self._register(invoice | overdue, invoice.amount_total + overdue.amount_total)
            self.assertEqual((invoice.payment_state, overdue.payment_state),
                             ('in_payment', 'in_payment'))
            self.assertFalse(payment.move_id)
            self.assertEqual(overdue.amount_residual, overdue.amount_total)
            before = (invoice.read(['payment_state', 'amount_residual']),
                      payment.read(['state', 'amount']))
            case = self._create_case(self.ticket)
            self.assertEqual(self._check(case), (False, 'passed', False))
            with self._today(date(2026, 11, 1)):
                case.invalidate_recordset(['overdue_warning'])
                self.assertFalse(case.overdue_warning)
            self.assertFalse(case.payment_approval_activity_ids)
            self.assertEqual((invoice.read(['payment_state', 'amount_residual']),
                              payment.read(['state', 'amount'])), before)

    def test_31_in_payment_partial_and_shared_payment(self):
        """Partially covered In Payment: the uncovered amount is outstanding (handling rules
        apply); a payment linked to several invoices is counted once."""
        self.bank = self._bank_without_outstanding()
        self.policy.overdue_claim_handling = 'hold'
        Case = self.env['warranty.case']
        with self._in_payment():
            invoice = self._invoice('not_paid')
            first = self._overdue(due=date(2026, 9, 1))
            second = self._overdue(due=date(2026, 9, 2))
            # One payment covering only one of the two invoices.
            self._register(first | second, first.amount_total)
            with self._today(date(2026, 11, 1)):
                amounts = Case._warranty_uncovered_amounts(first | second)
                self.assertEqual(amounts[first.id], 0.0, 'earlier due invoice covered first')
                self.assertAlmostEqual(amounts[second.id], second.amount_total)
                overdue, total = Case._warranty_overdue_invoices(self.customer, self.company)
                # The warranty sale invoice is overdue too on 2026-11-01.
                self.assertEqual(overdue, second | invoice)
                self.assertAlmostEqual(total, second.amount_total + invoice.amount_total)
            # Warranty sale invoice half covered; the overdue invoice fully covered.
            self._register(invoice, invoice.amount_total / 2)
            self._register(second, second.amount_total)
            case = self._create_case(self.ticket)
            self.assertEqual(self._check(case), ('pending_payment', 'failed', 'on_hold'))
            self.assertIn('not fully covered by the registered payments (uncovered', self._log(case))
            self.assertIn('Customer has 1 overdue invoice(s)', self._log(case))
            # Rest registered: the next check passes and removes the hold (Q20).
            self._register(invoice, invoice.amount_total / 2)
            self.assertEqual(self._check(case), (False, 'passed', False))

    def test_32_in_payment_currency_and_payment_states(self):
        """Payments in another currency are converted at the payment date; cancelled payments
        are not counted."""
        self.bank = self._bank_without_outstanding()
        eur = self.env.ref('base.EUR')
        eur.active = True
        self.env['res.currency.rate'].create({
            'currency_id': eur.id, 'name': date(2026, 10, 1), 'rate': 0.5,
            'company_id': self.company.id})
        Case = self.env['warranty.case']
        with self._in_payment():
            overdue = self._overdue()
            # Rate 0.5: a quarter of the amount in EUR covers half of the invoice.
            payment = self._register(overdue, overdue.amount_total / 4, currency=eur)
            with self._today(date(2026, 11, 1)):
                self.assertAlmostEqual(Case._warranty_uncovered_amounts(overdue)[overdue.id],
                                       overdue.amount_total / 2)
            other = self._register(overdue, overdue.amount_total / 4, currency=eur)
            with self._today(date(2026, 11, 1)):
                self.assertFalse(Case._warranty_uncovered_amounts(overdue)[overdue.id])
            other.action_cancel()
            with self._today(date(2026, 11, 1)):
                self.assertAlmostEqual(Case._warranty_uncovered_amounts(overdue)[overdue.id],
                                       overdue.amount_total / 2)
            self.assertIn(payment.state, ('in_process', 'paid'))
