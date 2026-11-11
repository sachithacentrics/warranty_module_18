from odoo import models

# Provision entries of an invoice: the cards of the invoiced warranty units.
PROVISION_SOURCE = """account_move x
                   JOIN account_move_line ml ON ml.move_id = x.warranty_provision_invoice_id
                   JOIN sale_order_line_invoice_rel rel ON rel.invoice_line_id = ml.id
                   JOIN warranty_unit u ON u.sale_order_line_id = rel.order_line_id
                   JOIN warranty_card c ON c.id = u.warranty_card_id"""
# Reserve utilization entries and inspection fee credit notes: the card of their case.
CASE_MOVE_SOURCE = """account_move x
                   JOIN warranty_case w
                     ON w.id = COALESCE(x.warranty_b2_case_id, x.warranty_inspection_case_id)
                   JOIN warranty_card c ON c.id = w.warranty_card_id"""


class WarrantyHistory(models.Model):
    """Warranty cost lines and warranty journal entries. Amounts are not shown: the source record
    is opened with the user's own rights. Journal entry rows are for accounting users only
    (record rules)."""
    _inherit = 'warranty.history'

    def _warranty_history_queries(self):
        return super()._warranty_history_queries() + [
            """SELECT w.warranty_card_id, NULL::integer, c.company_id, 'cost',
                      'Cost line created', l.create_date, l.create_uid, l.name,
                      initcap(replace(l.cost_type, '_', ' ')), 'warranty.cost.line', l.id
                 FROM warranty_cost_line l
                 JOIN warranty_case w ON w.id = l.case_id
                 JOIN warranty_card c ON c.id = w.warranty_card_id""",
            self._warranty_history_status_query(
                'warranty.cost.line', 'cost', 'Cost line',
                """warranty_cost_line x
                   JOIN warranty_case w ON w.id = x.case_id
                   JOIN warranty_card c ON c.id = w.warranty_card_id""", 'c.id'),
            f"""SELECT DISTINCT c.id, u.id, c.company_id, 'accounting',
                       CASE WHEN x.reversed_entry_id IS NOT NULL
                            THEN 'Provision reversal created'
                            ELSE 'Provision entry created' END,
                       x.create_date, x.create_uid, COALESCE(x.name, '/'), NULL::text,
                       'account.move', x.id
                  FROM {PROVISION_SOURCE}""",
            f"""SELECT DISTINCT q.* FROM ({self._warranty_history_status_query(
                'account.move', 'accounting', 'Provision entry', PROVISION_SOURCE, 'c.id',
                'u.id')}) q""",
            f"""SELECT c.id, NULL::integer, c.company_id, 'accounting',
                       CASE WHEN x.warranty_b2_case_id IS NOT NULL
                            THEN 'Reserve utilization entry created'
                            ELSE 'Inspection fee credit note created' END,
                       x.create_date, x.create_uid, COALESCE(x.name, '/'), w.name,
                       'account.move', x.id
                  FROM {CASE_MOVE_SOURCE}""",
            self._warranty_history_status_query(
                'account.move', 'accounting', 'Journal entry', CASE_MOVE_SOURCE, 'c.id'),
        ]
