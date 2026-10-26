from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .warranty_service_job import NONCOMPLETION_REASONS, VISIT_OUTCOMES

# Approved completion lock (V6 / C1-C2): warranty visits are closed only by the warranty
# completion / cancellation (Parts 4.7 / 4.8) through _warranty_close_visits(). The marker is a
# Python object: no client (UI, JSON-RPC, import) can put it in a context, and a sudo() write
# alone does not pass the lock.
_WARRANTY_CLOSE_MARKER = object()
CLOSED_TASK_STATES = ('1_done', '1_canceled')
# Standard customer signature of the Sign Report (industry_fsm portal, written with sudo).
SIGNOFF_FIELDS = {'worksheet_signature', 'worksheet_signed_by'}
# Set only by the warranty completion / non-completion (close marker).
OUTCOME_FIELDS = {'warranty_visit_outcome', 'warranty_noncompletion_reason',
                  'warranty_noncompletion_notes'}
# Approved L3 / L10: visit attempt history of a closed warranty visit (not changed later).
LOCKED_VISIT_FIELDS = OUTCOME_FIELDS | {'planned_date_begin', 'date_deadline', 'user_ids',
                                        'state', 'fsm_done', 'warranty_visit_no',
                                        'warranty_entitlement_ids', 'warranty_completion_date'}


