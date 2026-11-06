from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AmcPricingFactor(models.Model):
    """Product / category pricing factor of a formula version (approved P3). Like the tiers and
    rounding rules, the factors of an Active / Archived version are locked (New Version)."""
    _name = 'amc.pricing.factor'
    _description = 'AMC Pricing Factor'

    formula_id = fields.Many2one('amc.pricing.formula', required=True, ondelete='cascade',
                                 index=True)
    company_id = fields.Many2one(related='formula_id.company_id', store=True)
    product_id = fields.Many2one('product.product', string='Product')
    category_id = fields.Many2one('product.category', string='Product Category')
    factor = fields.Float(string='Factor', required=True, default=1.0, digits=(16, 4))

    @api.constrains('product_id', 'category_id', 'factor')
    def _check_factor(self):
        for line in self:
            if bool(line.product_id) == bool(line.category_id):
                raise ValidationError(_("A pricing factor is set for a product or for a category "
                                        "(one of them)."))
            if line.factor <= 0:
                raise ValidationError(_("Pricing factors must be greater than zero."))
            duplicates = line.formula_id.factor_ids.filtered(
                lambda other: other != line and other.product_id == line.product_id
                and other.category_id == line.category_id)
            if duplicates:
                raise ValidationError(_("The factor of %s is defined twice.",
                                        (line.product_id or line.category_id).display_name))

    # AMC-D11 (formula governance): factors change the price of the version, so they follow
    # the version lock exactly like the tiers and target-currency rounding rules.
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
