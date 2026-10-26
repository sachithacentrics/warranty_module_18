from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from ..models.warranty_service_entitlement import SCHEDULED_STATES


class WarrantyServiceEntitlementScheduleWizard(models.TransientModel):
    """Schedule / Reschedule a free service (approved S1-S7): select the Scheduled Service
    Date in a monthly date picker; the other services already scheduled in that month are
    shown for information (no capacity restriction, S6)."""
    _name = 'warranty.service.entitlement.schedule.wizard'
    _description = 'Schedule Free Service'

    entitlement_id = fields.Many2one(
        'warranty.service.entitlement', string='Free Service', required=True, readonly=True)
    mode = fields.Selection([
        ('schedule', 'Schedule'),
        ('reschedule', 'Reschedule'),
    ], string='Mode', compute='_compute_mode')
    due_date = fields.Date(related='entitlement_id.due_date', string='Due Date')
    grace_period_end_date = fields.Date(
        related='entitlement_id.grace_period_end_date', string='Grace Period End Date')
    earliest_service_date = fields.Date(related='entitlement_id.earliest_service_date')
    latest_service_date = fields.Date(related='entitlement_id.latest_service_date')
    current_scheduled_date = fields.Date(
        related='entitlement_id.scheduled_date', string='Current Scheduled Date')
    scheduled_date = fields.Date(string='Scheduled Service Date', required=True)
    reason = fields.Text(string='Reason / Note')
    month_entitlement_ids = fields.Many2many(
        'warranty.service.entitlement', string='Already Scheduled in this Month',
        compute='_compute_month_entitlement_ids')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        entitlement = self.env['warranty.service.entitlement'].browse(
            values.get('entitlement_id'))
        if entitlement and 'scheduled_date' in fields_list and not values.get('scheduled_date'):
            today = entitlement.company_id._warranty_today()
            date = entitlement.scheduled_date or entitlement.due_date or today
            date = max(date, today)
            window = entitlement._warranty_allowed_range()
            if window:
                date = min(max(date, window[0]), window[1])
            elif entitlement.grace_period_end_date:
                date = min(date, entitlement.grace_period_end_date)
            values['scheduled_date'] = date
        return values

    @api.depends('entitlement_id.scheduled_date')
    def _compute_mode(self):
        for wizard in self:
            wizard.mode = 'reschedule' if wizard.entitlement_id.scheduled_date else 'schedule'

    @api.depends('scheduled_date', 'entitlement_id')
    def _compute_month_entitlement_ids(self):
        Entitlement = self.env['warranty.service.entitlement']
        for wizard in self:
            if not wizard.scheduled_date:
                wizard.month_entitlement_ids = Entitlement
                continue
            first_day = wizard.scheduled_date.replace(day=1)
            wizard.month_entitlement_ids = Entitlement.search([
                ('id', '!=', wizard.entitlement_id.id),
                ('company_id', '=', wizard.entitlement_id.company_id.id),
                ('state', 'in', SCHEDULED_STATES),
                ('scheduled_date', '>=', first_day),
                ('scheduled_date', '<', first_day + relativedelta(months=1)),
            ], order='scheduled_date, id')

    def action_confirm(self):
        self.ensure_one()
        self.entitlement_id._schedule_service(self.scheduled_date, self.reason)
        return {'type': 'ir.actions.act_window_close'}
