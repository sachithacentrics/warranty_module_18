import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

LEGACY_PRODUCT_POLICY_PARAM = 'warranty_management.legacy_product_policies_migrated'
LEGACY_PRICELIST_RULE_PARAM = 'warranty_management.legacy_pricelist_rules_logged'

# Flexible service dates (BA-approved enhancement F2 / F5).
EARLY_SERVICE_RULES = [
    ('alert', 'From Alert Date'),
    ('days', 'Days Before Due'),
    ('any', 'Any Date'),
]
LATE_SERVICE_HANDLING = [
    ('block', 'Block after Grace Period End'),
    ('approval', 'Manager Approval after Grace Period End'),
]


class WarrantyPolicy(models.Model):
    """Reusable warranty configuration. A policy is selected where it applies: Product +
    Pricelist Warranty Mapping line, Product (per company), Product Category, Company Default
    Warranty Policy (approved strict priority, doc/warranty_policy_resolution.md)."""
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
    ], string='Applies To (Legacy)')
    pricelist_ids = fields.Many2many(
        'product.pricelist', 'warranty_policy_pricelist_rel', 'policy_id', 'pricelist_id',
        string='Applicable Pricelists (Legacy)')
    product_tmpl_ids = fields.Many2many(
        'product.template', 'warranty_policy_product_tmpl_rel', 'policy_id', 'product_tmpl_id',
        string='Applicable Products (Legacy)')
    sale_order_type_id = fields.Selection([
        ('retail', 'Retail Sale'),
        ('project', 'Project Sale'),
        ('dealer', 'Dealer Sale'),
        ('amc', 'AMC Sale'),
    ], string='Sales Order Type (Legacy)')
    warranty_duration = fields.Integer(string='Warranty Duration')
    warranty_duration_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Warranty Duration Unit')
    start_date_basis = fields.Selection([
        ('installation', 'Installation Date'),
        ('delivery', 'Delivery Date'),
        ('invoice', 'Invoice Date')
    ], string='Start Date Basis')
    free_service_count = fields.Integer(string='Free Service Count')
    free_service_period = fields.Integer(string='Free Service Period')
    free_service_period_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Free Service Period Unit')
    free_service_frequency = fields.Integer(
        string='Free Service Frequency',
        help="Interval between two free services. When empty, the free services are spread "
             "evenly over the Free Service Period.")
    free_service_frequency_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Free Service Frequency Unit')
    schedule_method = fields.Selection([
        ('equal_interval', 'Equal Interval'),
        ('fixed_offsets', 'Fixed Offsets'),
        ('manual', 'Manual Schedule'),
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
    usage_limit = fields.Float(
        string='Usage Limit', help="Required for a usage-based policy.")
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

    # Flexible service dates (BA-approved enhancement F1-F4 / K1-K2, 2026-10-24): copied to the
    # card at warranty confirmation. Empty Early Service Rule: the standard date rules (job
    # planning from the Alert Date, Part 2 scheduling from today, up to the Grace Period End).
    early_service_rule = fields.Selection(
        EARLY_SERVICE_RULES, string='Early Service Rule',
        help="Earliest permitted service date: the Alert Date, a number of days before the due "
             "date, or any date of the warranty period. Empty: standard date rules.")
    early_service_days = fields.Integer(
        string='Early Service Days', help="Days Before Due: earliest date = due date - days.")
    late_service_handling = fields.Selection(
        LATE_SERVICE_HANDLING, string='Late Service Handling', default='block',
        help="After the Grace Period End: blocked, or allowed up to a date approved by a "
             "Helpdesk manager (Late Service Exception, never after the warranty end date).")
    service_sequence_required = fields.Boolean(
        string='Enforce Service Sequence', default=True,
        help="A free service is completed only after the previous free services of the card are "
             "Completed, Expired or Cancelled; free services of one card are not merged.")

    @api.constrains('early_service_rule', 'early_service_days')
    def _check_early_service_days(self):
        for policy in self:
            if policy.early_service_days < 0 or (
                    policy.early_service_rule == 'days' and policy.early_service_days <= 0):
                raise ValidationError(_(
                    "Early Service Days of policy %s must be greater than zero for the rule Days "
                    "Before Due (and never negative).", policy.name))

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

    def _is_applicable_for_company(self, company):
        """Active and of `company` or shared: a policy of another company is never applied."""
        self.ensure_one()
        return self.active and self.company_id in (company, self.env['res.company'])

    def _check_warranty_configuration(self, level, product, order, warranty_basis):
        """Configuration error for a selected policy (approved Q3 / Decision 1): Warranty
        Duration and Duration Unit are required; a usage-based policy also needs its Usage
        Limit and Usage Unit."""
        self.ensure_one()
        params = {'policy': self.name, 'level': level, 'product': product.display_name,
                  'order': order.name}
        if self.warranty_duration <= 0 or not self.warranty_duration_unit:
            raise UserError(_(
                "Configuration Required: the warranty policy \"%(policy)s\" (selected on: "
                "%(level)s) for product \"%(product)s\" on %(order)s has no valid Warranty "
                "Duration and Duration Unit.", **params))
        if warranty_basis == 'usage' and (self.usage_limit <= 0 or not self.usage_unit):
            raise UserError(_(
                "Configuration Required: the usage-based warranty policy \"%(policy)s\" "
                "(selected on: %(level)s) for product \"%(product)s\" on %(order)s needs a Usage "
                "Limit and a Usage Unit.", **params))

    @api.model
    def _migrate_legacy_product_policies(self):
        """One-time copy (18.0.1.4.0) of the legacy direct product assignments (Applicable
        Products of active policies) to the per-company Warranty Policy of the products: the
        policy company, else the product company. Existing product values are never
        overwritten; assignments that cannot be placed are logged and skipped. Policies,
        categories, mapping lines, company settings and warranty cards are not changed."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param(LEGACY_PRODUCT_POLICY_PARAM):
            return
        # sudo: system migration over every company.
        policies = self.sudo().search([('product_tmpl_ids', '!=', False)])
        assignments = {}
        for policy in policies:
            for template in policy.product_tmpl_ids:
                company = policy.company_id or template.company_id
                if not company:
                    _logger.warning(
                        "Warranty policy migration: shared policy %s on shared product %s has "
                        "no company; not copied.", policy.name, template.display_name)
                    continue
                if template.company_id and template.company_id != company:
                    _logger.warning(
                        "Warranty policy migration: policy %s (company %s) on product %s of "
                        "company %s; not copied.", policy.name, company.name,
                        template.display_name, template.company_id.name)
                    continue
                assignments.setdefault((template, company), []).append(policy)
        for (template, company), assigned in assignments.items():
            if len(assigned) > 1:
                _logger.warning(
                    "Warranty policy migration: product %s has several policies in company %s "
                    "(%s); not copied.", template.display_name, company.name,
                    ', '.join(policy.name for policy in assigned))
                continue
            template = template.with_company(company)
            if template.warranty_policy_id:
                continue
            template.write({'warranty_policy_id': assigned[0].id})
            _logger.info("Warranty policy migration: product %s uses policy %s in company %s.",
                         template.display_name, assigned[0].name, company.name)
        ICP.set_param(LEGACY_PRODUCT_POLICY_PARAM, fields.Datetime.now())

    @api.model
    def _log_legacy_pricelist_rules(self):
        """The Product + Pricelist Warranty Mapping lines are
        retired without conversion; each active line is logged once so that it can be
        reconfigured as a product or pricelist Warranty Policy. Nothing is changed."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param(LEGACY_PRICELIST_RULE_PARAM):
            return
        # sudo: system review over every company.
        for rule in self.env['warranty.product.pricelist.rule'].sudo().search([]):
            _logger.warning(
                "Retired Product + Pricelist Warranty Mapping (not used any more, kept): "
                "product %s, pricelist %s, warranty %s %s, free services %s every %s %s, "
                "valid %s - %s.", rule.product_tmpl_id.display_name,
                rule.pricelist_id.display_name, rule.warranty_period,
                rule.warranty_period_unit or '', rule.free_service_count,
                rule.free_service_frequency, rule.free_service_frequency_unit or '',
                rule.effective_from or '-', rule.effective_to or '-')
        ICP.set_param(LEGACY_PRICELIST_RULE_PARAM, fields.Datetime.now())

    @api.constrains('service_offset_ids')
    def _check_service_offsets(self):
        for policy in self:
            numbers = sorted(policy.service_offset_ids.mapped('service_no'))
            if numbers != list(range(1, len(numbers) + 1)):
                raise ValidationError(_(
                    "Service offsets of policy %s must be numbered 1, 2, 3, ... without gaps.",
                    policy.name))