class ProjectTask(models.Model):
    """Field Service visit of a warranty Service Job (SRS 2.6 / #27: Helpdesk Ticket ->
    Service Job -> Field Service task)."""
    _inherit = 'project.task'

    warranty_service_job_id = fields.Many2one(
        'warranty.service.job', string='Service Job', readonly=True, copy=False,
        index='btree_not_null')
    warranty_case_id = fields.Many2one(
        related='warranty_service_job_id.warranty_case_id', store=True, string='Warranty Case')
    warranty_entitlement_ids = fields.Many2many(
        'warranty.service.entitlement', 'warranty_task_entitlement_rel', 'task_id',
        'entitlement_id', string='Free Services', readonly=True, copy=False)
    warranty_visit_no = fields.Integer(string='Visit No.', readonly=True, copy=False)
    warranty_worksheet_ids = fields.One2many('warranty.job.worksheet', 'task_id',
                                             string='Warranty Worksheets', readonly=True)
    warranty_worksheet_count = fields.Integer(compute='_compute_warranty_worksheet_count',
                                              compute_sudo=True)
    # Approved K7 / L2 option B: SRS Job Outcome of the visit, separate from the task status.
    warranty_visit_outcome = fields.Selection(VISIT_OUTCOMES, string='Visit Outcome',
                                              readonly=True, copy=False)
    # Flexible service dates (requirement 4): actual completion of the visit (Complete Visit).
    warranty_completion_date = fields.Datetime(string='Actual Completion Date', readonly=True,
                                               copy=False)
    # Phase 4.8 (SRS 2.8, approved L1): why the visit was not completed.
    warranty_noncompletion_reason = fields.Selection(
        NONCOMPLETION_REASONS, string='Non-completion Reason', readonly=True, copy=False)
    warranty_noncompletion_notes = fields.Text(string='Non-completion Notes', readonly=True,
                                               copy=False)

    # Standard Worksheet buttons only for a single task-hosted instance (approved W4 and
    # shared-worksheet fix); otherwise the Worksheets list of the instances.
    warranty_hide_standard_worksheet = fields.Boolean(
        compute='_compute_warranty_worksheet_count', compute_sudo=True)

    @api.depends('warranty_worksheet_ids.template_id')
    def _compute_warranty_worksheet_count(self):
        for task in self:
            sheets = task.warranty_worksheet_ids
            task.warranty_worksheet_count = len(sheets)
            task.warranty_hide_standard_worksheet = len(sheets) > 1 or any(
                sheet.template_id.res_model == 'warranty.job.worksheet' for sheet in sheets)

    def _warranty_closure_attempt(self, vals):
        """Warranty tasks this write would close (Done / Cancelled / Task Done); already
        closed tasks keep their status."""
        closing = self.browse()
        if vals.get('state') in CLOSED_TASK_STATES:
            closing |= self.filtered(lambda task: task.state != vals['state'])
        if vals.get('fsm_done'):
            closing |= self.filtered(lambda task: not task.fsm_done)
        return closing.filtered('warranty_service_job_id')

    def _warranty_check_closure(self, tasks):
        if tasks and self.env.context.get('warranty_close_marker') is not _WARRANTY_CLOSE_MARKER:
            raise UserError(_(
                "Warranty visit %s is completed through the warranty completion (worksheets, "
                "usage reading, customer sign-off) or cancelled through the service job; it "
                "cannot be marked Done or Cancelled directly.",
                ', '.join(tasks.mapped('name'))))

    def _warranty_check_outcome(self):
        # Approved K7: the visit outcome is set by the warranty completion only.
        if self.env.context.get('warranty_close_marker') is not _WARRANTY_CLOSE_MARKER:
            raise UserError(_("The visit outcome is set by the warranty completion (Complete "
                              "Visit)."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('warranty_service_job_id') and (
                    vals.get('state') in CLOSED_TASK_STATES or vals.get('fsm_done')):
                self._warranty_check_closure(self.new({'name': vals.get('name') or ''}))
            if OUTCOME_FIELDS & set(vals):
                self._warranty_check_outcome()
        return super().create(vals_list)

    def write(self, vals):
        self._warranty_check_closure(self._warranty_closure_attempt(vals))
        if OUTCOME_FIELDS & set(vals):
            self._warranty_check_outcome()
        locked = self._warranty_locked_changes(vals)
        if locked and self.env.context.get('warranty_close_marker') is not _WARRANTY_CLOSE_MARKER:
            raise UserError(_(
                "Visit %s is closed: its date, technicians, status, outcome and reason are kept "
                "as visit history and cannot be changed.", ', '.join(locked.mapped('name'))))
        # Approved K2: the customer sign-off of a warranty visit is the standard Sign Report
        # signature (portal, written with sudo); no direct UI / API write by users.
        if SIGNOFF_FIELDS & set(vals) and not self.env.su \
                and self.filtered('warranty_service_job_id'):
            raise UserError(_("The customer sign-off of a warranty visit is captured with Sign "
                              "Report."))
        return super().write(vals)

    def _inverse_state(self):
        """Approved L3 / L10: a warranty visit closed as Cancelled (not completed or cancelled)
        keeps its planned date and deadline as visit history: the standard unscheduling of
        cancelled future tasks (project_enterprise) is not applied to warranty visits (they have
        no recurrence, the other effect of this method)."""
        visits = self.filtered(lambda task: task.warranty_service_job_id
                               and task.state == '1_canceled')
        return super(ProjectTask, self - visits)._inverse_state()

    def _warranty_locked_changes(self, vals):
        """Closed warranty visits whose history fields this write would change."""
        names = LOCKED_VISIT_FIELDS & set(vals)
        if not names:
            return self.browse()
        closed = self.filtered(lambda task: task.warranty_service_job_id
                               and (task.fsm_done or task.state in CLOSED_TASK_STATES))

        def changed(task):
            for name in names:
                field = task._fields[name]
                if field.type in ('one2many', 'many2many'):
                    return True
                new = field.convert_to_record(field.convert_to_cache(vals[name], task), task)
                if new != task[name]:
                    return True
            return False
        return closed.filtered(changed)

    def action_warranty_visit_not_completed(self):
        """Visit Not Completed button (approved L1): reason, notes and next action."""
        self.ensure_one()
        # sudo: Helpdesk users may not read Field Service tasks; access checked on the job.
        job = self.sudo().warranty_service_job_id.with_env(self.env)
        if not job:
            raise UserError(_("%s is not a warranty visit.", self.sudo().name))
        job._warranty_check_visit_access()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Visit Not Completed"),
            'res_model': 'warranty.visit.noncompletion.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_id': self.id},
        }

    def action_warranty_complete_visit(self):
        """Complete Visit button (approved K1): the warranty completion of this visit."""
        self.ensure_one()
        # sudo: Helpdesk users may not read Field Service tasks; the job access is checked as
        # the user in _warranty_complete_visit().
        job = self.sudo().warranty_service_job_id.with_env(self.env)
        if not job:
            raise UserError(_("%s is not a warranty visit.", self.sudo().name))
        if job.job_type == 'chargeable_inspection':
            # Approved C7: the inspection result is recorded with the completion.
            job._warranty_check_completion_access()
            problems = job._warranty_visit_completion_problems(self.sudo())
            if problems:
                raise UserError(_("Visit %(task)s cannot be completed:\n%(problems)s",
                                  task=self.sudo().name,
                                  problems='\n'.join('- %s' % problem for problem in problems)))
            return {
                'type': 'ir.actions.act_window',
                'name': _("Inspection Result"),
                'res_model': 'warranty.inspection.result.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_task_id': self.id},
            }
        return job._warranty_complete_visit(self)

    def _warranty_close_visits(self, vals):
        """The only way to close warranty visits: reserved for the approved Part 4.7
        completion and Part 4.8 cancellation flows (server code; private method)."""
        if vals.get('state') == '1_done' or vals.get('fsm_done'):
            # Approved M6: no completion while the service job is Awaiting Parts / Workshop.
            blockers = [reason for job in self.warranty_service_job_id
                        for reason in job._warranty_completion_blockers()]
            if blockers:
                raise UserError('\n'.join(blockers))
        return self.with_context(warranty_close_marker=_WARRANTY_CLOSE_MARKER).write(vals)

    def action_fsm_validate(self, stop_running_timers=False):
        """Mark as done: refused for warranty visits before the stop-timers dialog."""
        self._warranty_check_closure(self.filtered(
            lambda task: task.warranty_service_job_id and not task.fsm_done))
        return super().action_fsm_validate(stop_running_timers=stop_running_timers)

    def action_timer_start(self):
        """Approved V1: the standard Field Service timer starts the warranty visit. The
        technician needs an active employee in the task company (the timesheet is created on
        that employee when the timer stops)."""
        job = self.warranty_service_job_id
        if job and not self.user_timer_id.timer_start and self.display_timesheet_timer:
            # sudo: technicians may not read employees; only the user's own employee is checked.
            if not self.env['hr.employee'].sudo().search_count([
                    ('user_id', '=', self.env.uid), ('company_id', '=', self.company_id.id)],
                    limit=1):
                raise UserError(_("You need an active employee in %(company)s to start the "
                                  "warranty visit %(task)s: ask your administrator to create "
                                  "it.", company=self.company_id.name, task=self.name))
        result = super().action_timer_start()
        if job and self.user_timer_id.timer_start:
            job._warranty_start_visit(self)
        return result

    def _track_template(self, changes):
        """Approved customer-email fix (a): warranty tasks never send the stage email
        templates (e.g. "Intervention Scheduled") to the customer."""
        res = super()._track_template(changes)
        if self[:1].warranty_service_job_id:
            res.pop('stage_id', None)
        return res

    def _send_task_rating_mail(self, force_send=False):
        """Approved customer-email fix (a): no stage rating requests for warranty tasks."""
        return super(ProjectTask, self.filtered(lambda task: not task.warranty_service_job_id))\
            ._send_task_rating_mail(force_send=force_send)

    def action_view_warranty_worksheets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Worksheets"),
            'res_model': 'warranty.job.worksheet',
            'view_mode': 'list,form',
            'domain': [('task_id', '=', self.id)],
            'context': {'create': False},
        }

    @api.constrains('warranty_service_job_id', 'helpdesk_ticket_id', 'project_id')
    def _check_warranty_chain(self):
        """No standalone warranty Field Service task (SRS #27, approved D8): a Field Service
        task of a ticket with warranty cases needs its Service Job, and a visit of a Service
        Job belongs to the job's ticket."""
        for task in self:
            job = task.warranty_service_job_id
            if job and task.helpdesk_ticket_id != job.helpdesk_ticket_id:
                raise ValidationError(_("The Field Service task %(task)s must belong to the Helpdesk "
                                        "ticket of service job %(job)s.", task=task.name,
                                        job=job.name))
            if not job and task.is_fsm and task.helpdesk_ticket_id.warranty_case_ids:
                raise ValidationError(_(
                    "Ticket %s has warranty cases: its Field Service tasks are created by "
                    "confirming a Service Job (Helpdesk Ticket -> Service Job -> Field Service "
                    "task).", task.helpdesk_ticket_id.display_name))
