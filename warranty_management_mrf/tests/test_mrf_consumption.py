import base64

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from .common import WarrantyMrfCommon

SIGNATURE = base64.b64encode(b'customer signature')


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyMrfConsumption(WarrantyMrfCommon):
    """Phase 5.6 - actual consumption and unused returns (design part5_6_consumption_design.md
    rev. 2, E-1 - E-15, T6.1 - T6.13). Requests are approved by an explicit No Approval rule;
    the main technician's location is Van 1."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Part 4 completion checks other than materials as in the Part 4 tests (no checklist).
        cls.company.write({'warranty_mrf_approval_matrix': True,
                           'warranty_mrf_dest_location_id': cls.default_tech_location.id,
                           'warranty_worksheet_checklist_required': False})
        cls.env['warranty.mrf.approval.rule'].create({
            'name': 'All free (5.6 test)', 'company_id': cls.company.id, 'no_approval': True})
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
        cls.policy.covered_item_ids |= cls.env['warranty.coverage.item'].create([
            {'name': product.name, 'product_id': product.id}
            for product in (cls.filter, cls.valve, cls.sensor)])
        cls.item_gas.product_id = cls.gas
        cls.store = cls._user('mrf_c_store',
                              'material_purchase_requisitions.group_purchase_requisition_user')
        cls.store.groups_id |= cls.env.ref('stock.group_stock_user')
        cls.coordinator = cls._user('mrf_c_coordinator', 'helpdesk.group_helpdesk_user')
        cls.coordinator.groups_id |= cls.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        cls.helpdesk_user.groups_id |= cls.env.ref('sales_team.group_sale_salesman')
        cls.stock = cls.warehouse.lot_stock_id
        cls.Lot = cls.env['stock.lot']
        cls.Quant = cls.env['stock.quant']

    # ------------------------------------------------------------------ helpers
    def _add_stock(self, product, qty, location=None, lot=None):
        self.Quant._update_available_quantity(product, location or self.stock, qty, lot_id=lot)

    def _qty(self, product, location, lot=None):
        return self.Quant._get_available_quantity(product, location, lot_id=lot,
                                                  strict=bool(lot))

    def _mrf(self, lines, job=None):
        record = job or self._approved()
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

    def _validate(self, picking, user=None):
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        result = picking.with_user(user or self.store).button_validate()
        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            self.env['stock.backorder.confirmation'].with_context(result['context']) \
                .create({}).process()

    def _issued(self, lines, job=None):
        """Approved request of the job, issued to the technician location (validated)."""
        job = job or self._confirmed_job()
        mrf = self._mrf(lines, job=job)
        mrf.with_user(self.store).action_warranty_fulfil()
        for picking in self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id),
                                                         ('state', 'not in', ('done', 'cancel'))]):
            self._validate(picking)
        self.assertEqual(mrf.dest_location_id, self.tech_location)
        return mrf

    def _open_wizard(self, action, user):
        return self.env[action['res_model']].with_user(user).browse(action['res_id'])

    def _set_rows(self, wizard, values):
        """values: {product: (qty, lots)}"""
        for row in wizard.line_ids:
            qty, lots = values.get(row.product_id, (0.0, self.Lot))
            row.write({'qty': qty, 'lot_ids': [(6, 0, lots.ids)]})

    def _visit(self, job):
        return job.visit_ids.filtered(lambda task: task.state not in ('1_done', '1_canceled'))

    def _ready(self, job):
        task = self._visit(job)
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Work'}).save_timesheet()
        task.sudo().write({'worksheet_signature': SIGNATURE, 'worksheet_signed_by': 'Customer'})
        return task

    def _blockers(self, job):
        job.invalidate_recordset()
        return ' '.join(job._warranty_completion_blockers())

    # ------------------------------------------------------------------ T6.1 / T6.8 / T6.12
    def test_01_record_usage_valuation_and_reversal(self):
        """Record Used Parts by the job's technician from the visit: validated move Van 1 ->
        Warranty Consumption (valuation layer, no journal entry with manual valuation); issued
        quantity unchanged; limits (line, location stock); access; reversal with reason."""
        self._add_stock(self.filter, 10)
        mrf = self._issued([(self.filter, 3)])
        job = mrf.warranty_service_job_id
        line = self._line(mrf, self.filter)
        self.assertEqual((line.issued_qty, line.to_reconcile_qty, line.reconcile_state),
                         (3, 3, 'open'))
        task = self._visit(job)
        wizard = self._open_wizard(task.with_user(self.tech).action_warranty_record_usage(), self.tech)
        self.assertEqual((wizard.mode, wizard.line_ids.line_id, wizard.line_ids.max_qty),
                         ('use', line, 3))
        self._set_rows(wizard, {self.filter: (2.0, self.Lot)})
        wizard.action_apply()
        entry = line.warranty_consumption_ids
        location = self.company.warranty_mrf_consumption_location_id
        self.assertEqual((location.usage, location.name, location.company_id),
                         ('inventory', 'Warranty Consumption', self.company))
        self.assertEqual((entry.kind, entry.qty, entry.task_id, entry.job_id, entry.user_id),
                         ('used', 2, task, job, self.tech))
        move = entry.move_ids
        self.assertEqual((move.state, move.location_id, move.location_dest_id),
                         ('done', self.tech_location, location))
        self.assertEqual((line.issued_qty, line.used_qty, line.to_reconcile_qty,
                          line.reconcile_state), (3, 2, 1, 'open'))
        self.assertEqual(self._qty(self.filter, self.tech_location), 1)
        self.assertIn(entry, task.warranty_consumption_ids)
        self.assertIn(entry, job.warranty_consumption_ids)
        # Valuation as verified on this database: Standard Price, Manual (periodic) valuation ->
        # an outgoing valuation layer at standard price and no journal entry.
        self.assertEqual(self.filter.categ_id.property_valuation, 'manual_periodic')
        layers = move.stock_valuation_layer_ids
        self.assertEqual((len(layers), layers.quantity, layers.value), (1, -2, -1000))
        self.assertFalse(layers.account_move_id)
        self.assertFalse(self.env['account.move'].search([('stock_move_id', '=', move.id)]))
        # Limits: line quantity, stock at the technician location (no negative stock).
        with self.assertRaisesRegex(UserError, 'at most 1'):
            mrf.with_user(self.tech)._warranty_record_usage([(line, 2.0, self.Lot)])
        self._add_stock(self.filter, -1, location=self.tech_location)
        with self.assertRaisesRegex(UserError, 'negative stock is not allowed'):
            mrf.with_user(self.tech)._warranty_record_usage([(line, 1.0, self.Lot)])
        self._add_stock(self.filter, 1, location=self.tech_location)
        # Access: another technician / plain user.
        with self.assertRaises(AccessError):
            mrf.with_user(self.other_tech)._warranty_record_usage([(line, 1.0, self.Lot)])
        # Reversal: coordinator / store only, reason required.
        with self.assertRaises(AccessError):
            entry.with_user(self.tech)._warranty_reverse('Wrong')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            entry.with_user(self.coordinator)._warranty_reverse(' ')
        entry.with_user(self.coordinator)._warranty_reverse('Recorded on the wrong job')
        self.assertEqual((entry.state, entry.reversed_by_id, entry.reverse_reason),
                         ('reversed', self.coordinator, 'Recorded on the wrong job'))
        reverse = entry.move_ids - move
        self.assertEqual((reverse.state, reverse.location_dest_id), ('done', self.tech_location))
        self.assertEqual(reverse.stock_valuation_layer_ids.value, 1000)
        self.assertEqual((line.used_qty, line.to_reconcile_qty), (0, 3))
        self.assertEqual(self._qty(self.filter, self.tech_location), 3)
        with self.assertRaisesRegex(UserError, 'not reversed yet'):
            entry.with_user(self.coordinator)._warranty_reverse('Again')
        self.assertTrue(any('reversed by' in (message.body or '') for message in mrf.message_ids))

    # ------------------------------------------------------------------ T6.3 / T6.4
    def test_02_return_unused_store_validation_and_status(self):
        """Return Unused: one transfer Van 1 -> WH/Stock linked to request / case / job; no
        duplicate; Return Pending does not block; only the store validates, not above the
        recorded quantity; Returned -> Closed; a cancelled return reopens the line."""
        self._add_stock(self.filter, 10)
        mrf = self._issued([(self.filter, 3)])
        job = mrf.warranty_service_job_id
        line = self._line(mrf, self.filter)
        mrf.with_user(self.tech)._warranty_record_usage([(line, 1.0, self.Lot)])
        wizard = self._open_wizard(mrf.with_user(self.tech).action_warranty_return_unused(), self.tech)
        self.assertEqual((wizard.line_ids.qty, wizard.line_ids.max_qty), (2, 2))
        wizard.note = 'Not needed'
        wizard.action_apply()
        entry = line.warranty_consumption_ids.filtered(lambda e: e.kind == 'unused_return')
        picking = entry.picking_id
        self.assertEqual((picking.location_id, picking.location_dest_id, picking.state,
                          picking.warranty_unused_return),
                         (self.tech_location, self.stock, 'assigned', True))
        self.assertEqual((picking.warranty_mrf_id, picking.warranty_mrf_case_id,
                          picking.warranty_mrf_job_id), (mrf, mrf.warranty_case_id, job))
        self.assertEqual((line.in_return_qty, line.to_reconcile_qty, line.reconcile_state),
                         (2, 0, 'return_pending'))
        self.assertEqual(mrf.warranty_mrf_status, 'returned')
        self.assertNotIn(mrf.name, self._blockers(job))
        self.assertEqual(mrf.warranty_return_picking_count, 1)
        with self.assertRaisesRegex(UserError, 'at most 0'):
            mrf.with_user(self.tech)._warranty_return_unused([(line, 1.0, self.Lot)])
        with self.assertRaises(AccessError):
            picking.with_user(self.tech).button_validate()
        picking.move_ids.quantity = 3
        picking.move_ids.picked = True
        with self.assertRaisesRegex(UserError, 'cannot exceed'):
            picking.with_user(self.store).button_validate()
        self._validate(picking)
        self.assertEqual((line.returned_qty, line.in_return_qty, line.reconcile_state,
                          line.issued_qty), (2, 0, 'reconciled', 3))
        self.assertEqual(mrf.warranty_mrf_status, 'reconciled')
        self.assertEqual(self._qty(self.filter, self.tech_location), 0)
        # A cancelled return is no longer counted: the line is open again and blocks.
        other = self._issued([(self.filter, 2)])
        other_line = self._line(other, self.filter)
        picking = other.with_user(self.store)._warranty_return_unused([(other_line, 2.0, self.Lot)])
        self.assertEqual(other_line.reconcile_state, 'return_pending')
        picking.action_cancel()
        self.assertEqual((other_line.in_return_qty, other_line.to_reconcile_qty,
                          other_line.reconcile_state), (0, 2, 'open'))
        self.assertIn('issued but not recorded', self._blockers(other.warranty_service_job_id))
        self.assertEqual(other.warranty_mrf_status, 'issued')

    # ------------------------------------------------------------------ T6.2 / T6.6
    def test_03_serials_and_full_consumption(self):
        """Serial numbers: only issued serials of the line, one per unit; Confirm Full
        Consumption needs the confirmation and uses the remaining serials; reconciled ->
        Closed."""
        s1, s2, s3 = (self.Lot.create({'name': name, 'product_id': self.sensor.id})
                      for name in ('SN-1', 'SN-2', 'SN-3'))
        for lot in (s1, s2):
            self._add_stock(self.sensor, 1, lot=lot)
        self._add_stock(self.sensor, 1, location=self.tech_location, lot=s3)
        self._add_stock(self.filter, 5)
        mrf = self._issued([(self.sensor, 2), (self.filter, 1)])
        line = self._line(mrf, self.sensor)
        self.assertEqual(set(line._warranty_lot_balance()), {s1, s2})
        with self.assertRaisesRegex(UserError, 'select the serial'):
            mrf.with_user(self.tech)._warranty_record_usage([(line, 1.0, self.Lot)])
        with self.assertRaisesRegex(UserError, 'one serial number per unit'):
            mrf.with_user(self.tech)._warranty_record_usage([(line, 2.0, s1)])
        with self.assertRaisesRegex(UserError, 'was not issued'):
            mrf.with_user(self.tech)._warranty_record_usage([(line, 1.0, s3)])
        mrf.with_user(self.tech)._warranty_record_usage([(line, 1.0, s1)])
        self.assertEqual(set(line._warranty_lot_balance()), {s2})
        with self.assertRaisesRegex(UserError, 'was not issued'):
            mrf.with_user(self.tech)._warranty_record_usage([(line, 1.0, s1)])
        wizard = self._open_wizard(mrf.with_user(self.tech).action_warranty_full_consumption(),
                              self.tech)
        self.assertEqual(wizard.mode, 'full')
        self.assertEqual(wizard.line_ids.filtered(lambda r: r.product_id == self.sensor).lot_ids,
                         s2)
        with self.assertRaisesRegex(UserError, 'confirmation'):
            wizard.action_apply()
        wizard.confirm_full = True
        wizard.action_apply()
        self.assertEqual(line.warranty_consumption_ids.filtered(
            lambda e: e.state == 'done').lot_ids, s1 | s2)
        self.assertEqual(mrf.requisition_line_ids.mapped('reconcile_state'),
                         ['reconciled', 'reconciled'])
        self.assertEqual(mrf.warranty_mrf_status, 'reconciled')
        self.assertEqual(self._qty(self.sensor, self.tech_location, s3), 1, 'other serial kept')
        self.assertFalse(mrf.can_warranty_record_usage)

    # ------------------------------------------------------------------ T6.10
    def test_04_customer_paid_installation_keep_and_return(self):
        """Not Covered parts: delivery and installation are separate; Installed (no stock move),
        Customer Keeps (commercial user, reason), Customer Return (standard return of the
        delivery, store validation, quotation quantities updated); reconciled -> Closed."""
        job = self._confirmed_job()
        mrf = self._mrf([(self.gas, 4)], job=job)
        line = self._line(mrf, self.gas)
        self.assertIn('To Quote', self._blockers(job))
        order = self.env['sale.order'].browse(
            mrf.with_user(self.helpdesk_user).action_create_parts_quotation()['res_id'])
        order.action_confirm()
        self.assertIn('not delivered', self._blockers(job))
        self._validate(order.picking_ids)
        self.assertEqual((line.issued_qty, line.to_reconcile_qty, line.reconcile_state),
                         (4, 4, 'open'))
        self.assertIn('delivered but not recorded as installed', self._blockers(job))
        moves_before = self.env['stock.move'].search_count([])
        mrf.with_user(self.tech)._warranty_record_usage([(line, 2.0, self.Lot)])
        self.assertEqual(self.env['stock.move'].search_count([]), moves_before,
                         'installation creates no second stock movement')
        entry = line.warranty_consumption_ids
        self.assertEqual((entry.kind, line.used_qty, line.to_reconcile_qty), ('installed', 2, 2))
        with self.assertRaisesRegex(UserError, 'parts issued to the technician'):
            mrf.with_user(self.tech)._warranty_return_unused([(line, 1.0, self.Lot)])
        with self.assertRaises(AccessError):
            mrf.with_user(self.tech)._warranty_customer_keep([(line, 1.0, self.Lot)], 'Spare')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            mrf.with_user(self.helpdesk_user)._warranty_customer_keep([(line, 1.0, self.Lot)], '')
        mrf.with_user(self.helpdesk_user)._warranty_customer_keep(
            [(line, 1.0, self.Lot)], 'Customer keeps a spare bottle')
        self.assertEqual((line.kept_qty, line.to_reconcile_qty), (1, 1))
        returns = mrf.with_user(self.helpdesk_user)._warranty_customer_return(
            [(line, 1.0, self.Lot)], 'Not needed, refund')
        self.assertEqual((returns.warranty_customer_return, returns.location_dest_id.usage,
                          returns.warranty_mrf_id), (True, 'internal', mrf))
        self.assertEqual((line.in_return_qty, line.to_reconcile_qty, line.reconcile_state),
                         (1, 0, 'return_pending'))
        self.assertNotIn(mrf.name, self._blockers(job))
        with self.assertRaises(AccessError):
            returns.with_user(self.tech).button_validate()
        self._validate(returns)
        sale_line = order.order_line.filtered(lambda sol: sol.warranty_mrf_line_id == line)
        self.assertEqual((sale_line.qty_delivered, line.issued_qty, line.returned_qty,
                          line.to_reconcile_qty, line.reconcile_state),
                         (3, 3, 1, 0, 'reconciled'))
        self.assertEqual((line.outstanding_qty, line.issue_state), (0, 'issued'))
        self.assertEqual(self._blockers(job), '')
        self.assertEqual(mrf.warranty_mrf_status, 'reconciled')

    # ------------------------------------------------------------------ T6.7
    def test_05_cancel_remaining(self):
        """Cancel Remaining: authorised users, reason, never quantities on open transfers or
        purchase orders; approval history kept; the line can then be completed."""
        self._add_stock(self.valve, 2)
        job = self._confirmed_job()
        mrf = self._mrf([(self.valve, 5)], job=job)
        mrf.with_user(self.store).action_warranty_fulfil()
        line = self._line(mrf, self.valve)
        approvals = len(mrf.sudo().warranty_approval_ids)
        self.assertEqual((line.in_issue_qty, line.purchased_qty, line._warranty_cancellable_qty()),
                         (2, 3, 0))
        self.assertFalse(mrf.with_user(self.store).can_warranty_cancel_remaining)
        with self.assertRaisesRegex(UserError, 'only 0'):
            mrf.with_user(self.store)._warranty_cancel_remaining([(line, 1.0, self.Lot)], 'No')
        mrf.sudo().purchase_order_ids.button_cancel()
        self.assertEqual(line._warranty_cancellable_qty(), 3)
        with self.assertRaises(AccessError):
            mrf.with_user(self.tech)._warranty_cancel_remaining([(line, 1.0, self.Lot)], 'x')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            mrf.with_user(self.store)._warranty_cancel_remaining([(line, 1.0, self.Lot)], ' ')
        with self.assertRaisesRegex(UserError, 'only 3'):
            mrf.with_user(self.store)._warranty_cancel_remaining([(line, 4.0, self.Lot)], 'x')
        wizard = self._open_wizard(mrf.with_user(self.helpdesk_user).action_warranty_cancel_remaining(),
                              self.helpdesk_user)
        self._set_rows(wizard, {self.valve: (3.0, self.Lot)})
        with self.assertRaisesRegex(UserError, 'reason is required'):
            wizard.action_apply()
        wizard.note = 'Customer replaced the unit, valves no longer needed'
        wizard.action_apply()
        entry = line.warranty_consumption_ids
        self.assertEqual((entry.kind, entry.qty, entry.user_id, entry.note[:8]),
                         ('cancelled', 3, self.helpdesk_user, 'Customer'))
        self.assertEqual((line.cancelled_qty, line.outstanding_qty), (3, 0))
        self.assertEqual(len(mrf.sudo().warranty_approval_ids), approvals)
        self.assertIn('Remaining quantity cancelled', mrf.message_ids[0].body)
        self._validate(self.env['stock.picking'].search(
            [('custom_requisition_id', '=', mrf.id), ('state', 'not in', ('done', 'cancel'))]))
        self.assertEqual((line.issued_qty, line.issue_state, mrf.warranty_mrf_status),
                         (2, 'issued', 'issued'))
        mrf.with_user(self.tech)._warranty_confirm_full_consumption()
        self.assertEqual(mrf.warranty_mrf_status, 'reconciled')
        self.assertEqual(self._blockers(job), '')

    # ------------------------------------------------------------------ T6.5 / E-13b
    def test_06_completion_blocker(self):
        """Complete Visit / Batch Complete are blocked by Draft / waiting / unreconciled
        requests of the job and allowed after reconciliation; Incomplete / Reschedule is never
        blocked; Draft requests are cancelled with a reason by the requester, creator or a
        Service Coordinator."""
        self._add_stock(self.filter, 10)
        job = self._confirmed_job()
        draft_action = job.with_user(self.helpdesk_user).action_create_material_request()
        draft = self.Mrf.with_user(self.helpdesk_user).with_context(**draft_action['context']) \
            .create({'requisition_line_ids': [(0, 0, {
                'product_id': self.filter.id, 'description': 'Filter', 'qty': 1,
                'uom': self.filter.uom_id.id})]})
        mrf = self._issued([(self.filter, 2)], job=job)
        blockers = self._blockers(job)
        self.assertIn('%s: not submitted' % draft.name, blockers)
        self.assertIn('%s: Air Filter: 2 Units issued but not recorded' % mrf.name, blockers)
        task = self._ready(job)
        with self.assertRaisesRegex(UserError, 'not submitted'):
            task.with_user(self.tech).action_warranty_complete_visit()
        problems = job.with_user(self.helpdesk_user)._warranty_batch_problems()
        self.assertTrue(any(mrf.name in problem for problem in problems))
        # E-13b: Cancel needs a reason; requester, creator or Service Coordinator.
        action = draft.with_user(self.helpdesk_user).action_cancel()
        self.assertEqual((action['res_model'], draft.state), ('warranty.mrf.cancel.wizard', 'draft'))
        with self.assertRaises(AccessError):
            draft.with_user(self.tech).action_cancel()
        with self.assertRaises(AccessError):
            draft.with_user(self.store).with_context(warranty_cancel_reason='x').action_cancel()
        wizard = self.env['warranty.mrf.cancel.wizard'].with_user(self.coordinator).create(
            {'requisition_id': draft.id, 'reason': 'Duplicate request'})
        wizard.action_cancel()
        self.assertEqual(draft.state, 'cancel')
        self.assertIn('Duplicate request', draft.message_ids[0].body)
        self.assertNotIn(draft.name, self._blockers(job))
        with self.assertRaisesRegex(UserError, 'issued but not recorded'):
            task.with_user(self.tech).action_warranty_complete_visit()
        mrf.with_user(self.tech)._warranty_record_usage([(self._line(mrf, self.filter), 2.0,
                                                          self.Lot)], task=task)
        self.assertEqual(self._blockers(job), '')
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(job.state, 'completed')
        with self.assertRaisesRegex(UserError, 'closed'):
            mrf.with_user(self.coordinator)._warranty_record_usage(
                [(self._line(mrf, self.filter), 1.0, self.Lot)])
        # Incomplete / Reschedule with open materials stays possible.
        other = self._issued([(self.filter, 1)])
        other_job = other.warranty_service_job_id
        other_task = self._visit(other_job)
        self.assertIn('issued but not recorded', self._blockers(other_job))
        other_job.with_user(self.tech)._warranty_visit_not_completed(
            other_task, 'awaiting_parts', 'Waiting for parts', 'reschedule')
        self.assertEqual(other_job.state, 'incomplete')

    # ------------------------------------------------------------------ T6.11
    def test_07_fsm_products_blocked_on_warranty_visits_only(self):
        """E-15: no Field Service Products on warranty visits (button hidden, server refused);
        ordinary Field Service tasks unchanged."""
        job = self._confirmed_job()
        task = self._visit(job)
        with self.assertRaisesRegex(UserError, 'Material Requests'):
            task.with_user(self.tech).action_fsm_view_material()
        with self.assertRaisesRegex(UserError, 'Material Requests'):
            self.filter.with_user(self.tech).with_context(fsm_task_id=task.id).set_fsm_quantity(1)
        arch = self.env['project.task'].with_user(self.tech).get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertIn('warranty_service_job_id', arch)
        plain = self.env['project.task'].create({
            'name': 'Ordinary repair', 'project_id': task.project_id.id,
            'partner_id': self.customer.id})
        self.assertFalse(plain.warranty_service_job_id)
        self.assertEqual(plain.action_fsm_view_material()['type'], 'ir.actions.act_window')

    # ------------------------------------------------------------------ legacy (pre-matrix)
    def _legacy(self, job, lines, state='stock'):
        """A warranty request processed by the Requisition workflow before the approval matrix
        (no approval round): New request, status written as the earlier workflow left it."""
        action = job.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {
                'product_id': product.id, 'description': product.name, 'qty': qty,
                'uom': product.uom_id.id}) for product, qty in lines]})
        mrf.sudo().write({'state': state})
        self.assertTrue(mrf.warranty_approval_legacy)
        self.assertFalse(mrf.approval_round)
        return mrf

    def _legacy_picking(self, mrf, moves, validate=True):
        """Issue transfer of the earlier workflow (moves linked to the request lines as the
        vendor does), created before the release guard existed."""
        picking = self.env['stock.picking'].create({
            'location_id': mrf.location_id.id, 'location_dest_id': mrf.dest_location_id.id,
            'picking_type_id': mrf.custom_picking_type_id.id, 'origin': mrf.name})
        for product, qty, lots in moves:
            move = self.env['stock.move'].create({
                'name': product.name, 'product_id': product.id, 'product_uom_qty': qty,
                'product_uom': product.uom_id.id, 'picking_id': picking.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id})
            if lots:
                picking.action_confirm()
                move.move_line_ids.unlink()
                for lot in lots:
                    self.env['stock.move.line'].create({
                        'move_id': move.id, 'picking_id': picking.id, 'product_id': product.id,
                        'product_uom_id': product.uom_id.id, 'quantity': 1, 'lot_id': lot.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id})
        picking.action_confirm()
        picking.action_assign()
        if validate:
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.button_validate()
        # Links written as by the vendor Create Picking and PO of the earlier workflow.
        self.env.flush_all()
        for move in picking.move_ids:
            line = self._line(mrf, move.product_id)
            self.env.cr.execute("UPDATE stock_move SET custom_requisition_line_id = %s "
                                "WHERE id = %s", (line.id, move.id))
        self.env.cr.execute("UPDATE stock_picking SET custom_requisition_id = %s WHERE id = %s",
                            (mrf.id, picking.id))
        self.env.invalidate_all()
        mrf.requisition_line_ids.modified(['warranty_move_ids'])
        picking.modified(['custom_requisition_id'])
        return picking

    def test_09_legacy_requests(self):
        """Pre-matrix requests (MRF/000003 case): issued quantities come from the validated moves
        only (Received does not mean fully issued); usage, unused return and reversal with the
        normal limits, serials, access and reasons; never approved or issued again; the job can
        be completed once they are reconciled. A pre-matrix request without issue keeps the
        withdraw rule."""
        s1, s2 = (self.Lot.create({'name': name, 'product_id': self.sensor.id})
                  for name in ('LG-1', 'LG-2'))
        self._add_stock(self.filter, 10)
        for lot in (s1, s2):
            self._add_stock(self.sensor, 1, lot=lot)
        job = self._confirmed_job()
        mrf = self._legacy(job, [(self.filter, 3), (self.sensor, 2)])
        done = self._legacy_picking(mrf, [(self.filter, 2, None), (self.sensor, 1, s1)])
        open_picking = self._legacy_picking(mrf, [(self.filter, 1, None)], validate=False)
        mrf.sudo().write({'state': 'receive'})
        filter_line, sensor_line = self._line(mrf, self.filter), self._line(mrf, self.sensor)
        self.assertEqual((done.state, open_picking.state), ('done', 'assigned'))
        self.assertEqual((filter_line.issued_qty, filter_line.in_issue_qty, filter_line.approved_qty,
                          filter_line.outstanding_qty, filter_line.to_reconcile_qty),
                         (2, 1, 0, 0, 2))
        self.assertEqual((sensor_line.issued_qty, sensor_line.to_reconcile_qty), (1, 1))
        blockers = self._blockers(job)
        self.assertIn('earlier workflow that is not validated', blockers)
        self.assertIn('Air Filter: 2 Units issued but not recorded', blockers)
        self.assertNotIn('withdraw', blockers)
        # Never approved or issued again; the open transfer of the earlier workflow cannot be
        # validated (it is cancelled instead).
        for method in ('request_stock', 'action_warranty_fulfil', 'user_approve',
                       'manager_approve'):
            with self.assertRaises(UserError):
                getattr(mrf.with_user(self.store), method)()
        with self.assertRaisesRegex(UserError, 'not approved through the warranty'):
            open_picking.with_user(self.store).button_validate()
        open_picking.action_cancel()
        self.assertEqual(filter_line.in_issue_qty, 0)
        # Usage limited to the validated moves; serials only those issued for the line.
        self.assertTrue(mrf.with_user(self.tech).can_warranty_record_usage)
        with self.assertRaisesRegex(UserError, 'at most 2'):
            mrf.with_user(self.tech)._warranty_record_usage([(filter_line, 3.0, self.Lot)])
        with self.assertRaisesRegex(UserError, 'was not issued'):
            mrf.with_user(self.tech)._warranty_record_usage([(sensor_line, 1.0, s2)])
        with self.assertRaises(AccessError):
            mrf.with_user(self.other_tech)._warranty_record_usage([(filter_line, 1.0, self.Lot)])
        mrf.with_user(self.tech)._warranty_record_usage(
            [(filter_line, 1.0, self.Lot), (sensor_line, 1.0, s1)])
        entry = sensor_line.warranty_consumption_ids
        self.assertEqual((entry.move_ids.state, entry.move_ids.location_dest_id),
                         ('done', self.company.warranty_mrf_consumption_location_id))
        # Duplicate prevention: only the remaining quantity can be returned.
        with self.assertRaisesRegex(UserError, 'at most 1'):
            mrf.with_user(self.tech)._warranty_return_unused([(filter_line, 2.0, self.Lot)])
        returned = mrf.with_user(self.tech)._warranty_return_unused([(filter_line, 1.0, self.Lot)])
        self.assertEqual((returned.custom_requisition_id, returned.warranty_unused_return,
                          returned.warranty_mrf_job_id), (mrf, True, job))
        with self.assertRaisesRegex(UserError, 'at most 0'):
            mrf.with_user(self.tech)._warranty_return_unused([(filter_line, 1.0, self.Lot)])
        with self.assertRaises(AccessError):
            returned.with_user(self.tech).button_validate()
        self._validate(returned)
        self.assertEqual((filter_line.returned_qty, filter_line.reconcile_state),
                         (1, 'reconciled'))
        # Reversal: authorised users, mandatory reason; the line is open again.
        with self.assertRaises(AccessError):
            entry.with_user(self.tech)._warranty_reverse('Wrong')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            entry.with_user(self.coordinator)._warranty_reverse('')
        entry.with_user(self.coordinator)._warranty_reverse('Wrong serial recorded')
        self.assertEqual((sensor_line.to_reconcile_qty, self._qty(self.sensor, self.tech_location,
                                                                  s1)), (1, 1))
        self.assertIn('Temperature Sensor: 1 Units issued but not recorded', self._blockers(job))
        mrf.with_user(self.tech)._warranty_record_usage([(sensor_line, 1.0, s1)])
        # Reconciled: no blocker, status Closed; history and status of the request unchanged.
        self.assertEqual(self._blockers(job), '')
        self.assertEqual((mrf.state, mrf.approval_round, mrf.warranty_approval_ids,
                          mrf.warranty_mrf_status),
                         ('receive', 0, self.env['warranty.mrf.approval'], 'reconciled'))
        self.assertTrue(mrf.warranty_approval_legacy)
        # A pre-matrix request that never issued anything keeps the withdraw rule.
        other_job = self._confirmed_job()
        approved = self._legacy(other_job, [(self.filter, 1)], state='approve')
        self.assertIn('withdraw it and submit it again', self._blockers(other_job))
        with self.assertRaisesRegex(UserError, 'approved warranty Material Requests only'):
            approved.with_user(self.tech)._warranty_record_usage(
                [(self._line(approved, self.filter), 1.0, self.Lot)])

    # ------------------------------------------------------------------ T6.9 / T6.13
    def test_08_access_views_and_standalone(self):
        """Wizards and tabs for technicians, coordinators and the store; other technicians are
        refused; standalone requests unchanged (no material actions, vendor Cancel)."""
        self._add_stock(self.filter, 5)
        mrf = self._issued([(self.filter, 1)])
        job = mrf.warranty_service_job_id
        with self.assertRaises(AccessError):
            job.with_user(self.other_tech).action_warranty_record_usage()
        for user in (self.tech, self.helpdesk_user, self.store, self.coordinator):
            self.assertTrue(job.with_user(user).warranty_material_line_ids, user.login)
            views = self.env['warranty.service.job'].with_user(user).get_views([(False, 'form')])
            self.assertIn('warranty_material_line_ids', views['views']['form']['arch'])
            for model in ('warranty.mrf.material.wizard', 'warranty.mrf.reverse.wizard',
                          'warranty.mrf.cancel.wizard', 'warranty.mrf.consumption'):
                self.env[model].with_user(user).get_views([(False, 'form')])
        self.assertTrue(job.with_user(self.tech).can_warranty_record_usage)
        self.assertFalse(job.with_user(self.other_tech).can_warranty_record_usage)
        self.assertTrue(mrf.with_user(self.store).can_warranty_record_usage)
        settings = self.env['res.config.settings'].get_views([(False, 'form')])
        self.assertIn('warranty_mrf_consumption_location_id', settings['views']['form']['arch'])
        standalone = self._standalone()
        with self.assertRaisesRegex(UserError, 'warranty Material Requests'):
            standalone._warranty_check_material_open()
        self.assertFalse(standalone.can_warranty_record_usage)
        standalone.with_user(self.helpdesk_user).action_cancel()
        self.assertEqual(standalone.state, 'cancel')
        # Helpdesk users without Inventory rights open the job (Form loads the usage views)
        # and read entries with transfers / serials.
        mrf.with_user(self.tech)._warranty_return_unused([(self._line(mrf, self.filter), 1.0,
                                                           self.Lot)])
        Form(job.with_user(self.helpdesk_user))
        self.assertFalse(self.helpdesk_user.has_group('stock.group_stock_user'))
        refs = job.with_user(self.helpdesk_user).warranty_consumption_ids.read(
            ['transfer_ref', 'lot_names', 'kind'])
        self.assertIn('WH/', refs[0]['transfer_ref'])

    def test_90_confirm_material_usage_screen(self):
        """Confirm Material Usage: several products, partial use, limits; unused is not returned
        until the transfer is validated; Return Unused and Close follow the real quantities."""
        self._add_stock(self.filter, 10)
        self._add_stock(self.valve, 10)
        mrf = self._issued([(self.filter, 3), (self.valve, 2)])
        filter_line, valve_line = self._line(mrf, self.filter), self._line(mrf, self.valve)
        mine = mrf.with_user(self.tech)
        self.assertTrue(mine.can_warranty_return_unused)
        self.assertFalse(mine.can_warranty_vendor_claim, 'nothing used yet: nothing to claim')
        self.assertFalse(mrf.with_user(self.coordinator).can_warranty_close, 'not accounted for')
        action = mine.action_warranty_record_usage()
        self.assertEqual(action['name'], 'Confirm Material Usage')
        self.assertEqual(action['views'][0][0], self.env.ref(
            'warranty_management_mrf.warranty_mrf_usage_wizard_view_form').id)
        wizard = self._open_wizard(action, self.tech)
        self._set_rows(wizard, {self.filter: (5.0, self.Lot)})
        with self.assertRaisesRegex(UserError, 'at most'):
            wizard.action_apply()
        self._set_rows(wizard, {self.filter: (-1.0, self.Lot)})
        with self.assertRaisesRegex(UserError, 'positive'):
            wizard.action_apply()
        self._set_rows(wizard, {self.filter: (2.0, self.Lot), self.valve: (2.0, self.Lot)})
        rows = wizard.line_ids.sorted(lambda row: row.product_id != self.filter)
        self.assertEqual(rows.mapped('left_unused_qty'), [1, 0])
        self.assertEqual(rows.mapped('requested_qty'), [3, 2])
        wizard.action_apply()
        self.assertEqual((filter_line.used_qty, filter_line.warranty_unused_qty,
                          filter_line.returned_qty, filter_line.to_reconcile_qty), (2, 1, 0, 1))
        self.assertEqual((valve_line.used_qty, valve_line.warranty_unused_qty,
                          valve_line.to_reconcile_qty), (2, 0, 0))
        self.env.invalidate_all()
        self.assertTrue(mine.can_warranty_return_unused)
        picking = mine._warranty_return_unused([(filter_line, 1.0, self.Lot)])
        self.assertEqual((filter_line.returned_qty, filter_line.in_return_qty,
                          filter_line.to_reconcile_qty), (0, 1, 0))
        self.env.invalidate_all()
        self.assertFalse(mine.can_warranty_return_unused, 'nothing left to return')
        self.assertFalse(mrf.with_user(self.coordinator).can_warranty_close, 'return not validated')
        self._validate(picking)
        self.assertEqual((filter_line.returned_qty, filter_line.in_return_qty,
                          filter_line.warranty_unused_qty), (1, 0, 1))
        self.env.invalidate_all()
        self.assertFalse(mrf.with_user(self.coordinator).warranty_material_issues)
        self.assertEqual((mrf.warranty_close_problems, mrf.with_user(self.coordinator).can_warranty_close),
                         (False, True))

    def test_91_usage_shortcut_and_header_buttons(self):
        """All Parts Were Used opens the existing confirmation; one primary action on the form;
        serials stay required."""
        self._add_stock(self.filter, 2)
        mrf = self._issued([(self.filter, 2)])
        wizard = self._open_wizard(mrf.with_user(self.tech).action_warranty_record_usage(), self.tech)
        full = self._open_wizard(wizard.action_all_used(), self.tech)
        self.assertEqual(full.mode, 'full')
        with self.assertRaisesRegex(UserError, 'Tick the confirmation'):
            full.action_apply()
        full.confirm_full = True
        full.action_apply()
        self.assertEqual(self._line(mrf, self.filter).used_qty, 2)
        arch = self.env['material.purchase.requisition'].get_view(self.env.ref(
            'material_purchase_requisitions.material_purchase_requisition_form_view').id,
            'form')['arch']
        self.assertIn('string="Confirm Material Usage"', arch)
        self.assertNotIn('Record Used Parts', arch)
        self.assertNotIn('name="action_warranty_full_consumption"', arch)
        self.assertIn('invisible="not can_warranty_close', arch)
        self.assertIn('invisible="not can_warranty_vendor_claim', arch)
