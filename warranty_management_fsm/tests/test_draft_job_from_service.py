from datetime import timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation

from .common import ServiceJobCommon, link_case


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestDraftJobFromService(ServiceJobCommon):
    """Phase 4.11 - Draft Job from Service (approved E1-E10, A1-A7, Q24 resolution)."""

    check_service_windows = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy.write({'grace_period_days': 30, 'service_due_alert_days': 7,
                          'draft_job_from_service': True,
                          'auto_case_item_ids': [(6, 0, cls.item_service.ids)]})
        cls.robot = cls._user('wdj_robot', 'helpdesk.group_helpdesk_user')
        cls.robot.email = 'robot.draftjob@example.com'
        cls.planner = cls._user('wdj_planner', 'helpdesk.group_helpdesk_user')
        cls.planner.email = 'planner.draftjob@example.com'
        cls.company.warranty_service_alert_user_ids = cls.planner
        cls.dj_team = cls.env['helpdesk.team'].create({'name': 'Draft Job Team'})
        cls.tech = cls._user('wdj_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.draftjob@example.com'
        cls.env['hr.employee'].create({'name': 'Draft Job Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False
        cls.company.write({'warranty_signoff_required': False,
                           'warranty_worksheet_checklist_required': False,
                           'warranty_worksheet_attachment_required': False})
        Partner = cls.env['res.partner']
        cls.addr_main = Partner.create({'name': 'ABC Hotel - Main Building',
                                        'parent_id': cls.customer.id, 'type': 'delivery',
                                        'street': 'No 5 Galle Road', 'city': 'Colombo'})
        cls.addr_same = Partner.create({'name': 'ABC Hotel - Plant Room',
                                        'parent_id': cls.customer.id, 'type': 'delivery',
                                        'street': ' no 5  GALLE road', 'city': 'colombo'})
        cls.addr_other = Partner.create({'name': 'ABC Hotel - Kandy',
                                         'parent_id': cls.customer.id, 'type': 'delivery',
                                         'street': '12 Peradeniya Road', 'city': 'Kandy'})

    def setUp(self):
        super().setUp()
        # The card of the common setup is not part of these scenarios.
        self.card.draft_job_from_service = False
        self.today = self.company._warranty_today()

    # ------------------------------------------------------------------ helpers
    def _configure(self, company=None, team=None, user=None):
        (company or self.company).write({
            'warranty_draft_job_team_id': (team or self.dj_team).id,
            'warranty_draft_job_user_id': (user or self.robot).id})

    def _ac_card(self, site=None, due_in=3, product=None, company=None):
        """Confirmed card whose first free service is due in `due_in` days (window: 7 days
        before .. 30 days after)."""
        company = company or self.company
        order = self.env['sale.order'].with_company(company).create({
            'company_id': company.id,
            'partner_id': self.customer.id,
            'partner_shipping_id': (site or self.addr_main).id,
            'order_line': [(0, 0, {'product_id': (product or self.product).id})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, self.today - relativedelta(months=4) + timedelta(days=due_in))
        card.action_confirm_warranty()
        return card

    def _first(self, cards):
        return self.env['warranty.service.entitlement'].union(*[
            card.service_entitlement_ids.sorted('service_no')[:1] for card in cards])

    def _cards(self, count, **kwargs):
        return self.env['warranty.card'].union(*[self._ac_card(**kwargs) for _ in range(count)])

    def _run(self, days=0):
        Entitlement = self.env['warranty.service.entitlement']
        with self._today(self.today + timedelta(days=days)):
            Entitlement._warranty_run_draft_jobs()

    def _start(self, service):
        """Days from today to the start of the service window."""
        return (service._warranty_service_window()[0] - self.today).days

    def _tickets(self, team=None):
        return self.env['helpdesk.ticket'].search([('team_id', '=', (team or self.dj_team).id)])

    def _todos(self, record):
        return record.warranty_auto_todo_ids.exists().filtered('active')

    def _notes(self, record):
        return ' '.join(record.message_ids.mapped('body'))

    def _confirm(self, job):
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=3),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        return job.visit_ids

    def _work(self, task):
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Maintenance'}).save_timesheet()

    # ------------------------------------------------------------------ tests
    def test_171_setting_off_snapshot_and_usage_based(self):
        """E2 / E9: the policy value is kept on the card at confirmation; cards without it and
        usage-based cards create nothing."""
        self._configure()
        self.policy.draft_job_from_service = False
        off = self._ac_card()
        self.policy.draft_job_from_service = True
        self.assertFalse(off.draft_job_from_service)
        usage = self._ac_card()
        self.assertTrue(usage.draft_job_from_service)
        usage.sudo().warranty_basis = 'usage'
        self._run()
        self.assertFalse(self._tickets())
        self.assertFalse(self._first(off | usage).filtered('warranty_auto_job_state'))

    def _auto_jobs(self):
        return self.env['warranty.service.job'].search([('warranty_auto_service_job', '=', True)])

    def test_171b_no_scope_mode_limitation(self):
        """BA decision 2026-10-28: a company left in Warranty Only (kept, unused field) is
        processed like any other; reruns create nothing more (D-B: a Draft job, no ticket)."""
        self._configure()
        self.company.warranty_scope_mode = 'warranty_only'
        service = self._first(self._ac_card())
        self._run()
        self.assertEqual(service.warranty_auto_job_state, 'job_created')
        self.assertEqual((len(self._auto_jobs()), len(self._tickets())), (1, 0))
        self._run()
        self.assertEqual(len(self._auto_jobs()), 1)

    def test_172_missing_configuration_blocked_and_retried(self):
        """E4 / A4: missing team / user -> Blocked with the reason, one To-Do (service alert
        users), not repeated; replaced when the reason changes; processed once configured; an
        invalid automation user is refused."""
        self.company.write({'warranty_draft_job_team_id': False, 'warranty_draft_job_user_id': False})
        service = self._first(self._ac_card())
        self._run()
        self.assertEqual(service.warranty_auto_job_state, 'blocked')
        self.assertIn('Draft Job Helpdesk Team is not configured', service.warranty_auto_job_note)
        todo = self._todos(service)
        self.assertEqual(todo.user_id, self.planner)
        self._run()
        self.assertEqual(self._todos(service), todo)
        self.company.warranty_draft_job_team_id = self.dj_team
        self._run()
        self.assertIn('Automation User is not configured', service.warranty_auto_job_note)
        self.assertNotEqual(self._todos(service), todo)
        with self.assertRaisesRegex(ValidationError, 'active internal Helpdesk user'):
            self.company.warranty_draft_job_user_id = self.internal_user
        self._configure()
        self._run()
        self.assertEqual(service.warranty_auto_job_state, 'job_created')
        self.assertFalse(self._todos(service))
        self.assertEqual((len(self._auto_jobs()), len(self._tickets())), (1, 0))

    def test_173_eight_ac_one_job_ticket_case(self):
        """D-B / SRS 9.4 / E5 / E7: 8 cards of one site (equivalent addresses) -> ONE Draft
        service-origin job (automation user, no ticket / case, no visit), due alerts replaced
        by the planning To-Do; reruns create nothing; Create or Link Helpdesk Ticket -> ticket
        and Free Service case Eligible without general approval (D-A); Confirm -> one visit
        with 8 worksheets; each card consumed once at completion."""
        self._configure()
        cards = self._cards(6) | self._cards(2, site=self.addr_same, due_in=5)
        services = self._first(cards)
        self.env['warranty.service.entitlement']._cron_monitor_free_services()
        job = self._auto_jobs()
        self.assertEqual((len(job), job.state, job.job_origin, job.warranty_case_id.ids,
                          job.helpdesk_ticket_id.ids, job.entitlement_ids, job.warranty_card_ids,
                          job.create_uid), (1, 'draft', 'service', [], [], services, cards,
                                            self.robot))
        self.assertEqual((job.partner_id, job.company_id), (self.customer, self.company))
        self.assertFalse(job.visit_ids)
        self.assertFalse(self._tickets())
        self.assertEqual(set(services.mapped('warranty_auto_job_state')), {'job_created'})
        self.assertEqual(set(services.mapped('merge_status')), {'merged'})
        self.assertFalse(services.due_alert_activity_ids.filtered('active'))
        self.assertEqual(self._todos(job).user_id, self.planner)
        self.assertFalse(self.env['mail.mail'].search([('recipient_ids', 'in', self.customer.ids)]))
        self._run()
        self._run()
        self.assertEqual(self._auto_jobs(), job)
        with self.assertRaisesRegex(UserError, 'Create or Link Helpdesk Ticket'):
            job.with_user(self.helpdesk_user).write({
                'planned_date': fields.Datetime.now() + timedelta(days=3),
                'main_technician_id': self.tech.id})
            job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
            job.with_user(self.helpdesk_user).action_confirm_job()
        case = link_case(job.with_user(self.helpdesk_user))
        ticket = case.helpdesk_ticket_id
        self.assertEqual((ticket.team_id, ticket.is_warranty, ticket.warranty_site_id),
                         (self.dj_team, True, job.site_id))
        self.assertEqual((job.warranty_case_id, job.helpdesk_ticket_id), (case, ticket))
        self.assertEqual((case.case_type, case.service_entitlement_ids, case.service_unit_ids,
                          case.requested_item_ids), ('free_service', services,
                                                     cards.unit_warranty_ids, self.item_service))
        self.assertEqual((case.state, case.eligibility_result),
                         ('eligibility_checked', 'eligible'))
        self.assertFalse(case.case_approval_activity_ids.filtered('active'), 'D-A: no approval')
        task = job.with_user(self.helpdesk_user).action_confirm_job() and job.visit_ids
        self.assertFalse(self._todos(job))
        self.assertEqual((len(task), len(job.worksheet_ids), task.helpdesk_ticket_id),
                         (1, 8, ticket))
        with self.assertRaises(UserError):
            job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual(len(job.visit_ids), 1)
        self._work(task)
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(set(services.mapped('state')), {'completed'})
        for card in cards:
            self.assertEqual((card.free_services_used, card.free_services_balance), (1, 2))

    def test_174_failed_card_blocks_confirmation(self):
        """A2 / D8: one card of another policy disagrees on the requested items -> the case of
        the job is Manual Review and the job cannot be confirmed; services of the job and the
        case must stay identical."""
        self._configure()
        policy = self.policy.copy({'name': 'DJ Policy PCB',
                                   'covered_item_ids': [(6, 0, self.item_pcb.ids)],
                                   'auto_case_item_ids': [(6, 0, self.item_pcb.ids)],
                                   'draft_job_from_service': True})
        categ = self.categ.copy({'name': 'DJ ACs PCB', 'warranty_policy_id': policy.id})
        product = self.env['product.product'].create({
            'name': 'DJ AC PCB', 'type': 'service', 'categ_id': categ.id,
            'warranty_applicable': True})
        self._cards(2)
        bad = self._ac_card(product=product)
        self.assertEqual(bad.policy_id, policy)
        self._run()
        job = self._auto_jobs()
        self.assertEqual(len(job.entitlement_ids), 3)
        case = link_case(job.with_user(self.helpdesk_user))
        self.assertEqual(case.eligibility_result, 'manual_review')
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=3),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        with self.assertRaisesRegex(UserError, 'must be Eligible'):
            job.with_user(self.helpdesk_user).action_confirm_job()
        case.with_user(self.helpdesk_user).service_entitlement_ids = [(3, self._first(bad).id)]
        case.with_user(self.planner).action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'eligible')
        with self.assertRaisesRegex(UserError, 'differ'):
            job.with_user(self.helpdesk_user).action_confirm_job()

    def test_175_later_services_join_only_open_draft_jobs(self):
        """E5 / A3: a service of a later run joins the open automatic Draft job (same customer
        / site, dates not ended, sequence); never a job with ticket / case or another site."""
        self._configure()
        first = self._ac_card()
        self._run()
        job = self._auto_jobs()
        later = self._ac_card(due_in=10)
        self._run()
        self.assertFalse(self._first(later).warranty_auto_job_state)
        self._run(days=self._start(self._first(later)))
        self.assertEqual(job.entitlement_ids, self._first(first | later))
        self.assertEqual(len(self._auto_jobs()), 1)
        link_case(job.with_user(self.helpdesk_user))
        third = self._first(self._ac_card(due_in=12))
        kandy = self._first(self._ac_card(site=self.addr_other, due_in=12))
        self._run(days=self._start(third))
        self.assertEqual(len(job.entitlement_ids), 2, 'a job with ticket / case is not joined')
        jobs = self._auto_jobs() - job
        self.assertEqual(len(jobs), 2)
        self.assertNotEqual(third.open_service_job_id, kandy.open_service_job_id)
        self.assertEqual(len(self._tickets()), 1)

    def test_176_cancelled_job_not_recreated(self):
        """E6: a cancelled automatic job is never created again by the automation."""
        self._configure()
        service = self._first(self._ac_card())
        self._run()
        job = self._auto_jobs()
        job.with_user(self.helpdesk_user).action_cancel()
        self.assertEqual(service.merge_status, 'not_merged')
        self.assertFalse(self._todos(job))
        self._run()
        self._run(days=1)
        self.assertEqual(self._auto_jobs(), job)

    def test_177_no_general_approval(self):
        """D-A: the Free Service case of a service-origin job is confirmed once Eligible,
        without general case approval (also when Warranty Case Approval Required is on)."""
        self.company.warranty_case_approval_required = True
        self._configure()
        self._ac_card()
        self._run()
        job = self._auto_jobs()
        case = link_case(job.with_user(self.planner))
        self.assertEqual((case.state, case.eligibility_result),
                         ('eligibility_checked', 'eligible'))
        self.assertFalse(case.case_approval_activity_ids.filtered('active'))
        self._confirm(job)
        self.assertEqual((job.state, case.state), ('confirmed', 'job_created'))

    def test_178_locked_and_concurrent_services(self):
        """Requirement 1 / A5: a service locked by another transaction is left for the next run;
        one linked manually meanwhile is not processed (no duplicate job / case)."""
        self._configure()
        first, second = self._first(self._cards(2))
        Entitlement = type(self.env['warranty.service.entitlement'])
        with patch.object(Entitlement, '_warranty_auto_lock',
                          lambda services: services - second):
            self._run()
        self.assertEqual((first.warranty_auto_job_state, second.warranty_auto_job_state),
                         ('job_created', False))
        ticket = self._ticket(warranty_site_id=self.addr_main.id)
        action = ticket.with_user(self.helpdesk_user).action_view_warranty_pending_services()
        manual = self.env['warranty.case'].browse(
            second.with_user(self.helpdesk_user).with_context(action['context'])
            .action_create_warranty_case_from_services()['res_id'])
        self._run()
        self.assertEqual((second.warranty_auto_job_state, second._warranty_active_cases()),
                         (False, manual))
        self.assertEqual(self._auto_jobs().entitlement_ids, first)
        # A service on an open job is no longer pending for the ticket: still refused.
        with self.assertRaisesRegex(UserError, 'not a pending free service'):
            first.with_user(self.helpdesk_user).with_context(action['context']) \
                .action_create_warranty_case_from_services()

    def test_179_companies_processed_separately(self):
        """Requirement 8 / E4: each company with its own team / automation user; a company
        without configuration is blocked (To-Do to its Helpdesk managers), the other continues;
        a team / user of another company is refused."""
        self._configure()
        self.other_company.write({
            'warranty_scope_mode': 'free_services', 'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period', 'default_start_criterion': 'installation',
            'default_warranty_duration': 12, 'default_warranty_duration_unit': 'months'})
        self.policy.company_id = False
        main = self._first(self._ac_card())
        foreign_card = self._ac_card(company=self.other_company)
        foreign = self._first(foreign_card)
        self.assertEqual((foreign_card.company_id, foreign.company_id, foreign.state),
                         (self.other_company, self.other_company, 'draft'))
        self._run()
        self.assertEqual(main.warranty_auto_job_state, 'job_created')
        self.assertEqual(foreign.warranty_auto_job_state, 'blocked')
        self.assertIn(self.other_company.name, foreign.warranty_auto_job_note)
        self.assertEqual(self._todos(foreign).user_id, self.foreign_user)
        other_team = self.env['helpdesk.team'].create({'name': 'Other DJ Team',
                                                       'company_id': self.other_company.id})
        other_robot = self._user('wdj_robot_other', 'helpdesk.group_helpdesk_user',
                                 company=self.other_company)
        with self.assertRaisesRegex(ValidationError, 'not a team of'):
            self.company.warranty_draft_job_team_id = other_team
        with self.assertRaisesRegex(ValidationError, 'active internal Helpdesk user'):
            self.company.warranty_draft_job_user_id = other_robot
        self._configure(self.other_company, other_team, other_robot)
        self._run()
        job = foreign.open_service_job_id
        self.assertEqual((job.company_id, job.job_origin, job.create_uid),
                         (self.other_company, 'service', other_robot))
        self.assertFalse(self._tickets())

    def test_180_protected_fields_window_end(self):
        """E10 / A7: the automation and origin fields cannot be set by users; a blocked service
        whose window ends is never processed."""
        self._configure()
        service = self._first(self._ac_card())
        with self.assertRaises(UserError):
            service.with_user(self.helpdesk_user).write({'warranty_auto_job_state': 'blocked'})
        with self.assertRaises(UserError):
            self.env['warranty.case'].with_user(self.helpdesk_user).create({
                'helpdesk_ticket_id': self.ticket.id, 'case_type': 'free_service',
                'warranty_auto_created': True})
        with self.assertRaises(UserError):
            self.env['warranty.service.job'].with_user(self.helpdesk_user).create({
                'job_origin': 'service', 'entitlement_ids': [(6, 0, service.ids)]})
        self._run()
        job = service.open_service_job_id
        for vals in ({'warranty_auto_service_job': False}, {'job_origin': 'case'},
                     {'warranty_case_id': self.env['warranty.case'].create({
                         'helpdesk_ticket_id': self.ticket.id,
                         'case_type': 'warranty_complaint'}).id}):
            with self.assertRaises(UserError):
                job.with_user(self.helpdesk_user).write(vals)
        late = self._first(self._ac_card())
        self.company.warranty_draft_job_team_id = False
        self._run()
        self.assertEqual(late.warranty_auto_job_state, 'blocked')
        self._run(days=40)
        self.assertEqual(late.warranty_auto_job_state, 'window_ended')
        self.assertIn('not created', self._todos(late).summary)
        self._configure()
        self._run(days=40)
        self.assertEqual((late.warranty_auto_job_state, late.open_service_job_id.ids),
                         ('window_ended', []))
