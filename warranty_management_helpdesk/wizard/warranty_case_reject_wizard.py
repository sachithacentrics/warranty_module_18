from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.warranty_case import REJECTION_REASONS


class WarrantyCaseRejectWizard(models.TransientModel):
    """Reject Case (approved Part 3.6b Q44-Q48): reason required, note required for Other."""
    _name = 'warranty.case.reject.wizard'
    _description = 'Reject Warranty Case'

    case_id = fields.Many2one('warranty.case', string='Warranty Case', required=True,
                              readonly=True, ondelete='cascade')
    eligibility_result = fields.Selection(related='case_id.eligibility_result')
    rejection_reason = fields.Selection(REJECTION_REASONS, string='Rejection Reason',
                                        required=True)
    rejection_note = fields.Text(string='Note')

    @api.constrains('rejection_reason', 'rejection_note')
    def _check_note(self):
        for wizard in self:
            if wizard.rejection_reason == 'other' and not (wizard.rejection_note or '').strip():
                raise UserError(_("Enter a note for the rejection reason Other."))

    def action_reject(self):
        self.ensure_one()
        self.case_id._warranty_reject(self.rejection_reason, (self.rejection_note or '').strip())
        return {'type': 'ir.actions.act_window_close'}
