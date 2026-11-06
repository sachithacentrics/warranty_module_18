from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AmcPricingTier(models.Model):
    _name = 'amc.pricing.tier'
    _description = 'AMC Pricing Tier'
    _order = 'formula_id, from_value'

    formula_id = fields.Many2one('amc.pricing.formula', required=True, ondelete='cascade',
                                 index=True)
    company_id = fields.Many2one(related='formula_id.company_id', store=True)
    currency_id = fields.Many2one(related='formula_id.currency_id')
    from_value = fields.Float(string='From', required=True)
    to_value = fields.Float(string='To', help="Empty / 0: no upper limit (last tier only).")
    rate = fields.Monetary(string='Rate', required=True)

    def _amc_tier_problems(self):
        """Approved P2: tiers start at 1 (or 0), do not overlap, have no gap; only the last
        one may be open-ended; rates > 0."""
        if not self:
            return [_("Tiered pricing needs at least one tier.")]
        problems = []
        tiers = self.sorted('from_value')
        if tiers[0].from_value > 1:
            problems.append(_("The first tier must start at 0 or 1."))
        for previous, tier in zip(tiers, tiers[1:]):
            if not previous.to_value:
                problems.append(_("Only the last tier can be open-ended."))
            elif tier.from_value <= previous.to_value:
                problems.append(_("Tiers %(a)s-%(b)s and %(c)s-%(d)s overlap.",
                                  a=previous.from_value, b=previous.to_value,
                                  c=tier.from_value, d=tier.to_value or '...'))
            elif tier.from_value - previous.to_value > 1:
                problems.append(_("Gap between the tiers ending at %(a)s and starting at %(b)s.",
                                  a=previous.to_value, b=tier.from_value))
        for tier in tiers:
            if tier.rate <= 0:
                problems.append(_("Tier rates must be greater than zero."))
            if tier.to_value and tier.to_value < tier.from_value:
                problems.append(_("A tier ends before it starts (%s).", tier.from_value))
        return problems

    def _amc_tier_for(self, value):
        for tier in self.sorted('from_value'):
            if tier.from_value <= value and (not tier.to_value or value <= tier.to_value):
                return tier
        return self.browse()

    @api.constrains('from_value', 'to_value', 'rate')
    def _check_tiers(self):
        for formula in self.formula_id:
            problems = formula.tier_ids._amc_tier_problems()
            if problems:
                raise ValidationError('%s: %s' % (formula.name, ' '.join(problems)))

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
