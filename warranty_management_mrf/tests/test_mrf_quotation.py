from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import WarrantyMrfCommon


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyMrfQuotation(WarrantyMrfCommon):
    """Phase 5.4 - commercial control of Not Covered lines (mapping 5.4, T4.1 - T4.8).
    Outdoor PCB is Covered, Gas R410A / Fan Motor are excluded items (Not Covered)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({'warranty_mrf_approval_matrix': True,
                           'warranty_mrf_dest_location_id': cls.default_tech_location.id})
        cls.env['warranty.mrf.approval.rule'].create({
            'name': 'All free (test)', 'company_id': cls.company.id, 'no_approval': True})
        Product = cls.env['product.product']
        cls.gas = Product.create({'name': 'Gas R410A', 'type': 'consu', 'standard_price': 3000,
                                  'list_price': 4000, 'invoice_policy': 'order'})
        cls.motor = Product.create({'name': 'Fan Motor', 'type': 'consu', 'standard_price': 1000,
                                    'list_price': 1500, 'invoice_policy': 'order'})
        cls.item_pcb.product_id = cls.part
        cls.item_gas.product_id = cls.gas
        cls.policy.excluded_item_ids |= cls.env['warranty.coverage.item'].create(
            {'name': 'Fan Motor', 'product_id': cls.motor.id})
        cls.helpdesk_user.groups_id |= cls.env.ref('sales_team.group_sale_salesman')
        cls.store = cls._user('mrf_q_store',
                              'material_purchase_requisitions.group_purchase_requisition_user')
        cls.exception_user = cls.approver_b
        cls.company.warranty_mrf_release_exception_user_ids = cls.exception_user | cls.helpdesk_user
        cls.env['stock.quant']._update_available_quantity(cls.part, cls.warehouse.lot_stock_id, 10)

    # ------------------------------------------------------------------ helpers
    def _mrf(self, lines, case=None):
        case = case or self._approved()
        action = case.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {
                'product_id': product.id, 'description': product.name, 'qty': qty,
                'uom': product.uom_id.id, 'requisition_type': 'internal'})
                for product, qty in lines]})
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual(mrf.state, 'approve')
        return mrf

    def _line(self, mrf, product):
        return mrf.requisition_line_ids.filtered(lambda line: line.product_id == product)

    def _quote(self, mrf, user=None):
        action = mrf.with_user(user or self.helpdesk_user).action_create_parts_quotation()
        return self.env['sale.order'].browse(action['res_id'])

    def _invoice(self, order):
        invoice = order._create_invoices()
        invoice.action_post()
        return invoice

    def _pay(self, invoice, amount=None):
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create(
            {'amount': amount or invoice.amount_residual}).action_create_payments()

    def _validate(self, picking):
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        return picking.button_validate()

    # ------------------------------------------------------------------ T4.1 / T4.2
    def test_01_quotation_only_not_covered(self):
        """T4.1 / T4.2: quotation only for approved Not Covered lines; customer, site, company,
        case links; no chargeable purpose; send To-Do; not twice; not before approval."""
        mrf = self._mrf([(self.part, 1), (self.gas, 2)])
        part, gas = self._line(mrf, self.part), self._line(mrf, self.gas)
        self.assertFalse(part.chargeable_state)
        self.assertEqual(gas.chargeable_state, 'to_quote')
        self.assertTrue(mrf.can_create_parts_quotation)
        order = self._quote(mrf)
        case = mrf.warranty_case_id
        self.assertEqual(order.order_line.product_id, self.gas)
        self.assertEqual((order.order_line.product_uom_qty, order.order_line.price_unit), (2, 4000))
        self.assertEqual(order.partner_id, case.partner_id.commercial_partner_id)
        self.assertEqual(order.partner_shipping_id, case.site_id or order.partner_id)
        self.assertEqual((order.company_id, order.warranty_mrf_id, order.warranty_case_id),
                         (mrf.company_id, mrf, case))
        self.assertFalse(order.warranty_chargeable_purpose)
        self.assertEqual(order.warranty_release_trigger, 'confirmation')
        self.assertEqual((gas.requisition_type, gas.chargeable_state), ('sale', 'waiting_customer'))
        self.assertIn(order, case.sale_order_ids)
        self.assertTrue(case.activity_ids.filtered(lambda a: order.name in a.summary))
        self.assertEqual(mrf.parts_quotation_count, 1)
        with self.assertRaisesRegex(UserError, 'no Not Covered line to quote'):
            mrf.with_user(self.helpdesk_user).action_create_parts_quotation()
        self.assertEqual(sorted(mrf.sudo().warranty_approval_ids.mapped('level')), ['none'],
                         'approval history unchanged')
        draft = self._approved()
        action = draft.with_user(self.helpdesk_user).action_create_material_request()
        new = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {'product_id': self.gas.id, 'description': 'Gas',
                                             'qty': 1, 'uom': self.gas.uom_id.id})]})
        with self.assertRaisesRegex(UserError, 'not approved'):
            new.with_user(self.helpdesk_user).action_create_parts_quotation()

    def test_02_confirmation_release_and_no_double_issue(self):
        """T4.3 (On Confirmation) / T4.8, Figure 7 D2: covered lines are issued on their own
        release (not held back by the Not Covered lines); the internal picking never contains
        Not Covered material; the quotation's delivery is the only issue and is validated after
        confirmation."""
        mrf = self._mrf([(self.part, 1), (self.gas, 2)])
        order = self._quote(mrf)
        mrf.with_user(self.store).request_stock()
        internal = self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id)])
        self.assertEqual(internal.move_ids.product_id, self.part)
        self.assertFalse(order.picking_ids)
        order.with_user(self.helpdesk_user).action_confirm()
        gas = self._line(mrf, self.gas)
        self.assertEqual(gas.chargeable_state, 'released')
        delivery = order.picking_ids
        self.assertEqual(delivery.move_ids.product_id, self.gas)
        self.assertEqual(self.env['stock.move'].search_count(
            [('product_id', '=', self.gas.id), ('state', '!=', 'cancel'),
             ('picking_id', 'in', (internal | delivery).ids)]), 1, 'gas issued once')
        self._validate(delivery)
        self.assertEqual(delivery.state, 'done')

    # ------------------------------------------------------------------ T4.3
    def test_03_payment_trigger(self):
        """T4.3 On Payment: confirmed -> Waiting Payment (delivery blocked); posted invoice,
        partial payment -> still blocked; full payment -> released; the trigger is the
        snapshot of the quotation; a reversed invoice does not release."""
        self.company.warranty_mrf_release_trigger = 'payment'
        mrf = self._mrf([(self.gas, 2)])
        order = self._quote(mrf)
        self.company.warranty_mrf_release_trigger = 'confirmation'
        self.assertEqual(order.warranty_release_trigger, 'payment')
        order.with_user(self.helpdesk_user).action_confirm()
        gas = self._line(mrf, self.gas)
        self.assertEqual(gas.chargeable_state, 'waiting_payment')
        with self.assertRaisesRegex(UserError, 'not released'):
            self._validate(order.picking_ids)
        invoice = self._invoice(order)
        self.assertEqual(gas.chargeable_state, 'waiting_payment')
        self._pay(invoice, invoice.amount_total / 2)
        gas.invalidate_recordset(['chargeable_state'])
        self.assertEqual(gas.chargeable_state, 'waiting_payment', 'partial payment')
        self._pay(invoice)
        gas.invalidate_recordset(['chargeable_state'])
        self.assertEqual(gas.chargeable_state, 'released')
        self._validate(order.picking_ids)
        self.assertEqual(order.picking_ids.state, 'done')
        # Reversed invoice.
        self.company.warranty_mrf_release_trigger = 'payment'
        other = self._mrf([(self.gas, 1)])
        order2 = self._quote(other)
        order2.action_confirm()
        invoice2 = self._invoice(order2)
        invoice2._reverse_moves(cancel=True)
        self.assertEqual(invoice2.payment_state, 'reversed')
        self.assertEqual(self._line(other, self.gas).chargeable_state, 'waiting_payment')

    # ------------------------------------------------------------------ T4.4
    def test_04_release_exception(self):
        """T4.4: only Chargeable Release Exception Users, not the requester; reason required;
        released (exception) -> delivery allowed."""
        self.company.warranty_mrf_release_trigger = 'payment'
        mrf = self._mrf([(self.gas, 1)])
        order = self._quote(mrf)
        self.assertFalse(mrf.with_user(self.exception_user).can_approve_release_exception)
        order.action_confirm()
        self.assertTrue(mrf.with_user(self.exception_user).can_approve_release_exception)
        self.assertFalse(mrf.with_user(self.helpdesk_user).can_approve_release_exception)
        with self.assertRaises(AccessError):
            mrf.with_user(self.helpdesk_user).action_open_release_exception()
        with self.assertRaises(AccessError):
            mrf.with_user(self.approver_a)._warranty_approve_release_exception(order, 'x')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            mrf.with_user(self.exception_user)._warranty_approve_release_exception(order, ' ')
        action = mrf.with_user(self.exception_user).action_open_release_exception()
        self.env['warranty.mrf.release.exception.wizard'].with_user(self.exception_user) \
            .with_context(**action['context']).create({'reason': 'Long-term customer'}) \
            .action_approve()
        self.assertEqual(self._line(mrf, self.gas).chargeable_state, 'released_exception')
        self.assertEqual(order.warranty_release_exception_by_id, self.exception_user)
        self._validate(order.picking_ids)
        self.assertEqual(order.picking_ids.state, 'done')

    # ------------------------------------------------------------------ T4.5
    def test_05_decline_and_cancel(self):
        """T4.5: Customer Declined removes the lines from the open quotation (cancelled when
        nothing remains); covered lines continue; not after confirmation; a cancelled quotation
        puts the lines back to To Quote."""
        mrf = self._mrf([(self.part, 1), (self.gas, 1), (self.motor, 1)])
        order = self._quote(mrf)
        gas, motor = self._line(mrf, self.gas), self._line(mrf, self.motor)
        with self.assertRaises(AccessError):
            mrf.with_user(self.tech)._warranty_decline_chargeable(motor, 'x')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            mrf.with_user(self.helpdesk_user)._warranty_decline_chargeable(motor, '')
        action = mrf.with_user(self.helpdesk_user).action_open_chargeable_decline()
        self.env['warranty.mrf.decline.wizard'].with_user(self.helpdesk_user).with_context(
            **action['context']).create({'line_ids': [(6, 0, motor.ids)],
                                         'reason': 'Too expensive'}).action_decline()
        self.assertEqual(motor.chargeable_state, 'declined')
        self.assertEqual(order.order_line.product_id, self.gas)
        self.assertEqual(order.state, 'draft')
        order._action_cancel()
        self.assertEqual(gas.chargeable_state, 'to_quote')
        order2 = self._quote(mrf)
        self.assertEqual(order2.order_line.product_id, self.gas)
        mrf.with_user(self.helpdesk_user)._warranty_decline_chargeable(gas, 'Customer repairs')
        self.assertEqual(order2.state, 'cancel')
        self.assertEqual(gas.chargeable_state, 'declined')
        mrf.with_user(self.store).request_stock()
        picking = self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id)])
        self.assertEqual(picking.move_ids.product_id, self.part)
        confirmed = self._mrf([(self.gas, 1)])
        self._quote(confirmed).action_confirm()
        with self.assertRaisesRegex(UserError, 'can be declined'):
            confirmed.with_user(self.helpdesk_user)._warranty_decline_chargeable(
                confirmed.requisition_line_ids, 'late')
        self.assertTrue(self._logged(mrf.warranty_case_id, 'Too expensive'))

    def _logged(self, record, text):
        return any(text in (message.body or '') for message in record.message_ids)

    # ------------------------------------------------------------------ T4.6
    def test_06_no_service_job_from_parts_quotation(self):
        """T4.6: a parts quotation of a Chargeable case never gets a Chargeable Purpose and
        never creates a Service Job (Part 4.10 untouched)."""
        case = self._approved()
        case.sudo().write({'state': 'chargeable', 'chargeable_type': 'repair'})
        mrf = self._mrf([(self.part, 1)], case=case)
        self.assertEqual(mrf.requisition_line_ids.coverage_type, 'not_covered')
        order = self._quote(mrf)
        self.assertFalse(order.warranty_chargeable_purpose)
        order.action_confirm()
        self.assertFalse(self.env['warranty.service.job'].search(
            [('chargeable_order_id', '=', order.id)]))
        self.assertFalse(case._warranty_trigger_orders())

    # ------------------------------------------------------------------ T4.7 / permissions
    def test_07_guards_and_permissions(self):
        """T4.7: Sales rights to quote; quotation lines locked; warranty fields only by the
        workflow; the Customer Quotation action cannot be set or removed by users; one active
        quotation line per request line; delivery of a non-released line refused."""
        mrf = self._mrf([(self.part, 1), (self.gas, 1)])
        with self.assertRaisesRegex(AccessError, 'Sales rights'):
            mrf.with_user(self.approver_b).action_create_parts_quotation()
        gas = self._line(mrf, self.gas)
        part = self._line(mrf, self.part)
        with self.assertRaisesRegex(UserError, 'Customer Quotation'):
            part.with_user(self.store).write({'requisition_type': 'sale'})
        order = self._quote(mrf)
        with self.assertRaisesRegex(UserError, 'Customer Quotation'):
            gas.with_user(self.store).write({'requisition_type': 'internal'})
        sol = order.order_line.with_user(self.helpdesk_user)
        with self.assertRaisesRegex(UserError, 'approved Material Request'):
            sol.write({'product_uom_qty': 5})
        sol.write({'price_unit': 3800})
        with self.assertRaisesRegex(UserError, 'Customer Declined'):
            sol.unlink()
        with self.assertRaisesRegex(UserError, 'set by the warranty workflow'):
            order.with_user(self.helpdesk_user).write({'warranty_release_trigger': 'payment'})
        with self.assertRaisesRegex(UserError, 'set by the warranty workflow'):
            self.env['sale.order'].with_user(self.helpdesk_user).create(
                {'partner_id': self.customer.id, 'warranty_mrf_id': mrf.id})
        with self.assertRaisesRegex(UserError, 'Create Parts Quotation'):
            self.env['sale.order.line'].with_user(self.helpdesk_user).create(
                {'order_id': order.id, 'product_id': self.gas.id,
                 'warranty_mrf_line_id': gas.id})
        copied = order.copy()
        with self.assertRaisesRegex(ValidationError, 'must belong to a parts quotation'):
            copied.order_line.sudo().write({'warranty_mrf_line_id': gas.id})
        copied.sudo().warranty_mrf_id = mrf
        with self.assertRaisesRegex(ValidationError, 'another active quotation'):
            copied.order_line.sudo().write({'warranty_mrf_line_id': gas.id})
        order.action_confirm()
        self.company.warranty_mrf_release_trigger = 'payment'
        payment_mrf = self._mrf([(self.gas, 1)])
        payment_order = self._quote(payment_mrf)
        payment_order.action_confirm()
        with self.assertRaisesRegex(UserError, 'Waiting Payment'):
            self._validate(payment_order.picking_ids)

    def test_08_views_render(self):
        for user in (self.helpdesk_user, self.store, self.approver_b):
            views = self.Mrf.with_user(user).get_views([(False, 'form')])
            self.assertIn('action_create_parts_quotation', views['views']['form']['arch'])
            for model in ('warranty.mrf.decline.wizard', 'warranty.mrf.release.exception.wizard'):
                self.env[model].with_user(user).get_views([(False, 'form')])
        views = self.env['sale.order'].with_user(self.helpdesk_user).get_views([(False, 'form')])
        self.assertIn('warranty_mrf_id', views['views']['form']['arch'])
        settings = self.env['res.config.settings'].get_views([(False, 'form')])
        self.assertIn('warranty_mrf_release_trigger', settings['views']['form']['arch'])
