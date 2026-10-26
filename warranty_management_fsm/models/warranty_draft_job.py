"""Phase 4.11 - Draft Job from Service (SRS 2.5, 9.3 step 9, 9.4 steps 5-7; approved E1-E10,
A1-A7): when a free service of a card with Draft Job from Service reaches its Alert Date (Due
Date without alert days), the daily monitoring creates a Helpdesk ticket and a Free Service
warranty case (one per customer site, cross-card merge), runs Check Eligibility and, after the
manual approval, prepares the Draft Service Job. Every record is created and checked by the
company's Draft Job Automation User; nothing is approved automatically."""
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html2plaintext

from odoo.addons.warranty_management.models.res_company import (
    FREE_SERVICE_SCOPE_MODES, get_valid_service_alert_users)
from odoo.addons.warranty_management_helpdesk.models.warranty_case import SELECTION_STATES
from odoo.addons.warranty_management_helpdesk.models.warranty_service_entitlement import (
    warranty_same_site)

_logger = logging.getLogger(__name__)

# The automation status fields are written by this module only: Python object in the context,
# which clients (UI, JSON-RPC, import) cannot send.
_AUTO_JOB_MARKER = object()
AUTO_SERVICE_FIELDS = {'warranty_auto_job_state', 'warranty_auto_job_note', 'warranty_auto_case_id',
                       'warranty_auto_todo_ids'}
AUTO_CASE_FIELDS = {'warranty_auto_created', 'warranty_auto_manual_change',
                    'warranty_auto_todo_ids'}
# Approved A3: a user change of these fields is a manual change (no automatic joining after it).
AUTO_CASE_MANUAL_FIELDS = {'service_entitlement_ids', 'service_unit_ids', 'requested_item_ids',
                           'site_id', 'warranty_card_id', 'warranty_unit_id', 'current_usage',
                           'product_id', 'serial_id', 'merged_adhoc_request',
                           'merged_adhoc_description', 'helpdesk_ticket_id', 'case_type'}
# Approved A7: statuses processed by the automation (not Missed, Expired, Completed, ...).
AUTO_JOB_SERVICE_STATES = ('draft', 'pending', 'scheduled', 'rescheduled')
AUTO_JOB_STATES = [
    ('case_created', 'Case Created'),
    ('job_created', 'Draft Job Created'),
    ('blocked', 'Blocked'),
    ('window_ended', 'Window Ended'),
]


def warranty_auto_planners(company, cards, ticket_user=None):
    """Approved A4: the assigned Helpdesk user of the ticket, else the service alert users of
    the cards (Part 2 resolution), else the company's Helpdesk managers."""
    users = get_valid_service_alert_users(ticket_user, company) if ticket_user else None
    if users:
        return users
    users = company.env['res.users']
    for card in cards:
        users |= card._resolve_service_alert_users()[0]
    if users:
        return users
    managers = company.env['res.users'].search([
        ('groups_id', 'in', company.env.ref('helpdesk.group_helpdesk_manager').ids),
        ('share', '=', False), ('company_ids', 'in', company.ids)])
    return get_valid_service_alert_users(managers, company)


def warranty_auto_close_todos(record, feedback):
    """Close the open automation To-Dos of `record` (done activities keep the history)."""
    todos = record.warranty_auto_todo_ids.filtered('active')
    if todos:
        todos.action_feedback(feedback=feedback)


def warranty_auto_todo(record, users, summary, note):
    """Approved E7 / E8: one set of open planner To-Dos per record, kept while the summary and
    reason are unchanged, replaced otherwise. Without any recipient the problem is logged
    (never silent)."""
    todos = record.warranty_auto_todo_ids.filtered('active')
    text = html2plaintext(note)
    if todos and todos.user_id == users and all(
            todo.summary == summary and html2plaintext(todo.note or '') == text for todo in todos):
        return todos
    warranty_auto_close_todos(record, record.env._("Replaced: %s", summary))
    if not users:
        _logger.warning("Draft Job from Service: no recipient for the To-Do '%s' of %s (%s): %s",
                        summary, record.display_name, record._name, text)
        record._message_log(body=Markup('<p><b>%s</b></p>%s<p>%s</p>') % (
            summary, note, record.env._("No user to notify: no ticket user, service alert user or Helpdesk "
                             "manager is configured.")))
        return record.env['mail.activity']
    # As for the case approvals: without sender email no assignment email.
    target = record if record.env.user.email \
        else record.with_context(mail_activity_quick_update=True)
    todos = record.env['mail.activity']
    for user in users:
        todos |= target.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                          summary=summary, note=note)
    record.with_context(warranty_auto_job_marker=_AUTO_JOB_MARKER).write(
        {'warranty_auto_todo_ids': [(4, todo.id) for todo in todos]})
    return todos


