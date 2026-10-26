from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .res_company import FREE_SERVICE_SCOPE_MODES


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Approved Scope Mode visibility: free service configuration shown only when the current
    # company's Warranty Scope Mode includes free services (display only, nothing stored).
    warranty_free_services_enabled = fields.Boolean(
        compute='_compute_warranty_free_services_enabled')

    @api.depends_context('company')
    def _compute_warranty_free_services_enabled(self):
        enabled = self.env.company.warranty_scope_mode in FREE_SERVICE_SCOPE_MODES
        for record in self:
            record.warranty_free_services_enabled = enabled

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
    # Same choices as the company / category Default Schedule Method.
    default_schedule_method = fields.Selection([
        ('equal_interval', 'Equal Interval'),
        ('manual', 'Manual Schedule'),
    ], string='Default Schedule Method')
    auto_create_services = fields.Boolean(string='Auto-create Services')
    warranty_worksheet_template_id = fields.Many2one(
        'worksheet.template', string='Worksheet Template',
        domain="[('res_model', '=', 'project.task'), "
               "'|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    # Legacy Product + Pricelist Warranty Mapping lines (retired, not shown, not used).
    warranty_pricelist_rule_ids = fields.One2many(
        'warranty.product.pricelist.rule', 'product_tmpl_id',
        string='Product + Pricelist Warranty Mapping (Legacy)')

    warranty_price_rule_ids = fields.One2many(
        'product.pricelist.item', 'product_tmpl_id', string='Pricelist Price Rules',
        readonly=True)

    # Legacy reverse side of the policies' Applicable Products (before 18.0.1.4.0); not used.
    warranty_product_policy_ids = fields.Many2many(
        'warranty.policy', 'warranty_policy_product_tmpl_rel', 'product_tmpl_id', 'policy_id',
        string='Legacy Product Warranty Policies', readonly=True, copy=False)

    warranty_policy_id = fields.Many2one(
        'warranty.policy', string='Warranty Policy', company_dependent=True,
        domain="[('company_id', 'in', [current_company_id, False])]",
        help="Warranty policy of this product in the current company. It applies after the "
             "Warranty Policy of the Sales Order pricelist and before the Default Warranty "
             "Policy of the product category.")
    warranty_category_policy_id = fields.Many2one(
        'warranty.policy', string='Category Warranty Policy',
        compute='_compute_warranty_policy_applicable',
        help="Default Warranty Policy of the product category (current company or shared), "
             "used when the product has no Warranty Policy.")
    warranty_policy_applicable = fields.Boolean(
        string='Warranty Policy Applicable', compute='_compute_warranty_policy_applicable',
        search='_search_warranty_policy_applicable',
        help="The product or its category has an active Warranty Policy of the current "
             "company (or a shared one). The product warranty defaults are then readonly.")

    warranty_applied_policy_id = fields.Many2one(
        'warranty.policy', string='Applied Warranty Policy',
        compute='_compute_warranty_policy_applicable',
        help="The product's Warranty Policy, else the Category Warranty Policy, applying in the "
             "current company. Its values are displayed (readonly) instead of the product's own "
             "warranty values, which are kept unchanged.")
    # Display only: values of the applied policy (never written to the product's own fields).
    warranty_policy_start_criterion = fields.Selection(
        related='warranty_applied_policy_id.start_date_basis', string='Start Criterion')
    warranty_policy_basis = fields.Selection(
        related='warranty_applied_policy_id.warranty_basis', string='Warranty Basis')
    warranty_policy_period = fields.Integer(
        related='warranty_applied_policy_id.warranty_duration', string='Default Period No.')
    warranty_policy_period_unit = fields.Selection(
        related='warranty_applied_policy_id.warranty_duration_unit',
        string='Default Period Unit')
    warranty_policy_usage_limit = fields.Float(
        related='warranty_applied_policy_id.usage_limit', string='Usage Limit')
    warranty_policy_usage_unit = fields.Selection(
        related='warranty_applied_policy_id.usage_unit', string='Usage Unit')
    warranty_policy_free_service_count = fields.Integer(
        related='warranty_applied_policy_id.free_service_count',
        string='Default Free Service Count')
    warranty_policy_frequency = fields.Integer(
        related='warranty_applied_policy_id.free_service_frequency',
        string='Free Service Period/Frequency')
    warranty_policy_frequency_unit = fields.Selection(
        related='warranty_applied_policy_id.free_service_frequency_unit',
        string='Free Service Frequency Unit')
    warranty_policy_service_period = fields.Integer(
        related='warranty_applied_policy_id.free_service_period', string='Free Service Period')
    warranty_policy_service_period_unit = fields.Selection(
        related='warranty_applied_policy_id.free_service_period_unit',
        string='Free Service Period Unit')
    warranty_policy_schedule_method = fields.Selection(
        related='warranty_applied_policy_id.schedule_method', string='Default Schedule Method')
    warranty_policy_auto_create = fields.Boolean(
        related='warranty_applied_policy_id.auto_create_services',
        string='Auto-create Services')

    @api.depends('warranty_policy_id', 'warranty_policy_id.active',
                 'warranty_policy_id.company_id', 'categ_id', 'categ_id.warranty_policy_id',
                 'categ_id.warranty_policy_id.active', 'categ_id.warranty_policy_id.company_id')
    @api.depends_context('company')
    def _compute_warranty_policy_applicable(self):
        company = self.env.company
        for template in self:
            category_policy = template.categ_id.warranty_policy_id
            if category_policy and not category_policy._is_applicable_for_company(company):
                category_policy = self.env['warranty.policy']
            own_policy = template.warranty_policy_id
            if own_policy and not own_policy._is_applicable_for_company(company):
                own_policy = self.env['warranty.policy']
            template.warranty_category_policy_id = category_policy
            template.warranty_applied_policy_id = own_policy or category_policy
            template.warranty_policy_applicable = bool(own_policy or category_policy)

    @api.constrains('warranty_policy_id')
    def _check_warranty_policy_company(self):
        # Company-dependent value: checked for the company it is written in.
        company = self.env.company
        for template in self:
            policy = template.warranty_policy_id
            if policy.company_id and (policy.company_id != company or (
                    template.company_id and template.company_id != policy.company_id)):
                raise ValidationError(_(
                    "The warranty policy \"%(policy)s\" of company %(policy_company)s cannot be "
                    "used for product \"%(product)s\" in company %(company)s.",
                    policy=policy.name, policy_company=policy.company_id.name,
                    product=template.display_name, company=company.name))

    @api.model_create_multi
    def create(self, vals_list):
        # A product with a Warranty Policy is Warranty Applicable.
        for vals in vals_list:
            if vals.get('warranty_policy_id'):
                self._check_warranty_policy_access()
                vals.setdefault('warranty_applicable', True)
        return super().create(vals_list)

    def write(self, vals):
        if 'warranty_policy_id' in vals:
            self._check_warranty_policy_access()
            if vals['warranty_policy_id'] and 'warranty_applicable' not in vals:
                vals = dict(vals, warranty_applicable=True)
        return super().write(vals)

    def _check_warranty_policy_access(self):
        """The product Warranty Policy is maintained by the users who maintain the policies
        (administrators); readonly for the other users."""
        self.env['warranty.policy'].check_access('write')

    def _search_warranty_policy_applicable(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(_("Unsupported search operator %s on Warranty Policy Applicable.",
                              operator))
        company = self.env.company
        # Active policies of the current company or shared.
        policies = self.env['warranty.policy'].search(
            [('company_id', 'in', [company.id, False])])
        template_ids = self.with_context(active_test=False)._search([
            '|', ('warranty_policy_id', 'in', policies.ids),
            ('categ_id.warranty_policy_id', 'in', policies.ids),
        ])
        positive = (operator == '=') == bool(value)
        return [('id', 'in' if positive else 'not in', template_ids)]
