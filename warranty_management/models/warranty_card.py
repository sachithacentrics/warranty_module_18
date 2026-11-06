import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

import pytz
from markupsafe import Markup

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import float_round, format_date, format_datetime

from .res_company import get_valid_service_alert_users
from .warranty_policy import EARLY_SERVICE_RULES, LATE_SERVICE_HANDLING

_logger = logging.getLogger(__name__)


# Internal marker of the system generation of the warranty card PDF (cannot be sent by a
# client: not JSON-serializable); see ir.actions.report / ir.binary.
SYSTEM_PDF_TOKEN = object()
PDF_PROTECTION_PARAM = 'warranty_management.card_pdfs_protected'

# Service entitlements in these states are kept for history and cannot be deleted.
PROTECTED_ENTITLEMENT_STATES = ('completed', 'missed', 'expired', 'cancelled')

CARD_STATES = [
    ('draft', 'Draft'),
    ('pending_installation', 'Pending Installation'),
    ('ready', 'Ready to Confirm'),
    ('confirmed', 'Confirmed'),
    ('suspended', 'Suspended'),
    ('expired', 'Expired'),
    ('cancelled', 'Cancelled'),
]

# Cards not confirmed yet: their state and missing requirements are recomputed.
OPEN_CARD_STATES = ('draft', 'pending_installation', 'ready')

# Start Date Automation (approved design doc/start_date_design.md).
START_DATE_SOURCES = [
    ('delivery', 'Delivery'),
    ('invoice', 'Invoice Posting'),
    ('installation', 'Installation Task'),
    ('custom', 'Custom Date Range'),
    ('exception', 'Authorized Exception'),
]
SOURCE_VERIFICATIONS = [
    ('event', 'Recorded at the event'),
    ('history', 'Verified from the posting history'),
    ('exception', 'Authorized exception'),
]
# Approved D9: warranty dates and their sources are written by system code only (confirmation,
# events, the exception / correction wizard). The marker is a Python object: no client (UI,
# import, JSON-RPC) can put it in a context, and a sudo() write alone does not pass.
_DATE_WRITE_MARKER = object()
CARD_DATE_FIELDS = {'warranty_start_date', 'warranty_end_date'}
CARD_SYSTEM_DATE_FIELDS = {
    'installation_date', 'start_exception_date', 'start_date_source', 'source_picking_id',
    'source_invoice_id', 'source_datetime', 'source_verification'}
DATE_CORRECTION_GROUP = 'warranty_management.group_warranty_date_correction'
# Part 9, SRS 13: after confirmation these change only through a controlled action or system code.
CARD_PROTECTED_FIELDS = {
    'partner_id', 'product_id', 'indoor_serial_id', 'outdoor_serial_id', 'policy_id',
    'policy_source', 'pricelist_id', 'company_id', 'sale_order_id', 'warranty_basis',
    'warranty_duration', 'warranty_duration_unit', 'usage_limit', 'usage_unit',
    'free_services_allowed', 'warranty_original_end_date'}

# Fields read by _get_missing_requirements(); the Draft / Pending Installation / Ready to
# Confirm state and the missing-requirements text are recomputed when they change.
REQUIREMENT_DEPENDS = [
    'policy_source', 'warranty_basis', 'start_criterion',
    'warranty_duration', 'warranty_duration_unit',
    'installation_date', 'warranty_start_date', 'warranty_end_date',
    'start_exception_date', 'start_date_source',
    'partner_id', 'company_id', 'policy_id.payment_check_required',
    'unit_warranty_ids', 'unit_warranty_ids.product_id',
    'unit_warranty_ids.sale_order_line_id', 'unit_warranty_ids.stock_move_line_id',
    'unit_warranty_ids.serial_ids', 'unit_warranty_ids.unit_number',
    'unit_warranty_ids.stock_move_line_id.picking_id.date_done',
    'delivery_ids', 'delivery_ids.state', 'delivery_ids.date_done',
    'sale_order_line_ids.invoice_lines.quantity',
    'sale_order_line_ids.invoice_lines.move_id.state',
    'sale_order_line_ids.invoice_lines.move_id.warranty_posted_at',
    'sale_order_line_ids.invoice_lines.move_id.reversed_entry_id',
    'sale_order_line_ids.invoice_lines.move_id.invoice_date',
    'sale_order_line_ids.invoice_lines.move_id.payment_state',
]


class WarrantyCard(models.Model):
    _name = 'warranty.card'
    _description = 'Warranty Card'
    # Chatter (approved): successful PDF downloads are logged as internal notes; Start Date
    # Automation (D11): activation, source changes, invoice reversals, exceptions and
    # corrections. Activities: credit notes after confirmation, failed automatic activation.
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
    installation_date = fields.Date(
        string='Installation Date', readonly=True, copy=False,
        help="Filled by the system: completion of the installation Field Service task(s) "
             "(Warranty Timezone) or an authorized exception.")
    warranty_start_date = fields.Date(string='Warranty Start Date')
    warranty_end_date = fields.Date(string='Warranty End Date')
    # Start Date Automation: expected values (not stored) before confirmation, frozen source
    # after confirmation (empty on cards confirmed before the automation).
    expected_start_date = fields.Date(
        string='Expected Start Date', compute='_compute_expected_dates',
        help="Start date calculated from the current delivery, invoice posting or installation "
             "completion; it becomes the Warranty Start Date at confirmation.")
    expected_end_date = fields.Date(
        string='Expected End Date', compute='_compute_expected_dates')
    start_source_note = fields.Text(
        string='Start Date Source Details', compute='_compute_expected_dates')
    start_exception_date = fields.Date(
        string='Exception Start Date', readonly=True, copy=False,
        help="Start date set by an authorized exception (Warranty: Date Correction).")
    start_date_source = fields.Selection(
        START_DATE_SOURCES, string='Start Date Source', readonly=True, copy=False)
    source_picking_id = fields.Many2one(
        'stock.picking', string='Source Delivery', readonly=True, copy=False)
    source_invoice_id = fields.Many2one(
        'account.move', string='Source Invoice', readonly=True, copy=False)
    source_datetime = fields.Datetime(
        string='Source Date / Time', readonly=True, copy=False,
        help="Actual time of the event that set the warranty start date.")
    source_verification = fields.Selection(
        SOURCE_VERIFICATIONS, string='Source Verification', readonly=True, copy=False)
    date_log_ids = fields.One2many(
        'warranty.card.date.log', 'card_id', string='Warranty Date History', readonly=True)
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
    ], string='Usage Unit', readonly=True ,)
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
    # Flexible service dates (BA-approved enhancement K1 / K2): policy snapshot; an empty rule
    # (cards confirmed before the enhancement) keeps the standard date rules.
    early_service_rule = fields.Selection(EARLY_SERVICE_RULES, string='Early Service Rule',
                                          readonly=True, copy=False)
    early_service_days = fields.Integer(string='Early Service Days', readonly=True, copy=False)
    late_service_handling = fields.Selection(LATE_SERVICE_HANDLING,
                                             string='Late Service Handling', readonly=True,
                                             copy=False)
    service_sequence_required = fields.Boolean(string='Enforce Service Sequence', readonly=True,
                                               copy=False)
    usage_alert_percentage = fields.Float(string='Usage Alert %', readonly=True, copy=False)
    service_alert_user_ids = fields.Many2many(
        'res.users', 'warranty_card_alert_user_rel', 'card_id', 'user_id',
        string='Service Alert Responsible Users', readonly=True, copy=False,
        context={'active_test': False})

    @api.model_create_multi
    def create(self, vals_list):
        if not self._warranty_date_write_allowed():
            for vals in vals_list:
                if any(vals.get(name) for name in self._warranty_system_date_fields()) or (
                        vals.get('start_criterion') != 'custom'
                        and any(vals.get(name) for name in CARD_DATE_FIELDS)):
                    raise UserError(self._warranty_date_write_error())
        if not self.env.su and not self._warranty_date_write_allowed() and any(
                vals.get('state') not in (None, *OPEN_CARD_STATES) for vals in vals_list):
            raise UserError(self._warranty_protected_write_error())
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                company = self.env['res.company'].browse(vals.get('company_id')) \
                    if vals.get('company_id') else self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(company) \
                    .next_by_code('warranty.card') or 'New'
        # The chatter only logs downloads: no creation note, no automatic followers.
        return super(WarrantyCard, self.with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)).create(vals_list)

    def write(self, vals):
        if not self._warranty_date_write_allowed():
            self._warranty_check_date_write(vals)
            if not self.env.su:
                self._warranty_check_protected_write(vals)
        return super().write(vals)

    @api.model
    def _warranty_protected_write_error(self):
        return _("This value of a confirmed warranty is protected: use Request Warranty Change on the "
                 "warranty card.")

    def _warranty_check_protected_write(self, vals):
        for card in self:
            changed = {name for name in vals if name in CARD_PROTECTED_FIELDS | {'state'}
                       and card._warranty_value_changed(name, vals[name])}
            if 'state' in changed or (changed and card.state not in OPEN_CARD_STATES):
                raise UserError(self._warranty_protected_write_error())

    def _warranty_value_changed(self, name, value):
        current = self[name]
        return (current.id if isinstance(current, models.BaseModel) else current) != (value or False)

    # ------------------------------------------------------------------ date protection (D9)
    def _warranty_date_write_allowed(self):
        return self.env.context.get('warranty_date_marker') is _DATE_WRITE_MARKER

    def _warranty_system_write(self, vals):
        """Write warranty dates / sources from system code (confirmation, events, wizard)."""
        return self.with_context(warranty_date_marker=_DATE_WRITE_MARKER).write(vals)

    @api.model
    def _warranty_marker(self):
        return _DATE_WRITE_MARKER

    def _warranty_system_date_fields(self):
        """Fields only system code writes (extended by warranty_management_fsm)."""
        return set(CARD_SYSTEM_DATE_FIELDS)

    @api.model
    def _warranty_date_write_error(self):
        return _("Warranty dates and their sources are set by the system (delivery validation, "
                 "invoice posting, installation task completion) or through an authorized "
                 "exception / Correct Warranty Dates; they cannot be changed directly.")

    def _warranty_check_date_write(self, vals):
        names = set(vals)
        if names & self._warranty_system_date_fields():
            raise UserError(self._warranty_date_write_error())
        if names & CARD_DATE_FIELDS and self.filtered(
                lambda card: card.state not in OPEN_CARD_STATES
                or card.start_criterion != 'custom'):
            raise UserError(self._warranty_date_write_error())
        if 'start_criterion' in names and self.filtered(
                lambda card: card.state not in OPEN_CARD_STATES):
            raise UserError(_("The start criterion of a confirmed warranty card cannot be "
                              "changed."))

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

    @api.depends('free_services_allowed')
    def _compute_free_services_included(self):
        for card in self:
            card.free_services_included = card._free_services_included()

    @api.depends(
        'state', 'free_services_allowed', 'policy_id',
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
            if card.state in (False, *OPEN_CARD_STATES):
                missing = card._get_missing_requirements()
                if not missing:
                    card.state = 'ready'
                elif card.start_criterion == 'installation' \
                        and set(missing) <= set(card._warranty_installation_missing()):
                    # Every other requirement is met: waiting for the installation only.
                    card.state = 'pending_installation'
                else:
                    card.state = 'draft'

    @api.depends('state', *REQUIREMENT_DEPENDS)
    def _compute_missing_requirements(self):
        for card in self:
            missing = card._get_missing_requirements() \
                if card.state in (False, *OPEN_CARD_STATES) else []
            card.missing_requirements = '\n'.join(missing) or False

    @api.depends('state', 'source_picking_id', 'source_invoice_id', 'source_datetime',
                 'source_verification', 'company_id.warranty_timezone', *REQUIREMENT_DEPENDS)
    def _compute_expected_dates(self):
        for card in self:
            if card.state in (False, *OPEN_CARD_STATES):
                source = card._warranty_start_source() if card.start_criterion else {}
                start = source.get('date')
                card.expected_start_date = start
                card.expected_end_date = start and card._get_warranty_end_date(start)
                card.start_source_note = card._warranty_source_description(source) if start \
                    else '\n'.join(source.get('problems', [])) or False
            else:
                card.expected_start_date = card.warranty_start_date
                card.expected_end_date = card.warranty_end_date
                card.start_source_note = card._warranty_source_description(
                    card._warranty_frozen_source()) if card.start_date_source else _(
                    "Not recorded (confirmed before the start date automation).")

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
        else:
            missing += self._warranty_start_source()['problems']

        if self.policy_id.payment_check_required and not self._get_posted_invoices().filtered(
                lambda move: move.payment_state in ('paid', 'in_payment')):
            missing.append(_("Invoice payment"))

        orders = units.sale_order_line_id.order_id
        if any(order.partner_id != self.partner_id or order.company_id != self.company_id
               for order in orders):
            missing.append(_("Grouping compatibility (customer / company)"))
        return missing

    # ------------------------------------------------------------------ start date sources
    def _warranty_installation_missing(self):
        """Installation requirement (Installation basis): the installation date filled by the
        completed installation task(s) (warranty_management_fsm) or an authorized exception."""
        self.ensure_one()
        if self.installation_date and self.start_date_source in ('installation', 'exception'):
            return []
        return [_("Installation / commissioning completed (installation Field Service task or "
                  "authorized exception)")]

    def _warranty_start_source(self):
        """Start date of the card from its current source events (approved design §7):
        dict with date, datetime (UTC), source, verification, picking, invoice, unit_invoices
        {unit: (invoice, posted_at, verification)} and problems (missing requirements of the
        start criterion; the date is empty while a problem exists)."""
        self.ensure_one()
        result = {'date': False, 'datetime': False, 'source': False, 'verification': False,
                  'picking': self.env['stock.picking'], 'invoice': self.env['account.move'],
                  'unit_invoices': {}, 'problems': []}
        criterion = self.start_criterion
        if criterion == 'custom':
            if not self.warranty_start_date or not self.warranty_end_date:
                result['problems'].append(_("Custom warranty start and end dates"))
            elif self.warranty_end_date < self.warranty_start_date:
                result['problems'].append(
                    _("Custom warranty end date must not be before the start date"))
            else:
                result.update(date=self.warranty_start_date, source='custom')
            return result
        if criterion == 'installation':
            result['problems'] = self._warranty_installation_missing()
            if not result['problems']:
                exception = self.start_date_source == 'exception'
                result.update(date=self.installation_date, datetime=self.source_datetime,
                              source=self.start_date_source,
                              verification='exception' if exception else 'event')
            return result
        if self.start_date_source == 'exception' and self.start_exception_date:
            # D1a / Q14: authorized exception; every other requirement still applies.
            result.update(date=self.start_exception_date, source='exception',
                          verification='exception')
            return result
        if criterion == 'delivery':
            self._warranty_delivery_source(result)
        elif criterion == 'invoice':
            self._warranty_invoice_source(result)
        return result

    def _warranty_delivery_source(self, result):
        """D2: each goods unit dates from its own validated delivery (unit allocation, never an
        unrelated delivery); the card starts at the latest one once every unit is delivered.
        Units waiting for their delivery are reported by the unit requirement."""
        goods = self.unit_warranty_ids.filtered(lambda unit: unit.product_id.type == 'consu')
        if not goods:
            result['problems'].append(_(
                "Validated delivery: the card has no physical delivery; an authorized "
                "exception is required"))
            return
        if not all(goods.mapped('delivery_datetime')):
            return
        latest = max(goods, key=lambda unit: (unit.delivery_datetime, unit.id))
        result.update(date=self.company_id._warranty_local_date(latest.delivery_datetime),
                      datetime=latest.delivery_datetime, source='delivery',
                      verification='event', picking=latest.delivery_picking_id)

    def _warranty_invoice_source(self, result):
        """D1 / D3: each unit is covered by a posted, non-reversed customer invoice of its Sales
        Order line (§7.2); the card starts at the latest covering posting time."""
        allocation = self._warranty_invoice_allocation()
        for unit in self.unit_warranty_ids.filtered('sale_order_line_id'):
            entry = allocation.get(unit)
            if not entry:
                result['problems'].append(_("Posted invoice for unit %s", unit.name))
            elif not entry[1]:
                result['problems'].append(_(
                    "Verified invoice posting time for unit %(unit)s (%(invoice)s): the posting "
                    "time cannot be established; an authorized exception is required",
                    unit=unit.name, invoice=entry[0].name))
        if result['problems'] or not allocation:
            return
        invoice, posted_at, verification = max(
            allocation.values(), key=lambda entry: (entry[1], entry[0].id))
        verifications = {entry[2] for entry in allocation.values()}
        result.update(date=self.company_id._warranty_local_date(posted_at), datetime=posted_at,
                      source='invoice', invoice=invoice, unit_invoices=allocation,
                      verification='history' if 'history' in verifications else 'event')

    def _warranty_invoice_allocation(self):
        """{unit: (invoice, posted_at, verification)} of the units covered by an invoice: per
        Sales Order line the net invoiced quantities in posting order cover the units in unit
        order; a unit is covered only by a whole cumulative quantity (Q3)."""
        self.ensure_one()
        allocation = {}
        for line, units in self.unit_warranty_ids.filtered('sale_order_line_id').grouped(
                'sale_order_line_id').items():
            cumulative = 0.0
            for invoice, quantity, posted_at, verification in line._warranty_invoice_coverage():
                cumulative = float_round(cumulative + quantity, precision_digits=6)
                covered = int(float_round(cumulative, precision_digits=0, rounding_method='DOWN'))
                for unit in units.filtered(lambda u: u not in allocation
                                           and u.unit_number <= covered):
                    allocation[unit] = (invoice, posted_at, verification)
        return allocation

    def _warranty_frozen_source(self):
        """Source values frozen at confirmation (same keys as _warranty_start_source)."""
        self.ensure_one()
        return {'date': self.warranty_start_date, 'datetime': self.source_datetime,
                'source': self.start_date_source, 'verification': self.source_verification,
                'picking': self.source_picking_id, 'invoice': self.source_invoice_id,
                'unit_invoices': {}, 'problems': []}

    def _warranty_format_datetime(self, value):
        """UTC datetime in the card company's warranty timezone, e.g. 26/10/2026 19:52
        (Asia/Colombo)."""
        self.ensure_one()
        tz_name = self.company_id._warranty_tz_name()
        return '%s (%s)' % (format_datetime(self.env, value, tz=tz_name, dt_format='short'),
                            tz_name)

    def _warranty_source_description(self, source):
        """Readable source of a start date (card view, chatter notes)."""
        self.ensure_one()
        when = source.get('datetime') and self._warranty_format_datetime(source['datetime'])
        kind = source.get('source')
        if kind == 'delivery':
            return _("Delivery %(picking)s validated on %(when)s",
                     picking=source['picking'].name or '', when=when)
        if kind == 'invoice':
            note = _("Invoice %(invoice)s posted on %(when)s",
                     invoice=source['invoice'].name or '', when=when)
            if source.get('verification') == 'history':
                note += _(" (verified from the invoice posting history)")
            return note
        if kind == 'installation':
            return _("Installation completed on %s", when) if when else _("Installation task")
        if kind == 'exception':
            return _("Authorized exception (Warranty: Date Correction): start date %s",
                     format_date(self.env, source.get('date')))
        if kind == 'custom':
            return _("Custom date range")
        return False

    def _get_warranty_start_date(self):
        self.ensure_one()
        return self._warranty_start_source()['date']

    def _get_warranty_end_date(self, start_date):
        self.ensure_one()
        if self.start_criterion == 'custom':
            return self.warranty_end_date
        if self.warranty_basis != 'period':
            return False
        duration = relativedelta(**{self.warranty_duration_unit: self.warranty_duration})
        return start_date + duration - relativedelta(days=1)


    def _free_services_included(self):
        """Free Services Included? The resolved free service count (BA decision 2026-10-28:
        the company Warranty Scope Mode no longer limits free services)."""
        self.ensure_one()
        return self.free_services_allowed > 0

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
                'early_service_rule': policy.early_service_rule,
                'early_service_days': policy.early_service_days,
                'late_service_handling': policy.early_service_rule
                and policy.late_service_handling or False,
                'service_sequence_required': policy.service_sequence_required,
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
            card.unit_warranty_ids._warranty_check_serial_duplicates()
            source = card._warranty_start_source()
            start_date = source['date']
            end_date = card._get_warranty_end_date(start_date)
            card._warranty_system_write(dict(card._warranty_source_write_values(source), **{
                'warranty_start_date': start_date,
                'warranty_end_date': end_date,
                'state': 'confirmed',
            }))
            unit_vals = {
                'start_date': start_date,
                'end_date': end_date,
                'usage_limit': card.usage_limit,
                'usage_unit': card.usage_unit,
                'state': 'active',
            }
            for unit in card.unit_warranty_ids:
                invoice, posted_at, __ = source['unit_invoices'].get(unit, (False, False, False))
                unit._warranty_system_write(dict(
                    unit_vals, source_invoice_id=invoice and invoice.id,
                    source_invoice_posted_at=posted_at))
            card._warranty_log_date_event('activation', _(
                "Warranty activated: %(start)s - %(end)s. Start date source: %(origin)s.",
                start=format_date(card.env, start_date),
                end=format_date(card.env, end_date) if end_date else _("no end date (usage)"),
                origin=card._warranty_source_description(source)),
                new_start=start_date, new_end=end_date)
            if card._free_services_included():
                card._snapshot_free_service_values()
        self._generate_free_service_entitlements()
        self._generate_soft_copy()
        return True

    def _warranty_source_write_values(self, source):
        """Card values freezing a start date source (extended by warranty_management_fsm)."""
        return {
            'start_date_source': source['source'],
            'source_picking_id': source['picking'].id,
            'source_invoice_id': source['invoice'].id,
            'source_datetime': source['datetime'],
            'source_verification': source['verification'],
        }

    def _warranty_auto_confirm(self):
        """D6: Installation cards whose installation comes from completed installation tasks
        are confirmed automatically once Ready (never twice: only Ready cards). A confirmation
        refused with a UserError leaves the card Ready, with a note and an activity; the event
        that triggered it (task completion, delivery, invoice) is not blocked."""
        cards = self.filtered(lambda card: card.start_criterion == 'installation'
                              and card.start_date_source == 'installation')
        for card in cards:
            if card.state != 'ready':
                continue
            try:
                with self.env.cr.savepoint():
                    # sudo: the technician / accountant may have no warranty card rights; the
                    # activation is a system step of the approved automation.
                    card.sudo().action_confirm_warranty()
            except UserError as error:
                self.env.invalidate_all(flush=False)
                message = _("Automatic warranty activation failed: %s", error.args[0])
                card._warranty_log_date_event('activation_failed', message, reason=error.args[0])
                card._warranty_schedule_review_activity(message)

    def _warranty_schedule_review_activity(self, note):
        """To-Do for the card's service alert responsible users (company fallback)."""
        self.ensure_one()
        users = self._get_service_alert_users()
        if not users:
            _logger.warning("Warranty card %s: no valid Service Alert Responsible User for the "
                            "review activity (%s).", self.name, note)
            return
        for user in users:
            # sudo: the user triggering the event may not have write access to the card.
            self.sudo().activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                summary=_("Warranty date review: %s", self.name), note=note)

    def _warranty_log_date_event(self, event, body, **values):
        """D11: append-only Warranty Date History record + internal chatter note (no email,
        no followers). `values`: old_ / new_ dates, reason, attachment_ids, picking_id,
        invoice_id, task_reference."""
        self.ensure_one()
        attachments = values.pop('attachment_ids', self.env['ir.attachment'])
        log_vals = {
            'card_id': self.id,
            'event': event,
            'user_id': self.env.uid,
            'start_date_source': self.start_date_source,
            'source_datetime': self.source_datetime,
            'picking_id': self.source_picking_id.id,
            'invoice_id': self.source_invoice_id.id,
        }
        log_vals.update(values)
        # sudo: the history is written by system code only (no user create / write access).
        log = self.env['warranty.card.date.log'].sudo().create(log_vals)
        if attachments:
            attachments.sudo().write({'res_model': log._name, 'res_id': log.id})
            log.attachment_ids = attachments
        if values.get('reason') and event in ('exception', 'correction'):
            body = Markup('%s<br/>%s') % (body, _("Reason: %s", values['reason']))
        # sudo: the user of the event may not have write access to the card.
        self.sudo()._message_log(body=body, author_id=self.env.user.partner_id.id)
        return log

    # ------------------------------------------------------------------ exception / correction
    def _warranty_check_date_correction_group(self):
        if not self.env.su and not self.env.user.has_group(DATE_CORRECTION_GROUP):
            raise UserError(_("Only users of the group Warranty: Date Correction can record "
                              "warranty date exceptions and corrections."))

    def _warranty_apply_exception(self, start_date, reason, attachments=None):
        """D1a / D8 / Q14: authorized exception before confirmation, when the source event is
        missing or cannot be verified; every other requirement still applies and the card is
        confirmed manually."""
        self.ensure_one()
        self._warranty_check_date_correction_group()
        if self.state not in OPEN_CARD_STATES:
            raise UserError(_("An exception can only be recorded before the warranty is "
                              "confirmed; use Correct Warranty Dates on %s.", self.name))
        if self.start_criterion not in ('delivery', 'invoice', 'installation'):
            raise UserError(_("Exceptions apply to the Delivery, Invoice and Installation start "
                              "criteria only."))
        if not start_date or not (reason or '').strip():
            raise UserError(_("The exception needs a start date and a reason."))
        vals = {'start_exception_date': start_date, 'start_date_source': 'exception',
                'source_verification': 'exception', 'source_datetime': False}
        if self.start_criterion == 'installation':
            vals['installation_date'] = start_date
        old_installation = self.installation_date
        self._warranty_system_write(vals)
        return self._warranty_log_date_event('exception', _(
            "Authorized start date exception: %(date)s (%(criterion)s basis).",
            date=format_date(self.env, start_date),
            criterion=dict(self._fields['start_criterion']._description_selection(self.env))[
                self.start_criterion]),
            new_start=start_date, old_installation=old_installation,
            new_installation=vals.get('installation_date', old_installation),
            reason=reason, attachment_ids=attachments or self.env['ir.attachment'])

    def _warranty_correction_end_date(self, start_date, end_date=False):
        self.ensure_one()
        if self.start_criterion == 'custom':
            return end_date
        if self.warranty_basis != 'period':
            return False
        duration = relativedelta(**{self.warranty_duration_unit: self.warranty_duration})
        return start_date + duration - relativedelta(days=1)

    def _warranty_correction_entitlements(self):
        """D10 / Q12: (recalculated, kept) entitlements of a date correction. Only Draft /
        Pending entitlements not selected / merged for a job whose due date is still the
        calculated one (not changed manually) are recalculated."""
        self.ensure_one()
        recalculated = self.env['warranty.service.entitlement']
        for entitlement in self.service_entitlement_ids:
            if entitlement.state in ('draft', 'pending') and not entitlement._is_expiry_blocked() \
                    and entitlement.due_date == self._get_free_service_due_values(
                        entitlement.service_no)['due_date']:
                recalculated |= entitlement
        return recalculated, self.service_entitlement_ids - recalculated

    def _warranty_correct_dates(self, start_date, reason, end_date=False, attachments=None):
        """D9 / D10 / Q11: authorized correction of a Confirmed / Suspended card."""
        self.ensure_one()
        self._warranty_check_date_correction_group()
        if self.state not in ('confirmed', 'suspended', 'expired'):
            raise UserError(_("Warranty dates can only be corrected on Confirmed, Suspended or "
                              "Expired warranty cards."))
        if not start_date or not (reason or '').strip():
            raise UserError(_("The correction needs a start date and a reason."))
        end_date = self._warranty_correction_end_date(start_date, end_date)
        if self.start_criterion == 'custom' and (not end_date or end_date < start_date):
            raise UserError(_("A custom date range needs an end date not before the start date."))
        old_start, old_end = self.warranty_start_date, self.warranty_end_date
        if (old_start, old_end) == (start_date, end_date):
            raise UserError(_("The new dates are the current warranty dates."))
        recalculated, __ = self._warranty_correction_entitlements()
        self._warranty_system_write({'warranty_start_date': start_date,
                                     'warranty_end_date': end_date})
        self.unit_warranty_ids.filtered(
            lambda unit: unit.state not in ('replaced', 'cancelled'))._warranty_system_write(
            {'start_date': start_date, 'end_date': end_date})
        changed = recalculated._warranty_recalculate_due_dates(
            _("Warranty date correction of %(card)s: %(reason)s", card=self.name, reason=reason))
        log = self._warranty_log_date_event('correction', _(
            "Warranty dates corrected: %(old_start)s - %(old_end)s -> %(start)s - %(end)s. "
            "Free services recalculated: %(services)s.",
            old_start=format_date(self.env, old_start),
            old_end=format_date(self.env, old_end) if old_end else '-',
            start=format_date(self.env, start_date),
            end=format_date(self.env, end_date) if end_date else '-',
            services=', '.join(changed.mapped('name')) or _("none")),
            old_start=old_start, old_end=old_end, new_start=start_date, new_end=end_date,
            reason=reason, attachment_ids=attachments or self.env['ir.attachment'])
        self._warranty_restore_from_expiry(_("date correction"))
        if self.state in ('confirmed', 'expired'):
            self._regenerate_soft_copy()
        return log

    # ------------------------------------------------------------------ expiry (SRS 9.13, 13, 14)
    @api.model
    def _cron_expire_warranties(self):
        """Daily, per company in its warranty timezone. It only expires, so a second run changes
        nothing, and it never writes dates. Usage-based, Suspended and Cancelled cards are not read."""
        cards = self.search([('state', '=', 'confirmed'), ('warranty_basis', '=', 'period')])
        for company, company_cards in cards.grouped('company_id').items():
            today = company._warranty_today(log_missing_timezone=True)
            for card in company_cards:
                card._warranty_apply_expiry(today)

    def _warranty_apply_expiry(self, today):
        """An Active unit expires when its coverage has ended. The card expires when every unit
        except Replaced and Cancelled is Expired: a Draft or Suspended unit holds it."""
        self.ensure_one()
        ended = self.unit_warranty_ids.filtered(
            lambda unit: unit.state == 'active' and unit._warranty_coverage_end()
            and unit._warranty_coverage_end() < today)
        ended._warranty_system_write({'state': 'expired'})
        covered = self.unit_warranty_ids.filtered(
            lambda unit: unit.state not in ('replaced', 'cancelled'))
        card_ended = bool(covered) and all(unit.state == 'expired' for unit in covered)
        if card_ended:
            self._warranty_system_write({'state': 'expired'})
        if ended or card_ended:
            self._message_log(body=Markup('<p>%s</p>') % _(
                "Warranty expiry: %(units)s. Warranty card %(status)s. Warranty dates did not change.",
                units=_("units %s Expired", ', '.join(ended.mapped('name'))) if ended
                else _("no further unit changed"),
                status=_("Expired") if card_ended else _("stays Confirmed")))

    def _warranty_restore_from_expiry(self, source):
        """Only a date correction or a completed replacement calls this: an Expired unit with a valid
        period is Active again, and an Expired card with an Active unit is Confirmed again."""
        self.ensure_one()
        today = self.company_id._warranty_today()
        restored = self.unit_warranty_ids.filtered(
            lambda unit: unit.state == 'expired' and unit._warranty_coverage_end()
            and unit._warranty_coverage_end() >= today)
        restored._warranty_system_write({'state': 'active'})
        card_restored = self.state == 'expired' and any(
            unit.state == 'active' for unit in self.unit_warranty_ids)
        if card_restored:
            self._warranty_system_write({'state': 'confirmed'})
        if restored or card_restored:
            self.sudo()._message_log(body=Markup('<p>%s</p>') % _(
                "Warranty restored by %(origin)s: units %(units)s Active. Warranty card %(status)s.",
                origin=source, units=', '.join(restored.mapped('name')) or '-',
                status=_("Confirmed") if card_restored else _("unchanged")))

    def _warranty_card_print_units(self):
        """One printed sheet per unit that is still under this card."""
        self.ensure_one()
        return self.unit_warranty_ids.filtered(lambda unit: unit.state != 'cancelled').sorted('name')

    def _warranty_card_print_values(self, unit):
        """Values of one printed sheet. sudo: the PDF is generated by system code; the user who
        confirms a card may have no Sales or Accounting rights."""
        self.ensure_one()
        card, unit = self.sudo(), unit.sudo()
        order = card.sale_order_id
        product = unit.product_id or card.product_id
        partner = card.partner_id
        company = card.company_id
        invoice = unit.source_invoice_id or card.source_invoice_id or card._get_posted_invoices()[:1]
        # 'warranty_model' comes from warranty_management_accounting, the roles from _mrp.
        model = 'warranty_model' in product._fields and product.warranty_model or product.default_code
        indoor = unit['indoor_serial_id'] if 'indoor_serial_id' in unit._fields else card.indoor_serial_id
        outdoor = unit['outdoor_serial_id'] if 'outdoor_serial_id' in unit._fields else card.outdoor_serial_id
        indoor, outdoor = indoor or card.indoor_serial_id, outdoor or card.outdoor_serial_id
        start = unit.start_date or card.warranty_start_date
        end = unit.end_date or card.warranty_end_date
        duration = False
        if card.warranty_basis == 'period' and card.warranty_duration:
            duration = '%s %s' % (card.warranty_duration, dict(
                card._fields['warranty_duration_unit']._description_selection(self.env)).get(
                    card.warranty_duration_unit, ''))
        usage = False
        if card.warranty_basis == 'usage' and (unit.usage_limit or card.usage_limit):
            usage = '%s %s' % (unit.usage_limit or card.usage_limit, dict(
                card._fields['usage_unit']._description_selection(self.env)).get(card.usage_unit, ''))
        address_of = lambda contact: ', '.join(line.strip() for line in (
            contact._display_address(without_company=True) or '').splitlines() if line.strip())
        phone = partner.phone or partner.mobile or partner.commercial_partner_id.phone \
            or partner.commercial_partner_id.mobile
        return {
            'number': card.name,
            'unit_number': unit.name,
            'dealer': order.user_id.name if order.user_id.id != SUPERUSER_ID else False,
            'model': model,
            'item': product.name,
            'serial': ', '.join(unit.serial_ids.mapped('name')),
            'indoor': indoor.name,
            'outdoor': outdoor.name,
            'invoice': invoice.name,
            'purchase_date': invoice.invoice_date or start,
            'customer': partner.name,
            'address': address_of(partner),
            'phone': phone,
            'sale_date': card.installation_date or start,
            'sale_order': order.name,
            'duration': duration,
            'usage': usage,
            'start_text': format_date(self.env, start) if start else '',
            'end_text': format_date(self.env, end) if end else '',
            'free_services': card.free_services_allowed,
            'hotline': company.warranty_card_hotline or company.phone,
            'company_name': company.name,
            'company_address': address_of(company.partner_id),
            'company_phone': company.phone,
            'company_email': company.email,
        }

    def _regenerate_soft_copy(self):
        """Q11: after a correction the protected PDF soft copy (same attachment record) gets
        the corrected dates; it is not a download (Download Count unchanged)."""
        report = self.env.ref('warranty_management.action_report_warranty_card')
        for card in self:
            attachment = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', card._name), ('res_id', '=', card.id),
                ('res_field', '=', 'pdf_file')], limit=1)
            if not attachment:
                card._generate_soft_copy()
                continue
            pdf_content, __ = self.env['ir.actions.report'].with_context(
                warranty_card_pdf_token=SYSTEM_PDF_TOKEN)._render_qweb_pdf(report, card.ids)
            # sudo: system regeneration of the protected PDF.
            attachment.write({'raw': pdf_content})

    def action_open_date_wizard(self):
        """Record Exception (before confirmation) / Correct Warranty Dates (after)."""
        self.ensure_one()
        self._warranty_check_date_correction_group()
        mode = 'exception' if self.state in OPEN_CARD_STATES else 'correction'
        return {
            'type': 'ir.actions.act_window',
            'name': _("Record Start Date Exception") if mode == 'exception'
            else _("Correct Warranty Dates"),
            'res_model': 'warranty.card.date.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_card_id': self.id, 'default_mode': mode},
        }

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

    def _warranty_render_pdf(self):
        """The warranty card PDF with the current report, nothing stored. Only after the download
        checks. sudo: same reach as the protected attachment; a Helpdesk user may have no Sales
        or Accounting rights."""
        self.ensure_one()
        report = self.env.ref('warranty_management.action_report_warranty_card')
        pdf_content, __ = self.env['ir.actions.report'].sudo().with_context(
            warranty_card_pdf_token=SYSTEM_PDF_TOKEN)._render_qweb_pdf(report, self.ids)
        return pdf_content

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

    def _log_pdf_download(self, log):
        """One internal chatter note per successful PDF download (approved): user, date, time
        (downloading user's timezone, UTC without one) and download number. Written in the
        same locked transaction as the download log, so a refused or retried link logs
        nothing; no email, no notification."""
        self.ensure_one()
        user = log.user_id
        tz_name = user.tz or 'UTC'
        local = pytz.utc.localize(log.download_date).astimezone(pytz.timezone(tz_name))
        body = Markup('<p>%s</p>') % _(
            "Warranty card PDF downloaded - Download No. %(number)s by %(user)s on %(date)s at "
            "%(time)s (%(tz)s)", number=log.download_no, user=user.name,
            date=format_date(self.env, local.date()), time=local.strftime('%H:%M'),
            tz=tz_name)
        # sudo: the downloading user may not have write access to the card.
        self.sudo()._message_log(body=body, author_id=user.partner_id.id)

    def action_download_pdf(self):
        """Download PDF (approved D1-D5): the free downloads, then one approved request per
        download; the file is delivered by a single-use ticket of the current user."""
        self.ensure_one()
        self.check_access('read')
        if self.state not in ('confirmed', 'expired'):
            raise UserError(_("The PDF can only be downloaded for a confirmed or expired warranty "
                              "card."))
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
