from odoo import _, api, fields, models


class WarrantyMrfLinkWizard(models.TransientModel):
    """Link Existing MRF (mapping 5.1 / T1.5): a Draft standalone requisition of the case
    company is linked to the warranty case, its open service job and visit."""
    _name = 'warranty.mrf.link.wizard'
    _description = 'Link Material Request to Warranty'

    warranty_case_id = fields.Many2one('warranty.case', string='Warranty Case', required=True,
                                       readonly=True)
    warranty_service_job_id = fields.Many2one('warranty.service.job', string='Service Job',
                                              readonly=True)
    warranty_task_id = fields.Many2one('project.task', string='Field Service Task', readonly=True)
    company_id = fields.Many2one(related='warranty_case_id.company_id')
    requisition_id = fields.Many2one(
        'material.purchase.requisition', string='Material Request', required=True,
        domain="[('warranty_case_id', '=', False), ('state', '=', 'draft'), "
               "('company_id', '=', company_id)]")

    @api.model
    def _warranty_open(self, case, job=False, task=False):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Link Material Request"),
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_warranty_case_id': case.id,
                'default_warranty_service_job_id': job and job.id or False,
                'default_warranty_task_id': task and task.id or False,
            },
        }

    def action_link(self):
        self.ensure_one()
        self.requisition_id._warranty_link(
            self.warranty_case_id, self.warranty_service_job_id, self.warranty_task_id)
        return self.requisition_id._warranty_action_view()
