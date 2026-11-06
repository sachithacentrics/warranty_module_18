from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import WarrantyMrfCommon


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestMrfSharedVisit(WarrantyMrfCommon):
    """Shared Field Service visit (approved v1): each Material Request stays on its own service
    job; materials block only the completion of that job."""

    def test_01_mrf_per_job_on_shared_visit(self):
        self.company.write({'warranty_signoff_required': False,
                            'warranty_worksheet_checklist_required': False,
                            'warranty_worksheet_attachment_required': False})
        self.company._warranty_fsm_project().sudo().worksheet_template_id = False
        job_a = self._prepare(self._approved())
        service = self._card().service_entitlement_ids.sorted('service_no')[:1]
        job_b = self._prepare(self._approved(service, case_type='free_service'))
        action = (job_a | job_b).with_user(self.helpdesk_user).action_open_shared_visit_wizard()
        with Form(self.env[action['res_model']].with_user(self.helpdesk_user)
                  .with_context(action['context'])) as form:
            form.planned_date = fields.Datetime.now() + timedelta(days=1)
            form.main_technician_id = self.tech
        task = self.env['project.task'].browse(form.record.action_apply()['res_id'])
        self.assertEqual(task.warranty_shared_job_ids, job_a | job_b)
        # MRF from the job: its own job, the shared visit as task
        mrf = self._save(job_a.with_user(self.helpdesk_user).action_create_material_request(),
                         self.helpdesk_user)
        self.assertEqual((mrf.warranty_service_job_id, mrf.warranty_task_id,
                          mrf.warranty_case_id), (job_a, task, job_a.warranty_case_id))
        self.assertEqual((job_a.material_request_ids, job_b.material_request_ids.ids), (mrf, []))
        with self.assertRaisesRegex(UserError, 'shared visit'):
            task.with_user(self.helpdesk_user).action_warranty_create_material_request()
        with self.assertRaisesRegex(UserError, 'shared visit'):
            task.with_user(self.tech).action_warranty_record_usage()
        # start, then: job A blocked by its open MRF, job B completes independently
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Shared visit'}).save_timesheet()
        lines = task.warranty_shared_line_ids
        line_a = lines.filtered(lambda line: line.job_id == job_a)
        line_b = lines - line_a
        with self.assertRaisesRegex(UserError, mrf.name):
            line_a.with_user(self.tech).action_complete()
        line_b.with_user(self.tech).action_complete()
        self.assertEqual((job_a.state, job_b.state, service.state),
                         ('in_progress', 'completed', 'completed'))
        self.assertFalse(task.fsm_done, 'job A is still open on the visit')
