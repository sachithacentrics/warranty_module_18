
from odoo import _, api, fields, models

class AmcContractCancelWizard(models.TransientModel):
    _name = 'amc.contract.cancel.wizard'
    _description = 'Cancel AMC Contract'

    contract_id = fields.Many2one('amc.contract', required=True, readonly=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        return self.contract_id.action_cancel_contract(self.reason)