"""18.0.1.2.6 - Warranty card PDF with several units (one sheet and the Unit Warranty Schedule).

The stored soft copy of a confirmed / expired card with several printed units still has the
earlier layout (one sheet per unit); Send to Customer emails the stored soft copy, so it is
regenerated once in the same protected attachment (user decision). Single-unit cards, Download
Count, download history and approvals are not touched."""
import logging

from markupsafe import Markup

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cards = env['warranty.card'].search([('state', 'in', ('confirmed', 'expired'))]).filtered(
        lambda card: len(card._warranty_card_print_units()) > 1 and card.pdf_attachment_id)
    for card in cards:
        card._regenerate_soft_copy()
        card._message_log(body=Markup('<p>%s</p>') % (
            "Warranty card PDF soft copy regenerated with the multi-unit layout (module upgrade). "
            "Download Count unchanged."))
    _logger.info("warranty_management upgrade from %s: soft copy regenerated for %s multi-unit "
                 "card(s): %s", version, len(cards), ', '.join(cards.mapped('name')) or '-')
