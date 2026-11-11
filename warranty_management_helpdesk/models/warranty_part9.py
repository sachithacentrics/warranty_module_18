from odoo import models


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    def _warranty_open_work(self):
        work = super()._warranty_open_work()
        # sudo: names only, for the card's controlled actions.
        cases = self.env['warranty.case'].sudo().search([
            ('warranty_card_id', '=', self.id),
            ('state', 'not in', ('completed', 'closed', 'rejected'))])
        return work + cases.mapped('name')


class WarrantyHistory(models.Model):
    _inherit = 'warranty.history'

    def _warranty_history_queries(self):
        return super()._warranty_history_queries() + [
            """SELECT w.warranty_card_id, w.warranty_unit_id, c.company_id, 'case',
                      'Case created', w.create_date, w.create_uid,
                      w.name, initcap(replace(w.case_type, '_', ' ')), 'warranty.case', w.id
                 FROM warranty_case w
                 JOIN warranty_card c ON c.id = w.warranty_card_id""",
            self._warranty_history_status_query(
                'warranty.case', 'case', 'Case',
                "warranty_case x JOIN warranty_card c ON c.id = x.warranty_card_id",
                'c.id', 'x.warranty_unit_id'),
        ]
