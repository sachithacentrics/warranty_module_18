from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation

from .test_warranty_case_eligibility import TestWarrantyCaseEligibility


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCaseCoverage(TestWarrantyCaseEligibility):
    """Part 3.4 - service coverage and free service entitlement eligibility (approved Q22-Q28)."""

    def setUp(self):
        super().setUp()
        self.card = self._card()
        self.s1, self.s2, self.s3 = self.card.service_entitlement_ids.sorted('service_no')
        self.ticket = self._ticket(warranty_product_id=self.product.id)

    def _check(self, case):
        with self._today(date(2026, 11, 1)):
            return super()._check(case)

    def _linked_case(self, services, **vals):
        with self._today(date(2026, 11, 1)):
            return self._case(self.ticket, service_entitlement_ids=[(6, 0, services.ids)], **vals)

    def test_31_all_covered_continues(self):
        """All requested items covered: the check continues, never the final Eligible."""
        case = self._case(self.ticket, requested_items=self.item_service | self.item_pcb)
        self.assertFalse(self._check(case))
        self.assertEqual(case.state, 'eligibility_checked')
        log = self._last_log(case)
        self.assertIn('All requested items are covered: Case Standard Service, Case PCB', log)
        self.assertIn('not needed', log)
        self.assertIn('the repeated failure check follows', log)

    def test_32_partial_and_not_eligible(self):
        """Covered + excluded: Partial; only excluded: Not Eligible; both stop (Q28)."""
        case = self._case(self.ticket, requested_items=self.item_service | self.item_gas)
        self.assertEqual(self._check(case), 'partial')
        self.assertIn('Excluded (chargeable quotation for the excluded items): Case Gas Refill',
                      self._last_log(case))
        self.assertNotIn('the repeated failure check follows', self._last_log(case))
        case.requested_item_ids = self.item_gas
        self.assertEqual(self._check(case), 'not_eligible')
        case.requested_item_ids = self.item_service
        self.assertFalse(self._check(case), 'reset by a new check')

    def test_33_manual_review_coverage(self):
        """Undefined item (Q23), no requested items (Q24, also Free Service cases), an item
        both covered and excluded: Manual Review."""
        case = self._case(self.ticket, requested_items=self.item_service | self.item_undefined)
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('Coverage not defined in policy Case Policy for: Case Installation Kit',
                      self._last_log(case))
        free = self._linked_case(self.s1, case_type='free_service',
                                 requested_items=self.env['warranty.coverage.item'])
        self.assertEqual(self._check(free), 'manual_review')
        self.assertIn('No Requested Items', self._last_log(free))
        self.policy.excluded_item_ids = [(4, self.item_pcb.id)]
        case.requested_item_ids = self.item_pcb
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('both a Covered and an Excluded Item', self._last_log(case))

    def test_34_card_without_policy(self):
        """P5 card (own values, no policy): coverage cannot be resolved - Manual Review (Q27);
        the card is not changed."""
        product = self.env['product.product'].create({
            'name': 'Case Own Values AC', 'type': 'service', 'warranty_applicable': True,
            'categ_id': self.env['product.category'].create({'name': 'Case No Policy'}).id})
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'order_line': [(0, 0, {'product_id': product.id})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, date(2026, 7, 15))
        card.action_confirm_warranty()
        self.assertFalse(card.policy_id)
        ticket = self._ticket(warranty_product_id=product.id)
        case = self._case(ticket)
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('has no warranty policy', self._last_log(case))
        self.assertFalse(card.policy_id)

    def test_35_free_service_linked_available(self):
        """Free Service case or any case with linked free services: the linked services must be
        available; linking changes nothing on the service (Q25)."""
        before = self.s1.read(['state', 'scheduled_date', 'due_date'])
        case = self._linked_case(self.s1, case_type='free_service')
        self.assertFalse(self._check(case))
        self.assertIn('Free service entitlement available: %s' % self.s1.name, self._last_log(case))
        self.assertEqual(self.s1.read(['state', 'scheduled_date', 'due_date']), before)
        complaint = self._linked_case(self.s2)
        self.assertFalse(self._check(complaint))
        self.assertIn('Free service entitlement available', self._last_log(complaint))

    def test_36_free_service_without_link(self):
        """Free Service case without a linked service: Manual Review, nothing linked
        automatically (Q26)."""
        case = self._case(self.ticket, case_type='free_service')
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('select the available free service', self._last_log(case))
        self.assertFalse(case.service_entitlement_ids)

    def test_40_linked_service_of_another_card(self):
        """Cross-card service merge (approved Option A): a free service of another card of
        the same customer and site is checked with its own card and accepted; another site
        gives Manual Review naming the card, service and reason (D1 / D6)."""
        other = self._card().service_entitlement_ids.sorted('service_no')[:1]
        case = self._linked_case(self.s1 | other, case_type='free_service')
        self.assertFalse(self._check(case))
        self.assertEqual(case.service_card_ids, self.s1.warranty_card_id | other.warranty_card_id)
        elsewhere = self._card(site=self.site_b).service_entitlement_ids.sorted('service_no')[:1]
        case = self._linked_case(self.s2 | elsewhere, case_type='free_service')
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('%s (%s): service address' % (elsewhere.warranty_card_id.name,
                                                    elsewhere.name), self._last_log(case))

    def test_37_linked_service_no_longer_available(self):
        """Linked service expired / missed after grace: Not Eligible (convert / reject, 3.6)."""
        case = self._linked_case(self.s1, case_type='free_service')
        self.s1.sudo().state = 'expired'
        self.assertEqual(self._check(case), 'not_eligible')
        self.assertIn('no longer available', self._last_log(case))
        self.s1.sudo().write({'state': 'missed', 'grace_period_end_date': date(2026, 10, 1)})
        self.assertEqual(self._check(case), 'not_eligible')
        self.s1.sudo().grace_period_end_date = date(2026, 12, 1)
        self.assertFalse(self._check(case), 'missed within grace is available')

    def test_38_rule_c_and_coverage_first(self):
        """One active case per free service still enforced; coverage is checked before the free
        service entitlement."""
        case = self._linked_case(self.s1, case_type='free_service',
                                 requested_items=self.item_gas)
        with self.assertRaises(ValidationError):
            self._linked_case(self.s1)
        self.s1.sudo().state = 'expired'
        self.assertEqual(self._check(case), 'not_eligible')
        self.assertNotIn('no longer available', self._last_log(case))
        self.assertIn('Case Gas Refill', self._last_log(case))

    def test_39_payment_stop_before_coverage(self):
        """A 3.3 payment stop prevents the 3.4 checks."""
        self.policy.write({'payment_check_required': True, 'overdue_claim_handling': 'hold'})
        case = self._case(self.ticket, requested_items=self.item_gas)
        self.assertEqual(self._check(case), 'pending_payment')
        self.assertNotIn('Excluded', self._last_log(case))
