from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

from .test_warranty_cost_lines import _SavepointMixin


@tagged('post_install', '-at_install', 'warranty_cost')
class TestWarrantyAccountingConfig(_SavepointMixin, TransactionCase):
    """Part 8.3: configuration on existing models, precedence, rights, audit. No journal entry."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Provision Co A', 'warranty_scope_mode': 'warranty_only',
            'default_warranty_basis': 'period', 'default_start_criterion': 'delivery',
            'default_card_grouping_mode': 'per_so', 'default_warranty_duration': 12,
            'default_warranty_duration_unit': 'months'})
        cls.other = cls.env['res.company'].create({'name': 'Provision Co B'})
        both = cls.company | cls.other
        cls.finance_admin = cls._user('prov_finance_admin', both, 'base.group_system',
                                      'account.group_account_manager')
        cls.admin_only = cls._user('prov_admin_only', both, 'base.group_system')
        cls.manager_only = cls._user('prov_manager_only', both, 'account.group_account_manager')
        cls.accountant = cls._user('prov_accountant', both, 'account.group_account_readonly')
        cls.product_user = cls._user('prov_product_user', both, 'sales_team.group_sale_manager')
        cls.tech = cls._user('prov_tech', both, 'industry_fsm.group_fsm_user')
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=both.ids))
        cls.expense = cls._account(cls.company, 'PE01', 'expense')
        cls.direct = cls._account(cls.company, 'PE02', 'expense_direct_cost')
        cls.provision = cls._account(cls.company, 'PL01', 'liability_current')
        cls.asset = cls._account(cls.company, 'PA01', 'asset_current')
        cls.other_expense = cls._account(cls.other, 'PE03', 'expense')
        cls.journal = cls.env['account.journal'].create({
            'name': 'Warranty', 'code': 'WPRV', 'type': 'general', 'company_id': cls.company.id})
        cls.sale_journal = cls.env['account.journal'].create({
            'name': 'Warranty Sales', 'code': 'WPRS', 'type': 'sale', 'company_id': cls.company.id,
            'default_account_id': cls._account(cls.company, 'PI01', 'income').id})
        cls.other_journal = cls.env['account.journal'].create({
            'name': 'Other', 'code': 'WPRO', 'type': 'general', 'company_id': cls.other.id})
        cls.parent = cls.env['product.category'].create({'name': 'Cooling'})
        cls.category = cls.env['product.category'].create({'name': 'Air Conditioners',
                                                           'parent_id': cls.parent.id})
        cls.policy = cls.env['warranty.policy'].create({'name': 'Provision Policy',
                                                        'company_id': cls.company.id})
        cls.product = cls.env['product.product'].create({'name': 'Split AC', 'type': 'consu',
                                                         'categ_id': cls.category.id})
        cls.template = cls.product.product_tmpl_id
        cls.team = cls.env['helpdesk.team'].create({'name': 'Provision Team',
                                                    'company_id': cls.company.id})

    @classmethod
    def _user(cls, login, companies, *groups):
        return cls.env['res.users'].create({
            'name': login, 'login': login, 'company_id': companies[0].id,
            'company_ids': [(6, 0, companies.ids)],
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id]
                           + [cls.env.ref(group).id for group in groups])]})

    @classmethod
    def _account(cls, company, code, account_type):
        return cls.env['account.account'].with_company(company).create({
            'name': code, 'code': code, 'account_type': account_type,
            'company_ids': [(6, 0, company.ids)]})

    def _company(self):
        return self.company.with_company(self.company)

    def _ready(self, **vals):
        self.company.write(dict({
            'warranty_accounting_journal_id': self.journal.id,
            'warranty_expense_account_id': self.expense.id,
            'warranty_provision_account_id': self.provision.id}, **vals))

    def _rule(self, **kwargs):
        return self.company._warranty_provision_rule(**kwargs)

    def _in_company(self, record):
        return record.with_company(self.company)

    # ------------------------------------------------------------------ 1 to 4: configuration
    def test_01_disabled_by_default(self):
        self.assertFalse(self.company.warranty_provision_enabled)
        self.assertEqual(self.company.warranty_provision_method, 'disabled')
        self.assertFalse(self.company.warranty_accounting_journal_id)
        self.assertEqual(self._rule(product=self.product)['method'], 'none')
        self.assertFalse(self.template.warranty_provision_method)
        self.assertEqual(self.company._warranty_provision_value(self.product, 3, 1000), 0)

    def test_02_fixed_is_per_unit(self):
        self._ready(warranty_provision_enabled=True, warranty_provision_method='fixed',
                    warranty_provision_amount=50)
        self.assertEqual(self.company._warranty_provision_value(self.product, 3, 9999), 150)
        with self.assertRaisesRegex(ValidationError, 'must be above 0'):
            self.company.warranty_provision_amount = 0

    def test_03_percentage_uses_the_sales_value(self):
        self._ready(warranty_provision_enabled=True, warranty_provision_method='percentage',
                    warranty_provision_rate=5)
        self.assertEqual(self.company._warranty_provision_value(self.product, 3, 1000), 50,
                         'quantity plays no part')
        for rate in (0, 100.01, -1):
            with self.assertRaisesRegex(ValidationError, 'above 0 and at most 100'):
                self.company.warranty_provision_rate = rate
        self.company.warranty_provision_rate = 100

    def test_04_accounts_and_journal_validation(self):
        for vals, message in (
                ({'warranty_accounting_journal_id': self.sale_journal.id}, 'Miscellaneous'),
                ({'warranty_accounting_journal_id': self.other_journal.id}, 'Miscellaneous'),
                ({'warranty_expense_account_id': self.provision.id}, 'wrong account type'),
                ({'warranty_provision_account_id': self.asset.id}, 'wrong account type'),
                ({'warranty_expense_account_id': self.other_expense.id}, 'does not belong'),
        ):
            with self.assertRaisesRegex(ValidationError, message):
                self.company.write(vals)
        self.expense.deprecated = True
        with self.assertRaisesRegex(ValidationError, 'deprecated'):
            self.company.warranty_expense_account_id = self.expense
        self.expense.deprecated = False
        self.company.write({'warranty_expense_account_id': self.direct.id})
        with self.assertRaisesRegex(ValidationError, 'Warranty Provision / Reserve Account'):
            self.company.warranty_provision_enabled = True
        with self.assertRaisesRegex(ValidationError, 'Warranty Accounting Journal'):
            self.company.warranty_provision_enabled = True
        self._ready(warranty_provision_enabled=True)
        self.assertTrue(self.company.warranty_provision_enabled)
        with self.assertRaisesRegex(ValidationError, 'Warranty Expense Account'):
            self.company.warranty_expense_account_id = False

    # ------------------------------------------------------------------ 5, 6: precedence
    def test_05_precedence(self):
        self._ready(warranty_provision_enabled=True, warranty_provision_method='percentage',
                    warranty_provision_rate=5)
        self.template.categ_id.warranty_policy_id = self.policy
        rule = self._rule(product=self.product)
        self.assertEqual((rule['level'], rule['rate']), ('company', 5))
        self.policy.write({'warranty_provision_method': 'percentage', 'warranty_provision_rate': 4})
        self.template.invalidate_recordset()
        rule = self._rule(product=self.product)
        self.assertEqual((rule['level'], rule['rate']), ('policy', 4))
        self._in_company(self.parent).write({'warranty_provision_method': 'percentage',
                                             'warranty_provision_rate': 3})
        rule = self._rule(product=self.product)
        self.assertEqual((rule['level'], rule['rate'], rule['source']),
                         ('category', 3, self.parent.display_name), 'the parent category')
        self._in_company(self.category).write({'warranty_provision_method': 'percentage',
                                               'warranty_provision_rate': 2.5})
        rule = self._rule(product=self.product)
        self.assertEqual((rule['level'], rule['rate'], rule['source']),
                         ('category', 2.5, self.category.display_name), 'nearest category first')
        self._in_company(self.template).write({'warranty_provision_method': 'fixed',
                                               'warranty_provision_amount': 20})
        rule = self._rule(product=self.product)
        self.assertEqual((rule['level'], rule['method'], rule['amount']),
                         ('product', 'fixed', 20))
        self.assertEqual(self.company._warranty_provision_value(self.product, 2, 1000), 40)
        effective = self._in_company(self.template).warranty_provision_effective
        self.assertIn('per unit', effective)
        self.assertIn('this product', effective)
        self.assertIn('from category', self._in_company(self.category).warranty_provision_effective)

    def test_06_no_provision_and_use_next_level(self):
        self._ready(warranty_provision_enabled=True, warranty_provision_method='percentage',
                    warranty_provision_rate=5)
        template = self._in_company(self.template)
        category = self._in_company(self.category)
        category.write({'warranty_provision_method': 'percentage', 'warranty_provision_rate': 3})
        template.warranty_provision_method = 'inherit'
        self.assertEqual(self._rule(product=self.product)['level'], 'category', 'Use Next Level')
        template.warranty_provision_method = 'none'
        rule = self._rule(product=self.product)
        self.assertEqual((rule['method'], rule['level']), ('none', 'product'), 'stops here')
        self.assertEqual(self.company._warranty_provision_value(self.product, 1, 1000), 0)
        self.assertIn('No provision', template.warranty_provision_effective)
        template.warranty_provision_method = False
        category.warranty_provision_method = 'none'
        self.assertEqual(self.company._warranty_provision_value(self.product, 1, 1000), 0)
        category.warranty_provision_method = 'inherit'
        self.assertEqual(self.company._warranty_provision_value(self.product, 1, 1000), 50)
        for record in (template, category, self.policy):
            with self.assertRaisesRegex(ValidationError, 'above 0 and at most 100'):
                record.write({'warranty_provision_method': 'percentage',
                              'warranty_provision_rate': 0})
            with self.assertRaisesRegex(ValidationError, 'must be above 0'):
                record.write({'warranty_provision_method': 'fixed',
                              'warranty_provision_amount': 0})

    # ------------------------------------------------------------------ 7 to 9: reuse
    def test_07_inspection_configuration_is_reused(self):
        fee = self.env['product.product'].create({'name': 'Inspection Fee', 'type': 'service',
                                                  'sale_ok': True, 'company_id': self.company.id})
        deduction = self.env['product.product'].create({'name': 'Inspection Deduction',
                                                        'type': 'service', 'sale_ok': True,
                                                        'company_id': self.company.id})
        self.team.write({'warranty_inspection_product_id': fee.id,
                         'warranty_inspection_amount': 850})
        partner = self.env['res.partner'].create({'name': 'Inspection Customer'})
        ticket = self.env['helpdesk.ticket'].create({'name': 'Inspect', 'team_id': self.team.id,
                                                     'partner_id': partner.id})
        lines = self.env['warranty.case'].new(
            {'helpdesk_ticket_id': ticket.id})._warranty_inspection_line_vals()
        self.assertEqual((lines[0]['product_id'], lines[0]['price_unit']), (fee.id, 850))
        self.assertFalse(set(self.env['res.company']._fields) & {
            'warranty_inspection_product_id', 'warranty_inspection_amount'}, 'no second copy')
        self.team.with_user(self.finance_admin).sudo(
        ).warranty_inspection_deduction_product_id = deduction
        self.assertEqual(self.team.warranty_inspection_deduction_product_id, deduction)
        with self.assertRaises(AccessError):
            self.team.with_user(self.manager_only).sudo(
            ).warranty_inspection_deduction_product_id = fee
        self.assertEqual(self.team.warranty_inspection_deduction_product_id, deduction)

    def test_08_vendor_recovery_account_is_reused(self):
        recovery = self._account(self.company, 'PR01', 'income_other')
        self.assertFalse([name for name in self.env['res.company']._fields
                          if 'recovery' in name and name != 'warranty_claim_recovery_account_id'])
        Settings = self.env['res.config.settings'].with_company(self.company).with_context(
            allowed_company_ids=self.company.ids)
        self._ready()
        settings = Settings.create({})
        self.assertIn('Vendor Recovery Account', settings.warranty_accounting_issues)
        self.company.warranty_claim_recovery_account_id = recovery
        settings = Settings.create({})
        self.assertEqual(settings.warranty_accounting_issues, 'Ready.')
        self.assertEqual(settings.warranty_claim_recovery_account_id, recovery)

    # ------------------------------------------------------------------ 10, 11: rights
    def _settings(self, user, **vals):
        return self.env['res.config.settings'].with_user(user).with_context(
            allowed_company_ids=self.company.ids).create(vals)

    def test_09_settings_need_both_rights(self):
        complete = {'warranty_accounting_journal_id': self.journal.id,
                    'warranty_expense_account_id': self.expense.id,
                    'warranty_provision_account_id': self.provision.id,
                    'warranty_provision_enabled': True, 'warranty_provision_method': 'fixed',
                    'warranty_provision_amount': 25}
        with self.assertRaisesRegex(AccessError, 'both Settings and Accounting Manager'):
            self._settings(self.admin_only, **complete).execute()
        self.assertFalse(self.company.warranty_provision_enabled)
        with self.assertRaises(AccessError):
            self._settings(self.manager_only, **complete).execute()
        self.assertFalse(self.company.warranty_provision_enabled)
        self._settings(self.admin_only).execute()
        self._settings(self.finance_admin, **complete).execute()
        self.assertTrue(self.company.warranty_provision_enabled)
        self.assertEqual(self.company.warranty_provision_amount, 25)
        self.assertFalse(self.other.warranty_provision_enabled, 'the other company is untouched')
        self.assertTrue(self._settings(self.finance_admin).warranty_accounting_can_edit)
        self.assertFalse(self._settings(self.admin_only).warranty_accounting_can_edit)
        # Server side, also in sudo and also directly on the company.
        for user in (self.admin_only, self.manager_only, self.tech):
            with self.assertRaisesRegex(AccessError, 'both Settings and Accounting Manager'):
                self.company.with_user(user).sudo().warranty_provision_amount = 1
        self.company.with_user(self.finance_admin).warranty_provision_amount = 30
        self.company.with_user(self.manager_only).sudo().write({'warranty_provision_amount': 30})

    def test_10_overrides_need_both_rights(self):
        vals = {'warranty_provision_method': 'fixed', 'warranty_provision_amount': 10}
        for record in (self.template, self.category, self.policy):
            self.assertTrue(record.with_user(self.manager_only).sudo().read(['warranty_provision_method']))
            for user in (self.manager_only, self.admin_only, self.accountant, self.product_user,
                         self.tech):
                with self.assertRaises(AccessError, msg='%s %s' % (user.login, record._name)):
                    record.with_user(user).sudo().write(vals)
            record.with_user(self.finance_admin).with_company(self.company).write(vals)
        for model, values in (('product.template', {'name': 'Blocked'}),
                              ('product.category', {'name': 'Blocked'}),
                              ('warranty.policy', {'name': 'Blocked'})):
            with self.assertRaises(AccessError):
                self.env[model].with_user(self.manager_only).sudo().create(dict(values, **vals))

    def test_11_normal_product_and_policy_work_stay_open(self):
        template = self.template.with_user(self.product_user).with_company(self.company)
        template.write({'name': 'Renamed AC', 'warranty_brand': 'GREE', 'list_price': 20})
        self.assertEqual(self.template.name, 'Renamed AC')
        new =self.env['product.template'].with_user(self.product_user).create({'name': 'New AC'})
        self.assertFalse(new.sudo().warranty_provision_method)
        copied = new.copy()
        self.assertTrue(copied)
        self.policy.with_user(self.finance_admin).name = 'Renamed Policy'
        admin_policy = self.env['warranty.policy'].with_user(self.admin_only).create(
            {'name': 'Admin Policy', 'company_id': self.company.id})
        admin_policy.write({'free_service_count': 2})
        self.assertEqual(admin_policy.free_service_count, 2)

    def test_12_read_access(self):
        self._ready()
        for record, names in ((self.company, ['warranty_expense_account_id']),
                              (self.template, ['warranty_provision_method']),
                              (self.category, ['warranty_provision_method']),
                              (self.policy, ['warranty_provision_method'])):
            self.assertTrue(record.with_user(self.accountant).read(names))
            with self.assertRaises(AccessError):
                record.with_user(self.tech).read(names)

    # ------------------------------------------------------------------ 12: companies
    def test_13_company_isolation(self):
        template = self.template.with_company(self.company)
        template.write({'warranty_provision_method': 'fixed', 'warranty_provision_amount': 10})
        self.assertFalse(self.template.with_company(self.other).warranty_provision_method,
                         'an override belongs to the company it was set in')
        rule = self.other._warranty_provision_rule(product=self.product)
        self.assertEqual((rule['method'], rule['level']), ('none', 'company'))
        self.assertEqual(self.company._warranty_provision_rule(product=self.product)['level'],
                         'product')
        self.policy.write({'warranty_provision_method': 'percentage', 'warranty_provision_rate': 7})
        rule = self.other._warranty_provision_rule(category=self.env['product.category'].create(
            {'name': 'Plain', 'warranty_policy_id': self.policy.id}))
        self.assertEqual(rule['level'], 'company', "another company's policy is not applied")
        self._ready(warranty_provision_method='fixed', warranty_provision_amount=9)
        self.assertEqual(self.other.warranty_provision_method, 'disabled')
        self.assertFalse(self.other.warranty_expense_account_id)
        with self.assertRaisesRegex(ValidationError, 'does not belong'):
            self.other.warranty_expense_account_id = self.expense
        user_a = self._user('prov_only_a', self.company, 'account.group_account_readonly')
        with self.assertRaises(AccessError):
            self.other.with_user(user_a).read(['warranty_expense_account_id'])

    # ------------------------------------------------------------------ 13: audit
    def test_14_audit_history(self):
        self._ready()
        self.env.cr.precommit.run()
        self.env.flush_all()
        self.company.with_user(self.finance_admin).write({'warranty_provision_method': 'fixed',
                                                          'warranty_provision_amount': 15})
        self.env.cr.precommit.run()
        self.env.flush_all()
        self.company.invalidate_recordset(['message_ids'])
        message = self.company.message_ids.filtered(
            lambda m: m.author_id == self.finance_admin.partner_id)[:1]
        tracked = message.sudo().tracking_value_ids.field_id.mapped('name')
        self.assertIn('warranty_provision_method', tracked)
        self.assertIn('warranty_provision_amount', tracked)
        for record in (self.template, self.category):
            record.with_user(self.finance_admin).with_company(self.company).write(
                {'warranty_provision_method': 'none'})
            self.env.cr.precommit.run()
            self.env.flush_all()
            record.invalidate_recordset(['message_ids'])
            self.assertIn('warranty_provision_method', record.message_ids.sudo(
            ).tracking_value_ids.field_id.mapped('name'), record._name)
        self.policy.with_user(self.finance_admin).write({'warranty_provision_method': 'percentage',
                                                         'warranty_provision_rate': 6})
        self.company.invalidate_recordset(['message_ids'])
        note = self.company.message_ids[:1]
        self.assertIn(self.policy.name, note.body)
        self.assertIn(self.finance_admin.name, note.body)
        self.assertIn('Provision Percentage', note.body)

    # ------------------------------------------------------------------ 14: no accounting
    def test_15_no_journal_entry_and_no_backfill(self):
        def counts():
            return (self.env['account.move'].search_count([]),
                    self.env['account.move.line'].search_count([]),
                    self.env['stock.valuation.layer'].search_count([]))

        before = counts()
        self._ready(warranty_provision_enabled=True, warranty_provision_method='percentage',
                    warranty_provision_rate=5)
        self._in_company(self.template).write({'warranty_provision_method': 'fixed',
                                               'warranty_provision_amount': 5})
        self.company._warranty_provision_value(self.product, 2, 100)
        self.assertEqual(counts(), before, 'configuration and calculation post nothing')
        partner = self.env['res.partner'].create({'name': 'Provision Customer'})
        income = self._account(self.company, 'PI02', 'income')
        partner.with_company(self.company).property_account_receivable_id = self._account(
            self.company, 'PR02', 'asset_receivable')
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'company_id': self.company.id,
            'invoice_date': fields.Date.today(), 'journal_id': self.sale_journal.id,
            'invoice_line_ids': [(0, 0, {'product_id': self.product.id, 'quantity': 1,
                                         'price_unit': 100, 'tax_ids': [(5, 0, 0)],
                                         'account_id': income.id})]})
        move.action_post()
        self.assertFalse(self.env['account.move.line'].search(
            [('account_id', 'in', (self.expense | self.provision).ids)]),
            'a posted invoice creates no warranty provision entry at this stage')

    def test_16_views_load_for_each_role(self):
        for user in (self.finance_admin, self.admin_only, self.manager_only, self.accountant,
                     self.product_user):
            self.env['product.template'].with_user(user).get_view(
                self.env.ref('product.product_template_form_view').id, 'form')
            self.env['product.category'].with_user(user).get_view(False, 'form')
            self.env['warranty.policy'].with_user(user).get_view(False, 'form')
        for user in (self.finance_admin, self.admin_only):
            self.env['res.config.settings'].with_user(user).get_view(False, 'form')
            self.env['res.company'].with_user(user).get_view(False, 'form')
        finance = self.env['res.config.settings'].with_user(self.finance_admin).get_view(
            False, 'form')['arch']
        self.assertIn('warranty_accounting_settings', finance)
        no_accounting = self.env['res.config.settings'].with_user(self.admin_only).get_view(
            False, 'form')['arch']
        self.assertNotIn('warranty_accounting_settings', no_accounting)
        tech = self.env['product.template'].with_user(self.tech).get_view(
            self.env.ref('product.product_template_form_view').id, 'form')['arch']
        self.assertNotIn('warranty_provision_method', tech)
