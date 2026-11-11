from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from .common import WarrantyMrfCommon


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyMrfFulfilment(WarrantyMrfCommon):
    """Phase 5.5 - availability, issue, purchasing, receipts and backorders (mapping 5.5,
    decisions F-1 - F-8). Requests are approved by an explicit No Approval rule."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({'warranty_mrf_approval_matrix': True,
                           'warranty_mrf_dest_location_id': cls.default_tech_location.id})
        cls.env['warranty.mrf.approval.rule'].create({
            'name': 'All free (5.5 test)', 'company_id': cls.company.id, 'no_approval': True})
        Product = cls.env['product.product']
        cls.vendor = cls.env['res.partner'].create({'name': 'Cool Parts Ltd', 'is_company': True})
        cls.filter = Product.create({'name': 'Air Filter', 'is_storable': True, 'type': 'consu',
                                     'standard_price': 500})
        cls.valve = Product.create({'name': 'Expansion Valve', 'is_storable': True,
                                    'type': 'consu', 'standard_price': 2000,
                                    'seller_ids': [(0, 0, {'partner_id': cls.vendor.id,
                                                           'price': 1800})]})
        cls.sensor = Product.create({'name': 'Temperature Sensor', 'is_storable': True,
                                     'type': 'consu', 'standard_price': 700, 'tracking': 'serial'})
        cls.gas = Product.create({'name': 'Gas R410A', 'type': 'consu', 'standard_price': 3000,
                                  'list_price': 4000, 'invoice_policy': 'order'})
        items = cls.env['warranty.coverage.item'].create([
            {'name': product.name, 'product_id': product.id}
            for product in (cls.filter, cls.valve, cls.sensor)])
        cls.policy.covered_item_ids |= items
        cls.item_gas.product_id = cls.gas
        cls.store = cls._user('mrf_f_store',
                              'material_purchase_requisitions.group_purchase_requisition_user')
        cls.stock_only = cls._user('mrf_f_stock', 'stock.group_stock_user')
        cls.helpdesk_user.groups_id |= cls.env.ref('sales_team.group_sale_salesman')
        cls.stock = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------ helpers
    def _add_stock(self, product, qty, lot=None):
        self.env['stock.quant']._update_available_quantity(product, self.stock, qty, lot_id=lot)

    def _mrf(self, lines, case=None, job=None):
        record = job or case or self._approved()
        action = record.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {
                'product_id': product.id, 'description': product.name, 'qty': qty,
                'uom': product.uom_id.id}) for product, qty in lines]})
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual(mrf.state, 'approve')
        return mrf

    def _line(self, mrf, product):
        return mrf.requisition_line_ids.filtered(lambda line: line.product_id == product)

    def _fulfil(self, mrf, user=None):
        mrf.with_user(user or self.store).action_warranty_fulfil()

    def _issue_pickings(self, mrf):
        return self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id)])

    def _validate(self, picking, qty=None):
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty if qty is None else qty
            move.picked = True
        result = picking.button_validate()
        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            self.env['stock.backorder.confirmation'].with_context(result['context']) \
                .create({}).process()

    # ------------------------------------------------------------------ availability
    def test_01_full_availability(self):
        """Full stock: availability Available, one issue picking, no RFQ; validation ->
        Issued; Received allowed; nothing left to process."""
        self._add_stock(self.filter, 10)
        mrf = self._mrf([(self.filter, 4)])
        line = self._line(mrf, self.filter)
        self.assertEqual((line.approved_qty, line.outstanding_qty, line.available_qty,
                          line.availability, line.issue_state), (4, 4, 10, 'available', 'to_issue'))
        self.assertTrue(mrf.can_warranty_fulfil)
        self._fulfil(mrf)
        picking = self._issue_pickings(mrf)
        self.assertEqual((picking.move_ids.product_uom_qty, picking.location_dest_id),
                         (4, self.default_tech_location))
        self.assertFalse(mrf.purchase_order_ids)
        self.assertEqual((mrf.state, mrf.warranty_mrf_status, line.in_issue_qty,
                          line.outstanding_qty), ('stock', 'released', 4, 0))
        self.assertEqual((picking.warranty_mrf_id, picking.warranty_mrf_case_id),
                         (mrf, mrf.warranty_case_id))
        with self.assertRaisesRegex(UserError, 'Nothing to issue'):
            self._fulfil(mrf)
        self._validate(picking)
        self.assertEqual((line.issued_qty, line.issue_state, mrf.warranty_mrf_status),
                         (4, 'issued', 'issued'))
        mrf.with_user(self.store).action_received()
        self.assertEqual(mrf.state, 'receive')

    def test_02_partial_stock_purchase_receipt_remaining(self):
        """Partial stock: available part issued, shortage on an RFQ to the product vendor;
        Partially Issued; receipt -> Issue Remaining -> Issued; links to case / job."""
        self._add_stock(self.valve, 2)
        job = self._confirmed_job()
        mrf = self._mrf([(self.valve, 5)], job=job)
        line = self._line(mrf, self.valve)
        self.assertEqual((line.available_qty, line.availability), (2, 'partial'))
        self._fulfil(mrf)
        picking = self._issue_pickings(mrf)
        order = mrf.sudo().purchase_order_ids
        self.assertEqual(picking.move_ids.product_uom_qty, 2)
        self.assertEqual((order.partner_id, order.order_line.product_qty,
                          order.order_line.custom_requisition_line_id, order.warranty_mrf_case_id,
                          order.warranty_mrf_job_id), (self.vendor, 3, line, job.warranty_case_id, job))
        self.assertEqual(order.order_line.price_unit, 1800)
        self.assertEqual(job.material_status, 'shortage')
        self._validate(picking)
        self.assertEqual((line.issued_qty, line.issue_state, mrf.warranty_mrf_status),
                         (2, 'partial', 'partially_issued'))
        with self.assertRaisesRegex(UserError, 'not completely issued'):
            mrf.with_user(self.store).action_received()
        with self.assertRaisesRegex(UserError, 'Nothing to issue'):
            self._fulfil(mrf)
        order.button_confirm()
        receipt = order.picking_ids
        self.assertEqual(receipt.warranty_mrf_id, mrf)
        self._validate(receipt)
        self.assertEqual((line.purchased_qty, line.received_qty), (3, 3))
        self._fulfil(mrf)
        remaining = self._issue_pickings(mrf) - picking
        self.assertEqual(remaining.move_ids.product_uom_qty, 3)
        self.assertEqual(len(mrf.purchase_order_ids), 1, 'no second RFQ')
        self._validate(remaining)
        self.assertEqual((line.issued_qty, mrf.warranty_mrf_status, job.material_status),
                         (5, 'issued', 'issued'))

    def test_03_out_of_stock(self):
        """No stock: without a vendor -> Awaiting Stock (Figure 7 D4: notification, note, one
        To-Do, nothing created, same request); with a line vendor (Store user) -> RFQ for the
        full quantity, no picking; open RFQ -> nothing more to buy."""
        mrf = self._mrf([(self.filter, 3)])
        line = self._line(mrf, self.filter)
        self.assertEqual(line.availability, 'unavailable')
        result = mrf.with_user(self.store).action_warranty_fulfil()
        self.assertEqual((result['tag'], result['params']['type']), ('display_notification',
                                                                      'warning'))
        self.assertIn('No stock and no vendor', line.stock_wait_reason)
        self.assertEqual((mrf.state, mrf.warranty_stock_status), ('approve', 'awaiting'))
        self.assertFalse(self._issue_pickings(mrf) or mrf.purchase_order_ids)
        line.with_user(self.store).write({'partner_id': [(6, 0, self.vendor.ids)]})
        self._fulfil(mrf)
        self.assertFalse(self._issue_pickings(mrf))
        self.assertEqual(mrf.purchase_order_ids.order_line.product_qty, 3)
        with self.assertRaisesRegex(UserError, 'Nothing to issue'):
            self._fulfil(mrf)

    def test_04_backorder(self):
        """Partial validation -> backorder linked to the request; issued / in picking
        quantities; the backorder completes the line."""
        self._add_stock(self.filter, 10)
        mrf = self._mrf([(self.filter, 6)])
        line = self._line(mrf, self.filter)
        self._fulfil(mrf)
        picking = self._issue_pickings(mrf)
        self._validate(picking, qty=4)
        backorder = self._issue_pickings(mrf) - picking
        self.assertEqual((backorder.backorder_id, backorder.warranty_mrf_id), (picking, mrf))
        self.assertEqual((line.issued_qty, line.in_issue_qty, line.outstanding_qty), (4, 2, 0))
        self.assertEqual(mrf.warranty_mrf_status, 'partially_issued')
        with self.assertRaisesRegex(UserError, 'Nothing to issue'):
            self._fulfil(mrf)
        self._validate(backorder)
        self.assertEqual((line.issued_qty, mrf.warranty_mrf_status), (6, 'issued'))

    def test_05_no_over_issue(self):
        """Validated quantities never exceed the approved quantity (duplicate issue)."""
        self._add_stock(self.filter, 10)
        mrf = self._mrf([(self.filter, 3)])
        self._fulfil(mrf)
        picking = self._issue_pickings(mrf)
        with self.assertRaisesRegex(UserError, 'exceed the approved quantity'):
            self._validate(picking, qty=5)
        self._validate(picking)
        self.assertEqual(self._line(mrf, self.filter).issued_qty, 3)

    def test_06_serial_tracking(self):
        """Serial products: the requested serial must be issued; another serial is refused."""
        lots = self.env['stock.lot'].create([
            {'name': name, 'product_id': self.sensor.id} for name in ('TS-001', 'TS-002')])
        for lot in lots:
            self._add_stock(self.sensor, 1, lot)
        case = self._approved()
        action = case.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {
                'product_id': self.sensor.id, 'description': 'Sensor', 'qty': 1,
                'uom': self.sensor.uom_id.id, 'lot_ids': [(6, 0, lots[0].ids)]})]})
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self._fulfil(mrf)
        picking = self._issue_pickings(mrf)
        picking.move_ids.move_line_ids.lot_id = lots[1]
        with self.assertRaisesRegex(UserError, 'requested serial'):
            self._validate(picking)
        picking.move_ids.move_line_ids.lot_id = lots[0]
        self._validate(picking)
        self.assertEqual(picking.move_ids.move_line_ids.lot_id, lots[0])
        self.assertEqual(self._line(mrf, self.sensor).issue_state, 'issued')

    # ------------------------------------------------------------------ controls
    def test_07_unapproved_blocked(self):
        """Draft / waiting requests are never issued or purchased."""
        self._add_stock(self.filter, 10)
        case = self._approved()
        action = case.with_user(self.helpdesk_user).action_create_material_request()
        draft = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {'product_id': self.filter.id, 'description': 'F',
                                             'qty': 1, 'uom': self.filter.uom_id.id})]})
        self.assertFalse(draft.can_warranty_fulfil)
        with self.assertRaisesRegex(UserError, 'approved Material Requests only'):
            self._fulfil(draft)
        self.env['warranty.mrf.approval.rule'].search([]).active = False
        manager = self._user('mrf_f_manager')
        self.env['warranty.mrf.approval.rule'].create({
            'name': 'Manager', 'company_id': self.company.id, 'manager_required': True,
            'manager_user_ids': [(6, 0, manager.ids)]})
        draft.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual(draft.state, 'dept_confirm')
        with self.assertRaisesRegex(UserError, 'approved Material Requests only'):
            self._fulfil(draft)
        self.assertFalse(self._issue_pickings(draft))

    def test_08_mixed_request_unpaid_chargeable(self):
        """Mixed request, On Payment: the covered line is issued by the request (Figure 7 D2:
        not held back by the Not Covered line); the Not Covered line only by the quotation
        delivery after payment; no duplicate movement."""
        self._add_stock(self.filter, 5)
        self.company.warranty_mrf_release_trigger = 'payment'
        mrf = self._mrf([(self.filter, 1), (self.gas, 2)])
        self._fulfil(mrf)
        picking = self._issue_pickings(mrf)
        action = mrf.with_user(self.helpdesk_user).action_create_parts_quotation()
        order = self.env['sale.order'].browse(action['res_id'])
        order.action_confirm()
        self.assertEqual(picking.move_ids.product_id, self.filter)
        self._validate(picking)
        gas = self._line(mrf, self.gas)
        self.assertEqual((gas.chargeable_state, gas.issue_state), ('waiting_payment', 'to_issue'))
        self.assertEqual(mrf.warranty_mrf_status, 'partially_issued')
        with self.assertRaisesRegex(UserError, 'not released'):
            self._validate(order.picking_ids)
        invoice = order._create_invoices()
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({}).action_create_payments()
        self._validate(order.picking_ids)
        self.assertEqual((gas.issued_qty, gas.issue_state, mrf.warranty_mrf_status),
                         (2, 'issued', 'issued'))
        self.assertEqual(self.env['stock.move'].search_count(
            [('product_id', '=', self.gas.id), ('state', '=', 'done'),
             ('picking_id', 'in', (picking | order.picking_ids).ids)]), 1)

    def test_09_permissions_and_company(self):
        """Issue: Requisition / Inventory users; purchasing: Requisition / Purchase users;
        locations of another company refused."""
        mrf = self._mrf([(self.valve, 2)])
        with self.assertRaises(AccessError):
            self._fulfil(mrf, user=self.helpdesk_user)
        self.stock_only.groups_id |= self.env.ref('helpdesk.group_helpdesk_user')
        with self.assertRaisesRegex(AccessError, 'Requisition / Purchase users'):
            self._fulfil(mrf, user=self.stock_only)
        other_wh = self.env['stock.warehouse'].search(
            [('company_id', '=', self.other_company.id)], limit=1) or \
            self.env['stock.warehouse'].create({'name': 'Other WH', 'code': 'OWH',
                                                'company_id': self.other_company.id})
        mrf.sudo().write({'location_id': other_wh.lot_stock_id.id})
        with self.assertRaisesRegex(UserError, 'does not belong'):
            self._fulfil(mrf)
        self.assertFalse(mrf.sudo().purchase_order_ids)

    def test_10_job_status_and_standalone(self):
        """Job material status (D15 suggestion, no automatic hold); standalone requests keep
        the vendor Create Picking and PO (full quantities by line action)."""
        job = self._confirmed_job()
        self.assertEqual(job.material_status, 'none')
        mrf = self._mrf([(self.filter, 2)], job=job)
        job.invalidate_recordset(['material_status', 'material_shortage'])
        self.assertEqual((job.material_status, job.material_shortage), ('shortage', True))
        self.assertEqual(job.state, 'confirmed', 'no automatic Awaiting Parts')
        self._add_stock(self.filter, 5)
        self.env.invalidate_all()
        self.assertEqual(job.material_status, 'to_issue')
        self._fulfil(mrf)
        self._validate(self._issue_pickings(mrf))
        job.invalidate_recordset(['material_status'])
        self.assertEqual(job.material_status, 'issued')
        standalone = self._standalone()
        standalone.write({
            'location_id': self.stock.id, 'dest_location_id': self.tech_location.id,
            'custom_picking_type_id': self.warehouse.int_type_id.id,
            'requisition_line_ids': [
                (0, 0, {'product_id': self.filter.id, 'description': 'F', 'qty': 50,
                        'uom': self.filter.uom_id.id, 'requisition_type': 'internal'}),
                (0, 0, {'product_id': self.valve.id, 'description': 'V', 'qty': 1,
                        'uom': self.valve.uom_id.id, 'requisition_type': 'purchase',
                        'partner_id': [(6, 0, self.vendor.ids)]})]})
        standalone.sudo().requisition_confirm()
        standalone.sudo().manager_approve()
        standalone.sudo().user_approve()
        standalone.sudo().request_stock()
        self.assertEqual(self._issue_pickings(standalone).move_ids.product_uom_qty, 50)
        self.assertEqual(standalone.purchase_order_ids.order_line.product_id, self.valve)

    def test_11_views_render(self):
        for user in (self.helpdesk_user, self.store, self.tech):
            views = self.Mrf.with_user(user).get_views([(False, 'form')])
            self.assertIn('issued_qty', views['views']['form']['arch'])
        views = self.env['warranty.service.job'].with_user(self.helpdesk_user).get_views(
            [(False, 'form')])
        self.assertIn('material_status', views['views']['form']['arch'])

    def test_12_non_storable_lines_on_the_form(self):
        """A covered non-storable part and a service added on the form (source location set):
        no error, Free at Source 0, line kept after save / reopen, coverage from the policy;
        a storable line keeps its free quantity."""
        parts = self.env['product.product'].create({'name': 'Parts Kit', 'type': 'consu'})
        self.policy.covered_item_ids |= self.env['warranty.coverage.item'].create(
            {'name': 'Parts Kit', 'product_id': parts.id})
        service = self.env['product.product'].create({'name': 'Site Survey', 'type': 'service'})
        self._add_stock(self.filter, 3)
        action = self._approved().with_user(self.helpdesk_user).action_create_material_request()
        form = Form(self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']))
        for product in (parts, service, self.filter):
            with form.requisition_line_ids.new() as line:
                line.product_id = product
                line.qty = 1
                self.assertEqual(line.available_qty, 3 if product == self.filter else 0.0)
        mrf = form.save()
        self.assertTrue(mrf.location_id)
        self.env.invalidate_all()
        reopened = Form(mrf.with_user(self.helpdesk_user))
        self.assertEqual(len(reopened.requisition_line_ids), 3)
        line = self._line(mrf, parts)
        self.assertEqual((line.available_qty, line.coverage_type), (0.0, 'covered'))
        self.assertEqual(self._line(mrf, self.filter).available_qty, 3)

    def test_13_non_storable_line_is_issued(self):
        """A covered non-storable line is not stock-limited: Available, and the whole quantity
        is issued as before; the storable line is issued from its stock."""
        parts = self.env['product.product'].create({'name': 'Parts Kit', 'type': 'consu'})
        self.policy.covered_item_ids |= self.env['warranty.coverage.item'].create(
            {'name': 'Parts Kit', 'product_id': parts.id})
        self._add_stock(self.filter, 5)
        mrf = self._mrf([(parts, 2), (self.filter, 1)])
        line = self._line(mrf, parts)
        self.assertEqual((line.coverage_type, line.available_qty, line.availability,
                          line.outstanding_qty), ('covered', 0.0, 'available', 2))
        self._fulfil(mrf)
        moves = self._issue_pickings(mrf).move_ids
        self.assertEqual(moves.filtered(lambda move: move.product_id == parts).product_uom_qty, 2)
        self.assertEqual(moves.filtered(lambda move: move.product_id == self.filter)
                         .product_uom_qty, 1)
        self.assertEqual((line.in_issue_qty, line.outstanding_qty), (2, 0))

    def test_90_smart_buttons_follow_linked_documents(self):
        """Internal Picking / Purchase Order only with linked documents: 0, 1 and 2 pickings,
        0 and 1 purchase order; shown to a user without Inventory / Purchase rights too."""
        self._add_stock(self.valve, 2)
        mrf = self._mrf([(self.valve, 5)], job=self._confirmed_job())
        counts = lambda: (mrf.with_user(self.helpdesk_user).warranty_picking_count,
                          mrf.with_user(self.helpdesk_user).warranty_purchase_count)
        self.assertEqual(counts(), (0, 0))
        self._fulfil(mrf)
        picking = self._issue_pickings(mrf)
        mrf.invalidate_recordset()
        self.assertEqual(counts(), (1, 1))
        self._validate(picking)
        order = mrf.sudo().purchase_order_ids
        order.button_confirm()
        self._validate(order.picking_ids)
        self._fulfil(mrf)
        mrf.invalidate_recordset()
        self.assertEqual(counts(), (2, 1), 'issue pickings only; the PO receipt is the order\'s')
        arch = self.env['material.purchase.requisition'].get_view(self.env.ref(
            'material_purchase_requisitions.material_purchase_requisition_form_view').id,
            'form')['arch']
        tree = etree.fromstring(arch)
        self.assertEqual(tree.xpath("//button[@name='show_picking']")[0].get('invisible'),
                         'not warranty_picking_count')
        self.assertEqual(tree.xpath("//button[@name='action_show_po']")[0].get('invisible'),
                         'not warranty_purchase_count')
