from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PRICING_METHODS = [
    ('fixed', 'Fixed'),
    ('per_unit', 'Per Unit'),
    ('per_visit', 'Per Visit'),
    ('percentage', 'Percentage of Equipment / Sales Value'),
    ('tiered', 'Tiered Quantity'),
    ('site', 'Site-Based'),
    ('usage', 'Usage-Based'),
    ('hybrid', 'Hybrid'),
]
START_RULES = [
    ('activation', 'Activation Date'),
    ('manual', 'Manual Start Date'),
]
# Approved B4b: activation on Sales Order confirmation or on payment of the first scheduled
# invoice (the payment part needs the A5 billing schedule).
ACTIVATION_TRIGGERS = [
    ('sale_confirmation', 'On Sales Order Confirmation'),
    ('payment', 'On Payment of the First Invoice'),
]
RENEWAL_RULES = [
    ('manual', 'Manual'),
    ('auto_offer', 'Auto Offer'),
]
FREQUENCY_UNITS = [
    ('month', 'Month'),
    ('year', 'Year'),
]
DURATION_UNITS = [
    ('months', 'Months'),
    ('years', 'Years'),
]
SERVICE_BASES = [
    ('period', 'Period'),
    ('usage', 'Usage'),
]
USAGE_UNITS = [
    ('hours', 'Operating Hours'),
    ('cycles', 'Cycles'),
    ('km', 'KM'),
    ('units', 'Units Produced'),
    ('other', 'Other'),
]
# AMC-E04 / E05 (SRS 2.5, 7 "Job Creation Mode", 19): how the preventive visits are planned.
# Alert: an activity is created Alert Days before the due date (recommended for high volume);
# Manual: no alert, the coordinator plans from the AMC Visit Schedule.
VISIT_PLANNING_MODES = [
    ('alert', 'Alert-Driven'),
    ('manual', 'Manual'),
]


