from datetime import date

from odoo import Command, fields
from odoo.tests import new_test_user

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class AmcCommon(AccountTestInvoicingCommon):
    """Shared AMC test data (docs/16_AMC_Test_Strategy.md): one company with accounting, AMC
    roles, an equipment product, plans (Retail 3 visits / Project 2 visits per year) and Active
    formula versions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True,
                                       mail_create_nolog=True, mail_notrack=True))
        cls.company = cls.env.company
        # The accounting test user runs the commercial flow: AMC Manager + Sales roles.
        cls.env.user.groups_id |= cls.env.ref('amc_management.group_amc_manager') \
            | cls.env.ref('sales_team.group_sale_salesman')
        cls.company.write({'amc_activation_trigger': 'sale_confirmation',
                           'amc_default_pricelist_id': False})
        cls.currency = cls.company.currency_id
        group = lambda xmlid: cls.env.ref(xmlid).id  # noqa: E731
        base_groups = [group('base.group_user'), group('sales_team.group_sale_salesman'),
                       group('account.group_account_invoice')]
        cls.user_amc = new_test_user(cls.env, login='amc_user', name='AMC User',
                                     groups_id=base_groups + [group('amc_management.group_amc_user')],
                                     company_id=cls.company.id, company_ids=cls.company.ids)
        cls.user_coordinator = new_test_user(
            cls.env, login='amc_coord', name='AMC Coordinator', company_id=cls.company.id,
            company_ids=cls.company.ids,
            groups_id=base_groups + [group('amc_management.group_amc_coordinator')])
        cls.user_manager = new_test_user(
            cls.env, login='amc_mgr', name='AMC Manager', company_id=cls.company.id,
            company_ids=cls.company.ids,
            groups_id=base_groups + [group('amc_management.group_amc_manager')])
        cls.user_employee = new_test_user(cls.env, login='amc_none', name='Employee',
                                          groups_id=[group('base.group_user')],
                                          company_id=cls.company.id,
                                          company_ids=cls.company.ids)
        cls.customer = cls.env['res.partner'].create({
            'name': 'ABC Hotel', 'company_id': False,
            'property_account_receivable_id': cls.company_data['default_account_receivable'].id,
        })
        cls.site = cls.env['res.partner'].create({'name': 'ABC Hotel - Weligama',
                                                  'parent_id': cls.customer.id,
                                                  'type': 'delivery'})
        cls.category = cls.env['product.category'].create({'name': 'Air Conditioners (AMC)'})
        cls.equipment = cls.env['product.product'].create({
            'name': 'GREE 9000 BTU', 'type': 'consu', 'is_storable': True,
            'tracking': 'serial', 'categ_id': cls.category.id})
        cls.equipment_untracked = cls.env['product.product'].create({
            'name': 'Split A/C', 'type': 'consu', 'categ_id': cls.category.id})
        amc_product = cls.company._amc_product()
        amc_product.write({
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
            'taxes_id': [Command.clear()]})
        cls.billing_upfront = cls.env.ref('amc_management.billing_plan_upfront')
        cls.billing_quarterly = cls.env.ref('amc_management.billing_plan_quarterly')
        cls.billing_per_visit = cls.env.ref('amc_management.billing_plan_per_visit')
        cls.plan_retail = cls._create_plan('Retail AMC (test)', visits=3, free=1)
        cls.plan_project = cls._create_plan('Project AMC (test)', visits=2, free=0)

    @classmethod
    def _create_plan(cls, name, visits=3, free=1, billing=None, method='fixed', amount=30000.0,
                     **values):
        plan = cls.env['amc.plan'].create(dict({
            'name': name, 'company_id': cls.company.id, 'visit_count': visits,
            'frequency_value': visits or 1, 'frequency_unit': 'year',
            'included_free_services': free, 'duration_value': 12, 'duration_unit': 'months',
            'billing_plan_id': (billing or cls.billing_upfront).id, 'pricing_method': method,
            'alert_days': 7, 'renewal_notice_days': 30,
        }, **values))
        formula_values = {'plan_id': plan.id, 'method': method,
                          'effective_from': date(2020, 1, 1),
                          'currency_id': cls.currency.id}
        if method == 'fixed':
            formula_values['fixed_amount'] = amount
        elif method == 'per_unit':
            formula_values['unit_rate'] = amount
        elif method == 'per_visit':
            formula_values['visit_rate'] = amount
        elif method == 'usage':
            formula_values.update(usage_base=amount, usage_rate=15.0)
        formula = cls.env['amc.pricing.formula'].create(formula_values)
        formula.action_activate()
        return plan

    def _new_serial(self, name, product=None):
        return self.env['stock.lot'].create({'name': name,
                                             'product_id': (product or self.equipment).id,
                                             'company_id': self.company.id})

    def _create_contract(self, plan=None, lines=None, **values):
        lines = lines or [{'product_id': self.equipment_untracked.id, 'quantity': 1.0}]
        return self.env['amc.contract'].create(dict({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'company_id': self.company.id, 'plan_id': (plan or self.plan_retail).id,
            'line_ids': [Command.create(line) for line in lines],
        }, **values))

    def _sell(self, contract):
        """Price, quotation and Sales Order confirmation (the standard commercial flow)."""
        contract.action_compute_price()
        contract.action_create_quotation()
        contract.sale_order_id.action_confirm()
        return contract.sale_order_id

    def _invoice_and_pay(self, contract):
        contract.action_create_invoice()
        invoice = contract.sale_order_id.invoice_ids.filtered(lambda m: m.state == 'draft')
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        return invoice

    def _today(self):
        return fields.Date.context_today(self.env.user)
