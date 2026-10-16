from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .warranty_policy import ATTRIBUTE_POLICIES


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    warranty_applicable = fields.Boolean(string='Warranty Applicable')
    product_brand_id = fields.Many2one('product.brand', string='Brand', index=True)
    product_model_id = fields.Many2one(
        'product.model', string='Model', index=True,
        domain="[('product_brand_id', 'in', [product_brand_id, False])] "
               "if product_brand_id else []",
        help="Only models of the selected brand (or without brand) can be selected.")
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
        ('calendar_month', 'Calendar Month'),
    ], string='Default Schedule Method')
    auto_create_services = fields.Boolean(string='Auto-create Services')
    warranty_worksheet_template_id = fields.Many2one(
        'worksheet.template', string='Worksheet Template',
        domain="[('res_model', '=', 'project.task'), "
               "'|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    warranty_pricelist_rule_ids = fields.One2many(
        'warranty.product.pricelist.rule', 'product_tmpl_id',
        string='Product + Pricelist Warranty Mapping')

    warranty_price_rule_ids = fields.One2many(
        'product.pricelist.item', 'product_tmpl_id', string='Pricelist Price Rules',
        readonly=True)

    warranty_product_policy_ids = fields.Many2many(
        'warranty.policy', 'warranty_policy_product_tmpl_rel', 'product_tmpl_id', 'policy_id',
        string='Product Warranty Policies', readonly=True, copy=False)

    warranty_policy_applicable = fields.Boolean(
        string='Warranty Policy Applicable', compute='_compute_warranty_policy',
        search='_search_warranty_policy_applicable',
        help="The product is listed on an active Product warranty policy, or its model / brand "
             "on an active Model / Brand warranty policy, or its category has an active Default "
             "Warranty Policy, of the current company (or a shared one).")

    warranty_policy_id = fields.Many2one(
        'warranty.policy', string='Warranty Policy', compute='_compute_warranty_policy',
        inverse='_inverse_warranty_policy_id', search='_search_warranty_policy_id',
        domain="[('company_id', 'in', [current_company_id, False])]",
        help="Applicable warranty policy in the current company: the Product policy listing "
             "this product, else the Model policy of its model, else the Brand policy of its "
             "brand, else the Customer Type policy of a pricelist linked to it (mapping line "
             "or product / variant price rule), else the Default Warranty Policy of its "
             "category. Maintained from the policies and categories.")

    @api.depends('warranty_product_policy_ids', 'warranty_product_policy_ids.applies_to',
                 'warranty_product_policy_ids.company_id', 'warranty_product_policy_ids.active',
                 'product_model_id', 'product_model_id.warranty_policy_ids',
                 'product_model_id.warranty_policy_ids.applies_to',
                 'product_model_id.warranty_policy_ids.company_id',
                 'product_model_id.warranty_policy_ids.active',
                 'product_brand_id', 'product_brand_id.warranty_policy_ids',
                 'product_brand_id.warranty_policy_ids.applies_to',
                 'product_brand_id.warranty_policy_ids.company_id',
                 'product_brand_id.warranty_policy_ids.active',
                 'warranty_pricelist_rule_ids', 'warranty_pricelist_rule_ids.active',
                 'warranty_pricelist_rule_ids.priority',
                 'warranty_pricelist_rule_ids.pricelist_id',
                 'warranty_pricelist_rule_ids.pricelist_id.warranty_policy_ids',
                 'warranty_pricelist_rule_ids.pricelist_id.warranty_policy_ids.applies_to',
                 'warranty_pricelist_rule_ids.pricelist_id.warranty_policy_ids.company_id',
                 'warranty_pricelist_rule_ids.pricelist_id.warranty_policy_ids.active',
                 'warranty_price_rule_ids', 'warranty_price_rule_ids.applied_on',
                 'warranty_price_rule_ids.pricelist_id',
                 'warranty_price_rule_ids.pricelist_id.warranty_policy_ids',
                 'warranty_price_rule_ids.pricelist_id.warranty_policy_ids.applies_to',
                 'warranty_price_rule_ids.pricelist_id.warranty_policy_ids.company_id',
                 'warranty_price_rule_ids.pricelist_id.warranty_policy_ids.active',
                 'categ_id', 'categ_id.warranty_policy_id',
                 'categ_id.warranty_policy_id.company_id', 'categ_id.warranty_policy_id.active')
    @api.depends_context('company')
    def _compute_warranty_policy(self):
        policy_map = self.env['warranty.policy']._get_product_policy_map(
            self.env.company, [tmpl_id for tmpl_id in self._origin.ids if tmpl_id])
        for template in self:
            policy = policy_map.get(template._origin.id, self.env['warranty.policy'])
            template.warranty_policy_id = policy
            template.warranty_policy_applicable = bool(policy)

    def _inverse_warranty_policy_id(self):
        """Set from the product: the product is assigned directly to the selected policy
        (any Applies To; added to its Applicable Products) and removed from the other direct
        assignments of the current company (one per company). Clearing removes the direct
        assignment; a Model / Brand / Customer Type policy, if any, then applies again."""
        Policy = self.env['warranty.policy']
        for template in self:
            policy = template.warranty_policy_id
            current = Policy.search([
                ('company_id', 'in', [self.env.company.id, False]),
                ('product_tmpl_ids', 'in', template.ids),
            ])
            (current - policy).write({'product_tmpl_ids': [(3, template.id)]})
            if policy and template not in policy.product_tmpl_ids:
                policy.write({'product_tmpl_ids': [(4, template.id)]})
        # Recompute from the policies (e.g. a Brand policy applies again after clearing).
        self.invalidate_recordset(['warranty_policy_id', 'warranty_policy_applicable'])

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        templates._mark_attribute_warranty_applicable()
        return templates

    def write(self, vals):
        result = super().write(vals)
        if vals.get('product_brand_id') or vals.get('product_model_id'):
            self._mark_attribute_warranty_applicable()
        return result

    def _mark_attribute_warranty_applicable(self):
        """A product given a model / brand with an active Model / Brand policy in the current
        company becomes Warranty Applicable (never reversed automatically)."""
        Policy = self.env['warranty.policy']
        templates = self.browse()
        for applies_to, __, template_field in ATTRIBUTE_POLICIES:
            value_map = Policy._get_attribute_policy_map(
                applies_to, self.env.company, self[template_field].ids)
            templates |= self.filtered(lambda template: template[template_field].id in value_map)
        templates = templates.filtered(lambda template: not template.warranty_applicable)
        if templates:
            templates.write({'warranty_applicable': True})

    def _search_warranty_policy_applicable(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(_("Unsupported search operator %s on Warranty Policy Applicable.",
                              operator))
        template_ids = list(self.env['warranty.policy']._get_product_policy_map(
            self.env.company))
        positive = (operator == '=') == bool(value)
        return [('id', 'in' if positive else 'not in', template_ids)]

    def _search_warranty_policy_id(self, operator, value):
        policy_map = self.env['warranty.policy']._get_product_policy_map(self.env.company)
        if operator in ('=', '!=') and not value:
            return [('id', 'not in' if operator == '=' else 'in', list(policy_map))]
        if operator in ('=', 'in'):
            policy_ids = set(value if isinstance(value, (list, tuple)) else [value])
        elif operator in ('ilike', '=ilike', 'like', '=like'):
            policy_ids = set(self.env['warranty.policy'].search([('name', operator, value)]).ids)
        else:
            raise UserError(_("Unsupported search operator %s on Warranty Policy.", operator))
        return [('id', 'in', [tmpl_id for tmpl_id, policy in policy_map.items()
                              if policy.id in policy_ids])]
