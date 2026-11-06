from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobVisit(ServiceJobCommon):
    """Phase 4.5 - visit start by the standard timer (V1 / V2) and usage readings (V4 / V5)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_v_tech', 'industry_fsm.group_fsm_user')
        cls.env['hr.employee'].create({'name': 'Visit Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.tech_no_employee = cls._user('job_v_tech2', 'industry_fsm.group_fsm_user')
        # The standard timer posts "Timer started at ..." as the technician (needs an email).
        (cls.tech | cls.tech_no_employee).email = 'tech@example.com'

    def _confirmed(self, services=None, case_type=None, tech=None):
        case = self._approved(services, case_type=case_type)
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': (tech or self.tech).id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual(job.state, 'confirmed')
        return job

    def _usage_job(self, limit=2000):
        job = self._confirmed()
        job.warranty_card_id.sudo().write({'warranty_basis': 'usage', 'usage_unit': 'operating_hours',
                                           'usage_limit': limit})
        job.worksheet_ids.unlink()
        sheet = job._warranty_create_worksheets(job.visit_ids)
        self.assertTrue(sheet.usage_required)
        return job, sheet

    def test_51_timer_starts_warranty_only_visit(self):
        """First timer start: job In Progress, worksheets In Progress, case stays Job Created,
        audit notes; later starts change nothing."""
        job = self._confirmed()
        task = job.visit_ids
        self.assertTrue(task.display_timesheet_timer)
        task.with_user(self.tech).action_timer_start()
        self.assertTrue(task.with_user(self.tech).user_timer_id.timer_start)
        self.assertEqual((job.state, job.worksheet_ids.state, job.warranty_case_id.state),
                         ('in_progress', 'in_progress', 'job_created'))
        self.assertIn('started by', job.message_ids[:1].body)
        self.assertIn('started by', job.warranty_case_id.message_ids[:1].body)
        logs = len(job.message_ids)
        task.with_user(self.tech).action_timer_pause()
        task.with_user(self.tech).action_timer_resume()
        task.with_user(self.tech).action_timer_start()
        self.assertFalse(job._warranty_start_visit(task))
        self.assertEqual((job.state, len(job.message_ids)), ('in_progress', logs))

    def test_52_free_services_in_progress(self):
        """Merged free services: Job Created -> In Progress at the first start."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        # several instances of one visit: no shared Field Service (task) checklist template
        self.company._warranty_fsm_project().sudo().worksheet_template_id = False
        job = self._confirmed(s1 | s2, case_type='free_service')
        self.assertEqual(set((s1 | s2).mapped('state')), {'job_created'})
        job.visit_ids.with_user(self.tech).action_timer_start()
        self.assertEqual(set((s1 | s2).mapped('state')), {'in_progress'})
        self.assertEqual(set(job.worksheet_ids.mapped('state')), {'in_progress'})
        self.assertIn('In Progress', s1.message_ids[:1].body)

    def test_53_employee_required_in_task_company(self):
        """No active employee in the task company: the warranty visit does not start; an
        ordinary Field Service task keeps the standard timer."""
        job = self._confirmed(tech=self.tech_no_employee)
        task = job.visit_ids
        with self.assertRaisesRegex(UserError, 'active employee'):
            task.with_user(self.tech_no_employee).action_timer_start()
        self.assertEqual((job.state, job.worksheet_ids.state), ('confirmed', 'todo'))
        employee = self.env['hr.employee'].create({
            'name': 'Archived', 'user_id': self.tech_no_employee.id, 'company_id': self.company.id})
        employee.action_archive()
        with self.assertRaisesRegex(UserError, 'active employee'):
            task.with_user(self.tech_no_employee).action_timer_start()
        plain = self.env['project.task'].create({
            'name': 'Plain visit', 'project_id': self.company._warranty_fsm_project().id,
            'user_ids': [(4, self.tech_no_employee.id)]})
        plain.with_user(self.tech_no_employee).action_timer_start()
        self.assertTrue(plain.with_user(self.tech_no_employee).user_timer_id.timer_start)

    def test_54_usage_reading_rules(self):
        """Reading > 0, card usage unit, not lower than the latest earlier reading of the same
        unit (the worksheet itself and other units ignored)."""
        job, sheet = self._usage_job()
        case = job.warranty_case_id
        self.assertEqual(sheet.warranty_unit_id, job.warranty_unit_id)
        case.sudo().current_usage = 500
        tech_sheet = sheet.with_user(self.tech)
        with self.assertRaisesRegex(ValidationError, 'greater than zero'):
            tech_sheet.current_usage = -5
        with self.assertRaisesRegex(ValidationError, 'usage unit'):
            tech_sheet.write({'current_usage': 900, 'usage_unit': 'km'})
        # assertRaisesRegex has no savepoint: restore the refused values.
        sheet.sudo().write({'current_usage': 0, 'usage_unit': 'operating_hours'})
        with self.assertRaisesRegex(ValidationError, 'lower than the latest reading 500'):
            tech_sheet.current_usage = 400
        tech_sheet.current_usage = 1000
        tech_sheet.current_usage = 900  # its own earlier value is not a previous reading
        other_card = self._card()
        other_case = self._create_case(self._ticket(), product_id=self.product.id)
        other_case.sudo().write({'warranty_card_id': other_card.id,
                                 'warranty_unit_id': other_card.unit_warranty_ids.id,
                                 'current_usage': 9999})
        tech_sheet.current_usage = 950  # another unit's reading is not compared
        self.assertEqual(sheet.current_usage, 950)
        self.assertEqual(sheet._previous_usage_reading(), (500, case.name))

    def test_55_usage_over_limit_warning(self):
        """A reading above the usage limit is logged on job and case, not blocked."""
        job, sheet = self._usage_job(limit=2000)
        sheet.with_user(self.tech).current_usage = 2500
        self.assertEqual(sheet.current_usage, 2500)
        self.assertIn('exceeds the usage limit', job.message_ids[:1].body)
        self.assertIn('exceeds the usage limit', job.warranty_case_id.message_ids[:1].body)
        self.assertEqual(job.warranty_case_id.state, 'job_created')
        sheet.with_user(self.tech).current_usage = 2600
