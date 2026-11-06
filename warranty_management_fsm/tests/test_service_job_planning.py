import re
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobPlanning(ServiceJobCommon):
    """Phase 4.2 - planned date, main / support technicians, Draft -> Planned (approved
    D1-D4); no Field Service task yet."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech_main = cls._user('job_tech_main', 'industry_fsm.group_fsm_user')
        cls.tech_support = cls._user('job_tech_support', 'industry_fsm.group_fsm_user')
        cls.tech_foreign = cls._user('job_tech_foreign', 'industry_fsm.group_fsm_user',
                                     company=cls.other_company)

    def setUp(self):
        super().setUp()
        self.tomorrow = fields.Datetime.now() + timedelta(days=1)

    def _plan(self, job, user=None, **vals):
        values = {'planned_date': self.tomorrow, 'main_technician_id': self.tech_main.id}
        values.update(vals)
        job.with_user(user or self.helpdesk_user).write(values)
        return job

    def test_21_plan_warranty_only_job(self):
        """Warranty Only (no free service): date + main + support -> Planned; chatter; no
        Field Service task."""
        tasks = self.env['project.task'].search_count([])
        job = self._prepare(self._approved())
        self._plan(job, support_technician_ids=[(6, 0, self.tech_support.ids)])
        self.assertIn(self.tech_main, job.technician_candidate_ids)
        self.assertNotIn(self.internal_user, job.technician_candidate_ids)
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        self.assertEqual((job.state, job.merge_type), ('planned', 'none'))
        self.assertIn('ready for confirmation', job.message_ids[:1].body)
        self.assertIn('job_tech_support', job.message_ids[:1].body)
        self.assertEqual(self.env['project.task'].search_count([]), tasks, 'no task in 4.2')
        self.assertEqual(job.warranty_case_id.state, 'approved', 'case unchanged')

    def test_22_block_without_date_or_main_technician(self):
        """D1 + diagram: missing Planned Date / Main Technician -> Block Job Confirmation."""
        job = self._prepare(self._approved())
        with self.assertRaisesRegex(UserError, 'Planned Date, Main Technician'):
            job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).planned_date = self.tomorrow
        with self.assertRaisesRegex(UserError, 'Main Technician required'):
            job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        self.assertEqual(job.state, 'draft')

    def test_23_technician_rules(self):
        """D2: active Field Service users of the job's company only; D3: the main technician
        cannot also be a support technician."""
        job = self._prepare(self._approved())
        for user in (self.internal_user, self.tech_foreign):
            with self.assertRaises(ValidationError):
                self._plan(job, main_technician_id=user.id)
        with self.assertRaises(ValidationError):
            self._plan(job, support_technician_ids=[(6, 0, self.internal_user.ids)])
        with self.assertRaises(ValidationError):
            self._plan(job, support_technician_ids=[(6, 0, self.tech_main.ids)])
        self.tech_support.active = False
        with self.assertRaises(ValidationError):
            self._plan(job, support_technician_ids=[(6, 0, self.tech_support.ids)])

    def test_24_past_date_allowed(self):
        """D4 revised (not an SRS rule): a past Planned Date is accepted on Draft and Planned
        jobs (postponed / retrospective visits) and tracked in the chatter."""
        job = self._prepare(self._approved())
        past = fields.Datetime.now() - timedelta(days=3)
        self._plan(job, planned_date=past)
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        self.assertEqual((job.state, job.planned_date), ('planned', past))
        earlier = past - timedelta(days=1)
        self._plan(job, planned_date=earlier)
        self.assertEqual(job.planned_date, earlier)
        # audit: Planned Date stays tracked (tracking values are not written for a record
        # created in the same test transaction)
        self.assertTrue(job._fields['planned_date'].tracking)

    def test_25_edit_until_confirmation(self):
        """Planning can be changed in Draft / Planned, not after confirmation; only Draft
        jobs are prepared; only Helpdesk users plan."""
        job = self._prepare(self._approved())
        self._plan(job)
        with self.assertRaises(AccessError):
            job.with_user(self.internal_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        self._plan(job, planned_date=self.tomorrow + timedelta(days=1))
        with self.assertRaises(UserError):
            job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.state = 'confirmed'
        with self.assertRaises(UserError):
            self._plan(job)

    def test_26_service_job_with_free_services(self):
        """A job with free services is planned the same way; the services are unchanged
        (status, Merge Status); Planned jobs can still be cancelled (Q42)."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        job = self._prepare(self._approved(s1, case_type='free_service'))
        state = s1.state
        self._plan(job)
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        self.assertEqual((s1.state, s1.merge_status), (state, 'selected'))
        job.with_user(self.helpdesk_user).action_cancel()
        self.assertEqual((job.state, s1.merge_status), ('cancelled', 'not_merged'))

    def test_27_plan_job_button_label(self):
        """UI label: the Draft -> Planned button reads "Plan Job" (same method, groups and
        visibility)."""
        arch = self.env['warranty.service.job'].get_view(
            self.env.ref('warranty_management_fsm.warranty_service_job_view_form').id, 'form')['arch']
        button = re.search(r'<button[^>]*name="action_prepare_for_confirmation"[^>]*>', arch).group(0)
        self.assertIn('string="Plan Job"', button)
        self.assertIn('invisible="state != \'draft\'"', button)
        self.assertNotIn('Prepare for Confirmation', arch)
