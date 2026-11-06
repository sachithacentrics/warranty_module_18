from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation

from .test_warranty_case import TestWarrantyCase


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCaseCardSelection(TestWarrantyCase):
    """Approved card selection fix: manual Warranty Card / Unit Warranty choices and their
    server-side validation; the Part 3.2 automatic lookup unchanged (Q8 / Q14)."""

    def _choices(self, case, fname):
        values = {'company_id': case.company_id.id,
                  'commercial_partner_id': case.commercial_partner_id.id,
                  'product_id': case.product_id.id, 'serial_id': case.serial_id.id,
                  'warranty_card_id': case.warranty_card_id.id}
        field = case._fields[fname]
        return self.env[field.comodel_name].search(safe_eval(field.domain, values))

    def _as_user(self, case):
        return case.with_user(self.helpdesk_user)

    def _draft_card(self):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'order_line': [(0, 0, {'product_id': self.product.id})]})
        confirm_and_group(order)
        return order.warranty_card_ids

    def test_01_card_choices(self):
        """Only Confirmed and Expired cards of the case company / customer / product are offered;
        Draft, other customer, other company and other product cards are not."""
        card = self._card()
        draft = self._draft_card()
        expired = self._card()
        expired.sudo().state = 'expired'
        foreign_customer = self._card(partner=self.other_customer)
        fan = self._card(product=self.other_product)
        other_company = self._card()
        other_company.sudo().company_id = self.other_company
        case = self._create_case(self._ticket(), product_id=self.product.id)
        choices = self._choices(case, 'warranty_card_id')
        self.assertIn(card, choices)
        self.assertIn(expired, choices)
        for hidden in (draft, foreign_customer, fan, other_company):
            self.assertNotIn(hidden, choices, hidden.name)
        no_product = self._create_case(self._ticket())
        self.assertIn(fan, self._choices(no_product, 'warranty_card_id'),
                      'no product on the case: no product filter')
        self.assertEqual(self._choices(case, 'warranty_unit_id'),
                         (card | expired).unit_warranty_ids)

    def test_02_multi_product_card_and_units(self):
        """Multi-product card (no card product): offered through its unit products; the unit
        choices are the units of the selected card and product."""
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {'product_id': self.product.id}),
                           (0, 0, {'product_id': self.other_product.id})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, date(2026, 7, 15))
        card.action_confirm_warranty()
        self.assertFalse(card.product_id)
        case = self._create_case(self._ticket(), product_id=self.other_product.id)
        self.assertIn(card, self._choices(case, 'warranty_card_id'))
        fan_unit = card.unit_warranty_ids.filtered(lambda u: u.product_id == self.other_product)
        self._as_user(case).warranty_card_id = card
        self.assertEqual(self._choices(case, 'warranty_unit_id'), fan_unit)
        self._as_user(case).warranty_unit_id = fan_unit
        ac_unit = card.unit_warranty_ids - fan_unit
        with self.assertRaisesRegex(ValidationError, 'another product'):
            self._as_user(case).warranty_unit_id = ac_unit

    def test_03_serial_and_kit_serials(self):
        """Serial selected: only cards / units holding it (unit serials, kit Indoor / Outdoor
        serials on the same unit)."""
        card, other = self._card(), self._card()
        indoor = self.env['stock.lot'].create({'name': 'IN-K-001', 'product_id': self.product.id})
        outdoor = self.env['stock.lot'].create({'name': 'OUT-K-001', 'product_id': self.product.id})
        card.unit_warranty_ids.serial_ids = indoor | outdoor
        case = self._create_case(self._ticket(), product_id=self.product.id, serial_id=outdoor.id)
        self.assertEqual(self._choices(case, 'warranty_card_id'), card)
        self.assertEqual(self._choices(case, 'warranty_unit_id'), card.unit_warranty_ids)
        self._as_user(case).write({'warranty_card_id': card.id,
                                   'warranty_unit_id': card.unit_warranty_ids.id})
        self.assertEqual(case.warranty_card_id, card)
        with self.assertRaisesRegex(ValidationError, 'is not on warranty card'):
            self._as_user(case).warranty_card_id = other

    def test_04_server_validation(self):
        """Manual / API assignments of invalid cards or units are refused, whatever the
        context; valid ones pass."""
        card = self._card()
        draft = self._draft_card()
        foreign_customer = self._card(partner=self.other_customer)
        fan = self._card(product=self.other_product)
        other_company = self._card()
        other_company.sudo().company_id = self.other_company
        case = self._create_case(self._ticket(), product_id=self.product.id)
        user_case = self._as_user(case)
        for bad, message in ((draft, 'not Confirmed'), (foreign_customer, 'another customer'),
                             (fan, 'does not cover product'),
                             (other_company, 'another company')):
            with self.assertRaisesRegex(ValidationError, message):
                user_case.sudo(False).with_context(warranty_revalidation=True).write(
                    {'warranty_card_id': bad.id})
        with self.assertRaisesRegex(ValidationError, 'is not a unit of'):
            user_case.write({'warranty_card_id': card.id,
                             'warranty_unit_id': fan.unit_warranty_ids.id})
        with self.assertRaisesRegex(ValidationError, 'not Confirmed'):
            user_case.write({'warranty_card_id': False,
                             'warranty_unit_id': draft.unit_warranty_ids.id})
        user_case.write({'warranty_card_id': card.id,
                         'warranty_unit_id': card.unit_warranty_ids.id})
        self.assertEqual(case.warranty_card_id, card)

    def test_05_lookup_keeps_q8_q14(self):
        """The automatic lookup still records a Draft / Expired card (Q8 / Q14 results); a
        later edit of another field of that case is not blocked."""
        draft = self._draft_card()
        self._unrelated_card()
        case = self._create_case(self._ticket(), product_id=self.product.id)
        self._as_user(case).action_check_eligibility()
        self.assertEqual((case.eligibility_result, case.warranty_card_id),
                         ('manual_review', draft))
        self._as_user(case).current_usage = 10
        set_installation(draft, date(2026, 7, 15))
        draft.action_confirm_warranty()
        draft.sudo().state = 'expired'
        self._as_user(case).action_check_eligibility()
        self.assertEqual((case.eligibility_result, case.warranty_card_id),
                         ('not_eligible', draft))

    def test_06_onchange_clears_incompatible(self):
        """Changing the product / serial in the form clears a card / unit that no longer
        matches; a matching one is kept."""
        card = self._card()
        lot = self.env['stock.lot'].create({'name': 'IN-OC-001', 'product_id': self.product.id})
        card.unit_warranty_ids.serial_ids = lot
        case = self._create_case(self._ticket(), product_id=self.product.id)
        with Form(case) as form:
            form.warranty_card_id = card
            form.warranty_unit_id = card.unit_warranty_ids
            form.serial_id = lot
            self.assertEqual(form.warranty_card_id, card)
            form.product_id = self.other_product
            self.assertFalse(form.warranty_card_id)
            self.assertFalse(form.warranty_unit_id)
