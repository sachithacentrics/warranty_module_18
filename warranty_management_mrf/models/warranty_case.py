from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .material_purchase_requisition import MRF_CASE_STATES, MRF_JOB_STATES


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    material_request_ids = fields.One2many(
        'material.purchase.requisition', 'warranty_case_id', string='Material Requests')
    material_request_count = fields.Integer(compute='_compute_material_request_count')

    @api.depends('material_request_ids')
    def _compute_material_request_count(self):
        for case in self:
            case.material_request_count = len(case.material_request_ids)

    def _warranty_mrf_check_allowed(self):
        """Mapping D22: Approved, Job Created, In Progress or Chargeable cases."""
        for case in self:
            # Optional Case Type (approved 5 / B-06): no material issue before the Case Type and
            # its approvals are known.
            if not case.case_type:
                raise UserError(_("No Material Request for warranty case %s: its Case Type is "
                                  "not determined yet (inspection).", case.name))
            if case.state not in MRF_CASE_STATES:
                state = dict(case._fields['state']._description_selection(self.env))[case.state]
                raise UserError(_("Material Requests can only be created for Approved, Job Created, "
                                  "In Progress or Chargeable warranty cases (%(case)s is %(state)s).",
                                  case=case.name, state=state))

    def _warranty_mrf_job_and_task(self):
        """The case's open service job (if it accepts requests) and its only open visit."""
        self.ensure_one()
        job = self.open_service_job_id
        if not job or job.state not in MRF_JOB_STATES:
            return False, False
        return job, job._warranty_mrf_open_visit()

    def action_create_material_request(self):
        self.ensure_one()
        job, task = self._warranty_mrf_job_and_task()
        return self.env['material.purchase.requisition']._warranty_mrf_form_action(self, job, task)

    def action_link_material_request(self):
        self.ensure_one()
        self._warranty_mrf_check_allowed()
        job, task = self._warranty_mrf_job_and_task()
        return self.env['warranty.mrf.link.wizard']._warranty_open(self, job, task)

    def action_view_material_requests(self):
        self.ensure_one()
        return self.material_request_ids._warranty_action_view()
