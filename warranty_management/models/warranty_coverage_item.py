from odoo import fields, models


class WarrantyCoverageItem(models.Model):
    _name = 'warranty.coverage.item'
    _description = 'Warranty Coverage Item'
    _order = 'name'

    name = fields.Char(string='Coverage Item', translate=True)
    product_id = fields.Many2one(
        'product.product', string='Product', domain=[('sale_ok', '=', True)],
        help="Product of the chargeable quotation line when this item is excluded.")

    active = fields.Boolean(string='Active', default=True)
