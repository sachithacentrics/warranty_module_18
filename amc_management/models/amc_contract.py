import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_is_zero, float_round

from .amc_plan import ACTIVATION_TRIGGERS, PRICING_METHODS

_logger = logging.getLogger(__name__)

CONTRACT_STATES = [
    ('draft', 'Draft'),
    ('quotation', 'Quotation'),
    ('awaiting_payment', 'Awaiting Payment'),
    ('active', 'Active'),
    ('on_hold', 'On Hold'),
    ('expiring', 'Expiring'),
    ('renewed', 'Renewed'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]
# Contracts whose coverage is running (AMC-C02 / C04): entitlements exist and may be consumed.
RUNNING_STATES = ('active', 'expiring', 'on_hold')
# States of a contract that is still being sold (renewal in preparation).
SELLING_STATES = ('draft', 'quotation', 'awaiting_payment')
PRICE_STATES = [
    ('none', 'Not Calculated'),
    ('calculated', 'Calculated'),
    ('overridden', 'Override Approved'),
]

_CONTRACT_MARKER = object()

_CANCELLING_MARKER = object()
PROTECTED_FIELDS = {
    'state', 'price_state', 'pricing_date', 'formula_id', 'formula_version', 'formula_method',
    'formula_currency_id', 'formula_amount', 'exchange_rate', 'conversion_date',
    'calculated_price', 'override_price', 'price_breakdown', 'price_approved_date',
    'sale_order_id', 'activation_trigger', 'activation_date', 'pricelist_overridden',
    'cancel_reason', 'currency_id',
    # Phases A4-A6.
    'contract_months', 'hold_reason', 'hold_date', 'hold_previous_state', 'close_reason',
    'close_date', 'renewal_of_id', 'expiring_date',
}

UNLOCKED_FIELDS = {'note', 'user_id'}
FREE_PREFIXES = ('message_', 'activity_', 'website_message')


def _marked(records):
    return records.with_context(amc_contract_marker=_CONTRACT_MARKER)


def _add_months(start, months):
    """`start` + a (possibly fractional) number of months: whole months with relativedelta,
    the fraction as days of a 30-day month (e.g. 2 visits per month = every half month)."""
    whole = int(months)
    days = int(round((months - whole) * 30))
    return start + relativedelta(months=whole) + timedelta(days=days)


class AmcContract(models.Model):
    """AMC Contract (Mapping 6 / SRS 2.12, 9.9; approved B2, B4a/b/d, B5/B5a, B9, C1-C5):
    standalone (no warranty card needed), customer, site, plan, covered equipment lines, price
    from the A2 pricing engine (snapshot of formula version, currency, rate, date), price /
    pricelist override approval, standard quotation, activation trigger.
    Phases A4-A6: service entitlements generated at activation, billing schedule, on-payment
    activation, hold / resume, expiring, renewal and closure (docs/09, docs/10)."""
    _name = 'amc.contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'AMC Contract'
    _order = 'id desc'

    name = fields.Char(string='Contract', required=True, readonly=True, copy=False,
                       default='New')
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, index=True,
                                 tracking=True)
    commercial_partner_id = fields.Many2one(related='partner_id.commercial_partner_id',
                                            store=True, index=True)
    site_id = fields.Many2one('res.partner', string='Site', tracking=True,
                              domain="[('id', 'child_of', commercial_partner_id)]",
                              help="Default service location of the equipment lines.")
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True,
                                 default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', string='Responsible', tracking=True,
                              default=lambda self: self.env.user)
    opportunity_id = fields.Many2one('amc.opportunity', string='Opportunity', readonly=True,
                                     copy=False, index=True)
    plan_id = fields.Many2one('amc.plan', string='AMC Plan', tracking=True,
                              domain="['|', ('company_id', '=', False), "
                                     "('company_id', '=', company_id)]")
    billing_plan_id = fields.Many2one(related='plan_id.billing_plan_id')
    state = fields.Selection(CONTRACT_STATES, string='Status', default='draft', required=True,
                             readonly=True, tracking=True, index=True, copy=False)
    line_ids = fields.One2many('amc.contract.line', 'contract_id', string='Covered Equipment',
                               copy=True)
    equipment_quantity = fields.Float(string='Covered Quantity',
                                      compute='_compute_equipment_quantity')

    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist',
                                   compute='_compute_pricelist', store=True, precompute=True,
                                   tracking=True)
    pricelist_overridden = fields.Boolean(string='Pricelist Override Approved', readonly=True,
                                          copy=False)
    currency_id = fields.Many2one('res.currency', string='Contract Currency',
                                  compute='_compute_pricelist', store=True, precompute=True,
                                  tracking=True)
    company_currency_id = fields.Many2one(related='company_id.currency_id')

    start_date = fields.Date(string='Start Date', tracking=True, copy=False,
                             help="Manual Start Date plans: enter it before the quotation. "
                                  "Activation Date plans: set at activation.")
    # Snapshot of the plan duration (defect fix: a later change of the plan must not move the
    # end date of contracts that were already sold). Follows the plan while Draft.
    contract_months = fields.Integer(string='Duration (Months)', compute='_compute_contract_months',
                                     store=True, readonly=True)
    end_date = fields.Date(string='End Date', compute='_compute_end_date', store=True)
    activation_trigger = fields.Selection(ACTIVATION_TRIGGERS, string='Activation Trigger',
                                          readonly=True, copy=False, tracking=True)
    activation_date = fields.Date(string='Activation Date', readonly=True, copy=False)
    # Usage-Based pricing input (defect fix: the contract price ignored the expected usage).
    expected_usage = fields.Float(string='Expected Usage', digits=(16, 2), tracking=True,
                                  help="Usage-Based / Hybrid pricing: expected usage of the "
                                       "contract period (e.g. operating hours).")

    price_state = fields.Selection(PRICE_STATES, string='Price Status', default='none',
                                   readonly=True, copy=False, tracking=True)
    pricing_date = fields.Date(string='Pricing Date', readonly=True, copy=False)
    formula_id = fields.Many2one('amc.pricing.formula', string='Formula Version', readonly=True,
                                 copy=False)
    formula_version = fields.Integer(string='Version', readonly=True, copy=False)
    formula_method = fields.Selection(PRICING_METHODS, string='Pricing Method', readonly=True,
                                      copy=False)
    formula_currency_id = fields.Many2one('res.currency', string='Formula Currency',
                                          readonly=True, copy=False)
    formula_amount = fields.Monetary(string='Formula Amount', readonly=True, copy=False,
                                     currency_field='formula_currency_id')
    exchange_rate = fields.Float(string='Exchange Rate', digits=(16, 6), readonly=True,
                                 copy=False)
    conversion_date = fields.Date(string='Conversion Date', readonly=True, copy=False)
    calculated_price = fields.Monetary(string='Calculated Price', readonly=True, copy=False,
                                       tracking=True)
    override_price = fields.Monetary(string='Approved Override Price', readonly=True,
                                     copy=False, tracking=True)
    price = fields.Monetary(string='Contract Value', compute='_compute_price', store=True,
                            help="Untaxed contract value in the contract currency: the "
                                 "approved override price, else the calculated price.")
    price_company_currency = fields.Monetary(
        string='Contract Value (Company Currency)', currency_field='company_currency_id',
        compute='_compute_price', store=True,
        help="At the exchange rate of the pricing date (information; accounting uses the "
             "invoice rates).")
    price_breakdown = fields.Text(string='Price Calculation', readonly=True, copy=False)
    price_approved_date = fields.Datetime(string='Price Agreed On', readonly=True, copy=False,
                                          help="Set when the quotation is confirmed: the price "
                                               "is frozen.")
    override_ids = fields.One2many('amc.price.override', 'contract_id', string='Override Requests',
                                   readonly=True)

    sale_order_id = fields.Many2one('sale.order', string='Quotation / Sales Order', readonly=True,
                                    copy=False)
    sale_order_ids = fields.One2many('sale.order', 'amc_contract_id', string='Quotations',
                                     readonly=True)
    sale_order_count = fields.Integer(compute='_compute_sale_order_count')
    invoice_count = fields.Integer(compute='_compute_sale_order_count')
    entitlement_summary = fields.Char(string='Entitlements', compute='_compute_equipment_quantity')
    cancel_reason = fields.Text(string='Cancellation Reason', readonly=True, copy=False)
    note = fields.Text(string='Notes')

    # Phase A4 - service entitlements (AMC-E01 .. E10).
    visit_ids = fields.One2many('amc.contract.visit', 'contract_id', string='AMC Visits',
                                readonly=True)
    visit_count = fields.Integer(string='Visits', compute='_compute_visit_stats')
    preventive_total = fields.Integer(string='Preventive Visits',
                                      compute='_compute_visit_stats', store=True)
    preventive_done = fields.Integer(string='Preventive Done', compute='_compute_visit_stats',
                                     store=True)
    preventive_balance = fields.Integer(string='Preventive Balance',
                                        compute='_compute_visit_stats', store=True)
    free_total = fields.Integer(string='Free Services Allowed', compute='_compute_visit_stats',
                                store=True)
    free_used = fields.Integer(string='Free Services Used', compute='_compute_visit_stats',
                               store=True)
    free_balance = fields.Integer(string='Free Services Balance',
                                  compute='_compute_visit_stats', store=True)
    next_visit_date = fields.Date(string='Next Visit Due', compute='_compute_visit_stats',
                                  store=True, index=True)
    # Phase A5 - billing schedule (AMC-B09 / G01 / G03).
    billing_line_ids = fields.One2many('amc.billing.line', 'contract_id',
                                       string='Billing Schedule', readonly=True)
    # Phase A6 - hold, expiry, renewal, closure (AMC-B08 / C04 / C05).
    hold_reason = fields.Text(string='Hold Reason', readonly=True, copy=False)
    hold_date = fields.Date(string='On Hold Since', readonly=True, copy=False)
    hold_previous_state = fields.Selection(CONTRACT_STATES, readonly=True, copy=False)
    expiring_date = fields.Date(string='Expiring Since', readonly=True, copy=False)
    close_reason = fields.Text(string='Closing Reason', readonly=True, copy=False)
    close_date = fields.Date(string='Closed On', readonly=True, copy=False)
    renewal_of_id = fields.Many2one('amc.contract', string='Renewal Of', readonly=True,
                                    copy=False, index=True, ondelete='restrict')
    renewal_ids = fields.One2many('amc.contract', 'renewal_of_id', string='Renewals',
                                  readonly=True)
    renewal_count = fields.Integer(compute='_compute_renewal_count')

    @api.depends('line_ids.quantity', 'plan_id.visit_count', 'plan_id.included_free_services')
    def _compute_equipment_quantity(self):
        for contract in self:
            quantity = sum(contract.line_ids.mapped('quantity'))
            contract.equipment_quantity = quantity
            plan = contract.plan_id
            contract.entitlement_summary = _(
                "%(visits)g preventive service entitlements + %(free)g on-demand services "
                "(%(per_visit)s + %(per_free)s per covered unit; generated at activation)",
                visits=plan.visit_count * quantity,
                free=plan.included_free_services * quantity, per_visit=plan.visit_count,
                per_free=plan.included_free_services) if plan else False

    @api.depends('partner_id', 'company_id')
    def _compute_pricelist(self):
        """customer pricelist (customer -> country group -> AMC
        Default Pricelist -> company currency); an approved override is kept."""
        for contract in self:
            company = contract.company_id or self.env.company
            if not contract.pricelist_overridden:
                contract.pricelist_id = company._amc_resolve_pricelist(contract.partner_id)[0] \
                    if contract.partner_id else self.env['product.pricelist']
            contract.currency_id = company._amc_currency(contract.pricelist_id or None)

    @api.depends('plan_id')
    def _compute_contract_months(self):
        for contract in self:
            contract.contract_months = contract.plan_id._duration_months() \
                if contract.plan_id else 0

    @api.depends('start_date', 'contract_months')
    def _compute_end_date(self):
        for contract in self:
            contract.end_date = contract.start_date + relativedelta(
                months=contract.contract_months, days=-1) \
                if contract.start_date and contract.contract_months else False

    @api.depends('calculated_price', 'override_price', 'price_state', 'exchange_rate',
                 'formula_currency_id', 'currency_id')
    def _compute_price(self):
        for contract in self:
            price = contract.override_price if contract.price_state == 'overridden' \
                else contract.calculated_price
            contract.price = price
            company = contract.company_id or self.env.company
            if contract.currency_id and contract.currency_id != company.currency_id \
                    and contract.pricing_date:
                contract.price_company_currency = contract.currency_id._convert(
                    price, company.currency_id, company, contract.pricing_date)
            else:
                contract.price_company_currency = price

    def _compute_sale_order_count(self):
        for contract in self:
            orders = contract.sudo().sale_order_ids
            contract.sale_order_count = len(orders)
            contract.invoice_count = len(orders.invoice_ids)

    @api.depends('visit_ids.state', 'visit_ids.visit_type', 'visit_ids.due_date')
    def _compute_visit_stats(self):
        for contract in self:
            visits = contract.visit_ids
            preventive = visits.filtered(lambda visit: visit.visit_type == 'preventive')
            free = visits - preventive
            live = lambda records: records.filtered(lambda v: v.state != 'cancelled')
            contract.visit_count = len(visits)
            contract.preventive_total = len(live(preventive))
            contract.preventive_done = len(preventive.filtered(lambda v: v.state == 'completed'))
            contract.preventive_balance = len(preventive.filtered(
                lambda v: v.state in ('pending', 'scheduled', 'in_progress')))
            contract.free_total = len(live(free))
            contract.free_used = len(free.filtered(lambda v: v.state == 'completed'))
            contract.free_balance = len(free.filtered(
                lambda v: v.state in ('pending', 'scheduled', 'in_progress')))
            due = preventive.filtered(
                lambda v: v.state in ('pending', 'scheduled', 'in_progress') and v.due_date)
            contract.next_visit_date = min(due.mapped('due_date')) if due else False

    def _compute_renewal_count(self):
        for contract in self:
            contract.renewal_count = len(contract.renewal_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if PROTECTED_FIELDS & set(vals) - {'currency_id'} \
                    and self.env.context.get('amc_contract_marker') is not _CONTRACT_MARKER:
                raise UserError(_("AMC contracts are created as Draft; status and price are set "
                                  "by the contract actions."))
            if vals.get('name', 'New') == 'New':
                company = self.env['res.company'].browse(vals.get('company_id')) \
                    or self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'amc.contract') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        marked = self.env.context.get('amc_contract_marker') is _CONTRACT_MARKER
        if not marked:
            protected = PROTECTED_FIELDS & set(vals)
            if protected:
                raise UserError(_("The status, price and quotation of an AMC contract are set by "
                                  "its actions (%s).", ', '.join(sorted(protected))))
            changed = {key for key in vals if not key.startswith(FREE_PREFIXES)} \
                - UNLOCKED_FIELDS
            locked = self.filtered(lambda contract: contract.state != 'draft')
            if changed and locked:
                raise UserError(_("AMC contract %s is not Draft: its customer, plan, equipment "
                                  "and dates cannot be changed (cancel the quotation to return "
                                  "to Draft).", ', '.join(locked.mapped('name'))))
            pricing = {'partner_id', 'company_id', 'plan_id', 'start_date',
                       'expected_usage'} & set(vals)
        else:
            pricing = set()
        result = super().write(vals)
        if pricing:
            self.filtered(lambda contract: contract.price_state != 'none')._amc_reset_price(
                _("customer, plan, company, start date or expected usage changed"))
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(contract.state != 'draft' or contract.sale_order_ids for contract in self):
            raise UserError(_("Only Draft AMC contracts without quotation can be deleted."))

    @api.constrains('partner_id', 'site_id', 'company_id', 'plan_id')
    def _check_consistency(self):
        for contract in self:
            if contract.site_id and contract.site_id.commercial_partner_id \
                    != contract.commercial_partner_id:
                raise ValidationError(_("The site of %s must be an address of the customer.",
                                        contract.name))
            plan = contract.plan_id
            if plan and plan.company_id and plan.company_id != contract.company_id:
                raise ValidationError(_("AMC Plan %(plan)s belongs to another company than "
                                        "%(contract)s.", plan=plan.name, contract=contract.name))

    @api.constrains('expected_usage')
    def _check_expected_usage(self):
        for contract in self:
            if contract.expected_usage < 0:
                raise ValidationError(_("The expected usage of %s cannot be negative.",
                                        contract.name))

    def _amc_log(self, text):
        for contract in self:
            contract._message_log(body=Markup('<p>%s</p>') % text)

    def _amc_state_label(self):
        self.ensure_one()
        return dict(CONTRACT_STATES)[self.state]

    def _amc_reset_price(self, reason):
        """Contract data changed in Draft: the price must be calculated again; an approved
        override price no longer applies (approved B9: price for this data only)."""
        for contract in self:
            _marked(contract).write({'price_state': 'none', 'calculated_price': 0.0,
                                     'override_price': 0.0})
            contract._amc_log(_("Price reset (%s): calculate the price again.", reason))

    def _amc_check_group(self, group, action):
        if not self.env.user.has_group(group):
            raise AccessError(_("You are not allowed to %s.", action))

    def _amc_pricing_problems(self):
        self.ensure_one()
        problems = []
        if self.state != 'draft':
            problems.append(_("the contract is not Draft"))
        if not self.plan_id:
            problems.append(_("select an AMC Plan"))
        if not self.line_ids:
            problems.append(_("add the covered equipment"))
        if self.plan_id.start_rule == 'manual' and not self.start_date:
            problems.append(_("the plan uses a Manual Start Date: enter the Start Date"))
        # AMC-B02: a plan restricted to customer types (pricelists) applies to those only.
        plan_pricelists = self.plan_id.pricelist_ids
        if plan_pricelists and self.pricelist_id not in plan_pricelists:
            problems.append(_("AMC Plan %(plan)s applies to the pricelists %(pricelists)s, not "
                              "to %(pricelist)s", plan=self.plan_id.name,
                              pricelists=', '.join(plan_pricelists.mapped('display_name')),
                              pricelist=self.pricelist_id.display_name or _("no pricelist")))
        if self.plan_id and not self.plan_id.active:
            problems.append(_("AMC Plan %s is archived", self.plan_id.name))
        problems += self.line_ids._amc_line_problems()
        return problems

    def action_compute_price(self):
        """ The formula version in force today (= quotation
        date), converted into the contract currency with the standard rates; full snapshot. An
        approved override price stays until the data changes."""
        self._amc_check_group('amc_management.group_amc_coordinator', _("calculate AMC prices"))
        for contract in self:
            problems = contract._amc_pricing_problems()
            if problems:
                raise UserError(_("The price of %(contract)s cannot be calculated: %(problems)s.",
                                  contract=contract.name, problems='; '.join(problems)))
            today = fields.Date.context_today(contract)
            # Draft: the duration snapshot follows the current plan.
            months = contract.plan_id._duration_months()
            if contract.contract_months != months:
                _marked(contract).write({'contract_months': months})
            formula = contract.plan_id._amc_pricing_formula(today)
            result = formula._amc_compute_price(contract.line_ids._amc_pricing_lines(),
                                                contract.currency_id, today, months=months,
                                                usage=contract.expected_usage)
            vals = {
                'pricing_date': today, 'formula_id': formula.id,
                'formula_version': formula.version, 'formula_method': result['method'],
                'formula_currency_id': result['formula_currency'].id,
                'formula_amount': result['formula_amount'], 'exchange_rate': result['rate'],
                'conversion_date': result['conversion_date'],
                'calculated_price': result['price'],
                'price_breakdown': '\n'.join(result['breakdown']),
            }
            if contract.price_state != 'overridden':
                vals['price_state'] = 'calculated'
            _marked(contract).write(vals)
            contract._amc_log(_("Price calculated by %(user)s: %(price)s with %(formula)s "
                                "(rate %(rate)s on %(date)s).", user=self.env.user.name,
                                price=contract.currency_id.format(result['price']),
                                formula=formula.name, rate=result['rate'], date=today))
        return True

    def action_open_override(self):
        self.ensure_one()
        self._amc_check_group('amc_management.group_amc_coordinator',
                              _("request AMC overrides"))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Request Override"),
            'res_model': 'amc.price.override',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }

    def _amc_apply_override(self, override):
        """Approved B9 / C5: approved price -> override price; approved pricelist -> pricelist and
        currency changed, price to be calculated again."""
        self.ensure_one()
        if override.override_type == 'price':
            _marked(self).write({'override_price': override.requested_price,
                                 'price_state': 'overridden'})
        else:
            _marked(self).write({'pricelist_id': override.requested_pricelist_id.id,
                                 'pricelist_overridden': True,
                                 'currency_id': override.requested_pricelist_id.currency_id.id})
            self._amc_reset_price(_("pricelist / currency override approved"))

    def _amc_quotation_problems(self):
        self.ensure_one()
        problems = self._amc_pricing_problems()
        if self.price_state == 'none' or self.price <= 0:
            problems.append(_("calculate the price first"))
        elif self.price_state == 'calculated' \
                and self.pricing_date != fields.Date.context_today(self):
            problems.append(_("the price was calculated on %s: calculate it again for today's "
                              "quotation (approved C3)", self.pricing_date))

        open_orders = self.sudo().sale_order_ids.filtered(lambda order: order.state != 'cancel')
        if open_orders:
            problems.append(_("the contract already has the quotation %s",
                              ', '.join(open_orders.mapped('name'))))
        if self.override_ids.filtered(lambda override: override.state == 'requested'):
            problems.append(_("an override request waits for approval"))
        if not self.plan_id.billing_plan_id:
            problems.append(_("the plan has no Billing Plan"))
        product = self.company_id._amc_product()
        if not product:
            problems.append(_("configure the AMC Service Product (AMC Settings)"))
        if self.plan_id.billing_plan_id.billing_frequency == 'per_visit' \
                and self.plan_id._amc_activation_trigger() == 'payment':
            problems.append(_("Per Preventive Visit billing needs activation On Sales Order "
                              "Confirmation"))
        return problems

    def _amc_quotation_lines(self, product):
        """Approved B4a / B4d: quantity = billing periods, unit price = period amount; the
        final period carries the rounding difference so that the lines equal the contract
        value."""
        self.ensure_one()
        currency = self.currency_id
        periods = max(self.plan_id._amc_billing_periods(self.equipment_quantity), 1)
        regular = currency.round(self.price / periods)
        final = currency.round(self.price - regular * (periods - 1))
        billing = self.plan_id.billing_plan_id
        label = _("%(contract)s - %(plan)s (%(billing)s)", contract=self.name,
                  plan=self.plan_id.name, billing=billing.name)
        lines = []
        if periods == 1 or currency.is_zero(final - regular):
            lines.append({'qty': periods, 'price': regular,
                          'name': _("%(label)s: %(periods)s billing period(s)", label=label,
                                    periods=periods)})
        else:
            lines.append({'qty': periods - 1, 'price': regular,
                          'name': _("%(label)s: billing periods 1-%(last)s", label=label,
                                    last=periods - 1)})
            lines.append({'qty': 1, 'price': final,
                          'name': _("%(label)s: final billing period %(period)s (adjusted to "
                                    "the contract value)", label=label, period=periods)})
        return [(0, 0, {'product_id': product.id, 'name': line['name'],
                        'product_uom_qty': line['qty'], 'price_unit': line['price']})
                for line in lines]

    def action_create_quotation(self):
        """Create Quotation (Mapping 8): one standard Sales Quotation per contract (no duplicate
        while one is open), in the contract pricelist / currency; contract -> Quotation."""
        self.ensure_one()
        self._amc_check_group('amc_management.group_amc_coordinator',
                              _("create AMC quotations"))
        self._amc_check_group('sales_team.group_sale_salesman', _("create sales quotations"))
        # Row lock: two simultaneous clicks never create two quotations.
        self._amc_lock()
        problems = self._amc_quotation_problems()
        if problems:
            raise UserError(_("No quotation for %(contract)s: %(problems)s.",
                              contract=self.name, problems='; '.join(problems)))
        product = self.company_id._amc_product()
        order = self.env['sale.order'].with_company(self.company_id).with_context(
            amc_contract_marker=_CONTRACT_MARKER).create({
                'partner_id': self.partner_id.id,
                'partner_shipping_id': (self.site_id or self.partner_id).id,
                'company_id': self.company_id.id,
                'pricelist_id': self.pricelist_id.id or False,
                'amc_contract_id': self.id,
                'origin': self.name,
                'order_line': self._amc_quotation_lines(product),
            }).with_env(self.env)
        if order.currency_id != self.currency_id:
            raise UserError(_("The quotation currency %(order)s differs from the contract "
                              "currency %(contract)s.", order=order.currency_id.name,
                              contract=self.currency_id.name))
        if order.currency_id.compare_amounts(order.amount_untaxed, self.price):
            raise UserError(_("The quotation amount %(order)s differs from the contract value "
                              "%(contract)s.", order=order.amount_untaxed, contract=self.price))
        trigger = self.plan_id._amc_activation_trigger()
        _marked(self).write({'state': 'quotation', 'sale_order_id': order.id,
                             'activation_trigger': trigger})
        self._amc_log(_("Quotation %(order)s created (%(amount)s untaxed, activation: "
                        "%(trigger)s).", order=order.name,
                        amount=self.currency_id.format(order.amount_untaxed),
                        trigger=dict(ACTIVATION_TRIGGERS)[trigger]))
        return self.action_view_quotation()

    def _amc_lock(self):
        """Row lock against concurrent commercial / lifecycle actions on the same contract
        (duplicate quotation, double activation, duplicate renewal)."""
        self.env.cr.execute("SELECT id FROM amc_contract WHERE id IN %s FOR UPDATE",
                            [tuple(self.ids)])

    def action_reissue_quotation(self):
        """Approved C3: an expired quotation is cancelled and the price calculated again with
        the formula version and rate of today (an approved override price is kept)."""
        self.ensure_one()
        self._amc_check_group('amc_management.group_amc_coordinator',
                              _("reissue AMC quotations"))
        # sudo: the contract's own quotation is cancelled whoever created it.
        order = self.sudo().sale_order_id
        if self.state != 'quotation' or order.state not in ('draft', 'sent'):
            raise UserError(_("Only an open quotation can be reissued."))
        order.with_context(amc_contract_marker=_CONTRACT_MARKER)._action_cancel()
        self.action_compute_price()
        return self.action_create_quotation()

    def action_view_quotation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Quotation"),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }

    def action_view_quotations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Quotations"),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('amc_contract_id', '=', self.id)],
        }

    def action_view_invoices(self):
        self.ensure_one()
        invoices = self.sudo().sale_order_ids.invoice_ids
        action = self.env['ir.actions.act_window']._for_xml_id(
            'account.action_move_out_invoice_type')
        action.update({'domain': [('id', 'in', invoices.ids)],
                       'context': {'create': False, 'default_move_type': 'out_invoice'}})
        return action

    def action_view_visits(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'amc_management.action_amc_contract_visit')
        action.update({'domain': [('contract_id', '=', self.id)],
                       'context': {'search_default_filter_open': 1}})
        return action

    def action_view_renewals(self):
        self.ensure_one()
        if len(self.renewal_ids) == 1:
            return self.renewal_ids._amc_open()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Renewals"),
            'res_model': 'amc.contract',
            'view_mode': 'list,form',
            'domain': [('renewal_of_id', '=', self.id)],
        }

    def _amc_on_order_confirmed(self, order):
        """Sales Order confirmed (approved B4b): the price is frozen and the billing schedule
        generated; activation now (trigger On Sales Order Confirmation) or Awaiting Payment: the
        first billing period is released at once so that it can be invoiced, and its payment
        activates the contract (AMC-A05 / G04)."""
        self.ensure_one()
        if self.state != 'quotation' or order != self.sale_order_id:
            return
        _marked(self).write({'price_approved_date': fields.Datetime.now()})
        self._amc_generate_billing()
        if self.activation_trigger == 'sale_confirmation':
            self._amc_activate(_("Sales Order %s confirmed", order.name))
        else:
            _marked(self).write({'state': 'awaiting_payment'})
            first = self.sudo().billing_line_ids.sorted('sequence')[:1]
            first._amc_release()
            self._amc_log(_("Sales Order %s confirmed: Awaiting Payment. Invoice the first "
                            "billing period; its payment activates the contract.", order.name))

    def _amc_on_order_cancelled(self, order):
        """Quotation / order cancelled before activation: the contract returns to Draft (a new
        quotation can be created); the cancelled order stays as history."""
        self.ensure_one()
        if order != self.sale_order_id or self.state not in ('quotation', 'awaiting_payment'):
            return
        lines = self.sudo().billing_line_ids
        _marked(lines.filtered(lambda line: line.state == 'released')).write(
            {'state': 'cancelled'})
        _marked(lines.filtered(lambda line: line.state != 'cancelled')).unlink()
        _marked(self).write({'state': 'draft', 'sale_order_id': False,
                             'price_approved_date': False})
        self._amc_log(_("Quotation %s cancelled: the contract is Draft again.", order.name))

    def _amc_on_invoice_paid(self, invoice):
        """First AMC invoice paid (approved B4b, AMC-G03): Awaiting Payment -> Active."""
        for contract in self.filtered(lambda c: c.state == 'awaiting_payment'):
            contract._amc_activate(_("invoice %s paid", invoice.name))

    def _amc_activate(self, reason):
        """Activation (approved S2 / B4b): only by the AMC commercial trigger; start date
        (Activation Date plans) and coverage set; entitlements generated (AMC-C03 / E01) and
        the billing periods dated; a renewal renews its predecessor."""
        self.ensure_one()
        self._amc_lock()
        if self.state not in ('quotation', 'awaiting_payment'):
            return
        today = fields.Date.context_today(self)
        vals = {'state': 'active', 'activation_date': today}
        if not self.start_date:
            vals['start_date'] = today
        _marked(self).write(vals)
        self._amc_generate_visits()
        self._amc_schedule_billing()
        self._amc_log(_("Contract activated (%(reason)s): %(start)s - %(end)s; %(prev)s "
                        "preventive visits and %(free)s included free services generated.",
                        reason=reason, start=self.start_date, end=self.end_date,
                        prev=self.preventive_total, free=self.free_total))
        source = self.renewal_of_id
        if source and (source.state == 'closed' or (
                source.state in RUNNING_STATES and source.end_date and source.end_date < today)):
            source._amc_mark_renewed(self)
        # A contract that already reached its renewal window is Expiring at once.
        self._amc_check_expiring(today)

    def action_cancel_contract(self, reason=None):
        """Cancel (AMC Manager, reason): Draft / Quotation / Awaiting Payment contracts; the open
        quotation is cancelled. Active contracts are not cancelled but Closed (AMC-C04)."""
        self._amc_check_group('amc_management.group_amc_manager', _("cancel AMC contracts"))
        reason = (reason or self.env.context.get('amc_cancel_reason') or '').strip()
        if not reason:
            return {
                'type': 'ir.actions.act_window',
                'name': _("Cancel AMC Contract"),
                'res_model': 'amc.contract.cancel.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_contract_id': self.id},
            }
        for contract in self:
            if contract.state not in SELLING_STATES:
                raise UserError(_("Only Draft, Quotation or Awaiting Payment contracts can be "
                                  "cancelled; running contracts are closed (Close Contract)."))
            # sudo: the contract's own quotation is cancelled whoever created it.
            order = contract.sudo().sale_order_id
            if order and order.state != 'cancel':
                if order.invoice_ids.filtered(lambda move: move.state == 'posted'):
                    raise UserError(_("Sales Order %s has posted invoices: handle them in "
                                      "Accounting first.", order.name))
                order.with_context(amc_contract_marker=_CONTRACT_MARKER,
                                   amc_contract_cancelling=_CANCELLING_MARKER)._action_cancel()
            open_lines = contract.sudo().billing_line_ids.filtered(
                lambda line: line.state != 'cancelled')
            if open_lines:
                _marked(open_lines).write({'state': 'cancelled'})
            _marked(contract).write({'state': 'cancelled', 'cancel_reason': reason})
            contract._amc_log(_("Contract cancelled by %(user)s: %(reason)s",
                                user=self.env.user.name, reason=reason))
        return True

    # ------------------------------------------------------------------ A4 entitlements
    def _amc_generate_visits(self):
        """AMC-E01 / E02 / B06: per covered unit of every equipment line, Visit Count
        preventive visits (period plans: due every 12 / frequency months from the start, never
        after the end date; usage plans: every Usage Interval) and Included Free Services
        on-demand entitlements. Generated once (no duplicate on a repeated call)."""
        self.ensure_one()
        if self.visit_ids:
            return self.visit_ids
        plan = self.plan_id
        interval = plan._amc_visit_interval_months()
        vals_list = []
        for line in self.line_ids:
            units = max(int(float_round(line.quantity, precision_digits=0)), 1)
            for unit in range(1, units + 1):
                for number in range(1, plan.visit_count + 1):
                    vals = {'contract_id': self.id, 'line_id': line.id, 'unit_no': unit,
                            'visit_type': 'preventive', 'sequence_no': number,
                            'sequence_total': plan.visit_count}
                    if plan.service_basis == 'usage':
                        vals.update(usage_due=plan.usage_interval * number,
                                    usage_unit=plan.usage_unit)
                    else:
                        due = _add_months(self.start_date, interval * number)
                        vals['due_date'] = min(due, self.end_date) if self.end_date else due
                    vals_list.append(vals)
                for number in range(1, plan.included_free_services + 1):
                    vals_list.append({'contract_id': self.id, 'line_id': line.id,
                                      'unit_no': unit, 'visit_type': 'free_service',
                                      'sequence_no': number,
                                      'sequence_total': plan.included_free_services})
        return _marked(self.env['amc.contract.visit'].sudo()).create(vals_list)

    def _amc_on_visits_completed(self, visits):
        """A consumed preventive visit releases its Per Preventive Visit billing period."""
        lines = self.sudo().billing_line_ids.filtered(
            lambda line: line.visit_id in visits and line.state == 'planned')
        lines._amc_release()

    # ------------------------------------------------------------------ A5 billing
    def _amc_generate_billing(self):
        """Billing schedule from the confirmed Sales Order lines (approved B4a / B4d): one line
        per period, amounts = the order line unit prices (the final period carries the
        rounding difference). Dated at activation."""
        self.ensure_one()
        if self.billing_line_ids.filtered(lambda line: line.state != 'cancelled'):
            return self.billing_line_ids
        order_lines = self.sudo().sale_order_id.order_line.filtered(
            lambda line: not line.display_type).sorted('id')
        vals_list = []
        sequence = 0
        for order_line in order_lines:
            for __ in range(int(round(order_line.product_uom_qty))):
                sequence += 1
                vals_list.append({'contract_id': self.id, 'sequence': sequence,
                                  'sale_line_id': order_line.id,
                                  'amount': order_line.price_unit})
        return _marked(self.env['amc.billing.line'].sudo()).create(vals_list)

    def _amc_schedule_billing(self, release=True):
        """Billing dates from the start date (AMC-G03): Upfront on the start date; periodic in
        advance on each period start, in arrears on each period end; Per Preventive Visit: one
        period per preventive visit, released when the visit is consumed. `release`: release
        the periods already due (False: dates only, e.g. the 1.1.0 data migration)."""
        self.ensure_one()
        billing = self.plan_id.billing_plan_id
        lines = self.sudo().billing_line_ids.filtered(lambda line: line.state != 'cancelled') \
            .sorted('sequence')
        if not lines:
            return
        if billing.billing_frequency == 'per_visit':
            visits = self.visit_ids.filtered(lambda v: v.visit_type == 'preventive').sorted(
                lambda v: (v.due_date or fields.Date.to_date('9999-12-31'), v.usage_due, v.id))
            for line, visit in zip(lines, visits):
                _marked(line).write({'visit_id': visit.id, 'date': visit.due_date,
                                     'period_start': self.start_date,
                                     'period_end': self.end_date})
            return
        months = billing.interval_months or self.contract_months
        for index, line in enumerate(lines):
            start = _add_months(self.start_date, months * index)
            end = min(_add_months(self.start_date, months * (index + 1)) - timedelta(days=1),
                      self.end_date) if self.end_date else start
            date = start if billing.billing_timing == 'advance' else end
            _marked(line).write({'period_start': start, 'period_end': end, 'date': date})
        if release:
            self._amc_release_due_billing()

    def _amc_release_due_billing(self, today=None):
        today = today or fields.Date.context_today(self)
        for contract in self.filtered(lambda c: c.state in RUNNING_STATES):
            due = contract.sudo().billing_line_ids.filtered(
                lambda line: line.state == 'planned' and line.date and line.date <= today
                and not line.visit_id)
            due.sorted('sequence')._amc_release(today)

    def action_create_invoice(self):
        """Create the draft invoice of the released billing periods with the standard Sales
        invoicing (nothing is posted automatically)."""
        self.ensure_one()
        self._amc_check_group('amc_management.group_amc_coordinator', _("invoice AMC contracts"))
        order = self.sale_order_id
        if not order or order.invoice_status != 'to invoice':
            raise UserError(_("Contract %s has no released billing period to invoice.",
                              self.name))
        invoices = order._create_invoices()
        self._amc_log(_("Draft invoice %s created for the released billing periods.",
                        ', '.join(invoices.mapped('display_name'))))
        return self.action_view_invoices()

    # ------------------------------------------------------------------ A6 lifecycle
    def _amc_check_expiring(self, today=None):
        """Active -> Expiring inside the renewal notice window (AMC-C05 / B08); Auto Offer plans
        prepare the renewal contract at that moment."""
        today = today or fields.Date.context_today(self)
        for contract in self.filtered(lambda c: c.state == 'active' and c.end_date):
            notice = contract.plan_id.renewal_notice_days
            if contract.end_date - timedelta(days=notice) > today:
                continue
            _marked(contract).write({'state': 'expiring', 'expiring_date': today})
            contract._amc_log(_("Expiring: the contract ends on %s.", contract.end_date))
            user = contract.user_id or self.env.user
            contract.sudo().activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=contract.end_date,
                user_id=user.id, summary=_("AMC contract %s is expiring", contract.name),
                note=_("Contract %(contract)s of %(customer)s ends on %(date)s: prepare the "
                       "renewal.", contract=contract.name,
                       customer=contract.partner_id.display_name, date=contract.end_date))
            if contract.plan_id.renewal_rule == 'auto_offer' \
                    and not contract._amc_open_renewal():
                contract.sudo()._amc_create_renewal()

    def _amc_open_renewal(self):
        self.ensure_one()
        return self.renewal_ids.filtered(lambda c: c.state not in ('cancelled',))

    def action_open_reason_wizard(self):
        """Hold / Close need a reason (AMC Manager)."""
        self.ensure_one()
        action = self.env.context.get('amc_reason_action')
        self._amc_check_group('amc_management.group_amc_manager',
                              _("hold or close AMC contracts"))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Put On Hold") if action == 'hold' else _("Close Contract"),
            'res_model': 'amc.contract.reason.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id, 'default_action': action},
        }

    def _amc_hold(self, reason):
        """On Hold (AMC Manager, reason; assumption AS-03): no visit alerts and no new service
        planning; entitlements and dates are kept (the period is not extended); billing
        continues. Reversible with Resume."""
        self._amc_check_group('amc_management.group_amc_manager', _("hold AMC contracts"))
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to put a contract on hold."))
        for contract in self:
            if contract.state not in ('active', 'expiring'):
                raise UserError(_("Only Active or Expiring contracts can be put on hold (%s).",
                                  contract.name))
            _marked(contract).write({'state': 'on_hold', 'hold_reason': reason,
                                     'hold_date': fields.Date.context_today(contract),
                                     'hold_previous_state': contract.state})
            contract._amc_log(_("Put on hold by %(user)s: %(reason)s", user=self.env.user.name,
                                reason=reason))
        return True

    def action_resume(self):
        self._amc_check_group('amc_management.group_amc_manager', _("resume AMC contracts"))
        today = fields.Date.context_today(self)
        for contract in self:
            if contract.state != 'on_hold':
                raise UserError(_("Only contracts On Hold can be resumed (%s).", contract.name))
            if contract.end_date and contract.end_date < today:
                raise UserError(_("Contract %s has ended during the hold: close or renew it.",
                                  contract.name))
            _marked(contract).write({'state': 'active', 'hold_previous_state': False})
            contract._amc_log(_("Resumed by %(user)s (on hold since %(date)s).",
                                user=self.env.user.name, date=contract.hold_date))
            contract._amc_check_expiring(today)
        return True

    def _amc_close(self, reason, automatic=False):
        """Closed (AMC-C04): manually by an AMC Manager (reason) or by the scheduler after the
        end date. Open entitlements expire (not consumed); billing periods not yet released are
        cancelled (assumption AS-05); released / invoiced periods are left to Accounting."""
        if not automatic:
            self._amc_check_group('amc_management.group_amc_manager',
                                  _("close AMC contracts"))
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to close a contract."))
        for contract in self:
            if contract.state not in RUNNING_STATES:
                raise UserError(_("Only Active, Expiring or On Hold contracts can be closed "
                                  "(%s).", contract.name))
            contract._amc_end_entitlements(_("contract closed"))
            _marked(contract).write({'state': 'closed', 'close_reason': reason,
                                     'close_date': fields.Date.context_today(contract)})
            contract._amc_log(_("Contract closed%(by)s: %(reason)s",
                                by='' if automatic else _(" by %s", self.env.user.name),
                                reason=reason))
        return True

    def _amc_end_entitlements(self, reason):
        self.ensure_one()
        visits = self.visit_ids.filtered(lambda v: v.state in ('pending', 'scheduled',
                                                               'in_progress', 'missed'))
        if visits:
            _marked(visits).write({'state': 'expired', 'due_status': False})
            visits._amc_log(_("Expired (%s): not consumed.", reason))
        planned = self.sudo().billing_line_ids.filtered(lambda line: line.state == 'planned')
        if planned:
            _marked(planned).write({'state': 'cancelled'})
            self._amc_log(_("%(count)s billing period(s) not released were cancelled (%(reason)s).",
                            count=len(planned), reason=reason))

    def _amc_mark_renewed(self, renewal):
        """The predecessor of an activated renewal ends as Renewed (AMC-C05)."""
        self.ensure_one()
        if self.state in RUNNING_STATES:
            self._amc_end_entitlements(_("renewed by %s", renewal.name))
        if self.state in RUNNING_STATES + ('closed',):
            _marked(self).write({'state': 'renewed'})
            self._amc_log(_("Renewed by %s.", renewal.name))

    def action_renew(self):
        """Renew (AMC Coordinator; assumption AS-04): a new Draft contract linked to this one,
        same customer, site, plan and equipment, starting the day after the end date; it is
        priced again with the formula in force and sold with its own quotation / trigger. This
        contract becomes Renewed when the renewal is activated after its end date."""
        self.ensure_one()
        self._amc_check_group('amc_management.group_amc_coordinator', _("renew AMC contracts"))
        return self._amc_create_renewal()._amc_open()

    def _amc_create_renewal(self):
        self.ensure_one()
        self._amc_lock()
        if self.state not in RUNNING_STATES + ('closed',):
            raise UserError(_("Only Active, Expiring, On Hold or Closed contracts can be renewed "
                              "(%s).", self.name))
        open_renewal = self._amc_open_renewal().filtered(lambda c: c.state in SELLING_STATES
                                                         or c.state in RUNNING_STATES)
        if open_renewal:
            raise UserError(_("Contract %(contract)s already has the renewal %(renewal)s.",
                              contract=self.name, renewal=', '.join(open_renewal.mapped('name'))))
        if not self.plan_id.active:
            raise UserError(_("AMC Plan %s is archived: renew with another plan by creating a "
                              "new contract.", self.plan_id.name))
        renewal = _marked(self.env['amc.contract']).create({
            'partner_id': self.partner_id.id,
            'site_id': self.site_id.id or False,
            'company_id': self.company_id.id,
            'user_id': self.user_id.id,
            'plan_id': self.plan_id.id,
            'expected_usage': self.expected_usage,
            'start_date': self.end_date + timedelta(days=1) if self.end_date else False,
            'renewal_of_id': self.id,
            'note': self.note,
            'line_ids': [(0, 0, line._amc_renewal_values()) for line in self.line_ids],
        }).with_env(self.env)
        self._amc_log(_("Renewal %s prepared (Draft).", renewal.name))
        renewal._amc_log(_("Renewal of %(contract)s (ends %(date)s).", contract=self.name,
                           date=self.end_date))
        return renewal

    def _amc_open(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'amc.contract',
            'res_id': self.id,
            'view_mode': 'form',
        }

    # ------------------------------------------------------------------ scheduler
    @api.model
    def _cron_amc_daily(self, today=None):
        """Daily AMC scheduler (docs/10 §8.5): release due billing periods, Expiring, end of
        period (Renewed / Closed) and the visit monitoring. Every contract is processed in its
        own savepoint so one failure does not stop the others; repeated runs are idempotent."""
        today = today or fields.Date.context_today(self)
        running = self.search([('state', 'in', RUNNING_STATES)])
        for contract in running:
            try:
                with self.env.cr.savepoint():
                    contract._amc_daily(today)
            except Exception:
                _logger.exception("AMC daily scheduler failed for contract %s", contract.name)
        self.env['amc.contract.visit']._cron_amc_visits(today)
        return True

    def _amc_daily(self, today):
        self.ensure_one()
        self._amc_release_due_billing(today)
        self._amc_check_expiring(today)
        if self.state in RUNNING_STATES and self.end_date and self.end_date < today:
            renewal = self.renewal_ids.filtered(lambda c: c.state in RUNNING_STATES)
            if renewal:
                self._amc_mark_renewed(renewal[:1])
            else:
                self._amc_close(_("Contract period ended on %s.", self.end_date),
                                automatic=True)


