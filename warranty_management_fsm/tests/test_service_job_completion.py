import base64
from datetime import timedelta
from unittest.mock import patch

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import ServiceJobCommon

SIGNATURE = base64.b64encode(b'customer signature')


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobCompletion(ServiceJobCommon):
    """Phase 4.7 - Complete Visit (approved K1-K10)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_c_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.complete@example.com'
        cls.env['hr.employee'].create({'name': 'Complete Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.checklist = cls.env['worksheet.template'].create({
            'name': 'Completion Checklist', 'res_model': 'project.task'})
        cls.product.product_tmpl_id.warranty_worksheet_template_id = cls.checklist
        # Merged services of one visit with one checklist design: Warranty Worksheet template.
        cls.instance_template = cls.env['worksheet.template'].create({
            'name': 'Per Service Checklist', 'res_model': 'warranty.job.worksheet'})
        cls.company.write({'warranty_signoff_required': True,
                           'warranty_worksheet_checklist_required': True,
                           'warranty_worksheet_attachment_required': False})

    # ------------------------------------------------------------------ helpers
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

    def _started(self, services=None, case_type=None):
        job = self._confirmed(services, case_type)
        job.visit_ids.with_user(self.tech).action_timer_start()
        self.assertEqual(job.state, 'in_progress')
        return job

    def _stop_timer(self, task):
        action = task.with_user(self.tech).action_timer_stop()
        wizard = self.env[action['res_model']].with_user(self.tech).with_context(
            action['context']).create({'time_spent': 1.0, 'description': 'Service work'})
        wizard.save_timesheet()
        self.assertFalse(task.with_user(self.tech).user_timer_id)

    def _fill(self, job, comment='<p>Unit checked</p>'):
        for sheet in job.worksheet_ids:
            sheet.with_user(self.tech)._worksheet_record().x_comments = comment

    def _sign(self, task):
        # As the standard Sign Report (portal controller, sudo).
        task.sudo().write({'worksheet_signature': SIGNATURE, 'worksheet_signed_by': 'Customer'})

    def _ready(self, job):
        self._fill(job)
        self._stop_timer(job.visit_ids)
        self._sign(job.visit_ids)

    def _assert_note(self, record, *texts):
        bodies = ' '.join(record.message_ids.mapped('body'))
        for text in texts:
            self.assertIn(text, bodies)

    def _complete(self, job, user=None):
        return job.visit_ids.with_user(user or self.tech).action_warranty_complete_visit()

    def _assert_not_completed(self, job, services=None):
        self.env.invalidate_all()
        task = job.visit_ids
        self.assertEqual((job.state, job.warranty_case_id.state), ('in_progress', 'job_created'))
        self.assertEqual((task.fsm_done, task.state, task.warranty_visit_outcome),
                         (False, '01_in_progress', False))
        self.assertEqual(set(job.worksheet_ids.mapped('state')), {'in_progress'})
        if services:
            self.assertEqual(set(services.mapped('state')), {'in_progress'})

    # ------------------------------------------------------------------ tests
    def test_81_warranty_only_completion(self):
        """Technician: visit Done (outcome Completed), worksheets / job / case Completed,
        ticket open, timesheets unchanged, history notes on job, case and card."""
        job = self._started()
        task, case = job.visit_ids, job.warranty_case_id
        self._ready(job)
        timesheets = task.sudo().timesheet_ids
        ticket_stage = case.helpdesk_ticket_id.stage_id
        self.assertTrue(self._complete(job))
        self.assertEqual((task.state, task.fsm_done, task.warranty_visit_outcome),
                         ('1_done', True, 'completed'))
        self.assertEqual((job.state, case.state, job.worksheet_ids.state),
                         ('completed', 'completed', 'completed'))
        self.assertEqual(case.helpdesk_ticket_id.stage_id, ticket_stage)
        self.assertFalse(case.helpdesk_ticket_id.fold)
        self.assertEqual(task.sudo().timesheet_ids, timesheets)
        for record in (job, case, job.warranty_card_id):
            self._assert_note(record, 'completed by', 'nothing consumed',
                              'Customer sign-off: Customer')

    def test_82_free_services_consumed_once(self):
        """Helpdesk user: merged free services Completed and consumed once (Used / Balance via
        Part 2); a retry is refused and consumes nothing."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        (s1 | s2).sudo().worksheet_template_id = self.instance_template
        job = self._started(s1 | s2, case_type='free_service')
        card = self.card
        used, balance = card.free_services_used, card.free_services_balance
        self._ready(job)
        self._complete(job, self.helpdesk_user)
        self.assertEqual(set((s1 | s2).mapped('state')), {'completed'})
        self.assertEqual(set((s1 | s2).mapped('merge_status')), {'completed'})
        self.assertEqual((card.free_services_used, card.free_services_balance),
                         (used + 2, balance - 2))
        self._assert_note(s1, 'Completed and consumed')
        self._assert_note(card, 'Free services consumed')
        # same Warranty Worksheet template on one visit: one checklist record per instance
        self.assertEqual(len(set(job.worksheet_ids.mapped('worksheet_res_id'))), 2)
        with self.assertRaisesRegex(UserError, 'already closed'):
            self._complete(job)
        with self.assertRaisesRegex(UserError, 'already closed'):
            job._warranty_complete_visit(job.visit_ids)
        self.assertEqual((card.free_services_used, card.free_services_balance),
                         (used + 2, balance - 2))

    def test_83_requirements_listed_and_nothing_changed(self):
        """Running timer, no sign-off, checklist never opened, missing attachment and usage
        reading: all listed at once; nothing is changed. Hold and not started are refused."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        job = self._started(s1, case_type='free_service')
        job.warranty_card_id.sudo().write({'warranty_basis': 'usage',
                                           'usage_unit': 'operating_hours', 'usage_limit': 5000})
        job.worksheet_ids.sudo().usage_required = True
        self.company.warranty_worksheet_attachment_required = True
        with self.assertRaises(UserError) as error:
            self._complete(job)
        message = error.exception.args[0]
        for text in ('Stop the timer', 'Customer sign-off is required',
                     'checklist has not been filled in', 'at least one attachment',
                     'usage reading and its unit are required'):
            self.assertIn(text, message)
        self._assert_not_completed(job, s1)
        # never opened: the checklist record was not created by the check
        self.assertFalse(job.worksheet_ids.worksheet_res_id)
        job.with_user(self.tech)._warranty_set_hold('awaiting_parts', 'No stock')
        with self.assertRaisesRegex(UserError, 'resume it first'):
            self._complete(job)
        self.assertEqual(job.state, 'awaiting_parts')

    def test_84_checklist_answers_and_settings(self):
        """Required answers of the worksheet form are checked server-side (also when written by
        API); an empty checklist has no answer; settings switch the checks; usage reading is
        kept on the worksheet only."""
        job = self._started()
        task = job.visit_ids
        sheet = job.worksheet_ids
        view = self.env['ir.ui.view'].search([('model', '=', self.checklist.model_id.model),
                                              ('type', '=', 'form')], limit=1)
        view.arch_db = view.arch_db.replace('<field name="x_comments"',
                                            '<field name="x_comments" required="True"')
        self._stop_timer(task)
        self._sign(task)
        record = sheet.with_user(self.tech)._worksheet_record()
        with self.assertRaisesRegex(UserError, 'required checklist answers missing: Comments'):
            self._complete(job)
        # conditional expression evaluated on the record (x_name: the task name)
        view.arch_db = view.arch_db.replace('required="True"', 'required="x_name"')
        with self.assertRaisesRegex(UserError, 'required checklist answers missing'):
            self._complete(job)
        view.arch_db = view.arch_db.replace('required="x_name"', 'required="not x_name"')
        with self.assertRaisesRegex(UserError, 'checklist has no answer'):
            self._complete(job)
        record.x_comments = '<p><br></p>'
        with self.assertRaisesRegex(UserError, 'checklist has no answer'):
            self._complete(job)
        self.company.write({'warranty_worksheet_checklist_required': False,
                            'warranty_worksheet_attachment_required': True})
        with self.assertRaisesRegex(UserError, 'at least one attachment'):
            self._complete(job)
        sheet.sudo().attachment_ids = [(0, 0, {'name': 'report.pdf', 'datas': SIGNATURE})]
        self._complete(job)
        self.assertEqual(job.state, 'completed')

    def test_85_usage_reading_and_signoff_setting(self):
        """Usage-based card: a valid reading is required and logged (K9: not written to the
        card / unit / case); sign-off not required by the setting."""
        job = self._started()
        case = job.warranty_case_id
        job.warranty_card_id.sudo().write({'warranty_basis': 'usage',
                                           'usage_unit': 'operating_hours', 'usage_limit': 5000})
        sheet = job.worksheet_ids
        sheet.sudo().write({'usage_required': True, 'usage_unit': 'operating_hours'})
        self.company.warranty_signoff_required = False
        self._fill(job)
        self._stop_timer(job.visit_ids)
        case.sudo().current_usage = 300
        with self.assertRaisesRegex(UserError, 'usage reading and its unit are required'):
            self._complete(job)
        sheet.with_user(self.tech).current_usage = 450
        self._complete(job)
        self.assertEqual((job.state, sheet.state, sheet.current_usage), ('completed', 'completed', 450))
        self.assertEqual(case.current_usage, 300)
        self._assert_note(job, 'Usage reading', '450.0', 'Customer sign-off: not required')

    def test_86_no_bypass(self):
        """Direct status / outcome / sign-off writes (UI, API, context flag, sudo) are refused;
        Mark as done stays refused."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        job = self._started(s1, case_type='free_service')
        task, case, sheet = job.visit_ids, job.warranty_case_id, job.worksheet_ids
        flags = ({}, {'warranty_completion_marker': True}, {'warranty_close_marker': True})
        for context in flags:
            for user in (self.tech, self.helpdesk_user):
                with self.assertRaisesRegex(UserError, 'Complete Visit'):
                    job.with_user(user).with_context(**context).write({'state': 'completed'})
                with self.assertRaisesRegex(UserError, 'Complete Visit'):
                    sheet.with_user(user).with_context(**context).write({'state': 'completed'})
                with self.assertRaisesRegex(UserError, 'Complete Visit'):
                    task.with_user(user).with_context(**context).write(
                        {'warranty_visit_outcome': 'completed'})
            with self.assertRaisesRegex(UserError, 'Complete Visit'):
                s1.with_user(self.helpdesk_user).with_context(**context).write(
                    {'state': 'completed'})
            with self.assertRaisesRegex(UserError, 'Complete Visit'):
                s1.with_context(**context).write({'merge_status': 'completed'})
            with self.assertRaisesRegex(UserError, 'Complete Visit'):
                case.with_user(self.helpdesk_user).with_context(**context).write(
                    {'state': 'completed'})
        for record in (job, sheet, case):
            with self.assertRaisesRegex(UserError, 'Complete Visit'):
                record.sudo().write({'state': 'completed'})
        with self.assertRaisesRegex(UserError, 'Sign Report'):
            task.with_user(self.tech).write({'worksheet_signature': SIGNATURE})
        with self.assertRaisesRegex(UserError, 'cannot be marked Done or Cancelled directly'):
            task.with_user(self.tech).action_fsm_validate()
        self._assert_not_completed(job, s1)

    def test_87_atomic(self):
        """A failure after the first completion step leaves nothing completed or consumed."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        job = self._started(s1, case_type='free_service')
        self._ready(job)
        used = self.card.free_services_used
        with patch.object(type(job), '_warranty_log_completion',
                          side_effect=UserError('history failure')):
            with self.assertRaisesRegex(UserError, 'history failure'):
                self._complete(job)
        self._assert_not_completed(job, s1)
        self.assertEqual(self.card.free_services_used, used)
        self._complete(job)
        self.assertEqual((job.state, s1.state, self.card.free_services_used),
                         ('completed', 'completed', used + 1))

    def test_88_access_and_buttons(self):
        """Other users / companies are refused; a visit that was not started is refused;
        Complete Visit replaces Mark as done on warranty visits only."""
        job = self._confirmed()
        with self.assertRaises(AccessError):
            job.with_user(self.internal_user)._warranty_complete_visit(job.visit_ids)
        with self.assertRaises(AccessError):
            job.with_user(self.foreign_user)._warranty_complete_visit(job.visit_ids)
        with self.assertRaisesRegex(UserError, 'has not been started'):
            self._complete(job)
        self.assertEqual(job.state, 'confirmed')
        arch = etree.fromstring(self.env['project.task'].get_view(view_type='form')['arch'])
        self.assertTrue(arch.xpath("//button[@name='action_warranty_complete_visit']"))
        for button in arch.xpath("//button[@name='action_fsm_validate']"):
            self.assertIn('warranty_is_visit', button.get('invisible'))
