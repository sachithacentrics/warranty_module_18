from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    warranty_scope_mode = fields.Selection([
        ('warranty_only', 'Warranty Only'),
        ('free_services', 'Free Services'),
        ('amc', 'AMC'),
        ('amc_free_services', 'AMC with Free Services'),
    ], string='Warranty Scope Mode', default='warranty_only')
    default_warranty_policy_id = fields.Many2one('warranty.policy', string='Default Warranty Policy')
    default_card_grouping_mode = fields.Selection([
        ('per_so', 'Per Sales Order'),
        ('per_product', 'Per Product'),
        ('per_delivery', 'Per Delivery'),
        ('per_unit', 'Per Unit/Serial'),
    ], string='Default Card Grouping Mode')
    warranty_auto_create_services = fields.Boolean(string='Auto-create Services')
    warranty_draft_job_from_service = fields.Boolean(string='Draft Job from Service')
    default_warranty_basis = fields.Selection([
        ('period', 'Period'),
        ('usage', 'Usage'),
    ], string='Default Warranty Basis')
    default_start_criterion = fields.Selection([
        ('installation', 'Installation/Commissioning'),
        ('delivery', 'Delivery'),
        ('invoice', 'Invoice'),
        ('custom', 'Custom Date Range'),
    ], string='Default Start Criterion')
    default_warranty_duration = fields.Integer(string='Default Warranty Duration')
    default_warranty_duration_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Default Duration Unit')
