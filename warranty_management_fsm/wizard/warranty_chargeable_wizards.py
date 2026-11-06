from odoo import api, fields, models

from odoo.addons.warranty_management_helpdesk.models.warranty_case import (
    CASE_TYPES, FAILURE_CATEGORIES)

# Final Case Type chosen after an inspection (approved G2): not Free Service / AMC.
INSPECTION_CASE_TYPES = [item for item in CASE_TYPES if item[0] not in ('free_service', 'amc')]


class WarrantyInspectionResultWizard(models.TransientModel):
    """Inspection Result at completion of a Chargeable Inspection visit (approved C7) or of
    a Warranty Inspection visit of a case with undetermined Case Type (Complete Inspection,
    approved G1 / G2)."""
    _name = 'warranty.inspection.result.wizard'
    _description = 'Inspection Result'

    task_id = fields.Many2one('project.task', string='Visit', required=True, readonly=True,
                              ondelete='cascade')
    job_type = fields.Selection(related='task_id.warranty_service_job_id.job_type')
    case_type_required = fields.Boolean(compute='_compute_case_type_required')
    diagnosis = fields.Text(string='Diagnosis / Findings', required=True)
    repair_required = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Repair Required')
    repair_details = fields.Text(string='Repair Details')
    case_type = fields.Selection(INSPECTION_CASE_TYPES, string='Final Case Type')
    failure_category = fields.Selection(FAILURE_CATEGORIES, string='Failure Category')

    @api.depends('task_id')
    def _compute_case_type_required(self):
        for wizard in self:
            # sudo: technicians may not read the warranty case; the type is shown only.
            wizard.case_type_required = not wizard.task_id.sudo().warranty_service_job_id                 .warranty_case_id.case_type

    def action_apply(self):
        self.ensure_one()
        # sudo: the visit's job (Helpdesk users may not read Field Service tasks); the job
        # access is checked as the user in _warranty_complete_visit().
        job = self.task_id.sudo().warranty_service_job_id.with_env(self.env)
        job._warranty_complete_visit(self.task_id, inspection={
            'diagnosis': self.diagnosis, 'repair_required': self.repair_required,
            'repair_details': self.repair_details, 'case_type': self.case_type,
            'failure_category': self.failure_category})
        return {'type': 'ir.actions.act_window_close'}


class WarrantyCaseRepairDeclineWizard(models.TransientModel):
    """Customer Declined Repair (approved C7.6)."""
    _name = 'warranty.case.repair.decline.wizard'
    _description = 'Customer Declined Repair'

    case_id = fields.Many2one('warranty.case', string='Warranty Case', required=True,
                              readonly=True, ondelete='cascade')
    reason = fields.Text(string='Reason', required=True)

    def action_apply(self):
        self.ensure_one()
        self.case_id._warranty_decline_repair(self.reason)
        return {'type': 'ir.actions.act_window_close'}
