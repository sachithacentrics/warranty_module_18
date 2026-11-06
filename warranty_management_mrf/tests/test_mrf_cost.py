from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import WarrantyMrfCommon

COST_FIELDS = ['approved_cost', 'actual_cost', 'actual_unverified_cost', 'billed_amount']


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyMrfCost(WarrantyMrfCommon):
    """Phase 5.7 - estimated, approved and actual material cost (design part5_7_cost_design.md
    rev. 1, H-1 - H-12, T7.1 - T7.10). Requests are approved by an explicit No Approval rule
    (matrix) unless stated; the main technician's location is Van 1; valuation is Manual."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({'warranty_mrf_approval_matrix': True,
                           'warranty_mrf_dest_location_id': cls.default_tech_location.id,
                           'warranty_worksheet_checklist_required': False})
        cls.env['warranty.mrf.approval.rule'].create({
            'name': 'All free (5.7 test)', 'company_id': cls.company.id, 'no_approval': True})
        Product = cls.env['product.product']
        Category = cls.env['product.category']
        cls.cat_fifo = Category.create({'name': 'Spare Parts FIFO', 'property_cost_method': 'fifo',
                                        'property_valuation': 'manual_periodic'})
        cls.cat_avco = Category.create({'name': 'Spare Parts AVCO',
                                        'property_cost_method': 'average',
                                        'property_valuation': 'manual_periodic'})
        cls.filter = Product.create({'name': 'Air Filter', 'is_storable': True, 'type': 'consu',
                                     'standard_price': 500})
        cls.vendor = cls.env['res.partner'].create({'name': 'Cool Parts Ltd', 'is_company': True})
        cls.valve = Product.create({'name': 'Expansion Valve', 'is_storable': True,
                                    'type': 'consu', 'standard_price': 2000,
                                    'seller_ids': [(0, 0, {'partner_id': cls.vendor.id,
                                                           'price': 1800})]})
        cls.motor = Product.create({'name': 'Fan Motor', 'is_storable': True, 'type': 'consu',
                                    'categ_id': cls.cat_fifo.id, 'standard_price': 100})
        cls.coil = Product.create({'name': 'Coil', 'is_storable': True, 'type': 'consu',
                                   'categ_id': cls.cat_avco.id, 'standard_price': 100})
        cls.oil = Product.create({'name': 'Compressor Oil', 'is_storable': True, 'type': 'consu',
                                  'standard_price': 1000, 'list_price': 4000,
                                  'invoice_policy': 'delivery', 'taxes_id': [(5, 0, 0)]})
        cls.policy.covered_item_ids |= cls.env['warranty.coverage.item'].create([
            {'name': product.name, 'product_id': product.id}
            for product in (cls.filter, cls.valve, cls.motor, cls.coil)])
        cls.item_gas.product_id = cls.oil
        cls.store = cls._user('mrf_k_store',
                              'material_purchase_requisitions.group_purchase_requisition_user')
        cls.store.groups_id |= cls.env.ref('stock.group_stock_user')
        cls.coordinator = cls._user('mrf_k_coordinator', 'helpdesk.group_helpdesk_user')
        cls.coordinator.groups_id |= cls.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        cls.accountant = cls._user('mrf_k_accountant', 'account.group_account_invoice')
        cls.helpdesk_user.groups_id |= cls.env.ref('sales_team.group_sale_salesman')
        cls.stock = cls.warehouse.lot_stock_id
        cls.Lot = cls.env['stock.lot']
        cls.Report = cls.env['warranty.mrf.cost.report']

    # ------------------------------------------------------------------ helpers
    def _receive(self, product, qty, price):
        """Vendor receipt with a price (valuation layer at that cost for FIFO / AVCO)."""
        move = self.env['stock.move'].create({
            'name': 'Receipt %s' % product.name, 'product_id': product.id,
            'product_uom': product.uom_id.id, 'product_uom_qty': qty, 'price_unit': price,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock.id, 'company_id': self.company.id})
        move._action_confirm()
        move.quantity = qty
        move.picked = True
        move._action_done()
        self.assertEqual(move.state, 'done')
        return move

    def _mrf(self, lines, job=None, approve=True):
        record = job or self._confirmed_job()
        action = record.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {
                'product_id': product.id, 'description': product.name, 'qty': qty,
                'uom': product.uom_id.id}) for product, qty in lines]})
        if approve:
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

    def _issue(self, mrf):
        mrf.with_user(self.store).action_warranty_fulfil()
        for picking in self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id),
                                                         ('state', 'not in', ('done', 'cancel'))]):
            self._validate(picking)
        return mrf

    def _use(self, mrf, product, qty):
        mrf.with_user(self.tech)._warranty_record_usage([(self._line(mrf, product), qty, self.Lot)])
        return self._line(mrf, product).warranty_consumption_ids.filtered(
            lambda entry: entry.kind == 'used' and entry.state == 'done')[:1]

    def _report(self, mrf, user=None):
        return self.Report.with_user(user or self.coordinator).search(
            [('requisition_id', '=', mrf.id)])

    # ------------------------------------------------------------------ T7.1 / T7.7 / T7.8
    def test_01_estimated_approved_actual_and_no_journal_entries(self):
        """Estimated (5.1), approved snapshot at final approval (= header Approved Amount),
        actual from the consumption layers; later product cost changes change neither the
        snapshot nor the actual cost; no journal entry; valuation settings unchanged."""
        moves_before = self.env['account.move'].search_count([])
        self._receive(self.filter, 10, 500)
        self._receive(self.valve, 5, 2000)
        job = self._confirmed_job()
        mrf = self._issue(self._mrf([(self.filter, 3), (self.valve, 1)], job=job))
        f_line, v_line = self._line(mrf, self.filter), self._line(mrf, self.valve)
        self.assertEqual((f_line.estimated_cost, v_line.estimated_cost), (1500, 2000))
        self.assertEqual((f_line.approved_cost, f_line.approved_unit_cost,
                          f_line.approved_cost_state), (1500, 500, 'recorded'))
        self.assertEqual(f_line.approved_cost + v_line.approved_cost, mrf.approved_amount)
        # Issue (internal) is no cost.
        self.assertEqual((f_line.actual_cost, f_line.cost_status), (0, 'none'))
        self._use(mrf, self.filter, 2)
        self.assertEqual((f_line.actual_cost, f_line.actual_unverified_cost, f_line.cost_status,
                          f_line.cost_bucket), (1000, 0, 'verified', 'covered'))
        self.filter.standard_price = 800
        f_line.invalidate_recordset()
        self.assertEqual((f_line.approved_cost, f_line.actual_cost), (1500, 1000))
        self.assertEqual(f_line.cost_variance, 1000 - 1500)
        # Job and case totals (Warranty Material Cost = Covered + Goodwill, verified).
        case = mrf.warranty_case_id
        for record in (mrf, job, case):
            record.invalidate_recordset()
            self.assertEqual((record.warranty_estimated_cost, record.warranty_approved_cost,
                              record.warranty_material_cost), (3500, 3500, 1000), record)
            self.assertIn('Warranty Material Cost', record.warranty_cost_summary)
        # T7.8: no accounting posting by any 5.7 computation; manual valuation kept.
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)
        self.assertEqual(self.filter.categ_id.property_valuation, 'manual_periodic')
        location = self.company.warranty_mrf_consumption_location_id
        self.assertFalse(location.valuation_in_account_id or location.valuation_out_account_id)
        # T7.10: report rows = form values.
        rows = self._report(mrf)
        self.assertEqual(len(rows), 2)
        self.assertEqual((sum(rows.mapped('estimated_cost')), sum(rows.mapped('approved_cost')),
                          sum(rows.mapped('actual_cost')), sum(rows.mapped('warranty_cost'))),
                         (3500, 3500, 1000, 1000))

    # ------------------------------------------------------------------ T7.6
    def test_02_fifo_and_avco_layer_values(self):
        """FIFO / AVCO: the actual cost is the value of the consumption layers, not qty x
        current product cost; a reversal after a cost change is not counted (no negative or
        overstated cost); the reversed value is reported separately."""
        self._receive(self.motor, 2, 100)
        self._receive(self.motor, 2, 150)
        self._receive(self.coil, 2, 100)
        self._receive(self.coil, 2, 200)
        mrf = self._issue(self._mrf([(self.motor, 3), (self.coil, 2)]))
        m_line, c_line = self._line(mrf, self.motor), self._line(mrf, self.coil)
        self._use(mrf, self.motor, 3)
        self.assertEqual(m_line.actual_cost, 2 * 100 + 150)
        self.assertNotEqual(m_line.actual_cost, 3 * self.motor.standard_price)
        entry = self._use(mrf, self.coil, 1)
        self.assertEqual(c_line.actual_cost, 150)
        self._receive(self.coil, 2, 300)
        self.assertNotEqual(self.coil.standard_price, 150)
        self._use(mrf, self.coil, 1)
        c_line.invalidate_recordset()
        actual_both = c_line.actual_cost
        self.assertEqual(actual_both, 150 + self.coil.standard_price)
        entry.with_user(self.coordinator)._warranty_reverse('Wrong job')
        c_line.invalidate_recordset()
        self.assertEqual((c_line.actual_cost, c_line.reversed_cost),
                         (actual_both - 150, 150))
        self.assertEqual(self._report(mrf).filtered(
            lambda row: row.product_id == self.coil).reversed_cost, 150)

    # ------------------------------------------------------------------ H-2
    def test_03_missing_valuation_layer_is_unverified(self):
        """A consumption move without valuation layer (as for legacy / imported moves or
        consigned stock): the fallback value is shown as Unverified / Estimated only, never as
        verified actual cost; visible in the totals note and the report filter."""
        self._receive(self.filter, 5, 500)
        mrf = self._issue(self._mrf([(self.filter, 4)]))
        line = self._line(mrf, self.filter)
        entry = self._use(mrf, self.filter, 3).sudo()
        self.assertEqual((line.actual_cost, line.cost_status), (1500, 'verified'))
        entry.move_ids.stock_valuation_layer_ids.sudo().unlink()
        self.assertFalse(entry.move_ids.stock_valuation_layer_ids)
        self.assertEqual((line.actual_cost, line.actual_unverified_cost, line.cost_status),
                         (0, 1500, 'unverified'))
        mrf.invalidate_recordset()
        self.assertEqual((mrf.warranty_material_cost, mrf.warranty_material_cost_unverified),
                         (0, 1500))
        self.assertIn('Unverified', mrf.warranty_cost_summary)
        row = self.Report.with_user(self.coordinator).search(
            [('requisition_id', '=', mrf.id), ('cost_status', '=', 'unverified')])
        self.assertEqual((row.actual_cost, row.actual_unverified_cost, row.warranty_cost),
                         (0, 1500, 0))

    # ------------------------------------------------------------------ T7.3 / T7.4
    def test_04_unused_return_and_cancel_remaining(self):
        """Unused returns create no cost; Cancel Remaining reduces Approved (Net) only, the
        approved snapshot and the approval history stay unchanged."""
        self._receive(self.filter, 10, 500)
        self._receive(self.valve, 2, 2000)
        mrf = self._mrf([(self.filter, 3), (self.valve, 5)])
        self._issue(mrf)
        mrf.sudo().purchase_order_ids.button_cancel()
        f_line, v_line = self._line(mrf, self.filter), self._line(mrf, self.valve)
        self._use(mrf, self.filter, 1)
        wizard_action = mrf.with_user(self.tech).action_warranty_return_unused()
        wizard = self.env[wizard_action['res_model']].with_user(self.tech).browse(
            wizard_action['res_id'])
        for row in wizard.line_ids:
            row.qty = 2 if row.product_id == self.filter else 0
        wizard.note = 'Not needed'
        wizard.action_apply()
        returns = f_line.warranty_consumption_ids.filtered(
            lambda entry: entry.kind == 'unused_return').picking_id
        self._validate(returns)
        self.assertEqual((f_line.returned_qty, f_line.actual_cost), (2, 500))
        approved = v_line.approved_cost
        mrf.with_user(self.store)._warranty_cancel_remaining([(v_line, 3.0, self.Lot)],
                                                             'Unit replaced')
        self.assertEqual((v_line.approved_cost, v_line.cancelled_cost, v_line.approved_net_cost),
                         (approved, 6000, approved - 6000))
        self._use(mrf, self.valve, 2)
        self.assertEqual((v_line.actual_cost, v_line.cost_variance), (4000, 0))
        row = self._report(mrf).filtered(lambda row: row.product_id == self.valve)
        self.assertEqual((row.cancelled_qty, row.cancelled_cost, row.approved_net_cost),
                         (3, 6000, 4000))

    # ------------------------------------------------------------------ T7.5
    def test_05_customer_paid_cost_billing_and_returns(self):
        """Customer-paid parts: cost of the delivery (layer) net of customer returns valued at
        the delivered cost, invoices and credit notes separately; excluded from the Warranty
        Material Cost; nothing counted twice."""
        self._receive(self.oil, 5, 1000)
        job = self._confirmed_job()
        mrf = self._mrf([(self.oil, 3)], job=job)
        line = self._line(mrf, self.oil)
        self.assertEqual(line.cost_bucket, 'customer')
        order = self.env['sale.order'].browse(
            mrf.with_user(self.helpdesk_user).action_create_parts_quotation()['res_id'])
        order.action_confirm()
        self._validate(order.picking_ids)
        self.assertEqual((line.actual_cost, line.cost_status), (3000, 'verified'))
        invoice = order._create_invoices()
        invoice.action_post()
        self.assertEqual((line.invoiced_amount, line.billed_amount), (12000, 12000))
        mrf.with_user(self.tech)._warranty_record_usage([(line, 2.0, self.Lot)])
        # Product cost change before the return: the return still reduces at delivered cost.
        self.oil.standard_price = 1500
        returns = mrf.with_user(self.helpdesk_user)._warranty_customer_return(
            [(line, 1.0, self.Lot)], 'Not needed')
        self._validate(returns)
        line.invalidate_recordset()
        self.assertEqual((line.actual_cost, line.returned_cost), (2000, 1000))
        refund = order._create_invoices(final=True)
        self.assertEqual(refund.move_type, 'out_refund')
        refund.action_post()
        self.assertEqual((line.invoiced_amount, line.credited_amount, line.billed_amount),
                         (12000, 4000, 8000))
        for record in (mrf, job):
            record.invalidate_recordset()
            self.assertEqual((record.warranty_material_cost, record.customer_paid_cost,
                              record.customer_billed_amount), (0, 2000, 8000))
        # Recomputing gives the same values (no accumulation).
        line.sudo()._compute_actual_cost()
        self.assertEqual((line.actual_cost, line.billed_amount), (2000, 8000))
        row = self._report(mrf)
        self.assertEqual((row.actual_cost, row.warranty_cost, row.billed_amount),
                         (2000, 0, 8000))

    # ------------------------------------------------------------------ T7.7 goodwill, matrix off
    def test_06_goodwill_bucket_matrix_off(self):
        """Goodwill lines are a separate bucket and part of the Warranty Material Cost; the
        vendor 2-step approval (matrix off) records the snapshot too."""
        self.company.warranty_mrf_approval_matrix = False
        self._receive(self.filter, 5, 500)
        mrf = self._mrf([(self.filter, 2)], approve=False)
        line = self._line(mrf, self.filter)
        self.env.flush_all()
        mrf.with_user(self.approver_b)._warranty_decide_coverage(line, 'goodwill', 'Key customer')
        self.env.flush_all()
        self.assertTrue(line.goodwill)
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        dept = self._user('mrf_k_dept',
                          'material_purchase_requisitions.group_purchase_requisition_department')
        dept.groups_id |= self.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        mrf.with_user(dept).manager_approve()
        self.assertFalse(line.approved_cost_recorded)
        mrf.with_user(self.store).user_approve()
        self.assertEqual((line.cost_bucket, line.approved_cost, line.approved_cost_state),
                         ('goodwill', 1000, 'recorded'))
        self._issue(mrf)
        self._use(mrf, self.filter, 2)
        mrf.invalidate_recordset()
        self.assertEqual(mrf.warranty_material_cost, 1000)
        self.assertEqual(self._report(mrf).warranty_cost, 1000)

    # ------------------------------------------------------------------ H-5 legacy / upgrade
    def test_07_legacy_and_pre_5_7_snapshots(self):
        """Legacy (pre-matrix) requests: Not Recorded (Legacy), actual cost still computed.
        Upgrade: requests approved before 5.7 get the snapshot only when the line costs still
        match the Approved Amount; otherwise Not Recorded; no approval record changed."""
        self._receive(self.filter, 10, 500)
        job = self._confirmed_job()
        action = job.with_user(self.helpdesk_user).action_create_material_request()
        legacy = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {'product_id': self.filter.id, 'qty': 2,
                                             'description': 'Filter',
                                             'uom': self.filter.uom_id.id})]})
        legacy.sudo().write({'state': 'stock'})
        line = legacy.requisition_line_ids
        self.assertEqual((line.approved_cost_state, line.approved_cost), ('legacy', 0))
        legacy.invalidate_recordset()
        self.assertIn('Not Recorded', legacy.warranty_cost_summary)
        # Requests approved before the upgrade (snapshot removed as in an old database).
        matching = self._mrf([(self.filter, 1)])
        changed = self._mrf([(self.valve, 1)])
        approvals = self.env['warranty.mrf.approval'].search_count([])
        (matching | changed).requisition_line_ids.sudo().write(
            {'approved_cost_recorded': False, 'approved_cost': 0, 'approved_unit_cost': 0})
        self.valve.standard_price = 2500
        done, skipped = self.Mrf._warranty_migrate_approved_cost()
        self.assertIn(matching, done)
        self.assertIn(changed, skipped)
        self.assertEqual((matching.requisition_line_ids.approved_cost_state,
                          matching.requisition_line_ids.approved_cost), ('recorded', 500))
        self.assertEqual((changed.requisition_line_ids.approved_cost_state,
                          changed.requisition_line_ids.approved_cost), ('pre_cost', 0))
        self.assertIn('Not Recorded', changed.message_ids[0].body)
        self.assertEqual(self.env['warranty.mrf.approval'].search_count([]), approvals)
        # A second run changes nothing.
        done, skipped = self.Mrf._warranty_migrate_approved_cost()
        self.assertNotIn(matching, done)

    # ------------------------------------------------------------------ T7.9 / H-11 / H-12
    def test_08_access_and_snapshot_protection(self):
        """Technicians cannot read cost fields (read, export, views, report); accountants read
        the report; nobody writes the snapshot; the report is company-scoped and uses the
        request company's currency."""
        self._receive(self.filter, 5, 500)
        mrf = self._issue(self._mrf([(self.filter, 2)]))
        self._use(mrf, self.filter, 1)
        line = self._line(mrf, self.filter)
        job = mrf.warranty_service_job_id
        tech_line = line.with_user(self.tech)
        self.assertEqual(tech_line.used_qty, 1)
        for field in COST_FIELDS:
            with self.assertRaises(AccessError):
                tech_line.read([field])
        with self.assertRaises(AccessError):
            tech_line.search_read([('id', '=', line.id)], ['actual_cost'])
        with self.assertRaises(AccessError):
            tech_line.read_group([('id', '=', line.id)], ['actual_cost:sum'], ['product_id'])
        with self.assertRaises(AccessError):
            job.with_user(self.tech).read(['warranty_material_cost'])
        with self.assertRaises(AccessError):
            self.Report.with_user(self.tech).search([])
        for model, record in (('warranty.service.job', job), ('material.purchase.requisition', mrf)):
            arch = self.env[model].with_user(self.tech).get_views(
                [(False, 'form')])['views']['form']['arch']
            self.assertNotIn('warranty_cost_summary', arch, model)
            self.assertNotIn('actual_cost', arch, model)
        arch = self.env['warranty.service.job'].with_user(self.coordinator).get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertIn('warranty_cost_summary', arch)
        # Accountant: report only (read, group by case), no write.
        rows = self._report(mrf, self.accountant)
        self.assertEqual(rows.actual_cost, 500)
        groups = self.Report.with_user(self.accountant).read_group(
            [('requisition_id', '=', mrf.id)], ['actual_cost:sum'], ['case_id'])
        self.assertEqual(groups[0]['actual_cost'], 500)
        with self.assertRaises(AccessError):
            rows.with_user(self.accountant).write({'actual_cost': 0})
        # Snapshot protection: users cannot set approved costs, also on New requests.
        draft = self._mrf([(self.filter, 1)], approve=False)
        with self.assertRaisesRegex(UserError, 'approval workflow'):
            draft.requisition_line_ids.with_user(self.helpdesk_user).write({'approved_cost': 1})
        # Multi-company: rows of another company are not visible; that company's currency.
        other_currency = self.env['res.currency'].with_context(active_test=False).search(
            [('id', '!=', self.company.currency_id.id)], limit=1)
        other_currency.active = True
        other = self.env['res.company'].create({'name': 'Warranty Co B',
                                                'currency_id': other_currency.id})
        self.env.flush_all()
        self.env.cr.execute("UPDATE material_purchase_requisition SET company_id = %s "
                            "WHERE id = %s", (other.id, draft.id))
        self.env.invalidate_all()
        self.assertFalse(self._report(draft, self.accountant))
        self.accountant.write({'company_ids': [(4, other.id)]})
        row = self.Report.with_user(self.accountant).with_context(
            allowed_company_ids=[self.company.id, other.id]).search(
            [('requisition_id', '=', draft.id)])
        self.assertEqual((row.company_id, row.currency_id), (other, other_currency))

    # ------------------------------------------------------------------ menu (SRS section 6)
    def test_09_report_menu_navigation_and_access(self):
        """Warranty -> Reports -> Warranty Material Cost (no separate Warranty -> Material Cost
        entry); Accounting -> Reporting shortcut kept; both open the same report action; menus
        visible to the authorised groups only, the Reports parent only when it has a report."""
        root = self.env.ref('warranty_management.menu_warranty_root')
        reports = self.env.ref('warranty_management_mrf.menu_warranty_reports')
        menu = self.env.ref('warranty_management_mrf.menu_warranty_mrf_cost_report')
        shortcut = self.env.ref('warranty_management_mrf.menu_warranty_mrf_cost_report_accounting')
        action = self.env.ref('warranty_management_mrf.action_warranty_mrf_cost_report')
        self.assertEqual((reports.parent_id, reports.name, bool(reports.action)), (root, 'Reports', False))
        self.assertEqual((menu.parent_id, menu.name, menu.action), (reports, 'Warranty Material Cost',
                                                                    action))
        self.assertEqual((shortcut.parent_id, shortcut.action),
                         (self.env.ref('account.menu_finance_reports'), action))
        self.assertFalse(self.env['ir.ui.menu'].search([('parent_id', '=', root.id),
                                                        ('action', '=', 'ir.actions.act_window,%s'
                                                         % action.id)]))
        self.assertEqual(action.view_mode, 'pivot,list,graph')
        Menu = self.env['ir.ui.menu']
        for user, warranty_menu, accounting_menu in ((self.coordinator, True, False),
                                                     (self.store, True, False),
                                                     (self.accountant, True, True),
                                                     (self.tech, False, False)):
            visible = Menu.with_user(user)._visible_menu_ids()
            self.assertEqual((menu.id in visible, reports.id in visible),
                             (warranty_menu, warranty_menu), user.login)
            self.assertEqual(shortcut.id in visible, accounting_menu, user.login)
        # Opening the action as an unauthorised user is refused by the model access rights.
        with self.assertRaises(AccessError):
            self.Report.with_user(self.tech).search_read([], ['actual_cost'])
        self.assertTrue(self.Report.with_user(self.accountant).has_access('read'))
        self.assertFalse(self.Report.with_user(self.tech).has_access('read'))
