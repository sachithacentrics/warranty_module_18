from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import ServiceJobCommon

HOST = 'warranty.job.worksheet'


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestWorksheetTemplateSecurity(ServiceJobCommon):
    """Approved security fix: access to Warranty Worksheet templates (hosted on the worksheet
    instance) for real (non-superuser) users; the standard worksheet rules are unchanged."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('wst_tech', 'industry_fsm.group_fsm_user')
        cls.project_manager = cls._user('wst_project_manager', 'project.group_project_manager')
        cls.project_user = cls._user('wst_project_user', 'project.group_project_user')
        cls.admin = cls.env.ref('base.user_admin')
        cls.admin.write({'company_ids': [(4, cls.company.id)]})
        Template = cls.env['worksheet.template']
        cls.warranty_template = Template.create({
            'name': 'Warranty Checklist (company)', 'res_model': HOST,
            'company_id': cls.company.id})
        cls.task_template = Template.create({'name': 'Task Checklist (company)',
                                             'res_model': 'project.task',
                                             'company_id': cls.company.id})

    def _template(self, user, name):
        return self.env['worksheet.template'].with_user(user).with_company(self.company).create(
            {'name': name, 'res_model': HOST, 'company_id': self.company.id})

    def test_121_helpdesk_manager_manages_templates(self):
        """Helpdesk managers edit Warranty Worksheet templates; creating / deleting one generates
        / removes a model, which standard Odoo keeps for Administration / Access Rights (also for
        Field Service templates)."""
        self.warranty_template.with_user(self.helpdesk_manager).write(
            {'name': 'Renamed by HD manager'})
        self.assertEqual(self.warranty_template.name, 'Renamed by HD manager')
        with self.assertRaises(AccessError):
            self._template(self.helpdesk_manager, 'HD Manager Checklist')
        with self.assertRaises(AccessError):
            self.warranty_template.with_user(self.helpdesk_manager).unlink()

    def test_122_mitchell_admin_and_project_manager(self):
        """Mitchell Admin (administrator, Project and Helpdesk manager) creates, edits and deletes
        Warranty Worksheet templates - the reported error. A Project manager only reads them
        and keeps managing the task templates (no new permission)."""
        self.assertTrue(self.admin.has_group('project.group_project_manager'))
        template = self._template(self.admin, 'FS AC Service Checklist')
        self.assertEqual((template.res_model, bool(template.model_id)), (HOST, True))
        self.assertIn('x_warranty_job_worksheet_id', self.env[template.model_id.model]._fields)
        template.with_user(self.admin).name = 'FS AC Service Checklist v2'
        template.with_user(self.admin).unlink()
        self.assertFalse(template.exists())
        manager_template = self.warranty_template.with_user(self.project_manager)
        self.assertTrue(manager_template.read(['name']))
        with self.assertRaises(AccessError):
            manager_template.write({'name': 'PM change'})
        with self.assertRaises(AccessError):
            manager_template.unlink()
        self.task_template.with_user(self.project_manager).name = 'Task Checklist renamed'
        self.assertEqual(self.task_template.name, 'Task Checklist renamed')

    def test_123_read_only_users_and_unauthorized(self):
        """Helpdesk users and technicians read the templates they need, but do not create,
        modify or delete them; other internal users have no access."""
        for user in (self.helpdesk_user, self.tech, self.project_user):
            template = self.warranty_template.with_user(user)
            self.assertTrue(template.read(['name', 'res_model']))
            self.assertIn(self.warranty_template, self.env['worksheet.template'].with_user(user)
                          .search([('res_model', '=', HOST)]))
            with self.assertRaises(AccessError):
                template.write({'name': 'changed'})
            with self.assertRaises(AccessError):
                template.unlink()
            with self.assertRaises(AccessError):
                self._template(user, 'Not allowed')
        with self.assertRaises(AccessError):
            self.warranty_template.with_user(self.internal_user).read(['name'])
        with self.assertRaises(AccessError):
            self._template(self.internal_user, 'Not allowed')
        self.assertEqual(self.warranty_template.name, 'Warranty Checklist (company)')

    def test_124_no_unintended_permissions(self):
        """The new rule only covers warranty-hosted templates: a Helpdesk-only user gets no
        access to Field Service (task) templates; the standard rule still limits Project users
        to task / warranty templates."""
        with self.assertRaises(AccessError):
            self.task_template.with_user(self.helpdesk_user).read(['name'])
        other_host = self.env['worksheet.template'].search([
            ('res_model', 'not in', ('project.task', HOST))], limit=1)
        if other_host:
            with self.assertRaises(AccessError):
                other_host.with_user(self.project_manager).read(['name'])
        rule = self.env.ref('industry_fsm_report.ir_rule_worksheet_template_project')
        self.assertEqual((rule.active, rule.domain_force), (True, "[('res_model', '=', 'project.task')]"))

    def test_125_cross_company(self):
        """The worksheet multi-company rule still applies: users of another company neither
        see nor change the company's templates."""
        Template = self.env['worksheet.template'].with_user(self.foreign_user)
        self.assertFalse(Template.search([('id', '=', self.warranty_template.id)]))
        with self.assertRaises(AccessError):
            self.warranty_template.with_user(self.foreign_user).read(['name'])
        with self.assertRaises(AccessError):
            self.warranty_template.with_user(self.foreign_user).write({'name': 'foreign'})
        with self.assertRaises(AccessError):
            self.warranty_template.with_user(self.foreign_user).unlink()
