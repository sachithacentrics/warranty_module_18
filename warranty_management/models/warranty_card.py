from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import float_round

from .res_company import get_valid_service_alert_users


# Service entitlements in these states are kept for history and cannot be deleted.
PROTECTED_ENTITLEMENT_STATES = ('completed', 'missed', 'expired', 'cancelled')

CARD_STATES = [
    ('draft', 'Draft'),
    ('ready', 'Ready to Confirm'),
    ('confirmed', 'Confirmed'),
    ('suspended', 'Suspended'),
    ('expired', 'Expired'),
    ('cancelled', 'Cancelled'),
]

# Fields read by _get_missing_requirements(); the Draft <-> Ready to Confirm
# state and the missing-requirements text are recomputed when they change.
REQUIREMENT_DEPENDS = [
    'policy_source', 'warranty_basis', 'start_criterion',
    'warranty_duration', 'warranty_duration_unit',
    'installation_date', 'warranty_start_date', 'warranty_end_date',
    'partner_id', 'company_id', 'policy_id.payment_check_required',
    'unit_warranty_ids', 'unit_warranty_ids.product_id',
    'unit_warranty_ids.sale_order_line_id', 'unit_warranty_ids.stock_move_line_id',
    'unit_warranty_ids.serial_ids',
    'delivery_ids', 'delivery_ids.state', 'delivery_ids.date_done',
    'sale_order_line_ids.invoice_lines.move_id.state',
    'sale_order_line_ids.invoice_lines.move_id.invoice_date',
    'sale_order_line_ids.invoice_lines.move_id.payment_state',
]