class AmcContractLine(models.Model):
    """Covered equipment (Mapping 7): product, serial, site, quantity, equipment value (C4:
    original amount and currency kept, converted into the contract currency at the transfer
    date), coverage dates. Approved B5a: entitlements per covered unit."""
    _name = 'amc.contract.line'
    _description = 'AMC Covered Equipment'
    _order = 'contract_id, id'

    contract_id = fields.Many2one('amc.contract', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    serial_id = fields.Many2one('stock.lot', string='Serial / Lot',
                                domain="[('product_id', '=', product_id)]")
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    site_id = fields.Many2one('res.partner', string='Site',
                              help="Service location; empty = the contract site.")
    original_value = fields.Float(string='Original Equipment Value')
    original_currency_id = fields.Many2one('res.currency', string='Original Currency')
    value_rate = fields.Float(string='Conversion Rate', digits=(16, 6), readonly=True)
    value_date = fields.Date(string='Conversion Date', readonly=True)
    equipment_value = fields.Monetary(
        string='Equipment Value', compute='_compute_equipment_value', store=True,
        help="In the contract currency (formula input of Percentage / Hybrid pricing).")
    coverage_start_date = fields.Date(related='contract_id.start_date', string='Coverage Start')
    coverage_end_date = fields.Date(related='contract_id.end_date', string='Coverage End')

    @api.depends('product_id', 'serial_id', 'contract_id.name')
    def _compute_display_name(self):
        """e.g. "AMC/00003 - GREE 9000 BTU (SN-001)" (was the technical "amc.contract.line,1")."""
        for line in self:
            name = '%s - %s' % (line.contract_id.name or '', line.product_id.display_name or '')
            line.display_name = '%s (%s)' % (name, line.serial_id.name) if line.serial_id else name

    @api.depends('original_value', 'original_currency_id', 'contract_id.currency_id')
    def _compute_equipment_value(self):
        """Approved C4: converted with the standard rate of the transfer (entry) date."""
        for line in self:
            target = line.contract_id.currency_id
            source = line.original_currency_id or target
            date = line.value_date or fields.Date.context_today(line)
            company = line.contract_id.company_id or self.env.company
            if source and target and source != target:
                line.equipment_value = source._convert(line.original_value, target, company,
                                                       date)
            else:
                line.equipment_value = line.original_value

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.context_today(self)
        for vals in vals_list:
            vals.setdefault('value_date', today)
        lines = super().create(vals_list)
        lines._amc_snapshot_rate()
        lines.contract_id._amc_check_draft_lines()
        lines.contract_id.filtered(lambda c: c.price_state != 'none')._amc_reset_price(
            _("covered equipment changed"))
        return lines

    def write(self, vals):
        self.contract_id._amc_check_draft_lines()
        if {'original_value', 'original_currency_id'} & set(vals):
            vals = dict(vals, value_date=vals.get('value_date')
                        or fields.Date.context_today(self))
        result = super().write(vals)
        if {'original_value', 'original_currency_id'} & set(vals):
            self._amc_snapshot_rate()
        if {'product_id', 'quantity', 'original_value', 'original_currency_id', 'site_id',
                'serial_id'} & set(vals):
            self.contract_id.filtered(lambda c: c.price_state != 'none')._amc_reset_price(
                _("covered equipment changed"))
        return result

    def unlink(self):
        contracts = self.contract_id
        contracts._amc_check_draft_lines()
        result = super().unlink()
        contracts.exists().filtered(lambda c: c.price_state != 'none')._amc_reset_price(
            _("covered equipment changed"))
        return result

    def _amc_snapshot_rate(self):
        for line in self:
            target = line.contract_id.currency_id
            source = line.original_currency_id
            company = line.contract_id.company_id
            if source and target and source != target:
                rate = self.env['res.currency']._get_conversion_rate(source, target, company,
                                                                     line.value_date)
            else:
                rate = 1.0
            if line.value_rate != rate:
                super(AmcContractLine, line).write({'value_rate': rate})

    def _amc_renewal_values(self):
        """Values copied to the renewal contract (AS-04)."""
        self.ensure_one()
        return {'product_id': self.product_id.id, 'serial_id': self.serial_id.id or False,
                'quantity': self.quantity, 'site_id': self.site_id.id or False,
                'original_value': self.original_value,
                'original_currency_id': self.original_currency_id.id or False}

    def _amc_serial_conflicts(self):
        """Open contracts already covering the serial of this line. The predecessor / successor
        of a renewal never conflict with each other (same unit, consecutive periods)."""
        self.ensure_one()
        contract = self.contract_id
        others = self.search([
            ('id', '!=', self.id), ('serial_id', '=', self.serial_id.id),
            ('contract_id.state', 'not in', ('cancelled', 'closed', 'renewed'))])
        return others.filtered(lambda other: other.contract_id != contract.renewal_of_id
                               and other.contract_id.renewal_of_id != contract
                               and other.contract_id != contract)

    def _amc_line_problems(self):
        """Plan applicability (products / categories), serial of the product, quantity 1 per
        serial, a serial covered by only one open contract, whole covered quantities."""
        problems = []
        for line in self:
            plan = line.contract_id.plan_id
            product = line.product_id
            if plan.product_ids or plan.category_ids:
                in_category = any(product.categ_id.parent_path.startswith(categ.parent_path)
                                  for categ in plan.category_ids if product.categ_id.parent_path)
                if product not in plan.product_ids and not in_category:
                    problems.append(_("%(product)s is not covered by AMC Plan %(plan)s",
                                      product=product.display_name, plan=plan.name))
            if line.serial_id:
                if line.serial_id.product_id != product:
                    problems.append(_("serial %s belongs to another product",
                                      line.serial_id.name))
                if line.quantity != 1:
                    problems.append(_("a line with serial %s covers quantity 1",
                                      line.serial_id.name))
                others = line._amc_serial_conflicts()
                if others:
                    problems.append(_("serial %(serial)s is already covered by %(contract)s",
                                      serial=line.serial_id.name,
                                      contract=', '.join(others.contract_id.mapped('name'))))
            if line.quantity <= 0:
                problems.append(_("equipment quantities must be greater than zero"))
            elif not float_is_zero(line.quantity - round(line.quantity), precision_digits=6):
                # AMC-E01 / B5a: entitlements are generated per covered unit.
                problems.append(_("covered quantities are whole units (%s)",
                                  product.display_name))
            site = line.site_id
            if site and site.commercial_partner_id != line.contract_id.commercial_partner_id:
                problems.append(_("site %s is not an address of the customer", site.display_name))
        return problems

    def _amc_pricing_lines(self):
        return [{'product': line.product_id, 'quantity': line.quantity,
                 'equipment_value': line.equipment_value,
                 'site': (line.site_id or line.contract_id.site_id
                          or line.contract_id.partner_id).id} for line in self]

    @api.constrains('quantity', 'serial_id', 'product_id', 'site_id')
    def _check_line(self):
        problems = self._amc_line_problems()
        if problems:
            raise ValidationError('; '.join(problems))


class AmcContractDraftLines(models.Model):
    _inherit = 'amc.contract'

    def _amc_check_draft_lines(self):
        if self.env.context.get('amc_contract_marker') is _CONTRACT_MARKER:
            return
        locked = self.filtered(lambda contract: contract.state != 'draft')
        if locked:
            raise UserError(_("The covered equipment of %s can only be changed while the "
                              "contract is Draft.", ', '.join(locked.mapped('name'))))
