from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_amount, html2plaintext

from odoo.addons.warranty_management.models.res_company import get_valid_service_alert_users


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
    warranty_card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', compute='_compute_warranty_card_id',
        store=True, readonly=False, tracking=True,
        domain="[('partner_id', 'child_of', commercial_partner_id), "
               "('company_id', '=', company_id)]")
    warranty_unit_id = fields.Many2one(
        'warranty.unit', string='Unit Warranty', tracking=True,
        domain="[('warranty_card_id', '=', warranty_card_id)] if warranty_card_id else "
               "[('warranty_card_id.partner_id', 'child_of', commercial_partner_id), "
               "('company_id', '=', company_id)]",
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
                 'company_id.warranty_case_approver_ids')
    def _compute_can_approve_case(self):
        for case in self:
            case.can_approve_case = case.state == 'eligibility_checked' \
                and case.eligibility_result == 'eligible' and case._is_case_approver()

    @api.depends_context('uid')
    @api.depends('state', 'eligibility_result', 'eligibility_checked_by_id', 'create_uid',
                 'company_id.warranty_case_approver_ids')
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
        self.ensure_one()
        return (user or self.env.user) in self._case_approvers()

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
        return cases

    def write(self, vals):
        # Approved Part 3.6b: a Rejected case is final (chatter / activities only).
        if any(not key.startswith(REJECTED_WRITABLE_PREFIXES) for key in vals) \
                and any(case.state == 'rejected' for case in self):
            raise UserError(_("A Rejected warranty case cannot be changed."))
        if 'service_entitlement_ids' in vals and any(case.state != 'new' for case in self):
            raise UserError(_("Linked free services can only be changed while the warranty "
                              "case is New."))
        previous = self.service_entitlement_ids
        result = super().write(vals)
        if 'service_entitlement_ids' in vals or 'helpdesk_ticket_id' in vals:
            self._sync_service_tickets(previous - self.service_entitlement_ids)
        return result

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
        return True

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
        self.write({'warranty_card_id': card.id, 'warranty_unit_id': unit.id})
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
        other_card = services.filtered(lambda s: s.warranty_card_id != self.warranty_card_id)
        if other_card:
            steps.append((False, _("Free service %(services)s belongs to another warranty card "
                                   "than %(card)s - manual review.",
                                   services=', '.join(other_card.mapped('name')),
                                   card=self.warranty_card_id.name)))
            return 'manual_review'
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
            if self.env.user in case.create_uid | case.eligibility_checked_by_id:
                raise AccessError(_("You cannot approve warranty case %s: you created it or ran "
                                    "its latest eligibility check.", case.name))
            if not case._is_case_approver():
                raise AccessError(_("Only the Warranty Case Approval Users of %s can approve "
                                    "warranty cases.", case.company_id.name))
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
            if self.env.user in case.create_uid | case.eligibility_checked_by_id:
                raise AccessError(_("You cannot reject warranty case %s: you created it or ran its "
                                    "latest eligibility check.", case.name))
            if not case._is_case_approver():
                raise AccessError(_("Only the Warranty Case Approval Users of %s can reject "
                                    "warranty cases.", case.company_id.name))

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
