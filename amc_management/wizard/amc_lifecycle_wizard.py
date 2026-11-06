from odoo import _, api, fields, models
from odoo.exceptions import UserError

REASON_ACTIONS = [
    ('hold', 'Put On Hold'),
    ('close', 'Close Contract'),
]
VISIT_ACTIONS = [
    ('complete', 'Complete'),
    ('cancel', 'Cancel'),
]


class AmcContractReasonWizard(models.TransientModel):
    """Reason of a contract Hold / Close (AMC Manager; audit in the chatter)."""
    _name = 'amc.contract.reason.wizard'
    _description = 'AMC Contract Hold / Close Reason'

    contract_id = fields.Many2one('amc.contract', required=True, readonly=True)
    action = fields.Selection(REASON_ACTIONS, required=True, readonly=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.action == 'hold':
            return self.contract_id._amc_hold(self.reason)
        return self.contract_id._amc_close(self.reason)


class AmcVisitActionWizard(models.TransientModel):
    """Manual completion (AMC Coordinator) or cancellation (AMC Manager) of AMC visits."""
    _name = 'amc.visit.action.wizard'
    _description = 'AMC Visit Completion / Cancellation'

    visit_ids = fields.Many2many('amc.contract.visit', string='AMC Visits', required=True)
    action = fields.Selection(VISIT_ACTIONS, required=True, readonly=True)
    completion_date = fields.Date(string='Completion Date',
                                  default=fields.Date.context_today)
    usage_reading = fields.Float(string='Usage Reading', digits=(16, 2),
                                 help="Required for usage-based preventive visits.")
    usage_required = fields.Boolean(compute='_compute_usage_required')
    note = fields.Text(string='Service Notes / Reason')

    @api.depends('visit_ids')
    def _compute_usage_required(self):
        for wizard in self:
            wizard.usage_required = any(visit.visit_type == 'preventive' and visit.usage_unit
                                        for visit in wizard.visit_ids)

    def action_confirm(self):
        self.ensure_one()
        if self.action == 'cancel':
            return self.visit_ids._amc_cancel(self.note)
        self.visit_ids._amc_check_coordinator()
        if not self.visit_ids._amc_manual_completion_allowed():
            raise UserError(_("AMC visits are completed through their Service Job."))
        self.visit_ids._amc_consume(self.completion_date, self.usage_reading, self.note,
                                    source=_("Manual completion by %s", self.env.user.name))
        return True
