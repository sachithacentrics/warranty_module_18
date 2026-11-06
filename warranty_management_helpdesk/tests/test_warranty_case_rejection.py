from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_warranty_case_approval import TestWarrantyCaseApproval


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCaseRejection(TestWarrantyCaseApproval):
    """Part 3.6b - claim rejection (approved Q44-Q48)."""

    def _not_eligible(self):
        case = self._create_case(self.ticket, user=self.creator, requested_items=self.item_gas)
        self.assertEqual(self._result(case), 'not_eligible')
        return case

    def _reject(self, case, user=None, reason='not_covered', note=''):
        user = user or self.approver_a
        action = case.with_user(user).action_open_reject_wizard()
        wizard = self.env['warranty.case.reject.wizard'].with_user(user).with_context(
            action['context']).create({'rejection_reason': reason, 'rejection_note': note})
        return wizard.action_reject()

    def test_61_who_and_which_results(self):
        """Q44 / Q45: Warranty Case Approval Users (not creator / latest checker) reject Not
        Eligible / Out of Warranty / Manual Review results only."""
        case = self._not_eligible()
        self.assertTrue(case.with_user(self.approver_a).can_reject_case)
        for user in (self.creator, self.helpdesk_user, self.internal_user):
            self.assertFalse(case.with_user(user).can_reject_case)
            with self.assertRaises(AccessError):
                case.with_user(user).action_open_reject_wizard()
        case.requested_item_ids = self.item_undefined
        self.assertEqual(self._result(case), 'manual_review')
        self.assertTrue(case.with_user(self.approver_a).can_reject_case)
        eligible = self._eligible()
        partial = self._create_case(self.ticket, user=self.creator,
                                    requested_items=self.item_service | self.item_gas)
        self.assertEqual(self._result(partial), 'partial')
        for other in (eligible, partial, self._create_case(self.ticket)):
            self.assertFalse(other.with_user(self.approver_a).can_reject_case)
            with self.assertRaises(UserError):
                other.with_user(self.approver_a).action_open_reject_wizard()

    def test_62_reject_reason_and_history(self):
        """Q46: reason required, note required for Other; status Rejected with reason / note /
        user / date and a chatter note; the Helpdesk ticket is unchanged (Q47)."""
        case = self._not_eligible()
        stage = self.ticket.stage_id
        with self.assertRaises(UserError):
            self._reject(case, reason='other', note=' ')
        self.assertEqual(case.state, 'eligibility_checked')
        self._reject(case, reason='other', note='Customer used the unit outdoors')
        self.assertEqual((case.state, case.rejection_reason, case.rejection_note,
                          case.rejected_by_id), ('rejected', 'other',
                                                 'Customer used the unit outdoors',
                                                 self.approver_a))
        self.assertTrue(case.rejected_date)
        self.assertIn('rejected by wcase_case_approver_a: Other', case.message_ids[:1].body)
        self.assertEqual(self.ticket.stage_id, stage)

    def test_63_open_activities_closed(self):
        """Open escalation activities are closed on rejection."""
        self.policy.write({'repeated_failure_threshold': 1, 'repeated_failure_period_days': 90})
        self.company.warranty_escalation_user_ids = self.approver_b
        self._create_case(self.ticket)
        case = self._create_case(self.ticket, user=self.creator)
        self.assertEqual(self._result(case), 'manual_review')
        activities = case.escalation_activity_ids
        self.assertTrue(activities)
        self._reject(case, reason='duplicate')
        self.assertFalse(activities.exists().filtered('active'))
        self.assertFalse(case.escalation_pending)

    def test_64_free_services_released(self):
        """Q48: linked free services become available for another case, status unchanged."""
        service = self.card.service_entitlement_ids.sorted('service_no')[:1]
        with self._today(date(2026, 11, 1)):
            case = self._create_case(self.ticket, user=self.creator, case_type='free_service',
                                     service_entitlement_ids=[(6, 0, service.ids)])
        self.assertEqual(service.helpdesk_ticket_id, self.ticket)
        service.sudo().state = 'expired'
        self.assertEqual(self._result(case), 'not_eligible')
        self._reject(case, reason='no_free_service')
        self.assertFalse(service._warranty_active_cases())
        self.assertFalse(service.helpdesk_ticket_id)
        self.assertEqual(service.state, 'expired')
        self.assertIn(case, service.warranty_case_ids, 'link kept as history')
        self.assertIn('Free services released', case.message_ids[:1].body)

    def test_65_rejected_is_final(self):
        """A Rejected case cannot be changed, checked, approved, rejected again or deleted;
        the chatter stays usable."""
        case = self._not_eligible()
        self._reject(case)
        with self.assertRaises(UserError):
            case.customer_complaint = 'changed'
        with self.assertRaises(UserError):
            case.with_user(self.helpdesk_user).action_check_eligibility()
        with self.assertRaises(UserError):
            case.with_user(self.approver_b).action_approve_case()
        with self.assertRaises(UserError):
            case.with_user(self.approver_b).action_open_reject_wizard()
        with self.assertRaises(UserError):
            case.unlink()
        case.message_post(body='Customer informed', message_type='comment',
                          author_id=self.env.user.partner_id.id, email_from='a@example.com')
        self.assertEqual(case.state, 'rejected')

    def test_67_check_button_hidden_for_approvers(self):
        """UI only: Check Eligibility is hidden when Approve Case or Reject Case is shown;
        creators, latest checkers and ordinary Helpdesk users keep it."""
        from lxml import etree
        arch = etree.fromstring(self.env['warranty.case'].get_view(view_type='form')['arch'])
        [button] = arch.xpath("//button[@name='action_check_eligibility']")
        invisible = button.get('invisible')
        self.assertIn('can_approve_case', invisible)
        self.assertIn('can_reject_case', invisible)
        # Option C: Approve / Reject Case sit right before Check Eligibility, same style.
        names = [b.get('name') for b in arch.xpath('//header/button')]
        position = names.index('action_check_eligibility')
        self.assertEqual(names[position - 2:position],
                         ['action_approve_case', 'action_open_reject_wizard'])
        for name in ('action_approve_case', 'action_open_reject_wizard'):
            [other] = arch.xpath("//header/button[@name='%s']" % name)
            self.assertIn('btn-primary', other.get('class'))
        ordinary = self._user('wcase_ordinary_helpdesk', 'helpdesk.group_helpdesk_user')

        def check_hidden(case, user):
            case = case.with_user(user)
            return case.can_approve_case or case.can_reject_case

        eligible = self._eligible()
        rejectable = self._not_eligible()
        for case in (eligible, rejectable):
            self.assertTrue(check_hidden(case, self.approver_a), 'authorized approver')
            for user in (self.creator, self.helpdesk_user, ordinary):
                self.assertFalse(check_hidden(case, user), user.login)

    def test_66_multi_company(self):
        """Another company's users cannot reject the case."""
        case = self._not_eligible()
        with self.assertRaises(AccessError):
            case.with_user(self.foreign_user).action_open_reject_wizard()
        with self.assertRaises(AccessError):
            case.with_user(self.foreign_user)._warranty_reject('duplicate', '')
