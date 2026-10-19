from odoo import fields, models


class WarrantyProductPricelistRule(models.Model):
    """Legacy Product + Pricelist Warranty Mapping (retired, approved D1): the records are kept
    but no longer shown on the product and not used by the warranty resolution; the
    pricelist's Warranty Policy replaces them."""
    _name = 'warranty.product.pricelist.rule'
    _description = 'Product + Pricelist Warranty Mapping (Legacy)'
    _order = 'priority, id'

    product_tmpl_id = fields.Many2one(
        'product.template', string='Product', required=True, ondelete='cascade', index=True)
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', required=True)
    warranty_period = fields.Integer(string='Warranty Period No.')
    warranty_period_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Warranty Period Unit')
    free_service_count = fields.Integer(string='Free Service Count')
    free_service_frequency = fields.Integer(string='Free Service Period/Frequency')
    free_service_frequency_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Free Service Frequency Unit')
    # Same choices as the product / category / company Default Schedule Method.
    default_schedule_method = fields.Selection([
        ('equal_interval', 'Equal Interval'),
        ('manual', 'Manual Schedule'),
    ], string='Default Schedule Method')
    auto_create_services = fields.Boolean(string='Auto-create Services')
    usage_limit = fields.Float(string='Usage Limit')
    usage_unit = fields.Selection([
        ('operating_hours', 'Operating Hours'),
        ('cycles', 'Cycles'),
        ('km', 'KM'),
        ('units_produced', 'Units Produced'),
        ('other', 'Other'),
    ], string='Usage Unit')
    effective_from = fields.Date(string='Effective From')
    effective_to = fields.Date(string='Effective To')
    priority = fields.Integer(string='Priority', default=10)
    active = fields.Boolean(string='Active', default=True)

