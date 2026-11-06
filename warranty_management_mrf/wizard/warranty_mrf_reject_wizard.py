from odoo import fields, models


class WarrantyMrfRejectWizard(models.TransientModel):
    """Reject (design rev. 2, section 7): an approver of the pending level rejects a warranty
    Material Request with a reason."""
    _name = 'warranty.mrf.reject.wizard'
    _description = 'Reject Material Request'

    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     required=True, readonly=True)
    reason = fields.Text(string='Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        self.requisition_id._warranty_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
