from odoo import fields, models


class WarrantyCostLineWizard(models.TransientModel):
    _name = 'warranty.cost.line.wizard'
    _description = 'Warranty Cost Line Reason'

    line_id = fields.Many2one('warranty.cost.line', required=True, readonly=True)
    action = fields.Selection([('reject', 'Reject'), ('reverse', 'Reverse'),
                               ('actual', 'Record Actual')], required=True, readonly=True)
    currency_id = fields.Many2one(related='line_id.currency_id')
    approved_amount = fields.Monetary(related='line_id.approved_amount')
    amount = fields.Monetary(string='Actual Cost')
    cost_date = fields.Date(string='Cost Incurred Date')
    reason = fields.Text(string='Reason', required=True)

    def action_apply(self):
        self.ensure_one()
        if self.action == 'reject':
            self.line_id._warranty_reject(self.reason)
        elif self.action == 'reverse':
            self.line_id._warranty_reverse(self.reason)
        else:
            self.line_id._warranty_record_actual(self.amount, self.reason, self.cost_date)
        return {'type': 'ir.actions.act_window_close'}
