from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

BILLING_FREQUENCIES = [
    ('upfront', 'Upfront (once)'),
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('half_yearly', 'Half-yearly'),
    ('annual', 'Annual'),
    ('per_visit', 'Per Preventive Visit'),
]
BILLING_TIMINGS = [
    ('advance', 'In Advance'),
    ('arrears', 'In Arrears'),
]
# Months of one billing period (upfront / per visit: no periodic interval).
FREQUENCY_MONTHS = {'monthly': 1, 'quarterly': 3, 'half_yearly': 6, 'annual': 12}


class AmcBillingPlan(models.Model):
    """AMC Billing Plan (Mapping 4 / SRS 2.12): how the contract value is invoiced. Upfront is
    billed in advance; Per Preventive Visit in arrears (at visit completion)."""
    _name = 'amc.billing.plan'
    _inherit = ['mail.thread']
    _description = 'AMC Billing Plan'
    _order = 'sequence, name'

    name = fields.Char(string='Billing Plan', required=True, translate=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True, tracking=True,
        default=lambda self: self.env.company, help="Empty: available in all companies.")
    billing_frequency = fields.Selection(BILLING_FREQUENCIES, string='Billing Frequency',
                                         required=True, default='annual', tracking=True)
    billing_timing = fields.Selection(BILLING_TIMINGS, string='Billing Timing', required=True,
                                      default='advance', tracking=True)
    interval_months = fields.Integer(string='Billing Interval (Months)',
                                     compute='_compute_interval_months')
    description = fields.Text(string='Description')

    @api.depends('billing_frequency')
    def _compute_interval_months(self):
        for plan in self:
            plan.interval_months = FREQUENCY_MONTHS.get(plan.billing_frequency, 0)

    @api.onchange('billing_frequency')
    def _onchange_billing_frequency(self):
        if self.billing_frequency == 'upfront':
            self.billing_timing = 'advance'
        elif self.billing_frequency == 'per_visit':
            self.billing_timing = 'arrears'

    @api.constrains('billing_frequency', 'billing_timing')
    def _check_billing_timing(self):
        for plan in self:
            if plan.billing_frequency == 'upfront' and plan.billing_timing != 'advance':
                raise ValidationError(_("Billing plan %s: Upfront billing is always In Advance.",
                                        plan.name))
            if plan.billing_frequency == 'per_visit' and plan.billing_timing != 'arrears':
                raise ValidationError(_("Billing plan %s: Per Preventive Visit billing is In "
                                        "Arrears (invoiced when the visit is completed).",
                                        plan.name))
