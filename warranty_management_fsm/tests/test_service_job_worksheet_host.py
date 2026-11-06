import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobWorksheetHost(ServiceJobCommon):
    """Approved shared-worksheet fix: Warranty Worksheet templates hosted on the worksheet
    instance (independent answers per instance), duplicate task templates blocked."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_x_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.host@example.com'
        cls.env['hr.employee'].create({'name': 'Host Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.task_template = cls.env['worksheet.template'].create({
            'name': 'AC Task Checklist', 'res_model': 'project.task'})
        cls.instance_template = cls.env['worksheet.template'].create({
            'name': 'Per Service Checklist', 'res_model': 'warranty.job.worksheet'})
        cls.product.product_tmpl_id.warranty_worksheet_template_id = cls.instance_template

    def _confirmed(self, services=None, case_type=None):
        case = self._approved(services, case_type=case_type)
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        return job

    def _merged(self):
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        return s1 | s2, self._confirmed(s1 | s2, case_type='free_service')

    def test_91_independent_answers_same_template(self):
        """One task, one instance per service, same template, one checklist record each;
        the standard task Worksheet buttons are replaced by the instance list."""
        services, job = self._merged()
        task = job.visit_ids
        sheets = job.worksheet_ids
        self.assertEqual((len(task), len(sheets)), (1, 2))
        self.assertEqual(sheets.template_id, self.instance_template)
        self.assertTrue(task.warranty_hide_standard_worksheet)
        self.assertNotEqual(task.worksheet_template_id, self.instance_template)
        first, second = sheets
        rec1 = first.with_user(self.tech)._worksheet_record()
        rec2 = second.with_user(self.tech)._worksheet_record()
        self.assertNotEqual(rec1, rec2)
        rec1.x_comments = '<p>Indoor unit cleaned</p>'
        rec2.x_comments = '<p>Outdoor unit gas checked</p>'
        self.assertEqual((rec1.x_warranty_job_worksheet_id, rec2.x_warranty_job_worksheet_id),
                         (first, second))
        self.assertIn('Indoor', first._worksheet_existing_record().x_comments)
        self.assertIn('Outdoor', second._worksheet_existing_record().x_comments)
        action = second.with_user(self.tech).action_open_worksheet()
        self.assertEqual((action['res_id'], action['context']['default_x_warranty_job_worksheet_id']),
                         (rec2.id, second.id))

    def test_92_duplicate_task_template_blocked(self):
        """A Field Service (task) template used by several instances of one visit blocks the
        confirmation when the product has no Warranty Worksheet template (genuine conflict)."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        # the free services' own template (Part 2 snapshot) comes first
        (s1 | s2).sudo().worksheet_template_id = self.task_template
        self.product.product_tmpl_id.warranty_worksheet_template_id = self.task_template
        case = self._approved(s1 | s2, case_type='free_service')
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        with self.assertRaisesRegex(UserError, 'AC Task Checklist would be used by several'):
            job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual((job.state, job.visit_ids), ('planned', self.env['project.task']))

    def test_97_stale_task_snapshot_uses_product_template(self):
        """JOB/000045: merged services whose snapshot is a Field Service (task) template use the
        product's Warranty Worksheet template; the stored snapshots are not changed."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        (s1 | s2).sudo().worksheet_template_id = self.task_template
        job = self._confirmed(s1 | s2, case_type='free_service')
        self.assertEqual(job.state, 'confirmed')
        sheets = job.worksheet_ids
        self.assertEqual((len(sheets), sheets.template_id), (2, self.instance_template))
        self.assertEqual((s1 | s2).worksheet_template_id, self.task_template)
        first, second = sheets
        self.assertNotEqual(first.with_user(self.tech)._worksheet_record(),
                            second.with_user(self.tech)._worksheet_record())

    def test_98_single_and_explicit_templates_kept(self):
        """A single service keeps its Field Service snapshot; merged services keep their own
        Warranty Worksheet template, and different task templates are no conflict."""
        s1, s2, s3 = self.card.service_entitlement_ids.sorted('service_no')[:3]
        s1.sudo().worksheet_template_id = self.task_template
        single = self._confirmed(s1, case_type='free_service')
        self.assertEqual((single.worksheet_ids.template_id, single.visit_ids.worksheet_template_id),
                         (self.task_template, self.task_template))
        own = self.env['worksheet.template'].create({
            'name': 'Own Service Checklist', 'res_model': 'warranty.job.worksheet'})
        other_task = self.env['worksheet.template'].create({
            'name': 'Other Task Checklist', 'res_model': 'project.task'})
        s2.sudo().worksheet_template_id = own
        s3.sudo().worksheet_template_id = other_task
        case = self._approved(s2 | s3, case_type='free_service')
        lines = self._prepare(case)._warranty_worksheet_lines()
        self.assertEqual({service: template for service, __, __, template in lines},
                         {s2: own, s3: other_task})

    def test_96_single_task_template_standard(self):
        """A single instance with a Field Service (task) template keeps the standard task
        Worksheet button (approved W4)."""
        self.product.product_tmpl_id.warranty_worksheet_template_id = self.task_template
        single = self._confirmed()
        self.assertEqual(single.visit_ids.worksheet_template_id, self.task_template)
        self.assertFalse(single.visit_ids.warranty_hide_standard_worksheet)

    def test_93_required_answers_per_instance(self):
        """Complete Visit checks each instance's own checklist (required answers server-side)."""
        services, job = self._merged()
        task = job.visit_ids
        first, second = job.worksheet_ids
        view = self.env['ir.ui.view'].search([('model', '=', self.instance_template.model_id.model),
                                              ('type', '=', 'form')], limit=1)
        view.arch_db = view.arch_db.replace('<field name="x_comments"',
                                            '<field name="x_comments" required="True"')
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Work'}).save_timesheet()
        task.sudo().write({'worksheet_signature': base64.b64encode(b'sig'),
                           'worksheet_signed_by': 'Customer'})
        first.with_user(self.tech)._worksheet_record().x_comments = '<p>Done</p>'
        second.with_user(self.tech)._worksheet_record()
        with self.assertRaises(UserError) as error:
            task.with_user(self.tech).action_warranty_complete_visit()
        message = error.exception.args[0]
        self.assertIn('%s: required checklist answers missing' % second.name, message)
        self.assertNotIn('%s: required' % first.name, message)
        second._worksheet_existing_record().x_comments = '<p>Done too</p>'
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual((job.state, set(services.mapped('state'))), ('completed', {'completed'}))

    def test_94_report_shows_each_instance(self):
        """The Field Service report (signed by the customer) shows every instance checklist."""
        services, job = self._merged()
        task = job.visit_ids
        first, second = job.worksheet_ids
        first.with_user(self.tech)._worksheet_record().x_comments = '<p>Answer of service one</p>'
        second.with_user(self.tech)._worksheet_record().x_comments = '<p>Answer of service two</p>'
        checklists = self.env['warranty.job.worksheet']._warranty_report_checklists(task)
        self.assertEqual([sheet for sheet, __ in checklists[task.id]], [first, second])
        html = self.env['ir.actions.report']._render_qweb_html(
            'industry_fsm.task_custom_report', task.ids)[0].decode()
        self.assertIn('Answer of service one', html)
        self.assertIn('Answer of service two', html)
        self.assertIn(second.name, html)

    def test_95_access_and_company(self):
        """Field Service / Helpdesk users read the checklists of their company only."""
        services, job = self._merged()
        record = job.worksheet_ids[:1].with_user(self.tech)._worksheet_record()
        Model = self.env[record._name]
        self.assertTrue(Model.with_user(self.helpdesk_user).browse(record.id).read(['x_comments']))
        with self.assertRaises(AccessError):
            Model.with_user(self.foreign_user).browse(record.id).read(['x_comments'])
