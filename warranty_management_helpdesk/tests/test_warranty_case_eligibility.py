from datetime import date, datetime

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation

from .test_warranty_case import TestWarrantyCase


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCaseEligibility(TestWarrantyCase):
    """Part 3.2 - warranty card, serial number and validity check (approved Q8-Q14)."""

    def _set_ticket_date(self, ticket, day):
        self.env.cr.execute("UPDATE helpdesk_ticket SET create_date = %s WHERE id = %s",
                            [datetime.combine(day, datetime.min.time().replace(hour=12)),
                             ticket.id])
        ticket.invalidate_recordset(['create_date'])

    def _check(self, case):
        """Result of the check; False when every 3.2-3.4 step passed (the 3.5 repeated
        failure check then gives Eligible when no escalation rule is configured)."""
        case.with_user(self.helpdesk_user).action_check_eligibility()
        return False if case.eligibility_result == 'eligible' else case.eligibility_result

    def _last_log(self, case):
        return case.message_ids.filtered(
            lambda m: 'Eligibility check' in (m.body or ''))[:1].body

    def _case(self, ticket=None, **vals):
        return self._create_case(ticket or self._ticket(), **vals)

    def _usage_card(self, limit=2000):
        policy = self.env['warranty.policy'].create({
            'name': 'Usage Case Policy', 'warranty_duration': 12,
            'warranty_duration_unit': 'months', 'warranty_basis': 'usage',
            'usage_limit': limit, 'usage_unit': 'operating_hours',
            'covered_item_ids': [(6, 0, self.item_service.ids)]})
        product = self.env['product.product'].create({
            'name': 'Usage Case AC', 'type': 'service', 'warranty_applicable': True})
        product.product_tmpl_id.warranty_policy_id = policy
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'order_line': [(0, 0, {'product_id': product.id})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, date(2026, 7, 15))
        card.action_confirm_warranty()
        return card, product

    # ------------------------------------------------------------------ find card
    def test_11_find_card(self):
        """Card found from the linked service, the serial (unit / kit serials), the product,
        or selected manually; written on the case; ticket panel shows card / unit."""
        card = self._card()
        lot = self.env['stock.lot'].create({'name': 'OUT-AC-0789', 'product_id': self.product.id})
        card.unit_warranty_ids.serial_ids = lot
        with self._today(date(2026, 11, 1)):
            by_service = self._case(service_entitlement_ids=[(6, 0, card.service_entitlement_ids[:1].ids)],
                                    serial_id=lot.id)
        by_serial = self._case(serial_id=lot.id)
        by_product = self._case(product_id=self.product.id, serial_id=lot.id)
        for case in (by_service, by_serial, by_product):
            self.assertFalse(self._check(case), self._last_log(case))
            self.assertEqual((case.state, case.warranty_card_id, case.warranty_unit_id),
                             ('eligibility_checked', card, card.unit_warranty_ids))
        ticket = self._ticket(warranty_product_id=self.product.id, warranty_serial_id=lot.id)
        self.assertEqual((ticket.warranty_card_id, ticket.warranty_unit_id),
                         (card, card.unit_warranty_ids))

    def test_12_card_not_found_or_several(self):
        """No card -> Manual Review; several cards for customer + product -> Manual Review
        (never an arbitrary card, Q12); selecting the unit then passes; other customer /
        company cards are never found."""
        self._unrelated_card()
        case = self._case(product_id=self.product.id)
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('No warranty card found', self._last_log(case))
        self._card(partner=self.other_customer)
        self.assertEqual(self._check(case), 'manual_review', 'other customer card not found')
        first, second = self._card(), self._card()
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('Several warranty cards', self._last_log(case))
        self.assertFalse(case.warranty_card_id)
        case.warranty_unit_id = second.unit_warranty_ids
        self.assertFalse(self._check(case))
        self.assertEqual(case.warranty_card_id, second)
        self.assertFalse(self.env['warranty.case']._warranty_find_card(
            self.customer, self.other_company, self.product)[0])

    # ------------------------------------------------------------------ serial
    def test_13_serial_rules(self):
        """Serial mismatch -> Manual Review; missing serial on a unit with serials (tracked /
        kit) -> Manual Review; product without serials -> serial check skipped."""
        card = self._card()
        lot = self.env['stock.lot'].create({'name': 'IN-AC-0001', 'product_id': self.product.id})
        wrong = self.env['stock.lot'].create({'name': 'IN-AC-9999', 'product_id': self.product.id})
        case = self._case(product_id=self.product.id)
        self.assertFalse(self._check(case))
        self.assertIn('serial check skipped', self._last_log(case))
        card.unit_warranty_ids.serial_ids = lot
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('serial number is required', self._last_log(case))
        case.serial_id = wrong
        case.warranty_card_id = card
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('does not match', self._last_log(case))
        case.serial_id = lot
        self.assertFalse(self._check(case))

    # ------------------------------------------------------------------ card status
    def test_14_card_status(self):
        """Card Draft / Ready -> Manual Review with the confirmation message (Q8); Suspended /
        Expired / Cancelled -> Not Eligible (Q14)."""
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'order_line': [(0, 0, {'product_id': self.product.id})]})
        confirm_and_group(order)
        draft = order.warranty_card_ids
        self.assertIn(draft.state, ('draft', 'pending_installation', 'ready'))
        self._unrelated_card()
        case = self._case(product_id=self.product.id)
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('not confirmed yet', self._last_log(case))
        set_installation(draft, date(2026, 7, 15))
        draft.action_confirm_warranty()
        self.assertFalse(self._check(case))
        for state in ('suspended', 'expired', 'cancelled'):
            draft.sudo().state = state
            self.assertEqual(self._check(case), 'not_eligible', state)

    # ------------------------------------------------------------------ validity
    def test_15_period_validity_by_ticket_date(self):
        """Period basis: Warranty Start <= ticket creation date <= Warranty End (Q10), not
        today's date."""
        card = self._card()
        self.assertEqual((card.warranty_start_date, card.warranty_end_date),
                         (date(2026, 7, 15), date(2027, 7, 14)))
        ticket = self._ticket(warranty_product_id=self.product.id)
        case = self._case(ticket)
        for day, result in ((date(2026, 7, 14), 'out_of_warranty'), (date(2026, 7, 15), False),
                            (date(2027, 7, 14), False), (date(2027, 7, 15), 'out_of_warranty')):
            self._set_ticket_date(ticket, day)
            self.assertEqual(self._check(case), result, day)
        self.assertIn('outside the warranty period', self._last_log(case))

    def test_16_usage_validity(self):
        """Usage basis: Current Usage required (Manual Review), <= unit usage limit passes,
        above -> Out of Warranty (Q9)."""
        card, product = self._usage_card()
        self.assertEqual((card.warranty_basis, card.unit_warranty_ids.usage_limit),
                         ('usage', 2000))
        case = self._case(product_id=product.id)
        self.assertEqual((case.warranty_basis, case.usage_unit), (False, False))
        self.assertEqual(self._check(case), 'manual_review')
        self.assertEqual((case.warranty_basis, case.usage_unit), ('usage', 'operating_hours'))
        self.assertIn('Current Usage', self._last_log(case))
        case.current_usage = 2000
        self.assertFalse(self._check(case))
        case.current_usage = 2000.5
        self.assertEqual(self._check(case), 'out_of_warranty')

    # ------------------------------------------------------------------ case types / runs
    def test_17_case_types(self):
        """AMC -> Manual Review (Q7); Chargeable Inspection / Repair are not checked (3.6);
        the four warranty types are checked (Q13)."""
        self._card()
        ticket = self._ticket(warranty_product_id=self.product.id)
        amc = self._case(ticket, case_type='amc')
        self.assertEqual(self._check(amc), 'manual_review')
        self.assertIn('AMC', self._last_log(amc))
        for case_type in ('chargeable_inspection', 'chargeable_repair'):
            with self.assertRaises(UserError):
                self._case(ticket, case_type=case_type).action_check_eligibility()
        for case_type in ('warranty_complaint', 'replacement', 'repeat_complaint'):
            self.assertFalse(self._check(self._case(ticket, case_type=case_type)), case_type)
        # Part 3.4 Q26: a Free Service case needs a linked free service.
        self.assertEqual(self._check(self._case(ticket, case_type='free_service')),
                         'manual_review')

    def test_18_rerun_log_and_status(self):
        """Every run is logged in the chatter; the result is reset by a new run; the status is
        Eligibility Checked; all passed is not the final Eligible; other statuses refused."""
        card = self._card()
        case = self._case(product_id=self.product.id)
        card.sudo().state = 'suspended'
        self.assertEqual(self._check(case), 'not_eligible')
        card.sudo().state = 'confirmed'
        self.assertFalse(self._check(case))
        # Part 3.5: Eligible once all checks (incl. repeated failure) passed.
        self.assertEqual(case.eligibility_result, 'eligible')
        self.assertEqual(case.state, 'eligibility_checked')
        logs = case.message_ids.filtered(lambda m: 'Eligibility check' in (m.body or ''))
        self.assertEqual(len(logs), 2)
        self.assertIn('the payment check follows', logs[0].body)
        case.sudo().state = 'approved'
        with self.assertRaises(UserError):
            case.action_check_eligibility()

    def test_19_access_and_part12_unchanged(self):
        """Only users who can edit cases run the check; the card, units and services are only
        read (Part 1 / 2 unchanged)."""
        card = self._card()
        case = self._case(product_id=self.product.id)
        with self.assertRaises(AccessError):
            case.with_user(self.internal_user).action_check_eligibility()
        before = (card.state, card.warranty_end_date, card.unit_warranty_ids.state,
                  card.service_entitlement_ids.mapped('state'))
        self._check(case)
        self.assertEqual(before, (card.state, card.warranty_end_date,
                                  card.unit_warranty_ids.state,
                                  card.service_entitlement_ids.mapped('state')))
