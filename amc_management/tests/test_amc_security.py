from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged

from .common import AmcCommon


@tagged('post_install', '-at_install', 'amc')
class TestAmcSecurity(AmcCommon):
    """Security (AMC-H03), multi-company and non-AMC regression tests (docs/17, docs/20)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_2 = cls.setup_other_company(name='AMC Company 2')['company']
        cls.user_both = new_test_user(
            cls.env, login='amc_both', name='AMC Manager Both', company_id=cls.company.id,
            company_ids=(cls.company | cls.company_2).ids,
            groups_id=[cls.env.ref('amc_management.group_amc_manager').id,
                       cls.env.ref('sales_team.group_sale_salesman').id])

    # ------------------------------------------------------------------ roles
    def test_tc050_employee_without_amc_role(self):
        """TC-050 / AMC-H03: an employee without AMC role cannot read or create contracts."""
        contract = self._create_contract()
        with self.assertRaises(AccessError):
            contract.with_user(self.user_employee).read(['name'])
        with self.assertRaises(AccessError):
            self.env['amc.contract'].with_user(self.user_employee).create({
                'partner_id': self.customer.id, 'company_id': self.company.id})

    def test_tc051_role_matrix(self):
        """TC-051 / AMC-H03: User reads / prepares Draft; Coordinator prices and quotes;
        Manager holds and closes - enforced server-side, not only by hidden buttons."""
        contract = self._create_contract().with_user(self.user_amc)
        contract.read(['name', 'state'])
        with self.assertRaises(AccessError):
            contract.action_compute_price()
        coordinator = contract.with_user(self.user_coordinator)
        coordinator.action_compute_price()
        coordinator.action_create_quotation()
        self.env['sale.order'].browse(contract.sudo().sale_order_id.id).action_confirm()
        self.assertEqual(contract.state, 'active')
        with self.assertRaises(AccessError):
            coordinator._amc_hold('no')
        with self.assertRaises(AccessError):
            coordinator._amc_close('no')
        with self.assertRaises(AccessError):
            contract.with_user(self.user_amc).action_renew()
        with self.assertRaises(AccessError):
            self.env['amc.plan'].with_user(self.user_coordinator).create({
                'name': 'X', 'visit_count': 1, 'frequency_value': 1})
        with self.assertRaises(UserError):  # AccessError is a UserError: either refusal
            contract.billing_line_ids.with_user(self.user_manager).write({'state': 'cancelled'})

    def test_tc052_billing_and_visit_rpc_protection(self):
        """TC-052: billing lines and entitlements cannot be forged through the ORM / RPC."""
        contract = self._create_contract()
        self._sell(contract)
        with self.assertRaises(UserError):
            contract.billing_line_ids.write({'state': 'planned'})
        with self.assertRaises(UserError):
            self.env['amc.billing.line'].create({'contract_id': contract.id, 'amount': 1.0})
        with self.assertRaises(UserError):
            contract.visit_ids[0].with_user(self.user_manager).write({'due_date': False})

    # ------------------------------------------------------------------ multi-company
    def test_tc060_company_isolation(self):
        """TC-060 / NFR multi-company: a user of company 1 does not see company 2 contracts and
        visits; a user of both companies does."""
        plan_2 = self.env['amc.plan'].with_company(self.company_2).create({
            'name': 'Company 2 AMC', 'company_id': self.company_2.id, 'visit_count': 1,
            'frequency_value': 1, 'billing_plan_id': self.billing_upfront.id})
        contract_2 = self.env['amc.contract'].with_company(self.company_2).create({
            'partner_id': self.customer.id, 'company_id': self.company_2.id,
            'plan_id': plan_2.id,
            'line_ids': [Command.create({'product_id': self.equipment_untracked.id})]})
        visible = self.env['amc.contract'].with_user(self.user_manager).search(
            [('id', '=', contract_2.id)])
        self.assertFalse(visible)
        visible = self.env['amc.contract'].with_user(self.user_both).with_context(
            allowed_company_ids=(self.company | self.company_2).ids).search(
            [('id', '=', contract_2.id)])
        self.assertEqual(visible, contract_2)

    def test_tc061_cross_company_plan_rejected(self):
        """TC-061: a contract cannot use the plan of another company."""
        plan_2 = self.env['amc.plan'].create({
            'name': 'Company 2 only', 'company_id': self.company_2.id, 'visit_count': 1,
            'frequency_value': 1, 'billing_plan_id': self.billing_upfront.id})
        with self.assertRaises(ValidationError):
            self._create_contract(plan=plan_2)

    def test_tc062_sequences_per_company(self):
        """TC-062: entitlement references come from the AMC Visit sequence."""
        contract = self._create_contract()
        self._sell(contract)
        self.assertTrue(all(name.startswith('AMCV/') for name in contract.visit_ids.mapped('name')))

    # ------------------------------------------------------------------ non-AMC regression
    def test_tc070_regular_sale_order_unchanged(self):
        """TC-070 / REG-01: a regular Sales Order (no AMC contract) is created, edited,
        duplicated, confirmed, delivered manually, invoiced and cancelled as in standard Odoo."""
        service = self.env['product.product'].create({
            'name': 'Regular service', 'type': 'service', 'invoice_policy': 'delivery',
            'service_type': 'manual', 'list_price': 100.0,
            'property_account_income_id': self.company_data['default_account_revenue'].id,
            'taxes_id': [Command.clear()]})
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({'product_id': service.id, 'product_uom_qty': 2})]})
        order.order_line.write({'price_unit': 120.0, 'discount': 5.0})
        order.write({'order_line': [Command.create({'product_id': service.id})]})
        copy = order.copy()
        order.action_confirm()
        order.order_line[0].qty_delivered = 2
        invoice = order._create_invoices()
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        self.assertFalse(order.amc_contract_id)
        copy._action_cancel()
        self.assertEqual(copy.state, 'cancel')

    def test_tc071_amc_order_protected(self):
        """TC-071: AMC quotations keep the values set by the contract."""
        contract = self._create_contract()
        contract.action_compute_price()
        contract.action_create_quotation()
        order = contract.sale_order_id
        with self.assertRaises(UserError):
            order.order_line.write({'price_unit': 1.0})
        with self.assertRaises(UserError):
            order.write({'order_line': [Command.create({'product_id': self.product_a.id})]})
        with self.assertRaises(UserError):
            order.copy()
        with self.assertRaises(UserError):
            self.env['sale.order'].create({'partner_id': self.customer.id,
                                           'amc_contract_id': contract.id})

    def test_tc072_regular_invoice_paid_hook_noop(self):
        """TC-072 / REG-02: paying an invoice without AMC order leaves AMC contracts as they
        are (paid hook scoped to AMC orders)."""
        self.plan_retail.activation_trigger = 'payment'
        contract = self._create_contract()
        self._sell(contract)
        self.assertEqual(contract.state, 'awaiting_payment')
        invoice = self.init_invoice('out_invoice', partner=self.customer, post=True,
                                    products=self.product_a)
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        self.assertEqual(contract.state, 'awaiting_payment')
