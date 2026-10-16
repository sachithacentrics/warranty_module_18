from odoo import fields, models


class ProductBrand(models.Model):
    _name = 'product.brand'
    _description = 'Product Brand'
    _order = 'name'

    name = fields.Char(string='Brand Name', required=True)
    active = fields.Boolean(string='Active', default=True)

    warranty_policy_ids = fields.Many2many(
        'warranty.policy', 'warranty_policy_product_brand_rel', 'brand_id', 'policy_id',
        string='Brand Warranty Policies', readonly=True, copy=False)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'This product brand already exists.'),
    ]
