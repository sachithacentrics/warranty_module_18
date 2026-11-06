from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .material_purchase_requisition import CLOSED_TASK_STATES


class ProjectTask(models.Model):
    _inherit = 'project.task'

    warranty_material_request_ids = fields.One2many(
        'material.purchase.requisition', 'warranty_task_id', string='Material Requests')
    warranty_material_request_count = fields.Integer(
        compute='_compute_warranty_material_request_count')

    @api.depends('warranty_material_request_ids')
    def _compute_warranty_material_request_count(self):
        for task in self:
            task.warranty_material_request_count = len(task.warranty_material_request_ids)

    def _warranty_mrf_check_allowed(self):
        """Mapping D22: an open visit of a warranty service job that accepts requests."""
        for task in self:
            if not task.warranty_is_visit:
                raise UserError(_("Material Requests can only be created from warranty Field "
                                  "Service visits."))
            if task.state in CLOSED_TASK_STATES:
                raise UserError(_("Field Service task %(task)s is closed.", task=task.display_name))
            task.warranty_service_job_id._warranty_mrf_check_allowed()

    def _warranty_mrf_check_single_job(self):
        # Shared visit (approved v1): each Material Request belongs to one service job.
        if self.sudo().warranty_shared_job_ids:
            raise UserError(_("%s is a shared visit: create or link the Material Request from "
                              "its Service Job (each job keeps its own materials).",
                              self.sudo().name))

    def action_warranty_create_material_request(self):
        self.ensure_one()
        self._warranty_mrf_check_single_job()
        self._warranty_mrf_check_allowed()
        job = self.warranty_service_job_id
        return self.env['material.purchase.requisition']._warranty_mrf_form_action(
            job.warranty_case_id, job, self)

    def action_warranty_link_material_request(self):
        self.ensure_one()
        self._warranty_mrf_check_single_job()
        self._warranty_mrf_check_allowed()
        job = self.warranty_service_job_id
        job.warranty_case_id._warranty_mrf_check_allowed()
        return self.env['warranty.mrf.link.wizard']._warranty_open(job.warranty_case_id, job, self)

    def action_warranty_view_material_requests(self):
        self.ensure_one()
        return self.warranty_material_request_ids._warranty_action_view()
