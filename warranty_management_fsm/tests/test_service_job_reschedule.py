from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.warranty_management_fsm.models.warranty_service_job import visit_outcome

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobReschedule(ServiceJobCommon):
    """Phase 4.8 - visit not completed, reschedule, follow-up and cancellation (approved
    L1-L10, R5, R6)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_r_tech', 'industry_fsm.group_fsm_user')
        cls.tech2 = cls._user('job_r_tech2', 'industry_fsm.group_fsm_user')
        (cls.tech | cls.tech2).email = 'tech.reschedule@example.com'
        for user in cls.tech | cls.tech2:
            cls.env['hr.employee'].create({'name': user.name, 'user_id': user.id,
                                           'company_id': cls.company.id})
        # several instances of one visit: no shared Field Service (task) checklist template
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False

    # ------------------------------------------------------------------ helpers
    def _confirmed(self, services=None, case_type=None):
        case = self._approved(services, case_type=case_type)
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        return job

    def _started(self, services=None, case_type=None):
        job = self._confirmed(services, case_type)
        job.visit_ids.with_user(self.tech).action_timer_start()
        self.assertEqual(job.state, 'in_progress')
        return job

    def _stop_timer(self, task, user=None):
        user = user or self.tech
        action = task.with_user(user).action_timer_stop()
        self.env[action['res_model']].with_user(user).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Visit attempt'}).save_timesheet()

    def _not_completed(self, job, reason='customer_unavailable', action='reschedule',
                       user=None, notes='Customer not at home', **planning):
        task = job.visit_ids.filtered(lambda t: t.state not in ('1_done', '1_canceled'))
        with Form(self.env['warranty.visit.noncompletion.wizard'].with_user(user or self.tech)
                  .with_context(default_task_id=task.id)) as form:
            form.reason = reason
            form.next_action = action
            form.notes = notes
            for name, value in planning.items():
                setattr(form, name, value)
        form.record.action_apply()
        return task

    def _plan(self, job, days=3, main=None):
        with Form(self.env['warranty.service.job.plan.wizard'].with_user(self.helpdesk_user)
                  .with_context(default_job_id=job.id)) as form:
            form.planned_date = fields.Datetime.now() + timedelta(days=days)
            form.main_technician_id = main or self.tech2
        form.record.action_apply()
        return job.visit_ids.sorted('warranty_visit_no')[-1]

    def _notes(self, record):
        return ' '.join(record.message_ids.mapped('body'))

    # ------------------------------------------------------------------ tests
    def test_101_reschedule_requested_by_technician(self):
        """Technician: visit closed (Cancelled, not Done) with outcome / reason / notes; job
        Incomplete; free services open and not consumed; case and ticket unchanged; Helpdesk
        To-Do instead of a customer notification."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        job = self._started(s1 | s2, case_type='free_service')
        task, case = job.visit_ids, job.warranty_case_id
        used = self.card.free_services_used
        with self.assertRaisesRegex(UserError, 'Stop the timer'):
            self._not_completed(job)
        self._stop_timer(task)
        self._not_completed(job)
        self.assertEqual((task.state, task.fsm_done), ('1_canceled', False))
        self.assertEqual((task.warranty_visit_outcome, task.warranty_noncompletion_reason,
                          task.warranty_noncompletion_notes),
                         ('rescheduled', 'customer_unavailable', 'Customer not at home'))
        self.assertEqual((job.state, case.state), ('incomplete', 'job_created'))
        self.assertEqual(set((s1 | s2).mapped('state')), {'in_progress'})
        self.assertEqual(set((s1 | s2).mapped('merge_status')), {'merged'})
        self.assertEqual(self.card.free_services_used, used)
        self.assertFalse(case.helpdesk_ticket_id.fold)
        todo = job.activity_ids.filtered(lambda a: 'Plan the next visit' in a.summary)
        self.assertEqual(len(todo), 1)
        self.assertIn('no automatic customer notification', todo.note)
        for record in (job, case, s1, self.card):
            self.assertIn('not completed - reported by', self._notes(record))
        with self.assertRaises(AccessError):  # L9: technicians do not plan the next visit
            job.with_user(self.tech)._warranty_plan_next_visit(
                fields.Datetime.now() + timedelta(days=2), self.tech)

    def test_102_plan_next_visit_and_complete(self):
        """Helpdesk user plans the next visit: new linked visit (number 2, High priority, same
        services, new worksheets), previous attempt kept; job Rescheduled -> In Progress ->
        Completed; free services consumed once (only now); reschedule counts."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        job = self._started(s1, case_type='free_service')
        first = job.visit_ids
        first_date, first_users = first.planned_date_begin, first.user_ids
        self._stop_timer(first)
        self._not_completed(job)
        reschedule_before = s1.reschedule_count
        second = self._plan(job)
        self.assertEqual((job.state, job.reschedule_count), ('rescheduled', 1))
        self.assertEqual((second.warranty_visit_no, second.priority, second.user_ids),
                         (2, '1', self.tech2))
        self.assertEqual(second.warranty_entitlement_ids, s1)
        self.assertEqual((first.planned_date_begin, first.user_ids, first.warranty_visit_outcome),
                         (first_date, first_users, 'rescheduled'))
        new_sheets = job.worksheet_ids.filtered(lambda sheet: sheet.task_id == second)
        self.assertEqual(new_sheets.mapped('state'), ['todo'])
        self.assertEqual(s1.reschedule_count, reschedule_before + 1)
        self.assertFalse(job.activity_ids.filtered(lambda a: 'Plan the next visit' in a.summary))
        self.assertTrue(job.activity_ids.filtered(lambda a: 'Inform the customer' in a.summary))
        self.assertEqual(s1.state, 'in_progress')
        second.with_user(self.tech2).action_timer_start()
        self.assertEqual((job.state, new_sheets.state), ('in_progress', 'in_progress'))
        self._stop_timer(second, self.tech2)
        self.company.warranty_signoff_required = False
        self.company.warranty_worksheet_checklist_required = False
        used = self.card.free_services_used
        second.with_user(self.tech2).action_warranty_complete_visit()
        self.assertEqual((job.state, s1.state, self.card.free_services_used),
                         ('completed', 'completed', used + 1))
        self.assertEqual(first.warranty_visit_outcome, 'rescheduled')

    def test_102b_plan_next_visit_past_date(self):
        """D4 revised: Plan Next Visit accepts a past date (retrospective entry); the previous
        visit keeps its date and outcome; history shows the previous planned date."""
        job = self._started()
        first = job.visit_ids
        first_date = first.planned_date_begin
        previous = job.planned_date
        self._stop_timer(first)
        self._not_completed(job)
        second = self._plan(job, days=-2)
        self.assertEqual((job.state, second.warranty_visit_no), ('rescheduled', 2))
        self.assertLess(job.planned_date, fields.Datetime.now())
        self.assertEqual(second.planned_date_begin, job.planned_date)
        self.assertEqual((first.planned_date_begin, first.warranty_visit_outcome),
                         (first_date, 'rescheduled'))
        self.assertIn('previous planned date %s' % fields.Datetime.to_string(previous),
                      self._notes(job))

    def test_103_follow_up_outcomes(self):
        """L2 option B / L6: follow-up keeps the job Incomplete (not completed, nothing
        consumed); outcome from the reason; Complete Visit is refused on the closed visit."""
        self.assertEqual(visit_outcome('reschedule', 'awaiting_parts'), 'rescheduled')
        self.assertEqual(visit_outcome('cancel', 'customer_unavailable'), 'cancelled')
        self.assertEqual(visit_outcome('followup', 'customer_unavailable'), 'customer_not_available')
        self.assertEqual(visit_outcome('followup', 'awaiting_parts'), 'part_pending')
        self.assertEqual(visit_outcome('followup', 'technical_escalation'), 'followup_required')
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        job = self._started(s1, case_type='free_service')
        task = job.visit_ids
        self._stop_timer(task)
        self._not_completed(job, reason='awaiting_parts', action='followup',
                            notes='Compressor to be ordered')
        self.assertEqual((task.warranty_visit_outcome, task.fsm_done, job.state, s1.state),
                         ('part_pending', False, 'incomplete', 'in_progress'))
        with self.assertRaisesRegex(UserError, 'already closed'):
            task.with_user(self.tech).action_warranty_complete_visit()
        with self.assertRaisesRegex(UserError, 'already closed'):
            job.with_user(self.tech)._warranty_visit_not_completed(task, 'other', 'again',
                                                                   'followup')
        self.assertEqual(job.state, 'incomplete')

    def test_104_hold_then_reschedule_keeps_hold_history(self):
        """L8: a job Awaiting Parts can be rescheduled; the hold notes stay."""
        job = self._started()
        self._stop_timer(job.visit_ids)
        job.with_user(self.tech)._warranty_set_hold('awaiting_parts', 'PCB out of stock')
        self._not_completed(job, reason='awaiting_parts', action='reschedule',
                            notes='Wait for the PCB')
        self.assertEqual(job.state, 'incomplete')
        notes = self._notes(job)
        self.assertIn('PCB out of stock', notes)
        self.assertIn('Awaiting Parts -&gt; Incomplete', notes)

    def test_105_cancel_from_visit_releases_services(self):
        """L5: Cancel: job Cancelled, services back to their status before the job, Not Merged,
        not consumed; case back to Approved; visit outcome Cancelled."""
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        before = {s: s.state for s in s1 | s2}
        job = self._started(s1 | s2, case_type='free_service')
        used = self.card.free_services_used
        self._stop_timer(job.visit_ids)
        task = self._not_completed(job, reason='other', action='cancel',
                                   notes='Customer sold the unit')
        self.assertEqual((job.state, job.cancel_reason, job.warranty_case_id.state),
                         ('cancelled', 'Customer sold the unit', 'approved'))
        self.assertEqual((task.state, task.warranty_visit_outcome), ('1_canceled', 'cancelled'))
        for service in s1 | s2:
            self.assertEqual((service.state, service.merge_status),
                             (before[service], 'not_merged'))
        self.assertEqual(self.card.free_services_used, used)
        self.assertIn('released, not consumed', self._notes(job.warranty_case_id))

    def test_106_cancel_job(self):
        """L7: Cancel Job (Helpdesk users, required reason) on a Rescheduled job cancels the
        open next visit; technicians cannot; a cancelled job is not cancelled again."""
        job = self._started()
        self._stop_timer(job.visit_ids)
        self._not_completed(job, user=self.helpdesk_user, planned_date=fields.Datetime.now()
                            + timedelta(days=2), main_technician_id=self.tech)
        self.assertEqual(job.state, 'rescheduled')
        second = job.visit_ids.sorted('warranty_visit_no')[-1]
        with self.assertRaises(AccessError):
            job.with_user(self.tech)._warranty_cancel_job('No')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            job.with_user(self.helpdesk_user)._warranty_cancel_job('  ')
        with Form(self.env['warranty.service.job.cancel.wizard'].with_user(self.helpdesk_user)
                  .with_context(default_job_id=job.id)) as form:
            form.reason = 'Duplicate request'
        form.record.action_apply()
        self.assertEqual((job.state, second.state, second.warranty_visit_outcome),
                         ('cancelled', '1_canceled', 'cancelled'))
        self.assertEqual(job.warranty_case_id.state, 'approved')
        with self.assertRaisesRegex(UserError, 'Draft / Planned jobs use Cancel'):
            job.with_user(self.helpdesk_user)._warranty_cancel_job('again')

    def test_107_history_locked_and_no_bypass(self):
        """L3 / L10: a closed visit's date, technicians, status, outcome, reason, timesheets
        and worksheets are kept; the new job statuses cannot be written directly."""
        job = self._started()
        task = job.visit_ids
        self._stop_timer(task)
        self._not_completed(job)
        locked = {'planned_date_begin': fields.Datetime.now() + timedelta(days=9),
                  'user_ids': [(6, 0, self.tech2.ids)], 'state': '01_in_progress',
                  'warranty_noncompletion_reason': 'other'}
        for name, value in locked.items():
            with self.assertRaisesRegex(UserError, 'kept as visit history|warranty completion'):
                task.with_user(self.tech).write({name: value})
            with self.assertRaisesRegex(UserError, 'kept as visit history|warranty completion'):
                task.sudo().write({name: value})
        timesheet = task.sudo().timesheet_ids
        with self.assertRaisesRegex(UserError, 'kept as visit history'):
            timesheet.with_user(self.tech).unit_amount = 5
        with self.assertRaisesRegex(UserError, 'kept as visit history'):
            timesheet.sudo().unlink()
        with self.assertRaisesRegex(UserError, 'kept as visit history'):
            job.worksheet_ids.with_user(self.tech).notes = 'changed'
        for state in ('in_progress', 'rescheduled', 'cancelled'):
            for user_job in (job.with_user(self.helpdesk_user), job.sudo(),
                             job.with_context(warranty_visit_marker=True)):
                with self.assertRaisesRegex(UserError, 'Plan Next Visit|Visit Not Completed'):
                    user_job.write({'state': state})
        self.assertEqual(job.state, 'incomplete')

    def test_108_atomic(self):
        """A failure inside the non-completion leaves the visit, job and services unchanged."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        job = self._started(s1, case_type='free_service')
        self._stop_timer(job.visit_ids)
        with patch.object(type(job), '_warranty_history', side_effect=UserError('history failure')):
            with self.assertRaisesRegex(UserError, 'history failure'):
                self._not_completed(job)
        self.env.invalidate_all()
        task = job.visit_ids
        self.assertEqual((task.state, task.warranty_visit_outcome, job.state, s1.state),
                         ('01_in_progress', False, 'in_progress', 'in_progress'))

    def test_109_access_and_buttons(self):
        """Other users / companies are refused; buttons on task and job."""
        job = self._started()
        self._stop_timer(job.visit_ids)
        for user in (self.internal_user, self.foreign_user):
            with self.assertRaises(AccessError):
                job.with_user(user)._warranty_visit_not_completed(
                    job.visit_ids, 'other', 'x', 'followup')
        self.assertEqual(job.state, 'in_progress')
        task_arch = self.env['project.task'].get_view(view_type='form')['arch']
        self.assertIn('action_warranty_visit_not_completed', task_arch)
        job_arch = self.env['warranty.service.job'].get_view(view_type='form')['arch']
        self.assertIn('action_open_plan_wizard', job_arch)
        self.assertIn('action_open_cancel_wizard', job_arch)
