from odoo import fields, models


class WarrantyMrfDeclineWizard(models.TransientModel):
    """Customer Declined (Phase 5.4): Not Covered lines the customer does not buy."""
    _name = 'warranty.mrf.decline.wizard'
    _description = 'Material Request Customer Decline'

    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     required=True, readonly=True)
    line_ids = fields.Many2many(
        'material.purchase.requisition.line', 'warranty_mrf_decline_wizard_line_rel',
        'wizard_id', 'line_id', string='Lines', required=True,
        domain="[('requisition_id', '=', requisition_id), "
               "('coverage_type', '=', 'not_covered'), ('chargeable_declined', '=', False)]")
    reason = fields.Text(string='Reason', required=True)

    def action_decline(self):
        self.ensure_one()
        self.requisition_id._warranty_decline_chargeable(self.line_ids, self.reason)
        return {'type': 'ir.actions.act_window_close'}


class WarrantyMrfReleaseExceptionWizard(models.TransientModel):
    """Approve Release Exception (Phase 5.4, D9): release before payment."""
    _name = 'warranty.mrf.release.exception.wizard'
    _description = 'Material Request Release Exception'

    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     required=True, readonly=True)
    order_id = fields.Many2one('sale.order', string='Parts Quotation', required=True,
                               domain="[('warranty_mrf_id', '=', requisition_id), "
                                      "('state', '=', 'sale')]")
    reason = fields.Text(string='Reason', required=True)

    def action_approve(self):
        self.ensure_one()
        self.requisition_id._warranty_approve_release_exception(self.order_id, self.reason)
        return {'type': 'ir.actions.act_window_close'}
