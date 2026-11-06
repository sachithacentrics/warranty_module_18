from datetime import date, timedelta

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation

from .test_warranty_case_eligibility import TestWarrantyCaseEligibility


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCaseRepeatedFailure(TestWarrantyCaseEligibility):
    """Part 3.5 - repeated failure check and final eligibility (approved Q29-Q37)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.gm = cls._user('wcase_gm')
        cls.service_manager = cls._user('wcase_service_manager')
        cls.company.warranty_escalation_user_ids = cls.gm | cls.service_manager | cls.helpdesk_user

    def setUp(self):
        super().setUp()
        self.policy.write({'repeated_failure_threshold': 2, 'repeated_failure_period_days': 90})
        self.card = self._card()
        self.unit = self.card.unit_warranty_ids
        self.ticket = self._ticket(warranty_product_id=self.product.id)

    def _result(self, case, user=None):
        case.with_user(user or self.helpdesk_user).action_check_eligibility()
        return case.eligibility_result

    def _failure(self, ticket=None, **vals):
        return self._case(ticket or self.ticket, **vals)

    def _dated_ticket(self, day):
        ticket = self._ticket(warranty_product_id=self.product.id)
        self._set_ticket_date(ticket, day)
        return ticket

    def test_41_no_rule_eligible(self):
        """No threshold / period on the policy: check not needed, Eligible (Q32 / Q34)."""
        self.policy.repeated_failure_threshold = 0
        case = self._failure()
        self.assertEqual(self._result(case), 'eligible')
        self.assertEqual((case.state, case.repeated_failure_flag), ('eligibility_checked', False))
        self.assertIn('No repeated failure escalation rule', self._last_log(case))
        self.assertIn('ready for the Service Job', self._last_log(case))
        with self.assertRaises(ValidationError):
            self.policy.repeated_failure_period_days = -1

    def test_42_threshold_and_escalation(self):
        """Current case included (Q30): 2 failures = Eligible, the 3rd exceeds threshold 2 ->
        Manual Review, flag, escalation activities (not the requester), no duplicates."""
        first = self._failure()
        self.assertEqual(self._result(first), 'eligible')
        self.assertEqual(first.repeated_failure_count, 1)
        second = self._failure(case_type='replacement')
        self.assertEqual(self._result(second), 'eligible')
        self.assertEqual(second.repeated_failure_count, 2)
        third = self._failure(case_type='repeat_complaint')
        self.assertEqual(self._result(third), 'manual_review')
        self.assertTrue(third.repeated_failure_flag and third.escalation_pending)
        self.assertEqual(third.repeated_failure_count, 3)
        self.assertIn(first.name, self._last_log(third))
        self.assertIn(second.name, self._last_log(third))
        activities = third.escalation_activity_ids
        self.assertEqual(activities.user_id, self.gm | self.service_manager)
        self.assertEqual(third.escalation_requested_by_id, self.helpdesk_user)
        self._result(third)
        self.assertEqual(third.escalation_activity_ids, activities, 'no duplicates')
        self.assertNotEqual(third.state, 'approved')

    def test_43_period_by_ticket_date(self):
        """Only failures with a ticket date within the period before this case count."""
        today = self.ticket.create_date.date()
        self._failure(self._dated_ticket(today - timedelta(days=91)))
        self._failure(self._dated_ticket(today - timedelta(days=90)))
        later = self._failure(self._dated_ticket(today + timedelta(days=1)))
        case = self._failure()
        self.assertEqual(self._result(case), 'eligible')
        self.assertEqual(case.repeated_failure_count, 2, '90 days counted, 91 days / later not')
        self.assertNotIn(later.name, self._last_log(case))

    def test_44_failure_types_and_free_service(self):
        """Free Service / AMC / chargeable / Rejected cases are not failures (Q29); a Free
        Service case is checked against the earlier failures without counting itself (Q33)."""
        self._failure(case_type='free_service')
        self._failure(case_type='amc')
        self._failure(case_type='chargeable_inspection')
        self._failure(case_type='chargeable_repair')
        self._failure().sudo().state = 'rejected'
        case = self._failure()
        self.assertEqual(self._result(case), 'eligible')
        self.assertEqual(case.repeated_failure_count, 1)
        self._failure()
        self._failure()
        self._failure()
        service = self.card.service_entitlement_ids.sorted('service_no')[:1]
        free = self._case(self.ticket, case_type='free_service',
                          service_entitlement_ids=[(6, 0, service.ids)])
        self.assertEqual(self._result(free), 'manual_review')
        self.assertEqual(free.repeated_failure_count, 4, 'case itself not a failure')
        self.assertIn('this case not a failure', self._last_log(free))

    def test_45_confirmation_for_this_case_only(self):
        """Only escalation users, never the requester, confirm; the confirmation is kept on
        this case; Check Eligibility again -> Eligible, flag kept (Q36)."""
        self._failure()
        self._failure()
        case = self._failure()
        self._result(case)
        self.assertFalse(case.with_user(self.helpdesk_user).can_confirm_escalation)
        self.assertTrue(case.with_user(self.gm).can_confirm_escalation)
        for user in (self.helpdesk_user, self.internal_user):
            with self.assertRaises(AccessError):
                case.with_user(user).action_confirm_repeated_failure()
        activities = case.escalation_activity_ids
        case.with_user(self.gm).action_confirm_repeated_failure()
        self.assertEqual((case.escalation_pending, case.escalation_confirmed_by_id,
                          case.eligibility_result), (False, self.gm, 'manual_review'))
        self.assertTrue(case.escalation_confirmed_date)
        self.assertFalse(activities.exists().filtered('active'))
        self.assertEqual(self._result(case), 'eligible')
        self.assertTrue(case.repeated_failure_flag)
        self.assertIn('Warranty confirmed by', self._last_log(case))
        other = self._failure()
        self.assertEqual(self._result(other), 'manual_review', 'confirmation of one case only')

    def test_46_kit_unit_serials_one_system(self):
        """Unit first (Q31): failures on the Indoor and the Outdoor serial of the same unit
        are the same physical system."""
        indoor = self.env['stock.lot'].create({'name': 'KIT-IN-01', 'product_id': self.product.id})
        outdoor = self.env['stock.lot'].create({'name': 'KIT-OUT-01', 'product_id': self.product.id})
        self.unit.serial_ids = indoor | outdoor
        self._failure(serial_id=indoor.id)
        self._failure(serial_id=outdoor.id)
        case = self._failure(serial_id=outdoor.id)
        self.assertEqual(self._result(case), 'manual_review')
        self.assertEqual(case.repeated_failure_count, 3)
        self.assertIn('KIT-IN-01, KIT-OUT-01', self._last_log(case))

    def test_47_multi_unit_card(self):
        """Several units without identified unit: Manual Review (Q37); the unit selected:
        only its failures count; earlier unattributable cases are listed, not counted."""
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {'product_id': self.other_product.id, 'product_uom_qty': 3})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, date(2026, 7, 15))
        card.action_confirm_warranty()
        unit_1, unit_2, __ = card.unit_warranty_ids.sorted('unit_number')
        ticket = self._ticket(warranty_product_id=self.other_product.id)
        unknown = self._case(ticket)
        unknown.warranty_card_id = card
        self.assertEqual(self._result(unknown), 'manual_review')
        self.assertIn('Physical unit not identified', self._last_log(unknown))
        self.assertIn('has 3 units', self._last_log(unknown))
        for unit in (unit_2, unit_2):
            self._case(ticket).warranty_unit_id = unit
        case = self._case(ticket)
        case.warranty_unit_id = unit_1
        self.assertEqual(self._result(case), 'eligible')
        self.assertEqual(case.repeated_failure_count, 1, 'other units not combined')
        self.assertIn('Not attributable to a physical unit, not counted: %s' % unknown.name,
                      self._last_log(case))

    def test_48_other_customer_company_not_counted(self):
        """Failures of other customers' units and of other companies are not counted; a
        Unit Warranty of another product is refused."""
        other_card = self._card(partner=self.other_customer)
        other_ticket = self._ticket(partner_id=self.other_customer.id,
                                    warranty_product_id=self.product.id)
        for __ in range(3):
            self._case(other_ticket)
        self._failure()
        case = self._failure()
        self.assertEqual(self._result(case), 'eligible')
        self.assertEqual(case.repeated_failure_count, 2)
        self.assertTrue(other_card)
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {'product_id': self.product.id}),
                           (0, 0, {'product_id': self.other_product.id})]})
        confirm_and_group(order)
        two = order.warranty_card_ids
        set_installation(two, date(2026, 7, 15))
        two.action_confirm_warranty()
        wrong = self._case(self.ticket)
        wrong.warranty_card_id = two
        wrong.warranty_unit_id = two.unit_warranty_ids.filtered(
            lambda u: u.product_id == self.other_product)
        self.assertEqual(self._result(wrong), 'manual_review')

    def test_49_earlier_stop_and_cleared_escalation(self):
        """A 3.4 stop prevents 3.5 (escalation cleared); when the threshold is no longer
        exceeded, the flag is cleared and the escalation activities closed."""
        first = self._failure()
        self._failure()
        case = self._failure()
        self.assertEqual(self._result(case), 'manual_review')
        activities = case.escalation_activity_ids
        case.requested_item_ids = self.item_gas
        self.assertEqual(self._result(case), 'not_eligible')
        self.assertFalse(case.escalation_pending)
        self.assertTrue(case.repeated_failure_flag, 'not re-evaluated when 3.5 not reached')
        self.assertFalse(activities.exists().filtered('active'))
        case.requested_item_ids = self.item_service
        first.sudo().state = 'rejected'
        self.assertEqual(self._result(case), 'eligible')
        self.assertFalse(case.repeated_failure_flag)

    def test_50_settings_and_multi_company(self):
        """Escalation users are internal users of the company; another company's users can
        neither confirm nor see the case."""
        with self.assertRaises(ValidationError):
            self.company.warranty_escalation_user_ids = [(4, self.foreign_user.id)]
        self._failure()
        self._failure()
        case = self._failure()
        self._result(case)
        with self.assertRaises(AccessError):
            case.with_user(self.foreign_user).action_confirm_repeated_failure()
        self.assertFalse(self.env['warranty.case'].with_user(self.foreign_user).search(
            [('id', '=', case.id)]))
