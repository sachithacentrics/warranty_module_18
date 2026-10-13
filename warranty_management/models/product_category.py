from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    warranty_policy_id = fields.Many2one('warranty.policy', string='Default Warranty Policy')
    default_warranty_period = fields.Integer(string='Default Period No.')
    default_warranty_period_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Default Period Unit')
    warranty_basis = fields.Selection([
        ('period', 'Period'),
        ('usage', 'Usage'),
    ], string='Warranty Basis')
    warranty_start_criterion = fields.Selection([
        ('installation', 'Installation/Commissioning'),
        ('delivery', 'Delivery'),
        ('invoice', 'Invoice'),
        ('custom', 'Custom Date Range'),
    ], string='Start Criterion')
    default_free_service_count = fields.Integer(string='Default Free Service Count')
    free_service_frequency = fields.Integer(string='Free Service Period/Frequency')
    free_service_frequency_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Free Service Frequency Unit')
    card_grouping_mode = fields.Selection([
        ('per_so', 'Per Sales Order'),
        ('per_product', 'Per Product'),
        ('per_delivery', 'Per Delivery'),
        ('per_unit', 'Per Unit/Serial'),
    ], string='Card Grouping Mode')
