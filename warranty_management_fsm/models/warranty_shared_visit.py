"""Shared Field Service visit (BA-approved v1, doc/shared_visit_design.md): ONE Field Service
visit for several compatible Service Jobs, which stay separate records (own case, card, free
services, worksheets, MRFs, history); every job is completed / not completed on its own line."""
import psycopg2

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.warranty_management_helpdesk.models.warranty_service_entitlement import (
    warranty_same_site)

from .project_task import _WARRANTY_CLOSE_MARKER, CLOSED_TASK_STATES
from .warranty_service_job import NONCOMPLETION_REASONS, VISIT_OUTCOMES

# Lines are written only by the warranty visit code (Python object: not settable by a client).
_SHARED_LINE_MARKER = object()
SHARED_JOB_TYPES = ('warranty',)


class WarrantySharedVisitLine(models.Model):
    _name = 'warranty.shared.visit.line'
    _description = 'Shared Field Service Visit - Service Job'
    _order = 'task_id, id'

    task_id = fields.Many2one('project.task', string='Shared Visit', required=True,
                              readonly=True, index=True, ondelete='restrict')
    job_id = fields.Many2one('warranty.service.job', string='Service Job', required=True,
                             readonly=True, index=True, ondelete='restrict')
    company_id = fields.Many2one(related='job_id.company_id', store=True)
    job_state = fields.Selection(related='job_id.state', string='Job Status')
    warranty_case_id = fields.Many2one(related='job_id.warranty_case_id')
    helpdesk_ticket_id = fields.Many2one(related='job_id.helpdesk_ticket_id')
    entitlement_ids = fields.Many2many(related='job_id.entitlement_ids')
    outcome = fields.Selection(VISIT_OUTCOMES, string='Visit Outcome', readonly=True)
    completion_date = fields.Datetime(string='Actual Completion Date', readonly=True)
    noncompletion_reason = fields.Selection(NONCOMPLETION_REASONS, string='Non-completion Reason',
                                            readonly=True)
    noncompletion_notes = fields.Text(string='Non-completion Notes', readonly=True)
    # Approved Q4: the shared customer sign-off, kept on every job of the visit.
    signed_by = fields.Char(string='Customer Sign-off', readonly=True)
    task_closed = fields.Boolean(compute='_compute_task_closed')

    _sql_constraints = [('task_job_unique', 'unique(task_id, job_id)',
                         'A service job is only once on a shared visit.')]

    @api.depends('task_id.state', 'task_id.fsm_done')
    def _compute_task_closed(self):
        for line in self:
            task = line.sudo().task_id
            line.task_closed = task.fsm_done or task.state in CLOSED_TASK_STATES

    def _check_marker(self):
        if self.env.context.get('warranty_shared_line_marker') is not _SHARED_LINE_MARKER:
            raise UserError(_("Shared visit lines are maintained by the warranty visit actions."))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_marker()
        return super().create(vals_list)

    def write(self, vals):
        self._check_marker()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_never(self):
        raise UserError(_("Shared visit lines are kept as visit history."))

    def _warranty_record(self, vals):
        # sudo: written by the checked completion / non-completion / cancellation of the job.
        return self.sudo().with_context(warranty_shared_line_marker=_SHARED_LINE_MARKER).write(vals)

    def action_complete(self):
        """Complete this job on the shared visit (the 4.7 Complete Visit of the job)."""
        self.ensure_one()
        job = self.sudo().job_id.with_env(self.env)
        return job._warranty_complete_visit(self.sudo().task_id)

    def action_not_completed(self):
        """Visit Not Completed for this job only (approved Q5)."""
        self.ensure_one()
        job = self.sudo().job_id.with_env(self.env)
        job._warranty_check_visit_access()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Visit Not Completed - %s", job.name),
            'res_model': 'warranty.visit.noncompletion.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_id': self.sudo().task_id.id, 'default_job_id': job.id},
        }


