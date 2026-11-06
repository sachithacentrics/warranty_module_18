from datetime import date

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .test_warranty_case_eligibility import TestWarrantyCaseEligibility


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCaseApproval(TestWarrantyCaseEligibility):
    """Part 3.6a - Approve Case (approved Q38-Q43)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approver_a = cls._user('wcase_case_approver_a')
        cls.approver_b = cls._user('wcase_case_approver_b', 'helpdesk.group_helpdesk_user')
        cls.creator = cls._user('wcase_case_creator', 'helpdesk.group_helpdesk_user')
        cls.company.warranty_case_approver_ids = \
            cls.approver_a | cls.approver_b | cls.helpdesk_user | cls.creator

    def setUp(self):
        super().setUp()
        self.card = self._card()
        self.ticket = self._ticket(warranty_product_id=self.product.id)

    def _eligible(self, **vals):
        case = self._create_case(self.ticket, user=self.creator, **vals)
        self.assertEqual(self._result(case), 'eligible')
        return case

    def _result(self, case, user=None):
        case.with_user(user or self.helpdesk_user).action_check_eligibility()
        return case.eligibility_result

    def _activities(self, case):
        return case.case_approval_activity_ids.exists().filtered('active')

    def _last_note(self, case):
        return case.message_ids[:1].body

    def test_51_activities_on_eligible(self):
        """Eligible: one To-Do per allowed approver (not the creator, not the checker), no
        duplicates on a new check (Q43)."""
        case = self._eligible()
        self.assertEqual(case.eligibility_checked_by_id, self.helpdesk_user)
        self.assertEqual(self._activities(case).user_id, self.approver_a | self.approver_b)
        activities = self._activities(case)
        self._result(case)
        self.assertEqual(self._activities(case), activities, 'no duplicates')
        self.assertIn('Case approval already requested from', self._last_note(case))

    def test_52_button_and_refused_results(self):
        """Approve only for allowed users of an Eligible case in Eligibility Checked."""
        case = self._eligible()
        self.assertTrue(case.with_user(self.approver_a).can_approve_case)
        for user in (self.helpdesk_user, self.creator, self.internal_user):
            self.assertFalse(case.with_user(user).can_approve_case)
        case.requested_item_ids = self.item_gas
        self.assertEqual(self._result(case), 'not_eligible')
        self.assertFalse(case.with_user(self.approver_a).can_approve_case)
        with self.assertRaises(UserError):
            case.with_user(self.approver_a).action_approve_case()
        new = self._create_case(self.ticket)
        with self.assertRaises(UserError):
            new.with_user(self.approver_a).action_approve_case()

    def test_53_no_self_approval(self):
        """Q40: the case creator and the latest eligibility checker cannot approve, even when
        they are configured approvers."""
        case = self._eligible()
        for user in (self.creator, self.helpdesk_user):
            with self.assertRaises(AccessError):
                case.with_user(user).action_approve_case()
        self.assertEqual(case.state, 'eligibility_checked')
        # The latest checker changes: the previous checker becomes allowed again.
        self._result(case, user=self.approver_b)
        self.assertEqual(self._activities(case).user_id, self.approver_a | self.helpdesk_user)
        with self.assertRaises(AccessError):
            case.with_user(self.approver_b).action_approve_case()

    def test_54_approve_success(self):
        """Revalidation passed: Approved + Eligible, approver / date, activities closed,
        chatter; card, units and free services unchanged; no further check (Q38)."""
        service = self.card.service_entitlement_ids.sorted('service_no')[:1]
        with self._today(date(2026, 11, 1)):
            case = self._create_case(self.ticket, user=self.creator, case_type='free_service',
                                     service_entitlement_ids=[(6, 0, service.ids)])
        self.assertEqual(self._result(case), 'eligible')
        before = (self.card.read(['state', 'free_services_balance']),
                  service.read(['state', 'scheduled_date', 'due_date']),
                  self.card.unit_warranty_ids.read(['serial_ids']))
        activities = self._activities(case)
        case.with_user(self.approver_a).action_approve_case()
        self.assertEqual((case.state, case.eligibility_result, case.case_approved_by_id),
                         ('approved', 'eligible', self.approver_a))
        self.assertTrue(case.case_approved_date)
        self.assertFalse(activities.exists().filtered('active'))
        self.assertIn('approved by wcase_case_approver_a - revalidation passed',
                      self._last_note(case))
        self.assertEqual((self.card.read(['state', 'free_services_balance']),
                          service.read(['state', 'scheduled_date', 'due_date']),
                          self.card.unit_warranty_ids.read(['serial_ids'])), before)
        with self.assertRaises(UserError):
            case.with_user(self.helpdesk_user).action_check_eligibility()
        with self.assertRaises(UserError):
            case.service_entitlement_ids = [(5,)]
        with self.assertRaises(UserError):
            case.unlink()

    def test_55_revalidation_fails(self):
        """Revalidation failed: not approved, result updated, no new payment approval /
        escalation / case approval activities, open approval activities closed, reason
        logged."""
        case = self._eligible()
        activities = self._activities(case)
        self.policy.write({'payment_check_required': True, 'overdue_claim_handling': 'approval'})
        self.company.warranty_overdue_approver_ids = self.approver_b
        action = case.with_user(self.approver_a).action_approve_case()
        self.assertEqual(action['params']['type'], 'warning')
        self.assertEqual((case.state, case.eligibility_result), ('eligibility_checked',
                                                                 'pending_payment'))
        self.assertFalse(case.case_approved_by_id)
        self.assertFalse(case.payment_approval_activity_ids)
        self.assertFalse(activities.exists().filtered('active'))
        self.assertIn('Approval refused by revalidation', self._last_note(case))
        self.assertIn('not requested during the approval revalidation', self._last_note(case))
        # Repeated failure: no escalation requested by the revalidation either.
        self.policy.write({'payment_check_required': False, 'repeated_failure_threshold': 1,
                           'repeated_failure_period_days': 90})
        self.company.warranty_escalation_user_ids = self.approver_b
        self.policy.repeated_failure_threshold = 0
        case2 = self._eligible()
        self._create_case(self.ticket)  # a second failure of the unit
        self.policy.repeated_failure_threshold = 1
        case2.with_user(self.approver_a).action_approve_case()
        self.assertEqual(case2.eligibility_result, 'manual_review')
        self.assertFalse(case2.escalation_activity_ids)

    def test_56_existing_waiver_and_confirmation_kept(self):
        """The payment waiver and the repeated failure confirmation of the case stay valid
        in the revalidation (Q41 rules preserved)."""
        self.policy.write({'payment_check_required': True, 'overdue_claim_handling': 'approval',
                           'repeated_failure_threshold': 1, 'repeated_failure_period_days': 90})
        self._create_case(self.ticket)  # earlier failure of the unit
        case = self._create_case(self.ticket, user=self.creator)
        case.sudo().write({'payment_waiver_user_id': self.approver_b.id,
                           'payment_waiver_date': '2026-10-20 10:00:00',
                           'escalation_confirmed_by_id': self.approver_b.id,
                           'escalation_confirmed_date': '2026-10-20 10:00:00'})
        self.assertEqual(self._result(case), 'eligible')
        self.assertEqual(case.payment_eligibility, 'waived')
        self.assertTrue(case.repeated_failure_flag)
        case.with_user(self.approver_a).action_approve_case()
        self.assertEqual(case.state, 'approved')

    def test_57_approver_configuration_changes(self):
        """Removed approver: refused by Approve Case; the next Eligible check closes the
        obsolete activity and creates activities for newly configured approvers."""
        case = self._eligible()
        old = self._activities(case).filtered(lambda a: a.user_id == self.approver_b)
        self.company.warranty_case_approver_ids = [(3, self.approver_b.id)]
        self.assertFalse(case.with_user(self.approver_b).can_approve_case)
        with self.assertRaises(AccessError):
            case.with_user(self.approver_b).action_approve_case()
        new_approver = self._user('wcase_case_approver_new')
        self.company.warranty_case_approver_ids = [(4, new_approver.id)]
        kept = self._activities(case).filtered(lambda a: a.user_id == self.approver_a)
        self._result(case)
        self.assertFalse(old.exists().filtered('active'))
        self.assertEqual(self._activities(case).user_id, self.approver_a | new_approver)
        self.assertIn(kept, self._activities(case), 'valid activity kept')
        self.assertIn('no longer authorized', self._last_note(case))

    def test_58_settings_and_multi_company(self):
        """Approvers are internal users of the company; another company's users cannot
        approve or see the case."""
        with self.assertRaises(ValidationError):
            self.company.warranty_case_approver_ids = [(4, self.foreign_user.id)]
        case = self._eligible()
        with self.assertRaises(AccessError):
            case.with_user(self.foreign_user).action_approve_case()
        self.assertFalse(self.env['warranty.case'].with_user(self.foreign_user).search(
            [('id', '=', case.id)]))
