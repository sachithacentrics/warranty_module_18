from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

# Late Service Exception records and request groups are created and decided only by the methods
# below: Python object in the context, which clients (UI, JSON-RPC, import) cannot send.
_EXCEPTION_MARKER = object()
EXCEPTION_STATES = [
    ('requested', 'Requested'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
    ('expired', 'Not Approved before Expiry'),
]
GROUP_STATES = [
    ('requested', 'Requested'),
    ('partly_expired', 'Partly Expired'),
    ('expired', 'Expired before Approval'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
]
# Groups an approver can still act on (H5-A: Partly Expired -> reject or cancel only).
OPEN_GROUP_STATES = ('requested', 'partly_expired')
CLOSED_SERVICE_STATES = ('completed', 'expired', 'cancelled')
# Chatter / activities stay writable on decided records.
FREE_PREFIXES = ('message_', 'activity_', 'website_message')


class WarrantyServiceDateExceptionMixin(models.AbstractModel):
    """Protected writes and the approver rules of the Late Service Exceptions (BA-approved
    F5 / K5): authorized Helpdesk managers of the company, never the requester or the Draft Job
    Automation User."""
    _name = 'warranty.service.date.exception.mixin'
    _description = 'Late Service Exception Rules'

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('warranty_exception_marker') is not _EXCEPTION_MARKER:
            raise UserError(_("Late Service Exceptions are created with Request Late Service "
                              "Exception."))
        return super().create(vals_list)

    def write(self, vals):
        if any(not key.startswith(FREE_PREFIXES) for key in vals) \
                and self.env.context.get('warranty_exception_marker') is not _EXCEPTION_MARKER:
            raise UserError(_("Late Service Exceptions are changed only by their request / "
                              "approval actions (audit history)."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_audit(self):
        raise UserError(_("Late Service Exceptions are kept for the audit history."))

    def _marked(self):
        return self.with_context(warranty_exception_marker=_EXCEPTION_MARKER)

    @api.model
    def _warranty_forbidden_approvers(self, company, requester):
        return company._warranty_late_service_forbidden_approvers(requester)

    def _warranty_decider_problem(self, user):
        self.ensure_one()
        company = self.company_id
        if not user.has_group('helpdesk.group_helpdesk_manager') \
                or company not in user.company_ids \
                or user not in company._warranty_late_service_approvers():
            return _("Only the Late Service Exception Approvers of %s can decide late-service "
                     "exceptions.", company.name)
        if user in self._warranty_forbidden_approvers(company, self.requested_by_id):
            return _("You cannot decide a late-service exception you requested (separation of "
                     "duties).")
        return False

    def _warranty_close_todos(self, feedback):
        activities = self.approval_activity_ids.exists().filtered('active')
        if activities:
            # sudo: the To-Dos of all approvers are closed by the decision.
            activities.sudo().action_feedback(feedback=feedback)

    def _warranty_schedule_todos(self, approvers, deadline, summary, note):
        """One To-Do per approver (approved requirement 8); the previous open ones are closed."""
        self.ensure_one()
        target = self if self.env.user.email \
            else self.with_context(mail_activity_quick_update=True)
        activities = self.env['mail.activity']
        for approver in approvers:
            activities |= target.activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=deadline, user_id=approver.id,
                summary=summary, note=note)
        self._marked().write({'approval_activity_ids': [(4, a.id) for a in activities]})
        return activities


class WarrantyServiceDateException(models.Model):
    """Late Service Exception of one free service (BA-approved enhancement F5-F8 / K3 / K5 /
    K6, not an original SRS requirement). Created inside a request group (one record per
    selected service, decided together); records created before the groups are decided alone.
    Approved: the service stays available and protected from the Part 2 expiry until that date,
    at most the warranty end date. The original due and grace dates are never changed."""
    _name = 'warranty.service.date.exception'
    _inherit = ['warranty.service.date.exception.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Late Service Exception'
    _order = 'id desc'
    _rec_name = 'entitlement_id'

    group_id = fields.Many2one('warranty.service.date.exception.group', string='Request',
                               readonly=True, index=True, ondelete='restrict')
    entitlement_id = fields.Many2one('warranty.service.entitlement', string='Free Service',
                                     required=True, readonly=True, index=True,
                                     ondelete='restrict')
    warranty_card_id = fields.Many2one(related='entitlement_id.warranty_card_id', store=True,
                                       string='Warranty Card')
    company_id = fields.Many2one(related='entitlement_id.company_id', store=True, index=True)
    partner_id = fields.Many2one(related='entitlement_id.partner_id', string='Customer')
    case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True)
    due_date = fields.Date(string='Due Date', readonly=True)
    grace_end_date = fields.Date(string='Grace Period End Date', readonly=True)
    warranty_end_date = fields.Date(string='Warranty End Date', readonly=True)
    requested_date = fields.Date(string='Requested Latest Service Date', required=True,
                                 readonly=True)
    reason = fields.Text(string='Reason', required=True, readonly=True)
    state = fields.Selection(EXCEPTION_STATES, string='Status', default='requested',
                             required=True, readonly=True, tracking=True, index=True)
    requested_by_id = fields.Many2one('res.users', string='Requested By', readonly=True)
    requested_on = fields.Datetime(string='Requested On', readonly=True)
    decided_by_id = fields.Many2one('res.users', string='Decided By', readonly=True)
    decided_on = fields.Datetime(string='Decided On', readonly=True)
    decision_note = fields.Text(string='Decision Note', readonly=True)
    approval_activity_ids = fields.Many2many(
        'mail.activity', 'warranty_service_exception_activity_rel', 'exception_id',
        'activity_id', string='Approval To-Dos', readonly=True, copy=False,
        context={'active_test': False})
    can_decide = fields.Boolean(compute='_compute_can_decide')

    @api.depends_context('uid')
    @api.depends('state', 'requested_by_id', 'group_id')
    def _compute_can_decide(self):
        for record in self:
            # Grouped records are decided on their request group.
            record.can_decide = record.state == 'requested' and not record.group_id \
                and not record._warranty_decider_problem(self.env.user)

    # ------------------------------------------------------------------ request
    @api.model
    def _warranty_service_problems(self, service, requested_date):
        """Per-service rules of a request (approved F5 / F6 / K6, requirement 5): the card's
        policy allows Manager Approval; open service; a date from today, after the service's
        current latest permitted date and not after its card's warranty end date; no open
        request. Returns the reasons (empty = valid)."""
        card = service.warranty_card_id
        if card.late_service_handling != 'approval' or not card.early_service_rule:
            return [_("the policy of warranty card %s does not allow late-service exceptions "
                      "(Late Service Handling: Block)", card.name)]
        if service.state in CLOSED_SERVICE_STATES:
            return [_("the free service is %s: no exception is possible", dict(
                service._fields['state']._description_selection(self.env))[service.state])]
        problems = []
        today = service.company_id._warranty_today()
        window = service._warranty_allowed_range()
        if requested_date < today:
            problems.append(_("the requested service date cannot be in the past"))
        elif window and requested_date <= window[1]:
            problems.append(_("%(date)s is already a permitted service date (until %(end)s): no "
                              "exception is needed", date=requested_date, end=window[1]))
        end = card.warranty_end_date
        if not end or requested_date > end:
            problems.append(_("the requested date %(date)s is after the warranty end date "
                              "%(end)s of %(card)s: the warranty coverage is not extended",
                              date=requested_date, end=end or '-', card=card.name))
        open_request = self.search([('entitlement_id', '=', service.id),
                                    ('state', '=', 'requested')], limit=1)
        if open_request:
            problems.append(_("a late-service exception is already requested by %s and waits "
                              "for approval", open_request.requested_by_id.name))
        return problems

    @api.model
    def _warranty_request(self, service, requested_date, reason, case=None):
        """Single-service request: a request group of one; returns its exception record."""
        group = self.env['warranty.service.date.exception.group']._warranty_request_group(
            service, requested_date, reason, values={'case_id': case.id if case else False})
        return group.exception_ids

    # ------------------------------------------------------------------ decisions
    def _warranty_check_decider(self):
        for record in self:
            problem = record._warranty_decider_problem(self.env.user)
            if problem:
                raise AccessError(problem)
            if record.state != 'requested':
                raise UserError(_("Only requested late-service exceptions can be decided."))

    def _warranty_group_action(self, method, *args):
        """Grouped records are decided with their request group (all or nothing); a group of
        one is decided through its record as well."""
        groups = self.group_id
        if any(len(group.exception_ids) > 1 for group in groups):
            raise UserError(_("Decide the request %s: its free services are approved or rejected "
                              "together.", ', '.join(groups.mapped('display_name'))))
        return getattr(groups, method)(*args)

    def _warranty_member_problems(self):
        """Re-check at approval (requirement 5, never bypassed by a group decision): the record
        is requested, its service open, the date not passed, within its card's warranty end
        date and the policy still allows Manager Approval."""
        self.ensure_one()
        service = self.entitlement_id
        card = service.warranty_card_id
        if self.state != 'requested':
            return [_("the exception is %s", dict(
                self._fields['state']._description_selection(self.env))[self.state])]
        if card.late_service_handling != 'approval' or not card.early_service_rule:
            return [_("the policy of warranty card %s no longer allows late-service exceptions",
                      card.name)]
        if service.state in CLOSED_SERVICE_STATES:
            return [_("the free service is closed (%s)", dict(
                service._fields['state']._description_selection(self.env))[service.state])]
        problems = []
        if self.requested_date < self.company_id._warranty_today():
            problems.append(_("the requested date %s has passed: request a new date",
                              self.requested_date))
        end = card.warranty_end_date
        if not end or self.requested_date > end:
            problems.append(_("the requested date is after the warranty end date %s",
                              end or '-'))
        return problems

    def action_approve(self, note=None):
        """Approve a standalone record (created before the request groups)."""
        if self.filtered('group_id'):
            return self._warranty_group_action('action_approve', note)
        self._warranty_check_decider()
        for record in self:
            problems = record._warranty_member_problems()
            if problems:
                raise UserError(_("%(service)s: %(problems)s.", service=record.entitlement_id.name,
                                  problems='; '.join(problems)))
            record._warranty_decide('approved', note)
            record._warranty_close_todos(_("Approved"))
        return True

    def action_reject(self, note):
        if self.filtered('group_id'):
            return self._warranty_group_action('action_reject', note)
        self._warranty_check_decider()
        note = (note or '').strip()
        if not note:
            raise UserError(_("A reason is required to reject a late-service exception."))
        for record in self:
            record._warranty_decide('rejected', note)
            record._warranty_close_todos(_("Rejected"))
        return True

    def action_cancel(self):
        if self.filtered('group_id'):
            return self._warranty_group_action('action_cancel')
        for record in self:
            if record.state != 'requested':
                raise UserError(_("Only requested late-service exceptions can be cancelled."))
            if self.env.user != record.requested_by_id \
                    and record._warranty_decider_problem(self.env.user):
                raise AccessError(_("Only the requester or an approver can cancel this request."))
            record._warranty_decide('cancelled', _("Cancelled by %s", self.env.user.name))
            record._warranty_close_todos(_("Cancelled"))
        return True

    def _warranty_decide(self, state, note):
        """Record the decision of this service and its audit notes."""
        self.ensure_one()
        self._marked().write({'state': state, 'decided_by_id': self.env.uid,
                              'decided_on': fields.Datetime.now(), 'decision_note': note})
        texts = {
            'approved': _("Late-service exception approved by %(user)s: %(service)s may be "
                          "serviced until %(date)s (Grace Period End %(grace)s unchanged)."),
            'rejected': _("Late-service exception of %(service)s rejected by %(user)s."),
            'cancelled': _("Late-service exception request of %(service)s cancelled by "
                           "%(user)s."),
        }
        text = texts[state] % {'user': self.env.user.name, 'service': self.entitlement_id.name,
                               'date': self.requested_date, 'grace': self.grace_end_date or '-'}
        self._warranty_log(text + (_(" Note: %s", note) if note else ''))

    def _warranty_close_on_expiry(self):
        """Approved K6 / H5-A: a request not approved before the Part 2 expiry is closed and
        recorded; the expired service stays final (F7); its group can only be rejected or
        cancelled."""
        for record in self.filtered(lambda r: r.state == 'requested'):
            record._marked().write({'state': 'expired', 'decided_on': fields.Datetime.now(),
                                    'decision_note': _("Not approved before the free service "
                                                       "expired.")})
            record._warranty_close_todos(_("Free service expired before approval."))
            record._warranty_log(_("Late-service exception request of %s was not approved before "
                                   "the free service expired: the service stays Expired.",
                                   record.entitlement_id.name))
        self.group_id._warranty_member_expired()

    def _warranty_log(self, text):
        """Audit notes on the record, its request group, the free service, its card and the
        case."""
        self.ensure_one()
        body = Markup('<p>%s</p>') % text
        # sudo: chatter notes only (the approver may not write the service / card / case).
        for record in (self, self.group_id, self.entitlement_id, self.warranty_card_id,
                       self.case_id):
            if record:
                record.sudo()._message_log(body=body)

    def action_open_reject_wizard(self):
        self.ensure_one()
        if self.group_id:
            return self.group_id.action_open_reject_wizard()
        self._warranty_check_decider()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Late Service Exception"),
            'res_model': 'warranty.service.date.exception.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_exception_id': self.id},
        }


class WarrantyServiceDateExceptionGroup(models.Model):
    """Late Service Exception request group (approved G1-G7, H5-A): one request (common
    requested date and reason) for several free services - e.g. the services of several cards
    merged into one service job - with one exception record per service. Every service is
    validated on its own at request and at approval; nothing is processed partially."""
    _name = 'warranty.service.date.exception.group'
    _inherit = ['warranty.service.date.exception.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Late Service Exception Request'
    _order = 'id desc'

    name = fields.Char(string='Request', readonly=True, required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True,
                                 index=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True)
    requested_date = fields.Date(string='Requested Latest Service Date', required=True,
                                 readonly=True)
    reason = fields.Text(string='Reason', required=True, readonly=True)
    requested_by_id = fields.Many2one('res.users', string='Requested By', readonly=True)
    requested_on = fields.Datetime(string='Requested On', readonly=True)
    decided_by_id = fields.Many2one('res.users', string='Decided By', readonly=True)
    decided_on = fields.Datetime(string='Decided On', readonly=True)
    decision_note = fields.Text(string='Decision Note', readonly=True)
    exception_ids = fields.One2many('warranty.service.date.exception', 'group_id',
                                    string='Free Service Exceptions', readonly=True)
    state = fields.Selection(GROUP_STATES, string='Status', compute='_compute_state',
                             store=True, index=True, tracking=True)
    approval_activity_ids = fields.Many2many(
        'mail.activity', 'warranty_service_exception_group_activity_rel', 'group_id',
        'activity_id', string='Approval To-Dos', readonly=True, copy=False,
        context={'active_test': False})
    can_decide = fields.Boolean(compute='_compute_can_decide')
    can_approve = fields.Boolean(compute='_compute_can_decide')

    @api.depends('exception_ids.state')
    def _compute_state(self):
        """Approved design 6: derived from the records, never typed in."""
        for group in self:
            states = set(group.exception_ids.mapped('state'))
            if not states or states == {'requested'}:
                group.state = 'requested'
            elif states == {'expired'}:
                group.state = 'expired'
            elif states <= {'requested', 'expired'}:
                group.state = 'partly_expired'
            elif 'approved' in states:
                group.state = 'approved'
            elif 'rejected' in states:
                group.state = 'rejected'
            else:
                group.state = 'cancelled'

    @api.depends_context('uid')
    @api.depends('state', 'requested_by_id')
    def _compute_can_decide(self):
        for group in self:
            allowed = group.state in OPEN_GROUP_STATES \
                and not group._warranty_decider_problem(self.env.user)
            group.can_decide = allowed
            group.can_approve = allowed and group.state == 'requested'

    # ------------------------------------------------------------------ request
    @api.model
    def _warranty_request_group(self, services, requested_date, reason, values=None):
        """Request Late Service Exception for `services` (approved G2 / G3): every service
        checked on its own, one company and customer, approvers available; any problem ->
        nothing created, every failing service named. Then one group, one record per service,
        one To-Do per approver."""
        user = self.env.user
        if not user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can request a late-service exception."))
        if not services:
            raise UserError(_("Select at least one free service."))
        services.check_access('read')
        companies = services.company_id
        if len(companies) > 1 \
                or len(services.warranty_card_id.partner_id.commercial_partner_id) > 1:
            raise UserError(_("A request contains the free services of one company and one "
                              "customer."))
        company = companies
        if company not in user.company_ids:
            raise AccessError(_("You cannot request exceptions for %s.", company.name))
        reason = (reason or '').strip()
        if not reason or not requested_date:
            raise UserError(_("The requested date and the reason are required."))
        Exception_ = self.env['warranty.service.date.exception']
        problems = []
        for service in services:
            for problem in Exception_._warranty_service_problems(service, requested_date):
                problems.append('%s (%s): %s' % (service.name, service.warranty_card_id.name,
                                                 problem))
        if problems:
            raise UserError(_("The late-service exception cannot be requested:\n%s",
                              '\n'.join('- %s' % problem for problem in problems)))
        approvers = company._warranty_late_service_approvers() \
            - Exception_._warranty_forbidden_approvers(company, user)
        if not approvers:
            raise UserError(_("No Late Service Exception Approver (Helpdesk manager of %s other "
                              "than you) is available.", company.name))
        now = fields.Datetime.now()
        common = {'requested_date': requested_date, 'reason': reason,
                  'requested_by_id': user.id, 'requested_on': now}
        group_vals = dict(common, **(values or {}))
        group = self._marked().create(dict(
            group_vals, company_id=company.id,
            partner_id=services.warranty_card_id.partner_id.commercial_partner_id.id,
            name=_("%(services)s until %(date)s", services=', '.join(services.mapped('name')),
                   date=requested_date))).with_env(self.env)
        today = company._warranty_today()
        records = Exception_._marked().create([dict(
            common, group_id=group.id, entitlement_id=service.id,
            case_id=group.case_id.id, due_date=service.due_date,
            grace_end_date=service.grace_period_end_date
            or service._warranty_allowed_range()[1],
            warranty_end_date=service.warranty_card_id.warranty_end_date)
            for service in services]).with_env(self.env)
        deadline = max(min(records.mapped('grace_end_date')) or today, today)
        group._warranty_schedule_todos(
            approvers, deadline, _("Approve late service: %s", group.name),
            _("Requested service date %(date)s for %(services)s by %(user)s: %(reason)s",
              date=requested_date, services=', '.join(services.mapped('name')),
              user=user.name, reason=reason))
        for record in records:
            record._warranty_log(_("Late-service exception requested by %(user)s for %(service)s "
                                   "(request %(group)s): service date until %(date)s. Reason: "
                                   "%(reason)s", user=user.name, service=record.entitlement_id.name,
                                   group=group.name, date=requested_date, reason=reason))
        return group

    # ------------------------------------------------------------------ decisions
    def _warranty_check_group_decider(self, approve=False):
        for group in self:
            problem = group._warranty_decider_problem(self.env.user)
            if problem:
                raise AccessError(problem)
            # Company security of every service record (record rules).
            group.exception_ids.check_access('read')
            if group.state not in OPEN_GROUP_STATES:
                raise UserError(_("Request %s is already decided.", group.name))
            if approve and group.state != 'requested':
                raise UserError(_("Request %s cannot be approved: a free service expired before "
                                  "the approval (approved H5-A). Reject or cancel it and request "
                                  "again for the remaining services.", group.name))

    def action_approve(self, note=None):
        """Approve the request (approved G4 / requirement 6): every record re-checked on its
        own first; any problem -> nothing decided, each failing service named; then all records
        approved in one savepoint."""
        self._warranty_check_group_decider(approve=True)
        for group in self:
            problems = []
            for record in group.exception_ids:
                problems += ['%s (%s): %s' % (record.entitlement_id.name,
                                              record.warranty_card_id.name, problem)
                             for problem in record._warranty_member_problems()]
            if problems:
                raise UserError(_("Request %(group)s cannot be approved:\n%(problems)s",
                                  group=group.name,
                                  problems='\n'.join('- %s' % problem for problem in problems)))
            with self.env.cr.savepoint():
                for record in group.exception_ids:
                    record._warranty_decide('approved', note)
                group._warranty_close_group('approved', note)
        return True

    def action_reject(self, note):
        """Reject (reason required): all requested records rejected; expired records keep their
        status (H5-A)."""
        self._warranty_check_group_decider()
        note = (note or '').strip()
        if not note:
            raise UserError(_("A reason is required to reject a late-service exception."))
        for group in self:
            with self.env.cr.savepoint():
                for record in group.exception_ids.filtered(lambda r: r.state == 'requested'):
                    record._warranty_decide('rejected', note)
                group._warranty_close_group('rejected', note)
        return True

    def action_cancel(self):
        """The requester or an approver withdraws the request; requested records cancelled,
        expired records unchanged; the remaining services can be requested again."""
        for group in self:
            if group.state not in OPEN_GROUP_STATES:
                raise UserError(_("Only open requests can be cancelled."))
            if self.env.user != group.requested_by_id \
                    and group._warranty_decider_problem(self.env.user):
                raise AccessError(_("Only the requester or an approver can cancel this request."))
            note = _("Cancelled by %s", self.env.user.name)
            with self.env.cr.savepoint():
                for record in group.exception_ids.filtered(lambda r: r.state == 'requested'):
                    record._warranty_decide('cancelled', note)
                group._warranty_close_group('cancelled', note)
        return True

    def _warranty_close_group(self, state, note):
        self.ensure_one()
        self._marked().write({'decided_by_id': self.env.uid, 'decided_on': fields.Datetime.now(),
                              'decision_note': note})
        self._warranty_close_todos(dict(self._fields['state']._description_selection(
            self.env))[state])

    def _warranty_member_expired(self):
        """Approved H5-A: after a member expired, the approval To-Dos become one To-Do per
        approver to reject or cancel the request (all expired: nothing left to decide)."""
        for group in self:
            group._warranty_close_todos(_("A free service expired before the approval."))
            if group.state != 'partly_expired':
                continue
            approvers = group.company_id._warranty_late_service_approvers() \
                - group._warranty_forbidden_approvers(group.company_id, group.requested_by_id)
            group._warranty_schedule_todos(
                approvers, group.company_id._warranty_today(),
                _("Reject or cancel late service request: %s", group.name),
                _("A free service of this request expired before the approval: the request cannot "
                  "be approved. Reject or cancel it; the remaining services can be requested "
                  "again."))

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._warranty_check_group_decider()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Late Service Exception"),
            'res_model': 'warranty.service.date.exception.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_group_id': self.id},
        }
