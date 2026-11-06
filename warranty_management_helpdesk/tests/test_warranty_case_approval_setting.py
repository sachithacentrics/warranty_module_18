from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_warranty_case_approval import TestWarrantyCaseApproval


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCaseApprovalSetting(TestWarrantyCaseApproval):
    """Company setting Warranty Case Approval Required (approved S1-S5)."""

    def test_81_default_true(self):
        self.assertTrue(self.company.warranty_case_approval_required)
        self.assertTrue(self.env['res.company'].create(
            {'name': 'New Approval Company'}).warranty_case_approval_required)
        settings = self.env['res.config.settings'].create({})
        self.assertTrue(settings.warranty_case_approval_required)
        arch = settings.get_view(view_type='form')['arch']
        self.assertIn('name="warranty_case_approval_required"', arch)
        self.assertIn('id="warranty_case_approver_ids" invisible="not warranty_case_approval_required"',
                      arch)

    def test_82_off_helpdesk_users_approve_incl_creator(self):
        """Off: no approval users needed; creator / latest checker may approve (S1 / S2); no
        activities (S3); approval stays manual and only for Eligible cases."""
        self.company.warranty_case_approval_required = False
        self.company.warranty_case_approver_ids = [(5,)]
        case = self._eligible()
        self.assertEqual(case.state, 'eligibility_checked', 'never approved automatically')
        self.assertFalse(self._activities(case), 'no approval activities')
        self.assertIn('Warranty Case Approval Required is off', self._last_note(case))
        for user in (self.creator, self.helpdesk_user, self.helpdesk_manager):
            self.assertTrue(case.with_user(user).can_approve_case, user.login)
        self.assertFalse(case.with_user(self.internal_user).can_approve_case)
        with self.assertRaises(AccessError):
            case.with_user(self.internal_user).action_approve_case()
        case.with_user(self.creator).action_approve_case()
        self.assertEqual((case.state, case.case_approved_by_id), ('approved', self.creator))
        other = self._create_case(self.ticket, user=self.creator, requested_items=self.item_gas)
        self._result(other)
        with self.assertRaises(UserError):
            other.with_user(self.creator).action_approve_case()

    def test_83_off_closes_open_activities(self):
        """Switching off: the next Eligible check closes the open approval activities."""
        case = self._eligible()
        activities = self._activities(case)
        self.assertTrue(activities)
        self.company.warranty_case_approval_required = False
        self._result(case)
        self.assertFalse(activities.exists().filtered('active'))

    def test_84_off_reject_same_rule(self):
        """S5: Reject Case follows the same rule as Approve Case."""
        self.company.warranty_case_approval_required = False
        case = self._create_case(self.ticket, user=self.creator, requested_items=self.item_gas)
        self.assertEqual(self._result(case), 'not_eligible')
        self.assertTrue(case.with_user(self.helpdesk_user).can_reject_case, 'checker may reject')
        self.assertFalse(case.with_user(self.internal_user).can_reject_case)
        with self.assertRaises(AccessError):
            case.with_user(self.internal_user).action_open_reject_wizard()
        action = case.with_user(self.creator).action_open_reject_wizard()
        self.assertEqual(action['res_model'], 'warranty.case.reject.wizard')

    def test_85_on_unchanged_and_per_company(self):
        """On (default): creator / checker refused, approval users only. The setting of the
        case's company applies; another company's user is refused."""
        self.other_company.warranty_case_approval_required = False
        case = self._eligible()
        for user in (self.creator, self.helpdesk_user):
            with self.assertRaises(AccessError):
                case.with_user(user).action_approve_case()
        self.assertTrue(case.with_user(self.approver_a).can_approve_case)
        self.company.warranty_case_approval_required = False
        with self.assertRaises(AccessError):
            case.with_user(self.foreign_user).action_approve_case()
