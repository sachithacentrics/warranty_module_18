from odoo import _, models


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    def _warranty_open_work(self):
        work = super()._warranty_open_work()
        # sudo: names only, for the card's controlled actions.
        replacements = self.env['warranty.replacement'].sudo().search([
            ('warranty_card_id', '=', self.id), ('state', 'in', ('draft', 'submitted', 'approved'))])
        backups = self.env['warranty.backup.unit'].sudo().search([
            ('warranty_case_id.warranty_card_id', '=', self.id),
            ('state', 'in', ('issued', 'overdue'))])
        return work + replacements.mapped('name') + backups.mapped('name')


class WarrantyCardAction(models.Model):
    _inherit = 'warranty.card.action'

    def _warranty_problems_correct_serial(self):
        problems = super()._warranty_problems_correct_serial()
        if self.unit_ids.indoor_serial_id or self.unit_ids.outdoor_serial_id:
            problems.append(_("Indoor / Outdoor serials of a kit are not corrected here."))
        return problems

    def _warranty_problems_extend(self):
        """An Indoor / Outdoor replacement gave that serial its own dates: the unit end date alone
        would not extend it."""
        problems = super()._warranty_problems_extend()
        own = self.unit_ids.filtered(lambda unit: unit.indoor_end_date or unit.outdoor_end_date)
        if own:
            problems.append(_("Units %s have Indoor / Outdoor dates from a replacement: they are "
                              "not extended here.", ', '.join(own.mapped('name'))))
        return problems


class WarrantyHistory(models.Model):
    _inherit = 'warranty.history'

    def _warranty_history_queries(self):
        return super()._warranty_history_queries() + [
            """SELECT p.warranty_card_id, p.warranty_unit_id, c.company_id, 'replacement',
                      'Replacement: ' || initcap(p.state), p.create_date, p.create_uid, p.name, NULL::text
                 FROM warranty_replacement p
                 JOIN warranty_card c ON c.id = p.warranty_card_id""",
            """SELECT w.warranty_card_id, NULL::integer, c.company_id, 'backup',
                      'Backup unit: ' || initcap(b.state), b.create_date, b.create_uid, b.name, NULL::text
                 FROM warranty_backup_unit b
                 JOIN warranty_case w ON w.id = b.warranty_case_id
                 JOIN warranty_card c ON c.id = w.warranty_card_id""",
            """SELECT w.warranty_card_id, NULL::integer, c.company_id, 'repair',
                      'Repair: ' || initcap(replace(r.state, '_', ' ')), r.create_date, r.create_uid, r.name, NULL::text
                 FROM repair_order r
                 JOIN warranty_case w ON w.id = r.warranty_case_id
                 JOIN warranty_card c ON c.id = w.warranty_card_id""",
        ]
