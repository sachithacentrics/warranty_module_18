from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    warranty_applicable = fields.Boolean(string='Warranty Applicable')
    warranty_start_criterion = fields.Selection([
        ('installation', 'Installation/Commissioning'),
        ('delivery', 'Delivery'),
        ('invoice', 'Invoice'),
        ('custom', 'Custom Date Range'),
    ], string='Start Criterion')
    warranty_basis = fields.Selection([
        ('period', 'Period'),
        ('usage', 'Usage'),
    ], string='Warranty Basis')
    default_warranty_period = fields.Integer(string='Default Period No.')
    default_warranty_period_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Default Period Unit')
    default_free_service_count = fields.Integer(string='Default Free Service Count')
    free_service_frequency = fields.Integer(string='Free Service Period/Frequency')
    free_service_frequency_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Free Service Frequency Unit')
    warranty_worksheet_template_id = fields.Many2one(
        'worksheet.template', string='Worksheet Template',
        domain="[('res_model', '=', 'project.task'), "
               "'|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    warranty_pricelist_rule_ids = fields.One2many(
        'warranty.product.pricelist.rule', 'product_tmpl_id',
        string='Product + Pricelist Warranty Mapping')
