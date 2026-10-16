from odoo import _, fields, models
from odoo.exceptions import UserError


class WarrantyServiceEntitlementDueDateWizard(models.TransientModel):
    _name = 'warranty.service.entitlement.due.date.wizard'
    _description = 'Change Service Entitlement Due Date'

    entitlement_id = fields.Many2one(
        'warranty.service.entitlement', string='Service Entitlement', required=True,
        readonly=True)
    current_due_date = fields.Date(
        related='entitlement_id.due_date', string='Current Due Date')
    warranty_end_date = fields.Date(
        related='entitlement_id.warranty_card_id.warranty_end_date', string='Warranty End Date')
    new_due_date = fields.Date(string='New Due Date', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_apply(self):
        self.ensure_one()
        entitlement = self.entitlement_id
        if entitlement.state != 'draft':
            raise UserError(_("The due date can only be changed while the entitlement is Draft."))
        self.env['warranty.service.entitlement.date.log'].create({
            'entitlement_id': entitlement.id,
            'previous_due_date': entitlement.due_date,
            'new_due_date': self.new_due_date,
            'reason': self.reason,
        })
        entitlement.with_context(warranty_due_date_audited=True).write(
            {'due_date': self.new_due_date})
        entitlement._reschedule_system_activities()
        entitlement._update_due_status()
        return {'type': 'ir.actions.act_window_close'}
