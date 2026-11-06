from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart9JobIntegration(ServiceJobCommon):
    """Stage 9.10: controlled actions meet the existing Part 4 gates. Part 4 itself is unchanged."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('p9_job_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'p9.tech@example.com'
        cls.env['hr.employee'].create({'name': 'P9 Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False
        cls.company.write({'warranty_signoff_required': False,
                           'warranty_worksheet_checklist_required': False,
                           'warranty_exception_approver_ids': [(6, 0, cls.approver_a.ids)],
                           'warranty_exception_evidence_required': False})

    def _action(self, kind):
        action = self.card.with_user(self.helpdesk_user)._warranty_request_action(
            kind, units=self.card.unit_warranty_ids, reason='Test', reason_code='misuse')
        action.with_user(self.approver_a).action_approve()
        self.env.invalidate_all()
        return action

    def _planned_job(self):
        job = self._prepare(self._approved())
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        return job

    def test_p9_01_suspended_card_blocks_job_confirmation_until_reactivated(self):
        job = self._planned_job()
        case = job.warranty_case_id
        state = job.state
        self._action('suspend')
        job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual((job.state, case.state), (state, 'approved'), 'blocked, nothing else moves')
        self.assertFalse(job.visit_ids)
        self._action('reactivate')
        job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual(job.state, 'confirmed')

    def test_p9_02_confirmed_job_is_left_as_it_is(self):
        """Q10 is pending: work already started is not changed."""
        job = self._planned_job()
        job.with_user(self.helpdesk_user).action_confirm_job()
        visits = job.visit_ids
        action = self._action('suspend')
        self.assertIn(job.name, action.open_work_note)
        self.assertEqual((job.state, job.visit_ids, self.card.state),
                         ('confirmed', visits, 'suspended'))

    def test_p9_03_suspended_card_offers_no_pending_services(self):
        Service = self.env['warranty.service.entitlement']
        services = self.card.service_entitlement_ids
        self.assertTrue(services)
        before = Service._warranty_pending_services(self.customer, self.company)
        self.assertTrue(before & services)
        states = services.mapped('state')
        self._action('suspend')
        self.assertFalse(Service._warranty_pending_services(self.customer, self.company) & services)
        self.assertEqual(services.mapped('state'), states, 'the services themselves do not change')
        self._action('reactivate')
        self.assertTrue(Service._warranty_pending_services(self.customer, self.company) & services)

    def test_p9_04_history_from_the_job_and_open_job_blocks_transfer(self):
        job = self._planned_job()
        self.env.flush_all()
        rows = self.env['warranty.history'].search(job.action_view_warranty_history()['domain'])
        self.assertIn(job.name, rows.filtered(lambda row: row.entity == 'job').mapped('reference'))
        self.assertIn(job.name, self.card._warranty_open_work())
