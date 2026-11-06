import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """BA decision 2026-10-28 (Warranty Scope Mode limitation removed): the stored arch of the
    Pending Services button view still references the removed field
    warranty_free_services_enabled, and is validated with the ticket form before its own file is
    reloaded. Remove only that condition from the stored arch; no record data is changed."""
    cr.execute("""
        UPDATE ir_ui_view view
           SET arch_db = (SELECT jsonb_object_agg(
                                     lang, replace(arch, ' or not warranty_free_services_enabled', ''))
                            FROM jsonb_each_text(view.arch_db) AS arch_lang(lang, arch))
          FROM ir_model_data data
         WHERE data.model = 'ir.ui.view' AND data.res_id = view.id
           AND data.module = 'warranty_management_helpdesk'
           AND data.name = 'helpdesk_ticket_view_form_warranty_pending'
           AND view.arch_db::text LIKE '%%warranty_free_services_enabled%%'
    """)
    _logger.info("Warranty Scope Mode removal: %s stored view arch(s) cleaned.", cr.rowcount)
