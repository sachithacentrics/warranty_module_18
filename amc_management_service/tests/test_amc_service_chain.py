import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.amc_management.tests.common import AmcCommon

SIGNATURE = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
    b'\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00'
    b'\x00\x00\x00IEND\xaeB`\x82')


@tagged('post_install', '-at_install', 'amc')
class TestAmcServiceChain(AmcCommon):
    """End-to-end AMC visit execution through Helpdesk Ticket -> Warranty Case (AMC) ->
    Service Job -> Field Service visit -> sign-off -> consumption (AMC-F01 .. F07, E07, E09,
    A08, H02 / H04; docs/19)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        helpdesk = ref('helpdesk.group_helpdesk_user')
        cls.user_coordinator.groups_id |= helpdesk
        cls.checker = new_test_user(cls.env, login='amc_hd_checker', name='HD Checker',
                                    groups_id=[ref('base.group_user').id, helpdesk.id],
                                    company_id=cls.company.id, company_ids=cls.company.ids)
        cls.approver = new_test_user(cls.env, login='amc_hd_approver', name='HD Approver',
                                     groups_id=[ref('base.group_user').id, helpdesk.id],
                                     company_id=cls.company.id, company_ids=cls.company.ids)
        cls.tech = new_test_user(cls.env, login='amc_tech', name='AMC Tech',
                                 groups_id=[ref('base.group_user').id,
                                            ref('industry_fsm.group_fsm_user').id],
                                 company_id=cls.company.id, company_ids=cls.company.ids)
        cls.env['hr.employee'].create({'name': 'AMC Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.team = cls.env['helpdesk.team'].create({'name': 'AMC Service Team',
                                                    'company_id': cls.company.id})
        # Merged visits = several worksheet instances on one visit: a Warranty Worksheet template
        # on the product (existing warranty rule, approved shared-worksheet fix).
        cls.instance_template = cls.env['worksheet.template'].create({
            'name': 'AMC Preventive Checklist', 'res_model': 'warranty.job.worksheet'})
        cls.equipment_untracked.product_tmpl_id.warranty_worksheet_template_id = \
            cls.instance_template
        cls.company.write({
            'warranty_case_approver_ids': [Command.set((cls.approver | cls.checker).ids)],
            'warranty_signoff_required': True,
            'warranty_worksheet_checklist_required': False,
            'warranty_worksheet_attachment_required': False,
            'warranty_draft_job_team_id': cls.team.id,
        })

    def setUp(self):
        super().setUp()
        # As the warranty FSM tests: the planned date window of free services is not tested here.
        self.startPatcher(patch.object(type(self.env['warranty.service.job']),
                                       '_warranty_planned_date_problems',
                                       lambda job, planned_date=None: []))
        self.contract = self._create_contract(lines=[
            {'product_id': self.equipment_untracked.id, 'quantity': 2.0}])
        self._sell(self.contract)
        self.preventive = self.contract.visit_ids.filtered(
            lambda v: v.visit_type == 'preventive').sorted(lambda v: (v.sequence_no, v.unit_no))

    # ------------------------------------------------------------------ helpers
    def _request(self, visits, **values):
        wizard = self.env['amc.service.request'].with_user(self.user_coordinator).create(
            dict({'visit_ids': [Command.set(visits.ids)], 'team_id': self.team.id}, **values))
        return self.env['warranty.case'].browse(wizard.action_confirm()['res_id'])

    def _approved_case(self, visits):
        case = self._request(visits)
        case.with_user(self.checker).action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'eligible', case.eligibility_reason)
        case.with_user(self.approver).action_approve_case()
        self.assertEqual(case.state, 'approved')
        return case

    def _confirmed_job(self, visits):
        case = self._approved_case(visits)
        action = case.with_user(self.checker).action_prepare_service_job()
        job = self.env['warranty.service.job'].browse(action['res_id'])
        job.with_user(self.checker).write({
            'planned_date': fields.Datetime.now() + timedelta(hours=2),
            'main_technician_id': self.tech.id})
        job.with_user(self.checker).action_prepare_for_confirmation()
        job.with_user(self.checker).action_confirm_job()
        self.assertEqual(job.state, 'confirmed')
        return job

    def _start_and_sign(self, job):
        task = job.visit_ids
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        wizard = self.env[action['res_model']].with_user(self.tech).with_context(
            action['context']).create({'time_spent': 1.0, 'description': 'AMC service'})
        wizard.save_timesheet()
        task.sudo().write({'worksheet_signature': SIGNATURE, 'worksheet_signed_by': 'Customer'})
        return task

    # ------------------------------------------------------------------ tests
    def test_tc090_end_to_end_service_chain(self):
        """TC-090 / E2E-01: two compatible AMC visits (same contract and site) merged into one
        request -> ticket (AMC tag) -> AMC case eligible -> approved -> service job with one
        worksheet per visit -> Field Service visit -> customer sign-off -> completion consumes
        both visits once; links retained for traceability."""
        visits = self.preventive[:2]
        job = self._confirmed_job(visits)
        case = job.warranty_case_id
        ticket = case.helpdesk_ticket_id
        self.assertEqual(case.case_type, 'amc')
        self.assertIn(self.env.ref('amc_management_service.helpdesk_tag_amc'), ticket.tag_ids)
        self.assertIn('2 x Preventive Visit 1 of 3', ticket.name)
        self.assertEqual(job.amc_contract_id, self.contract)
        self.assertEqual(set(visits.mapped('state')), {'in_progress'})
        self.assertEqual(len(job.worksheet_ids), 2)
        self.assertEqual(visits.worksheet_id, job.worksheet_ids)
        task = self._start_and_sign(job)
        job.visit_ids.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(job.state, 'completed')
        self.assertEqual(set(visits.mapped('state')), {'completed'})
        self.assertTrue(all('Service job %s' % job.name in v.consumption_source for v in visits))
        self.assertEqual(visits.task_id, task)
        self.assertEqual(visits.helpdesk_ticket_id, ticket)
        self.assertEqual(self.contract.preventive_done, 2)
        # E09: consumed once - a completed visit cannot be requested again.
        with self.assertRaises(UserError):
            self._request(visits[:1])

    def test_tc091_signoff_required(self):
        """TC-091 / AMC-F06: without customer sign-off the visit is not completed and the AMC
        visits are not consumed."""
        job = self._confirmed_job(self.preventive[:1])
        task = job.visit_ids
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(
            action['context']).create({'time_spent': 1.0, 'description': 'x'}).save_timesheet()
        with self.assertRaises(UserError):
            task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(self.preventive[0].state, 'in_progress')

    def test_tc092_cancelled_job_releases(self):
        """TC-092 / AMC-F07: a cancelled job keeps the AMC visit unconsumed on the case; a
        rejected case releases it to Pending."""
        job = self._confirmed_job(self.preventive[:1])
        visit = self.preventive[0]
        job.with_user(self.checker)._warranty_cancel_job('Customer not available')
        self.assertEqual(job.state, 'cancelled')
        self.assertEqual(visit.state, 'scheduled')
        self.assertFalse(visit.service_job_id)
        case = job.warranty_case_id
        case.sudo().write({'state': 'rejected'})
        self.assertEqual(visit.state, 'pending')
        self.assertFalse(visit.warranty_case_id)

    def test_tc093_incompatible_merge_refused(self):
        """TC-093 / AMC-F03: visits of other contracts, non-pending visits or visits on an open
        case cannot be requested together."""
        other = self._create_contract(plan=self.plan_project)
        self._sell(other)
        with self.assertRaises(UserError):
            self._request(self.preventive[:1] | other.visit_ids[:1])
        self._request(self.preventive[:1])
        with self.assertRaises(UserError):
            self._request(self.preventive[:1])

    def test_tc094_eligibility_on_hold_contract(self):
        """TC-094 / AMC-A08 / C04: a request is refused for a held contract; a case whose
        contract is put on hold afterwards is Not Eligible."""
        case = self._request(self.preventive[:1])
        self.contract.with_user(self.user_manager)._amc_hold('Site closed')
        case.with_user(self.checker).action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'not_eligible')
        with self.assertRaises(UserError):
            self._request(self.preventive[1:2])

    def test_tc095_manual_completion_disabled(self):
        """TC-095 / AMC-F01: with the service chain, visits are not completed manually."""
        with self.assertRaises(UserError):
            self.preventive[0].with_user(self.user_coordinator).action_open_complete_wizard()

    def test_tc096_pending_services_on_ticket(self):
        """TC-096 / AMC-F02: a Helpdesk ticket of the customer shows the pending AMC visits; the
        visits can be added to that ticket (link existing)."""
        ticket = self.env['helpdesk.ticket'].create({
            'name': 'Noise complaint', 'team_id': self.team.id,
            'partner_id': self.customer.id, 'company_id': self.company.id})
        # Preventive visits and included free services (on-demand) are both pending.
        self.assertEqual(ticket.amc_pending_visit_count, len(self.contract.visit_ids))
        case = self._request(self.preventive[:1], ticket_mode='link', ticket_id=ticket.id)
        self.assertEqual(case.helpdesk_ticket_id, ticket)
        ticket.invalidate_recordset(['amc_pending_visit_ids', 'amc_pending_visit_count'])
        self.assertEqual(ticket.amc_pending_visit_count, len(self.contract.visit_ids) - 1)

    def test_tc097_regular_warranty_case_unchanged(self):
        """TC-097 / REG-04: a non-AMC case on a customer without warranty card keeps the
        standard result (manual review); the AMC checks are not applied."""
        ticket = self.env['helpdesk.ticket'].create({
            'name': 'Complaint', 'team_id': self.team.id, 'partner_id': self.customer.id,
            'company_id': self.company.id, 'is_warranty': True})
        case = self.env['warranty.case'].create({'helpdesk_ticket_id': ticket.id,
                                                 'case_type': 'warranty_complaint'})
        case.with_user(self.checker).action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'manual_review')
        amc_case = self.env['warranty.case'].create({'helpdesk_ticket_id': ticket.id,
                                                     'case_type': 'amc'})
        amc_case.with_user(self.checker).action_check_eligibility()
        self.assertEqual(amc_case.eligibility_result, 'manual_review')
