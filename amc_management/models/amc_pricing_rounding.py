from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

ROUNDING_METHODS = [
    ('half_up', 'Half-up'),
    ('up', 'Up'),
    ('down', 'Down'),
]

class AmcPricingRounding(models.Model):
    """Target-currency rounding rule (approved P4): the rounding step of prices converted into
    this currency."""
    _name = 'amc.pricing.rounding'
    _description = 'AMC Pricing Target Currency Rounding'

    formula_id = fields.Many2one('amc.pricing.formula', required=True, ondelete='cascade',
                                 index=True)
    company_id = fields.Many2one(related='formula_id.company_id', store=True)
    currency_id = fields.Many2one('res.currency', string='Target Currency', required=True)
    step = fields.Float(string='Rounding Step', required=True)
    method = fields.Selection(ROUNDING_METHODS, string='Method', default='half_up', required=True)

    @api.constrains('currency_id', 'step')
    def _check_rule(self):
        for rule in self:
            if rule.step <= 0:
                raise ValidationError(_("The rounding step must be greater than zero."))
            if rule.currency_id == rule.formula_id.currency_id:
                raise ValidationError(_("The formula currency uses the formula's own Rounding "
                                        "Step."))
            if len(rule.formula_id.rounding_rule_ids.filtered(
                    lambda other: other.currency_id == rule.currency_id)) > 1:
                raise ValidationError(_("%s has two rounding rules.", rule.currency_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        self.env['amc.pricing.formula'].browse(
            [vals['formula_id'] for vals in vals_list if vals.get('formula_id')]
        )._amc_check_draft_children()
        return super().create(vals_list)

    def write(self, vals):
        self.formula_id._amc_check_draft_children()
        return super().write(vals)

    def unlink(self):
        self.formula_id._amc_check_draft_children()
        return super().unlink()



