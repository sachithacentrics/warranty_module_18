from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Product attribute policies, in approved priority order (after the Product policy):
# (applies_to, policy field, product.template field).
ATTRIBUTE_POLICIES = [
    ('model', 'product_model_ids', 'product_model_id'),
    ('brand', 'product_brand_ids', 'product_brand_id'),
]


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
    product_tmpl_ids = fields.Many2many(
        'product.template', 'warranty_policy_product_tmpl_rel', 'policy_id', 'product_tmpl_id',
        string='Applicable Products',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="Products assigned directly to this policy (any Applies To; for Applies To = "
             "Product this is the Applicable Products list). They use this policy before any "
             "Model / Brand / Customer Type / category policy. Also set from the product's "
             "Warranty Policy field. Selected products are marked Warranty Applicable "
             "automatically.")

    category_link_ids = fields.One2many(
        'product.category', 'warranty_policy_id', string='Linked Product Categories')
    product_categ_ids = fields.Many2many(
        'product.category', string='Applicable Product Categories',
        compute='_compute_product_categ_ids', inverse='_inverse_product_categ_ids',
        help="Used when Applies To is Product Category: sets this policy as the Default "
             "Warranty Policy of the selected categories. A category can have only one "
             "warranty policy.")
    product_brand_ids = fields.Many2many(
        'product.brand', 'warranty_policy_product_brand_rel', 'policy_id', 'brand_id',
        string='Applicable Brands',
        help="Used when Applies To is Brand: products of these brands use this policy when no "
             "Product policy lists them. Their products are marked Warranty Applicable "
             "automatically.")
    product_model_ids = fields.Many2many(
        'product.model', 'warranty_policy_product_model_rel', 'policy_id', 'model_id',
        string='Applicable Models',
        help="Used when Applies To is Model: products of these models use this policy when no "
             "Product policy lists them (before the Brand policy). Their products are marked "
             "Warranty Applicable automatically.")
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
    service_offset_ids = fields.One2many(
        'warranty.policy.service.offset', 'policy_id', string='Service Offsets')
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

    # Free service due monitoring (SRS 12 scenarios 6 / 23; see doc/part2_design_decisions.md)
    grace_period_days = fields.Integer(
        string='Grace Period (Days)',
        help="Days after the due date during which a missed free service stays acceptable.")
    auto_expire_services = fields.Boolean(
        string='Auto-expire',
        help="Expire free services automatically after the grace period.")

    carry_forward_allowed = fields.Boolean(
        string='Carry-forward Allowed',
        help="Missed free services are kept Missed and never expire automatically. "
             "The carry-forward rules themselves are not implemented yet.")
    service_due_alert_days = fields.Integer(
        string='Service Due Alert Days',
        help="Create a due alert activity this many days before the due date (0 = disabled).")
    expiry_reminder_days = fields.Integer(
        string='Expiry Reminder Days',
        help="Create an expiry reminder activity this many days before the grace period end "
             "date (0 = disabled).")
    usage_alert_percentage = fields.Float(
        string='Usage Alert %',
        help="Usage threshold shown on usage-based free services. Not monitored yet.")
    service_alert_user_ids = fields.Many2many(
        'res.users', 'warranty_policy_alert_user_rel', 'policy_id', 'user_id',
        string='Service Alert Responsible Users', domain=[('share', '=', False)],
        context={'active_test': False},
        help="Users receiving the due alerts and expiry reminders; each user receives their "
             "own activity. When empty, the company Service Alert Responsible Users are used.")

    @api.constrains('grace_period_days', 'service_due_alert_days', 'expiry_reminder_days',
                    'usage_alert_percentage')
    def _check_service_monitoring_values(self):
        for policy in self:
            if min(policy.grace_period_days, policy.service_due_alert_days,
                   policy.expiry_reminder_days) < 0:
                raise ValidationError(_(
                    "Grace period, service due alert days and expiry reminder days of policy "
                    "%s must not be negative.", policy.name))
            if not 0 <= policy.usage_alert_percentage <= 100:
                raise ValidationError(_(
                    "The usage alert percentage of policy %s must be between 0 and 100.",
                    policy.name))

    @api.constrains('service_alert_user_ids', 'company_id')
    def _check_service_alert_users(self):
        for policy in self:
            users = policy.service_alert_user_ids
            not_internal = users.filtered(lambda user: not user.active or user.share)
            if not_internal:
                raise ValidationError(_(
                    "The Service Alert Responsible Users of policy %(policy)s must be active "
                    "internal users: %(users)s",
                    policy=policy.name, users=', '.join(not_internal.mapped('name'))))
            other_company = users.filtered(
                lambda user: policy.company_id and policy.company_id not in user.company_ids)
            if other_company:
                raise ValidationError(_(
                    "The Service Alert Responsible Users of policy %(policy)s must be allowed in "
                    "company %(company)s: %(users)s", policy=policy.name,
                    company=policy.company_id.name,
                    users=', '.join(other_company.mapped('name'))))

    @api.constrains('applies_to', 'product_tmpl_ids', 'company_id', 'active')
    def _check_unique_product_policy(self):
        """A product may be assigned directly to only one active policy per company, whatever
        its Applies To (no company = shared policies, checked among themselves)."""

        Policy = self.sudo().with_context(active_test=True)
        for policy in self.filtered(lambda p: p.active and p.product_tmpl_ids):
            others = Policy.search([
                ('id', '!=', policy.id),
                ('company_id', '=', policy.company_id.id),
                ('product_tmpl_ids', 'in', policy.product_tmpl_ids.ids),
            ])
            for other in others:
                product = (policy.product_tmpl_ids & other.product_tmpl_ids)[:1]
                raise ValidationError(_(
                    "Product \"%(product)s\" is already assigned directly to the active warranty "
                    "policy \"%(other)s\" of the same company. A product can be assigned "
                    "directly to only one policy per company.",
                    product=product.display_name, other=other.name))

    @api.constrains('applies_to', 'product_brand_ids', 'company_id', 'active')
    def _check_unique_brand_policy(self):
        """A brand may belong to only one active Brand policy per company (no company =
        shared policies, checked among themselves)."""

        Policy = self.sudo().with_context(active_test=True)
        for policy in self.filtered(lambda p: p.active and p.applies_to == 'brand'
                                    and p.product_brand_ids):
            others = Policy.search([
                ('id', '!=', policy.id),
                ('applies_to', '=', 'brand'),
                ('company_id', '=', policy.company_id.id),
                ('product_brand_ids', 'in', policy.product_brand_ids.ids),
            ])
            for other in others:
                brand = (policy.product_brand_ids & other.product_brand_ids)[:1]
                raise ValidationError(_(
                    "Brand \"%(brand)s\" is already assigned to the active Brand warranty policy "
                    "\"%(other)s\" of the same company. A brand can belong to only one Brand "
                    "policy per company.",
                    brand=brand.display_name, other=other.name))

    @api.constrains('applies_to', 'product_model_ids', 'company_id', 'active')
    def _check_unique_model_policy(self):
        """A model may belong to only one active Model policy per company (no company =
        shared policies, checked among themselves)."""
        # sudo: the integrity check must see every policy of the company, whatever the
        # record rules of the current user.
        Policy = self.sudo().with_context(active_test=True)
        for policy in self.filtered(lambda p: p.active and p.applies_to == 'model'
                                    and p.product_model_ids):
            others = Policy.search([
                ('id', '!=', policy.id),
                ('applies_to', '=', 'model'),
                ('company_id', '=', policy.company_id.id),
                ('product_model_ids', 'in', policy.product_model_ids.ids),
            ])
            for other in others:
                model = (policy.product_model_ids & other.product_model_ids)[:1]
                raise ValidationError(_(
                    "Model \"%(model)s\" is already assigned to the active Model warranty policy "
                    "\"%(other)s\" of the same company. A model can belong to only one Model "
                    "policy per company.",
                    model=model.display_name, other=other.name))

    @api.model_create_multi
    def create(self, vals_list):
        policies = super().create(vals_list)
        policies._mark_products_warranty_applicable()
        return policies

    def write(self, vals):
        result = super().write(vals)
        if {'applies_to', 'product_tmpl_ids', 'product_brand_ids', 'product_model_ids',
                'active'} & vals.keys():
            self._mark_products_warranty_applicable()
        return result

    @api.depends('category_link_ids')
    def _compute_product_categ_ids(self):
        for policy in self:
            policy.product_categ_ids = policy.category_link_ids

    def _inverse_product_categ_ids(self):
        """Link the added categories to this policy and unlink the removed ones. A category
        already linked to another policy is refused (it must be removed there first)."""
        for policy in self:
            current = policy.category_link_ids
            added = policy.product_categ_ids - current
            removed = current - policy.product_categ_ids
            conflict = added.filtered(
                lambda categ: categ.warranty_policy_id and categ.warranty_policy_id != policy)
            if conflict:
                raise ValidationError(_(
                    "Product category \"%(category)s\" already uses the warranty policy "
                    "\"%(other)s\". Remove it from that policy (or from the category) first: a "
                    "category can have only one warranty policy.",
                    category=conflict[0].display_name,
                    other=conflict[0].warranty_policy_id.name))
            if added:
                added.write({'warranty_policy_id': policy.id})
            if removed:
                removed.write({'warranty_policy_id': False})

    def _mark_products_warranty_applicable(self):
        """Products assigned to an active Product policy, or whose model / brand is on an
        active Model / Brand policy, become Warranty Applicable. Never reversed automatically:
        the flag is also used by the other warranty rules."""
        active = self.filtered('active')
        # Direct assignments count for every Applies To.
        templates = active.product_tmpl_ids
        Template = self.env['product.template'].with_context(active_test=False)
        for applies_to, policy_field, template_field in ATTRIBUTE_POLICIES:
            values = active.filtered(lambda policy: policy.applies_to == applies_to)[policy_field]
            if values:
                templates |= Template.search([(template_field, 'in', values.ids)])
        templates = templates.filtered(lambda template: not template.warranty_applicable)
        if templates:
            templates.write({'warranty_applicable': True})

    @api.model
    def _get_attribute_policy_map(self, applies_to, company, value_ids=None):
        """{brand / model id: active Brand / Model policy} for `company` (`applies_to` is
        'brand' or 'model'); a company policy has priority over a shared (no company) policy.
        Limited to `value_ids` when given."""
        policy_field = dict((a, p) for a, p, __ in ATTRIBUTE_POLICIES)[applies_to]
        domain = [('applies_to', '=', applies_to), ('company_id', 'in', [company.id, False])]
        if value_ids is not None:
            if not value_ids:
                return {}
            domain.append((policy_field, 'in', value_ids))
        value_map = {}
        for policy in self.search(domain).sorted(lambda p: (bool(p.company_id), p.id)):
            for value_id in policy[policy_field].ids:
                if value_ids is None or value_id in value_ids:
                    value_map[value_id] = policy
        return value_map

    @api.model
    def _get_brand_policy_map(self, company, brand_ids=None):
        return self._get_attribute_policy_map('brand', company, brand_ids)

    @api.model
    def _get_product_policy_map(self, company, template_ids=None, include_category=True):
        """{product template id: applicable policy} for `company`: the active policy the
        product is assigned to directly (Applicable Products, any Applies To), else the active
        Model policy of the product's model, else the
        active Brand policy of its brand, else the active Customer Type policy of one of its
        pricelist mapping lines, else (`include_category`) the active Default Warranty Policy
        of its category (priority Product > Model > Brand > Customer Type > Category). A
        company policy has priority over a shared (no company) policy. Limited to
        `template_ids` when given."""
        # Direct assignments (Applicable Products) count for every Applies To.
        domain = [('product_tmpl_ids', '!=', False), ('company_id', 'in', [company.id, False])]
        if template_ids is not None:
            if not template_ids:
                return {}
            domain.append(('product_tmpl_ids', 'in', template_ids))
        policy_map = {}
        for policy in self.search(domain).sorted(lambda p: (bool(p.company_id), p.id)):
            for template_id in policy.product_tmpl_ids.ids:
                if template_ids is None or template_id in template_ids:
                    policy_map[template_id] = policy

        Template = self.env['product.template'].with_context(active_test=False)
        # ATTRIBUTE_POLICIES is in priority order (Model before Brand); setdefault keeps the
        # higher-priority policy already found.
        for applies_to, __, template_field in ATTRIBUTE_POLICIES:
            value_map = self._get_attribute_policy_map(applies_to, company)
            if not value_map:
                continue
            template_domain = [(template_field, 'in', list(value_map))]
            if template_ids is not None:
                template_domain.append(('id', 'in', template_ids))
            for template in Template.search(template_domain):
                policy_map.setdefault(template.id, value_map[template[template_field].id])

        # Lowest priority: Customer Type policy of a pricelist linked to the product; with
        # several, the first link wins (see _get_pricelist_product_links).
        pricelist_map = self._get_customer_type_policy_map(company)
        if pricelist_map:
            for template_id, pricelist_id in self._get_pricelist_product_links(
                    list(pricelist_map), template_ids):
                policy_map.setdefault(template_id, pricelist_map[pricelist_id])

        if include_category:
            # Inherited from the category (not stored on the product): its active Default
            # Warranty Policy of `company` or shared.
            category_domain = [
                ('categ_id.warranty_policy_id.active', '=', True),
                ('categ_id.warranty_policy_id.company_id', 'in', [company.id, False]),
            ]
            if template_ids is not None:
                category_domain.append(('id', 'in', template_ids))
            for template in Template.search(category_domain):
                policy_map.setdefault(template.id, template.categ_id.warranty_policy_id)
        return policy_map

    @api.model
    def _get_pricelist_product_links(self, pricelist_ids, template_ids=None):
        """[(product template id, pricelist id)] linking products to `pricelist_ids`, in
        priority order: active Product + Pricelist Warranty Mapping lines (Priority, id), then
        standard pricelist price rules applied on a Product or Product Variant (oldest first).
        Category and All Products price rules are not links. Limited to `template_ids` when
        given."""
        if not pricelist_ids or (template_ids is not None and not template_ids):
            return []
        links = []
        rule_domain = [('pricelist_id', 'in', pricelist_ids)]
        if template_ids is not None:
            rule_domain.append(('product_tmpl_id', 'in', template_ids))
        for rule in self.env['warranty.product.pricelist.rule'].search(
                rule_domain, order='priority, id'):
            links.append((rule.product_tmpl_id.id, rule.pricelist_id.id))

        item_domain = [('pricelist_id', 'in', pricelist_ids),
                       ('applied_on', 'in', ('1_product', '0_product_variant'))]
        if template_ids is not None:
            item_domain += ['|', ('product_tmpl_id', 'in', template_ids),
                            ('product_id.product_tmpl_id', 'in', template_ids)]
        for item in self.env['product.pricelist.item'].search(item_domain, order='id'):
            template = item.product_tmpl_id or item.product_id.product_tmpl_id
            if template and (template_ids is None or template.id in template_ids):
                links.append((template.id, item.pricelist_id.id))
        return links

    @api.model
    def _get_customer_type_policy_map(self, company, pricelist_ids=None):
        """{pricelist id: active Customer Type policy} for `company`; a company policy has
        priority over a shared (no company) policy. Limited to `pricelist_ids` when given."""
        domain = [('applies_to', '=', 'customer_type'), ('company_id', 'in', [company.id, False])]
        if pricelist_ids is not None:
            if not pricelist_ids:
                return {}
            domain.append(('pricelist_ids', 'in', pricelist_ids))
        pricelist_map = {}
        for policy in self.search(domain).sorted(lambda p: (bool(p.company_id), p.id)):
            for pricelist_id in policy.pricelist_ids.ids:
                if pricelist_ids is None or pricelist_id in pricelist_ids:
                    pricelist_map[pricelist_id] = policy
        return pricelist_map

    @api.model
    def _get_product_policy(self, product_tmpl, company, include_category=True):
        """The applicable Product / Model / Brand / Customer Type (/ Category) policy of
        `product_tmpl` for `company`. Empty when none."""
        return self._get_product_policy_map(
            company, product_tmpl.ids, include_category=include_category).get(
            product_tmpl.id, self.browse())

    @api.constrains('service_offset_ids')
    def _check_service_offsets(self):
        for policy in self:
            numbers = sorted(policy.service_offset_ids.mapped('service_no'))
            if numbers != list(range(1, len(numbers) + 1)):
                raise ValidationError(_(
                    "Service offsets of policy %s must be numbered 1, 2, 3, ... without gaps.",
                    policy.name))
