from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobHold(ServiceJobCommon):
    """Phase 4.6 - Awaiting Parts / Workshop Repair / Resume Job (approved M1-M8)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_h_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.hold@example.com'
        cls.env['hr.employee'].create({'name': 'Hold Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})

    def _started(self, services=None, case_type=None):
        case = self._approved(services, case_type=case_type)
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        job.visit_ids.with_user(self.tech).action_timer_start()
        self.assertEqual(job.state, 'in_progress')
        return job

    def _apply(self, job, action, reason, user):
        wizard_action = job.with_user(user).with_context(
            warranty_hold_action=action).action_open_hold_wizard()
        with Form(self.env[wizard_action['res_model']].with_user(user).with_context(
                wizard_action['context'])) as form:
            if reason is not None:
                form.reason = reason
        return form.record.action_apply()

    def test_71_awaiting_parts_and_resume_warranty_only(self):
        """Technician: In Progress -> Awaiting Parts -> In Progress with reasons; notes on job
        and case; case status, visit, timer and worksheets unchanged."""
        job = self._started()
        task, case = job.visit_ids, job.warranty_case_id
        timer = task.with_user(self.tech).user_timer_id
        self._apply(job, 'awaiting_parts', 'Compressor not in stock', self.tech)
        self.assertEqual((job.state, case.state), ('awaiting_parts', 'job_created'))
        self.assertIn('Compressor not in stock', job.message_ids[:1].body)
        self.assertIn('Awaiting Parts', case.message_ids[:1].body)
        self.assertEqual((task.state, task.fsm_done, job.worksheet_ids.state),
                         ('01_in_progress', False, 'in_progress'))
        self.assertEqual(task.with_user(self.tech).user_timer_id, timer)
        self._apply(job, 'resume', 'Parts received', self.tech)
        self.assertEqual((job.state, case.state), ('in_progress', 'job_created'))
        self.assertIn('Parts received', case.message_ids[:1].body)

    def test_72_workshop_free_services_open(self):
        """Helpdesk user: Workshop; free services stay In Progress (not consumed)."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        # several instances of one visit: no shared Field Service (task) checklist template
        self.company._warranty_fsm_project().sudo().worksheet_template_id = False
        job = self._started(s1 | s2, case_type='free_service')
        balance = self.card.free_service_balance if 'free_service_balance' in self.card else None
        self._apply(job, 'workshop', 'Unit taken to the workshop', self.helpdesk_user)
        self.assertEqual(job.state, 'workshop')
        self.assertEqual(set((s1 | s2).mapped('state')), {'in_progress'})
        if balance is not None:
            self.assertEqual(self.card.free_service_balance, balance)
        self._apply(job, 'resume', 'Repaired unit back on site', self.helpdesk_user)
        self.assertEqual(job.state, 'in_progress')

    def test_73_invalid_transitions_and_reason(self):
        """Hold only from In Progress, resume only from a hold, no double hold; a reason is
        required; direct status writes (UI / API, any context) are refused."""
        job = self._started()
        with self.assertRaisesRegex(UserError, 'can be resumed'):
            job.with_user(self.tech)._warranty_set_hold('resume', 'x')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            job.with_user(self.tech)._warranty_set_hold('awaiting_parts', '   ')
        with self.assertRaises(AssertionError):  # the wizard form requires the reason
            self._apply(job, 'awaiting_parts', None, self.tech)
        job.with_user(self.tech)._warranty_set_hold('awaiting_parts', 'No stock')
        for action in ('awaiting_parts', 'workshop'):
            with self.assertRaisesRegex(UserError, 'Only service jobs In Progress'):
                job.with_user(self.tech)._warranty_set_hold(action, 'again')
        for user in (self.tech, self.helpdesk_user):
            for context in ({}, {'warranty_hold_marker': True}):
                with self.assertRaisesRegex(UserError, 'Resume Job'):
                    job.with_user(user).with_context(**context).write({'state': 'in_progress'})
        with self.assertRaisesRegex(UserError, 'Resume Job'):
            job.sudo().write({'state': 'workshop'})
        self.assertEqual(job.state, 'awaiting_parts')
        job.with_user(self.tech)._warranty_set_hold('resume', 'Parts received')
        with self.assertRaisesRegex(UserError, 'Resume Job'):
            job.with_user(self.helpdesk_user).write({'state': 'awaiting_parts'})
        self.assertEqual(job.state, 'in_progress')

    def test_74_access_and_company(self):
        """Only Field Service / Helpdesk users; other companies do not see the job."""
        job = self._started()
        with self.assertRaises(AccessError):
            job.with_user(self.internal_user)._warranty_set_hold('awaiting_parts', 'x')
        with self.assertRaises(AccessError):
            job.with_user(self.foreign_user)._warranty_set_hold('awaiting_parts', 'x')
        self.assertEqual(job.state, 'in_progress')

    def test_75_completion_blocked_while_on_hold(self):
        """The reserved completion path refuses while Awaiting Parts / Workshop; the direct
        task lock is unchanged; after Resume the block is gone."""
        job = self._started()
        task = job.visit_ids
        task.with_user(self.tech).action_timer_stop()
        job.with_user(self.tech)._warranty_set_hold('workshop', 'Workshop')
        self.assertTrue(job._warranty_completion_blockers())
        with self.assertRaisesRegex(UserError, 'resume it first'):
            task._warranty_close_visits({'fsm_done': True, 'state': '1_done'})
        with self.assertRaisesRegex(UserError, 'cannot be marked Done or Cancelled directly'):
            task.with_user(self.tech).write({'state': '1_done'})
        self.assertEqual((task.state, task.fsm_done), ('01_in_progress', False))
        job.with_user(self.tech)._warranty_set_hold('resume', 'Back')
        self.assertFalse(job._warranty_completion_blockers())
