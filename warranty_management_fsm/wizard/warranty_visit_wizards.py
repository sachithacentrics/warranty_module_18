from odoo import api, fields, models

from ..models.warranty_service_job import NEXT_ACTIONS, NONCOMPLETION_REASONS


class WarrantyVisitPlanningMixin(models.AbstractModel):
    _name = 'warranty.visit.planning.mixin'
    _description = 'Warranty Next Visit Planning'

    planned_date = fields.Datetime(string='New Planned Date')
    main_technician_id = fields.Many2one('res.users', string='Main Technician',
                                         domain="[('id', 'in', technician_candidate_ids)]")
    technician_candidate_ids = fields.Many2many('res.users', compute='_compute_candidates')

    def _job(self):
        raise NotImplementedError

    @api.depends('main_technician_id')
    def _compute_candidates(self):
        for wizard in self:
            job = wizard._job()
            wizard.technician_candidate_ids = self.env['res.users'].search(
                job._technician_domain(job.company_id)) if job else self.env['res.users']


class WarrantyVisitNoncompletionWizard(models.TransientModel):
    """Visit Not Completed (approved L1 / L9)."""
    _name = 'warranty.visit.noncompletion.wizard'
    _inherit = 'warranty.visit.planning.mixin'
    _description = 'Visit Not Completed'

    task_id = fields.Many2one('project.task', string='Visit', required=True, readonly=True,
                              ondelete='cascade')
    # Shared visit (approved Q5): the service job reported as not completed.
    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True,
                             ondelete='cascade')
    reason = fields.Selection(NONCOMPLETION_REASONS, string='Non-completion Reason',
                              required=True)
    notes = fields.Text(string='Notes', required=True)
    next_action = fields.Selection(NEXT_ACTIONS, string='Next Action', required=True,
                                   default='reschedule')
    # Approved L9: only Helpdesk users enter the new date and technicians.
    can_plan = fields.Boolean(compute='_compute_can_plan')
    support_technician_ids = fields.Many2many(
        'res.users', 'warranty_noncompletion_wizard_support_rel', 'wizard_id', 'user_id',
        string='Support Technicians', domain="[('id', 'in', technician_candidate_ids)]")

    def _job(self):
        # sudo: the visit's job (Helpdesk users may not read Field Service tasks).
        return self.job_id or self.task_id.sudo().warranty_service_job_id.with_env(self.env)

    @api.depends_context('uid')
    @api.depends('task_id')
    def _compute_can_plan(self):
        for wizard in self:
            wizard.can_plan = self.env.user.has_group('helpdesk.group_helpdesk_user')

    def action_apply(self):
        self.ensure_one()
        planning = None
        if self.next_action == 'reschedule' and (self.planned_date or self.main_technician_id):
            planning = {'planned_date': self.planned_date,
                        'main_technician': self.main_technician_id,
                        'support_technicians': self.support_technician_ids}
        self._job()._warranty_visit_not_completed(self.task_id, self.reason, self.notes,
                                                  self.next_action, planning)
        return {'type': 'ir.actions.act_window_close'}


class WarrantyServiceJobPlanWizard(models.TransientModel):
    """Plan Next Visit (approved L3 / L6 / L9: Helpdesk users)."""
    _name = 'warranty.service.job.plan.wizard'
    _inherit = 'warranty.visit.planning.mixin'
    _description = 'Plan Next Visit'

    job_id = fields.Many2one('warranty.service.job', string='Service Job', required=True,
                             readonly=True, ondelete='cascade')
    planned_date = fields.Datetime(required=True)
    main_technician_id = fields.Many2one(required=True)
    support_technician_ids = fields.Many2many(
        'res.users', 'warranty_plan_wizard_support_rel', 'wizard_id', 'user_id',
        string='Support Technicians', domain="[('id', 'in', technician_candidate_ids)]")

    def _job(self):
        return self.job_id

    def action_apply(self):
        self.ensure_one()
        self.job_id._warranty_plan_next_visit(self.planned_date, self.main_technician_id,
                                              self.support_technician_ids)
        return {'type': 'ir.actions.act_window_close'}


class WarrantyServiceJobCancelWizard(models.TransientModel):
    """Cancel Job (approved L7: Helpdesk users, required reason)."""
    _name = 'warranty.service.job.cancel.wizard'
    _description = 'Cancel Service Job'

    job_id = fields.Many2one('warranty.service.job', string='Service Job', required=True,
                             readonly=True, ondelete='cascade')
    reason = fields.Text(string='Cancellation Reason', required=True)

    def action_apply(self):
        self.ensure_one()
        self.job_id._warranty_cancel_job(self.reason)
        return {'type': 'ir.actions.act_window_close'}
