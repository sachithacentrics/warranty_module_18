from odoo import fields, models


class WarrantyServiceJobHoldWizard(models.TransientModel):
    """Reason for putting a service job on hold or resuming it (approved M1)."""
    _name = 'warranty.service.job.hold.wizard'
    _description = 'Service Job Hold / Resume'

    job_id = fields.Many2one('warranty.service.job', string='Service Job', required=True,
                             readonly=True, ondelete='cascade')
    hold_action = fields.Selection([
        ('awaiting_parts', 'Awaiting Parts'),
        ('workshop', 'Workshop Repair'),
        ('resume', 'Resume Job'),
    ], string='Action', required=True, readonly=True)
    reason = fields.Text(string='Reason', required=True)

    def action_apply(self):
        self.ensure_one()
        self.job_id._warranty_set_hold(self.hold_action, self.reason)
        return {'type': 'ir.actions.act_window_close'}
