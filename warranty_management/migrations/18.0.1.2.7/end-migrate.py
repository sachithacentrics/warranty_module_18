"""18.0.1.2.7 - Completes the 18.0.1.2.6 soft copy regeneration where it did not run.

The UAT database reached 18.0.1.2.6 without the regeneration of the multi-unit soft copies
(WC/00011, WC/00026: no chatter note, attachments unchanged). Same step as 18.0.1.2.6 (user
decision: regenerate once, in the same protected attachment), skipping every card that already
has the regeneration note, so a database where 18.0.1.2.6 ran is not touched again. Download
Count, download history and approvals are not touched."""
import logging

from markupsafe import Markup

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

NOTE = ("Warranty card PDF soft copy regenerated with the multi-unit layout (module upgrade). "
        "Download Count unchanged.")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    done = env['mail.message'].search([('model', '=', 'warranty.card'),
                                       ('body', 'ilike', 'soft copy regenerated')]).mapped('res_id')
    cards = env['warranty.card'].search([('state', 'in', ('confirmed', 'expired')),
                                         ('id', 'not in', done)]).filtered(
        lambda card: len(card._warranty_card_print_units()) > 1 and card.pdf_attachment_id)
    for card in cards:
        card._regenerate_soft_copy()
        card._message_log(body=Markup('<p>%s</p>') % NOTE)
    _logger.info("warranty_management upgrade from %s: soft copy regenerated for %s multi-unit "
                 "card(s): %s", version, len(cards), ', '.join(cards.mapped('name')) or '-')
