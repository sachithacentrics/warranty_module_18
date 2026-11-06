from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .common import WarrantyMrfCommon


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyMrfCreateLink(WarrantyMrfCommon):
    """Phase 5.1 - create / link Material Requests from warranty cases, service jobs and Field
    Service visits (mapping 5.1, T1.1 - T1.10)."""

    # ------------------------------------------------------------------ T1.1
    def test_01_create_from_case(self):
        """T1.1: from an Approved case without job: case links, customer / site / ticket from
        the case, requester and department of the user, company default locations."""
        self.company.warranty_mrf_dest_location_id = self.default_tech_location
        case = self._approved()
        action = case.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self._save(action, self.helpdesk_user)
        self.assertEqual((mrf.warranty_case_id, mrf.warranty_service_job_id, mrf.warranty_task_id),
                         (case, self.env['warranty.service.job'], self.env['project.task']))
        self.assertTrue(mrf.is_warranty_mrf)
        self.assertEqual(mrf.warranty_partner_id, case.partner_id)
        self.assertEqual(mrf.warranty_helpdesk_ticket_id, case.helpdesk_ticket_id)
        self.assertEqual(mrf.warranty_site_id, case.site_id)
        self.assertEqual(mrf.employee_id.user_id, self.helpdesk_user)
        self.assertEqual(mrf.department_id, self.department)
        self.assertEqual(mrf.company_id, case.company_id)
        self.assertEqual(mrf.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(mrf.dest_location_id, self.default_tech_location)
        self.assertEqual(mrf.custom_picking_type_id, self.warehouse.int_type_id)
        self.assertEqual(mrf.state, 'draft')
        self.assertIn(case.name, mrf.reason)
        self.assertIn('created', case.message_ids[:1].body)

    def test_02_create_from_job_and_task(self):
        """T1.1: from a confirmed job: case, job and its only visit; the main technician's
        employee location is the destination. From the visit: the same links."""
        job = self._confirmed_job()
        task = job.visit_ids
        self.assertEqual(len(task), 1)
        mrf = self._save(job.with_user(self.helpdesk_user).action_create_material_request(),
                         self.helpdesk_user)
        self.assertEqual((mrf.warranty_case_id, mrf.warranty_service_job_id, mrf.warranty_task_id),
                         (job.warranty_case_id, job, task))
        self.assertEqual(mrf.dest_location_id, self.tech_location)
        self.assertIn('created', job.message_ids[:1].body)
        mrf2 = self._save(task.with_user(self.tech).action_warranty_create_material_request(),
                          self.tech)
        self.assertEqual((mrf2.warranty_case_id, mrf2.warranty_service_job_id, mrf2.warranty_task_id),
                         (job.warranty_case_id, job, task))
        self.assertEqual(mrf2.employee_id.user_id, self.tech)
        # The case shows the open job's links too.
        mrf3 = self._save(job.warranty_case_id.with_user(self.helpdesk_user)
                          .action_create_material_request(), self.helpdesk_user)
        self.assertEqual(mrf3.warranty_service_job_id, job)
        # Smart buttons (T1.9).
        self.assertEqual(job.warranty_case_id.material_request_count, 3)
        self.assertEqual(job.material_request_count, 3)
        self.assertEqual(task.warranty_material_request_count, 3)
        self.assertEqual(job.helpdesk_ticket_id.warranty_material_request_count, 3)
        action = job.action_view_material_requests()
        self.assertEqual(self.Mrf.search(action['domain']), mrf | mrf2 | mrf3)

    # ------------------------------------------------------------------ T1.2
    def test_03_refused_states(self):
        """T1.2: New case, Draft / Planned job, non-warranty or closed task are refused, also
        through a direct create with the links."""
        new_case = self._create_case(self.ticket, user=self.creator)
        self.assertEqual(new_case.state, 'new')
        with self.assertRaisesRegex(UserError, 'Approved, Job Created'):
            new_case.with_user(self.helpdesk_user).action_create_material_request()
        with self.assertRaisesRegex(UserError, 'Approved, Job Created'):
            self.Mrf.with_user(self.helpdesk_user).create(
                self.Mrf.with_user(self.helpdesk_user)._warranty_mrf_default_vals(new_case))
        job = self._prepare(self._approved())
        self.assertEqual(job.state, 'draft')
        with self.assertRaisesRegex(UserError, 'confirmed, open service jobs'):
            job.with_user(self.helpdesk_user).action_create_material_request()
        plain_task = self.env['project.task'].create({'name': 'Not a warranty visit'})
        with self.assertRaisesRegex(UserError, 'warranty Field Service visits'):
            plain_task.with_user(self.helpdesk_user).action_warranty_create_material_request()
        job = self._confirmed_job()
        # A closed visit on an open job (Part 4 only closes visits through its own paths).
        self.env.cr.execute("UPDATE project_task SET state = '1_canceled' WHERE id = %s",
                            [job.visit_ids.id])
        job.visit_ids.invalidate_recordset(['state'])
        with self.assertRaisesRegex(UserError, 'is closed'):
            job.visit_ids.with_user(self.tech).action_warranty_create_material_request()

    # ------------------------------------------------------------------ T1.3
    def test_04_requester_employee_and_department(self):
        """T1.3: the requester needs an employee in the company with a department."""
        case = self._approved()
        with self.assertRaisesRegex(UserError, 'employee linked to your user'):
            case.with_user(self.no_employee_user).action_create_material_request()
        with self.assertRaisesRegex(UserError, 'has no department'):
            case.with_user(self.no_dept_user).action_create_material_request()

    # ------------------------------------------------------------------ T1.4
    def test_05_numbering(self):
        """T1.4: warranty requests MRF/000001…, standalone requests keep the vendor sequence,
        also when both are created in one call."""
        case = self._approved()
        mrf = self._save(case.with_user(self.helpdesk_user).action_create_material_request(),
                         self.helpdesk_user)
        self.assertTrue(mrf.name.startswith('MRF/'), mrf.name)
        standalone = self._standalone()
        self.assertFalse(standalone.name.startswith('MRF/'))
        self.assertFalse(standalone.is_warranty_mrf)
        employee = standalone.employee_id
        vals = self.Mrf.with_user(self.helpdesk_user)._warranty_mrf_default_vals(case)
        mixed = self.Mrf.with_user(self.helpdesk_user).create([
            {'employee_id': employee.id, 'department_id': self.department.id}, vals])
        self.assertFalse(mixed[0].name.startswith('MRF/'))
        self.assertTrue(mixed[1].name.startswith('MRF/'))
        self.assertEqual(mixed[1].warranty_case_id, case)

    # ------------------------------------------------------------------ T1.5
    def test_06_link_existing(self):
        """T1.5: a New standalone request of the company is linked to the case / job / visit;
        already linked, confirmed or foreign requests are refused; links cannot be edited."""
        job = self._confirmed_job()
        standalone = self._standalone()
        number = standalone.name
        action = job.with_user(self.helpdesk_user).action_link_material_request()
        wizard = self.env['warranty.mrf.link.wizard'].with_user(self.helpdesk_user).with_context(
            **action['context']).create({'requisition_id': standalone.id})
        wizard.action_link()
        self.assertEqual((standalone.warranty_case_id, standalone.warranty_service_job_id,
                          standalone.warranty_task_id),
                         (job.warranty_case_id, job, job.visit_ids))
        self.assertEqual(standalone.name, number)
        self.assertIn('linked', job.warranty_case_id.message_ids[:1].body)
        with self.assertRaisesRegex(UserError, 'already linked'):
            standalone._warranty_link(job.warranty_case_id, job)
        confirmed = self._standalone()
        confirmed.state = 'dept_confirm'
        with self.assertRaisesRegex(UserError, 'status New'):
            confirmed._warranty_link(job.warranty_case_id, job)
        with self.assertRaisesRegex(UserError, 'cannot be changed'):
            standalone.with_user(self.helpdesk_user).write({'warranty_task_id': False})

    # ------------------------------------------------------------------ T1.6
    def test_07_estimated_cost(self):
        """T1.6: estimated unit cost from the product cost in the line UoM; cost = qty x unit
        cost; header total; the unit cost can be overridden."""
        case = self._approved()
        mrf = self._save(case.with_user(self.helpdesk_user).action_create_material_request(),
                         self.helpdesk_user, qty=2)
        line = mrf.requisition_line_ids
        self.assertEqual((line.estimated_unit_cost, line.estimated_cost, mrf.estimated_cost),
                         (18500, 37000, 37000))
        line.estimated_unit_cost = 17000
        self.assertEqual(mrf.estimated_cost, 34000)
        pipe = self.env['product.product'].create({
            'name': 'Copper Pipe', 'type': 'consu', 'standard_price': 10,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
            'uom_po_id': self.env.ref('uom.product_uom_unit').id})
        mrf.write({'requisition_line_ids': [(0, 0, {
            'product_id': pipe.id, 'description': 'Pipe', 'qty': 1,
            'uom': self.env.ref('uom.product_uom_dozen').id})]})
        self.assertEqual(mrf.requisition_line_ids[1].estimated_unit_cost, 120)
        self.assertEqual(mrf.estimated_cost, 34120)
        lot = self.env['stock.lot'].create({'name': 'PCB-001', 'product_id': self.part.id})
        line.lot_ids = lot
        with self.assertRaises(ValidationError):
            mrf.requisition_line_ids[1].lot_ids = lot

    # ------------------------------------------------------------------ T1.7
    def test_08_consistency(self):
        """T1.7: job of another case, visit of another job and company mismatch are refused."""
        job = self._confirmed_job()
        other_case = self._approved()
        Mrf = self.Mrf.with_user(self.helpdesk_user)
        vals = Mrf._warranty_mrf_default_vals(other_case)
        with self.assertRaisesRegex(ValidationError, 'does not belong'):
            Mrf.create(dict(vals, warranty_service_job_id=job.id))
        vals = Mrf._warranty_mrf_default_vals(job.warranty_case_id, job)
        other_task = self.env['project.task'].create({'name': 'Other task'})
        with self.assertRaisesRegex(ValidationError, 'not a visit'):
            Mrf.create(dict(vals, warranty_task_id=other_task.id))
        with self.assertRaisesRegex(ValidationError, 'different companies'):
            Mrf.sudo().create(dict(vals, company_id=self.other_company.id))

    # ------------------------------------------------------------------ T1.8
    def test_09_access(self):
        """T1.8: the job's technician reads (not edits) the job's requests; another technician
        does not see them; Helpdesk users see all warranty requests, not other users'
        standalone ones."""
        job = self._confirmed_job()
        mrf = self._save(job.with_user(self.helpdesk_user).action_create_material_request(),
                         self.helpdesk_user)
        self.assertEqual(self.Mrf.with_user(self.tech).search([('id', '=', mrf.id)]), mrf)
        self.assertEqual(mrf.requisition_line_ids.with_user(self.tech).read(['qty'])[0]['qty'], 1)
        with self.assertRaises(AccessError):
            mrf.with_user(self.tech).write({'reason': 'changed'})
        self.assertFalse(self.Mrf.with_user(self.other_tech).search([('id', '=', mrf.id)]))
        own = self._save(job.visit_ids.with_user(self.tech).action_warranty_create_material_request(),
                         self.tech)
        self.assertEqual(self.Mrf.with_user(self.helpdesk_user).search(
            [('id', 'in', (mrf | own).ids)]), mrf | own)
        tech_standalone = self._standalone(self.tech)
        self.assertFalse(self.Mrf.with_user(self.helpdesk_user).search(
            [('id', '=', tech_standalone.id)]))

    # ------------------------------------------------------------------ T1.10
    def test_10_standalone_unchanged(self):
        """T1.10: standalone requests have no warranty links, cost columns stay hidden and the
        vendor flow runs; the Warranty menu lists only warranty requests."""
        standalone = self._standalone()
        self.assertFalse(standalone.is_warranty_mrf)
        standalone.write({'requisition_line_ids': [(0, 0, {
            'product_id': self.part.id, 'description': 'PCB', 'qty': 1, 'uom': self.part.uom_id.id,
            'requisition_type': 'purchase',
            'partner_id': [(6, 0, self.customer.ids)]})]})
        standalone.sudo().requisition_confirm()
        self.assertEqual(standalone.state, 'dept_confirm')
        case = self._approved()
        mrf = self._save(case.with_user(self.helpdesk_user).action_create_material_request(),
                         self.helpdesk_user)
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_mrf.action_warranty_material_request')
        found = self.Mrf.search(safe_eval(action['domain']) + [('id', 'in', (mrf | standalone).ids)])
        self.assertEqual(found, mrf)

    # ------------------------------------------------------------------ views
    def test_11_views_render(self):
        """The inherited forms / lists / searches render for a Helpdesk user and a technician."""
        checks = {
            'material.purchase.requisition': ['form', 'list', 'search'],
            'warranty.case': ['form'], 'warranty.service.job': ['form'], 'project.task': ['form'],
            'helpdesk.ticket': ['form'], 'warranty.mrf.link.wizard': ['form'],
        }
        for user in (self.helpdesk_user, self.tech, self.env.user):
            for model, view_types in checks.items():
                arch = self.env[model].with_user(user).get_views(
                    [(False, view_type) for view_type in view_types])
                self.assertTrue(arch['views'])
        settings = self.env['res.config.settings'].get_views([(False, 'form')])
        self.assertIn('warranty_mrf_source_location_id', settings['views']['form']['arch'])