class ProjectTask(models.Model):
    _inherit = 'project.task'

    warranty_shared_job_ids = fields.Many2many(
        'warranty.service.job', 'warranty_shared_visit_job_rel', 'task_id', 'job_id',
        string='Shared Visit Service Jobs', readonly=True, copy=False)
    warranty_shared_line_ids = fields.One2many('warranty.shared.visit.line', 'task_id',
                                               string='Service Jobs on this Visit', readonly=True)

    def _warranty_close_shared_visit(self):
        """Approved Q7: the shared visit closes when every job on it has its outcome - Done when
        at least one job was completed on it, else Cancelled; through the reserved close path."""
        for task in self.sudo():
            lines = task.warranty_shared_line_ids
            if not lines or not all(lines.mapped('outcome')) or task.fsm_done \
                    or task.state in CLOSED_TASK_STATES:
                continue
            completed = lines.filtered(lambda line: line.outcome == 'completed')
            vals = {'state': '1_canceled'}
            if completed:
                vals = {'fsm_done': True, 'state': '1_done',
                        'warranty_completion_date': max(completed.mapped('completion_date'))}
            task.with_context(warranty_close_marker=_WARRANTY_CLOSE_MARKER).write(vals)


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    shared_visit_ids = fields.Many2many(
        'project.task', 'warranty_shared_visit_job_rel', 'job_id', 'task_id',
        string='Shared Visits', readonly=True, copy=False)

    def _warranty_check_shared_access(self):
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can create shared Field Service visits."))
        self.check_access('write')

    def _warranty_shared_visit_problems(self):
        """Compatibility of the selected jobs (approved Q1-Q3): two or more standard Warranty
        jobs, Draft / Planned, ticket and case, no visit yet, one company / customer / site."""
        problems = []
        if len(self) < 2:
            problems.append(_("Select two or more service jobs."))
        labels = dict(self._fields['state']._description_selection(self.env))
        for job in self:
            reasons = []
            if job.job_type not in SHARED_JOB_TYPES:
                reasons.append(_("only standard Warranty jobs (chargeable and inspection jobs "
                                 "keep their own visit)"))
            if job.state not in ('draft', 'planned'):
                reasons.append(_("must be Draft or Planned (is %s)", labels[job.state]))
            # sudo: Helpdesk users may not read Field Service tasks.
            if job.sudo()._warranty_all_visits():
                reasons.append(_("already has a Field Service visit"))
            if not job.warranty_case_id or not job.helpdesk_ticket_id:
                reasons.append(_("no Helpdesk ticket and warranty case yet: use Create or Link "
                                 "Helpdesk Ticket"))
            if reasons:
                problems.append('%s: %s' % (job.name, '; '.join(reasons)))
        if len(self.company_id) > 1:
            problems.append(_("The service jobs must belong to one company."))
        if len(self.commercial_partner_id) > 1:
            problems.append(_("The service jobs must belong to one customer."))
        site = self[:1].site_id
        other = self.filtered(lambda job: not warranty_same_site(job.site_id, site))
        if other:
            problems.append(_("The service jobs must have the same service site (%(site)s): "
                              "%(jobs)s.", site=site.display_name or '-',
                              jobs=', '.join(other.mapped('name'))))
        return problems

    def _warranty_raise_shared(self, problems):
        raise UserError(_("No shared Field Service visit can be created:\n%s",
                          '\n'.join('- %s' % problem for problem in problems)))

    def action_open_shared_visit_wizard(self):
        """Service Jobs list: Action > Create Merged Field Service Visit."""
        self._warranty_check_shared_access()
        problems = self._warranty_shared_visit_problems()
        if problems:
            self._warranty_raise_shared(problems)
        first = self[:1]
        return {
            'type': 'ir.actions.act_window',
            'name': _("Create Merged Field Service Visit"),
            'res_model': 'warranty.shared.visit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_job_ids': [(6, 0, self.ids)],
                'default_planned_date': first.planned_date,
                'default_main_technician_id': first.main_technician_id.id,
                'default_support_technician_ids': [(6, 0, first.support_technician_ids.ids)],
            },
        }

    def _warranty_lock_jobs(self):
        """Duplicate prevention: the jobs are locked; a job processed in another transaction
        is refused."""
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "SELECT id FROM warranty_service_job WHERE id IN %s FOR UPDATE NOWAIT",
                    [tuple(self.ids)])
        except psycopg2.errors.LockNotAvailable:
            raise UserError(_("These service jobs are being processed by another user: try "
                              "again."))

    def _warranty_create_shared_visit(self, planned_date, main_technician,
                                      support_technicians=None):
        """Create Merged Field Service Visit (approved v1): every job is planned, validated
        (Prepare checks, Confirm checks and the eligibility revalidation) and confirmed onto ONE
        Field Service visit, all or nothing; no service job is created or merged."""
        self._warranty_check_shared_access()
        self._warranty_lock_jobs()
        self.invalidate_recordset()
        problems = self._warranty_shared_visit_problems()
        if not planned_date or not main_technician:
            problems.append(_("Planned Visit Date and Main Technician are required."))
        if problems:
            self._warranty_raise_shared(problems)
        support_technicians = support_technicians or self.env['res.users']
        with self.env.cr.savepoint():
            for job in self:
                job.write({'planned_date': planned_date,
                           'main_technician_id': main_technician.id,
                           'support_technician_ids': [(6, 0, support_technicians.ids)]})
                if job.state == 'draft':
                    job.action_prepare_for_confirmation()
            for job in self:
                reasons = job._warranty_confirm_problems()
                if not reasons:
                    ok, __, steps = job._warranty_revalidate()
                    if not ok:
                        reasons = [_("eligibility revalidation failed: %s", '; '.join(
                            text for passed, text in steps if not passed))]
                if reasons:
                    problems.append('%s: %s' % (job.name, '; '.join(reasons)))
            if problems:
                self._warranty_raise_shared(problems)
            task = self._warranty_create_shared_task()
            for job in self:
                job._warranty_create_visit(task)
        return task

    def _warranty_create_shared_task(self):
        first = self[0]
        site = first.site_id or first.partner_id
        tickets = self.helpdesk_ticket_id
        # sudo: Helpdesk users create the visit without Field Service rights (as Confirm).
        task = self.env['project.task'].sudo().create({
            'name': _("Shared visit %(jobs)s - %(site)s", jobs=', '.join(self.mapped('name')),
                      site=site.display_name),
            'project_id': first.company_id._warranty_fsm_project().id,
            'company_id': first.company_id.id,
            'partner_id': site.id,
            'planned_date_begin': first.planned_date,
            'user_ids': [(6, 0, (first.main_technician_id | first.support_technician_ids).ids)],
            # Approved Q3: a ticket only when all jobs share it.
            'helpdesk_ticket_id': tickets.id if len(tickets) == 1 else False,
            'warranty_shared_job_ids': [(6, 0, self.ids)],
            'warranty_entitlement_ids': [(6, 0, self.entitlement_ids.ids)],
            'warranty_visit_no': 1,
            'description': '\n'.join(case.customer_complaint for case in self.warranty_case_id
                                     if case.customer_complaint),
        })
        self.env['warranty.shared.visit.line'].sudo().with_context(
            warranty_shared_line_marker=_SHARED_LINE_MARKER).create(
            [{'task_id': task.id, 'job_id': job.id} for job in self])
        task._message_log(body=Markup('<p>%s</p>') % _(
            "Shared Field Service visit for %(jobs)s created by %(user)s: each service job keeps "
            "its own case, card, free services, worksheets, materials and history and is "
            "completed separately.", jobs=', '.join(self.mapped('name')),
            user=self.env.user.name))
        return task
