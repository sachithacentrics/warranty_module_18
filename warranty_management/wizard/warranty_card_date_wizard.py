from odoo import _, api, fields, models


class WarrantyCardDateWizard(models.TransientModel):
    """Record Start Date Exception (before confirmation, D1a / D8 / Q14) and Correct Warranty
    Dates (Confirmed / Suspended cards, D9 / D10 / Q11); group Warranty: Date Correction."""
    _name = 'warranty.card.date.wizard'
    _description = 'Warranty Date Exception / Correction'

    card_id = fields.Many2one('warranty.card', string='Warranty Card', required=True,
                              readonly=True)
    mode = fields.Selection([
        ('exception', 'Start Date Exception'),
        ('correction', 'Date Correction'),
    ], string='Action', required=True, readonly=True)
    start_criterion = fields.Selection(related='card_id.start_criterion')
    current_start_date = fields.Date(related='card_id.warranty_start_date',
                                     string='Current Start Date')
    current_end_date = fields.Date(related='card_id.warranty_end_date',
                                   string='Current End Date')
    missing_requirements = fields.Text(related='card_id.missing_requirements')
    new_start_date = fields.Date(string='New Start Date', required=True)
    new_end_date = fields.Date(
        string='New End Date', help="Custom Date Range only; otherwise calculated from the "
                                    "warranty duration.")
    expected_end_date = fields.Date(string='Resulting End Date',
                                    compute='_compute_preview')
    entitlement_note = fields.Text(string='Free Services', compute='_compute_preview')
    reason = fields.Text(string='Reason', required=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'warranty_card_date_wizard_attachment_rel', 'wizard_id',
        'attachment_id', string='Evidence')

    @api.depends('card_id', 'mode', 'new_start_date', 'new_end_date')
    def _compute_preview(self):
        for wizard in self:
            card = wizard.card_id
            start = wizard.new_start_date
            wizard.expected_end_date = start and card._warranty_correction_end_date(
                start, wizard.new_end_date)
            if wizard.mode != 'correction' or not card:
                wizard.entitlement_note = False
                continue
            recalculated, kept = card._warranty_correction_entitlements()
            lines = []
            if recalculated:
                lines.append(_("Recalculated from the new start date: %s",
                               ', '.join(recalculated.mapped('name'))))
            if kept:
                lines.append(_("Not changed (scheduled, finalized, selected for a job or "
                               "manually re-dated): %s", ', '.join(kept.mapped('name'))))
            wizard.entitlement_note = '\n'.join(lines) or False

    def action_apply(self):
        self.ensure_one()
        card = self.card_id
        if self.mode == 'exception':
            card._warranty_apply_exception(self.new_start_date, self.reason,
                                           self.attachment_ids)
        else:
            card._warranty_correct_dates(self.new_start_date, self.reason,
                                         end_date=self.new_end_date,
                                         attachments=self.attachment_ids)
        return {'type': 'ir.actions.act_window_close'}
