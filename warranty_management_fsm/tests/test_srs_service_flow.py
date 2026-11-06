import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation

from .common import ServiceJobCommon, link_case, manual_case

SIGNATURE = base64.b64encode(b'customer signature')


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestSrsServiceFlow(ServiceJobCommon):
    """SRS service flow alignment + optional Case Type (doc/srs_service_flow_alignment_design.md,
    acceptance tests A-xx / B-xx)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('srs_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'srs.tech@example.com'
        cls.env['hr.employee'].create({'name': 'SRS Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False
        cls.company.write({'warranty_signoff_required': False,
                           'warranty_worksheet_checklist_required': False,
                           'warranty_worksheet_attachment_required': False,
                           'warranty_draft_job_team_id': cls.team.id})
        # Q24: the Free Service case of a service-origin job gets the policy's Automatic Case
        # Requested Items (none -> Manual Review "No Requested Items").
        cls.policy.auto_case_item_ids = cls.item_service

    # ------------------------------------------------------------------ helpers
    def _first(self, cards):
        return self.env['warranty.service.entitlement'].union(*[
            card.service_entitlement_ids.sorted('service_no')[:1] for card in cards])

    def _create_job(self, services, user=None, job=None):
        wizard = self.env['warranty.service.job.create.wizard'].with_user(
            user or self.helpdesk_user).create({
                'entitlement_ids': [(6, 0, services.ids)],
                'planned_date': fields.Datetime.now() + timedelta(days=2),
                'main_technician_id': self.tech.id,
                'job_id': job.id if job else False})
        return self.env['warranty.service.job'].browse(wizard.action_create()['res_id'])

    def _plan(self, job):
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()

    def _confirm(self, job):
        job.with_user(self.helpdesk_user).action_confirm_job()
        return job.visit_ids

    def _work(self, task):
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Visit'}).save_timesheet()

    def _undetermined_case(self, **vals):
        ticket = self._ticket(warranty_product_id=self.product.id)
        values = {'helpdesk_ticket_id': ticket.id}
        values.update(vals)
        wizard = self.env['warranty.case.create.wizard'].with_user(self.helpdesk_user).create(
            values)
        return self.env['warranty.case'].browse(wizard.action_create()['res_id'])

    # ------------------------------------------------------------------ A - service origin
    def test_a01_one_job_before_ticket(self):
        """A-01 / A-03: services of two cards (same customer / site) -> ONE Draft
        service-origin job with the planned date, no ticket / case; a second job for the same
        services is refused; a third service is added to the open Draft job."""
        second = self._card()
        services = self._first(self.card | second)
        job = self._create_job(services)
        self.assertEqual((job.state, job.job_origin, job.warranty_case_id.ids,
                          job.helpdesk_ticket_id.ids, job.entitlement_ids),
                         ('draft', 'service', [], [], services))
        self.assertEqual((job.partner_id, job.company_id, job.warranty_card_ids),
                         (self.card.partner_id, self.company, self.card | second))
        self.assertTrue(job.planned_date and job.main_technician_id == self.tech)
        self.assertEqual(set(services.mapped('merge_status')), {'merged'})
        with self.assertRaisesRegex(UserError, 'already on the open service job'):
            self._create_job(services[:1])
        third = self._first(self._card())
        self._create_job(third, job=job)
        self.assertEqual(job.entitlement_ids, services | third)
        self.assertEqual(self.env['warranty.service.job'].search_count(
            [('job_origin', '=', 'service'),
             ('entitlement_ids', 'in', (services | third).ids)]), 1)

    def test_a10_card_service_jobs_button(self):
        """Warranty Card smart button Service Jobs: case jobs, service-origin and cross-card
        jobs, cancelled included; one job opens its form, several the filtered list without
        creation; count and records follow the user's access (other company: none)."""
        self.assertEqual(self.card.service_job_count, 0)
        case_job = self._prepare(self._approved())
        case_job.with_user(self.helpdesk_user).action_cancel()
        second = self._card()
        self.assertEqual(second.service_job_count, 0)
        cross = self._create_job(self._first(self.card | second))
        self.assertEqual((case_job.job_origin, case_job.state, cross.job_origin),
                         ('case', 'cancelled', 'service'))
        self.env.invalidate_all()
        for user in (self.helpdesk_user, self.internal_user):
            card = self.card.with_user(user)
            self.assertEqual(card.service_job_count, 2)
            action = card.action_view_service_jobs()
            self.assertEqual(action['context'], {'create': False})
            self.assertEqual(self.env['warranty.service.job'].with_user(user).search(
                action['domain']), case_job | cross)
            single = second.with_user(user)
            self.assertEqual(single.service_job_count, 1)
            action = single.action_view_service_jobs()
            self.assertEqual((action['res_id'], action['views']), (cross.id, [(False, 'form')]))
        self.assertFalse(self.env['warranty.service.job'].with_user(self.foreign_user).search(
            self.card._warranty_service_job_domain()))
        with self.assertRaises(AccessError):
            self.card.with_user(self.foreign_user).read(['service_job_count'])
        view = self.env.ref('warranty_management_fsm.warranty_card_view_form_service_origin')
        self.assertIn('invisible="service_job_count == 0"', view.arch_db)

    def test_a02_incompatible_services(self):
        """A-02: other customer, inactive (completed) service, other site refused."""
        other = self.env['res.partner'].create({'name': 'Other Customer SRS'})
        foreign = self._first(self._card(partner=other))
        with self.assertRaisesRegex(UserError, 'one customer and one company'):
            self._create_job(self._first(self.card) | foreign)
        kandy = self.env['res.partner'].create({
            'name': 'Kandy Site', 'parent_id': self.customer.id, 'type': 'delivery',
            'street': '12 Peradeniya Road', 'city': 'Kandy'})
        far = self._first(self._card(site=kandy))
        with self.assertRaisesRegex(UserError, 'other service address'):
            self._create_job(self._first(self.card) | far)
        with self.assertRaises(AccessError):
            self._create_job(self._first(self.card), user=self.internal_user)

    def test_a04_link_or_create_ticket(self):
        """A-04 / A-05 / D-C / G6: an open warranty ticket of the customer is linked (no new
        ticket) and no case is created; the Free Service case created manually on the ticket
        (Warranty Cases > New) with the job's services is linked to the job; Check Eligibility;
        no general approval (D-A); Confirm refused before, accepted after."""
        services = self._first(self.card)
        job = self._create_job(services)
        self._plan(job)
        with self.assertRaisesRegex(UserError, 'Create or Link Helpdesk Ticket'):
            self._confirm(job)
        open_ticket = self._ticket(is_warranty=True, warranty_site_address='12 Lake Road')
        self.assertIn(open_ticket, job._warranty_ticket_candidates())
        tickets = self.env['helpdesk.ticket'].search_count([])
        cases = self.env['warranty.case'].search_count([])
        wizard = Form(self.env['warranty.service.job.ticket.wizard'].with_user(
            self.helpdesk_user).with_context(default_job_id=job.id))
        self.assertEqual(wizard.mode, 'link')
        wizard.ticket_id = open_ticket
        wizard.save().action_apply()
        self.assertEqual(self.env['helpdesk.ticket'].search_count([]), tickets)
        self.assertEqual((job.helpdesk_ticket_id, job.warranty_case_id), (open_ticket,
                                                                         self.env['warranty.case']))
        self.assertEqual(self.env['warranty.case'].search_count([]), cases)
        with self.assertRaisesRegex(UserError, 'no warranty case yet'):
            self._confirm(job)
        with self.assertRaisesRegex(UserError, 'already has its Helpdesk ticket'):
            job.with_user(self.helpdesk_user)._warranty_link_ticket()
        case = manual_case(open_ticket, services.with_user(self.helpdesk_user))
        self.assertEqual(job.warranty_case_id, case)
        self.assertEqual(self.env['warranty.case'].search_count([]), cases + 1)
        self.assertEqual((case.helpdesk_ticket_id, case.case_type, case.service_entitlement_ids,
                          case.state, case.eligibility_result),
                         (open_ticket, 'free_service', services, 'eligibility_checked',
                          'eligible'))
        self.assertEqual((case.service_card_ids, case.service_unit_ids),
                         (self.card, self.card.unit_warranty_ids))
        self.assertEqual(job.helpdesk_ticket_id, open_ticket)
        self.assertEqual((case.warranty_site_address, job.warranty_site_address),
                         ('12 Lake Road', '12 Lake Road'))
        self.assertTrue(job.message_ids.filtered(lambda m: case.name in (m.body or '')))
        self.assertFalse(case.case_approval_activity_ids.filtered('active'))
        task = self._confirm(job)
        self.assertEqual((job.state, case.state, len(task), task.helpdesk_ticket_id),
                         ('confirmed', 'job_created', 1, open_ticket))
        self.assertEqual(set(services.mapped('state')), {'job_created'})

    def test_a05_closed_or_ineligible_case_blocks(self):
        """A-05: the job is not confirmed while its ticket is closed."""
        job = self._create_job(self._first(self.card))
        self._plan(job)
        case = link_case(job.with_user(self.helpdesk_user))
        self.assertTrue(case.helpdesk_ticket_id.is_warranty)
        self.assertEqual(case.helpdesk_ticket_id.team_id, self.team)
        closed = self.env['helpdesk.stage'].create({'name': 'SRS Closed', 'fold': True,
                                                    'team_ids': [(6, 0, self.team.ids)]})
        case.helpdesk_ticket_id.stage_id = closed
        with self.assertRaisesRegex(UserError, 'closed'):
            self._confirm(job)

    def test_a05b_check_eligibility_from_job(self):
        """JOB/000008 case: no Automatic Case Requested Items -> the linked case is Manual
        Review ("No Requested Items"), shown on the job with its reason; Confirm blocked;
        after the case is corrected, Check Eligibility on the job (the case's own action and
        rights) makes it Eligible and the job can be confirmed."""
        self.policy.auto_case_item_ids = False
        job = self._create_job(self._first(self.card))
        self._plan(job)
        case = link_case(job.with_user(self.helpdesk_user))
        self.assertEqual((job.case_state, job.case_eligibility_result),
                         ('eligibility_checked', 'manual_review'))
        self.assertIn('No Requested Items', job.case_eligibility_reason)
        with self.assertRaisesRegex(UserError, 'Eligible'):
            self._confirm(job)
        with self.assertRaises(AccessError):
            job.with_user(self.tech).action_check_case_eligibility()
        case.with_user(self.creator).requested_item_ids = self.item_service
        job.with_user(self.helpdesk_user).action_check_case_eligibility()
        self.assertEqual((job.case_eligibility_result, job.case_eligibility_reason),
                         ('eligible', False))
        self._confirm(job)
        self.assertEqual(job.state, 'confirmed')
        with self.assertRaisesRegex(UserError, 'before the service job is confirmed'):
            job.with_user(self.helpdesk_user).action_check_case_eligibility()

    def test_a05c_helpdesk_ticket_smart_button(self):
        """Helpdesk Ticket smart button: hidden before Create or Link Helpdesk Ticket; after a
        new ticket (and for a linked existing ticket) count 1 and the exact ticket opens in
        form view; count follows the user's ticket access."""
        job = self._create_job(self._first(self.card))
        self.assertEqual(job.with_user(self.helpdesk_user).helpdesk_ticket_count, 0)
        with self.assertRaises(UserError):
            job.with_user(self.helpdesk_user).action_view_helpdesk_ticket()
        case = link_case(job.with_user(self.helpdesk_user))
        job.invalidate_recordset()
        self.assertEqual(job.with_user(self.helpdesk_user).helpdesk_ticket_count, 1)
        action = job.with_user(self.helpdesk_user).action_view_helpdesk_ticket()
        self.assertEqual((action['res_model'], action['res_id'], action['views']),
                         ('helpdesk.ticket', case.helpdesk_ticket_id.id, [(False, 'form')]))
        Ticket = self.env['helpdesk.ticket'].with_user(self.tech)
        visible = Ticket.has_access('read') and bool(Ticket.search_count(
            [('id', '=', job.helpdesk_ticket_id.id)]))
        self.assertEqual(job.with_user(self.tech).helpdesk_ticket_count, int(visible))
        # linked existing ticket
        ticket = self._ticket(is_warranty=True)
        other = self._create_job(self._first(self._card()))
        wizard = Form(self.env['warranty.service.job.ticket.wizard'].with_user(
            self.helpdesk_user).with_context(default_job_id=other.id))
        wizard.ticket_id = ticket
        wizard.save().action_apply()
        self.assertFalse(other.warranty_case_id)
        self.assertEqual(other.with_user(self.helpdesk_user).helpdesk_ticket_count, 1)
        self.assertEqual(other.with_user(self.helpdesk_user).action_view_helpdesk_ticket()['res_id'],
                         ticket.id)

    def test_a05d_manual_case_guards(self):
        """Manual case (Warranty Cases > New) for a service-origin job: refused before the
        job's ticket, on another ticket, with only part of the job's services or with the
        services of two jobs (duplicate protection kept); the matching case is linked to the
        job; a job with a ticket gets no further free services."""
        services = self._first(self.card | self._card())
        job = self._create_job(services)
        other_ticket = self._ticket(is_warranty=True)
        Case = services.with_user(self.helpdesk_user)
        with self.assertRaises(ValidationError):
            manual_case(other_ticket, Case)
        ticket = job.with_user(self.helpdesk_user)._warranty_link_ticket()
        self.assertEqual((job.helpdesk_ticket_id, job.origin_ticket_id), (ticket, ticket))
        self.assertFalse(ticket.warranty_case_ids)
        with self.assertRaises(UserError):
            job.with_user(self.helpdesk_user).write({'origin_ticket_id': False})
        with self.assertRaisesRegex(UserError, 'without Helpdesk ticket'):
            self._first(self._card()).with_user(self.helpdesk_user)._warranty_create_service_job(
                job=job)
        with self.assertRaises(ValidationError):
            manual_case(other_ticket, Case)
        with self.assertRaises(ValidationError):
            manual_case(ticket, Case[:1])
        second = self._create_job(self._first(self._card()))
        second.with_user(self.helpdesk_user)._warranty_link_ticket(ticket=ticket)
        with self.assertRaisesRegex(ValidationError, 'several service jobs'), \
                self.env.cr.savepoint():
            manual_case(ticket, Case | second.entitlement_ids.with_user(self.helpdesk_user))
        self.env.invalidate_all()
        self.assertFalse(self.env['warranty.case'].search([('helpdesk_ticket_id', '=', ticket.id)]))
        case = manual_case(ticket, Case)
        self.assertEqual((job.warranty_case_id, ticket.warranty_case_ids, second.warranty_case_id),
                         (case, case, self.env['warranty.case']))
        self.assertEqual(case.service_unit_ids, services.warranty_card_id.unit_warranty_ids)

    def test_a06_visit_worksheets_completion_once(self):
        """A-06 / A-07: one visit, one worksheet per service; completion consumes once; a
        second Confirm is refused."""
        second = self._card()
        services = self._first(self.card | second)
        job = self._create_job(services)
        link_case(job.with_user(self.helpdesk_user))
        self._plan(job)
        task = self._confirm(job)
        self.assertEqual((len(task), len(job.worksheet_ids)), (1, 2))
        with self.assertRaises(UserError):
            self._confirm(job)
        self._work(task)
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(set(services.mapped('state')), {'completed'})
        self.assertEqual((job.state, job.warranty_case_id.state), ('completed', 'completed'))
        self.assertEqual(self.card.free_services_used, 1)

    def test_a07_cancel_releases_services(self):
        services = self._first(self.card)
        job = self._create_job(services)
        job.with_user(self.helpdesk_user).action_cancel()
        self.assertEqual((job.state, services.merge_status, services.state),
                         ('cancelled', 'not_merged', 'draft'))
        self.assertEqual(self._create_job(services).entitlement_ids, services)

    def test_a08_caseless_job_guards(self):
        """Case-less jobs: only Draft / Planned actions; origin fields and case not writable."""
        job = self._create_job(self._first(self.card))
        for vals in ({'job_origin': 'case'}, {'origin_partner_id': False}):
            with self.assertRaises(UserError):
                job.with_user(self.helpdesk_user).write(vals)
        with self.assertRaises(ValidationError):
            job.sudo()._warranty_service_marker().write({'state': 'confirmed'})
        with self.assertRaises(UserError):
            self.env['warranty.service.job'].with_user(self.helpdesk_user).create({
                'job_origin': 'service'})

    def test_a09_usage_alert(self):
        """A-09 / D-E: a completed worksheet reading reaching the Usage Threshold of the next
        open usage-based service gives one To-Do; readings of open worksheets do not."""
        self.company.warranty_service_alert_user_ids = self.helpdesk_user
        policy = self.env['warranty.policy'].create({
            'name': 'SRS Usage Policy', 'warranty_duration': 12, 'warranty_duration_unit': 'months',
            'warranty_basis': 'usage', 'usage_limit': 2000, 'usage_unit': 'operating_hours',
            'free_service_count': 2, 'free_service_period': 12,
            'free_service_period_unit': 'months', 'schedule_method': 'equal_interval',
            'auto_create_services': True, 'usage_alert_percentage': 80,
            'covered_item_ids': [(6, 0, self.item_service.ids)]})
        product = self.env['product.product'].create({
            'name': 'SRS Usage AC', 'type': 'service', 'warranty_applicable': True})
        product.product_tmpl_id.warranty_policy_id = policy
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'order_line': [(0, 0, {'product_id': product.id})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, fields.Date.today() - timedelta(days=30))
        card.action_confirm_warranty()
        service = card.service_entitlement_ids.sorted('service_no')[:1]
        self.assertEqual((service.usage_due, service.usage_threshold), (1000.0, 800.0))
        job = self._create_job(self._first(self.card))
        link_case(job.with_user(self.helpdesk_user))
        self._plan(job)
        task = self._confirm(job)
        Sheet = self.env['warranty.job.worksheet'].sudo()
        vals = {'job_id': job.id, 'task_id': task.id, 'entitlement_id': service.id,
                'usage_required': True, 'usage_unit': 'operating_hours', 'current_usage': 900}
        Sheet.create(vals)
        Entitlement = self.env['warranty.service.entitlement']
        Entitlement._warranty_check_usage_alerts(card)
        self.assertFalse(service.usage_alert_date, 'open worksheet reading not used')
        Sheet.create(dict(vals, state='completed', current_usage=700))
        Entitlement._warranty_check_usage_alerts(card)
        self.assertFalse(service.usage_alert_date, 'below the threshold')
        Sheet.create(dict(vals, state='completed', current_usage=850))
        Entitlement._warranty_check_usage_alerts(card)
        self.assertEqual(service.usage_alert_reading, 850)
        todo = service.activity_ids.filtered(lambda a: 'Usage alert' in (a.summary or ''))
        self.assertEqual(todo.user_id, self.helpdesk_user)
        Entitlement._warranty_check_usage_alerts(card)
        self.assertEqual(len(service.activity_ids.filtered(
            lambda a: 'Usage alert' in (a.summary or ''))), 1, 'no duplicate')

    # ------------------------------------------------------------------ B - inspection
    def test_b01_case_without_type(self):
        """B-01 / G3: ticket and case without Case Type; free services refused."""
        case = self._undetermined_case()
        self.assertEqual((case.case_type, case.inspection_state), (False, 'required'))
        with self.assertRaisesRegex(ValidationError, 'no Case Type yet'):
            self._undetermined_case(
                service_entitlement_ids=[(6, 0, self._first(self.card).ids)])

    def test_b02_to_b05_inspection_flow(self):
        """B-02..B-05 / G2 / G4: preliminary check -> inspection job (no services, no hold, no
        Complete Visit / approval) -> Complete Inspection with findings and Case Type -> case
        New with the type -> full eligibility -> approval -> normal job."""
        case = self._undetermined_case()
        case.with_user(self.helpdesk_user).requested_item_ids = self.item_service
        case.with_user(self.helpdesk_user).action_check_eligibility()
        self.assertEqual((case.state, case.eligibility_result),
                         ('eligibility_checked', 'preliminary_passed'))
        self.assertIn('preliminary check passed', ' '.join(case.message_ids.mapped('body')))
        self.assertFalse(case.case_approval_activity_ids.filtered('active'))
        with self.assertRaises(UserError):
            case.with_user(self.approver_a).action_approve_case()
        with self.assertRaises(UserError):
            case.with_user(self.helpdesk_user).action_prepare_service_job()
        with self.assertRaisesRegex(UserError, 'only be changed while'):
            case.with_user(self.helpdesk_user).case_type = 'warranty_complaint'
        job = self.env['warranty.service.job'].browse(
            case.with_user(self.helpdesk_user).action_prepare_inspection_job()['res_id'])
        self.assertEqual((job.job_type, job.entitlement_ids.ids, job.state),
                         ('warranty_inspection', [], 'draft'))
        with self.assertRaisesRegex(UserError, 'already has the open service job'):
            case.with_user(self.helpdesk_user).action_prepare_inspection_job()
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        self._plan(job)
        task = self._confirm(job)
        self.assertEqual((len(task), len(job.worksheet_ids), case.state),
                         (1, 1, 'job_created'))
        if hasattr(job, '_warranty_mrf_check_allowed'):
            # warranty_management_mrf installed: no parts on an inspection / undetermined case.
            with self.assertRaisesRegex(UserError, 'inspection job'):
                job._warranty_mrf_check_allowed()
            with self.assertRaisesRegex(UserError, 'not determined'):
                case._warranty_mrf_check_allowed()
        task.with_user(self.tech).action_timer_start()
        with self.assertRaisesRegex(UserError, 'not put on hold'):
            job.with_user(self.tech)._warranty_set_hold('awaiting_parts', 'parts')
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Inspection'}).save_timesheet()
        with self.assertRaisesRegex(UserError, 'Complete Inspection'):
            job.with_user(self.tech)._warranty_complete_visit(task, batch=True)
        result = task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(result['res_model'], 'warranty.inspection.result.wizard')
        wizard = self.env['warranty.inspection.result.wizard'].with_user(self.tech).create({
            'task_id': task.id, 'diagnosis': 'Compressor relay burnt'})
        self.assertTrue(wizard.case_type_required)
        with self.assertRaisesRegex(UserError, 'final Case Type'):
            wizard.action_apply()
        wizard.write({'case_type': 'warranty_complaint', 'failure_category': 'electrical'})
        wizard.action_apply()
        self.assertEqual((job.state, task.state), ('completed', '1_done'))
        self.assertEqual((case.state, case.case_type, case.inspection_state,
                          case.inspection_findings, case.inspected_by_id, case.failure_category,
                          case.inspection_job_id),
                         ('new', 'warranty_complaint', 'done', 'Compressor relay burnt',
                          self.tech, 'electrical', job))
        self.assertFalse(self.card.service_entitlement_ids.filtered(
            lambda s: s.state == 'completed'), 'nothing consumed')
        case.with_user(self.creator).action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'eligible')
        case.with_user(self.approver_a).action_approve_case()
        normal = self._prepare(case)
        self.assertEqual((normal.job_type, normal.job_origin), ('warranty', 'case'))

    def test_b06_closure_and_chargeable_guards(self):
        """B-06 / G1: no completion / closure without Case Type; a team requiring inspection
        uses the chargeable inspection only."""
        case = self._undetermined_case()
        with self.assertRaisesRegex(UserError, 'cannot be completed or closed'):
            case.sudo().write({'state': 'closed'})
        case.with_user(self.helpdesk_user).action_check_eligibility()
        self.team.write({'warranty_inspection_required': True,
                         'warranty_inspection_product_id': self.env['product.product'].create({
                             'name': 'SRS Inspection Fee', 'type': 'service',
                             'list_price': 50}).id})
        # The team value is copied when the case is created; the case value decides.
        case.sudo().warranty_inspection_required = True
        with self.assertRaisesRegex(UserError, 'requires an inspection quotation'):
            case.with_user(self.helpdesk_user).action_prepare_inspection_job()
        with self.assertRaisesRegex(UserError, 'only a chargeable inspection'):
            case._warranty_convert_chargeable('repair')
        # Existing chargeable workflow (quotation needs Sales rights): as the superuser here.
        case._warranty_convert_chargeable('inspection')
        self.assertEqual((case.state, case.chargeable_type, case.case_type),
                         ('chargeable', 'inspection', False))

    def test_b07_case_type_change_while_new(self):
        """G2: Helpdesk users may set / change the Case Type while the case is New (tracked)."""
        case = self._undetermined_case()
        case.with_user(self.helpdesk_user).case_type = 'warranty_complaint'
        self.assertEqual((case.case_type, case.inspection_state), ('warranty_complaint', False))
        with self.assertRaises(UserError):
            case.with_user(self.helpdesk_user).inspection_findings = 'typed by hand'

    # ------------------------------------------------------------------ G5 fault report
    def test_g5_fault_during_free_service(self):
        """G5: a fault found during a free-service visit -> one complaint case on the same
        ticket; duplicates refused; the free service case and consumption unchanged."""
        services = self._first(self.card)
        job = self._create_job(services)
        source = link_case(job.with_user(self.helpdesk_user))
        self._plan(job)
        task = self._confirm(job)
        unit = self.card.unit_warranty_ids[:1]
        complaint = job.with_user(self.tech)._warranty_report_fault('Gas leak at the valve',
                                                                    unit=unit)
        self.assertEqual((complaint.helpdesk_ticket_id, complaint.case_type,
                          complaint.source_service_job_id, complaint.warranty_unit_id),
                         (source.helpdesk_ticket_id, 'warranty_complaint', job, unit))
        with self.assertRaisesRegex(UserError, 'already reported'):
            job.with_user(self.tech)._warranty_report_fault('Gas leak again', unit=unit)
        self.assertEqual(source.service_entitlement_ids, services)
        self._work(task)
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual((services.state, source.state, complaint.state),
                         ('completed', 'completed', 'new'))

    # ------------------------------------------------------------------ wizard from the job's ticket
    def _case_wizard(self, ticket):
        action = ticket.with_user(self.helpdesk_user).action_create_warranty_case()
        self.assertEqual(action['res_model'], 'warranty.case.create.wizard')
        return Form(self.env[action['res_model']].with_user(self.helpdesk_user)
                    .with_context(action['context']))

    def test_a05e_wizard_merged_job(self):
        """Merged job: the wizard is prefilled from the job, no arbitrary header product, the
        case links to the same job; afterwards the button and a stale wizard open that case."""
        second = self._card()
        services = self._first(self.card | second)
        job = self._create_job(services)
        ticket = job.with_user(self.helpdesk_user)._warranty_link_ticket()
        other = self._first(self._card())
        self._create_job(other)
        jobs_before = self.env['warranty.service.job'].search_count([])
        form = self._case_wizard(ticket)
        self.assertEqual(form.case_type, 'free_service')
        self.assertEqual(form.priority, ticket.priority or '1')
        self.assertEqual(form.site_id, job.site_id)
        self.assertTrue(form.customer_complaint)
        self.assertFalse(form.product_id, 'several units: no arbitrary product')
        self.assertFalse(form.serial_id, 'several units: no arbitrary serial')
        wizard = form.save()
        stale = self._case_wizard(ticket).save()
        self.assertEqual(wizard.service_entitlement_ids, services)
        self.assertEqual(wizard.available_service_ids & services, services)
        for service in services:
            unit = service.warranty_card_id.unit_warranty_ids
            self.assertEqual(service.warranty_job_units_display, '%s / %s / %s' % (
                unit.name, unit.product_id.display_name,
                ', '.join(unit.serial_ids.mapped('name')) or '-'))
        self.assertNotIn(other, wizard.available_service_ids, "another open job's service")
        used = [card.free_services_used for card in self.card | second]
        case = self.env['warranty.case'].browse(wizard.action_create()['res_id'])
        self.assertEqual(job.warranty_case_id, case)
        self.assertEqual(case.service_entitlement_ids, services)
        self.assertEqual(case.service_unit_ids, services.warranty_card_id.unit_warranty_ids)
        self.assertFalse(case.product_id or case.serial_id)
        self.assertEqual(self.env['warranty.service.job'].search_count([]), jobs_before)
        self.assertEqual([card.free_services_used for card in self.card | second], used,
                         'nothing consumed by the case')
        for action in (ticket.with_user(self.helpdesk_user).action_create_warranty_case(),
                       stale.action_create()):
            self.assertEqual((action['res_model'], action['res_id']), ('warranty.case', case.id))
        self.assertEqual(ticket.warranty_case_ids, case)

    def test_a05f_wizard_single_service_job(self):
        """Single service, single unit: its Product in the header; the eligibility still runs."""
        services = self._first(self.card)
        unit = self.card.unit_warranty_ids
        self.assertEqual(len(unit), 1)
        job = self._create_job(services)
        ticket = job.with_user(self.helpdesk_user)._warranty_link_ticket()
        form = self._case_wizard(ticket)
        self.assertEqual(form.product_id, unit.product_id)
        case = self.env['warranty.case'].browse(form.save().action_create()['res_id'])
        self.assertEqual((job.warranty_case_id, case.service_entitlement_ids), (case, services))
        case.with_user(self.helpdesk_user).action_check_eligibility()
        self.assertTrue(case.eligibility_result)

    def test_a05g_wizard_second_job_and_plain_ticket(self):
        """A ticket with two waiting jobs gets one case per job; the wizard's table cannot leave
        the job (forced at creation); tickets without job keep the plain wizard."""
        first = self._create_job(self._first(self._card()))
        ticket = first.with_user(self.helpdesk_user)._warranty_link_ticket()
        second = self._create_job(self._first(self._card()))
        second.with_user(self.helpdesk_user)._warranty_link_ticket(ticket=ticket)
        wizard = self._case_wizard(ticket).save()
        self.assertEqual(wizard.service_entitlement_ids, first.entitlement_ids)
        wizard.service_entitlement_ids = first.entitlement_ids[:0]
        case = self.env['warranty.case'].browse(wizard.action_create()['res_id'])
        self.assertEqual(first.warranty_case_id, case)
        self.assertEqual(self._case_wizard(ticket).save().service_entitlement_ids,
                         second.entitlement_ids)
        plain = self._case_wizard(self._ticket(is_warranty=True))
        self.assertFalse(plain.case_type)
        self.assertFalse(plain.save().service_entitlement_ids)

    # ------------------------------------------------------------------ Warranty tab protection
    def _assert_ticket_locked(self, ticket):
        """Attempted changes as a Helpdesk user and as a manager; the job and case keep theirs."""
        other = self._card()
        for user in (self.helpdesk_user, self.helpdesk_manager):
            mine = ticket.with_user(user)
            for vals in ({'warranty_product_id': other.product_id.id},
                         {'warranty_serial_id': self.env['stock.lot'].create({
                             'name': 'LOCK-%s-%s' % (other.id, user.id), 'product_id': other.product_id.id}).id},
                         {'partner_id': self.env['res.partner'].create({'name': 'Stranger'}).id}):
                with self.assertRaisesRegex(UserError, 'cannot be changed on the ticket'):
                    mine.write(vals)
        return other

    def test_a05h_linked_tab_merged_job(self):
        """Merged job: linked services shown and out of Pending, nothing arbitrary in the header,
        changes refused before and after the case; a cancelled job releases the ticket."""
        services = self._first(self.card | self._card())
        job = self._create_job(services)
        ticket = job.with_user(self.helpdesk_user)._warranty_link_ticket()
        self.env.invalidate_all()
        other = self._assert_ticket_locked(ticket)
        self.assertTrue(ticket.warranty_is_linked)
        self.assertEqual(ticket.warranty_linked_service_ids, services)
        self.env.invalidate_all()
        pending = ticket.warranty_pending_service_ids
        self.assertFalse(pending & services, 'pending and linked are separate')
        self.assertIn(self._first(other), pending)
        self.assertFalse(ticket.warranty_card_id or ticket.warranty_unit_id, 'merged: not one card')
        self.assertEqual(job.entitlement_ids, services, 'pending services change no link')
        case = self.env['warranty.case'].browse(
            self._case_wizard(ticket).save().action_create()['res_id'])
        self.env.invalidate_all()
        self._assert_ticket_locked(ticket)
        self.assertEqual(ticket.warranty_linked_service_ids, services)
        self.assertEqual((job.warranty_case_id, job.partner_id), (case, ticket.partner_id))
        same_customer = self.env['res.partner'].create({
            'name': 'Same customer contact', 'parent_id': ticket.partner_id.commercial_partner_id.id})
        ticket.with_user(self.helpdesk_user).write({'partner_id': same_customer.id})
        arch = self.env['helpdesk.ticket'].with_user(self.helpdesk_user).get_view(
            self.env.ref('helpdesk.helpdesk_ticket_view_form').id, 'form')['arch']
        self.assertIn('name="warranty_job_units_display"', arch)
        self.assertEqual(arch.count('readonly="warranty_is_linked"'), 3)

    def test_a05i_linked_tab_single_job_and_release(self):
        """Single service job: its own card and unit; cancelling the job frees the ticket."""
        services = self._first(self.card)
        job = self._create_job(services)
        ticket = job.with_user(self.helpdesk_user)._warranty_link_ticket()
        self.env.invalidate_all()
        self.assertEqual((ticket.warranty_card_id, ticket.warranty_unit_id),
                         (self.card, self.card.unit_warranty_ids))
        self.assertEqual(ticket.warranty_linked_service_ids, services)
        other = self._assert_ticket_locked(ticket)
        job.sudo()._warranty_service_marker().write({'state': 'cancelled'})
        self.env.invalidate_all()
        self.assertFalse(ticket.warranty_is_linked)
        ticket.with_user(self.helpdesk_user).write({'warranty_product_id': other.product_id.id})

    def test_a05j_standalone_ticket_stays_free(self):
        """A ticket without job or case keeps its free selections; its first case binds it, a
        system write (sudo) is not affected."""
        ticket = self._ticket(is_warranty=True)
        mine = ticket.with_user(self.helpdesk_user)
        product = self.card.unit_warranty_ids.product_id
        mine.write({'warranty_product_id': product.id})
        self.assertFalse(ticket.warranty_is_linked)
        self.assertEqual(ticket.warranty_card_id, self.card)
        self.assertFalse(ticket.warranty_linked_service_ids)
        case = manual_case(ticket, self._first(self.card).with_user(self.helpdesk_user))
        self.env.invalidate_all()
        self.assertTrue(ticket.warranty_is_linked)
        mine.write({'warranty_product_id': product.id})
        with self.assertRaisesRegex(UserError, 'cannot be changed on the ticket'):
            mine.write({'warranty_product_id': False})
        with self.assertRaisesRegex(UserError, 'cannot be changed on the ticket'):
            mine.write({'warranty_case_ids': [(3, case.id)]})
        ticket.sudo().write({'warranty_product_id': False})
