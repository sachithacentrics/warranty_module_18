"""18.0.1.0.3 - Is Warranty on Helpdesk tickets (default off).

Existing warranty tickets stay visible: tickets with a warranty case or with Warranty tab data
(site, product or serial) get Is Warranty ticked. No other data is changed."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE helpdesk_ticket t SET is_warranty = TRUE
         WHERE COALESCE(t.is_warranty, FALSE) = FALSE
           AND (EXISTS (SELECT 1 FROM warranty_case c WHERE c.helpdesk_ticket_id = t.id)
                OR t.warranty_site_id IS NOT NULL OR t.warranty_product_id IS NOT NULL
                OR t.warranty_serial_id IS NOT NULL)
    """)
    _logger.info("Is Warranty set on %s existing warranty ticket(s).", cr.rowcount)
