from odoo import fields, models


class AmcPricingPreviewLine(models.TransientModel):
    _name = 'amc.pricing.preview.line'
    _description = 'AMC Price Preview Equipment'

    preview_id = fields.Many2one('amc.pricing.preview', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product')
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    equipment_value = fields.Float(string='Equipment / Sales Value',
                                   help="In the formula currency (sample input).")
    site_id = fields.Many2one('res.partner', string='Site')
