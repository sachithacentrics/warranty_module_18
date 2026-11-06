from odoo import fields, models

REASON_ACTIONS = [
    ('hold', 'Put On Hold'),
    ('close', 'Close Contract'),
]


class AmcContractReason(models.TransientModel):
    """Reason of a contract Hold / Close (AMC Manager; audit in the chatter)."""
    _name = 'amc.contract.reason'
    _description = 'AMC Contract Hold / Close Reason'

    contract_id = fields.Many2one('amc.contract', required=True, readonly=True)
    action = fields.Selection(REASON_ACTIONS, required=True, readonly=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.action == 'hold':
            return self.contract_id._amc_hold(self.reason)
        return self.contract_id._amc_close(self.reason)
