from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation
from odoo.addons.warranty_management_helpdesk.models.warranty_service_date_exception import (
    _EXCEPTION_MARKER)

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestFlexibleServiceDates(ServiceJobCommon):
    """Flexible service dates (BA-approved enhancement F1-F10 / K1-K8, 2026-10-24)."""

    check_service_windows = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy.write({'grace_period_days': 30, 'service_due_alert_days': 7})
        cls.tech = cls._user('wfd_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.flex@example.com'
        cls.env['hr.employee'].create({'name': 'Flex Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.manager_b = cls._user('wfd_manager_b', 'helpdesk.group_helpdesk_manager')
        cls.helpdesk_manager.email = 'manager.flex@example.com'
        cls.helpdesk_user.email = 'user.flex@example.com'
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False
        cls.company.write({'warranty_signoff_required': False,
                           'warranty_worksheet_checklist_required': False,
                           'warranty_worksheet_attachment_required': False,
                           'warranty_late_service_approver_ids': [
                               (6, 0, (cls.helpdesk_manager | cls.manager_b).ids)]})
        cls.site = cls.env['res.partner'].create({
            'name': 'ABC Hotel - Flex Site', 'parent_id': cls.customer.id, 'type': 'delivery',
            'street': '1 Flex Road', 'city': 'Colombo'})

    def setUp(self):
        super().setUp()
        self.today = self.company._warranty_today()

    # ------------------------------------------------------------------ helpers
    def _rules(self, rule='any', days=0, late='block', sequence=True):
        self.policy.write({'early_service_rule': rule, 'early_service_days': days,
                           'late_service_handling': late, 'service_sequence_required': sequence})

    def _flex_card(self, due_in=10):
        """Confirmed card (policy rules snapshotted) whose service 1 is due about `due_in` days
        from today."""
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'partner_shipping_id': self.site.id,
            'order_line': [(0, 0, {'product_id': self.product.id})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, self.today - relativedelta(months=4) + timedelta(days=due_in))
        card.action_confirm_warranty()
        return card

    def _services(self, card):
        return card.service_entitlement_ids.sorted('service_no')

    def _case(self, services):
        ticket = self._ticket(warranty_site_id=self.site.id)
        action = ticket.with_user(self.helpdesk_user).action_view_warranty_pending_services()
        case = self.env['warranty.case'].browse(
            services.with_user(self.helpdesk_user).with_context(action['context'])
            .action_create_warranty_case_from_services()['res_id'])
        case.with_user(self.creator).requested_item_ids = self.item_service
        return case

    def _check(self, case):
        case.with_user(self.helpdesk_user).action_check_eligibility()
        return case.eligibility_result

    def _notes(self, record):
        return ' '.join(record.message_ids.mapped('body'))

    def _at(self, day):
        return datetime.combine(day, time(10, 0))

    def _job(self, services, day=None):
        case = self._case(services)
        self.assertEqual(self._check(case), 'eligible', self._notes(case)[:1500])
        case.with_user(self.approver_a).action_approve_case()
        action = case.with_user(self.helpdesk_user).action_prepare_service_job()
        job = self.env['warranty.service.job'].browse(action['res_id'])
        job.with_user(self.helpdesk_user).write({
            'planned_date': self._at(day or self.today + timedelta(days=1)),
            'main_technician_id': self.tech.id})
        return job

    def _confirm(self, job):
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        return job.visit_ids

    def _work(self, task):
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Maintenance'}).save_timesheet()

    def _request(self, service, day, user=None, reason='Customer abroad until then'):
        return self.env['warranty.service.date.exception'].with_user(
            user or self.helpdesk_user)._warranty_request(service, day, reason)

    # ------------------------------------------------------------------ tests
    def test_201_snapshot_and_legacy_cards(self):
        """K1 / F1 / F10: the policy rules are copied at confirmation; a card without them
        (confirmed before the enhancement) keeps the standard D3 / Part 2 rules."""
        self._rules('days', 60, 'approval')
        card = self._flex_card(due_in=100)
        self.assertEqual((card.early_service_rule, card.early_service_days,
                          card.late_service_handling, card.service_sequence_required),
                         ('days', 60, 'approval', True))
        self.policy.early_service_rule = 'any'
        self.assertEqual(card.early_service_rule, 'days')
        service = self._services(card)[0]
        window = service._warranty_allowed_range()
        self.assertEqual(window, (service.due_date - timedelta(days=60),
                                  service.due_date + timedelta(days=30)))
        legacy = self._flex_card(due_in=100)
        legacy.write({'early_service_rule': False, 'late_service_handling': False,
                      'service_sequence_required': False})
        old = self._services(legacy)[0]
        self.assertIsNone(old._warranty_allowed_range())
        self.assertEqual(old._warranty_service_window(), old._warranty_alert_window())
        # Part 2 legacy rule: any date from today to the Grace Period End.
        old.with_user(self.helpdesk_user)._schedule_service(self.today + timedelta(days=1))
        self.assertEqual(old.state, 'scheduled')

    def test_202_early_service_days_before_due(self):
        """F2 / K2: Days Before Due - schedule, plan and complete before the due date; the due
        date is unchanged and the service consumed once; outside: refused everywhere."""
        self._rules('days', 60)
        card = self._flex_card(due_in=40)
        service = self._services(card)[0]
        due = service.due_date
        far = self._services(self._flex_card(due_in=100))[0]
        with self.assertRaisesRegex(UserError, 'permitted service dates'):
            far.with_user(self.helpdesk_user)._schedule_service(self.today + timedelta(days=1))
        service.with_user(self.helpdesk_user)._schedule_service(self.today + timedelta(days=1))
        job = self._job(service)
        task = self._confirm(job)
        self._work(task)
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual((service.state, service.due_date, card.free_services_used),
                         ('completed', due, 1))
        self.assertTrue(job.actual_completion_date and task.warranty_completion_date)
        self.assertNotEqual(job.actual_completion_date, job.planned_date)
        case = self._case(far)
        self.assertEqual(self._check(case), 'eligible')
        case.with_user(self.approver_a).action_approve_case()
        action = case.with_user(self.helpdesk_user).action_prepare_service_job()
        far_job = self.env['warranty.service.job'].browse(action['res_id'])
        far_job.with_user(self.helpdesk_user).write({
            'planned_date': self._at(self.today + timedelta(days=1)),
            'main_technician_id': self.tech.id})
        # D3 revised: outside the permitted dates is a note, not a planning block
        far_job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        self.assertEqual(far_job.state, 'planned')
        self.assertIn('outside the service window', self._notes(far_job))

    def test_203_sequence_and_same_card(self):
        """F3 / K7: two services of one card are not merged; service 2 needs service 1 closed
        (eligibility unless service 1 is on an open job; completion always)."""
        self._rules('any')
        card = self._flex_card(due_in=10)
        first, second = self._services(card)[:2]
        both = self._case(first | second)
        self.assertEqual(self._check(both), 'manual_review')
        self.assertIn('of one card cannot be serviced together', self._notes(both))
        both.with_user(self.helpdesk_user).service_entitlement_ids = [(5, 0, 0)]
        alone = self._case(second)
        self.assertEqual(self._check(alone), 'manual_review')
        self.assertIn('previous free service %s must be Completed' % first.name, self._notes(alone))
        alone.with_user(self.helpdesk_user).service_entitlement_ids = [(3, second.id)]
        first_job = self._job(first)
        first_task = self._confirm(first_job)
        second_job = self._job(second)
        second_task = self._confirm(second_job)
        self._work(second_task)
        with self.assertRaisesRegex(UserError, 'previous free service %s' % first.name):
            second_task.with_user(self.tech).action_warranty_complete_visit()
        self.assertIn('previous free service', ' '.join(second_job._warranty_batch_problems()))
        self._work(first_task)
        first_task.with_user(self.tech).action_warranty_complete_visit()
        second_task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual((first.state, second.state, card.free_services_used),
                         ('completed', 'completed', 2))

    def test_204_grace_period_note_and_block(self):
        """F4: after the due date within the grace period: allowed with an audit note; after
        the Grace Period End with Block: refused (no exception offered)."""
        self._rules('alert', late='block')
        service = self._services(self._flex_card(due_in=-5))[0]
        job = self._job(service, day=self.today + timedelta(days=2))
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        self.assertIn('is after its due date', self._notes(job))
        late = service.due_date + timedelta(days=31)
        problems = job._warranty_planned_date_problems(self._at(late))
        self.assertTrue(problems)
        self.assertNotIn('Late Service Exception', ' '.join(problems))
        with self.assertRaisesRegex(UserError, 'does not allow late-service exceptions'):
            self._request(service, late)

    def test_205_exception_request_and_approval(self):
        """F5 / F6 / K5: request (mandatory reason, To-Dos, one open request, date after the
        current latest, not after the warranty end); approval by an approver only - never the
        requester, the automation user or another company; approved date permits planning."""
        self._rules('alert', late='approval')
        card = self._flex_card(due_in=-5)
        service = self._services(card)[0]
        job = self._job(service, day=self.today + timedelta(days=2))
        late = service.due_date + timedelta(days=40)
        problems = job._warranty_planned_date_problems(self._at(late))
        self.assertIn('Request Late Service Exception', ' '.join(problems))
        with self.assertRaisesRegex(UserError, 'already a permitted service date'):
            self._request(service, self.today + timedelta(days=3))
        with self.assertRaisesRegex(UserError, 'warranty coverage is not extended'):
            self._request(service, card.warranty_end_date + timedelta(days=1))
        with self.assertRaisesRegex(UserError, 'reason are required'):
            self._request(service, late, reason=' ')
        with self.assertRaises(AccessError):
            self._request(service, late, user=self.internal_user)
        request = self._request(service, late)
        self.assertEqual(request.state, 'requested')
        self.assertEqual(request.group_id.approval_activity_ids.user_id,
                         self.helpdesk_manager | self.manager_b)
        with self.assertRaisesRegex(UserError, 'already requested'):
            self._request(service, late)
        self.assertEqual(service._warranty_service_window()[1],
                         service.due_date + timedelta(days=30))
        with self.assertRaises(UserError):
            request.with_user(self.helpdesk_manager).write({'requested_date': late})
        with self.assertRaises(UserError):
            request.unlink()
        with self.assertRaises(UserError):
            self.env['warranty.service.date.exception'].create({
                'entitlement_id': service.id, 'requested_date': late, 'reason': 'x'})
        with self.assertRaises(AccessError):
            request.with_user(self.helpdesk_user).action_approve()
        with self.assertRaises(AccessError):
            request.with_user(self.foreign_user).action_approve()
        request.with_user(self.helpdesk_manager).action_approve()
        self.assertEqual((request.state, request.decided_by_id), ('approved', self.helpdesk_manager))
        self.assertFalse(request.group_id.approval_activity_ids.exists().filtered('active'))
        self.assertEqual(service._warranty_service_window()[1], late)
        self.assertFalse(job._warranty_planned_date_problems(self._at(late)))
        self.assertIn('approved by', self._notes(service))
        self.assertIn('approved by', self._notes(card))
        # Separation of duties: a manager requesting never approves; the automation user never.
        other = self._services(self._flex_card(due_in=-5))[0]
        own = self._request(other, late, user=self.helpdesk_manager)
        self.assertEqual(own.group_id.approval_activity_ids.user_id, self.manager_b)
        with self.assertRaisesRegex(AccessError, 'separation of duties'):
            own.with_user(self.helpdesk_manager).action_approve()
        self.company.warranty_draft_job_user_id = self.manager_b
        with self.assertRaisesRegex(AccessError, 'separation of duties'):
            own.with_user(self.manager_b).action_approve()
        self.company.warranty_draft_job_user_id = False
        with self.assertRaisesRegex(UserError, 'reason is required'):
            own.with_user(self.manager_b).action_reject(' ')
        own.with_user(self.manager_b).action_reject('Customer did not confirm')
        self.assertEqual(own.state, 'rejected')
        self.assertEqual(other._warranty_service_window()[1], other.due_date + timedelta(days=30))
        self.assertFalse(self.env['warranty.service.date.exception'].with_user(
            self.foreign_user).search([]))

    def test_206_expiry_protection(self):
        """F7 / F8 / K3 / K6: an approved exception keeps the service available and protected
        from the Part 2 expiry until its date; a request alone does not (closed as Not Approved
        before Expiry); Expired stays final."""
        self._rules('alert', late='approval')
        pending = self._services(self._flex_card(due_in=-5))[0]
        approved = self._services(self._flex_card(due_in=-5))[0]
        late = pending.due_date + timedelta(days=40)
        request = self._request(pending, late)
        self._request(approved, late).with_user(self.helpdesk_manager).action_approve()
        after_grace = pending.due_date + timedelta(days=31)
        Entitlement = self.env['warranty.service.entitlement']
        with self._today(after_grace):
            (pending | approved)._apply_expiry_rules(after_grace)
            self.assertEqual((pending.state, approved.state), ('expired', 'missed'))
            self.assertEqual(request.state, 'expired')
            self.assertFalse(request.group_id.approval_activity_ids.exists().filtered('active'))
            self.assertIn('not approved before', self._notes(pending))
            available = Entitlement._warranty_pending_services(self.customer, self.company)
            self.assertIn(approved, available)
            self.assertNotIn(pending, available)
            with self.assertRaisesRegex(UserError, 'no exception is possible'):
                self._request(pending, late)
        after_exception = late + timedelta(days=1)
        with self._today(after_exception):
            approved._apply_expiry_rules(after_exception)
        self.assertEqual(approved.state, 'expired')

    def test_207_completion_outside_dates_warns(self):
        """Revised F9: early and late completion are not blocked - warning returned, audit note,
        Actual Completion Date, consumed once (single and batch); planning outside the dates
        stays refused (tests 202 / 204)."""
        self._rules('days', 10, late='approval')
        early = self._services(self._flex_card(due_in=20))[0]
        job = self._job(early, day=early.due_date - timedelta(days=5))
        task = self._confirm(job)
        self._work(task)
        self.assertNotIn('outside', ' '.join(job._warranty_batch_problems()))
        result = task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(result['params']['type'], 'warning')
        self.assertIn('earlier than its earliest permitted service date', result['params']['message'])
        self.assertIn('earlier than its earliest permitted', self._notes(job))
        self.assertEqual((early.state, early.warranty_card_id.free_services_used), ('completed', 1))
        self.assertTrue(job.actual_completion_date)
        with self.assertRaisesRegex(UserError, 'already closed'):
            task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(early.warranty_card_id.free_services_used, 1)
        # Late, without exception, in a batch: completed with the note.
        late_service = self._services(self._flex_card(due_in=-25))[0]
        late_job = self._job(late_service, day=self.today + timedelta(days=1))
        late_task = self._confirm(late_job)
        self._work(late_task)
        after = late_service.due_date + timedelta(days=31)
        with self._today(after):
            self.assertFalse(late_job._warranty_batch_problems())
            late_job.with_user(self.helpdesk_user)._warranty_complete_visit(late_task, batch=True)
        self.assertEqual((late_service.state, late_service.warranty_card_id.free_services_used),
                         ('completed', 1))
        self.assertIn('later than its latest permitted service date', self._notes(late_job))

    def test_208_cross_card_different_due_dates(self):
        """Requirement 5 / D1-D8, D3 revised (cross-card merge): services of several cards with
        different due dates merge, also without a common permitted date (no exception needed);
        a service whose permitted dates ended is still refused, by name."""
        self._rules('days', 60, late='approval')
        soon = self._services(self._flex_card(due_in=10))[0]
        later = self._services(self._flex_card(due_in=50))[0]
        job = self._job(soon | later, day=self.today + timedelta(days=12))
        self.assertEqual(job.warranty_card_ids, soon.warranty_card_id | later.warranty_card_id)
        self.assertFalse(job._warranty_planned_date_problems())
        first = self._services(self._flex_card(due_in=-20))[0]
        far = self._services(self._flex_card(due_in=100))[0]
        self.assertLess(first._warranty_service_window()[1], far._warranty_service_window()[0])
        case = self._case(first | far)
        self.assertEqual(self._check(case), 'eligible', self._notes(case)[:1500])
        ended = self._services(self._flex_card(due_in=-200))[0]
        self.assertLess(ended._warranty_service_window()[1], self.today)
        problems = ' '.join((ended | far)._warranty_window_conflicts(self.company))
        self.assertIn('permitted service dates of %s' % ended.name, problems)
        self.assertNotIn(far.name, problems)

    def test_209_automatic_trigger_unchanged(self):
        """K8: the Part 4.11 automatic draft job keeps the Alert Date trigger, also when the
        flexible rules already permit the service."""
        self._rules('any')
        self.policy.draft_job_from_service = True
        robot = self._user('wfd_robot', 'helpdesk.group_helpdesk_user')
        self.company.write({'warranty_draft_job_team_id': self.team.id,
                            'warranty_draft_job_user_id': robot.id})
        service = self._services(self._flex_card(due_in=30))[0]
        self.assertTrue(service._warranty_allowed_range()[0] <= self.today)
        self.env['warranty.service.entitlement']._warranty_run_draft_jobs()
        self.assertFalse(service.warranty_auto_job_state)
        with self._today(service._warranty_alert_window()[0]):
            self.env['warranty.service.entitlement']._warranty_run_draft_jobs()
        # Approved D-B: a Draft service-origin job (ticket / case at Create or Link Ticket).
        self.assertEqual(service.warranty_auto_job_state, 'job_created')

    def test_210_reschedule_uses_the_rules(self):
        """K2: Plan Next Visit and Part 2 Reschedule use the permitted dates and approved
        exceptions."""
        self._rules('alert', late='approval')
        service = self._services(self._flex_card(due_in=-5))[0]
        late = service.due_date + timedelta(days=40)
        service.with_user(self.helpdesk_user)._schedule_service(self.today + timedelta(days=1))
        with self.assertRaisesRegex(UserError, 'Request Late Service Exception'):
            service.with_user(self.helpdesk_user)._schedule_service(late, reason='Customer away')
        self._request(service, late).with_user(self.helpdesk_manager).action_approve()
        service.with_user(self.helpdesk_user)._schedule_service(late, reason='Customer away')
        self.assertEqual((service.state, service.scheduled_date), ('rescheduled', late))
        job = self._job(service, day=self.today + timedelta(days=1))
        self.assertFalse(job._warranty_planned_date_problems(self._at(late)))
        self.assertTrue(job._warranty_planned_date_problems(self._at(late + timedelta(days=1))))

    # ------------------------------------------------------------------ request groups (G1-G7)
    def _two_services(self):
        self._rules('alert', late='approval')
        first = self._services(self._flex_card(due_in=-5))[0]
        second = self._services(self._flex_card(due_in=-5))[0]
        return first, second, first.due_date + timedelta(days=40)

    def _group(self, services, day, user=None, reason='Hotel closed for renovation'):
        return self.env['warranty.service.date.exception.group'].with_user(
            user or self.helpdesk_user)._warranty_request_group(services, day, reason)

    def _wizard(self, action, **vals):
        return self.env[action['res_model']].with_user(self.helpdesk_user).with_context(
            action['context']).create(dict({'reason': 'Hotel closed for renovation'}, **vals))

    def test_211_group_request_cross_card_job(self):
        """G1-G4: from a job with two cards both services are preselected (deselect possible);
        one request, one record per service, one To-Do per approver; approved together by an
        authorized manager only; every service then permits the date, not later."""
        first, second, late = self._two_services()
        job = self._job(first | second, day=self.today + timedelta(days=2))
        action = job.with_user(self.helpdesk_user).action_open_late_service_wizard()
        wizard = self._wizard(action, requested_date=late)
        self.assertEqual((wizard.entitlement_ids, wizard.job_id, wizard.case_id),
                         (first | second, job, job.warranty_case_id))
        wizard.entitlement_ids = [(3, second.id)]
        wizard.action_request()
        alone = first.service_date_exception_ids.group_id
        self.assertEqual(alone.exception_ids.entitlement_id, first)
        alone.with_user(self.helpdesk_user).action_cancel()
        self.assertEqual((alone.state, alone.exception_ids.state), ('cancelled', 'cancelled'))
        self._wizard(job.with_user(self.helpdesk_user).action_open_late_service_wizard(),
                     requested_date=late).action_request()
        group = second.service_date_exception_ids.group_id
        self.assertEqual((group.exception_ids.entitlement_id, group.job_id, group.state),
                         (first | second, job, 'requested'))
        todos = group.approval_activity_ids.filtered('active')
        self.assertEqual((len(todos), todos.user_id),
                         (2, self.helpdesk_manager | self.manager_b))
        self.assertFalse(group.exception_ids.approval_activity_ids)
        with self.assertRaisesRegex(UserError, 'Already requested|already requested'):
            job.with_user(self.helpdesk_user).action_open_late_service_wizard()
        with self.assertRaises(AccessError):
            group.with_user(self.helpdesk_user).action_approve()
        with self.assertRaises(AccessError):
            group.with_user(self.foreign_user).action_approve()
        with self.assertRaisesRegex(UserError, 'approved or rejected together'):
            group.exception_ids[0].with_user(self.helpdesk_manager).action_approve()
        group.with_user(self.helpdesk_manager).action_approve()
        self.assertEqual(group.state, 'approved')
        self.assertEqual(set(group.exception_ids.mapped('state')), {'approved'})
        self.assertEqual(group.exception_ids.decided_by_id, self.helpdesk_manager)
        self.assertFalse(group.approval_activity_ids.filtered('active'))
        for service in first | second:
            self.assertEqual(service._warranty_service_window()[1], late)
            self.assertIn('approved by', self._notes(service))
        self.assertFalse(job._warranty_planned_date_problems(self._at(late)))
        problems = ' '.join(job._warranty_planned_date_problems(self._at(late + timedelta(days=1))))
        self.assertIn(first.name, problems)
        self.assertIn(second.name, problems)

    def test_212_every_service_validated_nothing_partial(self):
        """G3: one invalid service (Block policy, date after its own warranty end, open request,
        two companies) -> nothing created, the failing service named."""
        first, second, late = self._two_services()
        Exception_ = self.env['warranty.service.date.exception']
        second.warranty_card_id.late_service_handling = 'block'
        with self.assertRaisesRegex(UserError, '%s .*does not allow' % second.name):
            self._group(first | second, late)
        self.assertFalse(Exception_.search([('entitlement_id', 'in', (first | second).ids)]))
        second.warranty_card_id.late_service_handling = 'approval'
        # Start Date Automation: confirmed dates are written by system code only.
        second.warranty_card_id._warranty_system_write({'warranty_end_date': late - timedelta(days=1)})
        with self.assertRaisesRegex(UserError, '%s .*after the warranty end date' % second.name):
            self._group(first | second, late)
        self.assertFalse(Exception_.search([('entitlement_id', 'in', (first | second).ids)]))
        second.warranty_card_id._warranty_system_write(
            {'warranty_end_date': late + timedelta(days=100)})
        self._group(first, late)
        with self.assertRaisesRegex(UserError, '%s .*already requested' % first.name):
            self._group(first | second, late)
        self.assertFalse(Exception_.search([('entitlement_id', '=', second.id)]))
        second.warranty_card_id.sudo().company_id = self.other_company
        both = self._user('wfd_both_companies', 'helpdesk.group_helpdesk_user')
        both.company_ids = self.company | self.other_company
        with self.assertRaisesRegex(UserError, 'one company and one customer'):
            self.env['warranty.service.date.exception.group'].with_user(both).with_context(
                allowed_company_ids=(self.company | self.other_company).ids
            )._warranty_request_group(first | second, late + timedelta(days=1), 'x')

    def test_213_approval_revalidates_every_service(self):
        """G3 / requirement 5: the group approval re-checks each service; one failure ->
        nothing decided."""
        first, second, late = self._two_services()
        group = self._group(first | second, late)
        second.warranty_card_id._warranty_system_write({'warranty_end_date': late - timedelta(days=1)})
        with self.assertRaisesRegex(UserError, '%s .*after the warranty end date' % second.name):
            group.with_user(self.helpdesk_manager).action_approve()
        self.assertEqual(set(group.exception_ids.mapped('state')), {'requested'})
        self.assertEqual(first._warranty_service_window()[1], first.due_date + timedelta(days=30))
        with self.assertRaisesRegex(UserError, 'reason is required'):
            group.with_user(self.helpdesk_manager).action_reject(' ')
        group.with_user(self.helpdesk_manager).action_reject('Not confirmed by the customer')
        self.assertEqual((group.state, set(group.exception_ids.mapped('state'))),
                         ('rejected', {'rejected'}))
        self.assertEqual(second._warranty_service_window()[1], second.due_date + timedelta(days=30))

    def test_214_partly_expired_group(self):
        """H5-A: a member expiring first -> Partly Expired, approval refused, To-Do to reject or
        cancel; rejecting keeps the expired member and releases the other for a new request."""
        first, second, late = self._two_services()
        group = self._group(first | second, late)
        after_grace = first.due_date + timedelta(days=31)
        with self._today(after_grace):
            first._apply_expiry_rules(after_grace)
            self.assertEqual((first.state, group.state), ('expired', 'partly_expired'))
            todos = group.approval_activity_ids.filtered('active')
            self.assertTrue(todos)
            self.assertTrue(all('Reject or cancel' in todo.summary for todo in todos))
            with self.assertRaisesRegex(UserError, 'cannot be approved'):
                group.with_user(self.helpdesk_manager).action_approve()
            group.with_user(self.helpdesk_manager).action_reject('First service expired')
            self.assertEqual(group.state, 'rejected')
            states = {record.entitlement_id: record.state for record in group.exception_ids}
            self.assertEqual(states, {first: 'expired', second: 'rejected'})
            self.assertFalse(group.approval_activity_ids.filtered('active'))
            new = self._group(second, late)
            self.assertEqual((new.state, new.exception_ids.entitlement_id), ('requested', second))

    def test_215_security_and_protected_records(self):
        """G7: groups of another company are invisible; records cannot be created, edited or
        deleted directly; the protection flag does not leak to callers."""
        first, second, late = self._two_services()
        group = self._group(first | second, late)
        Group = self.env['warranty.service.date.exception.group']
        self.assertFalse(Group.with_user(self.foreign_user).search([]))
        with self.assertRaises(UserError):
            group.with_user(self.helpdesk_user).write({'reason': 'changed'})
        with self.assertRaises(UserError):
            group.unlink()
        with self.assertRaises(UserError):
            Group.create({'name': 'x', 'company_id': self.company.id, 'requested_date': late,
                          'reason': 'x'})
        with self.assertRaises(UserError):
            group.exception_ids[0].write({'state': 'approved'})
        group.with_user(self.helpdesk_manager).action_approve()
        with self.assertRaises(UserError):
            group.exception_ids.with_user(self.helpdesk_manager).write({'requested_date': late})

    def test_216_single_service_and_standalone_records(self):
        """G6: from the free service form a request of one; a record created before the request
        groups (no group) is still decided alone."""
        first, second, late = self._two_services()
        action = first.with_user(self.helpdesk_user).action_open_late_service_wizard()
        wizard = self._wizard(action, requested_date=late)
        self.assertEqual(wizard.entitlement_ids, first)
        wizard.action_request()
        record = first.service_date_exception_ids
        self.assertEqual(len(record.group_id.exception_ids), 1)
        record.with_user(self.helpdesk_manager).action_approve()
        self.assertEqual((record.state, record.group_id.state), ('approved', 'approved'))
        legacy = self.env['warranty.service.date.exception'].with_context(
            warranty_exception_marker=_EXCEPTION_MARKER).create({
                'entitlement_id': second.id, 'requested_date': late, 'reason': 'Before groups',
                'requested_by_id': self.helpdesk_user.id,
                'grace_end_date': second.due_date + timedelta(days=30),
                'warranty_end_date': second.warranty_card_id.warranty_end_date}).with_env(self.env)
        self.assertTrue(legacy.with_user(self.helpdesk_manager).can_decide)
        with self.assertRaises(AccessError):
            legacy.with_user(self.helpdesk_user).action_approve()
        legacy.with_user(self.helpdesk_manager).action_approve()
        self.assertEqual(legacy.state, 'approved')
        self.assertEqual(second._warranty_service_window()[1], late)

    def test_217_cross_card_early_completion(self):
        """Revised F9 / requirement 8: a merged job of two cards completed before the earliest
        permitted date of both: completed, one warning per service, each consumed once."""
        self._rules('days', 10)
        first = self._services(self._flex_card(due_in=20))[0]
        second = self._services(self._flex_card(due_in=22))[0]
        job = self._job(first | second, day=first.due_date - timedelta(days=5))
        task = self._confirm(job)
        self._work(task)
        result = task.with_user(self.tech).action_warranty_complete_visit()
        message = result['params']['message']
        self.assertIn(first.name, message)
        self.assertIn(second.name, message)
        for service in first | second:
            self.assertEqual((service.state, service.warranty_card_id.free_services_used),
                             ('completed', 1))

    def test_219_planned_date_outside_window_not_blocking(self):
        """D3 / D4 revised: the due date is a target - a Planned Date long before the service
        window (e.g. today for a service due in 3 months, JOB/000006) or a past date outside it
        is accepted at Plan Job and Confirm with a Service date note; the free service due date
        and status are unchanged by the job."""
        self._rules('days', 30)
        service = self._services(self._flex_card(due_in=92))[0]
        due = service.due_date
        self.assertGreater(service._warranty_service_window()[0], self.today)
        job = self._job(service, day=self.today)
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        self.assertEqual(job.state, 'planned')
        self.assertIn('outside the service window of %s' % service.name, self._notes(job))
        job.with_user(self.helpdesk_user).planned_date = self._at(self.today - timedelta(days=25))
        job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual(job.state, 'confirmed')
        self.assertEqual(job.visit_ids.planned_date_begin, job.planned_date)
        self.assertEqual(service.due_date, due)
        self.assertNotIn(service.state, ('completed', 'expired', 'missed'))
        self.assertEqual(service.warranty_card_id.free_services_used, 0)

    def test_218_closed_services_never_completed(self):
        """Revised F9 safeguard: an Expired or Cancelled linked service blocks the completion
        (nothing consumed); the date rule removal does not reopen them."""
        self._rules('any')
        service = self._services(self._flex_card(due_in=10))[0]
        job = self._job(service)
        task = self._confirm(job)
        self._work(task)
        service.sudo().write({'state': 'expired'})
        with self.assertRaisesRegex(UserError, 'is Expired and cannot be completed'):
            task.with_user(self.tech).action_warranty_complete_visit()
        self.assertIn('cannot be completed', ' '.join(job._warranty_batch_problems()))
        self.assertEqual((service.state, job.state), ('expired', 'in_progress'))

