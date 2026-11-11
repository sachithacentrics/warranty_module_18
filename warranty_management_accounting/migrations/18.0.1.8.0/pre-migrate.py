"""18.0.1.8.0: covered parts move to standard Odoo stock accounting (Figure 7 / SRS 17).

The custom per-usage draft entry (kinds 'reclass' / 'reclass_reversal') is removed. Journal
entries are never deleted: any such entry keeps its lines, state and case link and becomes an
ordinary journal entry (its type is cleared and it is listed in the log). Unique indexes of the
removed kinds are dropped. Columns of removed fields stay in the database (standard Odoo).

A database upgraded from before the reserve utilization entries (for example odoo.sh staging
from 18.0.1.6.2) has no warranty_b2_kind column: no such entry can exist there, so that step is
skipped."""
import logging

from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if column_exists(cr, 'account_move', 'warranty_b2_kind'):
        cr.execute("""SELECT id, name, state FROM account_move
                       WHERE warranty_b2_kind IN ('reclass', 'reclass_reversal')""")
        legacy = cr.fetchall()
        if legacy:
            _logger.warning("Warranty accounting 18.0.1.8.0: %s former parts expense "
                            "entr(y/ies) kept as ordinary journal entries (type cleared): %s",
                            len(legacy),
                            ', '.join('%s %s (%s)' % row for row in legacy))
            cr.execute("""UPDATE account_move SET warranty_b2_kind = NULL
                           WHERE warranty_b2_kind IN ('reclass', 'reclass_reversal')""")
    for name in ('account_move_warranty_b2_reclass_uniq', 'account_move_warranty_b2_reversal_uniq'):
        cr.execute("DROP INDEX IF EXISTS %s" % name)
    # Views that show removed fields: removed here, the ones still used are loaded again from
    # the module files (otherwise Odoo validates the old arch against the new fields first).
    cr.execute("""
        WITH views AS (
            DELETE FROM ir_model_data
             WHERE module = 'warranty_management_accounting' AND model = 'ir.ui.view'
               AND name IN %s
         RETURNING res_id)
        DELETE FROM ir_ui_view WHERE id IN (SELECT res_id FROM views)""", (VIEWS,))


VIEWS = ('res_config_settings_view_form_warranty_accounting',
         'res_config_settings_view_form_warranty_b2', 'view_move_form_warranty_b2',
         'view_move_tree_warranty_b2', 'view_move_search_warranty_b2',
         'warranty_mrf_consumption_view_list_b2', 'warranty_mrf_consumption_view_form_b2',
         'warranty_mrf_consumption_view_search_b2', 'warranty_b2_verify_wizard_view_form',
         'warranty_case_view_form_b2')
