from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.warranty_management_mrf.tests.common import WarrantyMrfCommon

from .test_warranty_cost_lines import _SavepointMixin


@tagged('post_install', '-at_install', 'warranty_cost', 'warranty_figure7')
class TestFigure7CostBreakdown(_SavepointMixin, WarrantyMrfCommon):
    """Figure 7 D5: material approval stays on the request, labour / travel / subcontract / other
    on the case's cost lines (Part 8.1); the request shows a read-only estimated / approved /
    actual breakdown of itself and of its case, each source counted once; the Expected Cost
    Approval Gate blocks the material issue while a cost line or request is unapproved."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls._user('f7_cost_manager', 'helpdesk.group_helpdesk_user')
        cls.store = cls._user('f7_cost_store',
                              'material_purchase_requisitions.group_purchase_requisition_user')
        cls.company.write({
            'warranty_cost_approver_ids': [(6, 0, cls.manager.ids)],
            'warranty_cost_finance_threshold': 0,
            'warranty_cost_gate_enabled': False,
            'warranty_cost_gate_threshold': 0,
            'warranty_mrf_approval_matrix': True,
            'warranty_mrf_dest_location_id': cls.default_tech_location.id,
        })
        cls.filter = cls.env['product.product'].create({
            'name': 'F7 Air Filter', 'is_storable': True, 'type': 'consu', 'standard_price': 500})
        cls.gas = cls.env['product.product'].create({
            'name': 'F7 Gas', 'type': 'consu', 'standard_price': 3000, 'list_price': 4000})
        cls.policy.covered_item_ids |= cls.env['warranty.coverage.item'].create({
            'name': cls.filter.name, 'product_id': cls.filter.id})
        cls.item_gas.product_id = cls.gas
        cls.env['stock.quant']._update_available_quantity(cls.filter, cls.warehouse.lot_stock_id, 10)

    def _mrf(self, job, lines):
        action = job.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {'product_id': product.id, 'qty': qty,
                                             'description': product.name,
                                             'uom': product.uom_id.id})
                                     for product, qty in lines]})
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        return mrf

    def _cost_line(self, case, cost_type, amount):
        line = self.env['warranty.cost.line'].with_user(self.helpdesk_user).create({
            'case_id': case.id, 'cost_type': cost_type, 'reason': 'Figure 7',
            'estimated_amount': amount})
        return line

    def test_01_breakdown_counts_each_source_once(self):
        job = self._confirmed_job()
        case = job.warranty_case_id
        first = self._mrf(job, [(self.filter, 2), (self.gas, 1)])
        second = self._mrf(job, [(self.filter, 1)])
        self._cost_line(case, 'labour', 800)
        self._cost_line(case, 'subcontract', 1200)
        self._cost_line(case, 'other', 100)
        html = str(first.with_user(self.helpdesk_user).warranty_case_cost_breakdown)
        for text in ('This request: warranty-borne materials', 'Labour', 'Subcontract', 'Other',
                     'Variance', case.name, 'Customer-paid'):
            self.assertIn(text, html)
        figures = case._warranty_cost_figures()[0]
        self.assertEqual(figures['parts']['estimated'], 1500, 'both requests, covered only')
        self.assertEqual((figures['labour']['estimated'], figures['subcontract']['estimated'],
                          figures['other']['estimated']), (800, 1200, 100))
        self.assertEqual(case.warranty_total_estimated, 3600, 'each source once')
        self.assertEqual(str(second.with_user(self.helpdesk_user).warranty_case_cost_breakdown)
                         .count('3,600'), html.count('3,600'), 'same case totals on each request')
        self.assertEqual(first.approval_routing_amount, 4000, 'material only (D5)')
        arch = self.Mrf.with_user(self.helpdesk_user).get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertIn('warranty_case_cost_breakdown', arch)
        self.assertNotIn('warranty_case_cost_breakdown',
                         self.Mrf.with_user(self.tech).get_views(
                             [(False, 'form')])['views']['form']['arch'], 'cost groups only')

    def test_02_gate_blocks_material_issue(self):
        """Part 8.1 gate on: total expected cost above the threshold with an unapproved cost line
        -> the approved request is not issued (Create Picking / Recheck Stock); approved line ->
        issued; the gate shows on the breakdown."""
        job = self._confirmed_job()
        case = job.warranty_case_id
        mrf = self._mrf(job, [(self.filter, 1)])
        self.assertEqual(mrf.state, 'approve')
        line = self._cost_line(case, 'labour', 2000)
        self.company.write({'warranty_cost_gate_enabled': True,
                            'warranty_cost_gate_threshold': 1000})
        with self.assertRaisesRegex(UserError, 'waiting for approval'):
            mrf.with_user(self.store).action_warranty_fulfil()
        self.assertIn('waiting for approval',
                      str(mrf.with_user(self.helpdesk_user).warranty_case_cost_breakdown))
        line.with_user(self.helpdesk_user).action_submit()
        line.with_user(self.manager).action_approve()
        self.assertEqual(line.state, 'approved')
        mrf.with_user(self.store).action_warranty_fulfil()
        self.assertEqual(mrf.state, 'stock')
