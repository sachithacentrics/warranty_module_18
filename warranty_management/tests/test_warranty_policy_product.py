from datetime import date

from lxml import etree

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged

from .common import confirm_and_group, set_installation

# Product Warranty Configuration fields locked while a Warranty Policy applies to the product.
POLICY_LOCKED_FIELDS = (
    'warranty_start_criterion', 'warranty_basis', 'default_warranty_period',
    'default_warranty_period_unit', 'default_free_service_count', 'free_service_frequency',
    'free_service_frequency_unit', 'default_schedule_method', 'auto_create_services',
)
# SRS 2.7 (approved 2026-10-23): the Worksheet Template is defined on the product master, also
# when a Warranty Policy applies (it is not a policy value).
POLICY_EDITABLE_FIELDS = ('warranty_worksheet_template_id',)
POLICY_LOGGER = 'odoo.addons.warranty_management.models.warranty_policy'
MIGRATION_PARAM = 'warranty_management.legacy_product_policies_migrated'


@tagged('post_install', '-at_install', 'warranty_policy')
class TestWarrantyPolicyProduct(TransactionCase):
    """Strict Warranty Policy priority (doc/warranty_policy_resolution.md): the policy is
    selected on the Sales Order pricelist (P1), the product (P2, per company), the product
    category (P3) or the company (P4); otherwise the own values (P5)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Other Policy Company'})
        cls.company.write({
            'warranty_scope_mode': 'warranty_only',
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'installation',
            'default_warranty_duration': 0,
            'default_warranty_policy_id': False,
            'default_free_service_count': 0,
            'default_free_service_period': 0,
            'default_schedule_method': False,
            'warranty_auto_create_services': False,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Product Policy Customer'})
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': 'Product Policy Pricelist', 'company_id': cls.company.id})
        cls.categ = cls.env['product.category'].create({'name': 'Product Policy ACs'})
        cls.Policy = cls.env['warranty.policy']

    def _policy(self, name, **vals):
        values = {'name': name, 'warranty_duration': 12, 'warranty_duration_unit': 'months'}
        values.update(vals)
        return self.Policy.create(values)

    def _product(self, name, **vals):
        values = {
            'name': name, 'type': 'service', 'categ_id': self.categ.id,
            'warranty_applicable': True, 'default_warranty_period': 12,
            'default_warranty_period_unit': 'months',
        }
        values.update(vals)
        return self.env['product.product'].create(values)

    def _order(self, product, pricelist=None):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id, 'pricelist_id': (pricelist or self.pricelist).id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})],
        })

    def _card(self, product, pricelist=None):
        order = self._order(product, pricelist)
        confirm_and_group(order)
        return order.warranty_card_ids

    def _resolve(self, product, pricelist=None):
        return self._order(product, pricelist).order_line._warranty_resolve_rule()

    def _rule(self, product, **vals):
        """Legacy Product + Pricelist Warranty Mapping line (kept, not used)."""
        values = {'product_tmpl_id': product.product_tmpl_id.id,
                  'pricelist_id': self.pricelist.id}
        values.update(vals)
        return self.env['warranty.product.pricelist.rule'].create(values)

    def _pricelist_policy(self, policy, pricelist=None):
        (pricelist or self.pricelist).write({'warranty_applicable': bool(policy),
                                             'warranty_policy_id': policy.id})

    # ------------------------------------------------------------------ priority
    def test_01_strict_priority(self):
        """All four levels configured at the same time: pricelist policy (P1) > product policy
        (P2) > category policy (P3) > Company Default Warranty Policy (P4); each removal falls
        to the next level; no policy at all: the own values (P5); legacy mapping lines are
        not used."""
        pricelist_policy = self._policy('Pricelist Policy', warranty_duration=36)
        product_policy = self._policy('Product Policy', warranty_duration=24)
        category_policy = self._policy('Category Policy', warranty_duration=18)
        company_policy = self._policy('Company Policy', warranty_duration=6)
        product = self._product('AC Four Levels', default_warranty_period=3)
        self._rule(product, warranty_period=48, warranty_period_unit='months')
        self._pricelist_policy(pricelist_policy)
        product.product_tmpl_id.warranty_policy_id = product_policy
        self.categ.warranty_policy_id = category_policy
        self.company.default_warranty_policy_id = company_policy

        expected = [
            (pricelist_policy, 'pricelist_policy', 36),
            (product_policy, 'product_policy', 24),
            (category_policy, 'category_policy', 18),
            (company_policy, 'company_policy', 6),
        ]
        removals = [
            lambda: self.pricelist.write({'warranty_applicable': False}),
            lambda: product.product_tmpl_id.write({'warranty_policy_id': False}),
            lambda: self.categ.write({'warranty_policy_id': False}),
            lambda: self.company.write({'default_warranty_policy_id': False}),
        ]
        for (policy, source, duration), remove in zip(expected, removals):
            card = self._card(product)
            self.assertEqual((card.policy_id, card.policy_source, card.warranty_duration),
                             (policy, source, duration))
            remove()
        # P5: the product's own values (the legacy mapping line's 48 months are not used).
        card = self._card(product)
        self.assertEqual((card.policy_id, card.policy_source, card.warranty_duration),
                         (self.Policy, 'product', 3))
        # Another pricelist of the order: its own policy (or none).
        other = self.env['product.pricelist'].create({
            'name': 'Other Policy Pricelist', 'company_id': self.company.id})
        self._pricelist_policy(product_policy, other)
        self.assertEqual(self._card(product, other).policy_source, 'pricelist_policy')
        self.assertEqual(self._card(product).policy_source, 'product')

    def test_02_existing_cards_unchanged(self):
        """Selecting another policy later does not change cards created before."""
        category_policy = self._policy('Category Policy Existing')
        self.categ.warranty_policy_id = category_policy
        product = self._product('AC Existing Card')
        card = self._card(product)
        product.product_tmpl_id.warranty_policy_id = self._policy('Product Policy Later',
                                                                  warranty_duration=48)
        category_policy.warranty_duration = 1
        self.assertEqual((card.policy_id, card.policy_source, card.warranty_duration),
                         (category_policy, 'category_policy', 12))

    def test_03_no_value_mixing(self):
        """The selected policy gives every value; lower levels are never mixed in. Its empty
        Warranty Basis / Start Criterion / Free Service Period / Schedule Method come from the
        Company Warranty Settings only."""
        self.company.write({
            'warranty_scope_mode': 'free_services', 'default_start_criterion': 'installation',
            'default_free_service_count': 9, 'default_free_service_period': 6,
            'default_free_service_period_unit': 'months', 'default_schedule_method': 'manual',
            'warranty_auto_create_services': True,
        })
        rich = dict(free_service_count=4, free_service_frequency=3,
                    free_service_frequency_unit='months', free_service_period=12,
                    free_service_period_unit='months', schedule_method='equal_interval',
                    start_date_basis='delivery', warranty_basis='period',
                    auto_create_services=True, grace_period_days=10)
        self.categ.warranty_policy_id = self._policy('Rich Category Policy', **rich)
        self.company.default_warranty_policy_id = self._policy('Rich Company Policy', **rich)
        product = self._product(
            'AC No Mixing', default_free_service_count=5, free_service_frequency=2,
            free_service_frequency_unit='months', default_schedule_method='equal_interval',
            auto_create_services=True, warranty_start_criterion='delivery')
        product.product_tmpl_id.warranty_policy_id = self._policy('Rich Product Policy', **rich)
        lean = self._policy('Lean Line Policy', warranty_duration=24)
        self._pricelist_policy(lean)

        card = self._card(product)
        self.assertEqual(
            (card.policy_id, card.policy_source, card.warranty_duration,
             card.free_services_allowed, card.free_service_frequency, card.start_criterion,
             card.warranty_basis),
            (lean, 'pricelist_policy', 24, 0, 0, 'installation', 'period'))
        lean.free_service_count = 2
        card = self._card(product)
        set_installation(card, date(2026, 1, 1))
        card.action_confirm_warranty()
        self.assertEqual(
            (card.free_services_allowed, card.schedule_method, card.free_service_period,
             card.free_service_period_unit, card.grace_period_days),
            (2, 'manual', 6, 'months', 0), 'company settings fill the empty policy values')
        self.assertFalse(card.service_entitlement_ids, "the policy's Auto-create is unticked")

    def test_04_invalid_mapped_policy(self):
        """A policy selected at a level without a valid Warranty Duration / Duration Unit is a
        configuration error naming the policy and the level (never skipped silently); an
        archived policy or a level without policy continues with the next level."""
        product = self._product('AC Invalid Policy')
        invalid_cases = [
            ('No Duration', {'warranty_duration': 0}),
            ('No Unit', {'warranty_duration_unit': False}),
        ]
        levels = [
            ('Pricelist Product Policy Pricelist',
             lambda policy: self._pricelist_policy(policy)),
            ('Product', lambda policy: product.product_tmpl_id.write(
                {'warranty_policy_id': policy.id})),
            ('Product Category', lambda policy: self.categ.write(
                {'warranty_policy_id': policy.id})),
            ('Company Default Warranty Policy', lambda policy: self.company.write(
                {'default_warranty_policy_id': policy.id})),
        ]
        for level, select in levels:
            for name, vals in invalid_cases:
                policy = self._policy('%s %s' % (name, level), **vals)
                with self.assertRaises(UserError) as error:
                    with self.env.cr.savepoint():
                        select(policy)
                        self._order(product).action_confirm()
                message = str(error.exception)
                self.assertIn(policy.name, message)
                self.assertIn('(selected on: %s)' % level, message)
                self.assertIn('no valid Warranty Duration', message)

        # Archived policy at a level: the next level applies.
        archived = self._policy('Archived Product Policy', active=False)
        category_policy = self._policy('Next Level Policy', warranty_duration=18)
        product.product_tmpl_id.warranty_policy_id = archived
        self.categ.warranty_policy_id = category_policy
        card = self._card(product)
        self.assertEqual((card.policy_id, card.policy_source), (category_policy, 'category_policy'))

    def test_05_usage_policy(self):
        """Usage-based policy: Usage Limit and Usage Unit from the policy; one of them missing
        (also with the basis from the Company Warranty Settings) is a configuration error."""
        policy = self._policy('Usage Hours Policy', warranty_basis='usage', usage_limit=5000,
                              usage_unit='operating_hours')
        product = self._product('AC Usage Policy', warranty_basis='period')
        product.product_tmpl_id.warranty_policy_id = policy
        values = self._resolve(product)
        self.assertEqual((values['warranty_basis'], values['usage_limit'], values['usage_unit']),
                         ('usage', 5000, 'operating_hours'))

        for vals in ({'usage_limit': 0}, {'usage_limit': 5000, 'usage_unit': False}):
            policy.write(vals)
            with self.assertRaises(UserError) as error:
                self._order(product).action_confirm()
            self.assertIn('needs a Usage Limit and a Usage Unit', str(error.exception))

        # Basis empty on the policy, Usage in the Company Warranty Settings.
        policy.write({'warranty_basis': False, 'usage_limit': 0, 'usage_unit': False})
        self.company.default_warranty_basis = 'usage'
        with self.assertRaises(UserError):
            self._order(product).action_confirm()
        policy.write({'usage_limit': 100, 'usage_unit': 'km'})
        self.assertEqual(self._resolve(product)['warranty_basis'], 'usage')

        arch = etree.fromstring(self.env.ref('warranty_management.warranty_policy_view_form').arch)
        for name in ('usage_limit', 'usage_unit'):
            node = arch.xpath("//field[@name='%s']" % name)[0]
            self.assertEqual((node.get('invisible'), node.get('required')),
                             ("warranty_basis != 'usage'", "warranty_basis == 'usage'"), name)

    def test_06_frequency_from_policy(self):
        """Free Service Frequency of the policy: used for the due dates; empty: the services
        are spread over the policy's Free Service Period."""
        self.company.write({'warranty_scope_mode': 'free_services'})
        policy = self._policy('Frequency Policy', free_service_count=2, free_service_period=12,
                              free_service_period_unit='months', free_service_frequency=3,
                              free_service_frequency_unit='months',
                              schedule_method='equal_interval', auto_create_services=True)
        self.categ.warranty_policy_id = policy

        def due_dates():
            card = self._card(self._product('AC Frequency'))
            set_installation(card, date(2026, 1, 1))
            card.action_confirm_warranty()
            return card.service_entitlement_ids.sorted('service_no').mapped('due_date')

        self.assertEqual(due_dates(), [date(2026, 4, 1), date(2026, 7, 1)])
        policy.write({'free_service_frequency': 0, 'free_service_frequency_unit': False})
        self.assertEqual(due_dates(), [date(2026, 7, 1), date(2027, 1, 1)])

        arch = etree.fromstring(self.env.ref('warranty_management.warranty_policy_view_form').arch)
        unit = arch.xpath("//field[@name='free_service_frequency_unit']")[0]
        self.assertEqual(unit.get('required'), 'free_service_frequency')

    # ------------------------------------------------------------------ multi-company
    def test_07_company_specific_policies(self):
        """A policy of another company is never applied; shared policies are used by every
        company; the product policy is selected per company."""
        product = self._product('AC Two Companies')
        template = product.product_tmpl_id
        own = self._policy('Company A Policy', warranty_duration=24)
        other = self.Policy.with_company(self.other_company).create({
            'name': 'Company B Policy', 'warranty_duration': 6,
            'warranty_duration_unit': 'months'})
        shared = self._policy('Shared Policy', company_id=False, warranty_duration=30)

        # Per company selection on the product.
        template.warranty_policy_id = own
        template.with_company(self.other_company).warranty_policy_id = other
        self.assertEqual(template.warranty_policy_id, own)
        self.assertEqual(template.with_company(self.other_company).warranty_policy_id, other)
        with self.assertRaises(ValidationError):
            template.warranty_policy_id = other
        template.warranty_policy_id = shared
        self.assertEqual(self._card(product).policy_id, shared)
        Template = self.env['product.template']
        self.assertEqual(Template.search([('warranty_policy_id', '=', shared.id)]), template)
        self.assertEqual(Template.with_company(self.other_company).search(
            [('warranty_policy_id', '=', other.id)]), template)

        # Pricelist (D3): a company pricelist takes a policy of its company or a shared one; a
        # shared pricelist only a shared policy.
        with self.assertRaises(ValidationError):
            self._pricelist_policy(other)
        self._pricelist_policy(own)
        self._pricelist_policy(shared)
        shared_pricelist = self.env['product.pricelist'].create({
            'name': 'Shared Pricelist', 'company_id': False})
        with self.assertRaises(ValidationError):
            self._pricelist_policy(own, shared_pricelist)
        self._pricelist_policy(shared, shared_pricelist)
        self.assertEqual(self._card(product, shared_pricelist).policy_id, shared)
        self._pricelist_policy(self.Policy)

        # Category policy of another company: not applied in this company (next level / P5).
        template.warranty_policy_id = False
        self.categ.warranty_policy_id = other
        values = self._resolve(product)
        self.assertEqual((values['policy'], values['policy_source']), (self.Policy, 'product'))
        self.assertFalse(template.warranty_policy_applicable)
        self.assertFalse(template.warranty_category_policy_id)
        self.assertEqual(
            template.with_company(self.other_company).warranty_category_policy_id, other)

    def test_08_policy_form(self):
        """The policy form holds only the configuration: no Applies To / applicability
        mappings; new policies take the current company, shown readonly."""
        self.assertEqual(self._policy('Current Company Policy').company_id, self.company)
        switched = self.Policy.with_company(self.other_company).create({'name': 'Switched'})
        self.assertEqual(switched.company_id, self.other_company)

        for view in ('warranty_policy_view_form', 'warranty_policy_view_list'):
            arch = etree.fromstring(self.env.ref('warranty_management.%s' % view).arch)
            for name in ('applies_to', 'product_tmpl_ids', 'product_categ_ids',
                         'product_brand_ids', 'product_model_ids', 'pricelist_ids',
                         'sale_order_type_id'):
                self.assertFalse(arch.xpath("//field[@name='%s']" % name), (view, name))
        arch = etree.fromstring(self.env.ref('warranty_management.warranty_policy_view_form').arch)
        self.assertEqual(arch.xpath("//field[@name='company_id']")[0].get('readonly'), '1')
        for name in ('free_service_frequency', 'free_service_frequency_unit', 'usage_limit'):
            self.assertTrue(arch.xpath("//field[@name='%s']" % name), name)

    # ------------------------------------------------------------------ product
    def test_09_product_policy_field(self):
        """Selecting a policy on the product makes it Warranty Applicable (never unticked
        automatically); administrators only; other product settings are kept."""
        template = self.env['product.template'].create({
            'name': 'LG AC 18000 BTU', 'type': 'service', 'categ_id': self.categ.id,
            'warranty_applicable': False, 'default_warranty_period': 6,
            'default_warranty_period_unit': 'months'})
        premium = self._policy('Premium AC Warranty')
        template.warranty_policy_id = premium
        self.assertEqual((template.warranty_applicable, template.warranty_policy_applicable),
                         (True, True))
        self.assertEqual(template.default_warranty_period, 6, 'other settings are kept')
        template.warranty_policy_id = False
        self.assertEqual((template.warranty_applicable, template.warranty_policy_applicable),
                         (True, False))
        created = self.env['product.template'].create({
            'name': 'Created With Policy', 'warranty_policy_id': premium.id})
        self.assertTrue(created.warranty_applicable)
        premium.active = False
        created.invalidate_recordset(['warranty_policy_applicable'])
        self.assertFalse(created.warranty_policy_applicable, 'archived policy')

        stock_manager = self.env['res.users'].create({
            'name': 'Product Side Stock Manager', 'login': 'warranty_product_side_manager',
            'groups_id': [(6, 0, self.env.ref('stock.group_stock_manager').ids)]})
        with self.assertRaises(AccessError):
            template.with_user(stock_manager).warranty_policy_id = premium
        template.with_user(stock_manager).name = 'LG AC 18000 BTU (renamed)'

        arch = etree.fromstring(
            self.env.ref('warranty_management.product_template_form_view_warranty').arch)
        self.assertEqual(
            arch.xpath("//field[@name='warranty_policy_applicable']")[0].get('readonly'), '1')
        admin_node, user_node = arch.xpath(
            "//field[@name='warranty_policy_id'][not(ancestor::list)]")
        self.assertEqual((admin_node.get('groups'), admin_node.get('readonly')),
                         ('base.group_system', None))
        self.assertEqual((user_node.get('groups'), user_node.get('readonly')),
                         ('!base.group_system', '1'))

    def test_10_product_form_readonly_and_mapping_editable(self):
        """Warranty Configuration fields are readonly while a policy applies to the product
        (own or category, current company); the Product + Pricelist Warranty Mapping is no
        longer on the product form (legacy lines kept)."""
        arch = etree.fromstring(
            self.env.ref('warranty_management.product_template_form_view_warranty').arch)
        for name in POLICY_LOCKED_FIELDS:
            node = arch.xpath("//page[@name='warranty_configuration']"
                              "//field[@name='%s'][not(ancestor::list)]" % name)[0]
            self.assertEqual(node.get('readonly'), 'warranty_policy_applicable', name)
        for name in POLICY_EDITABLE_FIELDS:
            node = arch.xpath("//page[@name='warranty_configuration']//field[@name='%s']" % name)[0]
            self.assertFalse(node.get('readonly'), name)
        self.assertFalse(arch.xpath("//field[@name='warranty_pricelist_rule_ids']"))
        self.assertFalse(arch.xpath("//group[@string='Product + Pricelist Warranty Mapping']"))

        mapped = self._product('AC Locked').product_tmpl_id
        mapped.write({'warranty_start_criterion': 'delivery', 'default_free_service_count': 3})
        free = self._product('AC Editable').product_tmpl_id
        other_policy = self.Policy.with_company(self.other_company).create({
            'name': 'Other Company Lock', 'warranty_duration': 6,
            'warranty_duration_unit': 'months'})
        free.with_company(self.other_company).warranty_policy_id = other_policy
        mapped.warranty_policy_id = self._policy('Current Company Lock')

        form = Form(mapped)
        for name in POLICY_LOCKED_FIELDS:
            self.assertTrue(form._get_modifier(name, 'readonly'), name)
        with self.assertRaises(AssertionError):
            form.default_warranty_period = 99

        # Policy only in the other company: editable here, locked there.
        form = Form(free)
        for name in POLICY_LOCKED_FIELDS:
            self.assertFalse(form._get_modifier(name, 'readonly'), name)
        form.default_warranty_period = 24
        form.save()
        self.assertEqual(free.default_warranty_period, 24)
        other_form = Form(free.with_company(self.other_company))
        self.assertTrue(other_form._get_modifier('default_warranty_period', 'readonly'))

        # Values are never changed by the lock.
        self.assertEqual((mapped.warranty_start_criterion, mapped.default_warranty_period,
                          mapped.default_free_service_count), ('delivery', 12, 3))

    # ------------------------------------------------------------------ category
    def test_11_category_policy_inherited(self):
        """The category's Default Warranty Policy applies to its products without a policy of
        their own (current company or shared): shown on the product, readonly product fields,
        searchable, Sales Order source "Product Category Policy"; the product policy comes
        first; Warranty Applicable is not changed."""
        Template = self.env['product.template']
        policy = self._policy('Category Inherited', warranty_duration=24, free_service_count=2)
        product = self._product('Inherited AC', default_warranty_period=6,
                                warranty_applicable=False)
        template = product.product_tmpl_id
        self.assertFalse(template.warranty_policy_applicable)

        self.categ.warranty_policy_id = policy
        self.assertEqual((template.warranty_policy_applicable, template.warranty_policy_id,
                          template.warranty_category_policy_id), (True, self.Policy, policy))
        self.assertIn(template, Template.search([('warranty_policy_applicable', '=', True)]))
        self.assertNotIn(template, Template.search([('warranty_policy_applicable', '=', False)]))
        self.assertFalse(template.warranty_applicable, 'Warranty Applicable not changed')
        form = Form(template)
        for name in POLICY_LOCKED_FIELDS:
            self.assertTrue(form._get_modifier(name, 'readonly'), name)
        for name in POLICY_EDITABLE_FIELDS:
            self.assertFalse(form._get_modifier(name, 'readonly'), name)

        template.warranty_applicable = True
        values = self._resolve(product)
        self.assertEqual((values['policy_source'], values['policy'], values['warranty_duration'],
                          values['free_service_count']), ('category_policy', policy, 24, 2))
        own = self._policy('Own Product Policy', warranty_duration=36)
        template.warranty_policy_id = own
        self.assertEqual(self._resolve(product)['policy'], own)
        template.warranty_policy_id = False

        # Archived / removed category policy: not applied, fields editable, values kept.
        policy.active = False
        self.assertFalse(template.warranty_policy_applicable)
        policy.active = True
        self.categ.warranty_policy_id = False
        self.assertFalse(template.warranty_policy_applicable)
        form = Form(template)
        for name in POLICY_LOCKED_FIELDS:
            self.assertFalse(form._get_modifier(name, 'readonly'), name)
        values = self._resolve(product)
        self.assertEqual((values['policy_source'], values['warranty_duration']), ('product', 6))

        arch = etree.fromstring(
            self.env.ref('warranty_management.product_template_form_view_warranty').arch)
        node = arch.xpath("//field[@name='warranty_category_policy_id']")[0]
        self.assertEqual(node.get('invisible'), 'not warranty_applicable or warranty_policy_id '
                                                'or not warranty_category_policy_id')

    def test_12_category_policy_applicable_readonly(self):
        """Category form: the warranty defaults are readonly while a Default Warranty Policy
        is selected, editable otherwise; values are unchanged."""
        locked = ('default_warranty_period', 'default_warranty_period_unit',
                  'warranty_start_criterion', 'warranty_basis', 'default_free_service_count',
                  'free_service_frequency', 'free_service_frequency_unit', 'card_grouping_mode',
                  'default_schedule_method', 'auto_create_services')
        arch = etree.fromstring(
            self.env.ref('warranty_management.product_category_form_view_warranty').arch)
        for name in locked:
            self.assertEqual(arch.xpath("//field[@name='%s']" % name)[0].get('readonly'),
                             'warranty_policy_applicable', name)
        self.assertIsNone(arch.xpath("//field[@name='warranty_policy_id']")[0].get('readonly'))

        self.categ.write({'default_warranty_period': 6, 'default_warranty_period_unit': 'months',
                          'card_grouping_mode': 'per_product'})
        self.assertFalse(self.categ.warranty_policy_applicable)
        policy = self._policy('Category Applicable')
        form = Form(self.categ)
        for name in locked:
            self.assertFalse(form._get_modifier(name, 'readonly'), name)
        form.warranty_policy_id = policy
        self.assertTrue(form.warranty_policy_applicable)
        for name in locked:
            self.assertTrue(form._get_modifier(name, 'readonly'), name)
        form.save()
        self.assertEqual(self.categ.warranty_policy_id, policy)
        self.assertEqual((self.categ.default_warranty_period, self.categ.card_grouping_mode),
                         (6, 'per_product'))

    # ------------------------------------------------------------------ legacy data
    def test_13_legacy_mappings_not_used(self):
        """Legacy applicability data stored on a policy (Applies To, Applicable Products /
        Pricelists, Sales Order Type) is kept but not used."""
        product = self._product('AC Legacy')
        legacy = self._policy(
            'Legacy Mapping Policy', applies_to='customer_type', warranty_duration=60,
            product_tmpl_ids=[(6, 0, product.product_tmpl_id.ids)],
            pricelist_ids=[(6, 0, self.pricelist.ids)], sale_order_type_id='retail')
        rule = self._rule(product, warranty_period=48, warranty_period_unit='months')
        self.assertEqual(legacy.product_tmpl_ids, product.product_tmpl_id)
        self.assertFalse(product.product_tmpl_id.warranty_policy_id)
        values = self._resolve(product)
        self.assertEqual((values['policy'], values['policy_source'], values['warranty_duration']),
                         (self.Policy, 'product', 12))
        self.assertTrue(rule.exists(), 'legacy mapping line kept')
        self.assertFalse(self.pricelist.warranty_policy_id, 'legacy Customer Type not converted')
        sources = dict(self.env['warranty.card']._fields['policy_source'].selection)
        for key in ('pricelist_policy', 'product_policy', 'category_policy', 'company_policy',
                    'pricelist_rule', 'product', 'category', 'company', 'model_policy',
                    'brand_policy', 'customer_type_policy'):
            self.assertIn(key, sources)
        self.assertEqual((sources['pricelist_policy'], sources['category_policy'],
                          sources['company_policy']),
                         ('Pricelist Warranty Policy', 'Product Category Policy',
                          'Company Default Policy'))
        self.assertEqual(sources['pricelist_rule'], 'Product + Pricelist Rule')

    def test_14_legacy_product_assignment_migration(self):
        """One-time copy of the legacy direct product assignments to the per-company product
        Warranty Policy: policy company, else product company; existing values kept; shared /
        conflicting / archived assignments skipped (logged); cards and policies unchanged;
        runs once."""
        Template = self.env['product.template']
        self.env['ir.config_parameter'].sudo().set_param(MIGRATION_PARAM, False)
        shared_product = self._product('Legacy Shared Product').product_tmpl_id
        other_product = Template.create({'name': 'Legacy Company B Product',
                                         'company_id': self.other_company.id})
        orphan = self._product('Legacy Orphan').product_tmpl_id
        kept = self._product('Legacy Kept').product_tmpl_id
        conflict = self._product('Legacy Conflict').product_tmpl_id
        inactive_product = self._product('Legacy Inactive').product_tmpl_id
        existing = self._policy('Existing Product Policy')
        kept.warranty_policy_id = existing
        card = self._card(kept.product_variant_id)

        company_policy = self._policy('Legacy Company Policy', product_tmpl_ids=[
            (6, 0, (shared_product | kept | conflict).ids)])
        shared_policy = self._policy('Legacy Shared Policy', company_id=False, product_tmpl_ids=[
            (6, 0, (other_product | orphan).ids)])
        second = self._policy('Legacy Second Policy', product_tmpl_ids=[(6, 0, conflict.ids)])
        self._policy('Legacy Archived Policy', active=False,
                     product_tmpl_ids=[(6, 0, inactive_product.ids)])

        with self.assertLogs(POLICY_LOGGER, level='WARNING') as logs:
            self.Policy._migrate_legacy_product_policies()
        output = '\n'.join(logs.output)
        self.assertIn('Legacy Orphan', output)
        self.assertIn('Legacy Conflict', output)
        self.assertEqual(shared_product.warranty_policy_id, company_policy)
        self.assertFalse(shared_product.with_company(self.other_company).warranty_policy_id)
        self.assertEqual(other_product.with_company(self.other_company).warranty_policy_id,
                         shared_policy)
        self.assertFalse(orphan.warranty_policy_id)
        self.assertEqual(kept.warranty_policy_id, existing, 'existing value kept')
        self.assertFalse(conflict.warranty_policy_id)
        self.assertFalse(inactive_product.warranty_policy_id)
        self.assertEqual(company_policy.product_tmpl_ids, shared_product | kept | conflict,
                         'legacy data kept')
        self.assertEqual((card.policy_id, card.policy_source), (existing, 'product_policy'))
        self.assertTrue(self.env['ir.config_parameter'].sudo().get_param(MIGRATION_PARAM))

        # Runs once: a cleared product policy is not copied again.
        shared_product.warranty_policy_id = False
        self.Policy._migrate_legacy_product_policies()
        self.assertFalse(shared_product.warranty_policy_id)
        self.assertTrue(second.active)

    def test_15_policy_values_displayed_on_product(self):
        """While a policy applies, the product form shows its values (readonly) instead of the
        product's own values; they follow a policy change; without policy the own values are
        shown and editable again; a category policy is shown the same way; the product's own
        values are never modified; card creation keeps the strict priority."""
        own = dict(warranty_start_criterion='delivery', warranty_basis='period',
                   default_warranty_period=6, default_warranty_period_unit='months',
                   default_free_service_count=5, free_service_frequency=2,
                   free_service_frequency_unit='months', default_schedule_method='manual',
                   auto_create_services=False)
        product = self._product('AC Display', **own)
        template = product.product_tmpl_id
        first = self._policy(
            'Display First', warranty_duration=24, start_date_basis='installation',
            warranty_basis='usage', usage_limit=3000, usage_unit='km', free_service_count=3,
            free_service_frequency=4, free_service_frequency_unit='months',
            free_service_period=12, free_service_period_unit='months',
            schedule_method='equal_interval', auto_create_services=True)
        second = self._policy('Display Second', warranty_duration=2,
                              warranty_duration_unit='years', free_service_count=1)

        def displayed():
            return (template.warranty_policy_start_criterion, template.warranty_policy_basis,
                    template.warranty_policy_period, template.warranty_policy_period_unit,
                    template.warranty_policy_usage_limit, template.warranty_policy_usage_unit,
                    template.warranty_policy_free_service_count,
                    template.warranty_policy_frequency, template.warranty_policy_frequency_unit,
                    template.warranty_policy_service_period,
                    template.warranty_policy_service_period_unit,
                    template.warranty_policy_schedule_method,
                    template.warranty_policy_auto_create)

        template.warranty_policy_id = first
        self.assertEqual(template.warranty_applied_policy_id, first)
        self.assertEqual(displayed(), ('installation', 'usage', 24, 'months', 3000, 'km', 3, 4,
                                       'months', 12, 'months', 'equal_interval', True))
        template.warranty_policy_id = second
        self.assertEqual(displayed()[2:4] + displayed()[6:7], (2, 'years', 1))
        # Removed: nothing displayed, the product's own values are unchanged.
        template.warranty_policy_id = False
        self.assertFalse(template.warranty_applied_policy_id)
        self.assertFalse(template.warranty_policy_period)
        self.assertEqual(template.read(list(own))[0], dict(template.read(list(own))[0], **own))
        # Category policy inherited: displayed the same way.
        self.categ.warranty_policy_id = first
        self.assertEqual((template.warranty_applied_policy_id, template.warranty_policy_period),
                         (first, 24))
        self.assertEqual(template.default_warranty_period, 6, 'own value kept')

        # Form: the displayed values follow the selected policy.
        self.categ.warranty_policy_id = False
        form = Form(template)
        form.warranty_policy_id = second
        self.assertEqual((form.warranty_policy_period, form.warranty_policy_period_unit),
                         (2, 'years'))
        form.warranty_policy_id = self.Policy
        self.assertEqual(form.warranty_policy_period, 0)
        self.assertFalse(form._get_modifier('default_warranty_period', 'readonly'))

        # View: own fields hidden while a policy applies, policy values shown readonly.
        arch = etree.fromstring(
            self.env.ref('warranty_management.product_template_form_view_warranty').arch)
        page = "//page[@name='warranty_configuration']"
        for own_name, policy_name in (('warranty_start_criterion', 'warranty_policy_start_criterion'),
                                      ('warranty_basis', 'warranty_policy_basis'),
                                      ('default_free_service_count', 'warranty_policy_free_service_count'),
                                      ('default_schedule_method', 'warranty_policy_schedule_method'),
                                      ('auto_create_services', 'warranty_policy_auto_create')):
            own_node = arch.xpath("%s//field[@name='%s']" % (page, own_name))[0]
            policy_node = arch.xpath("%s//field[@name='%s']" % (page, policy_name))[0]
            self.assertIn('warranty_policy_applicable', own_node.get('invisible'))
            self.assertIn('not warranty_policy_applicable', policy_node.get('invisible'))
            self.assertTrue(self.env['product.template']._fields[policy_name].readonly)

        # Cards keep the strict priority: pricelist policy before the product policy.
        template.warranty_policy_id = second
        self._pricelist_policy(first)
        card = self._card(product)
        self.assertEqual((card.policy_id, card.policy_source), (first, 'pricelist_policy'))

    # ------------------------------------------------------------------ pricelist
    def test_16_pricelist_warranty_tab(self):
        """Pricelist Warranty tab: Warranty Applicable requires a Warranty Policy (D2); the
        policy values are displayed readonly and follow the policy (nothing copied); the
        pricelist does not make products Warranty Applicable."""
        with self.assertRaises(ValidationError):
            self.pricelist.write({'warranty_applicable': True})
        policy = self._policy(
            'Pricelist Display', warranty_duration=18, start_date_basis='delivery',
            warranty_basis='usage', usage_limit=900, usage_unit='cycles', free_service_count=2,
            free_service_frequency=3, free_service_frequency_unit='months',
            free_service_period=6, free_service_period_unit='months',
            schedule_method='equal_interval', auto_create_services=True,
            service_due_alert_days=5, expiry_reminder_days=4, grace_period_days=9,
            auto_expire_services=True, usage_alert_percentage=80)
        self._pricelist_policy(policy)
        pl = self.pricelist
        self.assertEqual(
            (pl.warranty_policy_duration, pl.warranty_policy_duration_unit,
             pl.warranty_policy_start_criterion, pl.warranty_policy_basis,
             pl.warranty_policy_usage_limit, pl.warranty_policy_usage_unit,
             pl.warranty_policy_free_service_count, pl.warranty_policy_frequency,
             pl.warranty_policy_frequency_unit, pl.warranty_policy_service_period,
             pl.warranty_policy_service_period_unit, pl.warranty_policy_schedule_method,
             pl.warranty_policy_auto_create, pl.warranty_policy_due_alert_days,
             pl.warranty_policy_expiry_reminder_days, pl.warranty_policy_grace_period_days,
             pl.warranty_policy_auto_expire, pl.warranty_policy_usage_alert_percentage),
            (18, 'months', 'delivery', 'usage', 900, 'cycles', 2, 3, 'months', 6, 'months',
             'equal_interval', True, 5, 4, 9, True, 80))
        policy.warranty_duration = 30
        self.assertEqual(pl.warranty_policy_duration, 30, 'displayed, not copied')
        for name, field in pl._fields.items():
            if name.startswith('warranty_policy_') and name not in ('warranty_policy_id',
                                                                   'warranty_policy_ids'):
                self.assertTrue(field.related and field.readonly and not field.store, name)

        # Warranty Applicable products only.
        plain = self._product('Pricelist Plain', warranty_applicable=False)
        order = self._order(plain)
        confirm_and_group(order)
        self.assertFalse(order.warranty_card_ids)
        self.assertFalse(plain.warranty_applicable)

        # Unticked: policy kept on the pricelist but not used.
        pl.warranty_applicable = False
        self.assertEqual(pl.warranty_policy_id, policy)
        self.assertEqual(self._resolve(self._product('Pricelist Unticked'))['policy_source'],
                         'product')

        arch = etree.fromstring(
            self.env.ref('warranty_management.product_pricelist_view_form_warranty').arch)
        page = arch.xpath("//page[@name='warranty']")[0]
        self.assertEqual(page.get('string'), 'Warranty')
        node = page.xpath(".//field[@name='warranty_policy_id']")[0]
        self.assertEqual((node.get('required'), node.get('invisible')),
                         ('warranty_applicable', 'not warranty_applicable'))
        form = Form(self.env['product.pricelist'].with_company(self.company))
        form.name = 'Form Pricelist'
        form.company_id = self.company
        form.warranty_applicable = True
        form.warranty_policy_id = policy
        self.assertEqual(form.warranty_policy_free_service_count, 2)
        form.save()

    def test_17_legacy_mapping_lines_logged_once(self):
        """Retired mapping lines (D1): kept unchanged, not converted, logged once for review."""
        self.env['ir.config_parameter'].sudo().set_param(
            'warranty_management.legacy_pricelist_rules_logged', False)
        product = self._product('AC Legacy Line')
        rule = self._rule(product, warranty_period=24, warranty_period_unit='months',
                          free_service_count=4)
        with self.assertLogs(POLICY_LOGGER, level='WARNING') as logs:
            self.Policy._log_legacy_pricelist_rules()
        self.assertIn('AC Legacy Line', '\n'.join(logs.output))
        self.assertEqual((rule.warranty_period, rule.free_service_count, rule.active),
                         (24, 4, True))
        self.assertFalse(self.pricelist.warranty_applicable)
        with self.assertNoLogs(POLICY_LOGGER, level='WARNING'):
            self.Policy._log_legacy_pricelist_rules()
