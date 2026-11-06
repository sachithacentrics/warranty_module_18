from odoo import _, models, fields
from odoo.exceptions import UserError

from .warranty_card import START_DATE_SOURCES

DATE_LOG_EVENTS = [
    ('activation', 'Activation'),
    ('activation_failed', 'Automatic Activation Failed'),
    ('exception', 'Authorized Exception'),
    ('correction', 'Date Correction'),
    ('extension', 'Warranty Extension'),
    ('source_change', 'Source Change'),
    ('invoice_reversal', 'Invoice Reversal'),
    ('delivery_return', 'Delivery Return'),
    ('task_reopened', 'Installation Task Reopened'),
    ('task_cancelled', 'Installation Task Cancelled'),
]


class WarrantyCardDateLog(models.Model):
    """Warranty Date History (approved D11): append-only audit of the start date automation –
    activation, exceptions, corrections (before / after, reason) and source events. Written by
    system code only; each record also has an internal note in the card chatter."""
    _name = 'warranty.card.date.log'
    _description = 'Warranty Date History'
    _order = 'log_datetime desc, id desc'

    card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', required=True, ondelete='restrict',
        index=True, readonly=True)
    event = fields.Selection(DATE_LOG_EVENTS, string='Event', required=True, readonly=True)
    log_datetime = fields.Datetime(
        string='Date / Time', required=True, readonly=True, default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='User', readonly=True)
    old_start = fields.Date(string='Previous Start Date', readonly=True)
    old_end = fields.Date(string='Previous End Date', readonly=True)
    new_start = fields.Date(string='New Start Date', readonly=True)
    new_end = fields.Date(string='New End Date', readonly=True)
    old_installation = fields.Date(string='Previous Installation Date', readonly=True)
    new_installation = fields.Date(string='New Installation Date', readonly=True)
    start_date_source = fields.Selection(START_DATE_SOURCES, string='Start Date Source',
                                         readonly=True)
    source_datetime = fields.Datetime(string='Source Date / Time', readonly=True)
    picking_id = fields.Many2one('stock.picking', string='Delivery', readonly=True)
    invoice_id = fields.Many2one('account.move', string='Invoice / Credit Note', readonly=True)
    task_reference = fields.Char(string='Installation Task', readonly=True)
    reason = fields.Text(string='Reason / Details', readonly=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'warranty_card_date_log_attachment_rel', 'log_id', 'attachment_id',
        string='Evidence', readonly=True)
    company_id = fields.Many2one(
        related='card_id.company_id', string='Company', store=True, index=True)

    def write(self, vals):
        if set(vals) - {'attachment_ids'}:
            raise UserError(_("The warranty date history cannot be changed."))
        return super().write(vals)
