from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from .common import confirm_and_group, set_installation

MODES = ('warranty_only', 'free_services', 'amc', 'amc_free_services')


@tagged('post_install', '-at_install', 'warranty_policy')
class TestWarrantyScopeVisibility(TransactionCase):
    """BA decision 2026-10-28: the company Warranty Scope Mode no longer limits warranty
    functionality. The company field is kept (unused, not in Settings); free services follow
    the resolved count, Auto-create Services and the existing business rules in every mode."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Other Scope Company'})
        cls.company.write({
            'warranty_scope_mode': 'warranty_only',
            'default_card_grouping_mode': 'per_so',
            'default_warranty_policy_id': False,
            'default_warranty_basis': 'period',
            'default_start_criterion': 'installation',
            'default_warranty_duration': 12,
            'default_warranty_duration_unit': 'months',
            'default_free_service_count': 2,
            'default_free_service_period': 12,
            'default_free_service_period_unit': 'months',
            'default_schedule_method': 'equal_interval',
            'warranty_auto_create_services': True,
        })
        cls.categ = cls.env['product.category'].create({'name': 'Scope ACs'})
        cls.product = cls.env['product.product'].create({
            'name': 'Scope AC', 'type': 'service', 'categ_id': cls.categ.id,
            'warranty_applicable': True, 'default_warranty_period': 12,
            'default_warranty_period_unit': 'months', 'default_free_service_count': 2,
            'free_service_frequency': 6, 'free_service_frequency_unit': 'months'})
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': 'Scope Pricelist', 'company_id': cls.company.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Scope Customer'})

    def _card(self, product=None):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'pricelist_id': self.pricelist.id,
            'order_line': [(0, 0, {'product_id': (product or self.product).id,
                                   'product_uom_qty': 1})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, date(2026, 7, 15))
        card.action_confirm_warranty()
        return card

    @staticmethod
    def _arch(env, model):
        return ' '.join(env[model].get_view(view_type='form')['arch'].split())

    def test_01_company_field_kept_settings_field_removed(self):
        """The company field and its values are kept; Settings no longer shows or edits it."""
        self.assertIn('warranty_scope_mode', self.env['res.company']._fields)
        self.assertNotIn('warranty_scope_mode', self.env['res.config.settings']._fields)
        self.company.warranty_scope_mode = 'amc'
        self.assertEqual(self.company.warranty_scope_mode, 'amc')
        arch = self._arch(self.env, 'res.config.settings')
        self.assertNotIn('warranty_scope_mode', arch)
        self.assertIn('<block title="Free Service Settings" name="warranty_free_service_settings">',
                      arch)
        self.assertIn('<block title="Free Service Monitoring" '
                      'name="warranty_service_monitoring_settings">', arch)

    def test_02_free_service_sections_always_shown(self):
        """No Scope Mode condition remains on product, category, pricelist and card."""
        for model in ('product.template', 'product.category', 'product.pricelist',
                      'warranty.card'):
            self.assertNotIn('warranty_free_services_enabled', self._arch(self.env, model), model)
            self.assertNotIn('warranty_free_services_enabled', self.env[model]._fields, model)
        template = self._arch(self.env, 'product.template')
        self.assertIn('name="warranty_free_services" invisible="not warranty_applicable"',
                      template)
        self.assertIn('name="warranty_worksheet_template_id"', template)
        self.assertIn('name="free_service_configuration"', self._arch(self.env, 'product.category'))
        # UX 2026-11-09: the card tab follows the card's own free services (count or
        # entitlements), never the company Scope Mode.
        self.assertIn('<page string="Free Services" name="free_services" '
                      'invisible="not free_services_allowed and not service_entitlement_ids">',
                      self._arch(self.env, 'warranty.card'))

    def test_03_values_kept_when_switching(self):
        """Changing the kept company field never resets the free service values."""
        template = self.product.product_tmpl_id
        before = (template.default_free_service_count, template.free_service_frequency,
                  self.company.default_free_service_count)
        for mode in ('warranty_only', 'free_services', 'amc', 'warranty_only'):
            self.company.warranty_scope_mode = mode
        self.assertEqual((template.default_free_service_count, template.free_service_frequency,
                          self.company.default_free_service_count), before)

    def test_04_free_services_in_every_mode(self):
        """Every former Scope Mode: the resolved count with Auto-create Services gives the
        entitlements 1..N (no Scope Mode limitation)."""
        for mode in MODES:
            self.company.warranty_scope_mode = mode
            card = self._card()
            self.assertTrue(card.free_services_included, mode)
            self.assertEqual(card.service_entitlement_ids.mapped('service_no'), [1, 2], mode)
            self.assertEqual(card.free_services_balance, 2, mode)

    def test_05_count_and_auto_create_still_respected(self):
        """Count 0: no free services; Auto-create Services off: none generated automatically
        (added manually up to the count); the count limit still applies."""
        zero = self.env['product.product'].create({
            'name': 'Scope AC Zero', 'type': 'service', 'categ_id': self.categ.id,
            'warranty_applicable': True, 'default_warranty_period': 12,
            'default_warranty_period_unit': 'months'})
        self.company.default_free_service_count = 0
        card = self._card(zero)
        self.assertFalse(card.free_services_included)
        self.assertFalse(card.service_entitlement_ids)
        with self.assertRaises(ValidationError):
            self.env['warranty.service.entitlement'].create(
                {'warranty_card_id': card.id, 'service_no': 1})

        self.company.write({'default_free_service_count': 2,
                            'warranty_auto_create_services': False})
        card = self._card()
        self.assertTrue(card.free_services_included)
        self.assertFalse(card.service_entitlement_ids)
        Entitlement = self.env['warranty.service.entitlement']
        Entitlement.create([{'warranty_card_id': card.id, 'service_no': number}
                            for number in (1, 2)])
        with self.assertRaises(ValidationError):
            Entitlement.create({'warranty_card_id': card.id, 'service_no': 3})

    def test_06_no_duplicates_existing_cards_unchanged(self):
        """Generating again never duplicates; switching the kept field leaves cards and their
        entitlements unchanged."""
        card = self._card()
        services = card.service_entitlement_ids
        card._generate_free_service_entitlements()
        self.assertEqual(card.service_entitlement_ids, services)
        for mode in MODES:
            self.company.warranty_scope_mode = mode
            card.invalidate_recordset()
            self.assertEqual(card.service_entitlement_ids, services, mode)
            self.assertEqual(card.free_services_allowed, 2, mode)
        self.assertEqual(set(services.mapped('state')) - {'draft', 'pending'}, set())
