from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools import format_datetime
from odoo.exceptions import AccessError, UserError, ValidationError

# SRS 9.13 Service Job: Draft -> Planned -> Confirmed -> In Progress ->
# Incomplete/Rescheduled/Awaiting Parts/Workshop -> Completed/Cancelled (visit level
# Incomplete / Rescheduled, Part 4 diagram; approved Part 4 breakdown).
JOB_STATES = [
    ('draft', 'Draft'),
    ('planned', 'Planned'),
    ('confirmed', 'Confirmed'),
    ('in_progress', 'In Progress'),
    ('awaiting_parts', 'Awaiting Parts'),
    ('workshop', 'Workshop'),
    # Phase 4.8 (approved L3 / L6, SRS 9.13): Incomplete = visit not completed, no next visit
    # planned yet; Rescheduled = next visit planned, not started.
    ('incomplete', 'Incomplete'),
    ('rescheduled', 'Rescheduled'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
]
CLOSED_JOB_STATES = ('completed', 'cancelled')
# Phase 4.1: states in which a job may still be cancelled (Q42: before confirmation).
CANCELLABLE_JOB_STATES = ('draft', 'planned')
# Phase 4.2: planning (date / technicians) can be changed before confirmation only.
PLANNING_JOB_STATES = ('draft', 'planned')
PLANNING_FIELDS = ('planned_date', 'main_technician_id', 'support_technician_ids')
# Phase 4.6 (approved M1): blocking statuses, entered / left only through _warranty_set_hold().
HOLD_STATES = ('awaiting_parts', 'workshop')
_HOLD_MARKER = object()
# Phase 4.7 (approved K5 / K6): Completed statuses of the job, its worksheets, free services and
# case are set only by _warranty_complete_visit(); the marker is a Python object that no client
# (UI, JSON-RPC, import) can put in a context, and sudo() alone does not pass.
_COMPLETION_MARKER = object()
# Phase 4.8: Incomplete / Rescheduled / Cancelled (after confirmation) and the re-planning of a
# job are set only by _warranty_visit_not_completed(), _warranty_plan_next_visit() and
# _warranty_cancel_job() (Python marker, not sendable by clients).
_VISIT_MARKER = object()
VISIT_STATES = ('incomplete', 'rescheduled')
# Jobs with an open visit (non-completion can be reported).
OPEN_VISIT_JOB_STATES = ('confirmed', 'rescheduled', 'in_progress', 'awaiting_parts', 'workshop')
# Jobs that Cancel Job (approved L7) applies to; Draft / Planned keep action_cancel (Q42).
CONFIRMED_JOB_STATES = OPEN_VISIT_JOB_STATES + ('incomplete',)
# SRS 2.8 non-completion reasons and SRS Field Service visit Job Outcome (approved L2 option B).
NONCOMPLETION_REASONS = [
    ('customer_unavailable', 'Customer Unavailable'),
    ('awaiting_parts', 'Awaiting Parts'),
    ('technical_escalation', 'Technical Escalation'),
    ('workshop_repair', 'Workshop Repair Required'),
    ('access_issue', 'Access Issue'),
    ('other', 'Other'),
]
VISIT_OUTCOMES = [
    ('completed', 'Completed'),
    ('rescheduled', 'Rescheduled'),
    ('customer_not_available', 'Customer Not Available'),
    ('followup_required', 'Follow-up Required'),
    ('cancelled', 'Cancelled'),
    ('part_pending', 'Part Pending'),
]
NEXT_ACTIONS = [
    ('reschedule', 'Reschedule'),
    ('followup', 'Follow-up'),
    ('cancel', 'Cancel'),
]


def visit_outcome(next_action, reason):
    """Approved L2 option B: the SRS Job Outcome from the next action and the reason."""
    if next_action == 'reschedule':
        return 'rescheduled'
    if next_action == 'cancel':
        return 'cancelled'
    return {'customer_unavailable': 'customer_not_available',
            'awaiting_parts': 'part_pending'}.get(reason, 'followup_required')
# Phase 4.10 (approved C5): job types; chargeable jobs come from chargeable cases.
JOB_TYPES = [
    ('warranty', 'Warranty'),
    ('chargeable_inspection', 'Chargeable Inspection'),
    ('chargeable_repair', 'Chargeable Repair'),
    ('chargeable_excluded', 'Chargeable Excluded Items'),
    ('warranty_inspection', 'Warranty Inspection'),
]
# SRS service flow alignment (doc/srs_service_flow_alignment_design.md): a job comes from a
# warranty case (Helpdesk-first route) or from free services (SRS 9.4 route: job before ticket).
JOB_ORIGINS = [
    ('case', 'Warranty Case'),
    ('service', 'Service Entitlements'),
]
# Service-origin jobs, inspection jobs and the late case link are created / written by system
# code only. Python object: no client (UI, import, JSON-RPC) can put it in a context.
_SERVICE_JOB_MARKER = object()
ORIGIN_FIELDS = {'job_origin', 'origin_company_id', 'origin_partner_id', 'origin_site_id',
                 'origin_ticket_id', 'warranty_case_id'}
# Service-origin jobs without warranty case: only these states (ticket / case before Confirm).
CASELESS_JOB_STATES = ('draft', 'planned', 'cancelled')
CHARGEABLE_JOB_FIELDS = ('job_type', 'chargeable_order_id', 'inspection_diagnosis',
                         'inspection_repair_required', 'inspection_repair_details',
                         'repair_quotation_id')
# Phase 4.9 (SRS 10.5 Service Job "Completion Mode", approved B3).
COMPLETION_MODES = [
    ('single', 'Single'),
    ('batch', 'Batch Eligible'),
]
MERGE_TYPES = [
    ('none', 'No Free Service'),
    ('single', 'Single Free Service'),
    ('merged', 'Merged Free Services'),
]


class WarrantyServiceJob(models.Model):
    """Service Job (SRS 1 / 10.5, approved P3): orchestration object between the warranty
    case / free services and the Field Service visits."""
    _name = 'warranty.service.job'
    _description = 'Warranty Service Job'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Job No.', required=True, readonly=True, copy=False,
                       default='New')
    job_origin = fields.Selection(JOB_ORIGINS, string='Origin', required=True, default='case',
                                  readonly=True, copy=False, tracking=True)
    # Required for case-origin jobs; service-origin jobs get it when their warranty case is
    # created manually on their ticket (warranty.case._warranty_link_waiting_job) before
    # confirmation (_check_origin_case).
    warranty_case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True,
                                       ondelete='restrict', index=True, tracking=True)
    # Service-origin jobs before their case: customer, company and site of the services.
    origin_company_id = fields.Many2one('res.company', string='Origin Company', readonly=True,
                                        copy=False)
    origin_partner_id = fields.Many2one('res.partner', string='Origin Customer', readonly=True,
                                        copy=False)
    origin_site_id = fields.Many2one('res.partner', string='Origin Site', readonly=True,
                                     copy=False)
    # Create or Link Helpdesk Ticket: the ticket before the manually created warranty case.
    origin_ticket_id = fields.Many2one('helpdesk.ticket', string='Origin Ticket', readonly=True,
                                       copy=False)
    company_id = fields.Many2one('res.company', string='Company',
                                 compute='_compute_origin_values', store=True, index=True)
    helpdesk_ticket_id = fields.Many2one('helpdesk.ticket', string='Helpdesk Ticket',
                                         compute='_compute_origin_values', store=True)
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 compute='_compute_origin_values', store=True)
    commercial_partner_id = fields.Many2one('res.partner', compute='_compute_origin_values',
                                            store=True)
    site_id = fields.Many2one('res.partner', string='Site', compute='_compute_origin_values',
                              store=True)
    product_id = fields.Many2one(related='warranty_case_id.product_id', store=True)
    serial_id = fields.Many2one(related='warranty_case_id.serial_id', store=True)
    warranty_site_address = fields.Char(related='warranty_case_id.warranty_site_address',
                                        string='Site Address')
    warranty_card_id = fields.Many2one('warranty.card', string='Warranty Card',
                                       compute='_compute_origin_values', store=True)
    warranty_unit_id = fields.Many2one(related='warranty_case_id.warranty_unit_id', store=True)
    entitlement_ids = fields.Many2many(
        'warranty.service.entitlement', 'warranty_service_job_entitlement_rel', 'job_id',
        'entitlement_id', string='Free Services', readonly=True, copy=False)
    # Cross-card service merge (approved D5 / UI 4): all cards of the job, searchable.
    warranty_card_ids = fields.Many2many(
        'warranty.card', 'warranty_service_job_card_rel', 'job_id', 'card_id',
        string='Warranty Cards', compute='_compute_warranty_card_ids', store=True)

    @api.depends('warranty_case_id.company_id', 'warranty_case_id.helpdesk_ticket_id',
                 'warranty_case_id.partner_id', 'warranty_case_id.commercial_partner_id',
                 'warranty_case_id.site_id', 'warranty_case_id.warranty_card_id',
                 'origin_company_id', 'origin_partner_id', 'origin_site_id', 'origin_ticket_id',
                 'entitlement_ids.warranty_card_id')
    def _compute_origin_values(self):
        """From the warranty case (same values as the former related fields); service-origin
        jobs before their case: the customer, company and site of their free services."""
        for job in self:
            case = job.warranty_case_id
            if case:
                job.company_id = case.company_id
                job.helpdesk_ticket_id = case.helpdesk_ticket_id
                job.partner_id = case.partner_id
                job.commercial_partner_id = case.commercial_partner_id
                job.site_id = case.site_id
                job.warranty_card_id = case.warranty_card_id
                continue
            cards = job.entitlement_ids.warranty_card_id
            job.company_id = job.origin_company_id
            job.helpdesk_ticket_id = job.origin_ticket_id
            job.partner_id = job.origin_partner_id
            job.commercial_partner_id = job.origin_partner_id.commercial_partner_id
            job.site_id = job.origin_site_id
            job.warranty_card_id = cards if len(cards) == 1 else False

    @api.constrains('job_origin', 'warranty_case_id', 'state')
    def _check_origin_case(self):
        for job in self:
            if job.warranty_case_id:
                continue
            if job.job_origin != 'service':
                raise ValidationError(_("Service job %s needs its warranty case.", job.name))
            if job.state not in CASELESS_JOB_STATES:
                raise ValidationError(_(
                    "Service job %s needs its Helpdesk ticket and warranty case before it is "
                    "confirmed: use Create or Link Helpdesk Ticket, then create its warranty case.",
                    job.name))

    def _warranty_service_marker(self):
        return self.with_context(warranty_service_job_marker=_SERVICE_JOB_MARKER)

    def _warranty_service_marker_set(self):
        return self.env.context.get('warranty_service_job_marker') is _SERVICE_JOB_MARKER

    @api.depends('warranty_card_id', 'entitlement_ids.warranty_card_id')
    def _compute_warranty_card_ids(self):
        for job in self:
            job.warranty_card_ids = job.warranty_card_id | job.entitlement_ids.warranty_card_id
    merge_type = fields.Selection(MERGE_TYPES, string='Free Services Type',
                                  compute='_compute_merge_type', store=True)
    state = fields.Selection(JOB_STATES, string='Status', default='draft', required=True,
                             readonly=True, copy=False, tracking=True, index=True)
    # Phase 4.2 - planning (SRS 2.5 / 10.5; approved D1-D4): one main responsible technician
    # (mandatory), several support technicians, manual assignment (no skill / AI assignment).
    planned_date = fields.Datetime(string='Planned Date', copy=False, tracking=True)
    # Flexible service dates (requirement 4): Job Creation Date = create_date, Planned Date,
    # Actual Completion Date (Complete Visit), Free Service Due Dates on the services.
    actual_completion_date = fields.Datetime(string='Actual Completion Date', readonly=True,
                                             copy=False)
    main_technician_id = fields.Many2one(
        'res.users', string='Main Technician', copy=False, tracking=True,
        domain="[('id', 'in', technician_candidate_ids)]")
    support_technician_ids = fields.Many2many(
        'res.users', 'warranty_service_job_support_user_rel', 'job_id', 'user_id',
        string='Support Technicians', copy=False, tracking=True,
        domain="[('id', 'in', technician_candidate_ids)]")
    technician_candidate_ids = fields.Many2many(
        'res.users', compute='_compute_technician_candidate_ids')
    # Phase 4.3: Field Service visits (tasks) of the job (SRS 10.5 Field Service Tasks / Visits).
    visit_ids = fields.One2many('project.task', 'warranty_service_job_id', string='Visits',
                                readonly=True)
    visit_count = fields.Integer(compute='_compute_visit_count')
    # Phase 4.4: worksheet instances (SRS 10.5 "Worksheet Instances").
    worksheet_ids = fields.One2many('warranty.job.worksheet', 'job_id', string='Worksheets',
                                    readonly=True)
    # Phase 4.8 (approved L3 / L10, SRS 2.8): reschedules = next visits planned after a visit
    # that was not completed (visit history: the visits themselves).
    reschedule_count = fields.Integer(string='Reschedule Count',
                                      compute='_compute_visit_count')
    cancel_reason = fields.Text(string='Cancellation Reason', readonly=True, copy=False)
    # Phase 4.9 (approved B3): Batch Eligible jobs may be completed with Complete Selected Jobs;
    # Single jobs only with Complete Visit. Set to Batch Eligible when a job is created (no
    # column default, so existing jobs are not rewritten; an empty value counts as Batch
    # Eligible).
    completion_mode = fields.Selection(COMPLETION_MODES, string='Completion Mode', copy=False,
                                       tracking=True)
    # Phase 4.10 (approved C2-C9): set by the trigger / inspection completion only.
    job_type = fields.Selection(JOB_TYPES, string='Job Type', default='warranty', required=True,
                                readonly=True, copy=False, tracking=True)
    chargeable_order_id = fields.Many2one('sale.order', string='Chargeable Order', readonly=True,
                                          copy=False, index='btree_not_null')
    inspection_diagnosis = fields.Text(string='Diagnosis', readonly=True, copy=False)
    inspection_repair_required = fields.Selection([('yes', 'Yes'), ('no', 'No')],
                                                  string='Repair Required', readonly=True,
                                                  copy=False)
    inspection_repair_details = fields.Text(string='Repair Details', readonly=True, copy=False)
    repair_quotation_id = fields.Many2one('sale.order', string='Repair Quotation', readonly=True,
                                          copy=False)
    # Approved C9: customer-approved excluded items of a Partial case, for the technician.
    approved_excluded_items = fields.Text(string='Customer-Approved Excluded Items',
                                          compute='_compute_approved_excluded_items')

    def _compute_approved_excluded_items(self):
        for job in self:
            # sudo: technicians may not read the case's excluded items; display only.
            items = job.sudo().warranty_case_id.excluded_item_ids.filtered(
                lambda item: item.customer_decision == 'approved')
            job.approved_excluded_items = '\n'.join(
                '%s - %s (confirmed qty %s)' % (item.coverage_item_id.name,
                                               item.product_id.display_name or '-',
                                               item.confirmed_qty) for item in items) or False

    @api.depends('visit_ids', 'shared_visit_ids')
    def _compute_visit_count(self):
        for job in self:
            # sudo: the visit count of the job (Helpdesk users may not read tasks); shared
            # Field Service visits count for every job on them.
            job.visit_count = len(job.sudo()._warranty_all_visits())
            job.reschedule_count = max(job.visit_count - 1, 0)

    @api.depends('entitlement_ids')
    def _compute_merge_type(self):
        for job in self:
            count = len(job.entitlement_ids)
            job.merge_type = 'none' if not count else 'single' if count == 1 else 'merged'

    @api.model
    def _technician_domain(self, company):
        """Approved D2: active Field Service users allowed in the job's company."""
        return [('share', '=', False), ('active', '=', True),
                ('groups_id', 'in', self.env.ref('industry_fsm.group_fsm_user').id),
                ('company_ids', 'in', company.id)]

    @api.depends('company_id')
    def _compute_technician_candidate_ids(self):
        Users = self.env['res.users']
        for job in self:
            job.technician_candidate_ids = Users.search(
                self._technician_domain(job.company_id)) if job.company_id else Users

    @api.constrains('main_technician_id', 'support_technician_ids')
    def _check_technicians(self):
        # active_test=False: archived users must be seen (and refused), not silently skipped.
        for job in self.with_context(active_test=False):
            technicians = job.main_technician_id | job.support_technician_ids
            if not technicians:
                continue
            allowed = self.env['res.users'].search(
                self._technician_domain(job.company_id) + [('id', 'in', technicians.ids)])
            invalid = technicians - allowed
            if invalid:
                raise ValidationError(_(
                    "Technicians of %(job)s must be active Field Service users of %(company)s: "
                    "%(users)s", job=job.name, company=job.company_id.name,
                    users=', '.join(invalid.mapped('name'))))
            if job.main_technician_id in job.support_technician_ids:
                raise ValidationError(_(
                    "%(user)s is the Main Technician of %(job)s and cannot also be a Support "
                    "Technician.", user=job.main_technician_id.name, job=job.name))

    def write(self, vals):
        context = self.env.context
        hold_marker = context.get('warranty_hold_marker') is _HOLD_MARKER
        visit_marker = context.get('warranty_visit_marker') is _VISIT_MARKER
        if 'state' in vals and ((vals['state'] in HOLD_STATES and not hold_marker) or (
                any(job.state in HOLD_STATES for job in self)
                and not (hold_marker or visit_marker))):
            raise UserError(_("Use Awaiting Parts / Workshop Repair / Resume Job (with a reason) to "
                              "put a service job on hold or resume it."))
        if 'state' in vals and not visit_marker and (
                vals['state'] in VISIT_STATES or any(job.state in VISIT_STATES for job in self)
                or (vals['state'] == 'cancelled'
                    and any(job.state not in CANCELLABLE_JOB_STATES for job in self))):
            raise UserError(_("Use Visit Not Completed, Plan Next Visit or Cancel Job (with a "
                              "reason) for this service job status."))
        if 'state' in vals \
                and self.env.context.get('warranty_completion_marker') is not _COMPLETION_MARKER \
                and (vals['state'] == 'completed' or any(job.state == 'completed' for job in self)):
            raise UserError(_("Service jobs are completed only with Complete Visit on their Field "
                              "Service visit (completion checks)."))
        if any(name in vals for name in CHARGEABLE_JOB_FIELDS) and not self.env.su \
                and context.get('warranty_completion_marker') is not _COMPLETION_MARKER:
            raise UserError(_("The job type, chargeable order and inspection result are set by "
                              "the chargeable workflow."))
        if ORIGIN_FIELDS & set(vals) and not self._warranty_service_marker_set():
            raise UserError(_("The origin and the warranty case of a service job are set by the "
                              "system (Prepare Service Job / Create or Link Helpdesk Ticket / warranty "
                              "case of the ticket)."))
        if 'completion_mode' in vals and any(job.state in CLOSED_JOB_STATES for job in self):
            raise UserError(_("The completion mode of a completed or cancelled service job cannot "
                              "be changed."))
        if any(name in vals for name in PLANNING_FIELDS) and not visit_marker \
                and any(job.state not in PLANNING_JOB_STATES for job in self):
            raise UserError(_("The planned date and the technicians can only be changed before "
                              "the service job is confirmed."))
        return super().write(vals)

    def action_prepare_for_confirmation(self):
        """Main Technician Assigned? -> Prepare Job for Confirmation (Draft -> Planned) or
        Block Job Confirmation (Part 4 diagram; approved D1: Planned Date mandatory)."""
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can plan service jobs."))
        for job in self:
            if job.state != 'draft':
                raise UserError(_("Only Draft service jobs can be prepared for confirmation "
                                  "(%s).", job.name))
            missing = []
            if not job.planned_date:
                missing.append(_("Planned Date"))
            if not job.main_technician_id:
                missing.append(_("Main Technician"))
            if missing:
                raise UserError(_("Job confirmation blocked for %(job)s: %(fields)s required.",
                                  job=job.name, fields=', '.join(missing)))
            job.state = 'planned'
            job._warranty_log_date_notes(job._warranty_service_day(job.planned_date),
                                         job.entitlement_ids,
                                         job._warranty_planned_date_problems())
            job._message_log(body=Markup('<p>%s</p>') % _(
                "Service job planned for %(date)s - Main Technician %(main)s%(support)s; ready "
                "for confirmation.", date=fields.Datetime.to_string(job.planned_date),
                main=job.main_technician_id.name,
                support=(_(", Support: %s", ', '.join(job.support_technician_ids.mapped('name')))
                         if job.support_technician_ids else '')))
        return True

    @api.model_create_multi
    def create(self, vals_list):
        marked = self._warranty_service_marker_set()
        for vals in vals_list:
            if not marked and (vals.get('job_origin', 'case') != 'case'
                               or vals.get('job_type') == 'warranty_inspection'
                               or (ORIGIN_FIELDS - {'warranty_case_id', 'job_origin'}) & set(vals)):
                raise UserError(_("Service-origin and inspection jobs are created with Create "
                                  "Service Job / Prepare Inspection Job."))
            if not self.env.su and not marked and (vals.get('chargeable_order_id') or vals.get(
                    'job_type', 'warranty') != 'warranty'):
                raise UserError(_("Chargeable jobs are created by the Job Trigger of their "
                                  "warranty case."))
            vals.setdefault('completion_mode', 'batch')
            if vals.get('name', 'New') == 'New':
                case = self.env['warranty.case'].browse(vals.get('warranty_case_id'))
                company = case.company_id or self.env['res.company'].browse(
                    vals.get('origin_company_id')) or self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'warranty.service.job') or 'New'
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_processed(self):
        if any(job.state not in ('draft', 'cancelled') for job in self):
            raise UserError(_("Only Draft or Cancelled service jobs can be deleted."))

    def action_cancel(self):
        """Cancel before confirmation (approved Q42): the case stays Approved, the free
        services go back to Not Merged (status unchanged, not consumed)."""
        for job in self:
            if job.state not in CANCELLABLE_JOB_STATES:
                raise UserError(_("Only Draft or Planned service jobs can be cancelled (%s).",
                                  job.name))
            services = job.entitlement_ids
            job.state = 'cancelled'
            services.write({'merge_status': 'not_merged'})
            if not job.warranty_case_id:
                text = _("Service job %s cancelled before confirmation (no ticket / case yet): "
                         "the free services are released, not consumed.", job.name)
            else:
                text = _("Service job %s cancelled before confirmation: the warranty case stays "
                         "unchanged, the free services are not consumed.", job.name)
            if services:
                text += ' ' + _("Merge Status reset to Not Merged: %s.",
                                ', '.join(services.mapped('name')))
            body = Markup('<p>%s</p>') % text
            job._message_log(body=body)
            if job.warranty_case_id:
                job.warranty_case_id._message_log(body=body)
        return True

    def action_view_warranty_history(self):
        self.ensure_one()
        return self.env['warranty.history']._warranty_open(
            [('card_id', 'in', self.warranty_card_ids.ids)])

    # ------------------------------------------------------------------ Phase 4.3
    def _warranty_confirm_problems(self):
        """Confirm Service Job checks: Planned, main technician and date, Helpdesk Ticket
        Exists? (case ticket, not closed - approved G5), Validate Mandatory Process Chain."""
        self.ensure_one()
        problems = []
        if self.state != 'planned':
            problems.append(_("the service job must be Planned"))
        if not self.planned_date or not self.main_technician_id:
            problems.append(_("Planned Date and Main Technician are required"))
        problems += self._warranty_worksheet_template_problems()
        ticket = self.helpdesk_ticket_id
        case = self.warranty_case_id
        if not case and ticket:
            problems.append(_("no warranty case yet: create the Free Service warranty case on "
                              "ticket %s with the job's free services (Warranty Cases > New)",
                              ticket.display_name))
        elif not case:
            problems.append(_("no Helpdesk ticket and warranty case yet: use Create or Link "
                              "Helpdesk Ticket, then create its warranty case"))
        elif not ticket:
            problems.append(_("no Helpdesk ticket"))
        elif ticket.fold:
            problems.append(_("Helpdesk ticket %s is closed: reopen it first", ticket.display_name))
        elif self.job_type not in ('warranty', 'warranty_inspection'):
            # Approved C4: no warranty eligibility; the commercial trigger is revalidated.
            if ticket != case.helpdesk_ticket_id or ticket.company_id != self.company_id \
                    or case.state != 'chargeable':
                problems.append(_("the Helpdesk ticket -> warranty case -> service job chain is "
                                  "not valid (case %s must be Chargeable)", case.name))
            elif self.chargeable_order_id not in case._warranty_trigger_orders():
                problems.append(_("the Job Trigger of order %s is no longer met (cancelled, "
                                  "not confirmed or not fully paid)",
                                  self.chargeable_order_id.sudo().name))
        elif self.job_origin == 'service' \
                and case.service_entitlement_ids != self.entitlement_ids:
            problems.append(_("the free services of the job and of warranty case %s differ: "
                              "cancel the job (or reject the case) and create it again with the "
                              "eligible services", case.name))
        elif ticket != case.helpdesk_ticket_id or ticket.company_id != self.company_id \
                or not self._warranty_case_ready():
            problems.append(_("the Helpdesk ticket -> warranty case -> service job chain is not "
                              "valid (case %(case)s must be %(state)s)", case=case.name,
                              state=self._warranty_case_ready_label()))
        return problems

    def _warranty_case_ready(self):
        """Case status required to confirm the job: Approved (Helpdesk-first route);
        Eligible without general approval (service-origin route, approved D-A); preliminary
        check passed and Case Type still to be determined (warranty inspection)."""
        self.ensure_one()
        case = self.warranty_case_id
        if self.job_type == 'warranty_inspection':
            return case.state == 'eligibility_checked' and not case.case_type \
                and case.eligibility_result == 'preliminary_passed'
        if self.job_origin == 'service':
            return case.state in ('eligibility_checked', 'approved') \
                and case.eligibility_result == 'eligible'
        return case.state == 'approved'

    def _warranty_case_ready_label(self):
        if self.job_type == 'warranty_inspection':
            return _("Eligibility Checked with result Preliminary Passed")
        if self.job_origin == 'service':
            return _("Eligible")
        return _("Approved")

    def _warranty_expected_revalidation(self):
        """Expected result of the Q41 revalidation at confirmation."""
        self.ensure_one()
        return 'preliminary_passed' if self.job_type == 'warranty_inspection' else 'eligible'

    def action_confirm_job(self):
        """Confirm Service Job (Part 4 diagram; approved Q41, G1, G5, D5, D7, D9, D13):
        eligibility revalidated (failure: blocked, logged, case unchanged), Field Service task
        created in the warranty Field Service project and linked to case / job / ticket / free
        services with planned date and technicians, free services Job Created, job Confirmed,
        case Job Created. Worksheet instances: Phase 4.4."""
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can confirm service jobs."))
        refused = self.browse()
        for job in self:
            problems = job._warranty_confirm_problems()
            if problems:
                raise UserError(_("%(job)s cannot be confirmed: %(problems)s.", job=job.name,
                                  problems='; '.join(problems)))
            case = job.warranty_case_id
            if job.job_type not in ('warranty', 'warranty_inspection'):
                job._warranty_create_visit()
                continue
            ok, result, steps = job._warranty_revalidate()
            if not ok:
                labels = dict(case._fields['eligibility_result']._description_selection(self.env))
                lines = Markup('').join(Markup('<li>%s %s</li>') % ('✔' if ok else '✘', text)
                                        for ok, text in steps)
                body = Markup('<p><b>%s</b></p><ul>%s</ul>') % (_(
                    "Confirmation of %(job)s blocked by the eligibility revalidation (%(result)s)",
                    job=job.name, result=labels.get(result, result)), lines)
                job._message_log(body=body)
                case.sudo()._message_log(body=body)
                refused |= job
                continue
            job._warranty_create_visit()
        if refused:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'sticky': True,
                    'title': _("Service job not confirmed"),
                    'message': _("The eligibility revalidation of %s failed - see the chatter.",
                                 ', '.join(refused.mapped('name'))),
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        return True

    def _warranty_revalidate(self):
        """Q41 revalidation, same checks as Check Eligibility; sudo + revalidation context:
        read-only checks, no new approval requests; the case is not modified (D7). Returns
        (ok, result, steps)."""
        self.ensure_one()
        result, steps, __, __ = self.warranty_case_id.sudo().with_context(
            warranty_revalidation=True)._warranty_run_checks()
        return result == self._warranty_expected_revalidation(), result, steps

    def _warranty_create_visit_task(self, visit_no):
        """Field Service visit of the job with its planned date and technicians (4.3; next
        visits 4.8: same free services, High priority - approved R5)."""
        self.ensure_one()
        case = self.warranty_case_id
        project = self.company_id._warranty_fsm_project()
        title = ' - '.join(part for part in (self.name, case.name, case.product_id.display_name)
                           if part)
        vals = {
            'name': title if visit_no == 1 else _("%(title)s - Visit %(no)s", title=title,
                                                  no=visit_no),
            'project_id': project.id,
            'company_id': self.company_id.id,
            'partner_id': (case.site_id or case.partner_id).id,
            'planned_date_begin': self.planned_date,
            'user_ids': [(6, 0, (self.main_technician_id | self.support_technician_ids).ids)],
            'helpdesk_ticket_id': self.helpdesk_ticket_id.id,
            'warranty_service_job_id': self.id,
            'warranty_entitlement_ids': [(6, 0, self.entitlement_ids.ids)],
            'warranty_visit_no': visit_no,
            'description': case.customer_complaint,
        }
        if visit_no > 1:
            vals['priority'] = '1'
        # sudo: Helpdesk users confirm / plan jobs but may have no Field Service rights; the task
        # is the mandatory output of this checked action (the only path for warranty tasks); the
        # acting user stays the creator (create_uid).
        return self.env['project.task'].sudo().create(vals)

    def _warranty_create_visit(self, task=None):
        """Confirmation output: the job's own visit 1, or its part of a shared Field Service
        visit (`task`)."""
        self.ensure_one()
        case = self.warranty_case_id
        services = self.entitlement_ids
        shared = bool(task)
        task = task or self._warranty_create_visit_task(1)
        sheets = self._warranty_create_worksheets(task)
        for service in services:
            service.write({'job_previous_state': service.state, 'state': 'job_created'})
        self.state = 'confirmed'
        # sudo: the case status is set by the confirmation (Approved -> Job Created).
        case.sudo().state = 'job_created'
        body = Markup('<p><b>%s</b></p>') % (_(
            "Service job %(job)s confirmed: shared Field Service visit %(task)s with %(jobs)s "
            "(planned %(date)s, Main Technician %(main)s)%(services)s.", job=self.name,
            task=task.name, jobs=', '.join((task.warranty_shared_job_ids - self).mapped('name')),
            date=format_datetime(self.env, self.planned_date, dt_format='short'),
            main=self.main_technician_id.name,
            services=(_("; free services Job Created: %s", ', '.join(services.mapped('name')))
                      if services else '')) if shared else _(
            "Service job %(job)s confirmed: Field Service task %(task)s created (visit 1, planned "
            "%(date)s, Main Technician %(main)s)%(services)s.", job=self.name, task=task.name,
            date=format_datetime(self.env, self.planned_date, dt_format='short'),
            main=self.main_technician_id.name,
            services=(_("; free services Job Created: %s", ', '.join(services.mapped('name')))
                      if services else ''))) + Markup('<p>%s</p>') % _(
            "Worksheet instances: %s.", ', '.join(sheets.mapped('name')))
        self._message_log(body=body)
        case.sudo()._message_log(body=body)
        for service in services:
            service._message_log(body=Markup('<p>%s</p>') % _(
                "Job Created: service job %(job)s confirmed (task %(task)s).", job=self.name,
                task=task.name))
        return task

    def action_view_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Visits"),
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.sudo()._warranty_all_visits().ids)],
            'context': {'create': False},
        }

    # ------------------------------------------------------------------ shared visit (v1)
    def _warranty_all_visits(self):
        """Own visits and shared Field Service visits of the job."""
        self.ensure_one()
        return self.visit_ids | self.shared_visit_ids

    def _warranty_is_visit_of(self, task):
        return task.warranty_service_job_id == self or self in task.warranty_shared_job_ids

    def _warranty_shared_line(self, task):
        """The job's line on a shared visit (empty for its own visits)."""
        return task.warranty_shared_line_ids.filtered(lambda line: line.job_id == self)

    def _warranty_visit_services(self, task):
        """The free services of the visit that belong to this job."""
        if task.warranty_shared_job_ids:
            return task.warranty_entitlement_ids & self.entitlement_ids
        return task.warranty_entitlement_ids

    def _warranty_visit_sheets(self, task):
        return task.warranty_worksheet_ids.filtered(lambda sheet: sheet.job_id == self)

    def _warranty_visit_closed(self, task):
        """Closed for this job: the visit is closed, or the job's outcome on a shared visit is
        recorded (approved Q5 / Q7)."""
        line = self._warranty_shared_line(task)
        return bool(line.outcome) or task.fsm_done or task.state in ('1_done', '1_canceled')

    def _warranty_open_shared_visits(self):
        """Shared visits on which the job has no outcome yet."""
        self.ensure_one()
        return self.sudo().shared_visit_ids.filtered(
            lambda task: not self._warranty_visit_closed(task))

    def _warranty_record_shared_outcome(self, task, vals):
        """Record the job's outcome on a shared visit; the visit closes when every job on it
        has its outcome (approved Q7)."""
        self._warranty_shared_line(task)._warranty_record(vals)
        task._warranty_close_shared_visit()

    # ------------------------------------------------------------------ Phase 4.4
    def _warranty_create_worksheets(self, task):
        """Create Worksheet Instance(s) (Part 4 diagram; approved W1-W6): one per linked free
        service, or one for the case product (Warranty Only); template: the free service's
        template, else the product's Worksheet Template, else the Field Service project's
        default (none: instance without checklist, W2); usage-based warranty: usage reading
        required (blocking in 4.5, G9). Not created twice for the same task."""
        self.ensure_one()
        Sheet = self.env['warranty.job.worksheet']
        existing = self.worksheet_ids.filtered(lambda sheet: sheet.task_id == task)
        if existing:
            return existing
        vals_list = []
        for service, unit, product, template in self._warranty_worksheet_lines(task.project_id):
            # Usage basis of the worksheet's own card (cross-card merge).
            card = unit.warranty_card_id or service.warranty_card_id or self.warranty_card_id
            usage = card.warranty_basis == 'usage'
            vals_list.append({
                'job_id': self.id, 'task_id': task.id, 'entitlement_id': service.id,
                'unit_id': unit.id, 'product_id': product.id, 'template_id': template.id,
                'usage_required': usage, 'usage_unit': card.usage_unit if usage else False,
            })
        # sudo: created by the checked confirmation (as the task, approved security a).
        sheets = Sheet.sudo().create(vals_list)
        if len(sheets) == 1 and sheets.template_id.sudo().res_model == 'project.task' \
                and not task.warranty_shared_job_ids:
            # Approved W4: one instance -> the standard task Worksheet button uses its template.
            task.sudo().worksheet_template_id = sheets.template_id
        return sheets.with_env(self.env)

    def _warranty_worksheet_lines(self, project=None):
        """(free service, product, template) of the worksheet instances of a visit (approved
        W1-W3): one per linked free service, or one for the case product (Warranty Only);
        template: the free service's, else the product's Worksheet Template, else the Field
        Service project's default."""
        self.ensure_one()
        case = self.warranty_case_id
        project = project or self.company_id._warranty_fsm_project()
        default_template = project.sudo().worksheet_template_id
        Unit = self.env['warranty.unit']
        lines = []
        for service in self.entitlement_ids:
            # Approved D4: one worksheet per selected unit of the service's own card (Units to
            # Service); cases without selection keep one worksheet per service.
            units = case.service_unit_ids.filtered(
                lambda unit: unit.warranty_card_id == service.warranty_card_id)
            for unit in units:
                lines.append((service, unit, unit.product_id))
            if not units:
                lines.append((service, Unit,
                              service.warranty_card_id.product_id or case.product_id))
        if not lines:
            lines.append((self.env['warranty.service.entitlement'], Unit,
                          case.product_id or self.warranty_card_id.product_id))
        if self.job_type == 'warranty_inspection' and self.company_id.warranty_inspection_template_id:
            # Inspection of an undetermined case (approved G2): the company inspection template.
            template = self.company_id.warranty_inspection_template_id
            return [(service, unit, product, template) for service, unit, product in lines]
        # Template: the free service's (single-product card) unless its unit has another
        # product, else the product's Worksheet Template, else the project default.
        lines = [(service, unit, product,
                  (service.worksheet_template_id if not unit or not service.warranty_card_id
                   .product_id or unit.product_id == service.warranty_card_id.product_id
                   else self.env['worksheet.template'])
                  or product.product_tmpl_id.warranty_worksheet_template_id or default_template)
                 for service, unit, product in lines]
        # A Field Service (task) template used by several instances of the visit (e.g. an older
        # free service snapshot) gives way to the product's Warranty Worksheet template; without
        # one the conflict stays and is blocked by _warranty_worksheet_template_problems.
        templates = [template for __, __, __, template in lines]
        resolved = []
        for service, unit, product, template in lines:
            product_template = product.product_tmpl_id.warranty_worksheet_template_id
            if template and template.sudo().res_model == 'project.task' \
                    and templates.count(template) > 1 \
                    and product_template.sudo().res_model == 'warranty.job.worksheet':
                template = product_template
            resolved.append((service, unit, product, template))
        return resolved

    def _warranty_worksheet_template_problems(self):
        """Approved shared-worksheet fix: a Field Service (task) worksheet template holds one
        record per task, so it cannot serve several worksheet instances of one visit (their
        answers must stay independent); a Warranty Worksheet template is required then."""
        self.ensure_one()
        if not self.company_id:
            return []
        templates = [template for __, __, __, template in self._warranty_worksheet_lines()
                     if template and template.sudo().res_model == 'project.task']
        duplicates = {template for template in templates if templates.count(template) > 1}
        return [_("worksheet template %s would be used by several worksheet instances of one "
                  "visit; a Field Service worksheet template holds only one checklist per task. "
                  "Set a Warranty Worksheet template (Warranty > Configuration > Warranty "
                  "Worksheet Templates) on the product; it is then used instead", template.name)
                for template in duplicates]

    def action_view_worksheets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Worksheets"),
            'res_model': 'warranty.job.worksheet',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
            'context': {'create': False},
        }

    # ------------------------------------------------------------------ Phase 4.5
    def _warranty_start_visit(self, task):
        """Technician Starts Field Service Visit (approved V2): on the first timer start of a
        visit of a Confirmed job, job -> In Progress, its free services Job Created -> In
        Progress, the visit's worksheets To Do -> In Progress; the case stays Job Created.
        Later starts change nothing."""
        self.ensure_one()
        # Phase 4.8: also the next visit of a Rescheduled job.
        if self.state not in ('confirmed', 'rescheduled'):
            return False
        services = self._warranty_visit_services(task).filtered(
            lambda s: s.state == 'job_created')
        sheets = self._warranty_visit_sheets(task).filtered(lambda sheet: sheet.state == 'todo')
        self.with_context(warranty_visit_marker=_VISIT_MARKER).state = 'in_progress'
        # sudo: technicians start visits; the free service / worksheet statuses follow the job.
        services.sudo().write({'state': 'in_progress'})
        sheets.sudo().write({'state': 'in_progress'})
        body = Markup('<p>%s</p>') % _(
            "Visit %(task)s started by %(user)s: service job In Progress%(services)s; worksheets "
            "In Progress: %(sheets)s.", task=task.name, user=self.env.user.name,
            services=(_("; free services In Progress: %s", ', '.join(services.mapped('name')))
                      if services else ''),
            sheets=', '.join(sheets.mapped('name')) or _("none"))
        self._message_log(body=body)
        # sudo: technicians may not read the warranty case; audit note only.
        self.warranty_case_id.sudo()._message_log(body=body)
        for service in services:
            service.sudo()._message_log(body=body)
        return True

    # ------------------------------------------------------------------ Phase 4.6
    def action_open_hold_wizard(self):
        """Awaiting Parts / Workshop Repair / Resume Job buttons: reason wizard (approved M1)."""
        self.ensure_one()
        self._warranty_check_hold_access()
        hold_action = self.env.context.get('warranty_hold_action')
        return {
            'type': 'ir.actions.act_window',
            'name': dict(self.env['warranty.service.job.hold.wizard']._fields['hold_action']
                         ._description_selection(self.env)).get(hold_action),
            'res_model': 'warranty.service.job.hold.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_job_id': self.id, 'default_hold_action': hold_action},
        }

    def _warranty_check_hold_access(self):
        # Approved M7: Field Service and Helpdesk users (company: record rule).
        if not (self.env.user.has_group('helpdesk.group_helpdesk_user')
                or self.env.user.has_group('industry_fsm.group_fsm_user')):
            raise AccessError(_("Only Field Service and Helpdesk users can put service jobs on "
                                "hold or resume them."))

    def _warranty_set_hold(self, hold_action, reason):
        """Material / Parts Blocking Job? / Repair / Workshop Required? (Part 4 diagram;
        approved M1-M3, M8): In Progress -> Awaiting Parts / Workshop, and back with Resume Job.
        Free services stay In Progress (not consumed), the case status, the visit, its timer and
        timesheets are not changed; notes on job and case."""
        self.ensure_one()
        self._warranty_check_hold_access()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required."))
        labels = dict(self._fields['state']._description_selection(self.env))
        if hold_action == 'resume':
            if self.state not in HOLD_STATES:
                raise UserError(_("Only service jobs Awaiting Parts or in Workshop can be resumed "
                                  "(%(job)s is %(state)s).", job=self.name,
                                  state=labels[self.state]))
            new_state = 'in_progress'
        else:
            if self.state != 'in_progress':
                raise UserError(_("Only service jobs In Progress can be put on hold (%(job)s is "
                                  "%(state)s).", job=self.name, state=labels[self.state]))
            if self.job_type == 'warranty_inspection':
                raise UserError(_("Inspection job %s is not put on hold: complete the inspection "
                                  "and decide the Case Type first.", self.name))
            new_state = hold_action
        old_state = self.state
        self.with_context(warranty_hold_marker=_HOLD_MARKER).write({'state': new_state})
        body = Markup('<p>%s</p>') % _(
            "Service job %(job)s: %(old)s -> %(new)s by %(user)s. Reason: %(reason)s",
            job=self.name, old=labels[old_state], new=labels[new_state],
            user=self.env.user.name, reason=reason)
        self._message_log(body=body)
        # sudo: technicians may not read the warranty case; audit note only (M3 option B: the
        # case status is not changed).
        self.warranty_case_id.sudo()._message_log(body=body)
        return True

    def _warranty_completion_blockers(self):
        """Reasons that prevent the warranty completion (Part 4.7 uses this; approved M6)."""
        self.ensure_one()
        if self.state in HOLD_STATES:
            return [_("Service job %(job)s is %(state)s: resume it first.", job=self.name,
                      state=dict(self._fields['state']._description_selection(self.env))
                      [self.state])]
        return []

    # ------------------------------------------------------------------ Phase 4.7
    def _warranty_check_completion_access(self):
        # Approved K10: Field Service and Helpdesk users; the company is checked by the job's
        # record rule (write access as the user).
        if not (self.env.user.has_group('helpdesk.group_helpdesk_user')
                or self.env.user.has_group('industry_fsm.group_fsm_user')):
            raise AccessError(_("Only Field Service and Helpdesk users can complete warranty "
                                "visits."))
        self.check_access('write')

    def _warranty_visit_completion_problems(self, task):
        """Customer Sign-off Required? / Check Visit Outcome / Validate Completion Requirements
        (Part 4 diagram; approved K2-K4, M6): every problem, listed at once."""
        self.ensure_one()
        if self.state == 'completed' or self._warranty_visit_closed(task):
            return [_("Visit %(task)s of service job %(job)s is already closed.", task=task.name,
                      job=self.name)]
        problems = self._warranty_completion_blockers()
        if not problems and self.state != 'in_progress':
            problems.append(_(
                "The visit has not been started: service job %(job)s must be In Progress (it is "
                "%(state)s).", job=self.name,
                state=dict(self._fields['state']._description_selection(self.env))[self.state]))
        # Approved K4: the technician stops the timer (the standard timer records the timesheet;
        # timesheets are never changed here). sudo: timers of all users of the visit.
        timers = self._warranty_running_timers(task)
        if timers:
            problems.append(_("Stop the timer of visit %(task)s first (running for %(users)s).",
                              task=task.name, users=', '.join(timers.user_id.mapped('name'))))
        if self.company_id.warranty_signoff_required and not task.worksheet_signature:
            problems.append(_("Customer sign-off is required: use Sign Report on visit %s.",
                              task.name))
        problems += self._warranty_completion_date_problems(task)
        for sheet in self._warranty_visit_sheets(task):
            problems += sheet._warranty_completion_problems()
        return problems

    def _warranty_complete_visit(self, task, batch=False, inspection=None):
        """Complete Visit (Part 4 diagram "Mark Field Service Visit Done" ... "Update Warranty
        History"; approved K1-K10): after the checks, in one savepoint: visit Done (outcome
        Completed) through the reserved close path, worksheets Completed, service job Completed,
        the visit's free services Completed (consumed once: Part 2 counts Completed services for
        Used / Balance), warranty case Completed (the Helpdesk ticket stays open), history
        notes. Warranty Only jobs consume nothing."""
        self.ensure_one()
        self._warranty_check_completion_access()
        # sudo: Helpdesk users complete visits without Field Service rights (approved K10); the
        # access to the job was checked above as the user.
        task = task.sudo()
        if not self._warranty_is_visit_of(task):
            raise UserError(_("%(task)s is not a visit of service job %(job)s.", task=task.name,
                              job=self.name))
        problems = self._warranty_visit_completion_problems(task)
        if self.job_type == 'chargeable_inspection':
            problems += self._warranty_inspection_problems(inspection)
        elif self.job_type == 'warranty_inspection':
            problems += self._warranty_case_type_problems(inspection, findings=True)
        if problems:
            raise UserError(_("Visit %(task)s cannot be completed:\n%(problems)s", task=task.name,
                              problems='\n'.join('- %s' % problem for problem in problems)))
        # Shared visit (approved v1): only this job's worksheets and free services.
        sheets = self._warranty_visit_sheets(task)
        # Already completed services are never completed (consumed) twice.
        services = self._warranty_visit_services(task).filtered(lambda s: s.state != 'completed')
        today = self.company_id._warranty_today()
        warnings = self._warranty_completion_date_warnings(today, services)
        marker = {'warranty_completion_marker': _COMPLETION_MARKER}
        # Requirement 5: all or nothing (also when a caller catches an error).
        with self.env.cr.savepoint():
            now = fields.Datetime.now()
            if task.warranty_shared_job_ids:
                # Approved Q4: the visit's customer sign-off, traceable on every job.
                self._warranty_record_shared_outcome(task, {
                    'outcome': 'completed', 'completion_date': now,
                    'signed_by': task.worksheet_signed_by or False})
            else:
                task._warranty_close_visits({'fsm_done': True, 'state': '1_done',
                                             'warranty_visit_outcome': 'completed',
                                             'warranty_completion_date': now})
            # sudo (task above): the worksheet / free service / case statuses follow the
            # validated completion.
            sheets.with_context(**marker).write({'state': 'completed'})
            services.with_context(**marker).write({'state': 'completed',
                                                   'merge_status': 'completed'})
            self.with_context(**marker).write({'state': 'completed',
                                               'actual_completion_date': now})
            self._warranty_log_date_notes(today, services, warnings)
            case_text = self._warranty_complete_case(inspection)
            self._warranty_log_completion(task, sheets, services, batch=batch, case_text=case_text)
        if warnings and not batch:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'sticky': True,
                    'title': _("Visit completed outside the permitted service dates"),
                    'message': '\n'.join(warnings),
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        return True

    def _warranty_case_type_problems(self, inspection, findings=False):
        """Optional Case Type (approved G2): the inspection of an undetermined case records the
        findings and the final Case Type."""
        inspection = inspection or {}
        problems = []
        if inspection is None or not inspection:
            return [_("Use Complete Inspection on the visit: findings and the final Case Type "
                      "are required.")]
        if findings and not (inspection.get('diagnosis') or '').strip():
            problems.append(_("Record the inspection findings."))
        if not self.warranty_case_id.case_type and not inspection.get('case_type'):
            problems.append(_("Select the final Case Type of the warranty case."))
        elif inspection.get('case_type') == 'free_service':
            problems.append(_("A free service request is not decided by an inspection (Free "
                              "Service cases are typed when created)."))
        return problems

    def _warranty_inspection_problems(self, inspection):
        """Approved C7: Diagnosis and Repair Required (Yes / No) at inspection completion;
        Repair Details when a repair is required."""
        inspection = inspection or {}
        problems = []
        if inspection and not self.warranty_case_id.case_type:
            problems += self._warranty_case_type_problems(inspection)
        if not (inspection.get('diagnosis') or '').strip():
            problems.append(_("Record the inspection result: the diagnosis is required."))
        if inspection.get('repair_required') not in ('yes', 'no'):
            problems.append(_("Record the inspection result: is a repair required?"))
        elif inspection['repair_required'] == 'yes' \
                and not (inspection.get('repair_details') or '').strip():
            problems.append(_("Record the inspection result: repair details are required."))
        return problems

    def _warranty_complete_case(self, inspection=None):
        """Case status at job completion (approved K6, C7, C12): Warranty -> Completed;
        Inspection without repair -> Completed (inspection only); Inspection with repair ->
        back to Chargeable (type Repair) with a draft repair quotation; Repair / Excluded Items
        -> Completed. Returns the case line of the completion note."""
        # sudo: the case status follows the validated completion.
        case = self.warranty_case_id.sudo()
        marker = {'warranty_completion_marker': _COMPLETION_MARKER}
        if self.job_type == 'warranty_inspection':
            self.sudo().with_context(**marker).write(
                {'inspection_diagnosis': inspection['diagnosis'].strip()})
            case._warranty_apply_inspection(self, inspection)
            return _("Inspection completed: warranty case %(case)s back to New with Case Type "
                     "%(type)s - check eligibility, coverage and approval for that type. "
                     "Findings: %(findings)s", case=case.name, type=case._warranty_case_type_label(),
                     findings=self.inspection_diagnosis)
        if self.job_type == 'chargeable_inspection' and not case.case_type \
                and inspection.get('case_type') not in ('chargeable_inspection',
                                                        'chargeable_repair'):
            # Undetermined case, paid inspection (approved G1): a warranty Case Type found on
            # site goes back to the full warranty eligibility.
            self.sudo().with_context(**marker).write(
                {'inspection_diagnosis': inspection['diagnosis'].strip(),
                 'inspection_repair_required': inspection['repair_required']})
            case._warranty_apply_inspection(self, inspection)
            return _("Paid inspection completed: warranty case %(case)s back to New with Case "
                     "Type %(type)s for the warranty eligibility check. Diagnosis: "
                     "%(findings)s", case=case.name, type=case._warranty_case_type_label(),
                     findings=self.inspection_diagnosis)
        if self.job_type == 'chargeable_inspection' and not case.case_type:
            case._warranty_apply_inspection(self, inspection, keep_state=True)
        if self.job_type == 'chargeable_inspection':
            self.sudo().with_context(**marker).write({
                'inspection_diagnosis': inspection['diagnosis'].strip(),
                'inspection_repair_required': inspection['repair_required'],
                'inspection_repair_details': (inspection.get('repair_details') or '').strip()
                or False,
            })
            if inspection['repair_required'] == 'yes':
                case.write({'state': 'chargeable', 'chargeable_type': 'repair'})
                order = self._warranty_create_repair_quotation()
                self.sudo().with_context(**marker).write({'repair_quotation_id': order.id})
                return _("Repair required: warranty case %(case)s back to Chargeable (Repair); "
                         "draft repair quotation %(order)s to price and send; the repair job is "
                         "created by the Job Trigger. Diagnosis: %(diagnosis)s",
                         case=case.name, order=order.name, diagnosis=self.inspection_diagnosis)
            case.with_context(**marker).write({'state': 'completed',
                                                 'warranty_chargeable_outcome': 'inspection_only'})
            return _("No repair needed: warranty case %(case)s Completed (inspection only; Closed "
                     "after the accounting steps, Part 8). Diagnosis: %(diagnosis)s",
                     case=case.name, diagnosis=self.inspection_diagnosis)
        if self.job_type == 'warranty':
            case.with_context(**marker).write({'state': 'completed'})
            return _("Warranty case %s: Completed (the Helpdesk ticket stays open).", case.name)
        outcome = 'repair_completed' if self.job_type == 'chargeable_repair' \
            else 'service_completed'
        case.with_context(**marker).write({'state': 'completed',
                                             'warranty_chargeable_outcome': outcome})
        return _("Warranty case %s: Completed (chargeable; the Helpdesk ticket stays open; Closed "
                 "after the accounting steps, Part 8).", case.name)

    def _warranty_create_repair_quotation(self):
        """Draft Repair Quotation (SRS 9.7 step 6, approved C7.4): the diagnosis and repair
        details as an informational note line; never sent or confirmed automatically.
        sudo: created by the inspection completion (technicians have no Sales rights); the
        salesperson prices and sends it."""
        case = self.warranty_case_id.sudo()
        commercial = case.partner_id.commercial_partner_id
        note = _("Inspection %(job)s - Diagnosis: %(diagnosis)s\nRepair: %(details)s",
                 job=self.name, diagnosis=self.inspection_diagnosis,
                 details=self.inspection_repair_details)
        return self.env['sale.order'].sudo().with_company(case.company_id).create({
            'partner_id': commercial.id,
            'partner_shipping_id': (case.site_id or commercial).id,
            'company_id': case.company_id.id,
            'origin': '%s / %s' % (case.name, self.name),
            'warranty_case_id': case.id,
            'order_line': [(0, 0, {'display_type': 'line_note', 'name': note})],
        })

    def _warranty_log_completion(self, task, sheets, services, batch=False, case_text=None):
        """Update Warranty History (approved K8 / K9): notes on the job, case, card(s) and the
        consumed free services; the usage reading stays on the worksheet (not written to the
        card or the unit)."""
        units = dict(sheets._fields['usage_unit']._description_selection(self.env))
        readings = ['%s: %s %s' % (sheet.name, sheet.current_usage, units.get(sheet.usage_unit, ''))
                    for sheet in sheets if sheet.usage_required and sheet.current_usage]
        # sudo: technicians may not read the case / card / free services; history notes only.
        case = self.warranty_case_id.sudo()
        cards = (self.warranty_card_id | services.warranty_card_id).sudo()
        if task.worksheet_signature:
            signoff = task.worksheet_signed_by or _("signed")
        else:
            signoff = _("not required")
        lines = [
            _("Outcome: Completed."),
            _("Customer sign-off: %s.", signoff),
            _("Worksheets completed: %s.", ', '.join(sheets.mapped('name')) or _("none")),
        ]
        if readings:
            lines.append(_("Usage reading: %s.", '; '.join(readings)))
        if services:
            lines.append(_("Free services consumed: %(services)s (%(cards)s).",
                           services=', '.join(services.mapped('name')),
                           cards='; '.join([_("card %(card)s: used %(used)s, balance %(balance)s",
                                              card=card.name, used=card.free_services_used,
                                              balance=card.free_services_balance)
                                            for card in cards])))
        else:
            lines.append(_("No free service linked (warranty claim only): nothing consumed."))
        lines.append(case_text or _("Warranty case %s: Completed (the Helpdesk ticket stays "
                                    "open).", case.name))
        title = _("Visit %(task)s completed by %(user)s: service job %(job)s Completed.",
                  task=task.name, user=self.env.user.name, job=self.name)
        if batch:
            title = _("%s (batch completion: Complete Selected Jobs)", title)
        body = Markup('<p><b>%s</b></p><ul>%s</ul>') % (title,
            Markup('').join(Markup('<li>%s</li>') % line for line in lines))
        self._message_log(body=body)
        case._message_log(body=body)
        for card in cards:
            card._message_log(body=body)
        for service in services.sudo():
            service._message_log(body=Markup('<p>%s</p>') % _(
                "Completed and consumed: service job %(job)s, visit %(task)s.", job=self.name,
                task=task.name))

    # ------------------------------------------------------------------ Phase 4.8
    def _warranty_running_timers(self, tasks):
        """Running or paused timers of all users on the visits or their timesheets (the
        technician stops them; timesheets are never changed here). sudo: timers of all users."""
        Timer = self.env['timer.timer'].sudo()
        tasks = tasks.sudo()
        timers = Timer.search([('res_model', '=', 'project.task'), ('res_id', 'in', tasks.ids)])
        if tasks.timesheet_ids:
            timers |= Timer.search([('res_model', '=', 'account.analytic.line'),
                                    ('res_id', 'in', tasks.timesheet_ids.ids)])
        return timers

    def _warranty_check_visit_access(self, planning=False):
        """Approved L9: technicians and Helpdesk users report non-completion; only Helpdesk
        users plan the next visit (date / technicians) or cancel the job. Company: record rule
        (write access as the user)."""
        user = self.env.user
        if planning and not user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can plan the next visit or cancel a service "
                                "job."))
        if not (user.has_group('helpdesk.group_helpdesk_user')
                or user.has_group('industry_fsm.group_fsm_user')):
            raise AccessError(_("Only Field Service and Helpdesk users can report a visit as not "
                                "completed."))
        self.check_access('write')

    def _warranty_history(self, body, services=None):
        """Warranty history notes (approved L10 / K8): job, case, card(s), free services."""
        self._message_log(body=body)
        # sudo: technicians may not read the case / card / free services; history notes only.
        self.warranty_case_id.sudo()._message_log(body=body)
        services = (services if services is not None else self.entitlement_ids).sudo()
        for card in (self.warranty_card_id | services.warranty_card_id).sudo():
            card._message_log(body=body)
        for service in services:
            service._message_log(body=body)

    def _warranty_todo(self, summary, note):
        """Approved L4: Helpdesk To-Do instead of an automatic customer notification (SRS 2.8
        customer notification: deviation pending BA). For the ticket's assigned user, else the
        job's creator; no duplicate open To-Do."""
        user = self.helpdesk_ticket_id.user_id or self.create_uid
        if not user or self.activity_ids.filtered(
                lambda activity: activity.user_id == user and activity.summary == summary):
            return
        self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=summary,
                               note=note)

    def _warranty_visit_not_completed(self, task, reason, notes, next_action, planning=None):
        """Visit Completed? No -> Select Non-completion Reason -> Reschedule Required? / Visit
        Cancelled? / Keep Job Open for Follow-up (Part 4 diagram, SRS 2.8; approved L1-L10):
        the visit is closed (Odoo status Cancelled, never Done) through the reserved close path
        with its Visit Outcome and reason; free services stay open and unconsumed, the ticket
        stays open. Reschedule / follow-up: job Incomplete (Helpdesk users may plan the next
        visit at once: job Rescheduled). Cancel: Cancel Job (L5)."""
        self.ensure_one()
        self._warranty_check_visit_access(planning=bool(planning))
        # sudo: Helpdesk users may have no Field Service rights; the job access is checked above.
        task = task.sudo()
        if not self._warranty_is_visit_of(task):
            raise UserError(_("%(task)s is not a visit of service job %(job)s.", task=task.name,
                              job=self.name))
        if self._warranty_visit_closed(task) or self.state not in OPEN_VISIT_JOB_STATES:
            raise UserError(_("Visit %(task)s of service job %(job)s is already closed.",
                              task=task.name, job=self.name))
        notes = (notes or '').strip()
        problems = []
        if reason not in dict(NONCOMPLETION_REASONS):
            problems.append(_("Select the non-completion reason."))
        if next_action not in dict(NEXT_ACTIONS):
            problems.append(_("Select the next action."))
        if not notes:
            problems.append(_("Notes are required."))
        if planning and next_action != 'reschedule':
            problems.append(_("A new planned date is only entered to reschedule."))
        timers = self._warranty_running_timers(task)
        if timers:
            problems.append(_("Stop the timer of visit %(task)s first (running for %(users)s).",
                              task=task.name, users=', '.join(timers.user_id.mapped('name'))))
        if problems:
            raise UserError(_("Visit %(task)s:\n%(problems)s", task=task.name,
                              problems='\n'.join('- %s' % problem for problem in problems)))
        outcome = visit_outcome(next_action, reason)
        state_labels = dict(self._fields['state']._description_selection(self.env))
        old_state = self.state
        # Requirement: all or nothing.
        with self.env.cr.savepoint():
            if task.warranty_shared_job_ids:
                # Approved Q5: only this job leaves the shared visit; the others continue.
                self._warranty_record_shared_outcome(task, {
                    'outcome': outcome, 'noncompletion_reason': reason,
                    'noncompletion_notes': notes})
            else:
                task._warranty_close_visits({
                    'state': '1_canceled', 'warranty_visit_outcome': outcome,
                    'warranty_noncompletion_reason': reason,
                    'warranty_noncompletion_notes': notes})
            body = Markup('<p><b>%s</b></p><ul><li>%s</li><li>%s</li><li>%s</li><li>%s</li></ul>') % (
                _("Visit %(task)s (visit %(no)s) not completed - reported by %(user)s.",
                  task=task.name, no=task.warranty_visit_no, user=self.env.user.name),
                _("Reason: %(reason)s. Notes: %(notes)s",
                  reason=dict(task._fields['warranty_noncompletion_reason']
                              ._description_selection(self.env))[reason], notes=notes),
                _("Visit Outcome: %s.", dict(task._fields['warranty_visit_outcome']
                                             ._description_selection(self.env))[outcome]),
                _("Planned %(date)s, technicians: %(users)s.",
                  date=fields.Datetime.to_string(task.planned_date_begin) or '-',
                  users=', '.join(task.user_ids.mapped('name')) or '-'),
                _("Service job %(old)s -> %(new)s; free services stay open, not consumed; the "
                  "Helpdesk ticket stays open.", old=state_labels[old_state],
                  new=state_labels['cancelled' if next_action == 'cancel' else 'incomplete']))
            if next_action == 'cancel':
                self._warranty_history(body)
                self._warranty_cancel(notes)
            else:
                self.with_context(warranty_visit_marker=_VISIT_MARKER).write(
                    {'state': 'incomplete'})
                self._warranty_history(body)
                if planning:
                    self._warranty_plan_next_visit(**planning)
                else:
                    self._warranty_todo(_("Plan the next visit of %s", self.name), _(
                        "Visit %(task)s was not completed (%(outcome)s): plan the next visit "
                        "and inform the customer (no automatic customer notification).",
                        task=task.name, outcome=dict(task._fields['warranty_visit_outcome']
                                                     ._description_selection(self.env))[outcome]))
        return True

    def _warranty_plan_next_visit(self, planned_date, main_technician, support_technicians=None):
        """Enter New Planned Date -> Assign Main / Support Technicians -> Create New Linked
        Field Service Visit -> (Notify Customer: Helpdesk To-Do, approved L4) -> Continue Under
        Same Service Job (Part 4 diagram; approved L3, L9, R5): Helpdesk users only; new visit
        (next visit number, High priority, same free services, new worksheet instances); the
        previous visits keep their date, technicians and outcome; job Rescheduled."""
        self.ensure_one()
        self._warranty_check_visit_access(planning=True)
        if self.state != 'incomplete':
            raise UserError(_("The next visit is planned for Incomplete service jobs (%s).",
                              self.name))
        support_technicians = support_technicians or self.env['res.users']
        problems = self._warranty_worksheet_template_problems()
        if not planned_date or not main_technician:
            problems.append(_("Planned Date and Main Technician are required"))
        if self.helpdesk_ticket_id.fold:
            problems.append(_("Helpdesk ticket %s is closed: reopen it first",
                              self.helpdesk_ticket_id.display_name))
        if problems:
            raise UserError(_("The next visit of %(job)s cannot be planned: %(problems)s.",
                              job=self.name, problems='; '.join(problems)))
        previous = self.planned_date
        # Technician rules of 4.2 (Field Service users of the job company); a past date is
        # allowed (D4 revised); the previous values stay on the previous visits and are tracked.
        self.with_context(warranty_visit_marker=_VISIT_MARKER).write({
            'planned_date': planned_date,
            'main_technician_id': main_technician.id,
            'support_technician_ids': [(6, 0, support_technicians.ids)],
        })
        visit_no = max(self.sudo()._warranty_all_visits().mapped('warranty_visit_no') or [0]) + 1
        task = self._warranty_create_visit_task(visit_no)
        sheets = self._warranty_create_worksheets(task)
        self.with_context(warranty_visit_marker=_VISIT_MARKER).write({'state': 'rescheduled'})
        body = Markup('<p><b>%s</b></p><p>%s</p>') % (_(
            "Next visit %(task)s planned by %(user)s: visit %(no)s on %(date)s (previous planned "
            "date %(previous)s), Main Technician %(main)s%(support)s, High priority; service job "
            "Rescheduled.", task=task.name, user=self.env.user.name, no=visit_no,
            date=fields.Datetime.to_string(self.planned_date),
            previous=fields.Datetime.to_string(previous) or '-',
            main=self.main_technician_id.name,
            support=(_(", Support: %s", ', '.join(self.support_technician_ids.mapped('name')))
                     if self.support_technician_ids else '')), _(
            "Worksheet instances: %s. Free services not consumed.",
            ', '.join(sheets.mapped('name')) or _("none")))
        self._warranty_history(body)
        self._warranty_log_date_notes(self._warranty_service_day(self.planned_date),
                                      task.warranty_entitlement_ids,
                                      self._warranty_planned_date_problems())
        plan_todo = self.activity_ids.filtered(
            lambda activity: activity.summary == _("Plan the next visit of %s", self.name))
        plan_todo.action_feedback(feedback=_("Next visit %s planned.", task.name))
        self._warranty_todo(_("Inform the customer of visit %s", task.name), _(
            "Inform the customer of the new visit date %s (no automatic customer notification).",
            fields.Datetime.to_string(self.planned_date)))
        return task

    def _warranty_cancel_job(self, reason):
        """Cancel Job (approved L7): Helpdesk users, required reason; open visits must have no
        running timer."""
        self.ensure_one()
        self._warranty_check_visit_access(planning=True)
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A cancellation reason is required."))
        if self.state not in CONFIRMED_JOB_STATES:
            raise UserError(_("Only confirmed, started or incomplete service jobs are cancelled "
                              "with Cancel Job (%s); Draft / Planned jobs use Cancel.", self.name))
        timers = self._warranty_running_timers(self.visit_ids | self._warranty_open_shared_visits())
        if timers:
            raise UserError(_("Stop the running timers of %(job)s first (%(users)s).",
                              job=self.name, users=', '.join(timers.user_id.mapped('name'))))
        with self.env.cr.savepoint():
            self._warranty_cancel(reason)
        return True

    def _warranty_cancel(self, reason):
        """Mark Visit Cancelled -> Keep Entitlement Unconsumed (approved L5 / L7, Q42): open
        visits closed (Odoo Cancelled, outcome Cancelled), job Cancelled with its reason, free
        services back to their status before the job and Not Merged (never consumed), warranty
        case back to Approved; ticket unchanged. The SRS "unless configured otherwise" option
        is not implemented (approved; documented)."""
        self.ensure_one()
        # sudo: closing the job's visits / restoring its free services and case is the checked
        # cancellation (users may have no Field Service / free service rights).
        visits = self.sudo().visit_ids.filtered(
            lambda task: not task.fsm_done and task.state not in ('1_done', '1_canceled'))
        visits._warranty_close_visits({'state': '1_canceled',
                                       'warranty_visit_outcome': 'cancelled',
                                       'warranty_noncompletion_notes': reason})
        # Shared visits (approved Q5 / Q7): only this job's outcome, the others continue.
        shared = self._warranty_open_shared_visits()
        for task in shared:
            self._warranty_record_shared_outcome(task, {'outcome': 'cancelled',
                                                        'noncompletion_notes': reason})
        visits |= shared
        services = self.entitlement_ids.sudo().filtered(lambda s: s.state != 'completed')
        restored = []
        for service in services:
            previous = service.job_previous_state or 'pending'
            service.write({'state': previous, 'merge_status': 'not_merged'})
            restored.append('%s (%s)' % (service.name, dict(
                service._fields['state']._description_selection(self.env))[previous]))
        old_state = self.state
        self.with_context(warranty_visit_marker=_VISIT_MARKER).write(
            {'state': 'cancelled', 'cancel_reason': reason})
        case_state = 'approved' if self.job_type == 'warranty' else 'chargeable'
        self.warranty_case_id.sudo().state = case_state
        body = Markup('<p><b>%s</b></p><ul><li>%s</li><li>%s</li><li>%s</li></ul>') % (
            _("Service job %(job)s cancelled by %(user)s (was %(state)s). Reason: %(reason)s",
              job=self.name, user=self.env.user.name, reason=reason,
              state=dict(self._fields['state']._description_selection(self.env))[old_state]),
            _("Visits cancelled: %s.", ', '.join(visits.mapped('name')) or _("none")),
            _("Free services released, not consumed: %s.", ', '.join(restored) or _("none")),
            _("Warranty case %(case)s back to %(state)s (Q42 / C12); the Helpdesk ticket is not "
              "changed.", case=self.warranty_case_id.sudo().name,
              state=_("Approved") if case_state == 'approved' else _("Chargeable")))
        self._warranty_history(body, services)

    def action_open_plan_wizard(self):
        self.ensure_one()
        self._warranty_check_visit_access(planning=True)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Plan Next Visit"),
            'res_model': 'warranty.service.job.plan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_job_id': self.id},
        }

    def action_open_cancel_wizard(self):
        self.ensure_one()
        self._warranty_check_visit_access(planning=True)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Cancel Job"),
            'res_model': 'warranty.service.job.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_job_id': self.id},
        }

    # ------------------------------------------------------------------ Phase 4.9
    def _warranty_check_batch_access(self):
        # Approved B2: Helpdesk users (Job Planner, SRS 16); technicians use Complete Visit.
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can complete service jobs in batch."))

    def _warranty_batch_problems(self):
        """Batch completion validation of one job (SRS 10.5 / validation table; approved B4,
        B5): the Complete Visit checks of 4.7 on the job's only open visit, plus Batch Eligible
        and the job's write access. Nothing is written."""
        self.ensure_one()
        labels = dict(self._fields['state']._description_selection(self.env))
        try:
            self.check_access('write')
        except AccessError:
            return [_("No access to this service job.")]
        if self.state in CLOSED_JOB_STATES:
            return [_("Already closed (%s).", labels[self.state])]
        problems = []
        if self.completion_mode == 'single':
            problems.append(_("Completion Mode is Single: use Complete Visit on the visit."))
        if self.job_type == 'chargeable_inspection':
            problems.append(_("Inspection jobs need the inspection result: use Complete Visit."))
        if self._warranty_open_shared_visits():
            # Approved Q8: no batch completion for shared visits in v1.
            problems.append(_("On a shared Field Service visit: complete it on the visit (no "
                              "batch completion for shared visits)."))
            return problems
        # sudo: the visits are read for the check (Helpdesk users may not read tasks).
        visits = self.sudo().visit_ids.filtered(
            lambda task: not task.fsm_done and task.state not in ('1_done', '1_canceled'))
        if self.state in ('draft', 'planned'):
            problems.append(_("The service job is not confirmed (%s).", labels[self.state]))
        elif not visits:
            problems.append(_("No open visit (%s): plan the next visit first.",
                              labels[self.state]))
        elif len(visits) > 1:
            problems.append(_("Several open visits: %s.", ', '.join(visits.mapped('name'))))
        else:
            problems += self._warranty_visit_completion_problems(visits)
        return problems

    def _warranty_batch_preview(self):
        """[(job, problems)] - Check / Preview (approved B6): nothing is changed."""
        self._warranty_check_batch_access()
        return [(job, job._warranty_batch_problems()) for job in self]

    def _warranty_batch_complete(self):
        """Complete Ready Jobs (approved B4-B10, T1): every job is revalidated just before its
        completion; jobs with business validation problems are skipped and not changed; the
        others are completed with the secure 4.7 Complete Visit (one savepoint per job, free
        services consumed once). An unexpected technical error is not caught: the whole batch
        transaction is rolled back. Returns [(job, completed, problems)]."""
        self._warranty_check_batch_access()
        results = []
        for job in self:
            problems = job._warranty_batch_problems()
            if problems:
                results.append((job, False, problems))
                continue
            # sudo: the job's only open visit (checked above), completed by the 4.7 path.
            visit = job.sudo().visit_ids.filtered(
                lambda task: not task.fsm_done and task.state not in ('1_done', '1_canceled'))
            job._warranty_complete_visit(visit, batch=True)
            results.append((job, True, []))
        return results

    def action_open_batch_wizard(self):
        """Complete Selected Jobs (approved B1 / B6) from the Service Jobs list."""
        self._warranty_check_batch_access()
        wizard = self.env['warranty.service.job.batch.wizard'].create(
            {'job_ids': [(6, 0, self.ids)]})
        wizard._warranty_preview()
        return wizard._warranty_action()

    def action_open_late_service_wizard(self):
        """Request Late Service Exception for a free service of the job (BA-approved F5)."""
        self.ensure_one()
        return self.env['warranty.service.date.exception.wizard']._warranty_open(
            self.entitlement_ids, case=self.warranty_case_id,
            defaults={'default_job_id': self.id})

    # ------------------------------------------------------------------ cross-card merge (D3)
    def _warranty_planned_date_problems(self, planned_date=None):
        """D3 revised 2026-10-29: the due date / service window is a target, not a planning
        restriction - planned visit dates (company warranty timezone) outside the window of a
        free service of the job are logged as a Service date note at Plan Job and Plan Next
        Visit, never refused; usage-based services have no date window. Returns service-level
        reasons."""
        self.ensure_one()
        planned_date = planned_date or self.planned_date
        if not planned_date:
            return []
        day = self._warranty_service_day(planned_date)
        problems = []
        for service in self.entitlement_ids.filtered(lambda s: s.state != 'completed'):
            window = service._warranty_service_window()
            if window and not window[0] <= day <= window[1]:
                problems.append(_("planned date %(day)s is outside the service window of "
                                  "%(service)s (%(card)s): %(start)s - %(end)s (due %(due)s; not "
                                  "blocking)%(hint)s", day=day, service=service.name,
                                  card=service.warranty_card_id.name, start=window[0],
                                  end=window[1], due=service.due_date or '-',
                                  hint=service._warranty_late_service_hint(day, window)))
        return problems

    def _warranty_service_day(self, moment):
        """Date of `moment` in the company warranty timezone."""
        self.ensure_one()
        company = self.company_id
        tz_name = company.warranty_timezone or company.partner_id.tz or 'UTC'
        return fields.Datetime.context_timestamp(self.with_context(tz=tz_name), moment).date()

    def _warranty_completion_date_problems(self, task):
        """Completion checks of the free services of the visit (revised F9, 2026-10-24): an
        Expired or Cancelled service is never completed (Completed ones are skipped, consumed
        once); Enforce Service Sequence (K7). The actual completion date itself does not block:
        outside the permitted dates it is a warning and an audit note
        (_warranty_completion_date_warnings)."""
        self.ensure_one()
        services = self._warranty_visit_services(task).filtered(lambda s: s.state != 'completed')
        labels = dict(services._fields['state']._description_selection(self.env))
        problems = [_("Free service %(service)s (%(card)s) is %(state)s and cannot be completed.",
                      service=service.name, card=service.warranty_card_id.name,
                      state=labels[service.state])
                    for service in services if service.state in ('expired', 'cancelled')]
        return problems + services._warranty_sequence_problems(completing=True)

    def _warranty_completion_date_warnings(self, day, services):
        """Revised F9: services completed earlier or later than their permitted service dates
        (cards with flexible service dates; an approved Late Service Exception included)."""
        self.ensure_one()
        warnings = []
        for service in services:
            window = service._warranty_allowed_range()
            if not window:
                continue
            if day < window[0]:
                warnings.append(_("%(service)s (%(card)s): completed on %(day)s, earlier than its "
                                  "earliest permitted service date %(start)s (due %(due)s).",
                                  service=service.name, card=service.warranty_card_id.name,
                                  day=day, start=window[0], due=service.due_date))
            elif day > window[1]:
                warnings.append(_("%(service)s (%(card)s): completed on %(day)s, later than its "
                                  "latest permitted service date %(end)s (due %(due)s, no approved "
                                  "Late Service Exception covering it).", service=service.name,
                                  card=service.warranty_card_id.name, day=day, end=window[1],
                                  due=service.due_date))
        return warnings

    def _warranty_log_date_notes(self, day, services, warnings=None):
        """Approved F4 / revised F9: audit note when a service is done after its due date
        (within the grace period or an approved Late Service Exception) and the completion
        warnings (outside the permitted dates)."""
        self.ensure_one()
        notes = list(warnings or [])
        for service in services:
            window = service._warranty_allowed_range()
            if window and service.due_date and service.due_date < day <= window[1]:
                approved = service._warranty_approved_service_date()
                notes.append(_("%(service)s: %(day)s is after its due date %(due)s (Grace Period "
                               "End %(grace)s%(approved)s).", service=service.name, day=day,
                               due=service.due_date, grace=service.grace_period_end_date or '-',
                               approved=_(", approved Late Service Exception until %s",
                                          approved) if approved else ''))
        if notes:
            self._message_log(body=Markup('<p><b>%s</b></p><ul>%s</ul>') % (
                _("Service date note"),
                Markup('').join(Markup('<li>%s</li>') % note for note in notes)))



class WarrantyServiceDateExceptionGroup(models.Model):
    _inherit = 'warranty.service.date.exception.group'

    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True)


class WarrantyServiceDateExceptionWizard(models.TransientModel):
    _inherit = 'warranty.service.date.exception.wizard'

    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True)

    def _warranty_group_values(self):
        return dict(super()._warranty_group_values(), job_id=self.job_id.id)
