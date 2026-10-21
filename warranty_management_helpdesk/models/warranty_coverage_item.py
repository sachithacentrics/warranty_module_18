from odoo import fields, models


class WarrantyCoverageItem(models.Model):
    _inherit = 'warranty.coverage.item'

    product_id = fields.Many2one(
        'product.product', string='Product', domain=[('sale_ok', '=', True)],
        help="Product of the chargeable quotation line when this item is excluded.")
