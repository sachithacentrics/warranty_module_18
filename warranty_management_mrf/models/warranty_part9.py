from odoo import models


class WarrantyHistory(models.Model):
    _inherit = 'warranty.history'

    def _warranty_history_queries(self):
        return super()._warranty_history_queries() + [
            """SELECT w.warranty_card_id, NULL::integer, c.company_id, 'material',
                      'Material request: ' || initcap(replace(m.state, '_', ' ')), m.create_date, m.create_uid, m.name, NULL::text
                 FROM material_purchase_requisition m
                 JOIN warranty_case w ON w.id = m.warranty_case_id
                 JOIN warranty_card c ON c.id = w.warranty_card_id""",
            """SELECT w.warranty_card_id, NULL::integer, c.company_id, 'claim',
                      'Vendor claim: ' || initcap(v.state), v.create_date, v.create_uid, v.name, NULL::text
                 FROM warranty_vendor_claim v
                 JOIN warranty_case w ON w.id = v.case_id
                 JOIN warranty_card c ON c.id = w.warranty_card_id""",
            """SELECT w.warranty_card_id, NULL::integer, c.company_id, 'claim',
                      'Vendor credit note: ' || initcap(m.state), r.create_date, r.create_uid,
                      COALESCE(m.name, '/'), v.name
                 FROM warranty_vendor_claim_recovery r
                 JOIN warranty_vendor_claim v ON v.id = r.claim_id
                 JOIN account_move m ON m.id = r.move_id
                 JOIN warranty_case w ON w.id = v.case_id
                 JOIN warranty_card c ON c.id = w.warranty_card_id""",
        ]
