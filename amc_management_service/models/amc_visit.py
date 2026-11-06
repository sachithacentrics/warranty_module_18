from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.amc_management.models.amc_contract import _marked
from odoo.addons.amc_management.models.amc_visit import PROTECTED_VISIT_FIELDS

# Service links are written by the service chain only (never by the UI, import or RPC).
PROTECTED_VISIT_FIELDS.update({'warranty_case_id', 'service_job_id', 'task_id', 'worksheet_id'})

# AMC usage units -> warranty worksheet usage units (same meaning, other keys).
USAGE_UNIT_MAP = {'hours': 'operating_hours', 'cycles': 'cycles', 'km': 'km',
                  'units': 'units_produced', 'other': 'other'}
# Warranty cases that still hold their AMC visits.
OPEN_CASE_STATES = ('new', 'eligibility_checked', 'approved', 'job_created', 'in_progress',
                    'chargeable')


class AmcContractVisit(models.Model):
    _inherit = 'amc.contract.visit'

    # AMC-H02 / H04: service traceability.
    warranty_case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True,
                                       copy=False, index=True, ondelete='set null')
    helpdesk_ticket_id = fields.Many2one(related='warranty_case_id.helpdesk_ticket_id',
                                         string='Helpdesk Ticket', store=True)
    service_job_id = fields.Many2one('warranty.service.job', string='Service Job',
                                     readonly=True, copy=False, index=True,
                                     ondelete='set null')
    task_id = fields.Many2one('project.task', string='Field Service Visit', readonly=True,
                              copy=False, ondelete='set null')
    worksheet_id = fields.Many2one('warranty.job.worksheet', string='Worksheet', readonly=True,
                                   copy=False, ondelete='set null')

    def _amc_manual_completion_allowed(self):
        """AMC-F01: with the service chain installed, AMC visits are consumed only by their
        Service Job completion (customer sign-off), never manually."""
        return False

    def _amc_check_not_in_service(self):
        for visit in self:
            if visit.warranty_case_id and visit.warranty_case_id.state in OPEN_CASE_STATES:
                raise UserError(_("AMC visit %(visit)s is on warranty case %(case)s: reject or "
                                  "remove it from the case first.", visit=visit.name,
                                  case=visit.warranty_case_id.name))
        return super()._amc_check_not_in_service()

    def _amc_service_problems(self):
        """Service Merge Compatibility for AMC (AMC-F03 / E09; SRS 2.5 / 13): open, of one
        running contract, not on another open case."""
        problems = []
        contracts = self.contract_id
        if len(contracts) > 1:
            problems.append(_("the AMC visits belong to several contracts (%s): one service "
                              "request per contract", ', '.join(contracts.mapped('name'))))
        sites = self.mapped('site_id')
        if len(sites) > 1:
            problems.append(_("the AMC visits are at several sites (%s)",
                              ', '.join(sites.mapped('display_name'))))
        for visit in self:
            if visit.state != 'pending':
                problems.append(_("%(visit)s is %(state)s (only Pending AMC visits can be "
                                  "requested)", visit=visit.name,
                                  state=dict(visit._fields['state']._description_selection(
                                      visit.env))[visit.state]))
            if visit.contract_id.state not in ('active', 'expiring'):
                problems.append(_("contract %(contract)s of %(visit)s is %(state)s",
                                  contract=visit.contract_id.name, visit=visit.name,
                                  state=visit.contract_id._amc_state_label()))
            if visit.warranty_case_id and visit.warranty_case_id.state in OPEN_CASE_STATES:
                problems.append(_("%(visit)s is already on the open warranty case %(case)s",
                                  visit=visit.name, case=visit.warranty_case_id.name))
        return problems

    def _amc_link_case(self, case):
        self._amc_marked().write({'warranty_case_id': case.id, 'state': 'scheduled'})
        self.sudo()._amc_log(_("Linked to warranty case %(case)s (ticket %(ticket)s).", case=case.name,
                        ticket=case.helpdesk_ticket_id.display_name))

    def _amc_release(self, reason):
        """Back to Pending, not consumed (cancelled job / rejected case, AMC-F07 / E07)."""
        visits = self.filtered(lambda v: v.state in ('scheduled', 'in_progress'))
        if visits:
            visits._amc_marked().write({'state': 'pending', 'warranty_case_id': False,
                                        'service_job_id': False, 'task_id': False,
                                        'worksheet_id': False, 'scheduled_date': False})
            visits.sudo()._amc_log(_("Released, not consumed: %s.", reason))
            visits.sudo()._amc_refresh_due_status()

    def _amc_marked(self):
        return _marked(self.sudo())

    def action_open_service_request(self):
        self._amc_check_coordinator()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Create Service Request"),
            'res_model': 'amc.service.request.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visit_ids': [(6, 0, self.ids)]},
        }

    @api.model
    def _amc_worksheet_usage_unit(self, unit):
        return USAGE_UNIT_MAP.get(unit, 'other') if unit else False
