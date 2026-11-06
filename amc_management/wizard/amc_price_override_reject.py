from odoo import fields, models


class AmcPriceOverrideReject(models.TransientModel):
    _name = 'amc.price.override.reject'
    _description = 'Reject AMC Override'

    override_id = fields.Many2one('amc.price.override', required=True, readonly=True)
    note = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        return self.override_id.action_reject(self.note)
