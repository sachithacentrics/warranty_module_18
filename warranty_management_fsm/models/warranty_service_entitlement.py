from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .warranty_service_job import CLOSED_JOB_STATES, _COMPLETION_MARKER


class WarrantyServiceEntitlement(models.Model):
    _inherit = 'warranty.service.entitlement'

    service_job_ids = fields.Many2many(
        'warranty.service.job', 'warranty_service_job_entitlement_rel', 'entitlement_id',
        'job_id', string='Service Jobs', readonly=True, copy=False)
    open_service_job_id = fields.Many2one('warranty.service.job', string='Service Job',
                                          compute='_compute_open_service_job_id')
    # Approved G1: status Job Created (SRS 9.13 / Mapping / Part 4 diagram), set when the Service
    # Job is confirmed; the previous status is kept for a later reversal.
    state = fields.Selection(selection_add=[('job_created', 'Job Created'), ('in_progress',)],
                             ondelete={'job_created': 'set default'})
    job_previous_state = fields.Char(string='Status before Job Created', readonly=True,
                                     copy=False)
    warranty_task_ids = fields.Many2many(
        'project.task', 'warranty_task_entitlement_rel', 'entitlement_id', 'task_id',
        string='Field Service Visits', readonly=True, copy=False)

    @api.depends('schedule_log_ids.action', 'warranty_task_ids.warranty_visit_no')
    def _compute_reschedule_count(self):
        """Approved R6 (SRS: tracks customer / technician reschedules): Part 2 schedule
        reschedules plus the next visits planned for the service (display only)."""
        super()._compute_reschedule_count()
        for service in self:
            # sudo: visits counted only (users may not read Field Service tasks).
            service.reschedule_count += len(service.sudo().warranty_task_ids.filtered(
                lambda task: task.warranty_visit_no > 1))

    def write(self, vals):
        """Approved K5: free services of a service job are completed (consumed) only by the
        warranty completion; no direct status change into or out of Completed."""
        if self.env.context.get('warranty_completion_marker') is not _COMPLETION_MARKER \
                and ('state' in vals or vals.get('merge_status') == 'completed'):
            linked = self.filtered('service_job_ids')
            if linked and (vals.get('state') == 'completed'
                           or vals.get('merge_status') == 'completed'
                           or ('state' in vals and any(s.state == 'completed' for s in linked))):
                raise UserError(_("Free services of a service job are completed (consumed) only "
                                  "with Complete Visit."))
        return super().write(vals)

    def _warranty_on_open_job(self):
        self.ensure_one()
        return bool(self.open_service_job_id)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_open_service_job(self):
        if any(service.open_service_job_id for service in self):
            raise UserError(_("Free services of an open service job cannot be deleted."))

    @api.depends('service_job_ids.state')
    def _compute_open_service_job_id(self):
        for service in self:
            service.open_service_job_id = service.service_job_ids.filtered(
                lambda job: job.state not in CLOSED_JOB_STATES)[:1]
