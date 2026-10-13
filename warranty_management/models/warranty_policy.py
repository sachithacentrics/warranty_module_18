from odoo import fields, models


class WarrantyPolicy(models.Model):
    _name = 'warranty.policy'
    _description = 'Warranty Policy'
    _order = 'name'

    name = fields.Char(string='Policy Name', required=True)
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)
    applies_to = fields.Selection([
        ('product', 'Product'),
        ('product_category', 'Product Category'),
        ('brand', 'Brand'),
        ('model', 'Model'),
        ('customer_type', 'Customer Type'),
        ('sale_order_type', 'Sales Order Type'),
    ], string='Applies To')
    pricelist_ids = fields.Many2many(
        'product.pricelist', 'warranty_policy_pricelist_rel', 'policy_id', 'pricelist_id',
        string='Applicable Pricelist / Customer Type')
    sale_order_type_id = fields.Selection([
        ('retail', 'Retail Sale'),
        ('project', 'Project Sale'),
        ('dealer', 'Dealer Sale'),
        ('amc', 'AMC Sale'),
    ], string='Sales Order Type')
    warranty_duration = fields.Integer(string='Warranty Duration')
    warranty_duration_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Warranty Duration Unit')
    start_date_basis = fields.Selection([
        ('installation', 'Installation/Commissioning'),
        ('delivery', 'Delivery'),
        ('invoice', 'Invoice'),
        ('custom', 'Custom Date Range'),
    ], string='Start Date Basis')
    free_service_count = fields.Integer(string='Free Service Count')
    free_service_period = fields.Integer(string='Free Service Period')
    free_service_period_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Free Service Period Unit')
    schedule_method = fields.Selection([
        ('equal_interval', 'Equal Interval'),
        ('fixed_offsets', 'Fixed Offsets'),
        ('manual', 'Manual Schedule'),
        ('calendar_month', 'Calendar Month'),
        ('amc_plan', 'AMC Plan'),
    ], string='Schedule Method')
    payment_check_required = fields.Boolean(string='Payment Check Required')
    covered_item_ids = fields.Many2many(
        'warranty.coverage.item', 'warranty_policy_covered_item_rel', 'policy_id', 'item_id',
        string='Covered Items')
    excluded_item_ids = fields.Many2many(
        'warranty.coverage.item', 'warranty_policy_excluded_item_rel', 'policy_id', 'item_id',
        string='Excluded Items')
    replacement_date_policy = fields.Selection([
        ('continue_original', 'Continue Original'),
        ('restart', 'Restart'),
        ('remaining_period', 'Remaining Period'),
        ('fixed_extension', 'Fixed Extension'),
        ('manual', 'Manual'),
    ], string='Replacement Date Policy')
    warranty_basis = fields.Selection([
        ('period', 'Period'),
        ('usage', 'Usage'),
    ], string='Warranty Basis')
    usage_unit = fields.Selection([
        ('operating_hours', 'Operating Hours'),
        ('cycles', 'Cycles'),
        ('km', 'KM'),
        ('units_produced', 'Units Produced'),
        ('other', 'Other'),
    ], string='Usage Unit')
    card_grouping_mode = fields.Selection([
        ('per_so', 'Per Sales Order'),
        ('per_product', 'Per Product'),
        ('per_delivery', 'Per Delivery'),
        ('per_unit', 'Per Unit/Serial'),
    ], string='Card Grouping Mode')
    auto_create_services = fields.Boolean(string='Auto-create Services')
    draft_job_from_service = fields.Boolean(string='Draft Job from Service')
    overdue_claim_handling = fields.Selection([
        ('warning', 'Warning Only'),
        ('hold', 'Hold'),
        ('approval', 'Approval Required'),
        ('block', 'Block'),
    ], string='Overdue Claim Handling')
