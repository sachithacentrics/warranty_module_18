from odoo.tests import TransactionCase, tagged

# Phase 5.0 role mapping (doc/part5_design_decisions.md): SRS section 16 roles -> existing groups.
ROLE_GROUPS = {
    'Service Coordinator': ['helpdesk.group_helpdesk_user',
                            'material_purchase_requisitions.group_purchase_requisition_user'],
    'Technician': ['industry_fsm.group_fsm_user'],
    'Store User': ['stock.group_stock_user',
                   'material_purchase_requisitions.group_purchase_requisition_user'],
    'Material Approver': ['material_purchase_requisitions.group_purchase_requisition_department',
                          'material_purchase_requisitions.group_purchase_requisition_manager'],
    'Purchasing': ['purchase.group_purchase_user'],
    'Accountant': ['account.group_account_readonly', 'account.group_account_invoice'],
}


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyMrfFoundation(TransactionCase):
    """Phase 5.0 - integration foundation (T0.1 - T0.4)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.department = cls.env['hr.department'].create({'name': 'MRF Test Service'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'MRF Test Requester', 'user_id': cls.env.uid,
            'department_id': cls.department.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'MRF Test Vendor'})
        cls.part = cls.env['product.product'].create({
            'name': 'MRF Test Compressor', 'type': 'consu', 'is_storable': True})
        cls.env['stock.quant']._update_available_quantity(
            cls.part, cls.warehouse.lot_stock_id, 10)
        cls.env.user.write({'groups_id': [
            (4, cls.env.ref('material_purchase_requisitions.group_purchase_requisition_manager').id),
            (4, cls.env.ref('material_purchase_requisitions.group_purchase_requisition_department').id),
        ]})

    def test_01_dependencies_installed(self):
        """T0.1: the bridge and the modules it builds on are installed."""
        modules = self.env['ir.module.module'].search([('name', 'in', [
            'warranty_management_mrf', 'material_purchase_requisitions', 'warranty_management_fsm',
            'warranty_management_helpdesk', 'warranty_management', 'purchase_stock', 'sale_stock'])])
        self.assertEqual(len(modules), 7)
        self.assertEqual(set(modules.mapped('state')), {'installed'})

    def test_02_role_mapping_groups_exist(self):
        """T0.2: every group of the approved role mapping exists."""
        for role, xmlids in ROLE_GROUPS.items():
            for xmlid in xmlids:
                self.assertTrue(self.env.ref(xmlid, raise_if_not_found=False),
                                "%s: group %s is missing" % (role, xmlid))

    def test_03_standalone_requisition_unchanged(self):
        """T0.3: a requisition without warranty link keeps the vendor workflow:
        confirm -> department approval -> approval -> picking + RFQ -> received."""
        mrf = self.env['material.purchase.requisition'].create({
            'employee_id': self.employee.id,
            'department_id': self.department.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'dest_location_id': self.env.ref('stock.stock_location_customers').id,
            'custom_picking_type_id': self.warehouse.int_type_id.id,
            'requisition_line_ids': [
                (0, 0, {'product_id': self.part.id, 'description': 'From stock', 'qty': 2,
                        'uom': self.part.uom_id.id, 'requisition_type': 'internal'}),
                (0, 0, {'product_id': self.part.id, 'description': 'To buy', 'qty': 3,
                        'uom': self.part.uom_id.id, 'requisition_type': 'purchase',
                        'partner_id': [(6, 0, self.vendor.ids)]}),
            ],
        })
        self.assertTrue(mrf.name)
        self.assertEqual(mrf.state, 'draft')
        mrf.requisition_confirm()
        self.assertEqual(mrf.state, 'dept_confirm')
        mrf.manager_approve()
        self.assertEqual(mrf.state, 'ir_approve')
        mrf.user_approve()
        self.assertEqual(mrf.state, 'approve')
        mrf.request_stock()
        self.assertEqual(mrf.state, 'stock')
        self.assertEqual(mrf.delivery_picking_id.move_ids.mapped('product_uom_qty'), [2.0])
        self.assertEqual(mrf.delivery_picking_id.custom_requisition_id, mrf)
        self.assertEqual(mrf.purchase_order_ids.partner_id, self.vendor)
        self.assertEqual(mrf.purchase_order_ids.order_line.product_qty, 3.0)
        mrf.action_received()
        self.assertEqual(mrf.state, 'receive')

    def test_04_bridge_fields_only_on_integration_models(self):
        """T0.4: the bridge only adds fields to the models it integrates (5.1); nothing else of
        Parts 1-4 or AMC is extended."""
        field_ids = self.env['ir.model.data'].search([
            ('module', '=', 'warranty_management_mrf'), ('model', '=', 'ir.model.fields')]).mapped('res_id')
        models_extended = set(self.env['ir.model.fields'].browse(field_ids).mapped('model'))
        self.assertLessEqual(models_extended, {
            'material.purchase.requisition', 'material.purchase.requisition.line', 'warranty.case',
            'warranty.service.job', 'project.task', 'helpdesk.ticket', 'res.company',
            'res.config.settings', 'warranty.mrf.link.wizard', 'warranty.mrf.coverage.wizard',
            'warranty.mrf.coverage.wizard.line',
            'warranty.mrf.route.preview.wizard', 'warranty.mrf.consumption', 'stock.move',
            'warranty.mrf.material.wizard', 'warranty.mrf.material.wizard.line',
            'warranty.mrf.reverse.wizard', 'warranty.mrf.cancel.wizard',
            'warranty.mrf.approval.rule', 'warranty.mrf.approval', 'warranty.mrf.reject.wizard',
            'warranty.mrf.decline.wizard', 'warranty.mrf.release.exception.wizard', 'sale.order',
            'sale.order.line', 'stock.picking', 'purchase.order',
            'warranty.mrf.cost.totals.mixin', 'warranty.mrf.cost.report',
            # Phase 5.8: vendor claims (claimable parts on products, credit note links).
            'warranty.vendor.claim', 'warranty.vendor.claim.line',
            'warranty.vendor.claim.recovery', 'warranty.vendor.claim.wizard',
            'warranty.vendor.claim.wizard.line', 'warranty.vendor.claim.reason.wizard',
            'warranty.vendor.claim.response.wizard',
            'warranty.vendor.claim.response.wizard.line',
            'warranty.vendor.claim.allocate.wizard', 'product.template', 'account.move',
            # delegated (_inherits) copies of the two fields above
            'product.product', 'account.bank.statement.line',
            # Phase 5.9: closure wizards and reports.
            'warranty.mrf.close.wizard', 'warranty.mrf.close.wizard.line',
            'warranty.mrf.reopen.wizard', 'warranty.mrf.approval.cost.report',
            'warranty.vendor.claim.recovery.report', 'warranty.mrf.audit.event'})