class AmcPlan(models.Model):
    """AMC Plan (Mapping 4 / SRS 2.12: pricelist / customer type, product / equipment,
    frequency, visit count, included free services, pricing method, billing plan, start / end
    criteria, renewal rule). Approved B5 / B5a: Visit Count (scheduled preventive visits) and
    Included Free Services (on-demand services) are separate entitlements, each per covered
    equipment line."""
    _name = 'amc.plan'
    _inherit = ['mail.thread']
    _description = 'AMC Plan'
    _order = 'sequence, name'

    def _default_company_value(self, field_name):
        return self.env.company[field_name]

    name = fields.Char(string='AMC Plan', required=True, translate=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', index=True, tracking=True,
                                 default=lambda self: self.env.company,
                                 help="Empty: available in all companies.")
    description = fields.Text(string='Description')
    # Applicability (pricelist / customer type, product / equipment).
    pricelist_ids = fields.Many2many(
        'product.pricelist', 'amc_plan_pricelist_rel', 'plan_id', 'pricelist_id',
        string='Pricelists / Customer Types',
        help="Customer types (pricelists) this plan applies to. Empty: all.")
    product_ids = fields.Many2many(
        'product.product', 'amc_plan_product_rel', 'plan_id', 'product_id',
        string='Applicable Products', help="Covered equipment products. Empty: all products.")
    category_ids = fields.Many2many(
        'product.category', 'amc_plan_category_rel', 'plan_id', 'category_id',
        string='Applicable Product Categories',
        help="Covered equipment categories (with their sub-categories). Empty: all.")
    # Service entitlements per covered equipment line (approved B5 / B5a).
    service_basis = fields.Selection(SERVICE_BASES, string='Service Basis', required=True,
                                     default='period', tracking=True)
    visit_count = fields.Integer(
        string='Visit Count (Preventive)', tracking=True,
        help="Scheduled preventive maintenance visits per covered equipment line during the "
             "contract (generated at AMC activation).")
    frequency_value = fields.Integer(
        string='Visit Frequency', tracking=True,
        help="Preventive visits per frequency unit, e.g. 3 visits per Year.")
    frequency_unit = fields.Selection(FREQUENCY_UNITS, string='Frequency Unit', default='year',
                                      tracking=True)
    usage_interval = fields.Float(
        string='Usage Interval', tracking=True,
        help="Usage-based plans: a preventive visit is due every this many usage units.")
    usage_unit = fields.Selection(USAGE_UNITS, string='Usage Unit', tracking=True)
    included_free_services = fields.Integer(
        string='Included Free Services (On-demand)', tracking=True,
        help="Additional customer-requested services per covered equipment line, available "
             "while the contract is active. Separate balance: never reduces the preventive "
             "visits.")
    entitlement_summary = fields.Char(string='Entitlements per Equipment Line',
                                      compute='_compute_entitlement_summary')
    # Commercial and contract rules.
    pricing_method = fields.Selection(
        PRICING_METHODS, string='Pricing Method', required=True, default='fixed', tracking=True,
        help="Method of new formula versions; a price uses the method of the formula version in "
             "force on the pricing date.")
    formula_ids = fields.One2many('amc.pricing.formula', 'plan_id', string='Formula Versions')
    current_formula_id = fields.Many2one('amc.pricing.formula', string='Formula in Force',
                                         compute='_compute_current_formula')
    billing_plan_id = fields.Many2one(
        'amc.billing.plan', string='Billing Plan', tracking=True,
        default=lambda self: self._default_company_value('amc_default_billing_plan_id'),
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    start_rule = fields.Selection(
        START_RULES, string='Start Criteria', required=True, tracking=True,
        default=lambda self: self._default_company_value('amc_default_start_rule') or 'activation')
    duration_value = fields.Integer(string='Contract Duration', default=12, required=True,
                                    tracking=True)
    duration_unit = fields.Selection(DURATION_UNITS, string='Duration Unit', default='months',
                                     required=True, tracking=True)
    renewal_rule = fields.Selection(
        RENEWAL_RULES, string='Renewal Rule', required=True, tracking=True,
        default=lambda self: self._default_company_value('amc_default_renewal_rule') or 'manual')
    activation_trigger = fields.Selection(
        ACTIVATION_TRIGGERS, string='Activation Trigger', tracking=True,
        help="Empty: the company's AMC Activation Trigger.")
    alert_days = fields.Integer(
        string='Visit Alert Days', tracking=True,
        default=lambda self: self._default_company_value('amc_default_alert_days'),
        help="Days before a preventive visit's due date when the alert is created.")
    # Phase A4 (AMC-E04 / E05 / E08; SRS 10.3 Grace Period End Date, 12 #6 / #23).
    visit_planning_mode = fields.Selection(
        VISIT_PLANNING_MODES, string='Visit Planning', required=True, default='alert',
        tracking=True,
        help="Alert-Driven: a to-do is created for the contract responsible Alert Days before "
             "each preventive visit is due. Manual: no alert; visits are planned from the AMC "
             "Visit Schedule.")
    grace_days = fields.Integer(
        string='Grace Period (Days)', tracking=True,
        help="Days after the due date during which a preventive visit is still Overdue (not "
             "Missed).")
    auto_mark_missed = fields.Boolean(
        string='Mark Missed After Grace Period', tracking=True,
        help="When set, the daily scheduler marks preventive visits Missed once the grace "
             "period has passed. A Missed visit is not consumed; an AMC Manager can reopen it "
             "(carry-forward) while the contract is running.")
    renewal_notice_days = fields.Integer(
        string='Renewal Notice (Days)', default=30, tracking=True,
        help="The contract becomes Expiring this many days before its end date (renewal "
             "reminder). Auto Offer renewal rule: the renewal contract is prepared at that "
             "moment.")

    _sql_constraints = [
        ('name_company_uniq', 'unique(name, company_id)',
         'An AMC Plan with this name already exists in this company.'),
    ]

    @api.depends('visit_count', 'included_free_services', 'frequency_value', 'frequency_unit',
                 'service_basis', 'usage_interval', 'usage_unit')
    def _compute_entitlement_summary(self):
        units = dict(USAGE_UNITS)
        for plan in self:
            if plan.service_basis == 'usage':
                schedule = _("every %(interval)s %(unit)s", interval=plan.usage_interval,
                             unit=units.get(plan.usage_unit, ''))
            else:
                schedule = _("%(count)s per %(unit)s", count=plan.frequency_value,
                             unit=dict(FREQUENCY_UNITS).get(plan.frequency_unit, ''))
            plan.entitlement_summary = _(
                "%(visits)s preventive visits (%(schedule)s) + %(free)s on-demand services per "
                "covered equipment line", visits=plan.visit_count, schedule=schedule,
                free=plan.included_free_services)

    def _compute_current_formula(self):
        today = fields.Date.context_today(self)
        for plan in self:
            plan.current_formula_id = plan._amc_pricing_formula(today, raise_missing=False)

    def _amc_pricing_formula(self, date, raise_missing=True):
        """The Active formula version in force on `date` (approved P1 / C3)."""
        self.ensure_one()
        formula = self.formula_ids.filtered(
            lambda f: f.state == 'active' and f._covers(date)).sorted('version', reverse=True)[:1]
        if not formula and raise_missing:
            raise UserError(_("AMC Plan %(plan)s has no Active pricing formula on %(date)s.",
                              plan=self.name, date=date))
        return formula

    def action_open_pricing_preview(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Price Preview"),
            'res_model': 'amc.pricing.preview',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_plan_id': self.id},
        }

    def _duration_months(self):
        self.ensure_one()
        return self.duration_value * (12 if self.duration_unit == 'years' else 1)

    def _amc_visit_interval_months(self):
        """Months between two preventive visits of a period-based plan (AMC-B04 / E02), e.g.
        3 visits per Year -> every 4 months, 1 visit per Month -> every month."""
        self.ensure_one()
        if self.service_basis != 'period' or self.frequency_value <= 0:
            return 0
        unit_months = 12 if self.frequency_unit == 'year' else 1
        return unit_months / self.frequency_value

    @api.constrains('visit_count', 'included_free_services', 'frequency_value',
                    'frequency_unit', 'duration_value', 'duration_unit', 'service_basis',
                    'usage_interval', 'usage_unit', 'alert_days', 'grace_days',
                    'renewal_notice_days')
    def _check_entitlements(self):
        """Approved B5: both counts configurable, never negative, at least one service; the
        preventive visits must fit into the contract duration at the visit frequency."""
        for plan in self:
            if min(plan.visit_count, plan.included_free_services, plan.frequency_value,
                   plan.alert_days, plan.duration_value, plan.grace_days,
                   plan.renewal_notice_days) < 0 or plan.usage_interval < 0:
                raise ValidationError(_("AMC Plan %s: counts, frequency, duration, usage interval, "
                                        "alert, grace and renewal notice days cannot be "
                                        "negative.", plan.name))
            if plan.duration_value <= 0:
                raise ValidationError(_("AMC Plan %s: the contract duration must be greater "
                                        "than zero.", plan.name))
            if not plan.visit_count and not plan.included_free_services:
                raise ValidationError(_("AMC Plan %s: set a Visit Count or Included Free "
                                        "Services (or both).", plan.name))
            if not plan.visit_count:
                continue
            if plan.service_basis == 'usage':
                if plan.usage_interval <= 0 or not plan.usage_unit:
                    raise ValidationError(_("AMC Plan %s: usage-based preventive visits need a "
                                            "Usage Interval and a Usage Unit.", plan.name))
                continue
            if plan.frequency_value <= 0 or not plan.frequency_unit:
                raise ValidationError(_("AMC Plan %s: preventive visits need a Visit Frequency "
                                        "(visits per month / year).", plan.name))
            months = plan._duration_months()
            capacity = plan.frequency_value * (months if plan.frequency_unit == 'month'
                                               else months / 12.0)
            if plan.visit_count > capacity:
                raise ValidationError(_(
                    "AMC Plan %(plan)s: %(count)s preventive visits do not fit into %(months)s "
                    "months at %(freq)s visits per %(unit)s (at most %(capacity)s).",
                    plan=plan.name, count=plan.visit_count, months=months,
                    freq=plan.frequency_value, unit=dict(FREQUENCY_UNITS)[plan.frequency_unit],
                    capacity=int(capacity)))

    @api.constrains('billing_plan_id', 'visit_count', 'activation_trigger')
    def _check_billing_plan(self):
        for plan in self:
            billing = plan.billing_plan_id
            if billing.billing_frequency == 'per_visit' and not plan.visit_count:
                raise ValidationError(_("AMC Plan %s: Per Preventive Visit billing needs a Visit "
                                        "Count.", plan.name))
            if billing.billing_frequency == 'per_visit' \
                    and plan._amc_activation_trigger() == 'payment':
                raise ValidationError(_(
                    "AMC Plan %s: Per Preventive Visit billing has no invoice before the first "
                    "visit, so the contract must be activated On Sales Order Confirmation.",
                    plan.name))

    def _amc_activation_trigger(self):
        self.ensure_one()
        return self.activation_trigger or (self.company_id or self.env.company) \
            .amc_activation_trigger or 'payment'

    def _amc_billing_periods(self, quantity):
        """Number of billing periods of a contract (approved B4a / B4d): Upfront 1; Per
        Preventive Visit = preventive service entitlements (Visit Count x covered quantity);
        periodic = contract months / billing interval (rounded up)."""
        self.ensure_one()
        billing = self.billing_plan_id
        if not billing or billing.billing_frequency == 'upfront':
            return 1
        if billing.billing_frequency == 'per_visit':
            return int(round(self.visit_count * quantity))
        return -(-self._duration_months() // billing.interval_months)

    @api.constrains('company_id', 'billing_plan_id', 'pricelist_ids')
    def _check_company(self):
        """Multi-company consistency: linked records of the plan's company or shared."""
        for plan in self:
            company = plan.company_id
            for record in list(plan.billing_plan_id) + list(plan.pricelist_ids):
                if record.company_id and record.company_id != company:
                    raise ValidationError(_(
                        "AMC Plan %(plan)s: %(record)s belongs to another company.",
                        plan=plan.name, record=record.display_name))
