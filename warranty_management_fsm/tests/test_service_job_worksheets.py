from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobWorksheets(ServiceJobCommon):
    """Phase 4.4 - worksheet instances (approved W1-W6, G9) and the customer-email fix."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_w_tech', 'industry_fsm.group_fsm_user')
        Template = cls.env['worksheet.template']
        cls.product_template = Template.create({'name': 'AC Checklist', 'res_model': 'project.task'})
        cls.service_template = Template.create({'name': 'Service Checklist',
                                                'res_model': 'project.task'})
        cls.product.product_tmpl_id.warranty_worksheet_template_id = cls.product_template

    def _confirmed(self, services=None, case_type=None):
        case = self._approved(services, case_type=case_type)
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual(job.state, 'confirmed')
        return job

    def test_41_warranty_only_single_instance(self):
        """Warranty Only: one instance for the case product (product template); the task
        keeps the standard Worksheet button on that template; both open the same record."""
        job = self._confirmed()
        sheet = job.worksheet_ids
        task = job.visit_ids
        self.assertEqual(len(sheet), 1)
        self.assertEqual((sheet.task_id, sheet.warranty_case_id, sheet.product_id,
                          sheet.template_id, sheet.state, sheet.entitlement_id),
                         (task, job.warranty_case_id, self.product, self.product_template,
                          'todo', self.env['warranty.service.entitlement']))
        self.assertEqual((task.worksheet_template_id, task.warranty_worksheet_count),
                         (self.product_template, 1))
        self.assertIn('Worksheet instances', job.message_ids[:1].body)
        action = sheet.with_user(self.tech).action_open_worksheet()
        record = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(record.x_project_task_id, task)
        standard = task.open_fsm_worksheet()
        self.assertEqual(standard['res_id'], record.id, 'standard button: the same worksheet')
        self.assertEqual(sheet.with_user(self.tech).action_open_worksheet()['res_id'], record.id)

    def test_42_merged_services_several_instances(self):
        """One instance per linked free service under one task; service template snapshot
        first; the standard Worksheet button is hidden for several instances."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        s1.sudo().worksheet_template_id = self.service_template
        job = self._confirmed(s1 | s2, case_type='free_service')
        sheets = job.worksheet_ids
        self.assertEqual(sheets.entitlement_id, s1 | s2)
        self.assertEqual(sheets.task_id, job.visit_ids)
        by_service = {sheet.entitlement_id: sheet.template_id for sheet in sheets}
        self.assertEqual(by_service[s1], self.service_template)
        self.assertEqual(by_service[s2], self.product_template)
        self.assertEqual(job.visit_ids.warranty_worksheet_count, 2)
        arch = ' '.join(self.env['project.task'].get_view(
            self.env.ref('project.view_task_form2').id, 'form')['arch'].split())
        self.assertIn('or (warranty_hide_standard_worksheet)', arch)
        self.assertTrue(job.visit_ids.warranty_hide_standard_worksheet)
        first, second = sheets
        first_record = first.action_open_worksheet()['res_id']
        self.assertNotEqual(second.action_open_worksheet()['res_id'], first_record)

    def test_43_no_template_and_no_duplicates(self):
        """W2: no template anywhere -> instance without checklist, confirmation not blocked;
        retried generation creates no duplicate."""
        self.product.product_tmpl_id.warranty_worksheet_template_id = False
        self.company._warranty_fsm_project().sudo().worksheet_template_id = False
        job = self._confirmed()
        sheet = job.worksheet_ids
        self.assertEqual((len(sheet), sheet.template_id), (1, self.env['worksheet.template']))
        with self.assertRaises(UserError):
            sheet.action_open_worksheet()
        self.assertEqual(job._warranty_create_worksheets(job.visit_ids), sheet)
        self.assertEqual(len(job.worksheet_ids), 1)

    def test_44_usage_based_and_technician_access(self):
        """Usage-based warranty: usage reading required with the card unit (blocking in 4.5);
        technicians fill readings / attachments; other companies cannot see instances."""
        job = self._confirmed()
        sheet = job.worksheet_ids
        self.assertFalse(sheet.usage_required, 'period-based: no reading required')
        sheet.unlink()
        job.warranty_card_id.sudo().write({'warranty_basis': 'usage',
                                           'usage_unit': 'operating_hours'})
        sheet = job._warranty_create_worksheets(job.visit_ids)
        self.assertEqual((sheet.usage_required, sheet.usage_unit), (True, 'operating_hours'))
        attachment = self.env['ir.attachment'].create({'name': 'report.pdf', 'raw': b'pdf'})
        sheet.with_user(self.tech).write({'current_usage': 1250.0,
                                          'attachment_ids': [(4, attachment.id)]})
        self.assertEqual(sheet.current_usage, 1250.0)
        with self.assertRaises(AccessError):
            self.env['warranty.job.worksheet'].with_user(self.tech).create(
                {'job_id': job.id, 'task_id': job.visit_ids.id})
        self.assertFalse(self.env['warranty.job.worksheet'].with_user(self.foreign_user).search(
            [('id', '=', sheet.id)]))

    def test_45_no_customer_stage_email_for_warranty_tasks(self):
        """Customer-email fix (a): the stage email template of a warranty task is not sent;
        other Field Service tasks keep the standard behaviour."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('mail.catchall.domain', 'example.com')
        ICP.set_param('mail.default.from', 'notifications')
        project = self.company._warranty_fsm_project()
        template = self.env['mail.template'].create({
            'name': 'Visit scheduled', 'model_id': self.env.ref('project.model_project_task').id,
            'subject': 'Your visit is scheduled', 'partner_to': '{{ object.partner_id.id }}'})
        stage = self.env['project.task.type'].create({
            'name': 'Warranty Planned', 'sequence': 0, 'project_ids': [(4, project.id)],
            'mail_template_id': template.id})
        self.customer.email = 'abc.hotel@example.com'
        job = self._confirmed()
        task = job.visit_ids
        # Stage email templates are posted at commit (precommit hook), as in Odoo mail tests.
        self.env.flush_all()
        self.env.cr.precommit.run()
        self.assertEqual(task.stage_id, stage)
        self.assertFalse(task.message_ids.filtered(lambda m: m.subject == 'Your visit is scheduled'))
        self.customer.email = 'abc.hotel@example.com'
        plain = self.env['project.task'].create({'name': 'Plain visit', 'project_id': project.id,
                                                 'partner_id': self.customer.id})
        self.env.flush_all()
        self.env.cr.precommit.run()
        self.assertTrue(plain.message_ids.filtered(lambda m: m.subject == 'Your visit is scheduled'))
        sent = []
        self.patch(type(self.env['project.task']), 'rating_send_request',
                   lambda tasks, *args, **kwargs: sent.append(tasks.ids))
        stage.rating_template_id = template
        (task | plain)._send_task_rating_mail()
        self.assertEqual(sent, [plain.ids])
