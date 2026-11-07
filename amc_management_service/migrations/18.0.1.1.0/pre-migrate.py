"""Upgrade of a database with amc_management_service 18.0.1.0.0: rename the XML ids changed by
the coding standards; the records are kept (same approach as
amc_management/migrations/18.0.1.3.0). Idempotent."""
import logging

_logger = logging.getLogger(__name__)

RENAMES = {
    'amc_service_request_wizard_view_form': 'amc_service_request_view_form',
    'helpdesk_ticket_view_form': 'helpdesk_ticket_view_form_warranty',
    'access_amc_service_request_wizard_coordinator': 'access_amc_service_request_coordinator',
}


def migrate(cr, version):
    if not version:
        return
    for old, new in RENAMES.items():
        cr.execute("""
            UPDATE ir_model_data SET name = %(new)s
             WHERE module = 'amc_management_service' AND name = %(old)s
               AND NOT EXISTS (SELECT 1 FROM ir_model_data
                                WHERE module = 'amc_management_service' AND name = %(new)s)
        """, {'old': old, 'new': new})
        if cr.rowcount:
            _logger.info("amc_management_service: XML id %s renamed to %s", old, new)
