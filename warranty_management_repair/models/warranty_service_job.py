from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.warranty_management_fsm.models.warranty_service_job import CLOSED_JOB_STATES

from .repair_order import INACTIVE_CASE_STATES, INSPECTION_JOB_TYPES


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    warranty_backup_unit_count = fields.Integer(compute='_compute_warranty_backup_unit_count')
    # UX: the Workshop actions are not part of an AMC preventive / free visit (SRS Figure 8).
    warranty_case_type = fields.Selection(related='warranty_case_id.case_type',
                                          string='Case Type')
    # UX: Workshop Intake is not offered again once the case's Repair Order is in the workshop.
    warranty_workshop_repair_count = fields.Integer(
        related='warranty_case_id.warranty_workshop_repair_count')

    def _compute_warranty_backup_unit_count(self):
        counts = self.env['warranty.backup.unit']._warranty_backup_counts(
            'warranty_service_job_id', self)
        for job in self:
            job.warranty_backup_unit_count = counts.get(job._origin.id, 0)

    def action_view_warranty_backup_units(self):
        self.ensure_one()
        return self.env['warranty.backup.unit']._warranty_backup_action(
            [('warranty_service_job_id', '=', self.id)])

    # ------------------------------------------------------------------ Figure 6 (SRS 2.9)
    def _warranty_workshop_ticket(self, team_option):
        """SRS 2.9 "Helpdesk / Service Job initiates": the ticket of an open job of an active case,
        whose team uses Returns / Repairs (same conditions as the ticket buttons)."""
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_user'):
            raise AccessError(_("Only Inventory users can start a workshop repair."))
        case = self.warranty_case_id
        ticket = self.helpdesk_ticket_id
        if self.state in CLOSED_JOB_STATES or not case or case.state in INACTIVE_CASE_STATES \
                or not ticket:
            raise UserError(_("Service job %s is closed or has no active warranty case.",
                              self.name))
        if not ticket[team_option]:
            raise UserError(_("Enable %(option)s on Helpdesk team %(team)s.",
                              option=ticket.team_id._fields[team_option].string,
                              team=ticket.team_id.name))
        return ticket

    def action_warranty_workshop_intake(self):
        """Workshop Intake: the Return wizard of the job's ticket (Warranty Repair Intake, the
        delivery of the machine and every intake check unchanged)."""
        ticket = self._warranty_workshop_ticket('use_product_returns')
        return self.warranty_case_id._warranty_intake_action(ticket)

    def action_warranty_open_repair(self):
        """Create / Open Repair Order of the job's case (shared with the case header)."""
        ticket = self._warranty_workshop_ticket('use_product_repairs')
        return self.warranty_case_id._warranty_open_repair_action(ticket)

    def _warranty_set_hold(self, hold_action, reason):
        """SM3: Workshop Repair hold = the on-site visit decided the workshop."""
        result = super()._warranty_set_hold(hold_action, reason)
        if hold_action == 'workshop' and self.warranty_case_id:
            self.warranty_case_id._warranty_set_service_mode('workshop', _(
                "Service Mode set to Workshop Repair: service job %(job)s was put on Workshop "
                "Repair hold by %(user)s. The job keeps control of the completion.",
                job=self.name, user=self.env.user.name))
        return result

    def _warranty_completion_blockers(self):
        """SRS 2.5 / 13: no completion with an open repair. Job-controlled completion is otherwise
        unchanged; inspection jobs (Figure 4) are not blocked. Incomplete / Reschedule does not
        use this hook, so a pickup visit keeps the existing reason Workshop Repair Required."""
        problems = super()._warranty_completion_blockers()
        if self.job_type in INSPECTION_JOB_TYPES:
            return problems
        case = self.warranty_case_id
        repairs = case._warranty_active_repairs().filtered(
            lambda repair: not repair.warranty_equipment_returned
            and not case._warranty_replacement_covers(repair))
        if repairs:
            problems.append(_(
                "Repair Order %(repairs)s of the warranty case: the machine has not been returned "
                "to the customer.", repairs=', '.join(repairs.mapped('name'))))
        problems.extend(case._warranty_replacement_problems())
        return problems
