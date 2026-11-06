"""18.0.1.3.0 - Service Alert Responsible User(s) became multi-user fields.

Copies the single values of 18.0.1.2.0 (responsible user on company / policy / warranty
card, system activity links on service entitlements) into the new many2many relations.
Databases that never had the 18.0.1.2.0 columns are skipped. The old columns are left in
place unchanged."""
import logging

from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)

# (table, old column, relation table, relation column of the record, relation column of the value)
SINGLE_TO_MULTI = [
    ('res_company', 'warranty_service_alert_user_id',
     'warranty_company_alert_user_rel', 'company_id', 'user_id'),
    ('warranty_policy', 'service_alert_user_id',
     'warranty_policy_alert_user_rel', 'policy_id', 'user_id'),
    ('warranty_card', 'service_alert_user_id',
     'warranty_card_alert_user_rel', 'card_id', 'user_id'),
    ('warranty_service_entitlement', 'due_alert_activity_id',
     'warranty_entitlement_due_activity_rel', 'entitlement_id', 'activity_id'),
    ('warranty_service_entitlement', 'expiry_reminder_activity_id',
     'warranty_entitlement_expiry_activity_rel', 'entitlement_id', 'activity_id'),
]


def migrate(cr, version):
    for table, column, relation, record_column, value_column in SINGLE_TO_MULTI:
        if not column_exists(cr, table, column):
            continue
        cr.execute(f"""
            INSERT INTO {relation} ({record_column}, {value_column})
            SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL
            ON CONFLICT DO NOTHING
        """)
        _logger.info("warranty_management upgrade from %s: copied %s %s.%s value(s) to %s",
                     version, cr.rowcount, table, column, relation)
