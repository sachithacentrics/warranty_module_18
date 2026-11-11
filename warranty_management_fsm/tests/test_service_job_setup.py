from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.warranty_management_fsm.models.warranty_service_job import _VISIT_MARKER

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobSetup(ServiceJobCommon):
    """Phase 4.0 - module setup: sequence, access rights, deletion, multi-company."""

    def _job(self):
        case = self._create_case(self.ticket)
        return self.env['warranty.service.job'].create({'warranty_case_id': case.id})

    def test_01_sequence_and_default_state(self):
        job = self._job()
        self.assertTrue(job.name.startswith('JOB/'))
        self.assertEqual((job.state, job.company_id), ('draft', self.company))

    def test_02_access_rights(self):
        Job = self.env['warranty.service.job']
        job = self._job()
        self.assertEqual(Job.with_user(self.internal_user).search([('id', '=', job.id)]), job)
        with self.assertRaises(AccessError):
            Job.with_user(self.internal_user).create({'warranty_case_id': job.warranty_case_id.id})
        for user in (self.helpdesk_user, self.fsm_user):
            self.assertTrue(Job.with_user(user).create(
                {'warranty_case_id': job.warranty_case_id.id}))
            with self.assertRaises(AccessError):
                job.with_user(user).unlink()
        job.with_user(self.helpdesk_manager).unlink()
        self.assertFalse(job.exists())

    def test_03_delete_only_draft_or_cancelled(self):
        job = self._job()
        job.state = 'confirmed'
        with self.assertRaises(UserError):
            job.unlink()
        # Phase 4.8: a confirmed job is cancelled only by Cancel Job (internal marker here).
        job.with_context(warranty_visit_marker=_VISIT_MARKER).state = 'cancelled'
        job.unlink()

    def test_04_multi_company(self):
        job = self._job()
        self.assertFalse(self.env['warranty.service.job'].with_user(self.foreign_user).search(
            [('id', '=', job.id)]))

    def test_05_free_services_tab_by_job_company(self):
        """BA decision 2026-10-28: the Free Services tab is shown for jobs of every company,
        whatever the (kept, unused) company Warranty Scope Mode."""
        self.assertNotIn('warranty_free_services_enabled', self.env['warranty.service.job']._fields)
        self.company.warranty_scope_mode = 'warranty_only'
        arch = ' '.join(self.env['warranty.service.job'].get_view(
            view_type='form')['arch'].split())
        # UX 2026-11-09: shown while planning and whenever the job has free services.
        self.assertIn('<page string="Free Services" name="free_services" '
                      'invisible="not entitlement_ids and state not in (\'draft\', \'planned\')">',
                      arch)
        self.assertNotIn('warranty_free_services_enabled', arch)
        self.assertIn('name="merge_type"', arch)
