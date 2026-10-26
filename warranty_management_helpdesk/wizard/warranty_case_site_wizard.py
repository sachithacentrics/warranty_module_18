from odoo import api, fields, models


class WarrantyCaseSiteWizard(models.TransientModel):
    """Confirm Same Site (approved D6 rule 3)."""
    _name = 'warranty.case.site.wizard'
    _description = 'Confirm Same Service Site'

    case_id = fields.Many2one('warranty.case', string='Warranty Case', required=True,
                              readonly=True, ondelete='cascade')
    candidate_ids = fields.Many2many('res.partner', compute='_compute_candidate_ids')
    address_ids = fields.Many2many('res.partner', string='Same Site Addresses',
                                   domain="[('id', 'in', candidate_ids)]")
    reason = fields.Text(string='Reason', required=True)

    @api.depends('case_id')
    def _compute_candidate_ids(self):
        for wizard in self:
            wizard.candidate_ids = wizard.case_id._warranty_site_candidates()

    def action_apply(self):
        self.ensure_one()
        self.case_id._warranty_confirm_same_site(self.address_ids, self.reason)
        return {'type': 'ir.actions.act_window_close'}