class WarrantyCard(models.Model):
    _name = 'warranty.card'
    _description = 'Warranty Card'
    _order = 'id desc'

    name = fields.Char(
        string='Warranty Card No.', required=True, readonly=True, copy=False, default='New')
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, index=True)
    product_id = fields.Many2one('product.product', string='Product')
    brand_id = fields.Char(string='Brand')
    model_id = fields.Char(string='Model')
    indoor_serial_id = fields.Many2one('stock.lot', string='Indoor Serial No.')
    outdoor_serial_id = fields.Many2one('stock.lot', string='Outdoor Serial No.')
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', index=True, readonly=True)
    sale_order_line_ids = fields.Many2many(
        'sale.order.line', 'warranty_card_sale_order_line_rel', 'card_id', 'line_id',
        string='Sales Order Lines', readonly=True)
    delivery_ids = fields.Many2many(
        'stock.picking', 'warranty_card_stock_picking_rel', 'card_id', 'picking_id',
        string='Delivery Orders', readonly=True)
    invoice_ids = fields.Many2many(
        'account.move', string='Invoices', compute='_compute_invoice_ids')
    installation_date = fields.Date(string='Installation Date')
    warranty_start_date = fields.Date(string='Warranty Start Date')
    warranty_end_date = fields.Date(string='Warranty End Date')
    state = fields.Selection(
        CARD_STATES, string='Status', default='draft', required=True, copy=False,
        compute='_compute_state', store=True, readonly=False, index=True)
    confirmation_status = fields.Selection(
        related='state', string='Confirmation Status')
    missing_requirements = fields.Text(
        string='Missing Confirmation Requirements', compute='_compute_missing_requirements',
        store=True)

    free_services_allowed = fields.Integer(string='Free Services Allowed', readonly=True)
    free_services_used = fields.Integer(
        string='Free Services Used', compute='_compute_free_services')
    free_services_missed = fields.Integer(
        string='Free Services Missed', compute='_compute_free_services')
    free_services_expired = fields.Integer(
        string='Free Services Expired', compute='_compute_free_services')
    free_services_cancelled = fields.Integer(
        string='Free Services Cancelled', compute='_compute_free_services')
    free_services_balance = fields.Integer(
        string='Free Services Balance', compute='_compute_free_services')
    replacement_count = fields.Integer(
        string='Replacement Count', compute='_compute_replacement_count')
    current_active_serial = fields.Boolean(string='Current Active Serial Flag', default=True)
    pdf_attachment_id = fields.Many2one(
        'ir.attachment', string='PDF Soft Copy', readonly=True, copy=False)
    print_count = fields.Integer(string='Print Count', compute='_compute_print_count')

    card_grouping_mode = fields.Selection([
        ('per_so', 'Per Sales Order'),
        ('per_product', 'Per Product'),
        ('per_delivery', 'Per Delivery'),
        ('per_unit', 'Per Unit/Serial'),
    ], string='Card Grouping Mode', readonly=True)
    unit_warranty_ids = fields.One2many(
        'warranty.unit', 'warranty_card_id', string='Unit Warranty Numbers')
    warranty_basis = fields.Selection([
        ('period', 'Period'),
        ('usage', 'Usage'),
    ], string='Warranty Basis', readonly=True)
    start_criterion = fields.Selection([
        ('installation', 'Installation/Commissioning'),
        ('delivery', 'Delivery'),
        ('invoice', 'Invoice'),
        ('custom', 'Custom Date Range'),
    ], string='Start Criterion', readonly=True)

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    policy_id = fields.Many2one('warranty.policy', string='Warranty Policy', readonly=True)
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', readonly=True)
    policy_source = fields.Selection([
        ('pricelist_rule', 'Product + Pricelist Rule'),
        ('product_policy', 'Product Warranty Policy'),
        ('model_policy', 'Model Warranty Policy'),
        ('brand_policy', 'Brand Warranty Policy'),
        ('customer_type_policy', 'Customer Type Warranty Policy'),
        ('product', 'Product Default Rule'),
        ('category', 'Product Category Rule'),
        ('company', 'Company Fallback Rule'),
    ], string='Policy Source', readonly=True)

    warranty_duration = fields.Integer(string='Warranty Duration', readonly=True)
    warranty_duration_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Duration Unit', readonly=True)
    free_service_frequency = fields.Integer(string='Free Service Frequency', readonly=True)
    free_service_frequency_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Free Service Frequency Unit', readonly=True)
    usage_limit = fields.Float(string='Usage Limit', readonly=True)
    usage_unit = fields.Selection([
        ('operating_hours', 'Operating Hours'),
        ('cycles', 'Cycles'),
        ('km', 'KM'),
        ('units_produced', 'Units Produced'),
        ('other', 'Other'),
    ], string='Usage Unit', readonly=True)
    payment_check_required = fields.Boolean(
        related='policy_id.payment_check_required', string='Payment Check Required')


    schedule_method = fields.Selection([
        ('equal_interval', 'Equal Interval'),
        ('fixed_offsets', 'Fixed Offsets'),
        ('manual', 'Manual Schedule'),
        ('calendar_month', 'Calendar Month'),
        ('amc_plan', 'AMC Plan'),
    ], string='Schedule Method', readonly=True, copy=False)
    free_service_period = fields.Integer(string='Free Service Period', readonly=True, copy=False)
    free_service_period_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Free Service Period Unit', readonly=True, copy=False)
    service_offset_ids = fields.One2many(
        'warranty.policy.service.offset', 'warranty_card_id', string='Service Offsets',
        readonly=True)
    service_entitlement_ids = fields.One2many(
        'warranty.service.entitlement', 'warranty_card_id', string='Service Entitlements')
    service_entitlement_count = fields.Integer(
        string='Service Entitlement Count', compute='_compute_service_entitlement_count')
    free_services_included = fields.Boolean(
        string='Free Services Included', compute='_compute_free_services_included')
    free_service_schedule_note = fields.Text(
        string='Free Service Schedule Notice', compute='_compute_free_service_schedule_note')


    service_monitoring_active = fields.Boolean(
        string='Service Monitoring Active', readonly=True, copy=False)
    grace_period_days = fields.Integer(string='Grace Period (Days)', readonly=True, copy=False)
    auto_expire_services = fields.Boolean(string='Auto-expire', readonly=True, copy=False)
    carry_forward_allowed = fields.Boolean(
        string='Carry-forward Allowed', readonly=True, copy=False)
    service_due_alert_days = fields.Integer(
        string='Service Due Alert Days', readonly=True, copy=False)
    expiry_reminder_days = fields.Integer(string='Expiry Reminder Days', readonly=True, copy=False)
    usage_alert_percentage = fields.Float(string='Usage Alert %', readonly=True, copy=False)
    service_alert_user_ids = fields.Many2many(
        'res.users', 'warranty_card_alert_user_rel', 'card_id', 'user_id',
        string='Service Alert Responsible Users', readonly=True, copy=False,
        context={'active_test': False})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                company = self.env['res.company'].browse(vals.get('company_id')) \
                    if vals.get('company_id') else self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(company) \
                    .next_by_code('warranty.card') or 'New'
        return super().create(vals_list)

    @api.depends('sale_order_line_ids.invoice_lines.move_id')
    def _compute_invoice_ids(self):
        for card in self:
            card.invoice_ids = card.sale_order_line_ids.invoice_lines.move_id.filtered(
                lambda move: move.move_type == 'out_invoice')

    @api.depends('free_services_allowed', 'service_entitlement_ids.state')
    def _compute_free_services(self):
        # Completion of services is delivered in a later part of the Development Mapping.
        for card in self:
            states = card.service_entitlement_ids.mapped('state')
            card.free_services_used = states.count('completed')
            card.free_services_missed = states.count('missed')
            card.free_services_expired = states.count('expired')
            card.free_services_cancelled = states.count('cancelled')
            card.free_services_balance = (
                card.free_services_allowed - card.free_services_used
                - card.free_services_expired - card.free_services_cancelled)

    @api.depends('service_entitlement_ids')
    def _compute_service_entitlement_count(self):
        for card in self:
            card.service_entitlement_count = len(card.service_entitlement_ids)

    @api.depends('free_services_allowed', 'company_id.warranty_scope_mode')
    def _compute_free_services_included(self):
        for card in self:
            card.free_services_included = card._free_services_included()

    @api.depends(
        'state', 'free_services_allowed', 'company_id.warranty_scope_mode', 'policy_id',
        'schedule_method', 'free_service_period', 'free_service_period_unit',
        'free_service_frequency', 'free_service_frequency_unit', 'warranty_basis',
        'usage_limit', 'usage_unit', 'warranty_start_date', 'warranty_end_date',
        'service_offset_ids.service_no', 'service_entitlement_ids.due_date',
        'service_entitlement_ids.due_date_conflict', 'service_monitoring_active',
        'service_due_alert_days', 'expiry_reminder_days', 'service_alert_user_ids',
        'company_id.warranty_service_alert_user_ids')
    def _compute_free_service_schedule_note(self):
        for card in self:
            card.free_service_schedule_note = \
                '\n'.join(card._get_free_service_schedule_notes()) or False

    @api.ondelete(at_uninstall=False)
    def _unlink_except_protected_entitlements(self):
        """Deleting a card must not bypass the service entitlement deletion restriction
        (entitlements are removed by the database cascade, without their own check)."""
        protected = self.service_entitlement_ids.filtered(
            lambda entitlement: entitlement.state in PROTECTED_ENTITLEMENT_STATES)
        if protected:
            raise UserError(_(
                "Warranty card(s) %s cannot be deleted: they have Completed, Missed, Expired or "
                "Cancelled service entitlements, which are kept for history.",
                ', '.join(protected.warranty_card_id.mapped('name'))))

    def _compute_replacement_count(self):
        self.replacement_count = 0

    def _compute_print_count(self):
        self.print_count = 0

    @api.depends(*REQUIREMENT_DEPENDS)
    def _compute_state(self):
        for card in self:
            if card.state in (False, 'draft', 'ready'):
                card.state = 'draft' if card._get_missing_requirements() else 'ready'

    @api.depends('state', *REQUIREMENT_DEPENDS)
    def _compute_missing_requirements(self):
        for card in self:
            missing = card._get_missing_requirements() \
                if card.state in (False, 'draft', 'ready') else []
            card.missing_requirements = '\n'.join(missing) or False

    def _get_unit_number_prefix(self):
        """WC/00012 -> WN/00012 (unit numbers are WN/xxxxx-xx under the card number)."""
        self.ensure_one()
        return 'WN/%s' % self.name.split('/', 1)[-1]

    def _create_unit_warranty_numbers(self, specs):
        """Create one Unit Warranty Number per (sale order line, unit number) in specs."""
        self.ensure_one()
        prefix = self._get_unit_number_prefix()
        start = len(self.unit_warranty_ids)
        return self.env['warranty.unit'].create([{
            'name': '%s-%02d' % (prefix, start + index),
            'warranty_card_id': self.id,
            'sale_order_line_id': line.id,
            'product_id': line.product_id.id,
            'unit_number': unit_number,
        } for index, (line, unit_number) in enumerate(specs, start=1)])

    def _split_units_to_new_card(self, units, deliveries):
        """Per Delivery grouping: move units that were not delivered to a new Draft card."""
        self.ensure_one()
        new_card = self.copy({
            'sale_order_line_ids': [Command.set(units.sale_order_line_id.ids)],
            'delivery_ids': [Command.set(deliveries.ids)],
            'installation_date': False,
            'warranty_start_date': False,
            'warranty_end_date': False,
        })
        prefix = new_card._get_unit_number_prefix()
        for index, unit in enumerate(units, start=1):
            unit.write({'warranty_card_id': new_card.id, 'name': '%s-%02d' % (prefix, index)})
        return new_card

    def _get_posted_invoices(self):
        self.ensure_one()
        return self.sale_order_line_ids.invoice_lines.move_id.filtered(
            lambda move: move.move_type == 'out_invoice' and move.state == 'posted')

    def _get_done_deliveries(self):
        self.ensure_one()
        return self.delivery_ids.filtered(lambda picking: picking.state == 'done')

    def _get_missing_requirements(self):
        """Warranty confirmation requirements of the Part 1 workflow:
        resolved rule, product/quantity, unit warranty lines, required serials,
        start criterion, required dates, invoice/payment if configured,
        grouping compatibility and warranty basis."""
        self.ensure_one()
        missing = []
        if not self.policy_source:
            missing.append(_("Resolved warranty rule"))
        if not self.warranty_basis:
            missing.append(_("Warranty basis"))
        elif self.warranty_basis == 'period' and (
                self.warranty_duration <= 0 or not self.warranty_duration_unit):
            missing.append(_("Warranty duration and duration unit"))

        units = self.unit_warranty_ids
        if not units:
            missing.append(_("Unit warranty lines"))
        for unit in units:
            if not unit.product_id or not unit.sale_order_line_id:
                missing.append(_("Product / quantity on unit %s", unit.name))
                continue
            if unit.product_id.type == 'consu' and not unit.stock_move_line_id:
                missing.append(_("Delivery for unit %s", unit.name))
            if unit.product_id.tracking == 'serial' and not unit.serial_ids:
                missing.append(_("Serial number for unit %s", unit.name))

        if not self.start_criterion:
            missing.append(_("Start criterion"))
        elif self.start_criterion == 'installation' and not self.installation_date:
            missing.append(_("Installation / commissioning date"))
        elif self.start_criterion == 'delivery' and not self._get_done_deliveries():
            missing.append(_("Validated delivery"))
        elif self.start_criterion == 'invoice' and not self._get_posted_invoices().filtered(
                'invoice_date'):
            missing.append(_("Posted invoice"))
        elif self.start_criterion == 'custom':
            if not self.warranty_start_date or not self.warranty_end_date:
                missing.append(_("Custom warranty start and end dates"))
            elif self.warranty_end_date < self.warranty_start_date:
                missing.append(_("Custom warranty end date must not be before the start date"))

        if self.policy_id.payment_check_required and not self._get_posted_invoices().filtered(
                lambda move: move.payment_state in ('paid', 'in_payment')):
            missing.append(_("Invoice payment"))

        orders = units.sale_order_line_id.order_id
        if any(order.partner_id != self.partner_id or order.company_id != self.company_id
               for order in orders):
            missing.append(_("Grouping compatibility (customer / company)"))
        return missing

    def _get_warranty_start_date(self):
        self.ensure_one()
        if self.start_criterion == 'installation':
            return self.installation_date
        if self.start_criterion == 'delivery':
            last_done = max(self._get_done_deliveries().mapped('date_done'))
            return fields.Datetime.context_timestamp(self, last_done).date()
        if self.start_criterion == 'invoice':
            return min(self._get_posted_invoices().filtered('invoice_date').mapped('invoice_date'))
        return self.warranty_start_date

    def _get_warranty_end_date(self, start_date):
        self.ensure_one()
        if self.start_criterion == 'custom':
            return self.warranty_end_date
        if self.warranty_basis != 'period':
            return False
        duration = relativedelta(**{self.warranty_duration_unit: self.warranty_duration})
        return start_date + duration - relativedelta(days=1)


    def _free_services_included(self):
        """Free Services Included? The resolved count and the company warranty scope."""
        self.ensure_one()
        return self.free_services_allowed > 0 and self.company_id.warranty_scope_mode in (
            'free_services', 'amc_free_services')

    @api.model
    def _get_free_service_levels(self, template, company, product_policy, policy):
        """Free service configuration levels after the Product + Pricelist line (approved
        priority, see doc/warranty_policy_resolution.md section 3f): for a product with a
        mapped Warranty Policy, the product-level policy resolved for the Sales Order
        (``product_policy``, e.g. the order pricelist's Customer Type policy), else the
        product; the category's Default Warranty Policy, else the category; the applicable
        (card) policy; the Company Default Warranty Policy. The Company Warranty Settings are
        the final fallback of the callers. Without a product (card of several products) the
        product and category levels are skipped."""
        levels = []
        if template:
            # A mapped product never uses its own (readonly) values.
            levels.append(product_policy
                          if template.with_company(company).warranty_policy_applicable
                          else template)
            category = template.categ_id
            levels.append(category.warranty_policy_id or category)
        levels += [policy, company.default_warranty_policy_id]
        return [level for level in levels if level]

    def _get_card_sale_line(self):
        """The Sales Order line of the card's product; empty for a card of several products."""
        self.ensure_one()
        if not self.product_id:
            return self.env['sale.order.line']
        return self.sale_order_line_ids.filtered(
            lambda line: line.product_id == self.product_id)[:1]

    def _get_card_pricelist_rule(self):
        """The Product + Pricelist mapping line the card's Sales Order line matched; empty for
        a card of several products."""
        self.ensure_one()
        line = self._get_card_sale_line()
        return (line._warranty_pricelist_rule() if line
                else self.env['warranty.product.pricelist.rule'])

    def _get_card_free_service_levels(self):
        self.ensure_one()
        # Product-level policy as resolved for the card's Sales Order line.
        line = self._get_card_sale_line()
        product_policy = (line._warranty_product_policy()[0] if line
                          else self.env['warranty.policy'])
        return self._get_free_service_levels(
            self.product_id.product_tmpl_id, self.company_id, product_policy, self.policy_id)

    def _auto_create_services_enabled(self):
        """Ticked on the matched Product + Pricelist mapping line enables it. Otherwise the
        first level that is a policy decides (an unticked policy is not overridden); a product
        / category without a policy enables it when ticked; the Company Warranty Settings are
        the final fallback."""
        self.ensure_one()
        if self._get_card_pricelist_rule().auto_create_services:
            return True
        for level in self._get_card_free_service_levels():
            if level._name == 'warranty.policy':
                return level.auto_create_services
            if level.auto_create_services:
                return True
        return self.company_id.warranty_auto_create_services

    def _resolve_service_alert_users(self):
        """Responsible users of the due alerts and expiry reminders: the valid users
        snapshotted on the card, else the valid current company fallback users (the snapshot
        is not overwritten). Returns (valid users, skipped invalid users of the levels
        consulted); valid users is empty when no valid user is configured."""
        self.ensure_one()
        skipped = self.env['res.users']
        for users in (self.service_alert_user_ids, self.company_id.warranty_service_alert_user_ids):
            valid = get_valid_service_alert_users(users, self.company_id)
            skipped |= users - valid
            if valid:
                return valid, skipped
        return self.env['res.users'], skipped

    def _get_service_alert_users(self):
        return self._resolve_service_alert_users()[0]

    def _snapshot_free_service_values(self):
        """Keep the policy values used at confirmation; later policy changes do not
        affect confirmed cards."""
        for card in self:
            policy = card.policy_id
            alert_users = get_valid_service_alert_users(
                policy.service_alert_user_ids, card.company_id) \
                or get_valid_service_alert_users(
                    card.company_id.warranty_service_alert_user_ids, card.company_id)
            # Schedule method and free service period: the first level with a value, else the
            # Company Warranty Settings.
            company = card.company_id
            levels = card._get_card_free_service_levels()
            # Product + Pricelist mapping line first (the line the Sales Order matched).
            rule = card._get_card_pricelist_rule()
            schedule_method = rule.default_schedule_method or next(filter(None, (
                level.schedule_method if level._name == 'warranty.policy'
                else level.default_schedule_method
                for level in levels)), company.default_schedule_method)
            period, period_unit = next((
                (level.free_service_period, level.free_service_period_unit)
                for level in levels if level._name == 'warranty.policy'
                and level.free_service_period > 0 and level.free_service_period_unit), (
                company.default_free_service_period, company.default_free_service_period_unit))
            card.write({
                'schedule_method': schedule_method,
                'free_service_period': period,
                'free_service_period_unit': period_unit,
                'service_monitoring_active': True,
                'grace_period_days': policy.grace_period_days,
                'auto_expire_services': policy.auto_expire_services,
                'carry_forward_allowed': policy.carry_forward_allowed,
                'service_due_alert_days': policy.service_due_alert_days,
                'expiry_reminder_days': policy.expiry_reminder_days,
                'usage_alert_percentage': policy.usage_alert_percentage,
                'service_alert_user_ids': [Command.set(alert_users.ids)],
            })
            # Snapshot lines are system records; users cannot create offset lines.
            self.env['warranty.policy.service.offset'].sudo().create([{
                'warranty_card_id': card.id,
                'service_no': offset.service_no,
                'offset': offset.offset,
                'offset_unit': offset.offset_unit,
            } for offset in policy.service_offset_ids])

    def _generate_free_service_entitlements(self):
        """Create Draft service entitlements 1..N when free services are included and
        Auto-create Services is enabled. Cards that already have entitlements are skipped."""
        for card in self:
            if (not card._free_services_included() or card.schedule_method == 'amc_plan'
                    or not card._auto_create_services_enabled()
                    or card.service_entitlement_ids):
                continue
            self.env['warranty.service.entitlement'].create([{
                'warranty_card_id': card.id,
                'service_no': number,
            } for number in range(1, card.free_services_allowed + 1)])

    def _has_complete_service_offsets(self):
        self.ensure_one()
        return sorted(self.service_offset_ids.mapped('service_no')) == \
            list(range(1, self.free_services_allowed + 1))

    def _get_free_service_due_values(self, service_no):
        """Due date and usage due of one free service. Dates are always calculated from
        the warranty start date; values that cannot be calculated are left empty."""
        self.ensure_one()
        count = self.free_services_allowed
        start = self.warranty_start_date
        due_date = False
        if start and count > 0 and self.schedule_method == 'equal_interval':
            if self.free_service_frequency > 0 and self.free_service_frequency_unit:
                due_date = start + relativedelta(**{
                    self.free_service_frequency_unit: self.free_service_frequency * service_no})
            elif self.free_service_period > 0 and self.free_service_period_unit:
                unit, period = self.free_service_period_unit, self.free_service_period
                if period % count == 0:
                    due_date = start + relativedelta(**{unit: period // count * service_no})
                else:
                    period_days = (start + relativedelta(**{unit: period}) - start).days
                    due_date = start + timedelta(days=period_days * service_no // count)
        elif start and self.schedule_method == 'fixed_offsets' \
                and self._has_complete_service_offsets():
            offset = self.service_offset_ids.filtered(lambda o: o.service_no == service_no)
            if offset:
                due_date = start + relativedelta(**{offset.offset_unit: offset.offset})

        usage_due = 0.0
        if self.warranty_basis == 'usage' and self.usage_limit > 0 and self.usage_unit \
                and count > 0:
            usage_due = self.usage_limit if service_no == count else float_round(
                self.usage_limit * service_no / count, precision_digits=2)
        return {'due_date': due_date, 'usage_due': usage_due}

    def _get_free_service_schedule_notes(self):
        self.ensure_one()
        if self.state != 'confirmed' or not self._free_services_included():
            return []
        notes = []
        method = self.schedule_method
        if not method:
            notes.append(_(
                "Schedule Method not resolved: the warranty card has no warranty policy with a "
                "Schedule Method. Enter the due dates manually."))
        elif method == 'amc_plan':
            notes.append(_(
                "AMC Plan: free service schedules are managed by the separate AMC module; no "
                "service entitlements are generated by the warranty module."))
        elif method == 'calendar_month':
            notes.append(_(
                "Calendar Month: the due date calculation is pending a business decision. "
                "Enter the due dates manually."))
        elif method == 'manual':
            notes.append(_("Manual Schedule: enter the due dates manually."))
        elif method == 'fixed_offsets' and not self._has_complete_service_offsets():
            notes.append(_(
                "Fixed Offsets incomplete: %(lines)s offset line(s) are configured for "
                "%(count)s free service(s); service numbers 1 to %(count)s are required. "
                "Due dates are not calculated.",
                lines=len(self.service_offset_ids), count=self.free_services_allowed))
        elif method == 'equal_interval':
            frequency = self.free_service_frequency > 0 and self.free_service_frequency_unit
            period = self.free_service_period > 0 and self.free_service_period_unit
            if not frequency and not period:
                notes.append(_(
                    "Equal Interval: no free service frequency or free service period is "
                    "configured. Due dates are not calculated."))
            elif frequency and period and self.warranty_start_date:
                start = self.warranty_start_date
                frequency_end = start + relativedelta(**{
                    self.free_service_frequency_unit:
                        self.free_service_frequency * self.free_services_allowed})
                period_end = start + relativedelta(**{
                    self.free_service_period_unit: self.free_service_period})
                if frequency_end != period_end:
                    notes.append(_(
                        "Free service frequency (every %(frequency)s %(frequency_unit)s x "
                        "%(count)s services, until %(frequency_end)s) differs from the policy "
                        "Free Service Period (%(period)s %(period_unit)s, until %(period_end)s). "
                        "The frequency is used for the due dates; the policy period is kept.",
                        frequency=self.free_service_frequency,
                        frequency_unit=self.free_service_frequency_unit,
                        count=self.free_services_allowed, frequency_end=frequency_end,
                        period=self.free_service_period,
                        period_unit=self.free_service_period_unit, period_end=period_end))
        if self.warranty_basis == 'usage' and (self.usage_limit <= 0 or not self.usage_unit):
            notes.append(_("Usage Due not calculated: the usage limit or usage unit is missing."))
        if method != 'amc_plan' and not self.service_entitlement_ids \
                and not self._auto_create_services_enabled():
            notes.append(_(
                "Auto-create Services is disabled: create the service entitlements manually."))
        if self.service_monitoring_active and (
                self.service_due_alert_days or self.expiry_reminder_days) \
                and not self._get_service_alert_users():
            notes.append(_(
                "No valid Service Alert Responsible User is configured (warranty card, policy or "
                "company): due alerts and expiry reminders are not created."))
        for entitlement in self.service_entitlement_ids.filtered('due_date_conflict'):
            notes.append(_(
                "Service %(number)s is due on %(due)s, after the warranty end date %(end)s: "
                "manual decision required.",
                number=entitlement.service_no, due=entitlement.due_date,
                end=self.warranty_end_date))
        return notes

    def action_view_service_entitlements(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management.action_warranty_service_entitlement')
        action['domain'] = [('warranty_card_id', '=', self.id)]
        action['context'] = {'default_warranty_card_id': self.id}
        return action

    def action_confirm_warranty(self):
        for card in self:
            if card.state != 'ready':
                raise UserError(_("Only warranty cards that are Ready to Confirm can be confirmed."))
            missing = card._get_missing_requirements()
            if missing:
                raise UserError(_(
                    "Warranty card %(card)s cannot be confirmed. Missing:\n%(missing)s",
                    card=card.name, missing='\n'.join(missing)))
            start_date = card._get_warranty_start_date()
            end_date = card._get_warranty_end_date(start_date)
            card.write({
                'warranty_start_date': start_date,
                'warranty_end_date': end_date,
                'state': 'confirmed',
            })
            card.unit_warranty_ids.write({
                'start_date': start_date,
                'end_date': end_date,
                'usage_limit': card.usage_limit,
                'usage_unit': card.usage_unit,
                'state': 'active',
            })
            if card._free_services_included():
                card._snapshot_free_service_values()
        self._generate_free_service_entitlements()
        self._generate_soft_copy()
        return True

    def _generate_soft_copy(self):
        report = self.env.ref('warranty_management.action_report_warranty_card')
        for card in self:
            pdf_content, __ = self.env['ir.actions.report']._render_qweb_pdf(report, card.ids)
            attachment = self.env['ir.attachment'].create({
                'name': '%s.pdf' % card.name.replace('/', '_'),
                'type': 'binary',
                'raw': pdf_content,
                'mimetype': 'application/pdf',
                'res_model': card._name,
                'res_id': card.id,
            })
            card.pdf_attachment_id = attachment
