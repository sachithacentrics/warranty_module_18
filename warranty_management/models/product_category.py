from odoo import api, fields, models

from .res_company import FREE_SERVICE_SCOPE_MODES


class ProductCategory(models.Model):
    _inherit = 'product.category'

    # Approved Scope Mode visibility: free service configuration shown only when the current
    # company's Warranty Scope Mode includes free services (display only, nothing stored).
    warranty_free_services_enabled = fields.Boolean(
        compute='_compute_warranty_free_services_enabled')

    @api.depends_context('company')
    def _compute_warranty_free_services_enabled(self):
        enabled = self.env.company.warranty_scope_mode in FREE_SERVICE_SCOPE_MODES
        for record in self:
            record.warranty_free_services_enabled = enabled

    warranty_policy_id = fields.Many2one('warranty.policy', string='Default Warranty Policy')
    warranty_policy_applicable = fields.Boolean(
        string='Warranty Policy Applicable', compute='_compute_warranty_policy_applicable',
        help="A Default Warranty Policy is selected. The category warranty defaults are then "
             "readonly.")
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
    default_schedule_method = fields.Selection([
        ('equal_interval', 'Equal Interval'),
        ('manual', 'Manual Schedule'),
    ], string='Default Schedule Method')
    auto_create_services = fields.Boolean(string='Auto-create Services')
    card_grouping_mode = fields.Selection([
        ('per_so', 'Per Sales Order'),
        ('per_product', 'Per Product'),
        ('per_delivery', 'Per Delivery'),
        ('per_unit', 'Per Unit/Serial'),
    ], string='Card Grouping Mode')

    @api.depends('warranty_policy_id')
    def _compute_warranty_policy_applicable(self):
        for category in self:
            category.warranty_policy_applicable = bool(category.warranty_policy_id)
