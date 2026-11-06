from odoo.exceptions import ValidationError
from odoo.tests import Form, TransactionCase, tagged

from .common import confirm_and_group


@tagged('post_install', '-at_install', 'warranty_policy')
class TestWarrantySettingsFallback(TransactionCase):
    """Warranty Settings: the selected Default Warranty Policy's values shown read-only;
    the company default values unchanged (U2 / U3 fallbacks, P1-P5 unchanged)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Other Fallback Company'})
        defaults = {
            'warranty_scope_mode': 'warranty_only',
            'default_card_grouping_mode': 'per_so',
            'default_warranty_policy_id': False,
            'default_warranty_basis': 'period',
            'default_start_criterion': 'invoice',
            'default_warranty_duration': 2,
            'default_warranty_duration_unit': 'years',
            'default_free_service_count': 0,
            'warranty_auto_create_services': False,
        }
        cls.company.write(defaults)
        cls.other_company.write(dict(defaults, default_start_criterion='delivery',
                                     default_warranty_duration=6,
                                     default_warranty_duration_unit='months'))
        Policy = cls.env['warranty.policy']
        cls.policy_a = Policy.create({
            'name': 'Fallback Policy A', 'warranty_basis': 'period',
            'start_date_basis': 'installation', 'warranty_duration': 12,
            'warranty_duration_unit': 'months'})
        cls.policy_b = Policy.create({
            'name': 'Fallback Policy B', 'warranty_basis': 'period',
            'start_date_basis': 'delivery', 'warranty_duration': 3,
            'warranty_duration_unit': 'years'})
        cls.partner = cls.env['res.partner'].create({'name': 'Fallback Customer'})
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': 'Fallback Pricelist', 'company_id': cls.company.id})
        cls.categ = cls.env['product.category'].create({'name': 'Fallback ACs'})

    def _defaults(self, company=None):
        company = company or self.company
        return (company.default_warranty_basis, company.default_start_criterion,
                company.default_warranty_duration, company.default_warranty_duration_unit)

    def _card(self, **product_vals):
        values = {'name': 'Fallback AC', 'type': 'service', 'categ_id': self.categ.id,
                  'warranty_applicable': True}
        values.update(product_vals)
        product = self.env['product.product'].create(values)
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'pricelist_id': self.pricelist.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})]})
        confirm_and_group(order)
        return order.warranty_card_ids

    def test_01_policy_values_displayed_readonly(self):
        """Default Policy selected: its Basis / Duration / Unit / Start Criterion are shown
        read-only (related, not stored)."""
        self.company.default_warranty_policy_id = self.policy_a
        settings = self.env['res.config.settings'].create({})
        self.assertEqual(
            (settings.warranty_default_policy_basis, settings.warranty_default_policy_duration,
             settings.warranty_default_policy_duration_unit,
             settings.warranty_default_policy_start_criterion),
            ('period', 12, 'months', 'installation'))
        for name in ('warranty_default_policy_basis', 'warranty_default_policy_duration',
                     'warranty_default_policy_duration_unit',
                     'warranty_default_policy_start_criterion'):
            field = settings._fields[name]
            self.assertTrue(field.readonly and not field.store, name)

    def test_02_switch_and_remove_policy_never_overwrites_defaults(self):
        """Changing / removing the Default Policy refreshes the display before saving; the
        company default values are never overwritten."""
        before = self._defaults()
        with Form(self.env['res.config.settings']) as form:
            form.warranty_default_policy_id = self.policy_a
            self.assertEqual(form.warranty_default_policy_duration, 12)
            form.warranty_default_policy_id = self.policy_b
            self.assertEqual((form.warranty_default_policy_duration,
                              form.warranty_default_policy_duration_unit,
                              form.warranty_default_policy_start_criterion),
                             (3, 'years', 'delivery'))
        form.save().execute()
        self.assertEqual(self.company.default_warranty_policy_id, self.policy_b)
        self.assertEqual(self._defaults(), before)
        self.assertEqual(self.policy_b.start_date_basis, 'delivery', 'policy unchanged')
        with Form(self.env['res.config.settings']) as form:
            form.warranty_default_policy_id = self.env['warranty.policy']
            self.assertFalse(form.warranty_default_policy_duration)
        form.save().execute()
        self.assertFalse(self.company.default_warranty_policy_id)
        self.assertEqual(self._defaults(), before)

    def test_03_company_specific(self):
        """Each company has its own Default Policy and default values."""
        self.company.default_warranty_policy_id = self.policy_a
        other = self.env['res.config.settings'].with_company(self.other_company).create({})
        self.assertEqual(other.company_id, self.other_company)
        self.assertFalse(other.warranty_default_policy_id)
        self.assertEqual((other.warranty_default_start_criterion, other.warranty_default_duration),
                         ('delivery', 6))
        mine = self.env['res.config.settings'].create({})
        self.assertEqual((mine.warranty_default_policy_id, mine.warranty_default_policy_duration),
                         (self.policy_a, 12))

    def test_04_u2_and_u3_unchanged(self):
        """U2: a selected policy without Basis / Start Criterion takes the company default
        values. U3 / P5: no policy at any level -> company default values (duration
        included)."""
        card = self._card()
        self.assertEqual((card.policy_id, card.policy_source, card.warranty_duration,
                          card.warranty_duration_unit, card.start_criterion),
                         (self.env['warranty.policy'], 'company', 2, 'years', 'invoice'))
        gap = self.env['warranty.policy'].create({
            'name': 'Fallback Gap Policy', 'warranty_duration': 18,
            'warranty_duration_unit': 'months'})
        self.company.default_warranty_policy_id = gap
        card = self._card()
        self.assertEqual((card.policy_id, card.policy_source, card.warranty_duration,
                          card.warranty_basis, card.start_criterion),
                         (gap, 'company_policy', 18, 'period', 'invoice'))

    def test_06_policy_selected_with_empty_default_duration(self):
        """Default Policy selected: empty company default duration / unit are accepted (UI
        and server) and stay empty; without a policy they are still required."""
        self.company.write({'default_warranty_duration': 0,
                            'default_warranty_duration_unit': False})
        arch = self.env['res.config.settings'].get_view(view_type='form')['arch']
        self.assertIn('required="not warranty_default_policy_id"', arch)
        with Form(self.env['res.config.settings']) as form:
            form.warranty_default_policy_id = self.policy_a
            self.assertEqual((form.warranty_default_policy_duration,
                              form.warranty_default_policy_duration_unit), (12, 'months'))
        form.save().execute()
        self.assertEqual(self.company.default_warranty_policy_id, self.policy_a)
        self.assertEqual((self.company.default_warranty_duration,
                          self.company.default_warranty_duration_unit), (0, False))
        settings = self.env['res.config.settings'].create({'warranty_default_policy_id': False})
        with self.assertRaises(ValidationError):
            settings.execute()

    def test_05_existing_cards_unchanged(self):
        """Changing the Default Policy never changes existing cards."""
        card = self._card()
        before = card.read(['policy_id', 'policy_source', 'warranty_duration',
                            'warranty_duration_unit', 'start_criterion', 'warranty_basis'])
        with Form(self.env['res.config.settings']) as form:
            form.warranty_default_policy_id = self.policy_b
        form.save().execute()
        card.invalidate_recordset()
        self.assertEqual(card.read(['policy_id', 'policy_source', 'warranty_duration',
                                    'warranty_duration_unit', 'start_criterion',
                                    'warranty_basis']), before)

    def test_07_policy_free_service_values_displayed_readonly(self):
        """Default Policy selected: its free service values are shown read-only and refresh
        when the policy changes; the company free service defaults are never overwritten."""
        self.company.write({'default_free_service_count': 1, 'default_free_service_period': 6,
                            'default_free_service_period_unit': 'months',
                            'default_schedule_method': 'manual'})
        self.policy_a.write({'free_service_count': 4, 'free_service_period': 1,
                             'free_service_period_unit': 'years', 'free_service_frequency': 3,
                             'free_service_frequency_unit': 'months',
                             'schedule_method': 'equal_interval'})
        names = ('warranty_default_policy_free_service_count',
                 'warranty_default_policy_free_service_period',
                 'warranty_default_policy_free_service_period_unit',
                 'warranty_default_policy_free_service_frequency',
                 'warranty_default_policy_free_service_frequency_unit',
                 'warranty_default_policy_schedule_method',
                 'warranty_default_policy_usage_limit', 'warranty_default_policy_usage_unit')
        settings = self.env['res.config.settings'].create({})
        for name in names:
            field = settings._fields[name]
            self.assertTrue(field.readonly and not field.store, name)
        with Form(self.env['res.config.settings']) as form:
            form.warranty_default_policy_id = self.policy_a
            self.assertEqual(
                tuple(form[name] for name in names[:6]),
                (4, 1, 'years', 3, 'months', 'equal_interval'))
            form.warranty_default_policy_id = self.policy_b
            self.assertEqual(form.warranty_default_policy_free_service_count, 0)
        form.save().execute()
        self.assertEqual(
            (self.company.default_free_service_count, self.company.default_free_service_period,
             self.company.default_free_service_period_unit,
             self.company.default_schedule_method), (1, 6, 'months', 'manual'))

    def test_08_only_company_or_shared_policy(self):
        """Only an active policy of the configured company or a shared one can be selected
        (settings domain + server check)."""
        arch = self.env['res.config.settings'].get_view(view_type='form')['arch']
        self.assertIn("[('company_id', 'in', [company_id, False])]", arch)
        foreign = self.env['warranty.policy'].create({
            'name': 'Other Company Policy', 'company_id': self.other_company.id,
            'warranty_duration': 1, 'warranty_duration_unit': 'years'})
        shared = self.env['warranty.policy'].create({
            'name': 'Shared Policy', 'company_id': False,
            'warranty_duration': 1, 'warranty_duration_unit': 'years'})
        with self.assertRaises(ValidationError):
            self.company.default_warranty_policy_id = foreign
        self.company.default_warranty_policy_id = shared
        self.other_company.default_warranty_policy_id = foreign
        self.policy_a.active = False
        with self.assertRaises(ValidationError):
            self.company.default_warranty_policy_id = self.policy_a

    def test_09_fallback_fields_shown_only_when_used(self):
        """With a Default Policy the company duration / free service count are hidden; the
        company Basis / Start Criterion / Free Service Period / Schedule Method stay visible
        only while the policy leaves that value empty (they fill it, P1-P5 unchanged)."""
        arch = self.env['res.config.settings'].get_view(view_type='form')['arch']
        for condition in (
                'invisible="warranty_default_policy_id and warranty_default_policy_basis"',
                'invisible="warranty_default_policy_id and '
                'warranty_default_policy_start_criterion"',
                'invisible="warranty_default_policy_id and '
                'warranty_default_policy_free_service_period and '
                'warranty_default_policy_free_service_period_unit"',
                'invisible="warranty_default_policy_id and '
                'warranty_default_policy_schedule_method"'):
            self.assertIn(condition, arch)
