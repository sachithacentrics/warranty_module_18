from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestSharedVisit(ServiceJobCommon):
    """Shared Field Service visit (BA-approved v1, doc/shared_visit_design.md): ONE visit for
    several existing service jobs, which stay separate and are completed independently."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_s_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.shared@example.com'
        cls.env['hr.employee'].create({'name': 'Shared Visit Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False
        cls.company.write({'warranty_signoff_required': False,
                           'warranty_worksheet_checklist_required': False,
                           'warranty_worksheet_attachment_required': False})
        Partner = cls.env['res.partner']
        cls.addr_main = Partner.create({'name': 'ABC Hotel - Main Building',
                                        'parent_id': cls.customer.id, 'type': 'delivery',
                                        'street': 'No 5 Galle Road', 'city': 'Colombo'})
        cls.addr_other = Partner.create({'name': 'ABC Hotel - Kandy',
                                         'parent_id': cls.customer.id, 'type': 'delivery',
                                         'street': '12 Peradeniya Road', 'city': 'Kandy'})

    # ------------------------------------------------------------------ helpers
    def _ac_card(self, site=None, due_in=10, partner=None):
        today = self.company._warranty_today()
        partner = partner or self.customer
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'partner_shipping_id': (site or (self.addr_main if partner == self.customer
                                             else partner)).id,
            'order_line': [(0, 0, {'product_id': self.product.id})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, today - relativedelta(months=4) + timedelta(days=due_in))
        card.action_confirm_warranty()
        return card

    def _first(self, card):
        return card.service_entitlement_ids.sorted('service_no')[:1]

    def _case(self, services, site=None, ticket=None):
        ticket = ticket or self._ticket(warranty_site_id=(site or self.addr_main).id)
        action = ticket.with_user(self.helpdesk_user).action_view_warranty_pending_services()
        case = self.env['warranty.case'].browse(services.with_user(self.helpdesk_user)
                                                .with_context(action['context'])
                                                .action_create_warranty_case_from_services()['res_id'])
        case.with_user(self.creator).requested_item_ids = self.item_service
        return case

    def _job(self, card, site=None, ticket=None, plan=False):
        case = self._case(self._first(card), site=site, ticket=ticket)
        case.with_user(self.helpdesk_user).action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'eligible')
        case.with_user(self.approver_a).action_approve_case()
        job = self.env['warranty.service.job'].browse(
            case.with_user(self.helpdesk_user).action_prepare_service_job()['res_id'])
        if plan:
            job.with_user(self.helpdesk_user).write({
                'planned_date': fields.Datetime.now() + timedelta(days=3),
                'main_technician_id': self.tech.id})
            job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        return job

    def _share(self, jobs, user=None):
        user = user or self.helpdesk_user
        action = jobs.with_user(user).action_open_shared_visit_wizard()
        with Form(self.env[action['res_model']].with_user(user)
                  .with_context(action['context'])) as form:
            form.planned_date = fields.Datetime.now() + timedelta(days=1)
            form.main_technician_id = self.tech
        result = form.record.action_apply()
        return self.env['project.task'].browse(result['res_id'])

    def _work(self, task):
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Shared visit'}).save_timesheet()

    def _line(self, task, job):
        return task.warranty_shared_line_ids.filtered(lambda line: line.job_id == job)

    def _not_completed(self, task, job, action='reschedule'):
        with Form(self.env['warranty.visit.noncompletion.wizard'].with_user(self.tech)
                  .with_context(default_task_id=task.id, default_job_id=job.id)) as form:
            form.reason = 'customer_unavailable'
            form.next_action = action
            form.notes = 'Unit room locked'
        form.record.action_apply()

    # ------------------------------------------------------------------ tests
    def test_301_one_visit_jobs_stay_separate(self):
        """Two jobs (cards A / B, own tickets and cases, Draft + Planned) -> ONE visit linked to
        both, no new job, no ticket on the visit (Q3); each job keeps its case, card, services
        and worksheets; job A completed alone (only its service consumed), job B Not Completed
        -> the visit closes (Q7); job B continues with its own next visit (Q5)."""
        card_a, card_b = self._ac_card(), self._ac_card(due_in=100)
        job_a, job_b = self._job(card_a), self._job(card_b, plan=True)
        self.assertEqual((job_a.state, job_b.state), ('draft', 'planned'))
        jobs = job_a | job_b
        job_count = self.env['warranty.service.job'].search_count([])
        task = self._share(jobs)
        self.assertEqual(self.env['warranty.service.job'].search_count([]), job_count)
        self.assertEqual(self.env['project.task'].search_count(
            [('warranty_shared_job_ids', 'in', jobs.ids)]), 1)
        self.assertEqual((task.warranty_shared_job_ids, task.warranty_service_job_id.ids,
                          task.helpdesk_ticket_id.ids, task.user_ids),
                         (jobs, [], [], self.tech))
        self.assertEqual(task.warranty_entitlement_ids, jobs.entitlement_ids)
        for job, card in ((job_a, card_a), (job_b, card_b)):
            self.assertEqual((job.state, job.warranty_case_id.state, job.warranty_card_id,
                              job.visit_count, job.shared_visit_ids),
                             ('confirmed', 'job_created', card, 1, task))
            self.assertEqual(set(job.entitlement_ids.mapped('state')), {'job_created'})
            self.assertEqual(job.worksheet_ids.task_id, task)
            self.assertEqual(job.worksheet_ids.entitlement_id, job.entitlement_ids)
            self.assertEqual(card.service_job_count, 1)
        self.assertEqual(len(task.warranty_shared_line_ids), 2)
        with self.assertRaisesRegex(UserError, 'shared visit'):
            task.with_user(self.tech).action_warranty_complete_visit()
        with self.assertRaisesRegex(UserError, 'already has a Field Service visit'):
            jobs.with_user(self.helpdesk_user).action_open_shared_visit_wizard()
        # one timer starts both jobs
        self._work(task)
        self.assertEqual(jobs.mapped('state'), ['in_progress', 'in_progress'])
        self._line(task, job_a).with_user(self.tech).action_complete()
        self.assertEqual((job_a.state, job_a.entitlement_ids.state, card_a.free_services_used),
                         ('completed', 'completed', 1))
        self.assertEqual((job_b.state, job_b.entitlement_ids.state, card_b.free_services_used),
                         ('in_progress', 'in_progress', 0))
        self.assertEqual(job_b.worksheet_ids.state, 'in_progress')
        self.assertFalse(task.fsm_done, 'the visit stays open for job B')
        self.assertEqual(self._line(task, job_a).outcome, 'completed')
        self._not_completed(task, job_b)
        self.assertEqual((job_b.state, self._line(task, job_b).outcome),
                         ('incomplete', 'rescheduled'))
        self.assertEqual(job_b.entitlement_ids.state, 'in_progress', 'not consumed')
        self.assertTrue(task.fsm_done and task.state == '1_done')
        self.assertEqual(job_a.state, 'completed', 'job A unchanged')
        # job B: its own next visit (existing single-job workflow)
        plan = Form(self.env['warranty.service.job.plan.wizard'].with_user(self.helpdesk_user)
                    .with_context(default_job_id=job_b.id))
        plan.planned_date = fields.Datetime.now() + timedelta(days=4)
        plan.main_technician_id = self.tech
        plan.save().action_apply()
        own = job_b.visit_ids
        self.assertEqual((len(own), own.warranty_visit_no, own.warranty_service_job_id),
                         (1, 2, job_b))
        self._work(own)
        own.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual((job_b.state, card_b.free_services_used), ('completed', 1))
        self.assertEqual(card_a.free_services_used, 1, 'consumed once')

    def test_302_validation_and_all_or_nothing(self):
        """Customer, site, readiness, one job, Helpdesk users, other company; a job failing
        its Confirm checks refuses the whole visit (nothing changed)."""
        card_a, card_b = self._ac_card(), self._ac_card()
        job_a, job_b = self._job(card_a), self._job(card_b)
        jobs = job_a | job_b
        with self.assertRaisesRegex(UserError, 'two or more'):
            job_a.with_user(self.helpdesk_user).action_open_shared_visit_wizard()
        with self.assertRaises(AccessError):
            jobs.with_user(self.tech).action_open_shared_visit_wizard()
        with self.assertRaises(AccessError):
            jobs.with_user(self.foreign_user).action_open_shared_visit_wizard()
        kandy = self._job(self._ac_card(site=self.addr_other), site=self.addr_other)
        with self.assertRaisesRegex(UserError, 'same service site'):
            (job_a | kandy).with_user(self.helpdesk_user).action_open_shared_visit_wizard()
        other_job = self._job(self._ac_card(partner=self.other_customer), ticket=self._ticket(
            partner_id=self.other_customer.id, warranty_site_id=self.other_customer.id))
        with self.assertRaisesRegex(UserError, 'one customer'):
            (job_a | other_job).with_user(self.helpdesk_user).action_open_shared_visit_wizard()
        # job B's ticket closed: Confirm check fails -> no visit, job A unchanged
        folded = self.env['helpdesk.stage'].create({'name': 'Shared Closed', 'fold': True,
                                                   'team_ids': [(4, self.team.id)]})
        job_b.helpdesk_ticket_id.stage_id = folded
        tasks = self.env['project.task'].search_count([])
        service_state = job_a.entitlement_ids.state
        with self.assertRaisesRegex(UserError, job_b.name):
            self._share(jobs)
        self.assertEqual(self.env['project.task'].search_count([]), tasks)
        self.assertEqual((job_a.state, job_a.planned_date, job_a.entitlement_ids.state),
                         ('draft', False, service_state))

    def test_303_common_ticket_cancel_hold_batch(self):
        """One ticket for both jobs: the visit belongs to it (Q3); Cancel Job on job A releases
        only its service (job B continues); batch completion refuses the shared visit (Q8);
        Awaiting Parts blocks only job B until resumed; the visit closes with job B."""
        ticket = self._ticket(warranty_site_id=self.addr_main.id)
        card_a, card_b = self._ac_card(), self._ac_card()
        job_a, job_b = self._job(card_a, ticket=ticket), self._job(card_b, ticket=ticket)
        task = self._share(job_a | job_b)
        self.assertEqual(task.helpdesk_ticket_id, ticket)
        self.assertIn('shared Field Service visit', job_a._warranty_batch_problems()[0])
        job_a.with_user(self.helpdesk_user)._warranty_cancel_job('Customer sold unit A')
        self.assertEqual((job_a.state, self._line(task, job_a).outcome,
                          job_a.entitlement_ids.merge_status), ('cancelled', 'cancelled',
                                                                'not_merged'))
        self.assertEqual((job_b.state, job_b.entitlement_ids.state), ('confirmed', 'job_created'))
        self.assertFalse(task.fsm_done)
        self._work(task)
        self.assertEqual(job_b.state, 'in_progress')
        job_b.with_user(self.helpdesk_user)._warranty_set_hold('awaiting_parts', 'Capacitor')
        with self.assertRaisesRegex(UserError, 'resume it first'):
            self._line(task, job_b).with_user(self.tech).action_complete()
        job_b.with_user(self.helpdesk_user)._warranty_set_hold('resume', 'Part arrived')
        self._line(task, job_b).with_user(self.tech).action_complete()
        self.assertEqual((job_b.state, card_b.free_services_used, card_a.free_services_used),
                         ('completed', 1, 0))
        self.assertTrue(task.fsm_done)
        with self.assertRaisesRegex(UserError, 'cannot be changed|closed'):
            task.with_user(self.tech).write({'user_ids': [(6, 0, [])]})
