import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from .common import ServiceJobCommon

SIGNATURE = base64.b64encode(b'customer signature')


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobBatch(ServiceJobCommon):
    """Phase 4.9 - Complete Selected Jobs (approved B1-B10, T1)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_b_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.batch@example.com'
        cls.env['hr.employee'].create({'name': 'Batch Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        # one worksheet instance per job, no checklist: sign-off and the other 4.7 checks apply
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False
        cls.company.write({'warranty_signoff_required': True,
                           'warranty_worksheet_checklist_required': True,
                           'warranty_worksheet_attachment_required': False})

    # ------------------------------------------------------------------ helpers
    def _confirmed(self, services=None, case_type=None):
        case = self._approved(services, case_type=case_type,
                              ticket=self._ticket(warranty_product_id=self.product.id))
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        return job

    def _open_visit(self, job):
        return job.visit_ids.filtered(lambda t: t.state not in ('1_done', '1_canceled'))

    def _started(self, services=None, case_type=None):
        job = self._confirmed(services, case_type)
        self._open_visit(job).with_user(self.tech).action_timer_start()
        return job

    def _stop_timer(self, task):
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Work'}).save_timesheet()

    def _ready(self, services=None, case_type=None):
        job = self._started(services, case_type)
        task = self._open_visit(job)
        self._stop_timer(task)
        task.sudo().write({'worksheet_signature': SIGNATURE, 'worksheet_signed_by': 'Customer'})
        return job

    def _snapshot(self, job):
        job.invalidate_recordset()
        visits = job.sudo().visit_ids
        return (job.state, job.warranty_case_id.state,
                tuple(visits.mapped('state')), tuple(visits.mapped('fsm_done')),
                tuple(job.worksheet_ids.mapped('state')),
                tuple(job.entitlement_ids.mapped('state')))

    def _batch_wizard(self, jobs, user=None):
        action = jobs.with_user(user or self.helpdesk_user).action_open_batch_wizard()
        return self.env[action['res_model']].with_user(user or self.helpdesk_user).browse(
            action['res_id'])

    def _results(self, wizard):
        return {line.job_id: (line.result, line.reasons or '') for line in wizard.line_ids}

    # ------------------------------------------------------------------ tests
    def test_141_mixed_selection(self):
        """Ready jobs are completed (4.7 path, services consumed once, ticket open, batch note);
        Not Ready jobs (timer running, no sign-off, Single, on hold) keep everything."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        ready = self._ready(s1, 'free_service')
        ready_only = self._ready()
        running = self._started(s2, 'free_service')
        unsigned = self._started()
        self._stop_timer(self._open_visit(unsigned))
        single = self._ready()
        single.with_user(self.helpdesk_user).completion_mode = 'single'
        hold = self._ready()
        hold.with_user(self.tech)._warranty_set_hold('awaiting_parts', 'No PCB')
        not_ready = running | unsigned | single | hold
        before = {job: self._snapshot(job) for job in not_ready}
        used = self.card.free_services_used
        wizard = self._batch_wizard(ready | ready_only | not_ready)
        preview = self._results(wizard)
        self.assertEqual({job: preview[job][0] for job in preview}, {
            ready: 'ready', ready_only: 'ready', running: 'not_ready', unsigned: 'not_ready',
            single: 'not_ready', hold: 'not_ready'})
        self.assertIn('Stop the timer', preview[running][1])
        self.assertIn('Customer sign-off is required', preview[unsigned][1])
        self.assertIn('Completion Mode is Single', preview[single][1])
        self.assertIn('resume it first', preview[hold][1])
        self.assertEqual((wizard.ready_count, wizard.not_ready_count), (2, 4))
        self.assertEqual((ready.state, ready_only.state), ('in_progress', 'in_progress'),
                         'the preview changes nothing')
        wizard.action_complete()
        result = self._results(wizard)
        self.assertEqual((result[ready][0], result[ready_only][0]), ('completed', 'completed'))
        self.assertEqual({result[job][0] for job in not_ready}, {'skipped'})
        self.assertEqual((wizard.completed_count, wizard.skipped_count), (2, 4))
        for job in ready | ready_only:
            self.assertEqual((job.state, job.warranty_case_id.state), ('completed', 'completed'))
            self.assertEqual(job.visit_ids.warranty_visit_outcome, 'completed')
            self.assertFalse(job.helpdesk_ticket_id.fold)
            self.assertIn('batch completion', ' '.join(job.message_ids.mapped('body')))
        self.assertEqual((s1.state, self.card.free_services_used), ('completed', used + 1))
        for job in not_ready:
            self.assertEqual(self._snapshot(job), before[job], job.name)
        self.assertEqual(s2.state, 'in_progress')

    def test_142_job_states_skipped(self):
        """Draft, Planned, Confirmed, Incomplete, Rescheduled and Cancelled jobs are skipped
        with their reason and not changed."""
        draft = self._prepare(self._approved(
            ticket=self._ticket(warranty_product_id=self.product.id)))
        confirmed = self._confirmed()
        incomplete = self._started()
        self._stop_timer(self._open_visit(incomplete))
        incomplete.with_user(self.tech)._warranty_visit_not_completed(
            self._open_visit(incomplete), 'customer_unavailable', 'Not at home', 'reschedule')
        rescheduled = self._started()
        self._stop_timer(self._open_visit(rescheduled))
        rescheduled.with_user(self.helpdesk_user)._warranty_visit_not_completed(
            self._open_visit(rescheduled), 'access_issue', 'Gate closed', 'reschedule',
            {'planned_date': fields.Datetime.now() + timedelta(days=2),
             'main_technician': self.tech})
        cancelled = self._started()
        self._stop_timer(self._open_visit(cancelled))
        cancelled.with_user(self.helpdesk_user)._warranty_cancel_job('Duplicate')
        jobs = draft | confirmed | incomplete | rescheduled | cancelled
        self.assertEqual(jobs.mapped('state'), ['draft', 'confirmed', 'incomplete',
                                                 'rescheduled', 'cancelled'])
        before = {job: self._snapshot(job) for job in jobs}
        wizard = self._batch_wizard(jobs)
        reasons = self._results(wizard)
        self.assertIn('not confirmed', reasons[draft][1])
        self.assertIn('has not been started', reasons[confirmed][1])
        self.assertIn('No open visit', reasons[incomplete][1])
        self.assertIn('has not been started', reasons[rescheduled][1])
        self.assertIn('Already closed', reasons[cancelled][1])
        self.assertFalse(wizard.ready_count)
        results = jobs.with_user(self.helpdesk_user)._warranty_batch_complete()
        self.assertFalse([job for job, completed, __ in results if completed])
        for job in jobs:
            self.assertEqual(self._snapshot(job), before[job], job.name)

    def test_143_multiple_visits_current_visit_only(self):
        """A rescheduled job completes only its current open visit; the earlier attempt stays
        closed (Cancelled, outcome Rescheduled) and is not reopened."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        job = self._started(s1, 'free_service')
        first = self._open_visit(job)
        self._stop_timer(first)
        job.with_user(self.helpdesk_user)._warranty_visit_not_completed(
            first, 'customer_unavailable', 'Not at home', 'reschedule',
            {'planned_date': fields.Datetime.now() + timedelta(days=2),
             'main_technician': self.tech})
        second = self._open_visit(job)
        self.assertEqual(second.warranty_visit_no, 2)
        second.with_user(self.tech).action_timer_start()
        self._stop_timer(second)
        second.sudo().write({'worksheet_signature': SIGNATURE, 'worksheet_signed_by': 'Customer'})
        used = self.card.free_services_used
        wizard = self._batch_wizard(job)
        self.assertEqual(self._results(wizard)[job][0], 'ready')
        wizard.action_complete()
        self.assertEqual((second.state, second.fsm_done, second.warranty_visit_outcome),
                         ('1_done', True, 'completed'))
        self.assertEqual((first.state, first.fsm_done, first.warranty_visit_outcome),
                         ('1_canceled', False, 'rescheduled'))
        self.assertEqual((job.state, s1.state, self.card.free_services_used),
                         ('completed', 'completed', used + 1))

    def test_144_retry_no_double_consumption(self):
        """Completing again (same or new wizard) skips the closed job; nothing is consumed
        again."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        job = self._ready(s1, 'free_service')
        wizard = self._batch_wizard(job)
        wizard.action_complete()
        used = self.card.free_services_used
        wizard.action_complete()
        self.assertEqual(self._results(wizard)[job][0], 'skipped')
        self.assertIn('Already closed', self._results(wizard)[job][1])
        again = self._batch_wizard(job)
        self.assertEqual(again.ready_count, 0)
        self.assertEqual((job.state, s1.state, self.card.free_services_used),
                         ('completed', 'completed', used))

    def test_145_completion_mode(self):
        """New jobs are Batch Eligible; Single can be selected while the job is open, not on a
        closed job; Single jobs keep Complete Visit."""
        job = self._ready()
        self.assertEqual(job.completion_mode, 'batch')
        with Form(job.with_user(self.helpdesk_user)) as form:
            form.completion_mode = 'single'
        self.assertEqual(job.completion_mode, 'single')
        self.assertEqual(self._batch_wizard(job).ready_count, 0)
        self._open_visit(job).with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(job.state, 'completed')
        with self.assertRaisesRegex(UserError, 'cannot be changed'):
            job.with_user(self.helpdesk_user).completion_mode = 'batch'

    def test_146_access_and_companies(self):
        """Helpdesk users only (technicians and internal users refused); jobs of another
        company are not accessible."""
        job = self._ready()
        for user in (self.tech, self.internal_user):
            with self.assertRaises(AccessError):
                job.with_user(user).action_open_batch_wizard()
            with self.assertRaises(AccessError):
                job.with_user(user)._warranty_batch_complete()
        self.assertFalse(self.env['warranty.service.job'].with_user(self.foreign_user).search(
            [('id', '=', job.id)]))
        results = job.with_user(self.foreign_user)._warranty_batch_complete()
        self.assertEqual((results[0][1], results[0][2]), (False, ['No access to this service job.']))
        self.assertEqual(job.state, 'in_progress')
        self.assertTrue(self.env['warranty.service.job'].get_view(
            view_type='list')['arch'].count('action_open_batch_wizard'))

    def test_147_technical_error_rolls_back_batch(self):
        """T1: an unexpected technical error stops the batch; the transaction is rolled back
        (also the jobs completed before it in the same batch); nothing is consumed."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        first = self._ready(s1, 'free_service')
        second = self._ready(s2, 'free_service')
        used = self.card.free_services_used
        original = type(second)._warranty_log_completion

        def failing(job, *args, **kwargs):
            if job == second:
                raise ValueError('technical failure')
            return original(job, *args, **kwargs)
        wizard = self._batch_wizard(first | second)
        with patch.object(type(second), '_warranty_log_completion', failing):
            with self.assertRaisesRegex(ValueError, 'technical failure'):
                with self.env.cr.savepoint():  # the request transaction
                    wizard.action_complete()
        self.env.invalidate_all()
        for job, service in ((first, s1), (second, s2)):
            self.assertEqual((job.state, service.state, self._open_visit(job).fsm_done),
                             ('in_progress', 'in_progress', False))
        self.assertEqual(self.card.free_services_used, used)
