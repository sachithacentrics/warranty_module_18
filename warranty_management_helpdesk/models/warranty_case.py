from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_amount, html2plaintext

from .warranty_service_entitlement import warranty_same_site

from odoo.addons.warranty_management.models.res_company import (
    FREE_SERVICE_SCOPE_MODES, get_valid_service_alert_users)


CASE_TYPES = [
    ('warranty_complaint', 'Warranty Complaint'),
    ('free_service', 'Free Service'),
    ('amc', 'AMC'),
    ('chargeable_inspection', 'Chargeable Inspection'),
    ('chargeable_repair', 'Chargeable Repair'),
    ('replacement', 'Replacement'),
    ('repeat_complaint', 'Reopen/Repeat Complaint'),
]
# Approved Part 3.5 Q29: case types counted as failures.
FAILURE_CASE_TYPES = ('warranty_complaint', 'replacement', 'repeat_complaint')
# SRS 10.4 Failure Category.
FAILURE_CATEGORIES = [
    ('electrical', 'Electrical'),
    ('mechanical', 'Mechanical'),
    ('refrigeration', 'Refrigeration'),
    ('installation', 'Installation'),
    ('misuse', 'Misuse'),
    ('other', 'Other'),
]
# Approved Part 3.6b: results that may be rejected (Q45) and the rejection reasons (Q46).
REJECTABLE_RESULTS = ('not_eligible', 'out_of_warranty', 'manual_review')
REJECTION_REASONS = [
    ('serial_mismatch', 'Serial Mismatch'),
    ('out_of_warranty', 'Out of Warranty'),
    ('not_covered', 'Not Covered / Excluded'),
    ('no_free_service', 'No Free Service Available'),
    ('customer_mismatch', 'Customer / Site Mismatch'),
    ('duplicate', 'Duplicate Complaint'),
    ('other', 'Other'),
]
# Approved Part 3.6c Q49: Chargeable Type of a converted case (original case type kept).
CHARGEABLE_TYPES = [
    ('inspection', 'Inspection'),
    ('repair', 'Repair'),
    ('excluded_items', 'Excluded Items'),
]
# Fields still written on a Rejected (final) case: chatter / activities only.
REJECTED_WRITABLE_PREFIXES = ('message_', 'activity_', 'website_message')
CASE_STATES = [
    ('new', 'New'),
    ('eligibility_checked', 'Eligibility Checked'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('chargeable', 'Chargeable'),
    ('job_created', 'Job Created'),
    ('in_progress', 'In Progress'),
    ('completed', 'Completed'),
    ('closed', 'Closed'),
]
ELIGIBILITY_RESULTS = [
    ('eligible', 'Eligible'),
    ('not_eligible', 'Not Eligible'),
    ('partial', 'Partial'),
    ('manual_review', 'Manual Review'),
    ('pending_payment', 'Pending Payment'),
    ('out_of_warranty', 'Out of Warranty'),
]

CHECKED_CASE_TYPES = ('warranty_complaint', 'free_service', 'replacement', 'repeat_complaint')
CHARGEABLE_CASE_TYPES = ('chargeable_inspection', 'chargeable_repair')
CHECKABLE_STATES = ('new', 'eligibility_checked')
# Cross-card service merge (approved D2 / D6): selection fields changeable before approval.
SELECTION_FIELDS = {'service_entitlement_ids', 'service_unit_ids'}
SELECTION_STATES = ('new', 'eligibility_checked')
SITE_CONFIRMATION_FIELDS = {'site_confirmed_partner_ids', 'site_confirmation_reason',
                            'site_confirmed_by_id', 'site_confirmed_date'}
PAYMENT_ELIGIBILITY = [
    ('not_required', 'Not Required'),
    ('pending', 'Pending'),
    ('passed', 'Passed'),
    ('failed', 'Failed'),
    ('waived', 'Waived'),
]
PAYMENT_HOLDS = [
    ('on_hold', 'On Hold'),
    ('pending_approval', 'Pending Approval'),
    ('blocked', 'Blocked'),
]
PAYMENT_STATE_PROBLEMS = {
    'in_payment': 'In Payment, not fully covered by the registered payments',
    'partial': 'Partially Paid',
    'not_paid': 'Not Paid',
    'blocked': 'Blocked',
    'reversed': 'Reversed (warranty sale refunded)',
}
CASE_PRIORITIES = [
    ('0', 'Low'),
    ('1', 'Normal'),
    ('2', 'High'),
    ('3', 'Urgent'),
]


class WarrantyCase(models.Model):
    """Warranty Case customer request / complaint handled through Helpdesk. Stage 3.1 creates the case and links the selected pending free services;
    the eligibility checks come in the next stages."""
    _name = 'warranty.case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Warranty Case'
    _order = 'id desc'

    name = fields.Char(string='Case No.', required=True, readonly=True, copy=False,
                       default='New')
    helpdesk_ticket_id = fields.Many2one(
        'helpdesk.ticket', string='Helpdesk Ticket', required=True, index=True,
        ondelete='restrict', tracking=True)
    partner_id = fields.Many2one(
        related='helpdesk_ticket_id.partner_id', string='Customer', store=True, index=True)
    commercial_partner_id = fields.Many2one(
        related='helpdesk_ticket_id.partner_id.commercial_partner_id')
    company_id = fields.Many2one(
        related='helpdesk_ticket_id.company_id', string='Company', store=True, index=True)
    site_id = fields.Many2one(
        'res.partner', string='Site', compute='_compute_from_ticket', store=True,
        readonly=False, domain="[('id', 'child_of', commercial_partner_id)]",
        help="Customer delivery address (child contact) where the service is requested.")
    case_type = fields.Selection(CASE_TYPES, string='Case Type', required=True, tracking=True)
    customer_complaint = fields.Text(
        string='Customer Complaint', compute='_compute_from_ticket', store=True,
        readonly=False)
    product_id = fields.Many2one(
        'product.product', string='Product', compute='_compute_from_ticket', store=True,
        readonly=False)
    serial_id = fields.Many2one(
        'stock.lot', string='Serial No.', compute='_compute_from_ticket', store=True,
        readonly=False,
        domain="[('product_id', '=', product_id)] if product_id else []")
    # Approved card selection fix: manual selection offers only Confirmed cards of the case
    # company / customer, product (card or unit product: multi-product cards) and serial (unit
    # serials, kit Indoor / Outdoor included); see _check_manual_card_unit.
    warranty_card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', compute='_compute_warranty_card_id',
        store=True, readonly=False, tracking=True,
        domain="[('state', '=', 'confirmed'), ('company_id', '=', company_id), "
               "('partner_id', 'child_of', commercial_partner_id)]"
               " + (['|', ('product_id', '=', product_id), "
               "('unit_warranty_ids.product_id', '=', product_id)] if product_id else [])"
               " + ([('unit_warranty_ids.serial_ids', 'in', [serial_id])] if serial_id else [])")
    warranty_unit_id = fields.Many2one(
        'warranty.unit', string='Unit Warranty', tracking=True,
        domain="([('warranty_card_id', '=', warranty_card_id)] if warranty_card_id else "
               "[('warranty_card_id.state', '=', 'confirmed'), "
               "('warranty_card_id.partner_id', 'child_of', commercial_partner_id), "
               "('company_id', '=', company_id)])"
               " + ([('product_id', '=', product_id)] if product_id else [])"
               " + ([('serial_ids', 'in', [serial_id])] if serial_id else [])",
        help="Unit warranty number of the serviced unit (SRS Helpdesk Warranty Panel).")
    warranty_basis = fields.Selection(related='warranty_card_id.warranty_basis')
    current_usage = fields.Float(
        string='Current Usage', digits=(16, 2), tracking=True,
        help="Usage-based warranty: current usage reading of the unit, compared with its "
             "usage limit by the eligibility check (0 = not provided).")
    usage_unit = fields.Selection(
        related='warranty_card_id.usage_unit', string='Usage Unit')
    priority = fields.Selection(
        CASE_PRIORITIES, string='Priority', compute='_compute_from_ticket', store=True,
        readonly=False, tracking=True)
    state = fields.Selection(
        CASE_STATES, string='Status', default='new', required=True, readonly=True,
        tracking=True, index=True)
    eligibility_result = fields.Selection(
        ELIGIBILITY_RESULTS, string='Eligibility Result', readonly=True, tracking=True)
    pending_service_ids = fields.Many2many(
        'warranty.service.entitlement', string='Pending Customer Services',
        compute='_compute_pending_service_ids',
        help="Pending free services of the customer, filtered by the case site, product and "
             "serial number.")
    service_entitlement_ids = fields.Many2many(
        'warranty.service.entitlement', 'warranty_case_service_entitlement_rel', 'case_id',
        'entitlement_id', string='Linked Free Services', tracking=True)
    merged_adhoc_request = fields.Boolean(
        string='Merged Ad-hoc Request',
        help="The case combines pending free services and an ad-hoc request.")
    merged_adhoc_description = fields.Text(string='Ad-hoc Request')
    # Free service UI shown only when the company's Warranty Scope Mode includes free
    # services (approved; display only, nothing stored).
    warranty_free_services_enabled = fields.Boolean(
        compute='_compute_warranty_free_services_enabled')

    @api.depends('company_id.warranty_scope_mode')
    def _compute_warranty_free_services_enabled(self):
        for record in self:
            record.warranty_free_services_enabled = \
                record.company_id.warranty_scope_mode in FREE_SERVICE_SCOPE_MODES
    # Approved Part 3.4 Q22: requested services / items, checked against the policy coverage.
    requested_item_ids = fields.Many2many(
        'warranty.coverage.item', 'warranty_case_coverage_item_rel', 'case_id', 'item_id',
        string='Requested Items', tracking=True,
        help="Services / items requested by the customer, checked against the Covered / "
             "Excluded Items of the warranty card's policy.")

    payment_eligibility = fields.Selection(
        PAYMENT_ELIGIBILITY, string='Payment Eligibility', readonly=True, tracking=True)
    payment_hold = fields.Selection(
        PAYMENT_HOLDS, string='Payment Hold', readonly=True, tracking=True,
        help="Payment indicator of the case: On Hold / Blocked until the payment conditions "
             "pass; Pending Approval until a payment exception is approved.")
    overdue_warning = fields.Char(
        string='Overdue Warning', compute='_compute_overdue_warning',
        help="Overdue customer invoices (same commercial customer and company), always shown; "
             "only informational when Payment Check Required is off.")
    payment_approval_requested_by_id = fields.Many2one(
        'res.users', string='Payment Exception Requested By', readonly=True, copy=False)
    payment_approval_activity_ids = fields.Many2many(
        'mail.activity', 'warranty_case_payment_activity_rel', 'case_id', 'activity_id',
        string='Payment Approval Activities', readonly=True, copy=False,
        context={'active_test': False})
    payment_waiver_user_id = fields.Many2one(
        'res.users', string='Payment Waiver Approved By', readonly=True, copy=False,
        tracking=True)
    payment_waiver_date = fields.Datetime(string='Payment Waiver Date', readonly=True, copy=False)
    payment_waiver_conditions = fields.Text(
        string='Waived Payment Conditions', readonly=True, copy=False,
        help="Payment conditions that failed when the exception was approved.")
    can_approve_payment = fields.Boolean(compute='_compute_can_approve_payment')

    failure_category = fields.Selection(
        FAILURE_CATEGORIES, string='Failure Category', tracking=True,
        help="Failure pattern reporting (optional, approved Q35).")
    repeated_failure_flag = fields.Boolean(
        string='Repeated Failure', readonly=True, tracking=True,
        help="Set by the latest repeated failure check: the failures of the physical unit "
             "within the policy period exceed the threshold (GM escalation trigger).")
    repeated_failure_count = fields.Integer(
        string='Failures in Period',
        help="Failures of the physical unit within the policy period at the latest check, "
             "this case included when it is a failure.")
    escalation_pending = fields.Boolean(
        string='Escalated - Pending Confirmation', readonly=True, tracking=True, copy=False)
    escalation_requested_by_id = fields.Many2one(
        'res.users', string='Escalation Requested By', readonly=True, copy=False)
    escalation_activity_ids = fields.Many2many(
        'mail.activity', 'warranty_case_escalation_activity_rel', 'case_id', 'activity_id',
        string='Escalation Activities', readonly=True, copy=False,
        context={'active_test': False})
    escalation_confirmed_by_id = fields.Many2one(
        'res.users', string='Warranty Confirmed By (Repeated Failure)', readonly=True,
        copy=False, tracking=True)
    escalation_confirmed_date = fields.Datetime(
        string='Warranty Confirmation Date', readonly=True, copy=False)
    can_confirm_escalation = fields.Boolean(compute='_compute_can_confirm_escalation')

    eligibility_checked_by_id = fields.Many2one(
        'res.users', string='Eligibility Checked By', readonly=True, copy=False,
        help="User who ran the latest Check Eligibility (cannot approve the case, Q40).")
    case_approved_by_id = fields.Many2one(
        'res.users', string='Approved By', readonly=True, copy=False, tracking=True)
    case_approved_date = fields.Datetime(string='Approval Date', readonly=True, copy=False)
    case_approval_activity_ids = fields.Many2many(
        'mail.activity', 'warranty_case_approval_activity_rel', 'case_id', 'activity_id',
        string='Case Approval Activities', readonly=True, copy=False,
        context={'active_test': False})
    can_approve_case = fields.Boolean(compute='_compute_can_approve_case')

    # Part 3.6b - claim rejection (approved Q44-Q48).
    rejection_reason = fields.Selection(
        REJECTION_REASONS, string='Rejection Reason', readonly=True, copy=False, tracking=True)
    rejection_note = fields.Text(string='Rejection Note', readonly=True, copy=False)
    rejected_by_id = fields.Many2one('res.users', string='Rejected By', readonly=True, copy=False)
    rejected_date = fields.Datetime(string='Rejection Date', readonly=True, copy=False)
    can_reject_case = fields.Boolean(compute='_compute_can_reject_case')

    # Part 3.6c - chargeable conversion and partial coverage (approved Q49-Q58).
    # Cross-card service merge (approved Option A, D4-D6): all cards of the linked services,
    # the units to service on them and the Helpdesk manager same-site confirmation.
    service_card_ids = fields.Many2many(
        'warranty.card', 'warranty_case_service_card_rel', 'case_id', 'card_id',
        string='Service Cards', compute='_compute_service_card_ids', store=True)
    service_unit_ids = fields.Many2many(
        'warranty.unit', 'warranty_case_service_unit_rel', 'case_id', 'unit_id',
        string='Units to Service', copy=False, domain="[('id', 'in', service_card_unit_ids)]")
    service_card_unit_ids = fields.Many2many('warranty.unit',
                                             compute='_compute_service_card_ids')
    site_confirmed_partner_ids = fields.Many2many(
        'res.partner', 'warranty_case_site_confirmed_rel', 'case_id', 'partner_id',
        string='Confirmed Same-Site Addresses', readonly=True, copy=False)
    site_confirmation_reason = fields.Text(string='Same-Site Reason', readonly=True, copy=False)
    site_confirmed_by_id = fields.Many2one('res.users', string='Same Site Confirmed By',
                                           readonly=True, copy=False)
    site_confirmed_date = fields.Datetime(string='Same Site Confirmed On', readonly=True,
                                          copy=False)
    chargeable_type = fields.Selection(CHARGEABLE_TYPES, string='Chargeable Type', readonly=True,
                                       copy=False, tracking=True)
    chargeable_converted_by_id = fields.Many2one('res.users', string='Converted By',
                                                 readonly=True, copy=False)
    chargeable_converted_date = fields.Datetime(string='Conversion Date', readonly=True,
                                                copy=False)
    excluded_item_ids = fields.One2many('warranty.case.excluded.item', 'case_id',
                                        string='Excluded Items', readonly=True)
    excluded_decision_pending = fields.Boolean(compute='_compute_excluded_decision_pending')
    sale_order_ids = fields.One2many('sale.order', 'warranty_case_id', string='Quotations',
                                     readonly=True)
    quotation_count = fields.Integer(compute='_compute_quotation_count')

    @api.depends('helpdesk_ticket_id')
    def _compute_from_ticket(self):
        for case in self:
            ticket = case.helpdesk_ticket_id
            case.site_id = ticket.warranty_site_id
            case.product_id = ticket.warranty_product_id
            case.serial_id = ticket.warranty_serial_id
            case.priority = ticket.priority or '1'
            case.customer_complaint = html2plaintext(ticket.description or '').strip() \
                or ticket.name

    @api.depends('service_entitlement_ids.warranty_card_id')
    def _compute_service_card_ids(self):
        for case in self:
            case.service_card_ids = case.service_entitlement_ids.warranty_card_id
            case.service_card_unit_ids = case.service_card_ids.unit_warranty_ids

    @api.depends('service_entitlement_ids')
    def _compute_warranty_card_id(self):
        for case in self:
            if not case.warranty_card_id:
                case.warranty_card_id = case.service_entitlement_ids.warranty_card_id[:1]

    @api.depends('partner_id', 'company_id')
    def _compute_overdue_warning(self):
        for case in self:
            case.overdue_warning = self._warranty_overdue_warning(case.partner_id, case.company_id)

    @api.depends_context('uid')
    @api.depends('payment_hold', 'payment_approval_requested_by_id',
                 'company_id.warranty_overdue_approver_ids')
    def _compute_can_approve_payment(self):
        for case in self:
            case.can_approve_payment = case.payment_hold == 'pending_approval' \
                and case._is_payment_approver()

    @api.depends_context('uid')
    @api.depends('escalation_pending', 'escalation_requested_by_id',
                 'company_id.warranty_escalation_user_ids')
    def _compute_can_confirm_escalation(self):
        for case in self:
            case.can_confirm_escalation = case.escalation_pending \
                and case._is_escalation_user()

    @api.depends_context('uid')
    @api.depends('state', 'eligibility_result', 'eligibility_checked_by_id', 'create_uid',
                 'company_id.warranty_case_approver_ids',
                 'company_id.warranty_case_approval_required')
    def _compute_can_approve_case(self):
        for case in self:
            case.can_approve_case = case.state == 'eligibility_checked' \
                and case.eligibility_result == 'eligible' and case._is_case_approver()

    @api.depends_context('uid')
    @api.depends('state', 'eligibility_result', 'eligibility_checked_by_id', 'create_uid',
                 'company_id.warranty_case_approver_ids',
                 'company_id.warranty_case_approval_required')
    def _compute_can_reject_case(self):
        for case in self:
            case.can_reject_case = case.state == 'eligibility_checked' \
                and case.eligibility_result in REJECTABLE_RESULTS and case._is_case_approver()

    @api.depends('eligibility_result', 'requested_item_ids', 'excluded_item_ids.customer_decision')
    def _compute_excluded_decision_pending(self):
        for case in self:
            items = case.excluded_item_ids.filtered(
                lambda item: item.coverage_item_id in case.requested_item_ids)
            case.excluded_decision_pending = case.eligibility_result == 'partial' and any(
                item.customer_decision in ('quotation_required', 'waiting') for item in items)

    @api.depends('sale_order_ids')
    def _compute_quotation_count(self):
        for case in self:
            # sudo: the count is shown to Helpdesk users without sales rights.
            case.quotation_count = len(case.sudo().sale_order_ids)

    def _case_approvers(self):
        """Users allowed to approve this case now (Q39 / Q40): the current Warranty Case
        Approval Users of the case company (valid internal users of that company), except the
        case creator and the user who ran the latest eligibility check."""
        self.ensure_one()
        users = self.company_id.warranty_case_approver_ids
        users = get_valid_service_alert_users(users, self.company_id)
        return users - self.create_uid - self.eligibility_checked_by_id

    def _is_case_approver(self, user=None):
        """Approve / Reject Case permission. Warranty Case Approval Required (company, default
        True): the current Warranty Case Approval Users except creator / latest checker. Off
        (approved S1 / S2): Helpdesk users and managers of the case company, creator and
        latest checker included."""
        self.ensure_one()
        user = user or self.env.user
        if self.company_id.warranty_case_approval_required:
            return user in self._case_approvers()
        return user.has_group('helpdesk.group_helpdesk_user') \
            and self.company_id in user.company_ids

    def _is_escalation_user(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        return user != self.escalation_requested_by_id \
            and user in self.company_id.warranty_escalation_user_ids

    def _is_payment_approver(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        return user != self.payment_approval_requested_by_id \
            and user in self.company_id.warranty_overdue_approver_ids

    @api.onchange('warranty_unit_id')
    def _onchange_warranty_unit_id(self):
        if self.warranty_unit_id:
            self.warranty_card_id = self.warranty_unit_id.warranty_card_id

    def _manual_card_unit_problems(self, card, unit):
        """Approved manual selection rules for a card / unit of this case."""
        self.ensure_one()
        problems = []
        if card:
            if card.state != 'confirmed':
                problems.append(_("warranty card %s is not Confirmed", card.name))
            if card.company_id != self.company_id:
                problems.append(_("warranty card %s belongs to another company", card.name))
            if card.partner_id.commercial_partner_id != self.commercial_partner_id:
                problems.append(_("warranty card %s belongs to another customer", card.name))
            if self.product_id and self.product_id not in (
                    card.product_id | card.unit_warranty_ids.product_id):
                problems.append(_("warranty card %(card)s does not cover product %(product)s",
                                  card=card.name, product=self.product_id.display_name))
            if self.serial_id and self.serial_id not in card.unit_warranty_ids.serial_ids:
                problems.append(_("serial number %(serial)s is not on warranty card %(card)s",
                                  serial=self.serial_id.name, card=card.name))
        if unit:
            if card and unit.warranty_card_id != card:
                problems.append(_("unit %(unit)s is not a unit of warranty card %(card)s",
                                  unit=unit.display_name, card=card.name))
            if self.product_id and unit.product_id != self.product_id:
                problems.append(_("unit %s is of another product", unit.display_name))
            if self.serial_id and self.serial_id not in unit.serial_ids:
                problems.append(_("serial number %(serial)s is not on unit %(unit)s",
                                  serial=self.serial_id.name, unit=unit.display_name))
        return problems

    @api.constrains('warranty_card_id', 'warranty_unit_id')
    def _check_manual_card_unit(self):
        """Server-side validation of manual / API card and unit assignments (approved fix).
        Not applied in superuser mode, which only server code can use: the Part 3.2 automatic
        lookup records the found card in that mode (also Draft / Expired cards for the Q8 / Q14
        results). A context flag would not be safe here, clients can send any context."""
        if self.env.su:
            return
        for case in self:
            unit = case.warranty_unit_id
            problems = case._manual_card_unit_problems(
                case.warranty_card_id or unit.warranty_card_id, unit)
            if problems:
                raise ValidationError(_("Invalid warranty card / unit on %(case)s: %(problems)s.",
                                        case=case.name, problems='; '.join(problems)))

    @api.onchange('product_id', 'serial_id', 'helpdesk_ticket_id')
    def _onchange_clear_incompatible_card(self):
        """Clear a manually selected card / unit that no longer matches."""
        if self.warranty_unit_id and self._manual_card_unit_problems(
                self.env['warranty.card'], self.warranty_unit_id):
            self.warranty_unit_id = False
        if self.warranty_card_id and self._manual_card_unit_problems(
                self.warranty_card_id, self.env['warranty.unit']):
            self.warranty_card_id = False
            self.warranty_unit_id = False

    @api.onchange('warranty_card_id')
    def _onchange_warranty_card_id(self):
        if self.warranty_unit_id.warranty_card_id != self.warranty_card_id:
            self.warranty_unit_id = False

    @api.depends('partner_id', 'company_id', 'site_id', 'product_id', 'serial_id')
    def _compute_pending_service_ids(self):
        Entitlement = self.env['warranty.service.entitlement']
        for case in self:
            case.pending_service_ids = Entitlement._warranty_pending_services(
                case.partner_id, case.company_id, case.site_id, case.product_id,
                case.serial_id)

    @api.constrains('helpdesk_ticket_id', 'site_id')
    def _check_customer_site(self):
        for case in self:
            if not case.partner_id:
                raise ValidationError(_(
                    "Set the customer on Helpdesk ticket %s before creating a warranty case.",
                    case.helpdesk_ticket_id.display_name))
            if case.site_id and case.site_id.commercial_partner_id \
                    != case.partner_id.commercial_partner_id:
                raise ValidationError(_(
                    "The site of warranty case %s must be an address of the customer %s.",
                    case.name, case.partner_id.display_name))

    @api.constrains('service_entitlement_ids')
    def _check_linked_services(self):
        """Linked free services must be pending services of the case customer (approved
        Q5) and not linked to another active case (approved C - additional rule)."""
        Entitlement = self.env['warranty.service.entitlement']
        for case in self:
            if not case.service_entitlement_ids:
                continue
            pending = Entitlement._warranty_pending_services(case.partner_id, case.company_id)
            for service in case.service_entitlement_ids:
                if service not in pending:
                    raise ValidationError(_(
                        "Free service %(service)s (%(card)s) is not a pending free service of "
                        "%(customer)s and cannot be linked.", service=service.name,
                        card=service.warranty_card_id.name, customer=case.partner_id.name))
                other = service._warranty_active_cases(exclude=case)
                if other:
                    raise ValidationError(_(
                        "Free service %(service)s is already linked to the active warranty case "
                        "%(other)s.", service=service.name, other=other[0].name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                ticket = self.env['helpdesk.ticket'].browse(vals.get('helpdesk_ticket_id'))
                vals['name'] = self.env['ir.sequence'].with_company(
                    ticket.company_id or self.env.company).next_by_code('warranty.case') or 'New'
        cases = super().create(vals_list)
        cases._sync_service_tickets()
        cases._warranty_sync_service_units()
        return cases

    def write(self, vals):
        # Approved Part 3.6b: a Rejected case is final (chatter / activities only).
        if any(not key.startswith(REJECTED_WRITABLE_PREFIXES) for key in vals) \
                and any(case.state == 'rejected' for case in self):
            raise UserError(_("A Rejected warranty case cannot be changed."))
        if SITE_CONFIRMATION_FIELDS & set(vals) and not self.env.su:
            raise UserError(_("The same-site confirmation is recorded with Confirm Same Site."))
        # Approved D2: the selection changes before approval only; a checked case is reset.
        if SELECTION_FIELDS & set(vals) \
                and any(case.state not in SELECTION_STATES for case in self):
            raise UserError(_("Linked free services and units to service can only be changed "
                              "while the warranty case is New or Eligibility Checked."))
        to_reset = self.filtered(lambda case: case.state == 'eligibility_checked') \
            if SELECTION_FIELDS & set(vals) else self.browse()
        previous = self.service_entitlement_ids
        result = super().write(vals)
        if 'service_entitlement_ids' in vals or 'helpdesk_ticket_id' in vals:
            self._sync_service_tickets(previous - self.service_entitlement_ids)
        if 'service_entitlement_ids' in vals:
            self._warranty_sync_service_units()
        to_reset._warranty_reset_eligibility(_("linked free services / units to service changed"))
        return result

    def _warranty_sync_service_units(self):
        """Units to Service (approved D4): units of the linked services' cards only; units of a
        newly linked card are all added (single-unit card: its unit); the user may remove units
        of multi-unit cards."""
        for case in self:
            cards = case.service_entitlement_ids.warranty_card_id
            keep = case.service_unit_ids.filtered(lambda unit: unit.warranty_card_id in cards)
            add = (cards - keep.warranty_card_id).unit_warranty_ids
            if keep | add != case.service_unit_ids:
                super(WarrantyCase, case).write({'service_unit_ids': [(6, 0, (keep | add).ids)]})

    def _warranty_reset_eligibility(self, reason):
        """Approved D2: back to New, approval / payment approval activities closed, check and
        approval required again; the change is logged."""
        for case in self:
            steps = case._close_case_approval_activities(_("Case changed: %s", reason))
            case._close_payment_approval_activities(_("Case changed: %s", reason))
            super(WarrantyCase, case).write({'state': 'new', 'eligibility_result': False})
            lines = Markup('').join(Markup('<li>%s</li>') % text for __, text in steps)
            case._message_log(body=Markup('<p><b>%s</b></p><ul>%s</ul>') % (_(
                "Eligibility reset by %(user)s: %(reason)s. Linked free services: %(services)s. "
                "Check eligibility and approve again.", user=self.env.user.name, reason=reason,
                services=', '.join(case.service_entitlement_ids.mapped('name')) or '-'), lines))

    def _warranty_reference_site(self):
        self.ensure_one()
        # sudo: the delivery address of the warranty sale is read only.
        return self.site_id or self.warranty_card_id.sudo().sale_order_id.partner_shipping_id

    def _warranty_site_ok(self, address):
        """Approved D6: same address record, identical normalized address of the same customer,
        or an address confirmed for this case by a Helpdesk manager."""
        self.ensure_one()
        return warranty_same_site(address, self._warranty_reference_site()) \
            or (address in self.site_confirmed_partner_ids
                and address.commercial_partner_id == self.partner_id.commercial_partner_id)

    def _warranty_service_card_problems(self, card):
        """Per-card checks of the linked free services (approved Option A, D1, D3-D6):
        [(result, reason)]."""
        self.ensure_one()
        labels = dict(card._fields['state']._description_selection(self.env))
        if card.company_id != self.company_id \
                or card.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id:
            return [('not_eligible', _("other customer or company"))]
        if card.state != 'confirmed':
            return [('manual_review' if card.state in ('draft', 'ready') else 'not_eligible',
                     _("warranty card is %s", labels[card.state]))]
        problems = []
        units = self.service_unit_ids.filtered(lambda unit: unit.warranty_card_id == card)
        if not units:
            problems.append(('manual_review', _("select the units to service (Units to Service)")))
        # sudo: the delivery address of the warranty sale is read only.
        address = card.sudo().sale_order_id.partner_shipping_id
        if not self._warranty_site_ok(address):
            problems.append(('manual_review', _(
                "service address %(address)s is not the case site %(site)s (a Helpdesk manager "
                "can Confirm Same Site)", address=address.display_name or '-',
                site=self._warranty_reference_site().display_name or '-')))
        if card.warranty_basis == 'usage':
            if card != self.warranty_card_id:
                problems.append(('manual_review', _(
                    "usage-based warranty: its usage is checked on a case of its own")))
        else:
            check_date = self._warranty_check_date()
            for unit in units or card.unit_warranty_ids[:1]:
                start = unit.start_date or card.warranty_start_date
                end = unit.end_date or card.warranty_end_date
                if not start or not end or not start <= check_date <= end:
                    problems.append(('not_eligible', _(
                        "%(unit)s: ticket date %(date)s outside the warranty period %(start)s - "
                        "%(end)s", unit=unit.name, date=check_date, start=start or '?',
                        end=end or '?')))
        return problems

    def _warranty_window_problems(self, services):
        """Approved D3: the service windows of the selected services must overlap, and not end
        before today."""
        self.ensure_one()
        windows = {service: service._warranty_service_window() for service in services}
        windows = {service: window for service, window in windows.items() if window}
        # Flexible service dates (BA-approved K2): a single service is checked too.
        flexible = any(service._warranty_allowed_range() for service in windows)
        if len(windows) < 2 and not (flexible and windows):
            return []
        earliest = max(window[0] for window in windows.values())
        latest = min(window[1] for window in windows.values())
        if earliest <= latest and latest >= self.company_id._warranty_today():
            return []
        hint = _(" A Helpdesk user can Request Late Service Exception for a service whose policy "
                 "allows it.") if any(service.late_service_handling == 'approval'
                                      for service in windows) else ''
        if len(windows) == 1:
            (service, window), = windows.items()
            return [_("The permitted service dates of %(service)s (%(start)s - %(end)s) have "
                      "ended.%(hint)s", service=service.name, start=window[0], end=window[1],
                      hint=hint)]
        return [_("The service windows do not overlap (no common feasible date): %(windows)s."
                  "%(hint)s", windows='; '.join('%s %s - %s' % (service.name, window[0], window[1])
                                                for service, window in windows.items()),
                  hint=hint)]

    def action_open_late_service_wizard(self):
        """Request Late Service Exception for a linked free service (BA-approved F5)."""
        self.ensure_one()
        return self.env['warranty.service.date.exception.wizard']._warranty_open(
            self.service_entitlement_ids, case=self)

    def action_open_site_wizard(self):
        self.ensure_one()
        self._warranty_check_site_confirmation()
        if not self._warranty_site_candidates():
            raise UserError(_("All service addresses of %(case)s already match the case site "
                              "%(site)s: no same-site confirmation is needed.", case=self.name,
                              site=self._warranty_reference_site().display_name or '-'))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Confirm Same Site"),
            'res_model': 'warranty.case.site.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_case_id': self.id},
        }

    def _warranty_check_site_confirmation(self):
        if not self.env.user.has_group('helpdesk.group_helpdesk_manager'):
            raise AccessError(_("Only Helpdesk managers can confirm the same service site."))
        if self.state not in SELECTION_STATES:
            raise UserError(_("The same site is confirmed before approval (%s).", self.name))

    def _warranty_site_candidates(self):
        """Delivery addresses of the linked services' cards that are not matched yet."""
        self.ensure_one()
        # sudo: delivery addresses of the warranty sales are read only.
        addresses = self.service_entitlement_ids.warranty_card_id.sudo() \
            .sale_order_id.partner_shipping_id
        return addresses.filtered(lambda address: not self._warranty_site_ok(address))

    def _warranty_confirm_same_site(self, addresses, reason):
        """Confirm Same Site (approved D6 rule 3): Helpdesk managers, this case only, same
        customer and company, reason required; user / date / addresses / reason recorded."""
        self.ensure_one()
        self._warranty_check_site_confirmation()
        reason = (reason or '').strip()
        if not reason or not addresses:
            raise UserError(_("Select the addresses and give the reason."))
        allowed = self.service_entitlement_ids.warranty_card_id.sudo() \
            .sale_order_id.partner_shipping_id
        wrong = addresses.filtered(
            lambda address: address not in allowed
            or address.commercial_partner_id != self.partner_id.commercial_partner_id)
        if wrong:
            raise UserError(_("%s is not a service address of this case's free services and "
                              "customer.", ', '.join(wrong.mapped('display_name'))))
        reset = self.state == 'eligibility_checked'
        # sudo: the confirmation fields are written by this checked action only.
        self.sudo().write({
            'site_confirmed_partner_ids': [(4, address.id) for address in addresses],
            'site_confirmation_reason': reason,
            'site_confirmed_by_id': self.env.uid,
            'site_confirmed_date': fields.Datetime.now(),
        })
        self._message_log(body=Markup('<p><b>%s</b></p>') % _(
            "Same service site confirmed by %(user)s for %(addresses)s (site %(site)s). Reason: "
            "%(reason)s", user=self.env.user.name,
            addresses=', '.join(addresses.mapped('display_name')),
            site=self._warranty_reference_site().display_name or '-', reason=reason))
        if reset:
            self._warranty_reset_eligibility(_("same site confirmed"))
        return True

    def _sync_service_tickets(self, removed=None):
        """Helpdesk Ticket of the linked free services (Development Mapping field): the
        ticket of their active case; cleared when no active case links them any more."""
        for case in self:
            case.service_entitlement_ids.write({'helpdesk_ticket_id': case.helpdesk_ticket_id.id})
        for service in removed or self.env['warranty.service.entitlement']:
            active = service._warranty_active_cases()
            service.helpdesk_ticket_id = active[:1].helpdesk_ticket_id

    @api.ondelete(at_uninstall=False)
    def _unlink_except_processed(self):
        if any(case.state != 'new' for case in self):
            raise UserError(_("Only New warranty cases can be deleted."))

    def unlink(self):
        services = self.service_entitlement_ids
        result = super().unlink()
        for service in services.exists():
            service.helpdesk_ticket_id = service._warranty_active_cases()[:1].helpdesk_ticket_id
        return result

    @api.model
    def _warranty_find_card(self, partner, company, product=None, serial=None, card=None,
                            unit=None):
        """Find Warranty Card / Unit Warranty (approved Part 3.2) for `partner` (commercial
        entity) in `company`: the selected unit, else the selected / linked card, else the
        unit holding `serial` (unit serials, kit Indoor / Outdoor too), else the card of
        `product`. Returns (card, unit, problem); problem is 'not_found' or 'multiple' (Q12:
        never an arbitrary card)."""
        Card, Unit = self.env['warranty.card'], self.env['warranty.unit']
        if not partner or not company:
            return Card, Unit, 'not_found'
        commercial = partner.commercial_partner_id

        def owned(record):
            return record.company_id == company \
                and record.partner_id.commercial_partner_id == commercial

        if unit:
            card = unit.warranty_card_id
            return (card, unit, None) if owned(card) else (Card, Unit, 'not_found')
        if card:
            if not owned(card):
                return Card, Unit, 'not_found'
            units = card.unit_warranty_ids
            if serial:
                units = units.filtered(lambda u: serial in u.serial_ids)
            return card, units if len(units) == 1 else Unit, None
        domain = [('company_id', '=', company.id),
                  ('warranty_card_id.partner_id', 'child_of', commercial.id)]
        if serial:
            units = Unit.search(domain + [('serial_ids', 'in', serial.ids)])
            if len(units) > 1:
                return Card, Unit, 'multiple'
            if units:
                return units.warranty_card_id, units, None
            return Card, Unit, 'not_found'
        if product:
            units = Unit.search(domain + [('product_id', '=', product.id)])
            cards = units.warranty_card_id | Card.search([
                ('company_id', '=', company.id), ('partner_id', 'child_of', commercial.id),
                ('product_id', '=', product.id)])
            if len(cards) > 1:
                return Card, Unit, 'multiple'
            if cards:
                card_units = units.filtered(lambda u: u.warranty_card_id == cards)
                return cards, card_units if len(card_units) == 1 else Unit, None
        return Card, Unit, 'not_found'

    def action_check_eligibility(self):
        """ warranty card, serial number and validity check the steps run in order and stop at the first failure (Manual Review / Not
        Eligible / Out of Warranty). All passed: the result stays empty, the payment,
        coverage and repeated failure checks follow (3.3-3.5). Every run is logged in the
        chatter."""
        for case in self:
            if case.state not in CHECKABLE_STATES:
                raise UserError(_("The eligibility of %s can only be checked while it is New or "
                                  "Eligibility Checked.", case.name))
            if case.case_type in CHARGEABLE_CASE_TYPES:
                raise UserError(_("%s is a chargeable case: it follows the chargeable workflow, "
                                  "not the warranty eligibility check.", case.name))
            result, steps, payment_vals, failure_vals = case._warranty_run_checks()
            case.write(dict(payment_vals, **failure_vals, state='eligibility_checked',
                            eligibility_result=result, eligibility_checked_by_id=self.env.uid))
            if not case.payment_hold == 'pending_approval':
                case._close_payment_approval_activities(_("Payment approval no longer needed"))
            if not case.escalation_pending:
                case._close_escalation_activities(_("Escalation no longer needed"))
            if result == 'eligible':
                steps += case._sync_case_approval_activities()
            else:
                steps += case._close_case_approval_activities(_(
                    "Approval no longer needed - eligibility result is no longer Eligible."))
            # Internal log note: no notification, no sender email needed.
            case._message_log(body=case._warranty_check_message(result, steps))
            case._warranty_after_eligibility_check(result, steps)
        return True

    def _warranty_after_eligibility_check(self, result, steps):
        """Extension point after each Check Eligibility run (result, [(passed, text)])."""
        self.ensure_one()

    def _warranty_run_checks(self):
        """All eligibility checks in diagram order (3.2-3.5). Returns (result, steps, payment
        values, repeated failure values)."""
        self.ensure_one()
        result, steps = self._warranty_check_card_validity()
        payment_vals = {'payment_eligibility': False, 'payment_hold': False}
        if not result:
            result, payment_vals = self._warranty_check_payment(steps)
        if not result:
            result = self._warranty_check_coverage(steps)
        if not result:
            result = self._warranty_check_free_service(steps)
        # Repeated failure flag / count: updated when the check is reached (Q36).
        failure_vals = {'escalation_pending': False}
        if not result:
            result, failure_vals = self._warranty_check_repeated_failure(steps)
        return result, steps, payment_vals, failure_vals

    def _warranty_check_card_validity(self):
        """Returns (eligibility result or False when all passed, [(passed, text)])."""
        self.ensure_one()
        steps = []
        if self.case_type == 'amc':
            steps.append((False, _("AMC case: AMC is handled outside the warranty module - "
                                   "manual review required.")))
            return 'manual_review', steps

        card, unit, problem = self._warranty_find_card(
            self.partner_id, self.company_id, self.product_id, self.serial_id,
            card=self.warranty_card_id, unit=self.warranty_unit_id)
        if problem == 'multiple':
            steps.append((False, _("Several warranty cards / units match the customer and "
                                   "product: select the Warranty Card or Unit Warranty and "
                                   "check again.")))
            return 'manual_review', steps
        if not card:
            steps.append((False, _("No warranty card found for the customer, product and "
                                   "serial number - chargeable inspection / manual review.")))
            return 'manual_review', steps
        # Approved: the automatic lookup records the found card in superuser mode, outside the
        # manual selection rules (Draft / Expired cards give the Q8 / Q14 results).
        self.sudo().write({'warranty_card_id': card.id, 'warranty_unit_id': unit.id})
        steps.append((True, _("Warranty card %(card)s found%(unit)s.", card=card.name,
                              unit=_(" (unit %s)", unit.name) if unit else '')))

        units = unit or card.unit_warranty_ids
        if self.serial_id:
            if self.serial_id not in units.serial_ids:
                steps.append((False, _("Serial number %s does not match the warranty card - "
                                       "serial mismatch / possible rejection.",
                                       self.serial_id.name)))
                return 'manual_review', steps
            steps.append((True, _("Serial number %s matches.", self.serial_id.name)))
        elif not self.product_id and self.service_unit_ids.filtered(
                lambda u: u.warranty_card_id == card):
            steps.append((True, _("Units to service on %(card)s: %(units)s.", card=card.name,
                                  units=', '.join(self.service_unit_ids.filtered(
                                      lambda u: u.warranty_card_id == card).mapped('name')))))
        elif any(u.product_id.tracking == 'serial' or u.serial_ids for u in units):
            steps.append((False, _("The serial number is required for this product: enter the "
                                   "Serial No. of the serviced unit and check again.")))
            return 'manual_review', steps
        else:
            steps.append((True, _("Product not tracked by serial number: serial check "
                                  "skipped.")))

        if card.state in ('draft', 'ready'):
            steps.append((False, _("Warranty card %s is not confirmed yet: confirm the warranty "
                                   "(Confirm Warranty) and check again.", card.name)))
            return 'manual_review', steps
        if card.state != 'confirmed':
            steps.append((False, _("Warranty card %(card)s is %(state)s: not eligible.",
                                   card=card.name, state=dict(card._fields['state']
                                   ._description_selection(self.env))[card.state])))
            return 'not_eligible', steps
        steps.append((True, _("Warranty card is active (Confirmed).")))

        if card.warranty_basis == 'usage':
            limit = (unit.usage_limit if unit else 0.0) or card.usage_limit
            unit_label = dict(card._fields['usage_unit']._description_selection(
                self.env)).get(card.usage_unit, '')
            if not self.current_usage:
                steps.append((False, _("Usage-based warranty: enter the Current Usage reading "
                                       "and check again.")))
                return 'manual_review', steps
            if limit <= 0:
                steps.append((False, _("Usage-based warranty without usage limit on %s - "
                                       "manual review.", card.name)))
                return 'manual_review', steps
            if self.current_usage > limit:
                steps.append((False, _("Current usage %(usage)s %(unit)s exceeds the usage "
                                       "limit %(limit)s %(unit)s: out of warranty.",
                                       usage=self.current_usage, limit=limit, unit=unit_label)))
                return 'out_of_warranty', steps
            steps.append((True, _("Current usage %(usage)s %(unit)s within the usage limit "
                                  "%(limit)s %(unit)s.", usage=self.current_usage,
                                  limit=limit, unit=unit_label)))
        else:
            check_date = self._warranty_check_date()
            start = (unit.start_date if unit else False) or card.warranty_start_date
            end = (unit.end_date if unit else False) or card.warranty_end_date
            if not start or not end or not start <= check_date <= end:
                steps.append((False, _("Ticket date %(date)s is outside the warranty period "
                                       "%(start)s - %(end)s: out of warranty.",
                                       date=check_date, start=start or '?', end=end or '?')))
                return 'out_of_warranty', steps
            steps.append((True, _("Ticket date %(date)s within the warranty period %(start)s - "
                                  "%(end)s.", date=check_date, start=start, end=end)))
        steps.append((True, _("Warranty card, serial number and validity passed - the payment "
                              "check follows.")))
        return False, steps

    def _warranty_check_date(self):
        """Approved Q10: the Helpdesk ticket creation date (user / company timezone)."""
        self.ensure_one()
        ticket = self.helpdesk_ticket_id
        return fields.Datetime.context_timestamp(ticket, ticket.create_date).date()

    def _warranty_check_message(self, result, steps):
        labels = dict(self._fields['eligibility_result']._description_selection(self.env))
        lines = Markup('').join(Markup('<li>%s %s</li>') % ('✔' if passed else '✘', text)
                                for passed, text in steps)
        title = _("Eligibility check (warranty card, serial, validity, payment, coverage, free "
                  "service, repeated failure): %s",
                  labels[result] if result else _("passed"))
        return Markup('<p><b>%s</b></p><ul>%s</ul>') % (title, lines)

    # ------------------------------------------------------------------ Part 3.3
    @api.model
    @api.model
    def _warranty_uncovered_amounts(self, invoices):
        """Outstanding amount of each customer invoice, in its currency (approved Q15 rev. B):
        Paid / Reversed = 0; In Payment = residual minus the registered payments linked to the
        invoice that have no journal entry yet (state In Process / Paid; a payment with a
        journal entry already reduces the residual once reconciled); otherwise the residual.
        A payment linked to several invoices is allocated once, by due date, never counted
        twice. Returns {invoice id: amount}."""
        amounts = {}
        pending = invoices.browse()  # keeps the (sudo) environment of the caller
        for invoice in invoices:
            if invoice.payment_state in ('paid', 'reversed'):
                amounts[invoice.id] = 0.0
            else:
                amounts[invoice.id] = invoice.amount_residual
                if invoice.payment_state == 'in_payment':
                    pending |= invoice
        payments = pending.matched_payment_ids.filtered(
            lambda pay: not pay.move_id and pay.state in ('in_process', 'paid')
            and pay.payment_type == 'inbound' and pay.partner_type == 'customer')
        # The other invoices of these payments take their share first when due earlier.
        need = {}
        for payment in payments.sorted('id'):
            available = payment.amount
            linked = payment.invoice_ids.filtered(
                lambda move: move.state == 'posted' and move.move_type == 'out_invoice'
                and move.payment_state == 'in_payment')
            for invoice in linked.sorted(lambda move: (move.invoice_date_due or move.date, move.id)):
                if payment.currency_id.compare_amounts(available, 0.0) <= 0:
                    break
                remaining = need.setdefault(invoice.id, invoice.amount_residual)
                if invoice.currency_id.is_zero(remaining):
                    continue
                convert = lambda amount, src, dst: src._convert(
                    amount, dst, invoice.company_id, payment.date)
                covered = min(remaining, convert(available, payment.currency_id,
                                                 invoice.currency_id))
                need[invoice.id] = remaining - covered
                available -= convert(covered, invoice.currency_id, payment.currency_id)
        for invoice in pending:
            uncovered = need.get(invoice.id, invoice.amount_residual)
            amounts[invoice.id] = 0.0 if invoice.currency_id.compare_amounts(
                uncovered, 0.0) <= 0 else uncovered
        return amounts

    def _warranty_overdue_invoices(self, partner, company):
        """Overdue receivables (approved Q15 (2), rev. B): posted customer invoices of the same
        commercial customer and company, due before today (company warranty timezone), with an
        outstanding amount (Paid, Reversed and fully covered In Payment invoices excluded).
        Returns (invoices, outstanding amount in company currency)."""
        Move = self.env['account.move']
        if not partner or not company:
            return Move, 0.0
        # sudo: the payment check reads the accounting status whatever the user's accounting
        # rights; only counts / amounts / references are shown.
        invoices = Move.sudo().search([
            ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
            ('commercial_partner_id', '=', partner.commercial_partner_id.id),
            ('company_id', '=', company.id),
            ('invoice_date_due', '<', company._warranty_today()),
            ('payment_state', 'not in', ('paid', 'reversed')),
        ])
        amounts = self._warranty_uncovered_amounts(invoices)
        overdue, total = invoices.browse(), 0.0
        for invoice in invoices:
            if not amounts[invoice.id]:
                continue
            overdue |= invoice
            # Company currency share of the invoice outstanding amount.
            rate = (invoice.amount_residual_signed / invoice.amount_residual
                    if invoice.amount_residual else 1.0)
            total += amounts[invoice.id] * rate
        return overdue, total

    @api.model
    def _warranty_overdue_warning(self, partner, company):
        invoices, total = self._warranty_overdue_invoices(partner, company)
        if not invoices:
            return False
        return _("Customer has %(count)s overdue invoice(s) (amount due %(amount)s)",
                 count=len(invoices), amount=format_amount(self.env, total, company.currency_id))

    def _warranty_payment_problems(self, card):
        """Failed payment conditions (approved Q15): (1) every posted customer invoice of the
        warranty sale is Paid; (2) no overdue receivables of the customer in the company."""
        self.ensure_one()
        problems = []
        # sudo: see _warranty_overdue_invoices.
        invoices = card.sudo()._get_posted_invoices()
        if not invoices:
            problems.append(_("No posted invoice for the warranty sale %s.",
                              card.sale_order_id.name or card.name))
        # Approved Q15 rev. B: Paid, or In Payment fully covered by the registered payments.
        uncovered = self._warranty_uncovered_amounts(invoices)
        for invoice in invoices.filtered(lambda move: move.payment_state != 'paid'
                                         and (move.payment_state != 'in_payment'
                                              or uncovered[move.id])):
            status = _(PAYMENT_STATE_PROBLEMS.get(invoice.payment_state, invoice.payment_state))
            if invoice.payment_state == 'in_payment':
                status += _(" (uncovered %s)", format_amount(
                    self.env, uncovered[invoice.id], invoice.currency_id))
            problems.append(_("Warranty sale invoice %(invoice)s is %(status)s.",
                              invoice=invoice.name, status=status))
        overdue = self._warranty_overdue_warning(self.partner_id, self.company_id)
        if overdue:
            problems.append(overdue + '.')
        return problems

    def _warranty_check_payment(self, steps):
        """Payment Check Required? -> invoice / payment / settlement -> Overdue Claim Handling
        (approved Q15-Q20). Returns (eligibility result or False to continue, payment values)."""
        self.ensure_one()
        card = self.warranty_card_id
        cards = card | self.service_entitlement_ids.warranty_card_id
        if len(cards) > 1:
            return self._warranty_check_payment_cards(steps, cards)
        policy = card.policy_id
        if not policy.payment_check_required:
            steps.append((True, _("Payment Check Required is off: payment eligibility Not "
                                  "Required.")))
            if self.overdue_warning:
                steps.append((True, _("Overdue Warning (information only): %s",
                                      self.overdue_warning)))
            return self._warranty_payment_continue(steps, 'not_required')
        problems = self._warranty_payment_problems(card)
        if not problems:
            steps.append((True, _("Warranty sale invoice(s) Paid or fully covered by registered "
                                  "payments and no overdue receivables: payment eligibility "
                                  "Passed.")))
            return self._warranty_payment_continue(steps, 'passed')
        for problem in problems:
            steps.append((False, problem))
        if self.payment_waiver_user_id:
            steps.append((True, _("Payment exception approved by %(user)s on %(date)s for this "
                                  "case: payment eligibility Waived.",
                                  user=self.payment_waiver_user_id.name,
                                  date=self.payment_waiver_date)))
            return self._warranty_payment_continue(steps, 'waived')
        handling = policy.overdue_claim_handling or 'warning'
        if handling == 'warning':
            steps.append((False, _("Overdue Claim Handling Warning Only: warning shown, the check "
                                   "continues.")))
            return self._warranty_payment_continue(steps, 'failed')
        if handling == 'hold':
            steps.append((False, _("Overdue Claim Handling Hold: the case is on hold until the "
                                   "payment conditions pass - check again after payment.")))
            return 'pending_payment', {'payment_eligibility': 'failed', 'payment_hold': 'on_hold'}
        if handling == 'block':
            steps.append((False, _("Overdue Claim Handling Block: warranty service is blocked "
                                   "until the payment conditions pass - check again after "
                                   "payment.")))
            return 'pending_payment', {'payment_eligibility': 'failed', 'payment_hold': 'blocked'}
        steps.append((False, self._request_payment_approval()))
        return 'pending_payment', {'payment_eligibility': 'pending',
                                   'payment_hold': 'pending_approval'}

    def _warranty_check_payment_cards(self, steps, cards):
        """Payment check of every participating card (approved Option A): each card with its
        own policy's Payment Check Required; problems named per card; the strictest Overdue
        Claim Handling of these policies applies; the case waiver covers the case."""
        checked = cards.filtered(lambda card: card.policy_id.payment_check_required)
        if not checked:
            steps.append((True, _("Payment Check Required is off for cards %s: payment "
                                  "eligibility Not Required.", ', '.join(cards.mapped('name')))))
            return self._warranty_payment_continue(steps, 'not_required')
        problems = []
        for card in checked:
            for problem in self._warranty_payment_problems(card):
                text = _("%(card)s: %(problem)s", card=card.name, problem=problem)
                if problem not in [raw for raw, __ in problems]:
                    problems.append((problem, text))
        if not problems:
            steps.append((True, _("Warranty sale invoices of %s Paid or fully covered and no "
                                  "overdue receivables: payment eligibility Passed.",
                                  ', '.join(checked.mapped('name')))))
            return self._warranty_payment_continue(steps, 'passed')
        for __, text in problems:
            steps.append((False, text))
        if self.payment_waiver_user_id:
            steps.append((True, _("Payment exception approved by %(user)s on %(date)s for this "
                                  "case: payment eligibility Waived.",
                                  user=self.payment_waiver_user_id.name,
                                  date=self.payment_waiver_date)))
            return self._warranty_payment_continue(steps, 'waived')
        rank = ['warning', 'approval', 'hold', 'block']
        handling = max((card.policy_id.overdue_claim_handling or 'warning' for card in checked),
                       key=rank.index)
        if handling == 'warning':
            steps.append((False, _("Overdue Claim Handling Warning Only: warning shown, the check "
                                   "continues.")))
            return self._warranty_payment_continue(steps, 'failed')
        if handling in ('hold', 'block'):
            steps.append((False, _("Overdue Claim Handling %s: check again after payment.",
                                   handling.capitalize())))
            return 'pending_payment', {'payment_eligibility': 'failed',
                                       'payment_hold': 'on_hold' if handling == 'hold'
                                       else 'blocked'}
        steps.append((False, self._request_payment_approval()))
        return 'pending_payment', {'payment_eligibility': 'pending',
                                   'payment_hold': 'pending_approval'}

    def _warranty_payment_continue(self, steps, eligibility):
        steps.append((True, _("Warranty card, serial, validity and payment checks done - the "
                              "coverage check follows.")))
        return False, {'payment_eligibility': eligibility, 'payment_hold': False}

    def _request_payment_approval(self):
        """Approval Required: one activity per configured approver (not the requester), no
        duplicates while open activities exist. Returns the chatter text."""
        self.ensure_one()
        if self.env.context.get('warranty_revalidation'):
            return _("Overdue Claim Handling Approval Required: not requested during the approval "
                     "revalidation - run Check Eligibility.")
        open_activities = self.payment_approval_activity_ids.exists().filtered('active')
        if open_activities:
            return _("Overdue Claim Handling Approval Required: approval already requested from "
                     "%s.", ', '.join(open_activities.user_id.mapped('name')))
        approvers = self.company_id.warranty_overdue_approver_ids - self.env.user
        self.write({'payment_approval_requested_by_id': self.env.uid})
        if not approvers:
            return _("Overdue Claim Handling Approval Required: no Overdue Claim Approval User "
                     "(other than you) is configured for %s.", self.company_id.name)
        activities = self.env['mail.activity']
        # The assignment email is sent from the requester: without an email address the
        # activities are still assigned (approvers see them in their activities), no email.
        case = self if self.env.user.email else self.with_context(mail_activity_quick_update=True)
        for approver in approvers:
            activities |= case.activity_schedule(
                'mail.mail_activity_data_todo', user_id=approver.id,
                summary=_("Approve payment exception of warranty case %s", self.name),
                note=self.overdue_warning or _("Warranty sale invoice not paid."))
        self.write({'payment_approval_activity_ids': [(4, a.id) for a in activities]})
        return _("Overdue Claim Handling Approval Required: approval requested from %s.",
                 ', '.join(approvers.mapped('name')))

    def _close_payment_approval_activities(self, feedback):
        activities = self.payment_approval_activity_ids.exists().filtered('active')
        if activities:
            # sudo: activities of the approvers are closed by the system.
            activities.sudo().action_feedback(feedback=feedback)

    def action_approve_payment_exception(self):
        """Approve the payment exception of this case only (approved Q18 / Q19): Payment
        Eligibility Waived, approver / date / failed conditions kept; Check Eligibility must be
        run again to continue."""
        for case in self:
            if case.payment_hold != 'pending_approval':
                raise UserError(_("No payment exception is waiting for approval on %s.",
                                  case.name))
            if self.env.user == case.payment_approval_requested_by_id:
                raise AccessError(_("You cannot approve your own payment exception request."))
            if not case._is_payment_approver():
                raise AccessError(_(
                    "Only the Overdue Claim Approval Users of %s can approve payment exceptions.",
                    case.company_id.name))
            conditions = '\n'.join(case._warranty_payment_problems(case.warranty_card_id))
            # sudo: approvers may not have edit rights on warranty cases.
            case.sudo().write({
                'payment_eligibility': 'waived',
                'payment_hold': False,
                'payment_waiver_user_id': self.env.uid,
                'payment_waiver_date': fields.Datetime.now(),
                'payment_waiver_conditions': conditions,
            })
            case._close_payment_approval_activities(_("Approved by %s", self.env.user.name))
            case.sudo()._message_log(body=Markup('<p><b>%s</b></p><p>%s</p>') % (
                _("Payment exception approved by %s", self.env.user.name),
                _("Run Check Eligibility again to continue.")))
        return True

    def _warranty_check_coverage(self, steps):
        """Check Requested Service / Item Coverage (approved Q22-Q24, Q27, Q28): every requested
        item must be a Covered Item of the card's policy. Partial (covered and excluded) and
        Not Eligible (only excluded) stop the check; undefined items, no requested items and a
        card without policy give Manual Review. Returns the result or False to continue."""
        self.ensure_one()
        policy = self.warranty_card_id.policy_id
        names = lambda items: ', '.join(items.mapped('name'))
        conflict = self._warranty_coverage_conflicts()
        if conflict:
            steps.append((False, conflict))
            return 'manual_review'
        if not policy:
            steps.append((False, _("Warranty card %s has no warranty policy: the coverage cannot "
                                   "be resolved - manual review.", self.warranty_card_id.name)))
            return 'manual_review'
        items = self.requested_item_ids
        if not items:
            steps.append((False, _("No Requested Items: select the requested services / items "
                                   "and check again.")))
            return 'manual_review'
        both = items & policy.covered_item_ids & policy.excluded_item_ids
        if both:
            steps.append((False, _("%(items)s is both a Covered and an Excluded Item of policy "
                                   "%(policy)s - manual review.", items=names(both),
                                   policy=policy.name)))
            return 'manual_review'
        covered = items & policy.covered_item_ids
        excluded = items & policy.excluded_item_ids
        undefined = items - covered - excluded
        if undefined:
            steps.append((False, _("Coverage not defined in policy %(policy)s for: %(items)s - "
                                   "manual review.", policy=policy.name, items=names(undefined))))
            return 'manual_review'
        if excluded:
            if covered:
                steps.append((True, _("Covered: %s.", names(covered))))
            steps.append((False, _("Excluded (chargeable quotation for the excluded items): %s.",
                                   names(excluded))))
            if not covered:
                return 'not_eligible'
            return self._warranty_check_excluded_decisions(steps, excluded)
        steps.append((True, _("All requested items are covered: %s.", names(covered))))
        return False

    def _warranty_coverage_conflicts(self):
        """Approved D8: the requested items are checked against the policy of every
        participating card; a card without policy or an item classified differently (covered /
        excluded / undefined) by the policies -> manual review text, else False."""
        self.ensure_one()
        cards = self.warranty_card_id | self.service_entitlement_ids.warranty_card_id
        if len(cards) < 2:
            return False
        without = cards.filtered(lambda card: not card.policy_id)
        if without:
            return _("Warranty card %s has no warranty policy: the coverage cannot be resolved - "
                     "manual review.", ', '.join(without.mapped('name')))
        conflicts = []
        for item in self.requested_item_ids:
            classes = {}
            for card in cards:
                policy = card.policy_id
                status = _("covered") if item in policy.covered_item_ids else _("excluded") \
                    if item in policy.excluded_item_ids else _("undefined")
                classes.setdefault(status, []).append(card.name)
            if len(classes) > 1:
                conflicts.append('%s (%s)' % (item.name, '; '.join(
                    '%s: %s' % (status, ', '.join(names)) for status, names in classes.items())))
        if conflicts:
            return _("The policies of the participating cards disagree on: %s - manual review.",
                     ' / '.join(conflicts))
        return False

    def _warranty_check_free_service(self, steps):
        """Free Service Request? -> Check Available Service Entitlement (approved Q25 / Q26,
        Part 2 rule A9 as in 3.1): case type Free Service or linked free services; the linked
        services (selected manually) must belong to the case's warranty card and still be
        available. Returns the result or False to continue (repeated failure check, 3.5)."""
        self.ensure_one()
        services = self.service_entitlement_ids
        if self.case_type != 'free_service' and not services:
            steps.append((True, _("Not a free service request: free service entitlement check "
                                  "not needed.")))
            return self._warranty_check_free_service_done(steps)
        if not services:
            steps.append((False, _("Free service request without linked free service: select the "
                                   "available free service on the case and check again.")))
            return 'manual_review'
        # Approved Option A / D1: every participating card is checked; any failure blocks the
        # case and is named (card, services, reason); nothing is excluded silently.
        problems = []
        for card in services.warranty_card_id:
            names = ', '.join(services.filtered(lambda s: s.warranty_card_id == card)
                              .mapped('name'))
            for result, reason in self._warranty_service_card_problems(card):
                problems.append((result, _("%(card)s (%(services)s): %(reason)s.",
                                           card=card.name, services=names, reason=reason)))
        problems += [('manual_review', text) for text in self._warranty_window_problems(services)]
        # BA-approved F3 / K7: service sequence of the cards (card snapshot).
        problems += [('manual_review', text) for text in services._warranty_sequence_problems()]
        if problems:
            steps += [(False, text) for __, text in problems]
            return 'not_eligible' if any(result == 'not_eligible' for result, __ in problems) \
                else 'manual_review'
        available = self.env['warranty.service.entitlement']._warranty_pending_services(
            self.partner_id, self.company_id)
        unavailable = services - available
        if unavailable:
            steps.append((False, _("Free service %s is no longer available (status, grace period "
                                   "or balance) - convert to chargeable service or reject.",
                                   ', '.join(unavailable.mapped('name')))))
            return 'not_eligible'
        steps.append((True, _("Free service entitlement available: %s.",
                              ', '.join(services.mapped('name')))))
        return self._warranty_check_free_service_done(steps)

    def _warranty_check_free_service_done(self, steps):
        steps.append((True, _("Coverage and free service checks done - the repeated failure check "
                              "follows.")))
        return False

    def _warranty_physical_unit(self):
        """Physical unit of the case (approved Q31 unit first / Q37): the Unit Warranty (all
        its serials, kit Indoor / Outdoor = one system), else the serial number, else the only
        unit of the product on the card. Returns (unit, serial, problem text or None)."""
        self.ensure_one()
        Unit = self.env['warranty.unit']
        card, unit, serial = self.warranty_card_id, self.warranty_unit_id, self.serial_id
        if unit:
            owner = unit.warranty_card_id.partner_id.commercial_partner_id
            if unit.warranty_card_id != card or unit.company_id != self.company_id \
                    or owner != self.partner_id.commercial_partner_id \
                    or (self.product_id and unit.product_id != self.product_id):
                return Unit, serial, _(
                    "Unit Warranty %(unit)s does not belong to warranty card %(card)s, product "
                    "%(product)s and customer %(customer)s: select the correct Unit Warranty "
                    "and check again.", unit=unit.display_name, card=card.name,
                    product=self.product_id.display_name or '-', customer=self.partner_id.name)
            return unit, serial, None
        if serial:
            return Unit, serial, None
        units = card.unit_warranty_ids
        if self.product_id:
            units = units.filtered(lambda u: u.product_id == self.product_id)
        if len(units) == 1:
            return units, serial, None
        return Unit, serial, _(
            "Physical unit not identified (warranty card %(card)s has %(count)s units of product "
            "%(product)s): select the Unit Warranty or serial number on the case and check "
            "again.", card=card.name, count=len(units),
            product=self.product_id.display_name or '-')

    def _warranty_failure_matches(self, other, unit, serial):
        """True when the earlier case `other` is a failure of the same physical unit; None
        when it cannot be attributed reliably (no unit / serial, several possible units of the
        product); False otherwise. Cases never checked are resolved like the 3.2 check."""
        card, other_unit, __ = self._warranty_find_card(
            other.partner_id, other.company_id, other.product_id, other.serial_id,
            card=other.warranty_card_id, unit=other.warranty_unit_id)
        if other_unit:
            return other_unit == unit if unit else serial in other_unit.serial_ids
        if other.serial_id:
            return other.serial_id in unit.serial_ids if unit else other.serial_id == serial
        same_product = not other.product_id or not self.product_id \
            or other.product_id == self.product_id
        if same_product and (not card or card == self.warranty_card_id):
            return None
        return False

    def _warranty_check_repeated_failure(self, steps):
        """Check Repeated Failure Threshold (approved Q29-Q37): failures of the physical unit
        (Warranty Complaint / Replacement / Repeat Complaint cases, not Rejected) with a ticket
        date within the policy period, this case included when it is a failure; more than the
        threshold -> escalation to the Manager / GM (Manual Review until an escalation user
        confirms the warranty of this case). Returns (result, values)."""
        self.ensure_one()
        policy = self.warranty_card_id.policy_id
        threshold, days = policy.repeated_failure_threshold, policy.repeated_failure_period_days
        if not threshold or not days:
            steps.append((True, _("No repeated failure escalation rule on policy %s: check not "
                                  "needed.", policy.name)))
            return self._warranty_eligible(steps), {
                'repeated_failure_flag': False, 'repeated_failure_count': 0,
                'escalation_pending': False}
        unit, serial, problem = self._warranty_physical_unit()
        if problem:
            steps.append((False, problem))
            return 'manual_review', {'escalation_pending': False}
        steps.append((True, _("Physical unit: %s.", unit.display_name + (
            ' (%s)' % ', '.join(unit.serial_ids.mapped('name')) if unit.serial_ids else '')
            if unit else serial.name)))
        end = self._warranty_check_date()
        start = end - timedelta(days=days)
        candidates = self.search([
            ('id', '!=', self.id), ('company_id', '=', self.company_id.id),
            ('commercial_partner_id', '=', self.commercial_partner_id.id),
            ('case_type', 'in', FAILURE_CASE_TYPES), ('state', '!=', 'rejected')])
        failures, unattributed = self.browse(), self.browse()
        for other in candidates:
            if not start <= other._warranty_check_date() <= end:
                continue
            match = self._warranty_failure_matches(other, unit, serial)
            if match:
                failures |= other
            elif match is None:
                unattributed |= other
        count = len(failures) + (1 if self.case_type in FAILURE_CASE_TYPES else 0)
        steps.append((True, _("%(count)s failure(s) within %(days)s days (%(start)s - %(end)s, "
                              "this case %(own)s)%(cases)s; threshold %(threshold)s.",
                              count=count, days=days, start=start, end=end,
                              own=_("included") if self.case_type in FAILURE_CASE_TYPES
                              else _("not a failure"),
                              cases=': ' + ', '.join(failures.mapped('name')) if failures else '',
                              threshold=threshold)))
        if unattributed:
            steps.append((True, _("Not attributable to a physical unit, not counted: %s.",
                                  ', '.join(unattributed.mapped('name')))))
        vals = {'repeated_failure_count': count, 'repeated_failure_flag': count > threshold}
        if count <= threshold:
            return self._warranty_eligible(steps), dict(vals, escalation_pending=False)
        steps.append((False, _("Repeated failure threshold exceeded (more than %s).", threshold)))
        if self.escalation_confirmed_by_id:
            steps.append((True, _("Warranty confirmed by %(user)s on %(date)s for this case.",
                                  user=self.escalation_confirmed_by_id.name,
                                  date=self.escalation_confirmed_date)))
            return self._warranty_eligible(steps), dict(vals, escalation_pending=False)
        steps.append((False, self._request_escalation(count, threshold, days)))
        return 'manual_review', dict(vals, escalation_pending=True)

    def _warranty_eligible(self, steps):
        steps.append((True, _("All eligibility checks passed: Eligible - warranty case ready for "
                              "the Service Job.")))
        return 'eligible'

    def _request_escalation(self, count, threshold, days):
        """Create Escalation Activity -> Escalate to Manager / GM: one activity per escalation
        user (not the requester), no duplicates while open activities exist."""
        self.ensure_one()
        if self.env.context.get('warranty_revalidation'):
            return _("Escalation required: not requested during the approval revalidation - run "
                     "Check Eligibility.")
        open_activities = self.escalation_activity_ids.exists().filtered('active')
        if open_activities:
            return _("Escalated to %s: waiting for the warranty confirmation.",
                     ', '.join(open_activities.user_id.mapped('name')))
        users = self.company_id.warranty_escalation_user_ids - self.env.user
        self.write({'escalation_requested_by_id': self.env.uid})
        if not users:
            return _("Escalation required: no Repeated Failure Escalation User (other than you) "
                     "is configured for %s.", self.company_id.name)
        activities = self.env['mail.activity']
        # As for the payment approvals: without sender email no assignment email.
        case = self if self.env.user.email else self.with_context(mail_activity_quick_update=True)
        for user in users:
            activities |= case.activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                summary=_("Repeated failure: confirm the warranty of case %s", self.name),
                note=_("%(count)s failures within %(days)s days (threshold %(threshold)s).",
                       count=count, days=days, threshold=threshold))
        self.write({'escalation_activity_ids': [(4, a.id) for a in activities]})
        return _("Escalated to %s: waiting for the warranty confirmation.",
                 ', '.join(users.mapped('name')))

    def _close_escalation_activities(self, feedback):
        activities = self.escalation_activity_ids.exists().filtered('active')
        if activities:
            # sudo: activities of the escalation users are closed by the system.
            activities.sudo().action_feedback(feedback=feedback)

    def action_confirm_repeated_failure(self):
        """Escalation user confirms the warranty of this case only (SRS 9.5 "continue only
        after authorized user confirms the warranty"); Check Eligibility must be run again."""
        for case in self:
            if not case.escalation_pending:
                raise UserError(_("No repeated failure escalation is waiting for confirmation on "
                                  "%s.", case.name))
            if self.env.user == case.escalation_requested_by_id:
                raise AccessError(_("You cannot confirm your own repeated failure escalation."))
            if not case._is_escalation_user():
                raise AccessError(_(
                    "Only the Repeated Failure Escalation Users of %s can confirm the warranty "
                    "of repeated failure cases.", case.company_id.name))
            # sudo: escalation users may not have edit rights on warranty cases.
            case.sudo().write({
                'escalation_pending': False,
                'escalation_confirmed_by_id': self.env.uid,
                'escalation_confirmed_date': fields.Datetime.now(),
            })
            case._close_escalation_activities(_("Confirmed by %s", self.env.user.name))
            case.sudo()._message_log(body=Markup('<p><b>%s</b></p><p>%s</p>') % (
                _("Warranty confirmed despite repeated failure by %s", self.env.user.name),
                _("Run Check Eligibility again to continue.")))
        return True

    # ------------------------------------------------------------------ Part 3.6a
    def _sync_case_approval_activities(self):
        """Q43: one To-Do per user allowed to approve the case now; obsolete activities (removed
        / now excluded users) closed, missing ones created, valid ones kept. Returns the
        chatter steps."""
        self.ensure_one()
        if not self.company_id.warranty_case_approval_required:
            # Approved S3: no approval activities when approval users are not required.
            return self._close_case_approval_activities(_(
                "Warranty Case Approval Required is off: approval by Helpdesk users, no approval "
                "activities.")) + [(True, _(
                    "Warranty Case Approval Required is off: a Helpdesk user approves the case "
                    "(no approval activities)."))]
        allowed = self._case_approvers()
        open_activities = self.case_approval_activity_ids.exists().filtered('active')
        steps = []
        obsolete = open_activities.filtered(lambda a: a.user_id not in allowed)
        kept = open_activities - obsolete
        if obsolete:
            # Names first: done activities are deleted by action_feedback.
            steps.append((True, _("Case approval activities closed (no longer authorized): %s.",
                                  ', '.join(obsolete.user_id.mapped('name')))))
            # sudo: activities of other users are closed by the system.
            obsolete.sudo().action_feedback(feedback=_(
                "Approval no longer assigned - user is no longer an authorized approver for this "
                "case."))
        if kept:
            steps.append((True, _("Case approval already requested from %s.",
                                  ', '.join(kept.user_id.mapped('name')))))
        missing = allowed - kept.user_id
        if missing:
            activities = self.env['mail.activity']
            # As for the payment approvals: without sender email no assignment email.
            case = self if self.env.user.email \
                else self.with_context(mail_activity_quick_update=True)
            for user in missing:
                activities |= case.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=_("Approve warranty case %s", self.name),
                    note=_("The warranty case is Eligible: review and approve it."))
            self.write({'case_approval_activity_ids': [(4, a.id) for a in activities]})
            steps.append((True, _("Case approval requested from %s.",
                                  ', '.join(missing.mapped('name')))))
        if not allowed:
            steps.append((False, _("No Warranty Case Approval User (other than the case creator "
                                   "and the eligibility checker) is configured for %s.",
                                   self.company_id.name)))
        return steps

    def _close_case_approval_activities(self, feedback):
        """Close the open case approval activities; returns the chatter steps."""
        activities = self.case_approval_activity_ids.exists().filtered('active')
        if not activities:
            return []
        names = ', '.join(activities.user_id.mapped('name'))
        # sudo: activities of the approvers are closed by the system.
        activities.sudo().action_feedback(feedback=feedback)
        return [(True, _("Case approval activities closed (%(users)s): %(reason)s",
                         users=names, reason=feedback))]

    def _check_case_approver(self, action):
        """Server-side Approve / Reject permission (same rules, approved S5)."""
        self.ensure_one()
        if self.company_id.warranty_case_approval_required:
            if self.env.user in self.create_uid | self.eligibility_checked_by_id:
                raise AccessError(_("You cannot %(action)s warranty case %(case)s: you created it "
                                    "or ran its latest eligibility check.", action=action,
                                    case=self.name))
            if not self._is_case_approver():
                raise AccessError(_("Only the Warranty Case Approval Users of %(company)s can "
                                    "%(action)s warranty cases.", company=self.company_id.name,
                                    action=action))
        elif not self._is_case_approver():
            raise AccessError(_("Only Helpdesk users of %(company)s can %(action)s warranty "
                                "cases.", company=self.company_id.name, action=action))

    def action_approve_case(self):
        """Approve Case (approved Q38-Q43): Eligibility Checked + Eligible, current Warranty
        Case Approval User, not the case creator nor the latest eligibility checker; the
        eligibility is revalidated first (existing payment waiver / repeated failure
        confirmation kept, no new approval requests); failed -> not approved, result updated."""
        refused = self.browse()
        for case in self:
            if case.state != 'eligibility_checked' or case.eligibility_result != 'eligible':
                raise UserError(_("Only Eligible warranty cases in Eligibility Checked status can be "
                                  "approved (%s).", case.name))
            case._check_case_approver(_("approve"))
            # sudo: the approver may lack rights on cards / services / accounting read by the
            # checks and on writing the case; the checks only read, approval requests are
            # suppressed by the revalidation context.
            checked = case.sudo().with_context(warranty_revalidation=True)
            result, steps, __, __ = checked._warranty_run_checks()
            if result != 'eligible':
                checked.write({'eligibility_result': result})
                steps += case._close_case_approval_activities(_(
                    "Approval no longer needed - revalidation failed."))
                case.sudo()._message_log(body=case._warranty_approval_message(
                    _("Approval refused by revalidation (%s)", self.env.user.name), result, steps))
                refused |= case
                continue
            checked.write({
                'state': 'approved',
                'eligibility_result': 'eligible',
                'case_approved_by_id': self.env.uid,
                'case_approved_date': fields.Datetime.now(),
            })
            steps += case._close_case_approval_activities(_("Approved by %s", self.env.user.name))
            case.sudo()._message_log(body=case._warranty_approval_message(
                _("Warranty case approved by %s - revalidation passed", self.env.user.name),
                result, steps))
        if refused:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'sticky': True,
                    'title': _("Warranty case not approved"),
                    'message': _("The eligibility revalidation of %s failed - see the chatter. Run "
                                 "Check Eligibility again.", ', '.join(refused.mapped('name'))),
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        return True

    def _warranty_approval_message(self, title, result, steps):
        labels = dict(self._fields['eligibility_result']._description_selection(self.env))
        lines = Markup('').join(Markup('<li>%s %s</li>') % ('✔' if passed else '✘', text)
                                for passed, text in steps)
        return Markup('<p><b>%s</b></p><p>%s</p><ul>%s</ul>') % (
            title, _("Revalidation result: %s", labels.get(result, result)), lines)

    def _check_case_rejection(self):
        """Reject Case (Q44 / Q45): Eligibility Checked with result Not Eligible / Out of
        Warranty / Manual Review; current Warranty Case Approval User, not the case creator
        nor the latest eligibility checker."""
        for case in self:
            if case.state != 'eligibility_checked' or case.eligibility_result not in REJECTABLE_RESULTS:
                raise UserError(_("Only warranty cases in Eligibility Checked status with result Not "
                                  "Eligible, Out of Warranty or Manual Review can be rejected (%s).",
                                  case.name))
            case._check_case_approver(_("reject"))

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._check_case_rejection()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Warranty Case"),
            'res_model': 'warranty.case.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_case_id': self.id},
        }

    def _warranty_reject(self, reason, note):
        """Status Rejected (final, SRS "do not silently reject": explicit reason / note / user /
        date, chatter); open approval / escalation activities closed; linked free services
        released (Q48, status unchanged); Helpdesk ticket unchanged (Q47)."""
        self._check_case_rejection()
        labels = dict(REJECTION_REASONS)
        for case in self:
            services = case.service_entitlement_ids
            steps = case._close_case_approval_activities(_("Case rejected"))
            case._close_payment_approval_activities(_("Case rejected"))
            case._close_escalation_activities(_("Case rejected"))
            # sudo: approvers may not have edit rights on warranty cases.
            case.sudo().write({
                'state': 'rejected',
                'payment_hold': False,
                'escalation_pending': False,
                'rejection_reason': reason,
                'rejection_note': note,
                'rejected_by_id': self.env.uid,
                'rejected_date': fields.Datetime.now(),
            })
            if services:
                # The services keep the case link as history; no active case -> available.
                case.sudo()._sync_service_tickets(services)
                steps.append((True, _("Free services released for another case (status "
                                      "unchanged): %s.", ', '.join(services.mapped('name')))))
            lines = Markup('').join(Markup('<li>%s %s</li>') % ('✔' if passed else '✘', text)
                                    for passed, text in steps)
            case.sudo()._message_log(body=Markup('<p><b>%s</b></p><p>%s</p><ul>%s</ul>') % (
                _("Warranty case rejected by %(user)s: %(reason)s", user=self.env.user.name,
                  reason=labels[reason]),
                note or '-', lines))
        return True

    # ------------------------------------------------------------------ Part 3.6c
    def _warranty_sync_excluded_items(self, excluded):
        """Excluded Items list (Q53a): one line per excluded requested item; unused lines of
        items no longer requested (no quotation line, not declined) are removed."""
        self.ensure_one()
        Item = self.env['warranty.case.excluded.item']
        existing = self.excluded_item_ids
        unused = existing.filtered(lambda item: item.coverage_item_id not in excluded
                                   and not item.declined and not item.sale_line_ids)
        unused.unlink()
        for coverage_item in excluded - existing.coverage_item_id:
            Item.create({'case_id': self.id, 'coverage_item_id': coverage_item.id})
        return self.excluded_item_ids.filtered(lambda item: item.coverage_item_id in excluded)

    def _warranty_check_excluded_decisions(self, steps, excluded):
        """Partial coverage (Q53a-d): the excluded items stay chargeable; the covered warranty
        work continues only after the customer decided on every excluded item (Approved on a
        confirmed quotation or explicitly Declined)."""
        labels = dict(self.env['warranty.case.excluded.item']._fields[
            'customer_decision']._description_selection(self.env))
        items = self._warranty_sync_excluded_items(excluded)
        for item in items:
            text = '%s: %s' % (item.coverage_item_id.name, labels[item.customer_decision])
            if item.customer_decision == 'approved':
                text += _(" (confirmed qty %(qty)s on %(order)s)", qty=item.confirmed_qty,
                          order=item.sudo().sale_order_id.name)
            elif item.customer_decision == 'declined':
                text += _(" (%s)", item.decline_reason)
            steps.append((item.customer_decision in ('approved', 'declined'), text))
        if any(item.customer_decision in ('quotation_required', 'waiting') for item in items):
            steps.append((False, _("Partial coverage: waiting for the customer decision on the "
                                   "excluded items - proceed only after approval.")))
            return 'partial'
        steps.append((True, _("Customer decided on all excluded items: the covered items "
                              "continue under warranty, the excluded items stay chargeable.")))
        return False

    def _warranty_check_quotation_rights(self):
        if not self.env.user.has_group('sales_team.group_sale_salesman'):
            raise AccessError(_("Creating quotations requires Sales rights."))

    def _warranty_quote_excluded_lines(self, items):
        """Quotation line values of excluded items without active quotation line (Q51:
        product of the coverage item)."""
        missing = items.filtered(lambda item: not item.product_id)
        if missing:
            raise UserError(_(
                "Set a Product on the coverage item(s) %s (Warranty > Configuration > Coverage "
                "Items) or record Customer Declined.",
                ', '.join(missing.coverage_item_id.mapped('name'))))
        return [{'product_id': item.product_id.id, 'product_uom_qty': 1.0,
                 'warranty_case_id': self.id, 'warranty_excluded_item_id': item.id}
                for item in items]

    def _warranty_create_quotation(self, line_vals):
        """Draft quotation of the case (Q54: several per case); no Service Job, no email to
        the customer (Q52)."""
        self.ensure_one()
        self._warranty_check_quotation_rights()
        commercial = self.partner_id.commercial_partner_id
        return self.env['sale.order'].with_company(self.company_id).create({
            'partner_id': commercial.id,
            'partner_shipping_id': (self.site_id or commercial).id,
            'company_id': self.company_id.id,
            'origin': '%s / %s' % (self.name, self.helpdesk_ticket_id.display_name),
            'warranty_case_id': self.id,
            'order_line': [(0, 0, vals) for vals in line_vals],
        })

    def _warranty_open_quotation(self, order):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': order.id,
        }

    def action_create_excluded_quotation(self):
        """Create Excluded Items Quotation (Q53a): Partial result, items still Quotation
        Required; the case status is unchanged."""
        self.ensure_one()
        if self.state != 'eligibility_checked' or self.eligibility_result != 'partial':
            raise UserError(_("The excluded items quotation is created for Partial cases in "
                              "Eligibility Checked status (%s).", self.name))
        items = self.excluded_item_ids.filtered(
            lambda item: item.coverage_item_id in self.requested_item_ids
            and item.customer_decision == 'quotation_required')
        if not items:
            raise UserError(_("All excluded items of %s are already quoted or decided.",
                              self.name))
        order = self._warranty_create_quotation(self._warranty_quote_excluded_lines(items))
        self._message_log(body=Markup('<p><b>%s</b></p>') % _(
            "Excluded items quotation %(order)s created: %(items)s - waiting for the customer "
            "decision.", order=order.name,
            items=', '.join(items.coverage_item_id.mapped('name'))))
        return self._warranty_open_quotation(order)

    def _check_chargeable_conversion(self):
        for case in self:
            if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
                raise AccessError(_("Only Helpdesk users can convert warranty cases to "
                                    "chargeable."))
            allowed = (case.state == 'eligibility_checked'
                       and case.eligibility_result in REJECTABLE_RESULTS) \
                or (case.state == 'new' and case.case_type in CHARGEABLE_CASE_TYPES)
            if not allowed:
                raise UserError(_(
                    "Only cases with result Not Eligible, Out of Warranty or Manual Review, or new "
                    "Chargeable Inspection / Repair cases, can be converted to chargeable (%s). "
                    "Partial cases keep the covered work under warranty: use Create Excluded "
                    "Items Quotation.", case.name))

    def action_open_chargeable_wizard(self):
        self.ensure_one()
        self._check_chargeable_conversion()
        if self.case_type == 'chargeable_repair':
            default = 'repair'
        elif self.case_type == 'chargeable_inspection':
            default = 'inspection'
        elif self.requested_item_ids & self.warranty_card_id.policy_id.excluded_item_ids:
            default = 'excluded_items'
        elif self.helpdesk_ticket_id.team_id.warranty_inspection_required:
            default = 'inspection'
        else:
            default = 'repair'
        return {
            'type': 'ir.actions.act_window',
            'name': _("Convert to Chargeable"),
            'res_model': 'warranty.case.chargeable.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_case_id': self.id, 'default_chargeable_type': default},
        }

    def _warranty_convert_chargeable(self, chargeable_type):
        """Convert to Chargeable (Q49-Q52, Q54): status Chargeable + Chargeable Type, original
        case type kept; draft quotation with the inspection line (Helpdesk team Inspection
        Required) and, for Excluded Items, the excluded requested items. No Service Job."""
        self.ensure_one()
        self._check_chargeable_conversion()
        team = self.helpdesk_ticket_id.team_id
        line_vals = []
        if team.warranty_inspection_required:
            if not team.warranty_inspection_product_id:
                raise UserError(_("Set the Inspection Product of Helpdesk team %s.", team.name))
            inspection = {'product_id': team.warranty_inspection_product_id.id,
                          'product_uom_qty': 1.0, 'warranty_case_id': self.id}
            if team.warranty_inspection_amount:
                inspection['price_unit'] = team.warranty_inspection_amount
            line_vals.append(inspection)
        items = self.env['warranty.case.excluded.item']
        if chargeable_type == 'excluded_items':
            excluded = self.requested_item_ids & self.warranty_card_id.policy_id.excluded_item_ids
            items = self._warranty_sync_excluded_items(excluded).filtered(
                lambda item: item.customer_decision == 'quotation_required')
            line_vals += self._warranty_quote_excluded_lines(items)
        order = self._warranty_create_quotation(line_vals) if line_vals else False
        steps = self._close_case_approval_activities(_("Case converted to chargeable"))
        self._close_payment_approval_activities(_("Case converted to chargeable"))
        self._close_escalation_activities(_("Case converted to chargeable"))
        self.write({
            'state': 'chargeable',
            'chargeable_type': chargeable_type,
            'chargeable_converted_by_id': self.env.uid,
            'chargeable_converted_date': fields.Datetime.now(),
            'payment_hold': False,
            'escalation_pending': False,
        })
        labels = dict(CHARGEABLE_TYPES)
        steps.append((True, _("Draft quotation %s created (no Service Job).", order.name)
                      if order else _("No quotation line configured: create the quotation from "
                                      "the Quotations button.")))
        lines = Markup('').join(Markup('<li>%s %s</li>') % ('✔' if passed else '✘', text)
                                for passed, text in steps)
        self._message_log(body=Markup('<p><b>%s</b></p><ul>%s</ul>') % (
            _("Converted to chargeable (%(type)s) by %(user)s", type=labels[chargeable_type],
              user=self.env.user.name), lines))
        return self._warranty_open_quotation(order) if order else True

    def action_view_quotations(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sale.action_quotations_with_onboarding')
        action.update({
            'domain': [('warranty_case_id', '=', self.id)],
            'context': {'default_warranty_case_id': self.id,
                        'default_partner_id': self.partner_id.commercial_partner_id.id},
        })
        return action
