from datetime import timedelta

from odoo import fields

from odoo.addons.warranty_management_fsm.tests.common import ServiceJobCommon


class WarrantyMrfCommon(ServiceJobCommon):
    """Employees, locations and a part for warranty Material Requests (Phase 5.1+)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Employee = cls.env['hr.employee']
        cls.department = cls.env['hr.department'].create({'name': 'MRF Service Department'})
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.tech_location = cls.env['stock.location'].create({
            'name': 'Van 1', 'usage': 'internal', 'location_id': cls.warehouse.view_location_id.id})
        cls.default_tech_location = cls.env['stock.location'].create({
            'name': 'Technician Stock', 'usage': 'internal',
            'location_id': cls.warehouse.view_location_id.id})
        cls.tech = cls._user('mrf_tech', 'industry_fsm.group_fsm_user')
        cls.other_tech = cls._user('mrf_other_tech', 'industry_fsm.group_fsm_user')
        (cls.tech | cls.other_tech).email = 'tech@example.com'
        for user, location in ((cls.helpdesk_user, False), (cls.tech, cls.tech_location),
                               (cls.other_tech, False)):
            Employee.create({'name': user.name, 'user_id': user.id, 'company_id': cls.company.id,
                             'department_id': cls.department.id,
                             'dest_location_id': location and location.id})
        cls.no_dept_user = cls._user('mrf_no_dept', 'helpdesk.group_helpdesk_user')
        Employee.create({'name': 'No Department', 'user_id': cls.no_dept_user.id,
                         'company_id': cls.company.id})
        cls.no_employee_user = cls._user('mrf_no_employee', 'helpdesk.group_helpdesk_user')
        cls.part = cls.env['product.product'].create({
            'name': 'Outdoor PCB', 'type': 'consu', 'is_storable': True, 'standard_price': 18500,
            'tracking': 'serial'})
        cls.Mrf = cls.env['material.purchase.requisition']
        # Phase 5.1 / 5.2 tests run the Requisition workflow (no approval rules); the 5.3
        # tests switch the Material Approval Matrix on.
        cls.company.warranty_mrf_approval_matrix = False
        # Rules of the database (e.g. manual test data) must not influence the tests.
        cls.env['warranty.mrf.approval.rule'].search([]).active = False
        # Same for the 5.4 settings: tests start from the default release trigger.
        cls.company.write({'warranty_mrf_release_trigger': 'confirmation',
                           'warranty_mrf_release_exception_user_ids': [(5, 0, 0)]})

    def _confirmed_job(self, tech=None):
        case = self._approved()
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': (tech or self.tech).id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual(job.state, 'confirmed')
        return job

    def _save(self, action, user, qty=1.0, products=None):
        """Save the form opened by Create Material Request (its context defaults)."""
        return self.Mrf.with_user(user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {
                'product_id': product.id, 'description': product.name, 'qty': qty,
                'uom': product.uom_id.id}) for product in (products or self.part)],
        })

    def _standalone(self, user=None):
        return self.Mrf.with_user(user or self.helpdesk_user).create({
            'employee_id': self.env['hr.employee'].search(
                [('user_id', '=', (user or self.helpdesk_user).id)], limit=1).id,
            'department_id': self.department.id,
        })
