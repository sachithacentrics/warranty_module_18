from datetime import date, timedelta
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation


@tagged('post_install', '-at_install', 'amc')
class TestAmcWarrantyLink(TransactionCase):
    """AMC <-> warranty integration (AMC-A03 / A04 / A06 / A07 / C07, SRS 14; docs/17)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.company.write({
            'warranty_auto_create_services': False, 'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so', 'default_warranty_basis': 'period',
            'default_start_criterion': 'installation', 'default_warranty_duration': 0,
            'amc_auto_create_mode': 'none', 'amc_offer_on_warranty_expiry': False,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'AMC Warranty Customer'})
        cls.pricelist = cls.env['product.pricelist'].create({'name': 'AMC W Retail',
                                                             'company_id': cls.company.id})
        cls.policy = cls.env['warranty.policy'].create({
            'name': 'AMC W Policy', 'warranty_duration': 12, 'warranty_duration_unit': 'months',
            'free_service_count': 0})
        cls.categ = cls.env['product.category'].create({'name': 'AMC W A/C',
                                                        'warranty_policy_id': cls.policy.id})
        cls.product = cls.env['product.product'].create({
            'name': 'AMC W A/C', 'type': 'service', 'categ_id': cls.categ.id,
            'warranty_applicable': True, 'warranty_start_criterion': 'installation',
            'default_warranty_period': 12, 'default_warranty_period_unit': 'months',
            'default_free_service_count': 0})
        cls.plan = cls.env['amc.plan'].create({
            'name': 'AMC W Plan', 'company_id': cls.company.id, 'visit_count': 2,
            'frequency_value': 2, 'billing_plan_id': cls.env.ref(
                'amc_management.billing_plan_upfront').id})
        cls.company.amc_default_plan_id = cls.plan

    def _card(self, quantity=2, start=None, confirm=True):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'pricelist_id': self.pricelist.id,
            'order_line': [Command.create({'product_id': self.product.id,
                                           'product_uom_qty': quantity})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, start or date.today() - timedelta(days=30))
        if confirm:
            card.action_confirm_warranty()
        return card

    def test_tc080_mode_none_creates_nothing(self):
        """TC-080 / REG-03: with mode None the warranty confirmation is unchanged."""
        card = self._card()
        self.assertEqual(card.state, 'confirmed')
        self.assertFalse(card.amc_contract_ids)
        self.assertFalse(card.amc_opportunity_ids)

    def test_tc081_auto_create_draft_contract(self):
        """TC-081 / AMC-A03 / A04 / A06 / C07: mode Draft AMC Contract creates one Draft
        contract per card covering its units, never Active, starting after the warranty."""
        self.company.amc_auto_create_mode = 'contract'
        card = self._card(quantity=2)
        contract = card.amc_contract_ids
        self.assertEqual(len(contract), 1)
        self.assertEqual(contract.state, 'draft')
        self.assertFalse(contract.visit_ids)
        self.assertEqual(contract.plan_id, self.plan)
        self.assertEqual(contract.line_ids.warranty_unit_id, card.unit_warranty_ids)
        self.assertEqual(contract.start_date, card.warranty_end_date + timedelta(days=1))
        self.assertEqual(contract.warranty_card_ids, card)
        self.assertEqual(card.amc_count, 1)

    def test_tc082_auto_create_opportunity(self):
        """TC-082 / AMC-A04: mode Draft AMC Opportunity; Won creates the contract with units."""
        self.company.amc_auto_create_mode = 'opportunity'
        card = self._card(quantity=1)
        opportunity = card.amc_opportunity_ids
        self.assertEqual(len(opportunity), 1)
        self.assertEqual(opportunity.state, 'new')
        opportunity.action_create_contract()
        contract = opportunity.contract_ids
        self.assertEqual(contract.source_warranty_card_id, card)
        self.assertEqual(contract.line_ids.warranty_unit_id, card.unit_warranty_ids)

    def test_tc083_auto_create_failure_never_blocks(self):
        """TC-083: an AMC auto-create error is logged; the warranty is still confirmed."""
        self.company.amc_auto_create_mode = 'contract'
        card = self._card(confirm=False)
        with patch.object(type(card), '_amc_create_contract',
                          side_effect=UserError("forced failure")):
            card.action_confirm_warranty()
        self.assertEqual(card.state, 'confirmed')
        self.assertFalse(card.amc_contract_ids)

    def test_tc084_convert_to_amc(self):
        """TC-084 / AMC-A07: Convert to AMC on a confirmed card; a second call opens the same
        contract; Draft cards cannot be converted."""
        card = self._card()
        action = card.action_convert_to_amc()
        contract = self.env['amc.contract'].browse(action['res_id'])
        self.assertEqual(contract.source_warranty_card_id, card)
        self.assertEqual(card.action_convert_to_amc()['res_id'], contract.id)
        draft = self._card(confirm=False)
        with self.assertRaises(UserError):
            draft.action_convert_to_amc()

    def test_tc085_expired_card_conversion_starts_at_activation(self):
        """TC-085 / AMC-A08 / C07: an expired warranty converts with no retroactive start."""
        card = self._card(start=date.today() - timedelta(days=400))
        card._warranty_apply_expiry(date.today())
        self.assertEqual(card.state, 'expired')
        contract = self.env['amc.contract'].browse(card.action_convert_to_amc()['res_id'])
        self.assertFalse(contract.start_date)

    def test_tc086_unit_covered_once(self):
        """TC-086 / AMC-E09: one warranty unit is covered by one open AMC only."""
        card = self._card(quantity=1)
        card.action_convert_to_amc()
        unit = card.unit_warranty_ids
        with self.assertRaises(ValidationError):
            self.env['amc.contract'].create({
                'partner_id': self.partner.id, 'company_id': self.company.id,
                'plan_id': self.plan.id,
                'line_ids': [Command.create({'product_id': unit.product_id.id,
                                             'warranty_unit_id': unit.id})]})

    def test_tc087_offer_on_expiry(self):
        """TC-087 / SRS 14 "Warranty expires -> offer AMC conversion if configured"."""
        self.company.amc_offer_on_warranty_expiry = True
        card = self._card(start=date.today() - timedelta(days=400))
        activities = len(card.activity_ids)
        card._warranty_apply_expiry(date.today())
        self.assertEqual(card.state, 'expired')
        self.assertGreater(len(card.activity_ids), activities)
        card._warranty_apply_expiry(date.today())
        self.assertEqual(len(card.activity_ids), activities + len(
            card._get_service_alert_users() or self.env.user))

    def test_tc088_source_card_protected(self):
        """TC-088: the source warranty card is set by the conversion only."""
        card = self._card()
        contract = self.env['amc.contract'].browse(card.action_convert_to_amc()['res_id'])
        other = self._card()
        with self.assertRaises(UserError):
            contract.write({'source_warranty_card_id': other.id})