def warranty_auto_error(error):
    return error.args[0] if error.args else str(error)


class WarrantyServiceEntitlement(models.Model):
    _inherit = 'warranty.service.entitlement'

    warranty_auto_job_state = fields.Selection(
        AUTO_JOB_STATES, string='Automatic Draft Job', readonly=True, copy=False, index=True,
        help="Draft Job from Service: processing status of this free service (empty: not "
             "processed).")
    warranty_auto_job_note = fields.Text(string='Automatic Draft Job Reason', readonly=True,
                                         copy=False)
    warranty_auto_case_id = fields.Many2one('warranty.case', string='Automatic Warranty Case',
                                            readonly=True, copy=False)
    warranty_auto_todo_ids = fields.Many2many(
        'mail.activity', 'warranty_service_auto_todo_rel', 'entitlement_id', 'activity_id',
        string='Automatic Draft Job To-Dos', readonly=True, copy=False,
        context={'active_test': False})

    def write(self, vals):
        if AUTO_SERVICE_FIELDS & set(vals) \
                and self.env.context.get('warranty_auto_job_marker') is not _AUTO_JOB_MARKER:
            raise UserError(_("The automatic Draft Job status is set by Draft Job from Service."))
        return super().write(vals)

    def _warranty_auto_write(self, vals):
        return self.with_context(warranty_auto_job_marker=_AUTO_JOB_MARKER).write(vals)

    def _cron_monitor_free_services(self):
        result = super()._cron_monitor_free_services()
        self._warranty_run_draft_jobs()
        return result

    @api.model
    def _warranty_run_draft_jobs(self):
        """Draft Job from Service step of the daily monitoring (approved E1 / E2 / A7)."""
        # The cron runs as OdooBot (superuser): only the candidates are searched here; tickets,
        # cases and checks run as the company's Draft Job Automation User (approved E10).
        # Usage-based services have no due date (approved E9: pending SRS requirement).
        candidates = self.search([
            ('warranty_card_id.state', '=', 'confirmed'),
            ('warranty_card_id.draft_job_from_service', '=', True),
            ('warranty_card_id.warranty_basis', '=', 'period'),
            ('due_date', '!=', False),
            ('state', 'in', AUTO_JOB_SERVICE_STATES),
            ('warranty_auto_job_state', 'in', (False, 'blocked')),
        ], order='due_date, id')
        for company, services in candidates.grouped('company_id').items():
            if company.warranty_scope_mode in FREE_SERVICE_SCOPE_MODES:
                services._warranty_draft_jobs_for_company(company)

    def _warranty_draft_jobs_for_company(self, company):
        """Approved E1: processed from the start of the D3 window (Alert Date, else Due Date);
        a window that ended is not processed any more (A7). Missing / invalid configuration:
        the services are Blocked with the reason and retried on the next run (E4)."""
        today = company._warranty_today()
        started = ended = self.browse()
        for service in self:
            earliest, latest = service._warranty_alert_window()
            if latest < today:
                ended |= service
            elif earliest <= today:
                started |= service
        ended._warranty_auto_window_ended()
        if not started:
            return
        problems = company._warranty_draft_job_config_problems()
        if problems:
            started._warranty_auto_block(' '.join(problems))
            return
        started.with_user(company.warranty_draft_job_user_id).with_context(
            allowed_company_ids=company.ids)._warranty_auto_process(company)

    def _warranty_auto_process(self, company):
        """Lock, revalidate and group the started services, then one ticket / case per group."""
        locked = self._warranty_auto_lock()
        if len(locked) < len(self):
            _logger.info("Draft Job from Service: %s locked by another transaction, left for the "
                         "next run.", ', '.join((self - locked).mapped('name')))
        self.env.invalidate_all()
        # Revalidation after the lock (approved E6 / A7 / D7).
        locked = locked.filtered(
            lambda service: service.warranty_auto_job_state in (False, 'blocked')
            and service.state in AUTO_JOB_SERVICE_STATES)
        services = locked.filtered(
            lambda service: not service._warranty_active_cases()
            and not service.open_service_job_id)
        for service in locked - services:
            # Linked manually meanwhile: the blocked To-Do is done.
            warranty_auto_close_todos(service, _("Handled manually (%s).", ', '.join(
                service._warranty_active_cases().mapped('name')
                + service.open_service_job_id.mapped('name'))))
        Entitlement = self.env['warranty.service.entitlement']
        for partner, customer_services in services.grouped(
                lambda service: service.warranty_card_id.partner_id.commercial_partner_id).items():
            available = Entitlement._warranty_pending_services(partner, company)
            (customer_services - available)._warranty_auto_block(_(
                "The free service is no longer available (status, grace period or Free Services "
                "Balance)."))
            for address, group in (customer_services & available)._warranty_auto_groups():
                group._warranty_auto_case(address)

    def _warranty_auto_lock(self):
        """Requirement 1 / A5: row locks against concurrent runs and simultaneous case creation
        (a case being linked in another transaction holds a key share lock on the service);
        the services locked elsewhere are left for the next run. SQL: the ORM has no SKIP
        LOCKED."""
        self.env.cr.execute(
            "SELECT id FROM warranty_service_entitlement WHERE id IN %s FOR UPDATE SKIP LOCKED",
            [tuple(self.ids)])
        return self.browse([row[0] for row in self.env.cr.fetchall()])

    def _warranty_auto_groups(self):
        """Approved E5: one group per customer site (D6 rules 1 / 2: same address record or
        identical normalized address; a Confirm Same Site is never assumed). The windows of the
        started services all contain today, so they overlap (D3). Returns [(address, services)]."""
        groups = []
        for service in self:
            # sudo: the delivery address of the warranty sale is read only.
            address = service.warranty_card_id.sudo().sale_order_id.partner_shipping_id
            for index, (site, services) in enumerate(groups):
                if warranty_same_site(address, site):
                    groups[index] = (site, services | service)
                    break
            else:
                groups.append((address, service))
        return [(self.env['res.partner'].browse(address.ids), services)
                for address, services in groups]

    def _warranty_auto_case(self, address):
        """One ticket and case per group (approved E3 / E5 / A3 / A6), then Check Eligibility,
        in a savepoint: a failure is rolled back, the services are Blocked with the reason and
        the other groups continue."""
        # The pending tracking is posted first: a rolled back savepoint clears the precommit.
        self.env.cr.precommit.run()
        try:
            with self.env.cr.savepoint():
                case = self._warranty_auto_join_case(address) \
                    or self._warranty_auto_create_case(address)
                case.action_check_eligibility()
        except (UserError, ValidationError, AccessError) as error:
            reason = _("The automatic warranty case could not be created: %s",
                       warranty_auto_error(error))
            _logger.warning("Draft Job from Service: %s (%s)", reason, ', '.join(self.mapped('name')))
            self._warranty_auto_block(reason)
            return self.env['warranty.case']
        return case

    def _warranty_auto_create_case(self, address):
        """Helpdesk ticket (Draft Job Helpdesk Team; no tracking template, so no automatic
        customer email) and Free Service warranty case with the group's services, units (D4)
        and the policies' Automatic Case Requested Items."""
        company = self.company_id
        cards = self.warranty_card_id
        names = ', '.join('%s (%s)' % (service.name, service.warranty_card_id.name)
                          for service in self)
        ticket = self.env['helpdesk.ticket'].with_context(
            mail_notrack=True, mail_create_nosubscribe=True).create({
                'name': _("Free service due: %s", names),
                'team_id': company.warranty_draft_job_team_id.id,
                'partner_id': cards[:1].partner_id.id,
                'warranty_site_id': address.id,
                'description': Markup('<p>%s</p>') % _(
                    "Created by Draft Job from Service for the free services %s.", names),
            })
        items = cards.policy_id.auto_case_item_ids
        case = self.env['warranty.case'].with_context(
            warranty_auto_job_marker=_AUTO_JOB_MARKER).create({
                'helpdesk_ticket_id': ticket.id,
                'case_type': 'free_service',
                'service_entitlement_ids': [(6, 0, self.ids)],
                'requested_item_ids': [(6, 0, items.ids)],
                'warranty_auto_created': True,
            }).with_env(self.env)
        body = Markup('<p><b>%s</b></p><p>%s</p>') % (
            _("Created automatically by Draft Job from Service (%(user)s): ticket %(ticket)s, "
              "free services %(services)s.", user=self.env.user.name, ticket=ticket.display_name,
              services=names),
            _("Requested Items (policy Automatic Case Requested Items): %s. A Draft Service Job is "
              "prepared only after the eligibility check and the manual approval.",
              ', '.join(items.mapped('name')) or _("none")))
        case._message_log(body=body)
        self._warranty_auto_linked(case, _("Automatic warranty case %(case)s created (ticket "
                                           "%(ticket)s).", case=case.name,
                                           ticket=ticket.display_name))
        return case

    def _warranty_auto_join_case(self, address):
        """Approved A3: a later service joins an automatic case of the customer only when the
        case is New / Eligibility Checked, has no service job, no manual change or human decision,
        the same site (D6 rules 1 / 2) and overlapping service windows (D3); the case is then
        reset (D2) and checked again by the caller."""
        partner = self.warranty_card_id.partner_id.commercial_partner_id
        cases = self.env['warranty.case'].search([
            ('warranty_auto_created', '=', True), ('company_id', '=', self.company_id.id),
            ('partner_id', 'child_of', partner.id), ('state', 'in', SELECTION_STATES),
            ('service_job_ids', '=', False), ('warranty_auto_manual_change', '=', False),
        ], order='id')
        for case in cases:
            if case._warranty_auto_human_decision() \
                    or not warranty_same_site(address, case._warranty_reference_site()) \
                    or case._warranty_window_problems(case.service_entitlement_ids | self):
                continue
            items = self.warranty_card_id.policy_id.auto_case_item_ids - case.requested_item_ids
            case.with_context(warranty_auto_job_marker=_AUTO_JOB_MARKER).write({
                'service_entitlement_ids': [(4, service.id) for service in self],
                'requested_item_ids': [(4, item.id) for item in items],
            })
            case._message_log(body=Markup('<p><b>%s</b></p>') % _(
                "Free services %(services)s added by Draft Job from Service (%(user)s): same "
                "customer, site and service window; eligibility checked again.",
                services=', '.join(self.mapped('name')), user=self.env.user.name))
            self._warranty_auto_linked(case, _("Added to the automatic warranty case %s.",
                                               case.name))
            return case
        return self.env['warranty.case']

    def _warranty_auto_linked(self, case, text):
        for service in self:
            warranty_auto_close_todos(service, text)
            service._message_log(body=Markup('<p>%s</p>') % text)
        self._warranty_auto_write({'warranty_auto_job_state': 'case_created',
                                   'warranty_auto_case_id': case.id,
                                   'warranty_auto_job_note': False})

    def _warranty_auto_block(self, reason):
        """Blocked (approved E4 / E7): reason stored and logged, one actionable To-Do; retried on
        the next run while the window is open. Unchanged reasons are not logged again."""
        for service in self:
            if service.warranty_auto_job_state == 'blocked' \
                    and service.warranty_auto_job_note == reason:
                continue
            service._warranty_auto_write({'warranty_auto_job_state': 'blocked',
                                          'warranty_auto_job_note': reason})
            service._message_log(body=Markup('<p><b>%s</b></p><p>%s</p>') % (
                _("Draft Job from Service blocked"), reason))
            warranty_auto_todo(
                service, warranty_auto_planners(service.company_id, service.warranty_card_id),
                _("Draft job from service blocked: %s", service.name),
                Markup('<p>%s</p><p>%s</p>') % (reason, _(
                    "Fix the cause: the automation retries on its next daily run while the service "
                    "window is open. The service can also be handled manually (ticket Pending "
                    "Services).")))

    def _warranty_auto_window_ended(self):
        """Approved A7: a service whose window ended is not processed any more; an open blocked
        To-Do is replaced by the final reason."""
        for service in self:
            earliest, latest = service._warranty_alert_window()
            reason = _("The service window %(start)s - %(end)s ended without automatic draft job.",
                       start=earliest, end=latest)
            todos = service.warranty_auto_todo_ids.filtered('active')
            service._warranty_auto_write({'warranty_auto_job_state': 'window_ended',
                                          'warranty_auto_job_note': reason})
            service._message_log(body=Markup('<p>%s</p>') % reason)
            if todos:
                warranty_auto_todo(service, todos.user_id,
                                   _("Draft job from service not created: %s", service.name),
                                   Markup('<p>%s</p>') % reason)


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    warranty_auto_created = fields.Boolean(
        string='Created by Draft Job from Service', readonly=True, copy=False, index=True)
    warranty_auto_manual_change = fields.Boolean(
        string='Changed Manually', readonly=True, copy=False,
        help="A user changed the services, units, items, card or site of this automatic case: "
             "later services are not added to it automatically.")
    warranty_auto_todo_ids = fields.Many2many(
        'mail.activity', 'warranty_case_auto_todo_rel', 'case_id', 'activity_id',
        string='Automatic Draft Job To-Dos', readonly=True, copy=False,
        context={'active_test': False})

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('warranty_auto_job_marker') is not _AUTO_JOB_MARKER \
                and any(AUTO_CASE_FIELDS & set(vals) for vals in vals_list):
            raise UserError(_("Automatic warranty cases are created by Draft Job from Service."))
        return super().create(vals_list)

    def write(self, vals):
        marked = self.env.context.get('warranty_auto_job_marker') is _AUTO_JOB_MARKER
        if AUTO_CASE_FIELDS & set(vals) and not marked:
            raise UserError(_("The Draft Job from Service fields are set by the automation."))
        manual = self.filtered(
            lambda case: case.warranty_auto_created and not case.warranty_auto_manual_change) \
            if AUTO_CASE_MANUAL_FIELDS & set(vals) and not marked and not self.env.su \
            else self.browse()
        result = super().write(vals)
        if manual:
            manual.with_context(warranty_auto_job_marker=_AUTO_JOB_MARKER).write(
                {'warranty_auto_manual_change': True})
        return result

    def _warranty_auto_human_decision(self):
        """Approved A3: a manual change or exception decision recorded on the case."""
        self.ensure_one()
        return bool(self.warranty_auto_manual_change or self.payment_waiver_user_id
                    or self.escalation_confirmed_by_id or self.site_confirmed_by_id
                    or self.case_approved_by_id or self.rejected_by_id
                    or self.chargeable_converted_by_id)

    def _warranty_auto_planners(self):
        self.ensure_one()
        return warranty_auto_planners(self.company_id, self.service_entitlement_ids.warranty_card_id,
                                      self.helpdesk_ticket_id.user_id)

    def _warranty_auto_env(self):
        """The case as the Draft Job Automation User of its company (approved E10); in superuser
        mode when it is not configured, for the notifications only."""
        self.ensure_one()
        company = self.company_id
        if company._warranty_draft_job_config_problems():
            # sudo: system notification of a configuration problem (no automation user).
            return self.sudo()
        return self.with_user(company.warranty_draft_job_user_id).with_context(
            allowed_company_ids=company.ids)

    def _warranty_after_eligibility_check(self, result, steps):
        """Approved E3 / E7 / A1 / A2: after each check of an automatic case, the planners get
        an actionable To-Do unless the approval was requested from the approvers."""
        super()._warranty_after_eligibility_check(result, steps)
        if not self.warranty_auto_created or self.state != 'eligibility_checked':
            return
        case = self._warranty_auto_env()
        if result == 'eligible':
            if not self.company_id.warranty_case_approval_required:
                summary = _("Approve automatic warranty case %s", self.name)
                note = Markup('<p>%s</p>') % _(
                    "The case is Eligible. Warranty Case Approval Required is off: a Helpdesk user "
                    "approves it with Approve Case; the Draft Service Job is then prepared "
                    "automatically.")
            elif self.case_approval_activity_ids.filtered('active'):
                warranty_auto_close_todos(case, _("Eligible: approval requested from %s.", ', '.join(
                    self.case_approval_activity_ids.filtered('active').user_id.mapped('name'))))
                return
            else:
                summary = _("Automatic warranty case %s: approval cannot be requested", self.name)
                note = Markup('<p>%s</p>') % _(
                    "The case is Eligible but no Warranty Case Approval User (other than the case "
                    "creator and the eligibility checker) is configured for %s.",
                    self.company_id.name)
        else:
            label = dict(self._fields['eligibility_result']._description_selection(self.env))
            summary = _("Automatic warranty case %(case)s: %(result)s", case=self.name,
                        result=label.get(result, result))
            note = Markup('<p>%s</p><ul>%s</ul>') % (
                _("No draft job is prepared before an Eligible result and the approval. Resolve "
                  "the reasons (for example remove the service of a failed card from Linked Free "
                  "Services) and run Check Eligibility again."),
                Markup('').join(Markup('<li>%s</li>') % text
                                for passed, text in steps if not passed))
        warranty_auto_todo(case, self._warranty_auto_planners(), summary, note)

    def action_approve_case(self):
        """Approved E3 / A1: the manual approval of an automatic case prepares its Draft
        Service Job (once: never again after a job, also a cancelled one, approved E6)."""
        result = super().action_approve_case()
        for case in self.filtered(lambda case: case.warranty_auto_created
                                  and case.state == 'approved' and not case.service_job_ids):
            case._warranty_auto_prepare_job()
        return result

    def _warranty_auto_prepare_job(self):
        """Prepare Service Job as the Draft Job Automation User, with all its checks (merge, D3
        windows, duplicates, templates), in a savepoint: a failure keeps the approval and gives
        the planners the reason."""
        self.ensure_one()
        problems = self.company_id._warranty_draft_job_config_problems()
        if not problems:
            # The pending tracking is posted first: a rolled back savepoint clears the precommit.
            self.env.cr.precommit.run()
            try:
                with self.env.cr.savepoint():
                    self._warranty_auto_env().action_prepare_service_job()
                return True
            except (UserError, ValidationError, AccessError) as error:
                problems = [warranty_auto_error(error)]
        reason = ' '.join(problems)
        _logger.warning("Draft Job from Service: no draft job for %s: %s", self.name, reason)
        case = self._warranty_auto_env()
        case._message_log(body=Markup('<p><b>%s</b></p><p>%s</p>') % (
            _("Draft service job not prepared automatically after the approval"), reason))
        warranty_auto_todo(case, self._warranty_auto_planners(),
                           _("Prepare the service job of %s", self.name),
                           Markup('<p>%s</p><p>%s</p>') % (reason, _(
                               "Fix the cause, then use Prepare Service Job on the case.")))
        return False

    def action_prepare_service_job(self):
        result = super().action_prepare_service_job()
        job = self.open_service_job_id
        if self.warranty_auto_created and self.state == 'approved' and job.state == 'draft':
            self._warranty_auto_job_created(job)
        return result

    def _warranty_auto_job_created(self, job):
        """Approved E7 / E8: services Draft Job Created; their due alerts and the automation
        To-Dos are replaced by one To-Do to plan the draft job."""
        self.ensure_one()
        services = job.entitlement_ids
        services._warranty_auto_write({'warranty_auto_job_state': 'job_created',
                                       'warranty_auto_job_note': False})
        text = _("Draft service job %s prepared: plan it from the job.", job.name)
        alerts = services.due_alert_activity_ids.filtered('active')
        if alerts:
            alerts.action_feedback(feedback=text)
        for service in services:
            warranty_auto_close_todos(service, text)
        warranty_auto_close_todos(self, text)
        warranty_auto_todo(job, self._warranty_auto_planners(),
                           _("Plan draft service job %s", job.name),
                           Markup('<p>%s</p>') % _(
                               "Automatic case %s approved: enter the Planned Date and the "
                               "technicians, then Plan Job and Confirm (the Field Service visit "
                               "is created at confirmation).", self.name))


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    warranty_auto_created = fields.Boolean(related='warranty_case_id.warranty_auto_created',
                                           string='Created by Draft Job from Service')
    warranty_auto_todo_ids = fields.Many2many(
        'mail.activity', 'warranty_service_job_auto_todo_rel', 'job_id', 'activity_id',
        string='Automatic Draft Job To-Dos', readonly=True, copy=False,
        context={'active_test': False})

    def write(self, vals):
        if 'warranty_auto_todo_ids' in vals \
                and self.env.context.get('warranty_auto_job_marker') is not _AUTO_JOB_MARKER:
            raise UserError(_("The automatic Draft Job To-Dos are set by Draft Job from Service."))
        result = super().write(vals)
        # The planning To-Do is done once the job leaves Draft (planned or cancelled).
        if vals.get('state') and vals['state'] != 'draft':
            for job in self:
                warranty_auto_close_todos(job, _("Service job %s is no longer Draft.", job.name))
        return result


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _warranty_late_service_forbidden_approvers(self, requester):
        """Approved K5: the Draft Job Automation User never approves late-service exceptions."""
        return super()._warranty_late_service_forbidden_approvers(requester) | (
            self.warranty_draft_job_user_id)
