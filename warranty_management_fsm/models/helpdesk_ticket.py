from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.warranty_management_helpdesk.models.warranty_service_entitlement import (
    INACTIVE_CASE_STATES)


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    def _compute_warranty_pending_service_ids(self):
        """Pending Services display / count: same availability as the case selection."""
        super()._compute_warranty_pending_service_ids()
        for ticket in self:
            ticket.warranty_pending_service_ids = \
                ticket.warranty_pending_service_ids._warranty_selectable_services(ticket)
            ticket.warranty_pending_service_count = len(ticket.warranty_pending_service_ids)

    def _warranty_linked_jobs(self):
        """The service-origin jobs of this ticket, cancelled ones released."""
        self.ensure_one()
        if not self._origin:
            return self.env['warranty.service.job']
        # sudo: the jobs of the ticket are read for the link only.
        return self.env['warranty.service.job'].sudo().search([
            ('origin_ticket_id', '=', self._origin.id), ('job_origin', '=', 'service'),
            ('state', '!=', 'cancelled')])

    def _warranty_is_linked_ticket(self):
        return super()._warranty_is_linked_ticket() or bool(self._warranty_linked_jobs())

    def _warranty_linked_services(self):
        return super()._warranty_linked_services() \
            | self._warranty_linked_jobs().entitlement_ids.with_env(self.env)

    def _warranty_waiting_service_job(self):
        """The oldest service-origin job waiting for its warranty case on this ticket; a ticket
        linked to several jobs gets one case per job (see warranty.case._warranty_waiting_job)."""
        self.ensure_one()
        Job = self.env['warranty.service.job']
        if not self._origin:
            return Job
        # sudo: the jobs of the ticket are read for the link only.
        return Job.sudo().search([
            ('origin_ticket_id', '=', self._origin.id), ('job_origin', '=', 'service'),
            ('warranty_case_id', '=', False), ('state', 'in', ('draft', 'planned'))],
            order='id', limit=1).with_env(self.env)

    def _warranty_job_linked_cases(self):
        """The active warranty cases already linked to the service-origin jobs of this ticket."""
        self.ensure_one()
        # sudo: the jobs of the ticket are read for the link only.
        jobs = self.env['warranty.service.job'].sudo().search([
            ('origin_ticket_id', '=', self.id), ('job_origin', '=', 'service'),
            ('warranty_case_id', '!=', False)])
        return jobs.warranty_case_id.filtered(
            lambda case: case.state not in INACTIVE_CASE_STATES).with_env(self.env)

    def _warranty_open_job_cases(self, cases):
        self.ensure_one()
        action = self.action_view_warranty_cases()
        action['domain'] = [('id', 'in', cases.ids)]
        if len(cases) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')], 'res_id': cases.id})
        return action

    def action_create_warranty_case(self):
        """Duplicate prevention: the job's case exists, open it; the wizard stays for a job
        still waiting for its case and for tickets without service-origin job."""
        self.ensure_one()
        cases = self._warranty_job_linked_cases()
        if cases and not self._warranty_waiting_service_job():
            return self._warranty_open_job_cases(cases)
        return super().action_create_warranty_case()

    def action_generate_fsm_task(self):
        """Approved D8: the standard Plan Intervention must not bypass the Service Job for
        tickets with warranty cases; other tickets keep the standard behaviour."""
        if self.warranty_case_ids:
            raise UserError(_(
                "Ticket %s has warranty cases: plan the visit with Prepare Service Job / Confirm "
                "Service Job on the warranty case.", self.display_name))
        return super().action_generate_fsm_task()
