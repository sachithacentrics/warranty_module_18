from odoo import _, api, fields, models
from odoo.exceptions import UserError

VISIT_ACTIONS = [
    ('complete', 'Complete'),
    ('cancel', 'Cancel'),
]


class AmcContractVisitAction(models.TransientModel):
    """Manual completion (AMC Coordinator) or cancellation (AMC Manager) of AMC visits."""
    _name = 'amc.contract.visit.action'
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
