import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import float_round

from .res_company import get_valid_service_alert_users

_logger = logging.getLogger(__name__)


# Internal marker of the system generation of the warranty card PDF (cannot be sent by a
# client: not JSON-serializable); see ir.actions.report / ir.binary.
SYSTEM_PDF_TOKEN = object()
PDF_PROTECTION_PARAM = 'warranty_management.card_pdfs_protected'

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
    # The PDF soft copy is a protected field attachment (approved D1 / D5): not listed with the
    # normal attachments and only delivered through Download PDF.
    pdf_file = fields.Binary(
        string='Warranty Card PDF', attachment=True, copy=False, groups='base.group_system')
    pdf_attachment_id = fields.Many2one(
        'ir.attachment', string='PDF Soft Copy', readonly=True, copy=False,
        groups='base.group_system')
    print_count = fields.Integer(
        string='Download Count', compute='_compute_print_count',
        help="Authorized downloads of the warranty card PDF (the PDF generated at confirmation "
             "is not counted).")
    download_log_ids = fields.One2many(
        'warranty.card.download.log', 'warranty_card_id', string='Download History',
        readonly=True)
    download_request_ids = fields.One2many(
        'warranty.card.download.request', 'warranty_card_id',
        string='Download Approval Requests', readonly=True)
    download_history_ids = fields.One2many(
        'warranty.card.download.history', 'warranty_card_id', string='Download History',
        readonly=True)

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
        ('pricelist_policy', 'Pricelist Warranty Policy'),
        ('product_policy', 'Product Warranty Policy'),
        ('category_policy', 'Product Category Policy'),
        ('company_policy', 'Company Default Policy'),
        ('product', 'Product Default Rule'),
        ('category', 'Product Category Rule'),
        ('company', 'Company Fallback Rule'),
        # Legacy sources, kept for the existing warranty cards.
        ('pricelist_rule', 'Product + Pricelist Rule'),
        ('model_policy', 'Model Warranty Policy'),
        ('brand_policy', 'Brand Warranty Policy'),
        ('customer_type_policy', 'Customer Type Warranty Policy'),
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

    @api.depends('download_log_ids')
    def _compute_print_count(self):
        # sudo: the count includes every download of the card, whoever downloaded it.
        counts = dict(self.env['warranty.card.download.log'].sudo()._read_group(
            [('warranty_card_id', 'in', self.ids)], ['warranty_card_id'], ['__count']))
        for card in self:
            card.print_count = counts.get(card.sudo(), 0) if card.id else 0

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
    def _get_own_value_levels(self, template):
        """Own-value levels used when no Warranty Policy applies (P5): the product, then its
        category. Without a product (card of several products) there is none."""
        return [level for level in (template, template.categ_id) if level] if template else []

    def _get_card_sale_line(self):
        """The Sales Order line of the card's product; empty for a card of several products."""
        self.ensure_one()
        if not self.product_id:
            return self.env['sale.order.line']
        return self.sale_order_line_ids.filtered(
            lambda line: line.product_id == self.product_id)[:1]

    def _auto_create_services_enabled(self):
        """The card's Warranty Policy decides alone (strict priority). Without a policy (P5):
        ticked on the product or its category enables it; the Company Warranty Settings are
        the final fallback."""
        self.ensure_one()
        if self.policy_id:
            return self.policy_id.auto_create_services
        if any(level.auto_create_services
                for level in self._get_own_value_levels(self.product_id.product_tmpl_id)):
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
            # Schedule method and free service period: the card's Warranty Policy, its empty
            # values filled by the Company Warranty Settings. Without a policy (P5): the product
            # or category schedule method, and the Company Warranty Settings.
            company = card.company_id
            if policy:
                schedule_method = policy.schedule_method or company.default_schedule_method
            else:
                schedule_method = next(filter(None, (
                    level.default_schedule_method for level in card._get_own_value_levels(
                        card.product_id.product_tmpl_id))), company.default_schedule_method)
            if policy.free_service_period > 0 and policy.free_service_period_unit:
                period, period_unit = policy.free_service_period, policy.free_service_period_unit
            else:
                period = company.default_free_service_period
                period_unit = company.default_free_service_period_unit
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
        """Generate the warranty card PDF (unchanged report) and store it in the protected
        field attachment; this is not a download (approved: Download Count unchanged)."""
        report = self.env.ref('warranty_management.action_report_warranty_card')
        for card in self:
            pdf_content, __ = self.env['ir.actions.report'].with_context(
                warranty_card_pdf_token=SYSTEM_PDF_TOKEN)._render_qweb_pdf(report, card.ids)
            # sudo: system generation of the protected PDF (field restricted to administrators).
            attachment = self.env['ir.attachment'].sudo().create({
                'name': '%s.pdf' % card.name.replace('/', '_'),
                'type': 'binary',
                'raw': pdf_content,
                'mimetype': 'application/pdf',
                'res_model': card._name,
                'res_id': card.id,
                'res_field': 'pdf_file',
            })
            card.sudo().pdf_attachment_id = attachment

    def _get_pdf_attachment(self):
        """The protected PDF attachment of the card (sudo record); generated when missing."""
        self.ensure_one()
        Attachment = self.env['ir.attachment'].sudo()
        attachment = Attachment.search([
            ('res_model', '=', self._name), ('res_id', '=', self.id),
            ('res_field', '=', 'pdf_file')], limit=1)
        if not attachment:
            self._generate_soft_copy()
            attachment = Attachment.search([
                ('res_model', '=', self._name), ('res_id', '=', self.id),
                ('res_field', '=', 'pdf_file')], limit=1)
        return attachment

    def action_download_pdf(self):
        """Download PDF (approved D1-D5): the free downloads, then one approved request per
        download; the file is delivered by a single-use ticket of the current user."""
        self.ensure_one()
        self.check_access('read')
        if self.state != 'confirmed':
            raise UserError(_("The PDF can only be downloaded for a confirmed warranty card."))
        self._get_pdf_attachment()
        request = self.env['warranty.card.download.request']
        if self._download_approval_needed():
            request = request.sudo().search([
                ('warranty_card_id', '=', self.id), ('requested_by_id', '=', self.env.uid),
                ('state', '=', 'approved')], order='id', limit=1)
            if not request:
                pending = self.env['warranty.card.download.request'].sudo().search([
                    ('warranty_card_id', '=', self.id), ('requested_by_id', '=', self.env.uid),
                    ('state', '=', 'to_approve')], limit=1)
                if pending:
                    raise UserError(_(
                        "Your download approval request %s is waiting for approval.",
                        pending.name))
                return {
                    'type': 'ir.actions.act_window',
                    'name': _("Request Download Approval"),
                    'res_model': 'warranty.card.download.request.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_warranty_card_id': self.id},
                }
        ticket = self.env['warranty.card.download.ticket']._issue(self, request)
        return {
            'type': 'ir.actions.act_url',
            'url': '/warranty/card/pdf/%s' % ticket.token,
            'target': 'self',
        }

    def _download_approval_needed(self):
        self.ensure_one()
        company = self.company_id
        return company.warranty_download_approval_required \
            and self.print_count >= company.warranty_free_download_count

    @api.model
    def _migrate_protect_card_pdfs(self):
        """One-time (approved D1): move the existing warranty card PDF soft copies (the
        attachment of PDF Soft Copy) into the protected field attachment. Same attachment
        records and content; other attachments are not changed; no download is recorded."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param(PDF_PROTECTION_PARAM):
            return
        # sudo: system migration over every company.
        for card in self.sudo().search([('pdf_attachment_id', '!=', False)]):
            attachment = card.pdf_attachment_id
            if attachment.res_field == 'pdf_file':
                continue
            if attachment.res_model != card._name or attachment.res_id != card.id:
                _logger.warning("Warranty card PDF protection: attachment %s of %s belongs to "
                                "another record; not changed.", attachment.id, card.name)
                continue
            if self.env['ir.attachment'].sudo().search_count([
                    ('res_model', '=', card._name), ('res_id', '=', card.id),
                    ('res_field', '=', 'pdf_file')]):
                _logger.warning("Warranty card PDF protection: %s already has a protected PDF; "
                                "attachment %s not changed.", card.name, attachment.id)
                continue
            attachment.write({'res_field': 'pdf_file'})
            _logger.info("Warranty card PDF protection: %s (attachment %s) protected.",
                         card.name, attachment.id)
        ICP.set_param(PDF_PROTECTION_PARAM, fields.Datetime.now())
