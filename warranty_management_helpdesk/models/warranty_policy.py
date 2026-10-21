from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WarrantyPolicy(models.Model):
    _inherit = 'warranty.policy'

    repeated_failure_threshold = fields.Integer(
        string='Repeated Failure Threshold',
        help="Escalate to the Manager / GM when the failures of a physical unit within the "
             "period (current case included) exceed this number. 0 = no escalation rule.")
    repeated_failure_period_days = fields.Integer(
        string='Repeated Failure Period (days)',
        help="Time window of the repeated failure check, counted back from the ticket date of "
             "the case. 0 = no escalation rule.")

    @api.constrains('repeated_failure_threshold', 'repeated_failure_period_days')
    def _check_repeated_failure_rule(self):
        for policy in self:
            if policy.repeated_failure_threshold < 0 or policy.repeated_failure_period_days < 0:
                raise ValidationError(_(
                    "The repeated failure threshold and period of policy %s cannot be negative.",
                    policy.name))
