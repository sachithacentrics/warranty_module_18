from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_figure6_service_mode import Figure6Common


@tagged('post_install', '-at_install', 'warranty_repair', 'warranty_figure7')
class TestFigure7RepairMaterialRequest(Figure6Common):
    """Figure 7 D9: Create Material Request on the Repair Order links exactly that Repair Order
    (also with several open Repair Orders), the case, customer, product and serial; a request
    created from the case is linked only to the case's only open Repair Order (never guessed)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        department = cls.env['hr.department'].create({'name': 'F7 Workshop'})
        cls.env['hr.employee'].create({'name': cls.coordinator.name, 'user_id': cls.coordinator.id,
                                       'company_id': cls.company.id,
                                       'department_id': department.id})
        cls.pcb = cls.env['product.product'].create({
            'name': 'F7 Workshop PCB', 'type': 'consu', 'is_storable': True,
            'standard_price': 100})

    def _save(self, action):
        return self.env['material.purchase.requisition'].with_user(self.coordinator).with_context(
            **action['context']).create({'requisition_line_ids': [(0, 0, {
                'product_id': self.pcb.id, 'description': self.pcb.name, 'qty': 1,
                'uom': self.pcb.uom_id.id})]})

    def test_01_create_from_repair_order(self):
        if not self.case.case_type:
            self.case.sudo().case_type = 'warranty_complaint'
        first, second = self._repair(), self._repair()
        from_case = self._save(self.case.with_user(self.coordinator)
                               .action_create_material_request())
        self.assertFalse(from_case.warranty_repair_id, 'two open Repair Orders: not guessed')
        mrf = self._save(second.with_user(self.coordinator)
                         .action_warranty_create_material_request())
        self.assertEqual((mrf.warranty_repair_id, mrf.warranty_case_id), (second, self.case))
        self.assertEqual((mrf.warranty_partner_id, mrf.warranty_product_id, mrf.warranty_serial_id),
                         (self.case.partner_id, self.case.product_id, self.case.serial_id))
        self.assertFalse(mrf.warranty_service_job_id, 'no job accepts requests: none linked')
        self.assertIn(mrf.requisition_line_ids, second.warranty_mrf_line_ids)
        self.assertNotIn(mrf.requisition_line_ids, first.warranty_mrf_line_ids)
        first.action_repair_cancel()
        with self.assertRaisesRegex(UserError, 'is closed'):
            first.with_user(self.coordinator).action_warranty_create_material_request()
        single = self._save(self.case.with_user(self.coordinator)
                            .action_create_material_request())
        self.assertEqual(single.warranty_repair_id, second, 'the only open Repair Order')
        arch = self.env['repair.order'].with_user(self.coordinator).get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertIn('action_warranty_create_material_request', arch)
        arch = self.env['material.purchase.requisition'].with_user(self.coordinator).get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertIn('warranty_repair_id', arch)
