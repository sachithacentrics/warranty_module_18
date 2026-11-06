from odoo import _, fields, models
from odoo.exceptions import UserError

# Start Date Automation (D1 / D1b): the posting time is recorded by these hooks only. The marker
# is a Python object: no client (UI, import, JSON-RPC) can put it in a context.
_POSTING_MARKER = object()
CUSTOMER_MOVE_TYPES = ('out_invoice', 'out_refund')
POSTING_EVENTS = [
    ('posted', 'Posted'),
    ('reset_to_draft', 'Reset to Draft'),
    ('cancelled', 'Cancelled'),
]


class AccountMove(models.Model):
    _inherit = 'account.move'

    warranty_posted_at = fields.Datetime(
        string='Actual Posting Time', readonly=True, copy=False,
        help="Time the customer invoice / credit note was actually posted (latest valid "
             "posting); used as the warranty start of Invoice-basis warranty cards. Empty for "
             "entries posted before the Warranty Start Date Automation.")
    warranty_posting_event_ids = fields.One2many(
        'warranty.invoice.posting.event', 'move_id', string='Posting History', readonly=True)

    def write(self, vals):
        if 'warranty_posted_at' in vals \
                and self.env.context.get('warranty_posting_marker') is not _POSTING_MARKER:
            raise UserError(_("The actual posting time is recorded by the system when the "
                              "invoice is posted."))
        return super().write(vals)

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        moves = posted.filtered(lambda move: move.move_type in CUSTOMER_MOVE_TYPES
                                and move.state == 'posted')
        if moves:
            moves._warranty_record_posting_event('posted')
            moves._warranty_after_posting_change('posted')
        return posted

    def button_draft(self):
        posted = self.filtered(lambda move: move.move_type in CUSTOMER_MOVE_TYPES
                               and move.state == 'posted')
        result = super().button_draft()
        posted = posted.filtered(lambda move: move.state == 'draft')
        if posted:
            posted._warranty_record_posting_event('reset_to_draft')
            posted._warranty_after_posting_change('reset_to_draft')
        return result

    def button_cancel(self):
        moves = self.filtered(lambda move: move.move_type in CUSTOMER_MOVE_TYPES
                              and move.state != 'cancel')
        result = super().button_cancel()
        moves = moves.filtered(lambda move: move.state == 'cancel')
        if moves:
            moves._warranty_record_posting_event('cancelled')
        return result

    def _warranty_record_posting_event(self, event):
        now = fields.Datetime.now()
        # sudo: the posting history is written by system code only (no user write access).
        self.env['warranty.invoice.posting.event'].sudo().create([{
            'move_id': move.id,
            'event': event,
            'event_datetime': now,
            'user_id': self.env.uid,
        } for move in self])
        self.with_context(warranty_posting_marker=_POSTING_MARKER).write(
            {'warranty_posted_at': now if event == 'posted' else False})

    def _warranty_posting_info(self):
        """(posted_at, verification) of a posted customer invoice: the recorded posting time
        ('event'), else a verified historical posting ('history', D1a), else (False, False).
        create / write / invoice / accounting dates are never used."""
        self.ensure_one()
        if self.state != 'posted':
            return False, False
        if self.warranty_posted_at:
            return self.warranty_posted_at, 'event'
        posted_at = self._warranty_history_posting_time()
        return (posted_at, 'history') if posted_at else (False, False)

    def _warranty_history_posting_time(self):
        """D1a / Q4: time of the latest Draft -> Posted status tracking of the entry (written in
        the posting transaction), when the entry has not left Posted since; False otherwise."""
        self.ensure_one()
        field = self.env['ir.model.fields']._get(self._name, 'state')
        labels = set()
        for code, __ in self.env['res.lang'].get_installed():
            selection = self._fields['state']._description_selection(
                self.with_context(lang=code).env)
            labels.add(dict(selection)['posted'])
        # sudo: tracking values are only readable through their messages; read-only check.
        trackings = self.env['mail.tracking.value'].sudo().search([
            ('field_id', '=', field.id),
            ('mail_message_id.model', '=', self._name),
            ('mail_message_id.res_id', '=', self.id),
        ]).sorted(lambda tracking: (tracking.mail_message_id.date, tracking.id))
        if trackings and trackings[-1].new_value_char in labels:
            return trackings[-1].mail_message_id.date
        return False

    def _warranty_after_posting_change(self, event):
        """Card follow-up of a posting / reset: invoice reversals and source changes on
        confirmed cards (D11, Q16), automatic activation of Installation cards (D6)."""
        # sudo: the accountant may have no warranty rights; only the cards of these entries'
        # Sales Order lines are read and logged by system code.
        Card = self.env['warranty.card']
        for move in self.sudo():
            cards = move.invoice_line_ids.sale_line_ids.warranty_unit_ids.warranty_card_id
            confirmed = cards.filtered(
                lambda card: card.state in ('confirmed', 'suspended', 'expired'))
            if event == 'posted' and move.move_type == 'out_refund':
                for card in confirmed:
                    note = _(
                        "Credit note %(refund)s posted on %(when)s for %(invoice)s: warranty "
                        "dates unchanged; review whether a correction is needed.",
                        refund=move.name, when=card._warranty_format_datetime(
                            move.warranty_posted_at),
                        invoice=move.reversed_entry_id.name or _("the Sales Order lines"))
                    card._warranty_log_date_event('invoice_reversal', note,
                                                  invoice_id=move.id)
                    card._warranty_schedule_review_activity(note)
            elif event == 'reset_to_draft':
                for card in confirmed.filtered(lambda card: card.source_invoice_id == move):
                    card._warranty_log_date_event('source_change', _(
                        "Source invoice %s was reset to draft: warranty dates unchanged.",
                        move.name), invoice_id=move.id)
            Card |= cards
        Card.with_env(self.env)._warranty_auto_confirm()


class WarrantyInvoicePostingEvent(models.Model):
    """Append-only posting history of customer invoices / credit notes (D1b): every posting,
    reset to draft and cancellation, kept for audit."""
    _name = 'warranty.invoice.posting.event'
    _description = 'Invoice Posting Event'
    _order = 'event_datetime desc, id desc'

    move_id = fields.Many2one(
        'account.move', string='Journal Entry', required=True, ondelete='cascade',
        index=True, readonly=True)
    event = fields.Selection(POSTING_EVENTS, string='Event', required=True, readonly=True)
    event_datetime = fields.Datetime(string='Date / Time', required=True, readonly=True)
    user_id = fields.Many2one('res.users', string='User', readonly=True)
    company_id = fields.Many2one(
        related='move_id.company_id', string='Company', store=True, index=True)

    def write(self, vals):
        # No user has write / unlink access (ACL); system code never changes an event.
        raise UserError(_("The invoice posting history cannot be changed."))
