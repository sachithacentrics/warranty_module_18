from odoo import api, fields, models


class WarrantySharedVisitWizard(models.TransientModel):
    """Create Merged Field Service Visit (approved v1): one visit for the selected jobs."""
    _name = 'warranty.shared.visit.wizard'
    _description = 'Create Merged Field Service Visit'

    job_ids = fields.Many2many('warranty.service.job', string='Service Jobs', required=True,
                               readonly=True)
    planned_date = fields.Datetime(string='Planned Visit Date', required=True)
    main_technician_id = fields.Many2one('res.users', string='Main Technician', required=True,
                                         domain="[('id', 'in', technician_candidate_ids)]")
    support_technician_ids = fields.Many2many(
        'res.users', 'warranty_shared_visit_wizard_support_rel', 'wizard_id', 'user_id',
        string='Support Technicians', domain="[('id', 'in', technician_candidate_ids)]")
    technician_candidate_ids = fields.Many2many('res.users', compute='_compute_candidates')

    @api.depends('job_ids')
    def _compute_candidates(self):
        for wizard in self:
            job = wizard.job_ids[:1]
            wizard.technician_candidate_ids = self.env['res.users'].search(
                job._technician_domain(job.company_id)) if job else self.env['res.users']

    def action_apply(self):
        self.ensure_one()
        task = self.job_ids._warranty_create_shared_visit(
            self.planned_date, self.main_technician_id, self.support_technician_ids)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'res_id': task.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }
