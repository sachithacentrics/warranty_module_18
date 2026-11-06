import logging

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.tools import format_date, format_datetime

from odoo.addons.warranty_management_mrp.models.mrp_bom import ROLE_FIELDS

_logger = logging.getLogger(__name__)

# SRS 10.6, see doc/part7_replacement_design.md.
EXECUTABLE_TYPES = ('full', *ROLE_FIELDS, 'goodwill', 'vendor', 'component')
# The types with a Finance approval level (SRS 16.1, BA B1).
FINANCE_TYPES = ('full',)
# The types that change the serial and the dates of the whole unit.
UNIT_SCOPE_TYPES = ('full', 'goodwill', 'vendor')
# BA decision: the case results of a Goodwill replacement. The result itself never changes.
GOODWILL_RESULTS = ('not_eligible', 'out_of_warranty')
GOODWILL_CARD_STATES = ('confirmed', 'expired')
GOODWILL_UNIT_STATES = ('active', 'expired')
# Dates of one serial of a kit unit (SRS 11.3); empty: the dates of the unit apply.
ROLE_DATE_FIELDS = {
    'indoor': ('indoor_start_date', 'indoor_end_date'),
    'outdoor': ('outdoor_start_date', 'outdoor_end_date'),
}
REPLACEMENT_TYPES = [
    ('full', 'Full Product'),
    ('indoor', 'Indoor Unit'),
    ('outdoor', 'Outdoor Unit'),
    ('component', 'Component'),
    ('goodwill', 'Goodwill'),
    ('vendor', 'Vendor Replacement'),
]
REPLACEMENT_REASONS = [
    ('manufacturing_defect', 'Manufacturing Defect'),
    ('compressor_failure', 'Compressor Failure'),
    ('pcb_failure', 'PCB Failure'),
    ('goodwill', 'Goodwill'),
    ('other', 'Other'),
]
REPLACEMENT_STATES = [
    ('draft', 'Draft'),
    ('submitted', 'Submitted'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('done', 'Done'),
]
# SRS 11.3; same keys as warranty.policy.replacement_date_policy.
DATE_POLICIES = [
    ('continue_original', 'Continue Original Warranty'),
    ('restart', 'Restart from Replacement Date'),
    ('remaining_period', 'Remaining Period Only'),
    ('fixed_extension', 'Add Fixed Extension'),
    ('manual', 'Manual Approval-Based Date'),
]
EXTENSION_UNITS = [
    ('days', 'Days'),
    ('months', 'Months'),
]
OPEN_STATES = ('draft', 'submitted', 'approved')
# Proposed: the case states that can still complete through the existing job or repair path.
ORIGIN_CASE_STATES = ('approved', 'job_created', 'in_progress')
# Written by the actions and the validated pickings only. Python object: no client can send it.
_REPLACEMENT_MARKER = object()
SYSTEM_FIELDS = {
    'state', 'warranty_card_id', 'warranty_unit_id', 'old_serial_id', 'product_id',
    'requested_by_id', 'requested_date', 'finance_required', 'gm_approved_by_id',
    'gm_approved_date', 'finance_approved_by_id', 'finance_approved_date', 'rejected_by_id',
    'rejected_date', 'return_required', 'return_picking_id', 'return_reused',
    'delivery_picking_id', 'delivery_date', 'extension_base', 'remaining_days', 'old_start_date',
    'old_end_date', 'new_start_date', 'new_end_date', 'dates_changed', 'updated_card_generated',
    'replacement_cost', 'replacement_cost_verified'}
REQUEST_FIELDS = {'warranty_case_id', 'replacement_type', 'new_serial_id', 'return_location_id',
                  'reason', 'reason_note', 'date_policy', 'extension_value', 'extension_unit'}
MANUAL_DATE_FIELDS = {'manual_end_date', 'manual_date_reason'}
RECOVERY_FIELDS = {'rejection_reason', 'recovery_new_serial_id', 'recovery_reason'}


class WarrantyReplacement(models.Model):
    """Warranty Replacement / Serial Swap (SRS 10.6, 11, 9.12 Figure 3). The stock moves are
    standard transfers, validated on the standard screen: this record only creates them and
    follows their validation; the swap runs once, after the replacement delivery is validated."""
    _name = 'warranty.replacement'
    _description = 'Warranty Replacement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Replacement Ref', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    state = fields.Selection(REPLACEMENT_STATES, string='Approval Status', default='draft',
                             required=True, readonly=True, copy=False, tracking=True, index=True)
    warranty_case_id = fields.Many2one(
        'warranty.case', string='Warranty Case', required=True, tracking=True, index=True,
        ondelete='restrict', domain="[('state', 'in', ('approved', 'job_created', 'in_progress'))]")
    company_id = fields.Many2one(related='warranty_case_id.company_id', store=True, index=True)
    ticket_id = fields.Many2one(related='warranty_case_id.helpdesk_ticket_id')
    partner_id = fields.Many2one(related='warranty_case_id.partner_id', string='Customer')
    warranty_card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', compute='_compute_case_links', store=True,
        index='btree_not_null', ondelete='restrict')
    warranty_unit_id = fields.Many2one(
        'warranty.unit', string='Unit Warranty', compute='_compute_case_links', store=True,
        index='btree_not_null', ondelete='restrict')
    product_id = fields.Many2one('product.product', string='Product',
                                 compute='_compute_product_id', store=True, ondelete='restrict')
    replacement_type = fields.Selection(
        REPLACEMENT_TYPES, string='Replacement Type', required=True, default='full', tracking=True,
        help="Full Product: the old product comes back and a new one is delivered.\n"
             "Indoor Unit: only the indoor serial of a kit changes; the outdoor serial stays.\n"
             "Outdoor Unit: only the outdoor serial of a kit changes; the indoor serial stays.\n"
             "Goodwill: customer support decision outside the normal warranty rules. Needs "
             "management approval, and the manager decides the warranty end date.\n"
             "Vendor Replacement: the supplier or manufacturer replaces a defective product. A "
             "vendor claim is optional.\n"
             "Component: a part is replaced through a Material Request; the serial of the product "
             "and the warranty dates do not change.")
    old_serial_id = fields.Many2one(
        'stock.lot', string='Old Serial', compute='_compute_old_serial', store=True, tracking=True,
        index='btree_not_null', ondelete='restrict',
        help="The active serial of the Unit Warranty when the request is submitted. On an Indoor "
             "or Outdoor Unit replacement, the active serial of that component.")
    unaffected_serial_id = fields.Many2one(
        'stock.lot', string='Other Serial (Not Changed)', compute='_compute_unaffected_serial',
        compute_sudo=True,
        help="The serial of the other kit component. This replacement does not change it or its "
             "warranty dates.")
    new_serial_id = fields.Many2one(
        'stock.lot', string='New Serial', tracking=True, index='btree_not_null', ondelete='restrict',
        domain="[('id', 'in', available_lot_ids)]",
        help="Serials of the same product in the source location of the Replacement Delivery "
             "Operation Type, not on any warranty card.")
    available_lot_ids = fields.Many2many('stock.lot', compute='_compute_available_lot_ids')
    reason = fields.Selection(REPLACEMENT_REASONS, string='Reason', required=True, tracking=True)
    reason_note = fields.Text(string='Reason Details')
    # Approval (SRS 11.2, 16, 16.1). Finance on a Full Product is BA decision B1: read from the
    # company setting at Submit, never assumed here.
    requested_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    requested_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    finance_required = fields.Boolean(string='Finance Approval Required', readonly=True, copy=False)
    gm_approved_by_id = fields.Many2one('res.users', string='GM Approved By', readonly=True,
                                        copy=False, tracking=True)
    gm_approved_date = fields.Datetime(string='GM Approved On', readonly=True, copy=False)
    finance_approved_by_id = fields.Many2one('res.users', string='Finance Approved By',
                                             readonly=True, copy=False, tracking=True)
    finance_approved_date = fields.Datetime(string='Finance Approved On', readonly=True, copy=False)
    rejected_by_id = fields.Many2one('res.users', string='Rejected By', readonly=True, copy=False,
                                     tracking=True)
    rejected_date = fields.Datetime(string='Rejected On', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', copy=False, tracking=True,
                                   help="Written by the approver. Required to reject.")
    case_eligibility_result = fields.Selection(related='warranty_case_id.eligibility_result',
                                               string='Case Eligibility Result')
    case_eligibility_reason = fields.Text(related='warranty_case_id.eligibility_reason',
                                          string='Case Eligibility Reason')
    can_approve = fields.Boolean(compute='_compute_can_decide')
    can_reject = fields.Boolean(compute='_compute_can_decide')
    approval_missing = fields.Boolean(
        compute='_compute_approval_missing',
        help="Indoor or Outdoor Unit request that reached Approved under the earlier no-approval "
             "version: it holds no Manager / GM approval, so its transfers cannot be validated.")
    # Recovery while the delivery is not validated: no extra status, validated stock is kept.
    recovery_new_serial_id = fields.Many2one(
        'stock.lot', string='Change New Serial To', copy=False, ondelete='restrict',
        domain="[('id', 'in', available_lot_ids)]",
        help="Used when the new serial cannot be delivered. The open delivery is cancelled and a "
             "delivery of this serial is created.")
    recovery_reason = fields.Text(string='Reason for Serial Change', copy=False,
                                  help="Written by the approver. Required to change the serial.")
    transfers_missing = fields.Boolean(compute='_compute_transfers_missing')
    # SRS 11.1: the parts of a Component replacement.
    component_line_ids = fields.One2many('warranty.replacement.component.line', 'replacement_id',
                                         string='Components')
    # SRS 11.1, 12 #15: the optional claim of a Vendor Replacement.
    vendor_claim_line_ids = fields.One2many('warranty.vendor.claim.line', 'replacement_id',
                                            string='Vendor Claim Lines', readonly=True)
    vendor_claim_count = fields.Integer(string='Vendor Claims',
                                        compute='_compute_vendor_claim_count', compute_sudo=True)
    # Return and delivery (SRS 11 steps 3-4, 13, 14).
    return_required = fields.Boolean(
        string='Return Required', readonly=True, copy=False,
        help="Read from the Warranty Policy of the card when the request is submitted. A card "
             "without this policy setting needs the return.")
    return_location_id = fields.Many2one(
        'stock.location', string='Old Unit Location', compute='_compute_return_location_id',
        store=True, readonly=False, ondelete='restrict', tracking=True,
        domain="['|', '&', ('usage', '=', 'internal'), ('warehouse_id', '=', False), "
               "('scrap_location', '=', True)]",
        help="Where the old unit is kept: warranty return, quality, repair, scrap or vendor return "
             "location. It is never a warehouse location, so the old unit cannot be sold.")
    return_picking_id = fields.Many2one(
        'stock.picking', string='Return Picking', readonly=True, copy=False,
        index='btree_not_null', ondelete='restrict',
        help="Old unit movement from the customer.")
    return_reused = fields.Boolean(
        string='Existing Return Reused', readonly=True, copy=False,
        help="The old unit was already received by this validated return: no second transfer.")
    delivery_picking_id = fields.Many2one(
        'stock.picking', string='Replacement Delivery', readonly=True, copy=False,
        index='btree_not_null', ondelete='restrict')
    delivery_date = fields.Date(string='Replacement Date', readonly=True, copy=False, tracking=True,
                                help="Date the replacement delivery was validated (Warranty "
                                     "Timezone).")
    # Warranty date policy (SRS 11.3). The base of a Fixed Extension is BA decision B3.
    date_policy = fields.Selection(
        DATE_POLICIES, string='Warranty Date Policy', compute='_compute_date_policy', store=True,
        readonly=False, required=True, tracking=True,
        help="Continue Original Warranty: the end date does not change.\n"
             "Restart from Replacement Date: a new warranty period starts on the replacement "
             "date.\n"
             "Remaining Period Only: the replacement gets only the remaining period, so the end "
             "date does not change.\n"
             "Add Fixed Extension: adds days or months.\n"
             "Manual Approval-Based Date: the approver decides the end date.")
    extension_value = fields.Integer(string='Extension', compute='_compute_date_policy', store=True,
                                     readonly=False, tracking=True)
    extension_unit = fields.Selection(EXTENSION_UNITS, string='Extension Unit',
                                      compute='_compute_date_policy', store=True, readonly=False)
    extension_base = fields.Selection(
        [('original_end', 'Warranty end date before this replacement'),
         ('delivery', 'Replacement delivery date')],
        string='Extension Added To', readonly=True, copy=False)
    manual_end_date = fields.Date(string='Manual End Date', copy=False, tracking=True,
                                  help="Entered by the approver before approving.")
    manual_date_reason = fields.Text(string='Manual Date Reason', copy=False)
    remaining_days = fields.Integer(string='Remaining Days', readonly=True, copy=False,
                                    help="Days from the replacement date to the end date.")
    old_start_date = fields.Date(string='Previous Start Date', readonly=True, copy=False)
    old_end_date = fields.Date(string='Previous End Date', readonly=True, copy=False)
    new_start_date = fields.Date(string='New Start Date', readonly=True, copy=False)
    new_end_date = fields.Date(string='New End Date', readonly=True, copy=False)
    dates_changed = fields.Boolean(string='Dates Changed', readonly=True, copy=False)
    updated_card_generated = fields.Boolean(string='Updated Card Generated', readonly=True,
                                            copy=False, tracking=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    replacement_cost = fields.Monetary(
        string='Replacement Cost', readonly=True, copy=False, tracking=True,
        help="Cost of the replacement unit, read from the stock valuation of the validated "
             "delivery. The value of the old unit is not deducted.")
    replacement_cost_verified = fields.Boolean(
        string='Cost From Stock Valuation', readonly=True, copy=False,
        help="Empty: the delivery has no stock valuation, so the cost is an estimate from the "
             "product cost.")

    @api.depends('warranty_case_id')
    def _compute_case_links(self):
        for replacement in self:
            case = replacement.warranty_case_id
            replacement.warranty_card_id = case.warranty_card_id
            replacement.warranty_unit_id = case.warranty_unit_id

    @api.depends('warranty_unit_id', 'replacement_type')
    def _compute_product_id(self):
        for replacement in self:
            replacement.product_id = replacement._warranty_replacement_target_product()

    @api.depends('warranty_unit_id', 'replacement_type')
    def _compute_old_serial(self):
        for replacement in self:
            replacement.old_serial_id = replacement._warranty_replacement_active_serial()

    @api.depends('warranty_unit_id', 'replacement_type')
    def _compute_unaffected_serial(self):
        for replacement in self:
            serial = self.env['stock.lot']
            if replacement.replacement_type in ROLE_FIELDS:
                for role, field in ROLE_FIELDS.items():
                    if role != replacement.replacement_type:
                        serial |= replacement.warranty_unit_id[field]
            replacement.unaffected_serial_id = serial

    def _warranty_replacement_role_line(self):
        """BoM line of the Indoor / Outdoor type, on the kit the unit was delivered with. sudo: the
        coordinator may have no Manufacturing rights."""
        self.ensure_one()
        if self.replacement_type not in ROLE_FIELDS:
            return self.env['mrp.bom.line']
        bom = self.sudo().warranty_unit_id._warranty_kit_bom()
        return (bom and bom._warranty_role_lines().get(self.replacement_type)) \
            or self.env['mrp.bom.line']

    def _warranty_replacement_target_product(self):
        """The product that moves: the kit component on an Indoor / Outdoor type. A Component
        replacement moves the products of its lines."""
        self.ensure_one()
        if self.replacement_type == 'component':
            return self.env['product.product']
        if self.replacement_type in ROLE_FIELDS:
            return self._warranty_replacement_role_line().product_id
        return self.warranty_unit_id.product_id

    def _warranty_replacement_active_serial(self):
        """The serial this type replaces: the serial of the role, or the only serial of the unit. A
        Component replacement replaces no serial of the unit."""
        self.ensure_one()
        unit = self.warranty_unit_id
        if self.replacement_type == 'component':
            return self.env['stock.lot']
        if self.replacement_type in ROLE_FIELDS:
            return unit[ROLE_FIELDS[self.replacement_type]]
        return unit.serial_ids if len(unit.serial_ids) == 1 else unit.serial_ids.browse()

    def _warranty_replacement_current_dates(self):
        """(start, end) in force for the serial this type replaces."""
        self.ensure_one()
        unit = self.sudo().warranty_unit_id
        if self.replacement_type in ROLE_FIELDS:
            return unit._warranty_role_dates(self.replacement_type)
        return unit.start_date, unit.end_date

    @api.depends('warranty_card_id')
    def _compute_date_policy(self):
        """continue the original warranty unless the policy says otherwise."""
        for replacement in self:
            policy = replacement.warranty_card_id.policy_id
            if replacement.replacement_type == 'goodwill':
                replacement.date_policy = 'manual'
            elif replacement.replacement_type == 'component':
                replacement.date_policy = 'continue_original'
            else:
                replacement.date_policy = policy.replacement_date_policy or 'continue_original'
            replacement.extension_value = policy.replacement_extension_value
            replacement.extension_unit = policy.replacement_extension_unit

    @api.onchange('replacement_type')
    def _onchange_replacement_type_goodwill(self):
        """SRS 11.1: a Goodwill replacement always uses the manual date."""
        if self.replacement_type == 'goodwill':
            self.reason = 'goodwill'
            self.date_policy = 'manual'
        elif self.replacement_type == 'component':
            self.date_policy = 'continue_original'

    @api.depends('company_id')
    def _compute_return_location_id(self):
        for replacement in self:
            company = replacement.company_id.sudo()
            replacement.return_location_id = \
                company.warranty_replacement_return_type_id.default_location_dest_id

    @api.depends('product_id', 'company_id')
    def _compute_available_lot_ids(self):
        """sudo: read for the selection, whatever the user's Inventory rights."""
        Quant = self.env['stock.quant'].sudo()
        for replacement in self:
            company = replacement.company_id.sudo()
            location = company.warranty_replacement_delivery_type_id.default_location_src_id
            lots = self.env['stock.lot']
            if location and replacement.product_id:
                lots = Quant.search([('location_id', 'child_of', location.id),
                                     ('product_id', '=', replacement.product_id.id),
                                     ('lot_id', '!=', False), ('quantity', '>', 0)]).lot_id
                lots -= self.env['warranty.unit'].sudo().search(
                    [('serial_ids', 'in', lots.ids), ('state', '!=', 'cancelled')]).serial_ids
            replacement.available_lot_ids = self.env['stock.lot'].browse(lots.ids)

    @api.depends('vendor_claim_line_ids')
    def _compute_vendor_claim_count(self):
        for replacement in self:
            replacement.vendor_claim_count = len(replacement.vendor_claim_line_ids.claim_id)

    @api.depends('state', 'replacement_type', 'gm_approved_by_id')
    def _compute_approval_missing(self):
        for replacement in self:
            replacement.approval_missing = replacement.state == 'approved' \
                and replacement.replacement_type in ROLE_FIELDS \
                and not replacement.gm_approved_by_id

    @api.depends('state', 'return_required', 'return_picking_id.state', 'delivery_picking_id.state',
                 'approval_missing', 'replacement_type', 'component_line_ids.return_required',
                 'component_line_ids.return_picking_id.state')
    def _compute_transfers_missing(self):
        """sudo: the status of the transfers, whatever the user's Inventory rights."""
        for replacement in self:
            record = replacement.sudo()
            if record.replacement_type == 'component':
                replacement.transfers_missing = record.state == 'approved' and any(
                    line.return_required
                    and not self._warranty_replacement_active(line.return_picking_id)
                    for line in record.component_line_ids)
                continue
            replacement.transfers_missing = record.state == 'approved' \
                and not record.approval_missing and (
                not self._warranty_replacement_active(record.delivery_picking_id)
                or (record.return_required
                    and not self._warranty_replacement_active(record.return_picking_id)))

    @api.depends_context('uid')
    @api.depends('state', 'requested_by_id', 'gm_approved_by_id', 'finance_approved_by_id',
                 'finance_required', 'delivery_picking_id.state')
    def _compute_can_decide(self):
        for replacement in self:
            replacement.can_approve = replacement.state == 'submitted' \
                and bool(replacement._warranty_replacement_levels_to_sign())
            replacement.can_reject = replacement._warranty_replacement_may_reject()

    @api.constrains('warranty_case_id', 'new_serial_id')
    def _check_replacement_serials(self):
        for replacement in self.sudo():
            new = replacement.new_serial_id
            if new and new == replacement.old_serial_id:
                raise ValidationError(_("The New Serial must differ from the Old Serial."))

    @api.model_create_multi
    def create(self, vals_list):
        if any(SYSTEM_FIELDS & set(vals) for vals in vals_list) \
                and self.env.context.get('warranty_replacement_marker') is not _REPLACEMENT_MARKER:
            raise UserError(_("Status, approvals, dates and transfers of a replacement are set by "
                              "its actions and validated transfers."))
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                case = self.env['warranty.case'].browse(vals.get('warranty_case_id'))
                vals['name'] = self.env['ir.sequence'].with_company(
                    case.sudo().company_id or self.env.company).next_by_code(
                    'warranty.replacement') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('warranty_replacement_marker') is not _REPLACEMENT_MARKER:
            names = set(vals)
            if SYSTEM_FIELDS & names:
                raise UserError(_("Status, approvals, dates and transfers of a replacement are set "
                                  "by its actions and validated transfers."))
            if REQUEST_FIELDS & names:
                self._warranty_replacement_check_coordinator()
                if any(replacement.state != 'draft' for replacement in self):
                    raise UserError(_("The request can only be changed while it is Draft."))
            if MANUAL_DATE_FIELDS & names and any(
                    not replacement._warranty_replacement_may_enter_manual_date()
                    for replacement in self):
                raise UserError(_("The manual end date is entered by an approver, before the first "
                                  "approval."))
            if RECOVERY_FIELDS & names and any(not replacement.can_reject
                                               for replacement in self):
                raise UserError(_("The rejection and serial change details are written by an "
                                  "authorized approver."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_not_draft(self):
        if any(replacement.state != 'draft' for replacement in self):
            raise UserError(_("Only Draft replacements can be deleted (replacement history)."))

    def _warranty_replacement_finance_applies(self):
        self.ensure_one()
        return self.replacement_type in FINANCE_TYPES

    def _warranty_replacement_replaces_unit(self):
        self.ensure_one()
        return self.replacement_type in UNIT_SCOPE_TYPES

    def _warranty_replacement_may_enter_manual_date(self):
        """The first approver."""
        self.ensure_one()
        return self.can_approve and not self.gm_approved_by_id \
            and not self.finance_approved_by_id

    def _warranty_replacement_marked(self):
        return self.with_context(warranty_replacement_marker=_REPLACEMENT_MARKER)

    def _warranty_replacement_lock(self):
        """One action at a time on a replacement: a second click or a parallel request waits, then
        reads the result of the first, so no transfer or signature is duplicated."""
        self.env.cr.execute("SELECT id FROM warranty_replacement WHERE id IN %s FOR UPDATE",
                            [tuple(self.ids)])
        self.invalidate_recordset()

    def _warranty_replacement_check_coordinator(self):
        user = self.env.user
        if not self.env.su and not (user.has_group('helpdesk.group_helpdesk_user')
                                    or user.has_group('stock.group_stock_user')):
            raise AccessError(_("Only Helpdesk or Inventory users can prepare replacements."))


    def _warranty_replacement_log(self, text):
        """Warranty history notes (SRS 2.13): replacement, ticket, case, card and repair orders of
        this serial. sudo: the warehouse user may not write to them; notes only."""
        self.ensure_one()
        replacement = self.sudo()
        body = Markup('<p>%s</p>') % text
        case = replacement.warranty_case_id
        repairs = case._warranty_active_repairs().filtered(
            lambda repair: repair.lot_id == replacement.old_serial_id)
        for record in (replacement, replacement.ticket_id, case, replacement.warranty_card_id,
                       *repairs):
            if record:
                record._message_log(body=body)

    def _warranty_replacement_todo_prefix(self):
        self.ensure_one()
        return _("Replacement %s: ", self.name)

    def _warranty_replacement_close_todos(self):
        self.ensure_one()
        prefix = self._warranty_replacement_todo_prefix()
        self.sudo().activity_ids.filtered(
            lambda activity: (activity.summary or '').startswith(prefix)
        ).action_feedback(feedback=_("Next step reached."))

    def _warranty_replacement_todo(self, step, note, users=None):
        """The next step for the given users, else the ticket's assigned user, else the creator;
        the previous step is closed; no duplicate. sudo: To-Dos of other users."""
        self.ensure_one()
        replacement = self.sudo()
        summary = self._warranty_replacement_todo_prefix() + step
        if replacement.activity_ids.filtered(lambda activity: activity.summary == summary):
            return
        self._warranty_replacement_close_todos()
        for user in users or replacement.ticket_id.user_id or replacement.create_uid:
            replacement.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                          summary=summary, note=note)

    # ------------------------------------------------------------------ validations (SRS 11.2, 13)
    def _warranty_replacement_type_problems(self):
        """Full Product, Indoor Unit, Outdoor Unit and Goodwill run. A Goodwill reason needs the
        Goodwill manual date, so it never runs as one of the others. The Reason Details of a Goodwill
        replacement are its exception reason."""
        self.ensure_one()
        if self.replacement_type not in EXECUTABLE_TYPES:
            labels = dict(REPLACEMENT_TYPES)
            return [_("Replacement type %s is not available yet: it needs business decisions that "
                      "are still pending.", labels[self.replacement_type])]
        if self.replacement_type == 'goodwill':
            if not (self.reason_note or '').strip():
                return [_("Enter the Reason Details: why this Goodwill replacement is granted.")]
        elif self.reason == 'goodwill':
            return [_("Reason Goodwill belongs to the Goodwill replacement type.")]
        return []

    def _warranty_replacement_role_problems(self):
        """SRS 11.1, 11.2: the old serial is the active serial of this component of the kit, and
        the case was checked on that serial (its eligibility used that serial's dates)."""
        self.ensure_one()
        replacement = self.sudo()
        case = replacement.warranty_case_id
        unit = replacement.warranty_unit_id
        label = dict(REPLACEMENT_TYPES)[self.replacement_type]
        line = replacement._warranty_replacement_role_line()
        if not line:
            return [_("%(type)s replacement needs a kit with this component: %(unit)s has none.",
                      type=label, unit=unit.name)]
        serial = replacement._warranty_replacement_active_serial()
        if not serial:
            return [_("Unit Warranty %(unit)s has no active %(type)s serial.", unit=unit.name,
                      type=label)]
        problems = []
        if serial.product_id != line.product_id:
            problems.append(_("Active serial %(serial)s of %(unit)s belongs to %(lot_product)s, not "
                              "to the %(type)s component %(product)s.", serial=serial.name,
                              unit=unit.name, lot_product=serial.product_id.display_name,
                              type=label, product=line.product_id.display_name))
        if replacement.old_serial_id != serial:
            problems.append(_("Old Serial %(old)s is not the active %(type)s serial %(serial)s of "
                              "%(unit)s.", old=replacement.old_serial_id.name or '-', type=label,
                              serial=serial.name, unit=unit.name))
        if case.serial_id != serial:
            problems.append(_("Warranty case %(case)s was checked on serial %(case_serial)s, not on "
                              "the active %(type)s serial %(serial)s. Use the replacement type of "
                              "the case serial, or open a case for this serial.", case=case.name,
                              case_serial=case.serial_id.name or '-', type=label,
                              serial=serial.name))
        return problems

    def _warranty_replacement_case_problems(self):
        """SRS 11.2: from a warranty case; the old serial is the current active serial."""
        self.ensure_one()
        replacement = self.sudo()
        case = replacement.warranty_case_id
        card = case.warranty_card_id
        unit = case.warranty_unit_id
        problems = []
        goodwill = self.replacement_type == 'goodwill'
        if goodwill:
            if case.state != 'eligibility_checked' or case.eligibility_result not in GOODWILL_RESULTS:
                problems.append(_("Goodwill: warranty case %s must be Eligibility Checked, with "
                                  "result Not Eligible or Out of Warranty.", case.name))
            # The existing rule: a case without Case Type cannot be completed (approved B6).
            if not case.case_type:
                problems.append(_("Goodwill: warranty case %s has no Case Type, so it could not be "
                                  "completed.", case.name))
        elif case.state not in ORIGIN_CASE_STATES or case.eligibility_result != 'eligible':
            problems.append(_("Warranty case %s must be Eligible and Approved, Job Created or In "
                              "Progress.", case.name))
        if not unit:
            problems.append(_("Warranty case %s has no Unit Warranty.", case.name))
            return problems
        if goodwill:
            if card.state not in GOODWILL_CARD_STATES:
                problems.append(_("Goodwill: warranty card %(card)s is %(state)s. A Cancelled or "
                                  "Suspended warranty stays blocked.", card=card.name,
                                  state=dict(card._fields['state']._description_selection(
                                      self.env))[card.state]))
            if unit.state not in GOODWILL_UNIT_STATES:
                problems.append(_("Goodwill: Unit Warranty %s must be Active or Expired.", unit.name))
        else:
            # An Approved replacement finishes its stock when the warranty ends meanwhile; Suspended
            # and Cancelled still block it. The final approval itself still needs Confirmed.
            approved = self.state == 'approved'
            if card.state != 'confirmed' and not (approved and card.state == 'expired'):
                problems.append(_("Warranty card %s must be Confirmed.", card.name))
            if unit.state != 'active' and not (approved and unit.state == 'expired'):
                problems.append(_("Unit Warranty %s must be Active.", unit.name))
        if self.replacement_type in ROLE_FIELDS:
            problems += self._warranty_replacement_role_problems()
        elif self.replacement_type == 'component':
            pass  # the unit keeps its serial: a kit or any other unit
        elif unit.product_id.tracking != 'serial' or unit.indoor_serial_id \
                or unit.outdoor_serial_id or len(unit.serial_ids) != 1:
            problems.append(_("Unit Warranty %s must hold one product with one serial. A kit "
                              "uses the Indoor Unit or Outdoor Unit type.", unit.name))
        elif case.serial_id and case.serial_id != unit.serial_ids:
            problems.append(_("Serial %(case_serial)s of the case is not the active serial "
                              "%(serial)s of %(unit)s.", case_serial=case.serial_id.name,
                              serial=unit.serial_ids.name, unit=unit.name))
        # Per type: the Indoor and the Outdoor serial of one kit are separate machines.
        other = self.search([('warranty_unit_id', '=', unit.id), ('id', '!=', self.id),
                             ('replacement_type', '=', self.replacement_type),
                             ('state', 'in', ('submitted', 'approved'))], limit=1)
        if other:
            problems.append(_("Unit Warranty %(unit)s already has the open replacement %(other)s.",
                              unit=unit.name, other=other.name))
        if self.replacement_type == 'component':
            return problems
        active_serial = replacement._warranty_replacement_active_serial()
        for repair in case._warranty_active_repairs().filtered(
                lambda repair: repair.lot_id == active_serial
                and not repair.warranty_equipment_returned):
            if repair.state != 'done' or repair.warranty_repair_result != 'not_repairable':
                problems.append(_("Repair Order %s of this serial must first end as Not Repairable "
                                  "or be cancelled.", repair.name))
        return problems

    def _warranty_replacement_new_serial_problems(self):
        """SRS 11.2 / 13: available in stock and not on another active card."""
        self.ensure_one()
        replacement = self.sudo()
        new = replacement.new_serial_id
        if not new:
            return [_("Select the New Serial.")]
        problems = []
        if new.product_id != replacement.product_id:
            problems.append(_("New Serial %(serial)s belongs to %(lot_product)s, not to "
                              "%(product)s.", serial=new.name,
                              lot_product=new.product_id.display_name,
                              product=replacement.product_id.display_name))
        unit = self.env['warranty.unit'].sudo().search(
            [('serial_ids', 'in', new.ids), ('state', '!=', 'cancelled')], limit=1)
        if unit:
            problems.append(_("New Serial %(serial)s is already on warranty unit %(unit)s.",
                              serial=new.name, unit=unit.name))
        other = self.sudo().search([('new_serial_id', '=', new.id), ('id', '!=', self.id),
                                    ('state', 'in', ('submitted', 'approved'))], limit=1)
        if other:
            problems.append(_("New Serial %(serial)s is on the open replacement %(other)s.",
                              serial=new.name, other=other.name))
        backup = self.env['warranty.backup.unit'].sudo().search(
            [('lot_id', '=', new.id), ('state', '!=', 'closed')], limit=1)
        if backup:
            problems.append(_("New Serial %(serial)s is on the open backup unit %(backup)s.",
                              serial=new.name, backup=backup.name))
        # A card can hold a manually entered Indoor / Outdoor serial that is on no unit.
        card = self.env['warranty.card'].sudo().search(
            ['|', ('indoor_serial_id', '=', new.id), ('outdoor_serial_id', '=', new.id),
             ('state', '!=', 'cancelled')], limit=1)
        if card:
            problems.append(_("New Serial %(serial)s is already on warranty card %(card)s.",
                              serial=new.name, card=card.name))
        return problems

    def _warranty_replacement_new_serial_available(self):
        self.ensure_one()
        replacement = self.sudo()
        location = replacement.company_id.warranty_replacement_delivery_type_id\
            .default_location_src_id
        return bool(location) and self.env['stock.quant'].sudo()._get_available_quantity(
            replacement.product_id, location, lot_id=replacement.new_serial_id, strict=False) >= 1

    def _warranty_replacement_approver_problems(self):
        """Indoor / Outdoor need the Manager / GM level only (SRS 11.2, Figure 3)."""
        self.ensure_one()
        company = self.sudo().company_id
        problems = []
        finance_applies = self._warranty_replacement_finance_applies()
        if finance_applies and not company.warranty_replacement_full_finance:
            problems.append(_("Finance approval of Full Product replacements is a pending business "
                              "decision (BA B1): choose it in Settings > Warranty."))
        requester = self.requested_by_id or self.env.user
        managers = company.warranty_replacement_gm_user_ids - requester
        finance = company.warranty_replacement_finance_user_ids - requester
        if not managers:
            problems.append(_("Set the Replacement GM Approvers in Settings > Warranty: at least "
                              "one user other than the submitter."))
        if finance_applies and company.warranty_replacement_full_finance == 'required' \
                and (not finance or (len(managers | finance) < 2)):
            problems.append(_("Set the Replacement Finance Approvers in Settings > Warranty: one "
                              "person cannot sign both levels, and the submitter cannot sign."))
        return problems

    def _warranty_replacement_settings_problems(self):
        """Pending BA decisions stop the request here instead of being assumed."""
        self.ensure_one()
        replacement = self.sudo()
        company = replacement.company_id
        problems = []
        component = self.replacement_type == 'component'
        if not company.warranty_replacement_return_type_id and (
                not component or self.component_line_ids.filtered('return_required')):
            problems.append(_("Set the Replacement Return Operation Type in Settings > Warranty."))
        if not company.warranty_replacement_delivery_type_id and not component:
            problems.append(_("Set the Replacement Delivery Operation Type in Settings > Warranty."))
        problems += self._warranty_replacement_approver_problems()
        location = replacement.return_location_id
        if not location:
            problems.append(_("Select the Old Unit Location."))
        elif not location.scrap_location and (location.usage != 'internal' or location.warehouse_id):
            problems.append(_("Old Unit Location %s must be a scrap location or an internal "
                              "location outside the warehouses.", location.display_name))
        return problems

    def _warranty_replacement_date_problems(self):
        """SRS 11.3. A Fixed Extension needs BA decision B3 before it can run."""
        self.ensure_one()
        replacement = self.sudo()
        company = replacement.company_id
        card = replacement.warranty_card_id
        unit = replacement.warranty_unit_id
        today = company._warranty_today()
        policy = self.date_policy
        __, end_date = self._warranty_replacement_current_dates()
        problems = []
        if policy != 'continue_original' and card.warranty_basis != 'period':
            problems.append(_("A usage-based warranty can only use Continue Original Warranty."))
        if policy == 'restart' and (card.start_criterion == 'custom'
                                    or not card.warranty_duration):
            problems.append(_("Restart from Replacement Date needs a warranty duration: a custom "
                              "date range has none."))
        # Checked up to the approval: an Approved replacement finishes its stock.
        if policy == 'remaining_period' and self.state != 'approved' \
                and (not end_date or end_date < today):
            problems.append(_("Remaining Period Only: the warranty of %s has no remaining period.",
                              unit.name))
        if policy == 'fixed_extension':
            if not (self.extension_base or company.warranty_replacement_extension_base):
                problems.append(_("What a Fixed Extension is added to is a pending business "
                                  "decision (BA B3): choose it in Settings > Warranty."))
            if self.extension_value <= 0 or not self.extension_unit:
                problems.append(_("Enter the Extension and its unit."))
        return problems

    def _warranty_replacement_manual_date_problems(self):
        self.ensure_one()
        if self.date_policy != 'manual':
            return []
        problems = []
        start, __ = self._warranty_replacement_current_dates()
        if not self.manual_end_date:
            problems.append(_("Enter the Manual End Date."))
        elif start and self.manual_end_date < start:
            problems.append(_("The Manual End Date cannot be before the warranty start date."))
        if not (self.manual_date_reason or '').strip():
            problems.append(_("Enter the Manual Date Reason."))
        return problems

    def _warranty_replacement_old_position(self):
        """Where the old serial is: ('customer', location), ('reuse', picking) when a validated
        return already received exactly this serial in the Old Unit Location or the Warranty Repair
        Intake Location, else ('refused', problem). sudo: read for the checks."""
        self.ensure_one()
        replacement = self.sudo()
        lot = replacement.old_serial_id
        quants = self.env['stock.quant'].sudo().search([('lot_id', '=', lot.id),
                                                        ('quantity', '>', 0)])
        if len(quants) != 1:
            return 'refused', _("Old Serial %s has no single stock position: an inventory user "
                                "must review it.", lot.name)
        location = quants.location_id
        if location.usage == 'customer':
            problem = replacement._warranty_replacement_open_return_problem()
            return ('refused', problem) if problem else ('customer', location)
        within = self.env['warranty.backup.unit']._warranty_backup_location_within
        company = replacement.company_id
        accepted = replacement.return_location_id | company.warranty_repair_intake_location_id
        line = self.env['stock.move.line'].sudo().search(
            [('lot_id', '=', lot.id), ('state', '=', 'done'), ('picking_id', '!=', False),
             ('location_id.usage', '=', 'customer')], order='date desc, id desc', limit=1)
        if not line or line.location_dest_id != location \
                or not any(within(location, parent) for parent in accepted):
            return 'refused', _("Old Serial %(serial)s is in %(location)s, which is not a validated "
                                "return to the Old Unit Location or the Warranty Repair Intake "
                                "Location: an inventory user must review it.", serial=lot.name,
                                location=location.display_name)
        picking = line.picking_id
        other = self.search([('return_picking_id', '=', picking.id), ('id', '!=', self.id),
                             ('state', 'in', ('submitted', 'approved', 'done'))], limit=1)
        if other:
            return 'refused', _("Return %(picking)s is already linked to replacement %(other)s.",
                                picking=picking.name, other=other.name)
        return 'reuse', picking

    def _warranty_replacement_open_return_problem(self):
        """No second return of this machine while another one is open."""
        self.ensure_one()
        replacement = self.sudo()
        lot = replacement.old_serial_id
        own = replacement.return_picking_id
        lines = self.env['stock.move.line'].sudo().search(
            [('lot_id', '=', lot.id), ('state', 'not in', ('done', 'cancel')),
             ('picking_id', '!=', False)])
        pickings = lines.picking_id
        pickings |= replacement.ticket_id.picking_ids.filtered(
            lambda picking: picking.state not in ('done', 'cancel')
            and replacement.product_id in picking.move_ids.product_id)
        pickings -= own
        if pickings:
            return _("Validate or cancel the open transfer %(pickings)s of serial %(serial)s "
                     "first.", pickings=', '.join(pickings.mapped('name')), serial=lot.name)
        return False

    def _warranty_replacement_unavailable_text(self):
        self.ensure_one()
        return _("New Serial %s is not available in the source location of the Replacement "
                 "Delivery Operation Type.", self.sudo().new_serial_id.name or '-')

    def _warranty_replacement_stock_problems(self):
        """Stock conditions of Submit; the final approval checks them again on the transfers."""
        self.ensure_one()
        problems = []
        if not self._warranty_replacement_new_serial_available():
            problems.append(self._warranty_replacement_unavailable_text())
        kind, value = self._warranty_replacement_old_position()
        if kind == 'refused' and self._warranty_replacement_policy_return_required():
            problems.append(value)
        return problems

    def _warranty_replacement_policy_return_required(self):
        """SRS 11 step 3: policy-based. SRS 11.1 Full Product: 'Old product returned', so a card
        without this setting needs the return."""
        self.ensure_one()
        return self.sudo().warranty_card_id.policy_id.replacement_return_required != 'not_required'

    def _warranty_replacement_raise(self, problems):
        self.ensure_one()
        if problems:
            raise UserError(_("Replacement %(ref)s:\n%(problems)s", ref=self.name,
                              problems='\n'.join('- %s' % problem for problem in problems)))

    def action_warranty_replacement_submit(self):
        """Replacement Recommended -> Manager / GM Approval (Figure 3); every problem at once."""
        self.ensure_one()
        self._warranty_replacement_check_coordinator()
        if self.state != 'draft':
            raise UserError(_("Replacement %s has already been submitted.", self.name))
        self._warranty_replacement_raise(self._warranty_replacement_type_problems())
        replacement = self.sudo()
        case = replacement.warranty_case_id
        # The case may have received its unit after this draft was created. Only a real change: a
        # write of the card recomputes the date policy chosen on this draft.
        if (replacement.warranty_card_id, replacement.warranty_unit_id) \
                != (case.warranty_card_id, case.warranty_unit_id):
            self._warranty_replacement_marked().sudo().write({
                'warranty_card_id': case.warranty_card_id.id,
                'warranty_unit_id': case.warranty_unit_id.id,
            })
        vals = {
            'product_id': replacement._warranty_replacement_target_product().id,
            'old_serial_id': replacement._warranty_replacement_active_serial().id,
        }
        if self.replacement_type == 'goodwill':
            vals.update(reason='goodwill', date_policy='manual')
        elif self.replacement_type == 'component':
            vals.update(date_policy='continue_original')
        self._warranty_replacement_marked().sudo().write(vals)
        component = self.replacement_type == 'component'
        problems = self._warranty_replacement_case_problems()
        if not self.warranty_unit_id or (not self.product_id and not component):
            self._warranty_replacement_raise(problems)
        if component:
            if not self.component_line_ids:
                problems.append(_("Add the components to replace."))
            problems += self.component_line_ids._warranty_component_request_problems()
        else:
            problems += self._warranty_replacement_new_serial_problems()
        problems += self._warranty_replacement_settings_problems()
        problems += self._warranty_replacement_date_problems()
        if not problems and not component:
            problems += self._warranty_replacement_stock_problems()
        self._warranty_replacement_raise(problems)
        company = replacement.company_id
        self._warranty_replacement_marked().sudo().write({
            'state': 'submitted',
            'requested_by_id': self.env.uid,
            'requested_date': fields.Datetime.now(),
            'finance_required': self._warranty_replacement_finance_applies()
            and company.warranty_replacement_full_finance == 'required',
            'return_required': bool(self.component_line_ids.filtered('return_required')) if component
            else self._warranty_replacement_policy_return_required(),
            'extension_base': company.warranty_replacement_extension_base
            if self.date_policy == 'fixed_extension' else False,
        })
        self._warranty_replacement_log(_(
            "Replacement %(ref)s submitted by %(user)s: serial %(old)s to %(new)s on %(unit)s. "
            "Reason: %(reason)s. Date policy: %(policy)s.", ref=self.name, user=self.env.user.name,
            old=replacement.old_serial_id.name or _("(component)"),
            new=replacement.new_serial_id.name or ', '.join(
                replacement.component_line_ids.product_id.mapped('display_name')),
            unit=replacement.warranty_unit_id.name,
            reason=dict(REPLACEMENT_REASONS)[self.reason],
            policy=dict(DATE_POLICIES)[self.date_policy]))
        if self.replacement_type == 'goodwill':
            self._warranty_replacement_log(_(
                "Goodwill exception on %(case)s: eligibility result %(result)s stays as checked "
                "(%(checked)s). Exception reason: %(reason)s.", case=case.name,
                result=dict(case._fields['eligibility_result']._description_selection(self.env))[
                    case.eligibility_result],
                checked=case.eligibility_reason or '-', reason=self.reason_note))
        self._warranty_replacement_approval_todo()
        return True

    def _warranty_replacement_pending_levels(self):
        self.ensure_one()
        levels = []
        if not self.gm_approved_by_id:
            levels.append('gm')
        if self.finance_required and not self.finance_approved_by_id:
            levels.append('finance')
        return levels

    def _warranty_replacement_level_users(self, level):
        company = self.sudo().company_id
        return company.warranty_replacement_gm_user_ids if level == 'gm' \
            else company.warranty_replacement_finance_user_ids

    def _warranty_replacement_levels_to_sign(self):
        """Separation of duties: never the submitter, and one person signs one level."""
        self.ensure_one()
        user = self.env.user
        if user in (self.requested_by_id, self.gm_approved_by_id, self.finance_approved_by_id):
            return []
        return [level for level in self._warranty_replacement_pending_levels()
                if user in self._warranty_replacement_level_users(level)]

    def _warranty_replacement_level_label(self, level):
        self.ensure_one()
        if not self._warranty_replacement_finance_applies():
            return _("Manager / GM")
        return {'gm': _("GM"), 'finance': _("Finance")}[level]

    def _warranty_replacement_approval_todo(self):
        self.ensure_one()
        levels = self._warranty_replacement_pending_levels()
        users = self.env['res.users']
        for level in levels:
            users |= self._warranty_replacement_level_users(level)
        users -= self.requested_by_id | self.gm_approved_by_id | self.finance_approved_by_id
        self._warranty_replacement_todo(
            _("approval needed (%s)", ' + '.join(
                self._warranty_replacement_level_label(level) for level in levels)),
            _("Review the replacement, then use Approve or Reject."), users=users)

    def action_warranty_replacement_approve(self):
        """One signature per click. The final signature re-checks the stock and creates the return
        and the replacement delivery (SRS 14)."""
        self.ensure_one()
        self._warranty_replacement_lock()
        if self.state != 'submitted':
            raise UserError(_("Replacement %s is not waiting for approval.", self.name))
        levels = self._warranty_replacement_levels_to_sign()
        if not levels:
            raise AccessError(_("Only a replacement approver of the company, other than the "
                                "submitter and the earlier signer, can approve %s.", self.name))
        self._warranty_replacement_raise(self._warranty_replacement_manual_date_problems()
                                         + self._warranty_replacement_date_problems())
        level = levels[0]
        vals = {'%s_approved_by_id' % level: self.env.uid,
                '%s_approved_date' % level: fields.Datetime.now()}
        # sudo: the approver may have no Warranty, Helpdesk or Inventory rights.
        self.sudo()._warranty_replacement_marked().write(vals)
        if not self._warranty_replacement_finance_applies():
            self._warranty_replacement_log(_(
                "Replacement %(ref)s: decision Approved. %(level)s approval by %(user)s on %(date)s.",
                ref=self.name, level=self._warranty_replacement_level_label(level),
                user=self.env.user.name, date=format_datetime(self.env, vals['gm_approved_date'])))
        else:
            self._warranty_replacement_log(_(
                "Replacement %(ref)s: %(level)s approval by %(user)s.", ref=self.name,
                level=self._warranty_replacement_level_label(level), user=self.env.user.name))
        if self._warranty_replacement_pending_levels():
            self._warranty_replacement_approval_todo()
            return True
        self._warranty_replacement_finish_approval()
        return True

    def _warranty_replacement_finish_approval(self):
        self.ensure_one()
        replacement = self.sudo()
        problems = self._warranty_replacement_case_problems()
        if self.replacement_type != 'component':
            problems += self._warranty_replacement_new_serial_problems()
        self._warranty_replacement_raise(problems)
        replacement._warranty_replacement_marked().write({'state': 'approved'})
        self._warranty_replacement_log(_("Replacement %(ref)s approved.", ref=self.name))
        replacement._warranty_replacement_create_transfers()

    def action_warranty_replacement_create_transfers(self):
        """Creates again a cancelled return or delivery, nothing else: an open or validated
        transfer is kept, so a second click creates nothing. Inventory users only."""
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_user'):
            raise AccessError(_("Only Inventory users can create replacement transfers."))
        self._warranty_replacement_lock()
        if self.state != 'approved':
            raise UserError(_("Replacement %s is not Approved.", self.name))
        self._warranty_replacement_raise(self._warranty_replacement_approval_missing_problems())
        if self.transfers_missing:
            self.sudo()._warranty_replacement_create_transfers()
        return True

    def _warranty_replacement_create_transfers(self):
        """SRS 14. Existing validated return of this exact serial and location: linked, no second
        transfer. sudo by the callers: the approver may have no Inventory rights. A Component
        replacement has a return per line and no delivery: the Material Request issues the part."""
        self.ensure_one()
        if self.replacement_type == 'component':
            self._warranty_replacement_create_component_returns()
            self._warranty_replacement_next_stock_todo()
            return
        marked = self._warranty_replacement_marked()
        if not self._warranty_replacement_active(self.return_picking_id):
            kind, value = self._warranty_replacement_old_position()
            if kind == 'reuse':
                marked.write({'return_picking_id': value.id, 'return_reused': True})
                self._warranty_replacement_log(_(
                    "Replacement %(ref)s: serial %(serial)s was already received by %(picking)s; "
                    "no second return is created.", ref=self.name,
                    serial=self.old_serial_id.name, picking=value.name))
            elif not self.return_required:
                if not self.delivery_picking_id:  # once: not when a delivery is created again
                    self._warranty_replacement_log(_(
                        "Replacement %(ref)s: the Warranty Policy needs no return; serial "
                        "%(serial)s is recorded as not returned.", ref=self.name,
                        serial=self.old_serial_id.name))
            elif kind == 'refused':
                self._warranty_replacement_raise([value])
            else:
                marked.write({'return_picking_id': self._warranty_replacement_create_return(value).id,
                              'return_reused': False})
        if not self._warranty_replacement_active(self.delivery_picking_id):
            if not self._warranty_replacement_new_serial_available():
                self._warranty_replacement_raise([self._warranty_replacement_unavailable_text()])
            marked.write({'delivery_picking_id': self._warranty_replacement_create_delivery().id})
        self._warranty_replacement_next_stock_todo()

    @api.model
    def _warranty_replacement_active(self, picking):
        return bool(picking) and picking.state != 'cancel'

    def _warranty_replacement_create_return(self, location):
        """Standard transfer from the customer: no sale line and no origin move, so the Sales Order
        quantities, invoices and delivery history stay as they are. A customer location reserves
        nothing, so the exact serial is set on the move line."""
        self.ensure_one()
        picking_type = self.company_id.warranty_replacement_return_type_id
        lot = self.old_serial_id
        picking = self._warranty_replacement_create_picking(
            picking_type, location, self.return_location_id)
        move = picking.move_ids
        line = move.move_line_ids[:1]
        if line:
            line.write({'lot_id': lot.id, 'quantity': 1.0})
        else:
            self.env['stock.move.line'].create(dict(
                move._prepare_move_line_vals(quantity=1.0), lot_id=lot.id))
        return picking

    def _warranty_replacement_create_delivery(self):
        """Standard delivery of exactly the new serial, without a sale line. Odoo may reserve any
        serial on confirmation, so that reservation is released and this serial reserved."""
        self.ensure_one()
        picking_type = self.company_id.warranty_replacement_delivery_type_id
        partner = self.warranty_case_id.site_id or self.partner_id
        picking = self._warranty_replacement_create_picking(
            picking_type, picking_type.default_location_src_id,
            partner.with_company(self.company_id).property_stock_customer, partner=partner)
        move = picking.move_ids
        move._do_unreserve()
        if not move._update_reserved_quantity(1.0, move.location_id, lot_id=self.new_serial_id,
                                              strict=False):
            raise UserError(_("Serial %(serial)s of %(product)s is not available in %(location)s.",
                              serial=self.new_serial_id.name,
                              product=self.product_id.display_name,
                              location=move.location_id.display_name))
        move._recompute_state()
        return picking

    def _warranty_replacement_create_component_returns(self):
        """The standard return of each defective part, the same transfer as an old unit."""
        self.ensure_one()
        partner = self.warranty_case_id.site_id or self.partner_id
        location = partner.with_company(self.company_id).property_stock_customer
        for line in self.component_line_ids.filtered('return_required'):
            if self._warranty_replacement_active(line.return_picking_id):
                continue
            picking = self._warranty_replacement_create_picking(
                self.company_id.warranty_replacement_return_type_id, location,
                self.return_location_id, product=line.product_id, qty=line.qty)
            move = picking.move_ids
            move_line = move.move_line_ids[:1]
            values = {'lot_id': line.old_lot_id.id, 'quantity': line.qty}
            if move_line:
                move_line.write(values)
            else:
                self.env['stock.move.line'].create(dict(
                    move._prepare_move_line_vals(quantity=line.qty), **values))
            line.with_context(warranty_replacement_marker=_REPLACEMENT_MARKER).write(
                {'return_picking_id': picking.id})

    def _warranty_replacement_create_picking(self, picking_type, source, destination, partner=None,
                                             product=None, qty=1.0):
        self.ensure_one()
        product = product or self.product_id
        picking = self.env['stock.picking'].with_company(self.company_id).create({
            'picking_type_id': picking_type.id,
            'location_id': source.id,
            'location_dest_id': destination.id,
            'partner_id': (partner or self.warranty_case_id.site_id or self.partner_id).id,
            'origin': self.name,
            'move_ids': [(0, 0, {
                'name': self.name,
                'product_id': product.id,
                'product_uom': product.uom_id.id,
                'product_uom_qty': qty,
                'location_id': source.id,
                'location_dest_id': destination.id,
            })],
        })
        picking.action_confirm()
        return picking

    def _warranty_replacement_next_stock_todo(self):
        self.ensure_one()
        if self.replacement_type == 'component':
            self._warranty_replacement_todo(_("process the components"), _(
                "Create or link the Material Request, record the usage, validate the defective part "
                "returns, then use Complete Replacement."))
            return
        returned = self.sudo().return_picking_id
        delivery = self.sudo().delivery_picking_id
        if self.return_required and returned.state != 'done':
            self._warranty_replacement_todo(_("validate the return"), _(
                "Validate return %s of the old serial.", returned.name))
        elif delivery:
            self._warranty_replacement_todo(_("validate the delivery"), _(
                "Validate replacement delivery %s of the new serial.", delivery.name))

    def _warranty_replacement_may_reject(self):
        """Submitted; or Approved until the replacement delivery is validated. A company approver
        other than the submitter; on Indoor / Outdoor, a Manager / GM approver: they have no
        Finance level. Also the authority of the serial change."""
        self.ensure_one()
        replacement = self.sudo()
        user = self.env.user
        approvers = replacement.company_id.warranty_replacement_gm_user_ids
        if self._warranty_replacement_finance_applies():
            approvers |= replacement.company_id.warranty_replacement_finance_user_ids
        if user == self.requested_by_id or user not in approvers:
            return False
        if self.state == 'submitted':
            return True
        return self.state == 'approved' and replacement.delivery_picking_id.state != 'done'

    def action_warranty_replacement_reject(self):
        """Safe cancel. Open transfers are cancelled; a validated return is never reversed: the old
        unit stays where it is, the serial and dates do not change, and the old unit goes back with
        the standard Return of that transfer, or a new replacement reuses that return."""
        self.ensure_one()
        self._warranty_replacement_lock()
        if not self._warranty_replacement_may_reject():
            raise AccessError(_("Replacement %s cannot be rejected in this status, or by this "
                                "user.", self.name))
        reason = (self.rejection_reason or '').strip()
        if not reason:
            raise UserError(_("Enter the Rejection Reason."))
        replacement = self.sudo()
        used = replacement.component_line_ids.filtered('used_qty')
        if used:
            raise UserError(_("%s is already recorded as used on its Material Request: the "
                              "replacement can only be completed.",
                              ', '.join(used.product_id.mapped('display_name'))))
        for picking in replacement.delivery_picking_id | replacement.return_picking_id \
                | replacement.component_line_ids.return_picking_id:
            if picking.state not in ('done', 'cancel'):
                picking.action_cancel()
        replacement._warranty_replacement_marked().write({
            'state': 'rejected', 'rejected_by_id': self.env.uid,
            'rejected_date': fields.Datetime.now()})
        self._warranty_replacement_close_todos()
        self._warranty_replacement_log(_(
            "Replacement %(ref)s rejected by %(user)s: %(reason)s. The serials did not change.",
            ref=self.name, user=self.env.user.name, reason=reason))
        location = replacement._warranty_replacement_unresolved_location()
        if location:
            note = _("Old serial %(serial)s stays in %(location)s after validated transfer "
                     "%(picking)s. Send it back with the standard Return of that transfer, or "
                     "create a new replacement, which reuses that transfer.",
                     serial=replacement.old_serial_id.name, location=location.display_name,
                     picking=replacement.return_picking_id.name)
            self._warranty_replacement_log(note)
            self._warranty_replacement_todo(_("resolve the old unit"), note)
        return True

    def action_warranty_replacement_change_serial(self):
        """Resolves a new serial that cannot be delivered. The open delivery is cancelled before a
        delivery of the new serial is created, so only one can ever be validated. The approvals and
        the validated return stay as they are; the change is on the chatter of every record."""
        self.ensure_one()
        self._warranty_replacement_lock()
        if self.state != 'approved' or self.replacement_type == 'component' \
                or not self._warranty_replacement_may_reject():
            raise AccessError(_("The serial of replacement %s cannot be changed in this status, or "
                                "by this user.", self.name))
        self._warranty_replacement_raise(self._warranty_replacement_approval_missing_problems())
        replacement = self.sudo()
        serial = replacement.recovery_new_serial_id
        reason = (self.recovery_reason or '').strip()
        problems = []
        if not serial:
            problems.append(_("Select Change New Serial To."))
        elif serial == replacement.new_serial_id:
            problems.append(_("Serial %s is already the New Serial.", serial.name))
        if not reason:
            problems.append(_("Enter the Reason for Serial Change."))
        self._warranty_replacement_raise(problems)
        previous = replacement.new_serial_id
        cancelled = replacement.delivery_picking_id
        if cancelled.state not in ('done', 'cancel'):
            cancelled.action_cancel()
        marked = replacement._warranty_replacement_marked()
        marked.write({'new_serial_id': serial.id, 'recovery_new_serial_id': False,
                      'recovery_reason': False})
        # A refusal here rolls back the cancellation and the serial above.
        problems = self._warranty_replacement_new_serial_problems()
        if not self._warranty_replacement_new_serial_available():
            problems.append(self._warranty_replacement_unavailable_text())
        self._warranty_replacement_raise(problems)
        delivery = replacement._warranty_replacement_create_delivery()
        marked.write({'delivery_picking_id': delivery.id})
        self._warranty_replacement_log(_(
            "Replacement %(ref)s: new serial changed from %(previous)s to %(serial)s by %(user)s: "
            "%(reason)s. Delivery %(cancelled)s cancelled, delivery %(delivery)s created.",
            ref=self.name, previous=previous.name, serial=serial.name, user=self.env.user.name,
            reason=reason, cancelled=cancelled.name or '-', delivery=delivery.name))
        replacement._warranty_replacement_next_stock_todo()
        return True

    def _warranty_replacement_approval_missing_problems(self):
        """SRS 11.2, Figure 3: nothing executes on a request that reached Approved under the earlier
        no-approval version. The record stays as it is; an approver can reject it."""
        self.ensure_one()
        if not self.sudo().approval_missing:
            return []
        return [_("This Indoor / Outdoor request reached Approved without the Manager / GM approval "
                  "that is now mandatory, so it cannot continue. A Manager / GM approver can reject "
                  "it, then create a new request.")]

    # ------------------------------------------------------------------ component replacement
    def action_warranty_replacement_create_material_request(self):
        """The existing Create Material Request form of the case and its own approvals."""
        self.ensure_one()
        if self.replacement_type != 'component' or self.state != 'approved':
            raise UserError(_("Replacement %s is not an Approved Component replacement.", self.name))
        return self.warranty_case_id.action_create_material_request()

    def action_warranty_replacement_complete_component(self):
        """SRS 11.1: the part history is updated; serial, card, unit and dates do not change. The
        Material Request holds the stock issue and the cost, so no Replacement Cost is recorded."""
        self.ensure_one()
        self._warranty_replacement_check_coordinator()
        self._warranty_replacement_lock()
        if self.replacement_type != 'component' or self.state != 'approved':
            raise UserError(_("Replacement %s is not an Approved Component replacement.", self.name))
        replacement = self.sudo()
        self._warranty_replacement_raise(
            replacement.component_line_ids._warranty_component_completion_problems())
        unit = replacement.warranty_unit_id
        start, end = unit.start_date, unit.end_date
        replacement._warranty_replacement_marked().write({
            'state': 'done',
            'delivery_date': replacement.company_id._warranty_today(),
            'old_start_date': start, 'old_end_date': end,
            'new_start_date': start, 'new_end_date': end,
            'dates_changed': False,
        })
        history = '; '.join(line._warranty_component_history_text()
                            for line in replacement.component_line_ids)
        replacement.warranty_card_id._warranty_log_date_event('replacement', _(
            "Replacement %(ref)s (Component) on %(unit)s: %(history)s. Warranty dates did not change.",
            ref=self.name, unit=unit.name, history=history),
            old_start=start, old_end=end, new_start=start, new_end=end)
        self._warranty_replacement_log(_(
            "Replacement %(ref)s done: %(history)s. Serial, card, unit and warranty dates did not "
            "change.", ref=self.name, history=history))
        replacement._warranty_replacement_generate_card()
        return True

    # ------------------------------------------------------------------ optional vendor claim
    def _warranty_replacement_claim_problem(self, exclude=None):
        """Why this replacement cannot be claimed (False = it can): the conditions of a Material
        Request claim (V-1, V-7). Never a condition of the replacement itself."""
        self.ensure_one()
        replacement = self.sudo()
        if replacement.replacement_type != 'vendor' or replacement.state != 'done':
            return _("only a Done Vendor Replacement can be claimed")
        if not replacement.company_id.warranty_vendor_claim_enabled:
            return _("vendor claims are not enabled for the company")
        if not replacement.product_id.product_tmpl_id.warranty_vendor_claimable:
            return _("the product is not marked Vendor Claimable")
        if not replacement.replacement_cost_verified or replacement.currency_id.compare_amounts(
                replacement.replacement_cost, 0.0) <= 0:
            return _("no verified cost (stock valuation) of the replacement delivery")
        others = replacement.vendor_claim_line_ids.filtered('active_claim')
        if exclude:
            others -= exclude
        if others:
            return _("the replacement is already on vendor claim %s", others[0].claim_id.name)
        return False

    def _warranty_replacement_claim_partner(self):
        """(partner, source), in the order of a Material Request claim (C2): the supplier of the
        old serial, the Warranty Claim Partner of the product, its vendor list."""
        self.ensure_one()
        replacement = self.sudo()
        orders = replacement.old_serial_id.purchase_order_ids.filtered(
            lambda order: order.state in ('purchase', 'done'))
        if orders:
            return orders.sorted('id')[0].partner_id, 'supplier'
        template = replacement.product_id.product_tmpl_id
        if template.warranty_claim_partner_id:
            return template.warranty_claim_partner_id, 'manufacturer'
        sellers = replacement.product_id.seller_ids.filtered(
            lambda seller: seller.company_id in (replacement.company_id, self.env['res.company']))
        if sellers:
            return sellers[0].partner_id, 'pricelist'
        return self.env['res.partner'], False

    def action_warranty_replacement_create_vendor_claim(self):
        """A Draft claim of the existing workflow: the partner can be changed there, and nothing is
        posted. sudo: as the claim wizard; the claim checks its creator."""
        self.ensure_one()
        Claim = self.env['warranty.vendor.claim']
        replacement = self.sudo()
        replacement._warranty_replacement_lock()
        problem = replacement._warranty_replacement_claim_problem()
        if problem:
            raise UserError(_("Replacement %(ref)s: %(problem)s.", ref=self.name, problem=problem))
        if not Claim._is_coordinator():
            raise AccessError(_("Only Service Coordinators (Helpdesk users) and Requisition users "
                                "of the company create vendor claims."))
        partner, source = replacement._warranty_replacement_claim_partner()
        if not partner:
            raise UserError(_("Replacement %(ref)s: set the Warranty Claim Partner of %(product)s, "
                              "or its vendor, to create the claim.", ref=self.name,
                              product=replacement.product_id.display_name))
        reason = dict(REPLACEMENT_REASONS)[replacement.reason]
        claim = Claim.sudo().create({
            'company_id': replacement.company_id.id,
            'case_id': replacement.warranty_case_id.id,
            'partner_id': partner.id,
            'claim_type': 'manufacturer' if source == 'manufacturer' else 'vendor',
            'proposed_partner_id': partner.id,
            'partner_source': source,
            'failure_description': _("Replacement %(ref)s, old serial %(serial)s: %(reason)s. "
                                     "%(details)s", ref=replacement.name,
                                     serial=replacement.old_serial_id.name, reason=reason,
                                     details=replacement.reason_note or ''),
            'line_ids': [(0, 0, {'replacement_id': replacement.id, 'qty': 1.0,
                                 'lot_ids': [(6, 0, replacement.old_serial_id.ids)]})],
        })
        claim.with_env(self.env)._check_creator()
        self._warranty_replacement_log(_("Vendor claim %(claim)s created for replacement %(ref)s.",
                                         claim=claim.name, ref=self.name))
        return {'type': 'ir.actions.act_window', 'res_model': claim._name, 'res_id': claim.id,
                'view_mode': 'form', 'views': [(False, 'form')]}

    def action_view_vendor_claims(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_mrf.action_warranty_vendor_claim')
        action['domain'] = [('id', 'in', self.sudo().vendor_claim_line_ids.claim_id.ids)]
        action['context'] = {'create': False}
        return action

    def _warranty_replacement_unresolved_location(self):
        """Where the old unit waits after a rejection that came after its return: the location, or
        empty once it is back at the customer or another replacement replaced it."""
        self.ensure_one()
        replacement = self.sudo()
        location = self.env['stock.location']
        lot = replacement.old_serial_id
        if replacement.state != 'rejected' or replacement.return_picking_id.state != 'done' \
                or lot not in replacement.warranty_unit_id.serial_ids:
            return location
        quants = self.env['stock.quant'].sudo().search([('lot_id', '=', lot.id),
                                                        ('quantity', '>', 0)])
        return quants.location_id.filtered(lambda place: place.usage != 'customer')[:1]

    def action_view_return_picking(self):
        self.ensure_one()
        return self._warranty_replacement_open_picking(self.return_picking_id)

    def action_view_delivery_picking(self):
        self.ensure_one()
        return self._warranty_replacement_open_picking(self.delivery_picking_id)

    def _warranty_replacement_open_picking(self, picking):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'res_id': picking.id,
        }

    # ------------------------------------------------------------------ picking validation
    @api.model
    def _warranty_replacement_of_pickings(self, pickings):
        # sudo: the warehouse user may not read the record; read for the checks and status only.
        return self.sudo().search(['|', ('return_picking_id', 'in', pickings.ids),
                                   ('delivery_picking_id', 'in', pickings.ids)])

    @api.model
    def _warranty_replacement_single_line(self, picking):
        lines = picking.move_line_ids.filtered('quantity')
        return lines if len(lines) == 1 else lines.browse()

    @api.model
    def _warranty_replacement_check_pickings(self, pickings):
        """Before any stock move (SRS 13, Figure 3): approved, exact serial, return before the
        delivery; the serials of an approved replacement move only on its own transfers."""
        lots = pickings.move_line_ids.filtered('quantity').lot_id
        if lots:
            others = self.sudo().search([('state', '=', 'approved'), '|',
                                         ('old_serial_id', 'in', lots.ids),
                                         ('new_serial_id', 'in', lots.ids)])
            for replacement in others:
                foreign = pickings - replacement.return_picking_id \
                    - replacement.delivery_picking_id
                serials = replacement.old_serial_id | replacement.new_serial_id
                if foreign.move_line_ids.filtered('quantity').lot_id & serials:
                    raise UserError(_(
                        "Serials of the approved replacement %s can only move with its own return "
                        "and delivery.", replacement.name))
        for replacement in self._warranty_replacement_of_pickings(pickings):
            if replacement.state == 'done':
                continue
            if replacement.state != 'approved':
                raise UserError(_("Replacement %(ref)s is %(state)s: its transfers cannot be "
                                  "validated.", ref=replacement.name,
                                  state=dict(REPLACEMENT_STATES)[replacement.state]))
            replacement._warranty_replacement_raise(
                replacement._warranty_replacement_approval_missing_problems())
            if replacement.delivery_picking_id in pickings:
                replacement._warranty_replacement_check_delivery()
            if not replacement.return_reused and replacement.return_picking_id in pickings:
                replacement._warranty_replacement_check_return()

    def _warranty_replacement_check_return(self):
        self.ensure_one()
        picking = self.return_picking_id
        line = self._warranty_replacement_single_line(picking)
        within = self.env['warranty.backup.unit']._warranty_backup_location_within
        if not line or line.lot_id != self.old_serial_id or line.quantity_product_uom != 1 \
                or line.location_id.usage != 'customer' \
                or not within(line.location_dest_id, self.return_location_id):
            raise UserError(_(
                "%(picking)s must move exactly one %(product)s, serial %(serial)s, from the "
                "customer to %(location)s (replacement %(ref)s).", picking=picking.name,
                product=self.product_id.display_name, serial=self.old_serial_id.name,
                location=self.return_location_id.display_name, ref=self.name))
        if not self.env['stock.quant'].search_count(
                [('lot_id', '=', self.old_serial_id.id), ('location_id', '=', line.location_id.id),
                 ('quantity', '>', 0)]):
            raise UserError(_("Serial %(serial)s is not at the customer location %(location)s.",
                              serial=self.old_serial_id.name,
                              location=line.location_id.display_name))

    def _warranty_replacement_check_delivery(self):
        self.ensure_one()
        picking = self.delivery_picking_id
        if self.return_required and self.return_picking_id.state != 'done':
            raise UserError(_(
                "Replacement %(ref)s: validate the return of old serial %(serial)s before the "
                "replacement delivery.", ref=self.name, serial=self.old_serial_id.name))
        line = self._warranty_replacement_single_line(picking)
        if not line or line.lot_id != self.new_serial_id or line.quantity_product_uom != 1 \
                or line.location_dest_id.usage != 'customer':
            raise UserError(_(
                "%(picking)s must deliver exactly one %(product)s, serial %(serial)s, to the "
                "customer (replacement %(ref)s).", picking=picking.name,
                product=self.product_id.display_name, serial=self.new_serial_id.name,
                ref=self.name))
        problems = self._warranty_replacement_case_problems() \
            + self._warranty_replacement_new_serial_problems() \
            + self._warranty_replacement_date_problems() \
            + self._warranty_replacement_manual_date_problems()
        self._warranty_replacement_raise(problems)

    @api.model
    def _warranty_replacement_after_pickings(self, pickings):
        """After validation: the return moves to the delivery step; the delivery runs the swap. An
        old unit of a rejected replacement that went back closes its To-Do."""
        lots = pickings.move_line_ids.filtered('quantity').lot_id
        if lots:
            for rejected in self.sudo().search([('state', '=', 'rejected'),
                                                ('old_serial_id', 'in', lots.ids)]):
                if not rejected._warranty_replacement_unresolved_location():
                    rejected._warranty_replacement_close_todos()
        replacements = self._warranty_replacement_of_pickings(pickings)
        if replacements:
            replacements._warranty_replacement_lock()
        for replacement in replacements.filtered(lambda record: record.state == 'approved'):
            if replacement.delivery_picking_id in pickings:
                replacement._warranty_replacement_complete()
            elif replacement.return_picking_id in pickings:
                replacement._warranty_replacement_log(_(
                    "Replacement %(ref)s: old serial %(serial)s received with %(picking)s.",
                    ref=replacement.name, serial=replacement.old_serial_id.name,
                    picking=replacement.return_picking_id.name))
                replacement._warranty_replacement_next_stock_todo()

    # ------------------------------------------------------------------ serial swap
    def _warranty_replacement_new_dates(self, start, end, delivery_date):
        """(start, end, remaining days) of the policy (SRS 11.3). Stage 1: the Unit Warranty; the
        card header keeps the original dates and no free service is recalculated."""
        self.ensure_one()
        policy = self.date_policy
        card = self.warranty_card_id
        remaining = 0
        if policy == 'restart':
            return delivery_date, card._get_warranty_end_date(delivery_date), remaining
        if policy == 'remaining_period':
            return start, end, max((end - delivery_date).days, 0)
        if policy == 'fixed_extension':
            base = end if self.extension_base == 'original_end' else delivery_date
            return start, base + relativedelta(**{self.extension_unit: self.extension_value}), \
                remaining
        if policy == 'manual':
            return start, self.manual_end_date, remaining
        return start, end, remaining

    def _warranty_replacement_complete(self):
        """Figure 3: Update Warranty Card Current Serial, Preserve History + Date Policy,
        Regenerate Updated Soft Copy Card. Same card and unit numbers. Runs in the transaction of
        the delivery validation, so the stock and the swap succeed or fail together."""
        self.ensure_one()
        unit = self.warranty_unit_id
        card = self.warranty_card_id
        picking = self.delivery_picking_id
        delivery_date = self.company_id._warranty_local_date(picking.date_done)
        old_start, old_end = self._warranty_replacement_current_dates()
        new_start, new_end, remaining = self._warranty_replacement_new_dates(
            old_start, old_end, delivery_date)
        marked_unit = unit.with_context(warranty_replacement_marker=_REPLACEMENT_MARKER)
        if self.replacement_type in ROLE_FIELDS:
            vals = {ROLE_FIELDS[self.replacement_type]: self.new_serial_id.id}
            if (old_start, old_end) != (new_start, new_end):
                start_field, end_field = ROLE_DATE_FIELDS[self.replacement_type]
                vals.update({start_field: new_start, end_field: new_end})
            # The kit write path keeps serial_ids and the serials of a single-unit card in sync.
            # The dates of the unit, the other serial and its dates are not written.
            marked_unit.with_context(warranty_kit_allocation=True).write(vals)
        else:
            marked_unit._warranty_system_write({
                'serial_ids': [Command.set(self.new_serial_id.ids)],
                'start_date': new_start,
                'end_date': new_end,
            })
        # Same source as the Material Request cost: the valuation layers of the done move.
        cost, verified = self.env['material.purchase.requisition.line']._warranty_move_value(
            picking.move_ids.filtered(lambda move: move.state == 'done'))
        self._warranty_replacement_marked().write({
            'state': 'done',
            'replacement_cost': cost,
            'replacement_cost_verified': verified,
            'delivery_date': delivery_date,
            'old_start_date': old_start,
            'old_end_date': old_end,
            'new_start_date': new_start,
            'new_end_date': new_end,
            'dates_changed': (old_start, old_end) != (new_start, new_end),
            'remaining_days': remaining,
        })

        def show(value):
            return format_date(self.env, value) if value else '-'

        card._warranty_log_date_event('replacement', _(
            "Replacement %(ref)s (%(type)s) on %(unit)s: serial %(old)s replaced by %(new)s, "
            "delivered with %(picking)s. Warranty dates %(old_start)s - %(old_end)s -> %(start)s - "
            "%(end)s (%(policy)s).", ref=self.name,
            type=dict(REPLACEMENT_TYPES)[self.replacement_type], unit=unit.name,
            old=self.old_serial_id.name,
            new=self.new_serial_id.name, picking=picking.name, old_start=show(old_start),
            old_end=show(old_end), start=show(new_start), end=show(new_end),
            policy=dict(DATE_POLICIES)[self.date_policy]),
            old_start=old_start, old_end=old_end, new_start=new_start, new_end=new_end,
            picking_id=picking.id, reason=self.manual_date_reason or False)
        self._warranty_replacement_log(_(
            "Replacement %(ref)s done: %(unit)s now has serial %(new)s (old serial %(old)s kept in "
            "the history). Replacement cost: %(cost)s.", ref=self.name, unit=unit.name,
            new=self.new_serial_id.name, old=self.old_serial_id.name, cost=cost))
        if self.unaffected_serial_id:
            self._warranty_replacement_log(_(
                "Replacement %(ref)s: serial %(serial)s and its warranty dates did not change.",
                ref=self.name, serial=self.unaffected_serial_id.name))
        if self.dates_changed:
            card._warranty_restore_from_expiry(_("replacement %s", self.name))
        self._warranty_replacement_after_done()

    def _warranty_replacement_after_done(self):
        """The PDF cannot undo a validated delivery: a failure leaves Updated Card Generated empty,
        with a To-Do and a button to try again. Sharing with the customer is not built yet, so the
        To-Do asks for it."""
        self.ensure_one()
        self._warranty_replacement_generate_card()
        case = self.warranty_case_id
        self.env['warranty.backup.unit']._warranty_backup_replacement_done(case)
        for repair in case._warranty_active_repairs().filtered(
                lambda repair: case._warranty_replacement_covers(repair)):
            if case.open_service_job_id:
                repair._warranty_repair_close_todos()
            else:
                repair._warranty_repair_todo(_("complete the warranty case"), _(
                    "Replacement %s is done: use Complete Warranty Case.", self.name))

    def _warranty_replacement_generate_card(self):
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.warranty_card_id.sudo()._regenerate_soft_copy()
        except Exception:
            _logger.exception("Updated warranty card of replacement %s failed.", self.name)
            self._warranty_replacement_marked().write({'updated_card_generated': False})
            self._warranty_replacement_todo(_("generate the updated card"), _(
                "The updated warranty card could not be generated: use Generate Updated Card."))
            return False
        self._warranty_replacement_marked().write({'updated_card_generated': True})
        self._warranty_replacement_log(_(
            "Updated warranty card %(card)s generated for replacement %(ref)s.",
            card=self.warranty_card_id.name, ref=self.name))
        self._warranty_replacement_todo(_("share the updated card"), _(
            "Use Download PDF on warranty card %s and share it with the customer.",
            self.warranty_card_id.name))
        return True

    def action_warranty_replacement_generate_card(self):
        """Only after a failed generation. It rewrites the same protected PDF of the card (no second
        attachment, not a download) and changes no warranty data; a second click does nothing."""
        self.ensure_one()
        self._warranty_replacement_check_coordinator()
        self._warranty_replacement_lock()
        if self.state != 'done':
            raise UserError(_("Replacement %s is not Done.", self.name))
        if self.updated_card_generated:
            return True
        if self.sudo().warranty_card_id.state not in ('confirmed', 'expired'):
            raise UserError(_("Warranty card %s is no longer Confirmed: no updated card is "
                              "generated.", self.sudo().warranty_card_id.name))
        self.sudo()._warranty_replacement_generate_card()
        return True

    @api.model
    def _warranty_replacement_check_standard_return(self, wizard):
        """Standard Return button: never on replacement transfers or on a reused return, and no
        return of the ticket's machine while a replacement is waiting."""
        picking = wizard.picking_id
        linked = self.sudo().search(
            ['|', ('return_picking_id', '=', picking.id), ('delivery_picking_id', '=', picking.id),
             ('state', 'in', ('submitted', 'approved', 'done'))], limit=1)
        if linked:
            raise UserError(_("%(picking)s belongs to replacement %(ref)s: it cannot be returned "
                              "with the standard Return.", picking=picking.name, ref=linked.name))
        if wizard.ticket_id:
            waiting = self.sudo().search(
                [('warranty_case_id.helpdesk_ticket_id', '=', wizard.ticket_id.id),
                 ('replacement_type', '!=', 'component'),
                 ('state', 'in', ('submitted', 'approved'))], limit=1)
            if waiting:
                raise UserError(_("Replacement %s of this ticket is open: its old unit moves only "
                                  "with the replacement return.", waiting.name))
