from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round

from .amc_plan import PRICING_METHODS
from .amc_pricing_rounding import ROUNDING_METHODS
from .amc_safe_expression import AmcExpressionError, check_expression, evaluate_expression

FORMULA_STATES = [
    ('draft', 'Draft'),
    ('active', 'Active'),
    ('archived', 'Archived'),
]
TIER_BASES = [
    ('quantity', 'Quantity'),
    ('site', 'Site Count'),
]

ODOO_ROUNDING = {'half_up': 'HALF-UP', 'up': 'UP', 'down': 'DOWN'}
# Approved P3: the methods using the product / category factors per equipment line (Hybrid:
# the quantity-weighted factor as variable `factor`).
FACTOR_METHODS = ('per_unit', 'percentage')

HYBRID_VARIABLES = ('equipment_value', 'quantity', 'visit_count', 'contract_months', 'usage',
                    'site_count', 'factor', 'min_price', 'max_price')
# Fields of an Active / Archived version that only the activation / new version flow changes.
_FORMULA_MARKER = object()
LOCK_FREE_FIELDS = {'state', 'effective_to'}
FREE_PREFIXES = ('message_', 'activity_', 'website_message')


class AmcPricingFormula(models.Model):
    """AMC Pricing / Formula version (SRS 2.12 / 16.2, Mapping 5; approved P1-P6, C1, C3): one
    record per version of a plan; one Active version per plan and date (no overlapping
    effective periods); Active versions are locked (New Version for changes). Amounts are in
    the formula currency and converted into the target (contract) currency with the standard
    Odoo currency rates of the pricing date."""
    _name = 'amc.pricing.formula'
    _inherit = ['mail.thread']
    _description = 'AMC Pricing Formula Version'
    _order = 'plan_id, version desc'

    name = fields.Char(string='Formula', compute='_compute_name', store=True)
    plan_id = fields.Many2one('amc.plan', string='AMC Plan', required=True, index=True,
                              ondelete='restrict', tracking=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True, index=True)
    version = fields.Integer(string='Version', readonly=True, copy=False, default=1)
    state = fields.Selection(FORMULA_STATES, string='Status', default='draft', required=True,
                             readonly=True, copy=False, tracking=True, index=True)
    method = fields.Selection(PRICING_METHODS, string='Pricing Method', required=True,
                              tracking=True)
    effective_from = fields.Date(string='Effective From', required=True, tracking=True,
                                 default=fields.Date.context_today)
    effective_to = fields.Date(string='Effective To', tracking=True,
                               help="Empty: until the next version.")
    currency_id = fields.Many2one('res.currency', string='Formula Currency', required=True,
                                  tracking=True,
                                  default=lambda self: self.env.company.currency_id)

    fixed_amount = fields.Monetary(string='Fixed Amount', tracking=True)
    unit_rate = fields.Monetary(string='Rate per Unit', tracking=True)
    visit_rate = fields.Monetary(
        string='Rate per Preventive Service', tracking=True,
        help="Per Visit: rate per equipment-level preventive service entitlement (approved P6), "
             "not per physical technician visit.")
    percentage = fields.Float(string='Percentage (%)', digits=(16, 4), tracking=True)
    tier_basis = fields.Selection(TIER_BASES, string='Tier Basis', default='quantity',
                                  tracking=True)
    tier_ids = fields.One2many('amc.pricing.tier', 'formula_id', string='Tiers', copy=True)
    site_rate = fields.Monetary(string='Rate per Site', tracking=True)
    usage_base = fields.Monetary(string='Usage Base Amount', tracking=True)
    usage_rate = fields.Monetary(string='Rate per Usage Unit', tracking=True)
    hybrid_expression = fields.Char(
        string='Hybrid Expression', tracking=True,
        help="Controlled expression: numbers, + - * /, ( ), min, max, round, abs and the "
             "variables equipment_value, quantity, visit_count (preventive service "
             "entitlements), contract_months, usage, site_count, factor, min_price, max_price.")
    factor_ids = fields.One2many('amc.pricing.factor', 'formula_id', string='Pricing Factors',
                                 copy=True)

    min_price = fields.Monetary(string='Minimum Price', tracking=True)
    max_price = fields.Monetary(string='Maximum Price', tracking=True)
    rounding_step = fields.Float(string='Rounding Step', tracking=True,
                                 help="In the formula currency, e.g. 100. 0 = currency rounding "
                                      "only.")
    rounding_method = fields.Selection(ROUNDING_METHODS, string='Rounding Method',
                                       default='half_up', required=True, tracking=True)
    rounding_rule_ids = fields.One2many(
        'amc.pricing.rounding', 'formula_id', string='Target Currency Rounding', copy=True,
        help="Rounding of prices converted into another currency (approved P4). Without a rule "
             "for the target currency only its standard rounding applies.")
    # Sample preview (one sample equipment line).
    sample_quantity = fields.Float(string='Sample Quantity', default=10)
    sample_equipment_value = fields.Monetary(string='Sample Equipment / Sales Value')
    sample_site_count = fields.Integer(string='Sample Site Count', default=1)
    sample_usage = fields.Float(string='Sample Expected Usage')
    sample_product_id = fields.Many2one('product.product', string='Sample Product')
    sample_result = fields.Monetary(string='Sample Price', compute='_compute_sample')
    sample_breakdown = fields.Text(string='Sample Breakdown', compute='_compute_sample')
    is_current = fields.Boolean(string='In Force Today', compute='_compute_is_current')

    @api.depends('plan_id.name', 'version')
    def _compute_name(self):
        for formula in self:
            formula.name = '%s - v%s' % (formula.plan_id.name or '', formula.version)

    def _compute_is_current(self):
        today = fields.Date.context_today(self)
        for formula in self:
            formula.is_current = formula.state == 'active' and formula._covers(today)

    def _covers(self, date):
        self.ensure_one()
        return self.effective_from <= date and (not self.effective_to or date <= self.effective_to)

    @api.depends('method', 'fixed_amount', 'unit_rate', 'visit_rate', 'percentage', 'tier_basis',
                 'tier_ids.from_value', 'tier_ids.to_value', 'tier_ids.rate', 'site_rate',
                 'usage_base', 'usage_rate', 'hybrid_expression', 'factor_ids.factor',
                 'factor_ids.product_id', 'factor_ids.category_id', 'min_price', 'max_price',
                 'rounding_step', 'rounding_method', 'sample_quantity', 'sample_equipment_value',
                 'sample_site_count', 'sample_usage', 'sample_product_id', 'currency_id')
    def _compute_sample(self):
        for formula in self:


            if not formula.plan_id or not formula.currency_id or not formula.method:
                formula.sample_result, formula.sample_breakdown = 0.0, False
                continue
            try:
                result = formula._amc_compute_price(
                    formula._amc_sample_lines(), formula.currency_id,
                    formula.effective_from or fields.Date.context_today(formula),
                    usage=formula.sample_usage)
            except (UserError, ValidationError) as error:
                formula.sample_result = 0.0
                formula.sample_breakdown = error.args[0] if error.args else str(error)
                continue
            formula.sample_result = result['price']
            formula.sample_breakdown = '\n'.join(result['breakdown'])

    def _amc_sample_lines(self):
        self.ensure_one()
        sites = max(self.sample_site_count, 1)
        return [{'product': self.sample_product_id, 'quantity': self.sample_quantity / sites,
                 'equipment_value': self.sample_equipment_value / sites, 'site': index}
                for index in range(sites)]

    def _amc_check_draft_children(self):
        """Tiers, factors and rounding rules of Active / Archived versions are locked."""
        if self.env.context.get('amc_formula_marker') is _FORMULA_MARKER:
            return
        locked = self.filtered(lambda formula: formula.state != 'draft')
        if locked:
            raise UserError(_("Formula version %s is not Draft: its tiers, factors and rounding "
                              "rules cannot be changed (create a New Version).",
                              ', '.join(locked.mapped('name'))))


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            plan = self.env['amc.plan'].browse(vals.get('plan_id'))
            vals.setdefault('method', plan.pricing_method)
            if 'version' not in vals and plan:
                vals['version'] = (max(plan.with_context(active_test=False)
                                       .formula_ids.mapped('version'), default=0) + 1)
            if vals.get('state', 'draft') != 'draft' \
                    and self.env.context.get('amc_formula_marker') is not _FORMULA_MARKER:
                raise UserError(_("Formula versions are created as Draft and activated with "
                                  "Activate."))
        return super().create(vals_list)

    def write(self, vals):
        marked = self.env.context.get('amc_formula_marker') is _FORMULA_MARKER
        if not marked:
            if 'state' in vals:
                raise UserError(_("Use Activate / Archive to change the status of a formula "
                                  "version."))
            locked = self.filtered(lambda formula: formula.state != 'draft')
            changed = {key for key in vals if not key.startswith(FREE_PREFIXES)
                       and not key.startswith('sample_')}
            if locked and changed:
                raise UserError(_(
                    "Formula version %s is %s and cannot be changed: create a New Version "
                    "(approved formula history).", ', '.join(locked.mapped('name')),
                    dict(self._fields['state']._description_selection(self.env))[
                        locked[0].state]))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_used(self):
        if any(formula.state != 'draft' for formula in self):
            raise UserError(_("Only Draft formula versions can be deleted; Active and Archived "
                              "versions are kept as pricing history."))

    def _marked(self):
        return self.with_context(amc_formula_marker=_FORMULA_MARKER)


    def _amc_parameter_problems(self):
        """Required parameters of the method (checked at activation)."""
        self.ensure_one()
        problems = []
        required = {
            'fixed': ('fixed_amount',), 'per_unit': ('unit_rate',),
            'per_visit': ('visit_rate',), 'percentage': ('percentage',),
            'site': ('site_rate',), 'usage': ('usage_rate',),
        }
        for name in required.get(self.method, ()):
            if self[name] <= 0:
                problems.append(_("%s must be greater than zero.", self._fields[name].string))
        if self.method == 'tiered':
            problems += self.tier_ids._amc_tier_problems()
        if self.method == 'hybrid':
            try:
                check_expression(self.hybrid_expression, HYBRID_VARIABLES)
            except AmcExpressionError as error:
                problems.append(_("Hybrid expression: %s", error.args[0]))
        if self.method == 'per_visit' and not self.plan_id.visit_count:
            problems.append(_("Per Visit pricing needs a Visit Count on the plan."))
        return problems

    @api.constrains('fixed_amount', 'unit_rate', 'visit_rate', 'percentage', 'site_rate',
                    'usage_base', 'usage_rate', 'min_price', 'max_price', 'rounding_step',
                    'effective_from', 'effective_to', 'hybrid_expression', 'method')
    def _check_values(self):
        for formula in self:
            amounts = (formula.fixed_amount, formula.unit_rate, formula.visit_rate,
                       formula.percentage, formula.site_rate, formula.usage_base,
                       formula.usage_rate, formula.min_price, formula.max_price,
                       formula.rounding_step)
            if min(amounts) < 0:
                raise ValidationError(_("%s: amounts, percentage and rounding step cannot be "
                                        "negative.", formula.name))
            if formula.max_price and formula.min_price > formula.max_price:
                raise ValidationError(_("%s: the minimum price is greater than the maximum "
                                        "price.", formula.name))
            if formula.effective_to and formula.effective_to < formula.effective_from:
                raise ValidationError(_("%s: Effective To is before Effective From.",
                                        formula.name))
            if formula.method == 'hybrid' and formula.hybrid_expression:
                try:
                    check_expression(formula.hybrid_expression, HYBRID_VARIABLES)
                except AmcExpressionError as error:
                    raise ValidationError(_("%(formula)s - hybrid expression: %(error)s",
                                            formula=formula.name, error=error.args[0])) from None

    def _amc_overlapping(self):
        """Active versions of the plan whose effective period overlaps this one."""
        self.ensure_one()
        others = self.plan_id.formula_ids.filtered(
            lambda formula: formula.state == 'active' and formula != self)
        end = self.effective_to or fields.Date.to_date('9999-12-31')
        return others.filtered(lambda formula: formula.effective_from <= end and (
            not formula.effective_to or formula.effective_to >= self.effective_from))

    def action_activate(self):
        """Activate (approved P1): parameters complete; the open-ended previous version that
        started earlier is ended the day before; any other overlap is refused."""
        self._amc_check_manager()
        for formula in self:
            if formula.state != 'draft':
                raise UserError(_("Only Draft formula versions can be activated."))
            problems = formula._amc_parameter_problems()
            if problems:
                raise UserError(_("Formula %(formula)s cannot be activated:\n%(problems)s",
                                  formula=formula.name,
                                  problems='\n'.join('- %s' % p for p in problems)))
            for other in formula._amc_overlapping():
                if other.effective_from < formula.effective_from:
                    other._marked().write(
                        {'effective_to': formula.effective_from - timedelta(days=1)})
                    other._message_log(body=Markup('<p>%s</p>') % _(
                        "Ended on %(date)s by the activation of %(formula)s.",
                        date=other.effective_to, formula=formula.name))
            overlap = formula._amc_overlapping()
            if overlap:
                raise UserError(_("Formula %(formula)s overlaps the effective period of the "
                                  "Active version %(other)s.", formula=formula.name,
                                  other=', '.join(overlap.mapped('name'))))
            formula._marked().write({'state': 'active'})
        return True

    def action_archive_version(self):
        self._amc_check_manager()
        for formula in self:
            if formula.state != 'active':
                raise UserError(_("Only Active formula versions can be archived."))
            formula._marked().write({'state': 'archived'})
        return True

    def action_new_version(self):
        """New Version: Draft copy (parameters, tiers, factors, rounding rules) starting the day
        after the end of this version, else today."""
        self.ensure_one()
        self._amc_check_manager()
        start = self.effective_to + timedelta(days=1) if self.effective_to \
            else fields.Date.context_today(self)
        new = self.copy({'state': 'draft', 'effective_from': start, 'effective_to': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': new.id,
            'view_mode': 'form',
        }

    def _amc_check_manager(self):
        if not self.env.user.has_group('amc_management.group_amc_manager'):
            raise UserError(_("Only AMC Managers can activate, archive or version formulas."))

    def _amc_factor(self, product):
        """Approved P3: product factor, else the factor of the nearest category, else 1."""
        self.ensure_one()
        if product:
            line = self.factor_ids.filtered(lambda factor: factor.product_id == product)[:1]
            if line:
                return line.factor
            category = product.categ_id
            while category:
                line = self.factor_ids.filtered(lambda f, c=category: f.category_id == c)[:1]
                if line:
                    return line.factor
                category = category.parent_id
        return 1.0

    def _amc_compute_price(self, lines, target_currency, date, months=None, usage=0.0):
        """Price of `lines` (dicts: product, quantity, equipment_value, site) in
        `target_currency` on `date` (approved P1-P6, C1, C3). Returns a dict with the method
        amount, min / max, conversion (rate, date), rounding, final price and the breakdown."""
        self.ensure_one()
        plan = self.plan_id
        currency = self.currency_id
        months = months or plan._duration_months()
        quantity = sum(line['quantity'] for line in lines)
        equipment_value = sum(line['equipment_value'] for line in lines)
        site_count = len({line.get('site') for line in lines}) if lines else 0
        entitlements = plan.visit_count * quantity
        factors = [(line, self._amc_factor(line.get('product'))) for line in lines]
        weighted = (sum(line['quantity'] * factor for line, factor in factors) / quantity
                    if quantity else 1.0)
        fmt = lambda amount: currency.format(amount)
        num = lambda value: '%g' % value
        if not self.method:
            raise UserError(_("Formula %s has no pricing method.", self.name or ''))
        breakdown = [_("Formula %(formula)s (%(method)s), currency %(currency)s, pricing date "
                       "%(date)s.", formula=self.name, method=dict(PRICING_METHODS)[self.method],
                       currency=currency.name, date=date)]
        method = self.method
        if method == 'fixed':
            amount = self.fixed_amount
            breakdown.append(_("Fixed amount: %s.", fmt(amount)))
        elif method == 'per_unit':
            amount = sum(self.unit_rate * line['quantity'] * factor for line, factor in factors)
            breakdown.append(_("Per unit: %(rate)s x %(qty)s units x factors = %(amount)s.",
                               rate=fmt(self.unit_rate), qty=num(quantity), amount=fmt(amount)))
        elif method == 'per_visit':
            amount = self.visit_rate * entitlements
            breakdown.append(_(
                "Per visit: %(rate)s x %(ent)s preventive service entitlements (%(per)s per "
                "equipment x %(qty)s equipment) = %(amount)s. Physical technician visits are not "
                "counted: several equipment lines serviced in one visit still use one entitlement "
                "each.", rate=fmt(self.visit_rate), ent=num(entitlements), per=plan.visit_count,
                qty=num(quantity), amount=fmt(amount)))
        elif method == 'percentage':
            amount = sum(line['equipment_value'] * self.percentage / 100.0 * factor
                         for line, factor in factors)
            breakdown.append(_("Percentage: %(value)s x %(pct)s %% x factors = %(amount)s.",
                               value=fmt(equipment_value), pct=self.percentage,
                               amount=fmt(amount)))
        elif method == 'tiered':
            basis = quantity if self.tier_basis == 'quantity' else site_count
            tier = self.tier_ids._amc_tier_for(basis)
            if not tier:
                raise UserError(_("No pricing tier of %(formula)s covers %(basis)s %(label)s.",
                                  formula=self.name, basis=basis,
                                  label=dict(TIER_BASES)[self.tier_basis].lower()))
            amount = tier.rate * basis
            breakdown.append(_("Tiered (whole quantity): %(basis)s %(label)s in tier "
                               "%(start)s-%(end)s at %(rate)s = %(amount)s.", basis=num(basis),
                               label=dict(TIER_BASES)[self.tier_basis].lower(),
                               start=tier.from_value, end=tier.to_value or '...',
                               rate=fmt(tier.rate), amount=fmt(amount)))
        elif method == 'site':
            amount = self.site_rate * site_count
            breakdown.append(_("Site-based: %(rate)s x %(sites)s sites = %(amount)s.",
                               rate=fmt(self.site_rate), sites=site_count, amount=fmt(amount)))
        elif method == 'usage':
            amount = self.usage_base + self.usage_rate * usage
            breakdown.append(_("Usage: %(base)s + %(rate)s x %(usage)s = %(amount)s.",
                               base=fmt(self.usage_base), rate=fmt(self.usage_rate), usage=usage,
                               amount=fmt(amount)))
        else:
            values = {'equipment_value': equipment_value, 'quantity': quantity,
                      'visit_count': entitlements, 'contract_months': months, 'usage': usage,
                      'site_count': site_count, 'factor': weighted,
                      'min_price': self.min_price, 'max_price': self.max_price}
            try:
                amount = evaluate_expression(self.hybrid_expression, values)
            except AmcExpressionError as error:
                raise UserError(_("Hybrid expression of %(formula)s: %(error)s",
                                  formula=self.name, error=error.args[0])) from None
            breakdown.append(_("Hybrid: %(expr)s with %(values)s = %(amount)s.",
                               expr=self.hybrid_expression,
                               values=', '.join('%s=%s' % item for item in sorted(values.items())),
                               amount=fmt(amount)))
        if method in FACTOR_METHODS:
            generic = _("equipment")
            names = ['%s x%s' % (line['product'].display_name if line.get('product') else generic,
                                 num(factor)) for line, factor in factors]
            breakdown.append(_("Factors per equipment line: %s.", ', '.join(names) or '-'))
        method_amount = amount
        if self.min_price and amount < self.min_price:
            amount = self.min_price
            breakdown.append(_("Minimum price applied: %s.", fmt(amount)))
        if self.max_price and amount > self.max_price:
            amount = self.max_price
            breakdown.append(_("Maximum price applied: %s.", fmt(amount)))
        company = self.company_id or self.env.company
        if target_currency == currency:
            converted, rate = amount, 1.0
            step, rounding = self.rounding_step, self.rounding_method
            rounding_basis = _("formula rounding step %(step)s %(currency)s",
                               step=step, currency=currency.name) if step else False
        else:
            # Approved C1: standard Odoo conversion with the rate of the pricing date.
            rate = self.env['res.currency']._get_conversion_rate(currency, target_currency,
                                                                 company, date)
            converted = currency._convert(amount, target_currency, company, date, round=False)
            breakdown.append(_("Converted %(amount)s %(from)s to %(to)s at rate %(rate)s "
                               "(standard rate of %(date)s) = %(result)s.", amount=amount,
                               rate=rate, date=date, result=target_currency.format(converted),
                               **{'from': currency.name, 'to': target_currency.name}))
            # Approved P4: the formula's numeric step is never reused in another currency.
            rule = self.rounding_rule_ids.filtered(
                lambda line: line.currency_id == target_currency)[:1]
            step, rounding = (rule.step, rule.method) if rule else (0.0, 'half_up')
            rounding_basis = _("target currency rule %(step)s %(currency)s", step=step,
                               currency=target_currency.name) if rule else False
        price = converted
        if step:
            price = float_round(price, precision_rounding=step,
                                rounding_method=ODOO_ROUNDING[rounding])
            breakdown.append(_("Rounded (%(basis)s, %(method)s): %(price)s.",
                               basis=rounding_basis,
                               method=dict(ROUNDING_METHODS)[rounding],
                               price=target_currency.format(price)))
        else:
            breakdown.append(_("No rounding step for %s: standard currency rounding only.",
                               target_currency.name))
        price = target_currency.round(price)
        breakdown.append(_("Final price: %s.", target_currency.format(price)))
        return {
            'formula': self, 'version': self.version, 'method': method,
            'formula_currency': currency, 'method_amount': method_amount,
            'formula_amount': amount, 'target_currency': target_currency, 'rate': rate,
            'conversion_date': date, 'converted_amount': converted,
            'rounding_step': step, 'rounding_method': rounding, 'price': price,
            'quantity': quantity, 'entitlements': entitlements, 'site_count': site_count,
            'breakdown': breakdown,
        }


class AmcPricingTier(models.Model):
    _name = 'amc.pricing.tier'
    _description = 'AMC Pricing Tier'
    _order = 'formula_id, from_value'

    formula_id = fields.Many2one('amc.pricing.formula', required=True, ondelete='cascade',
                                 index=True)
    company_id = fields.Many2one(related='formula_id.company_id', store=True)
    currency_id = fields.Many2one(related='formula_id.currency_id')
    from_value = fields.Float(string='From', required=True)
    to_value = fields.Float(string='To', help="Empty / 0: no upper limit (last tier only).")
    rate = fields.Monetary(string='Rate', required=True)

    def _amc_tier_problems(self):
        """Approved P2: tiers start at 1 (or 0), do not overlap, have no gap; only the last
        one may be open-ended; rates > 0."""
        if not self:
            return [_("Tiered pricing needs at least one tier.")]
        problems = []
        tiers = self.sorted('from_value')
        if tiers[0].from_value > 1:
            problems.append(_("The first tier must start at 0 or 1."))
        for previous, tier in zip(tiers, tiers[1:]):
            if not previous.to_value:
                problems.append(_("Only the last tier can be open-ended."))
            elif tier.from_value <= previous.to_value:
                problems.append(_("Tiers %(a)s-%(b)s and %(c)s-%(d)s overlap.",
                                  a=previous.from_value, b=previous.to_value,
                                  c=tier.from_value, d=tier.to_value or '...'))
            elif tier.from_value - previous.to_value > 1:
                problems.append(_("Gap between the tiers ending at %(a)s and starting at %(b)s.",
                                  a=previous.to_value, b=tier.from_value))
        for tier in tiers:
            if tier.rate <= 0:
                problems.append(_("Tier rates must be greater than zero."))
            if tier.to_value and tier.to_value < tier.from_value:
                problems.append(_("A tier ends before it starts (%s).", tier.from_value))
        return problems

    def _amc_tier_for(self, value):
        for tier in self.sorted('from_value'):
            if tier.from_value <= value and (not tier.to_value or value <= tier.to_value):
                return tier
        return self.browse()

    @api.constrains('from_value', 'to_value', 'rate')
    def _check_tiers(self):
        for formula in self.formula_id:
            problems = formula.tier_ids._amc_tier_problems()
            if problems:
                raise ValidationError('%s: %s' % (formula.name, ' '.join(problems)))

    @api.model_create_multi
    def create(self, vals_list):
        self.env['amc.pricing.formula'].browse(
            [vals['formula_id'] for vals in vals_list if vals.get('formula_id')]
        )._amc_check_draft_children()
        return super().create(vals_list)

    def write(self, vals):
        self.formula_id._amc_check_draft_children()
        return super().write(vals)

    def unlink(self):
        self.formula_id._amc_check_draft_children()
        return super().unlink()
