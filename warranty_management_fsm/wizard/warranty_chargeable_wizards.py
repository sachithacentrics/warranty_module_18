from odoo import fields, models


class WarrantyInspectionResultWizard(models.TransientModel):
    """Inspection Result at completion of a Chargeable Inspection visit (approved C7)."""
    _name = 'warranty.inspection.result.wizard'
    _description = 'Inspection Result'

    task_id = fields.Many2one('project.task', string='Visit', required=True, readonly=True,
                              ondelete='cascade')
    diagnosis = fields.Text(string='Diagnosis', required=True)
    repair_required = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Repair Required',
                                       required=True)
    repair_details = fields.Text(string='Repair Details')

    def action_apply(self):
        self.ensure_one()
        # sudo: the visit's job (Helpdesk users may not read Field Service tasks); the job
        # access is checked as the user in _warranty_complete_visit().
        job = self.task_id.sudo().warranty_service_job_id.with_env(self.env)
        job._warranty_complete_visit(self.task_id, inspection={
            'diagnosis': self.diagnosis, 'repair_required': self.repair_required,
            'repair_details': self.repair_details})
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
