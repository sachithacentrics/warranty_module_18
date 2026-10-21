from odoo import fields, models


class WarrantyCaseDeclineWizard(models.TransientModel):
    _name = 'warranty.case.decline.wizard'
    _description = 'Customer Declined Excluded Items'

    excluded_item_ids = fields.Many2many('warranty.case.excluded.item', string='Excluded Items',
                                         required=True, readonly=True)
    decline_reason = fields.Text(string='Decline Reason', required=True)

    def action_decline(self):
        self.ensure_one()
        self.excluded_item_ids._warranty_decline(self.decline_reason)
        return {'type': 'ir.actions.act_window_close'}
