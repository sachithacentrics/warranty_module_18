from odoo import fields, models


class AmcOpportunityLost(models.TransientModel):
    _name = 'amc.opportunity.lost'
    _description = 'AMC Opportunity Lost Reason'

    opportunity_ids = fields.Many2many('amc.opportunity', string='Opportunities')
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        return self.opportunity_ids.action_mark_lost(self.reason)
