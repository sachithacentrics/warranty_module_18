from odoo import _, fields, models


class WarrantyCardDownloadRequestWizard(models.TransientModel):
    _name = 'warranty.card.download.request.wizard'
    _description = 'Request Warranty Card PDF Download Approval'

    warranty_card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', required=True, readonly=True)
    download_count = fields.Integer(
        related='warranty_card_id.print_count', string='Download Count')
    reason = fields.Text(string='Reason', required=True)

    def action_submit(self):
        self.ensure_one()
        request = self.env['warranty.card.download.request']._submit(
            self.warranty_card_id, self.reason)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Download approval request %s sent to the approvers.",
                             request.name),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
