from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

class AmcPricingFactor(models.Model):
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