from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    warranty_brand = fields.Char(string='Brand',
                                 help="Used by the warranty cost report.")
    warranty_model = fields.Char(string='Model',
                                 help="Used by the warranty cost report.")
