from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .material_purchase_requisition import CLOSED_TASK_STATES, MRF_JOB_STATES


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    material_request_ids = fields.One2many(
        'material.purchase.requisition', 'warranty_service_job_id', string='Material Requests')
    material_request_count = fields.Integer(compute='_compute_material_request_count')

    @api.depends('material_request_ids')
    def _compute_material_request_count(self):
        for job in self:
            job.material_request_count = len(job.material_request_ids)

    def _warranty_mrf_check_allowed(self):
        """Mapping D22: confirmed, not closed jobs (Confirmed, Rescheduled, In Progress, Awaiting
        Parts, Workshop, Incomplete)."""
        for job in self:
            # Optional Case Type (approved G3 / B-03): no parts on an inspection visit.
            if job.job_type == 'warranty_inspection':
                raise UserError(_("No Material Request on inspection job %s: decide the Case "
                                  "Type with Complete Inspection first.", job.name))
            if job.state not in MRF_JOB_STATES:
                state = dict(job._fields['state']._description_selection(self.env))[job.state]
                raise UserError(_("Material Requests can only be created for confirmed, open "
                                  "service jobs (%(job)s is %(state)s).", job=job.name, state=state))

    def _warranty_mrf_open_visit(self):
        """The job's only open Field Service visit, else False."""
        self.ensure_one()
        visits = self.visit_ids.filtered(lambda task: task.state not in CLOSED_TASK_STATES)             | self._warranty_open_shared_visits()
        return visits if len(visits) == 1 else False

    def action_create_material_request(self):
        self.ensure_one()
        return self.env['material.purchase.requisition']._warranty_mrf_form_action(
            self.warranty_case_id, self, self._warranty_mrf_open_visit())

    def action_link_material_request(self):
        self.ensure_one()
        self.warranty_case_id._warranty_mrf_check_allowed()
        self._warranty_mrf_check_allowed()
        return self.env['warranty.mrf.link.wizard']._warranty_open(
            self.warranty_case_id, self, self._warranty_mrf_open_visit())

    def action_view_material_requests(self):
        self.ensure_one()
        return self.material_request_ids._warranty_action_view()
