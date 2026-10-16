from odoo import fields, models


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    warranty_policy_ids = fields.Many2many(
        'warranty.policy', 'warranty_policy_pricelist_rel', 'pricelist_id', 'policy_id',
        string='Customer Type Warranty Policies', readonly=True, copy=False)
