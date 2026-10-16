from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductModel(models.Model):
    _name = 'product.model'
    _description = 'Product Model'
    _order = 'product_brand_id, name'

    name = fields.Char(string='Model Name', required=True)
    active = fields.Boolean(string='Active', default=True)
    product_brand_id = fields.Many2one('product.brand', string='Brand', index=True)

    warranty_policy_ids = fields.Many2many(
        'warranty.policy', 'warranty_policy_product_model_rel', 'model_id', 'policy_id',
        string='Model Warranty Policies', readonly=True, copy=False)

    @api.constrains('name', 'product_brand_id')
    def _check_unique_name_per_brand(self):
        """A model name is unique per brand (models without brand are checked among
        themselves); archived models are included."""
        for model in self:
            duplicate = self.with_context(active_test=False).search_count([
                ('id', '!=', model.id),
                ('name', '=', model.name),
                ('product_brand_id', '=', model.product_brand_id.id),
            ])
            if duplicate:
                raise ValidationError(_(
                    "Product model \"%(model)s\" already exists for brand %(brand)s.",
                    model=model.name, brand=model.product_brand_id.name or _("(none)")))
