import re
from datetime import date

from lxml import etree

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .test_warranty_case import TestWarrantyCase


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCasePaymentApproverView(TestWarrantyCase):
    """Case form header of a Payment Exception Approver: only Approve Payment Exception while the
    case waits for their approval; every other user and state keeps the normal buttons."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Helpdesk users, as the approvers working the cases.
        cls.approver = cls._user('wcase_pay_approver', 'helpdesk.group_helpdesk_user')
        cls.plain_user = cls._user('wcase_pay_plain', 'helpdesk.group_helpdesk_user')
        cls.company.warranty_overdue_approver_ids = cls.approver | cls.helpdesk_user

    def setUp(self):
        super().setUp()
        self.card = self._card()
        self.policy.write({'payment_check_required': True, 'overdue_claim_handling': 'approval'})
        invoice = self.card.sale_order_id._create_invoices()
        invoice.action_post()
        invoice.payment_state = 'in_payment'
        self.invoice = invoice
        self.ticket = self._ticket(warranty_product_id=self.product.id)

    def _check(self, case):
        with self._today(date(2026, 11, 1)):
            case.with_user(self.helpdesk_user).action_check_eligibility()

    def _pending_case(self):
        case = self._create_case(self.ticket)
        self._check(case)
        self.assertEqual((case.eligibility_result, case.payment_hold),
                         ('pending_payment', 'pending_approval'))
        return case

    def _visible(self, case, user):
        """Header buttons the user sees on the case form (their own view, their own values)."""
        record = case.with_user(user)
        arch = etree.fromstring(record.get_view(view_type='form')['arch'])
        visible = set()
        for button in arch.xpath('//header/button'):
            expr = button.get('invisible') or 'False'
            values = {'context': {}, 'uid': user.id, 'id': case.id}
            for name in set(re.findall(r'[a-z_][a-z0-9_]*', expr)) & set(case._fields):
                value = record[name]
                values[name] = value.ids if case._fields[name].type in ('one2many', 'many2many') \
                    else value.id if case._fields[name].type == 'many2one' else value
            if not safe_eval(expr, values):
                visible.add(button.get('name'))
        return visible

    def test_01_approver_sees_only_the_approval(self):
        case = self._pending_case()
        self.assertEqual(self._visible(case, self.approver), {'action_approve_payment_exception'})

    def test_02_normal_user_keeps_the_workflow(self):
        """A Helpdesk user who is not an approver: the normal buttons, no approval."""
        case = self._pending_case()
        visible = self._visible(case, self.plain_user)
        self.assertIn('action_check_eligibility', visible)
        self.assertNotIn('action_approve_payment_exception', visible)
        with self.assertRaises(AccessError):
            case.with_user(self.plain_user).action_approve_payment_exception()

    def test_03_unauthorized_user(self):
        """No Helpdesk rights, no approver: nothing to approve, and the server refuses it."""
        case = self._pending_case()
        self.assertNotIn('action_approve_payment_exception',
                         self._visible(case, self.internal_user))
        with self.assertRaises(AccessError):
            case.with_user(self.internal_user).action_approve_payment_exception()

    def test_04_requester_is_not_the_approver(self):
        """The user who ran the check (requester, also listed as approver) keeps the normal
        buttons and cannot approve their own request."""
        case = self._pending_case()
        self.assertEqual(case.payment_approval_requested_by_id, self.helpdesk_user)
        visible = self._visible(case, self.helpdesk_user)
        self.assertIn('action_check_eligibility', visible)
        self.assertNotIn('action_approve_payment_exception', visible)
        with self.assertRaises(AccessError):
            case.with_user(self.helpdesk_user).action_approve_payment_exception()

    def test_05_after_approval_the_normal_buttons_return(self):
        case = self._pending_case()
        with self._today(date(2026, 11, 1)):
            case.with_user(self.approver).action_approve_payment_exception()
        self.assertEqual((case.payment_eligibility, case.payment_hold), ('waived', False))
        visible = self._visible(case, self.approver)
        self.assertIn('action_check_eligibility', visible)
        self.assertNotIn('action_approve_payment_exception', visible)

    def test_06_case_not_waiting_for_approval(self):
        """Payment passed: the approver sees the normal buttons of the state."""
        self.invoice.payment_state = 'paid'
        case = self._create_case(self.ticket)
        self.assertEqual(self._visible(case, self.approver),
                         self._visible(case, self.plain_user))
        self.assertIn('action_check_eligibility', self._visible(case, self.approver))
        self._check(case)
        self.assertFalse(case.payment_hold)
        self.assertEqual(self._visible(case, self.approver),
                         self._visible(case, self.plain_user))

    def test_07_activity_done_is_not_an_approval(self):
        """Marking the approval To-Do Done approves nothing: still waiting, still only the
        approval for the approver."""
        case = self._pending_case()
        case.payment_approval_activity_ids.filtered(
            lambda activity: activity.user_id == self.approver).with_user(
                self.approver).action_feedback(feedback='Seen')
        self.assertEqual((case.payment_eligibility, case.payment_hold),
                         ('pending', 'pending_approval'))
        self.assertEqual(self._visible(case, self.approver), {'action_approve_payment_exception'})
