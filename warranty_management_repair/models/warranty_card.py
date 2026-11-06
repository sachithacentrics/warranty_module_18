from markupsafe import Markup

from odoo import _, api, fields, models

from odoo.addons.warranty_management_mrp.models.mrp_bom import ROLE_FIELDS

from .warranty_replacement import ROLE_DATE_FIELDS

DATE_LOG_REPLACEMENT = 'replacement'


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    warranty_replacement_ids = fields.One2many(
        'warranty.replacement', 'warranty_card_id', string='Replacements', readonly=True)
    # The PDF labels of the existing report (SRS 9.10 step 7).
    warranty_replacement_updated = fields.Boolean(
        string='Updated After Replacement', compute='_compute_warranty_replacement_updated',
        compute_sudo=True)
    warranty_replacement_dates_changed = fields.Boolean(
        string='Replacement Changed Unit Dates', compute='_compute_warranty_replacement_updated',
        compute_sudo=True)

    @api.depends('warranty_replacement_ids.state', 'warranty_replacement_ids.dates_changed')
    def _compute_warranty_replacement_updated(self):
        for card in self:
            done = card.warranty_replacement_ids.filtered(
                lambda replacement: replacement.state == 'done')
            card.warranty_replacement_updated = bool(done)
            card.warranty_replacement_dates_changed = any(done.mapped('dates_changed'))

    @api.depends('warranty_replacement_ids.state')
    def _compute_replacement_count(self):
        """SRS 10.2: replacement records of the card, rejected requests excluded. sudo: count."""
        for card in self:
            card.replacement_count = len(card.sudo().warranty_replacement_ids.filtered(
                lambda replacement: replacement.state != 'rejected'))

    def _warranty_replacement_serial_date_rows(self):
        """PDF rows of the kit units with dates of their own on one serial: both serials are shown,
        so the customer sees which dates apply to which serial."""
        self.ensure_one()
        labels = {'indoor': _("Indoor Unit"), 'outdoor': _("Outdoor Unit")}
        rows = []
        for unit in self.unit_warranty_ids:
            if not any(unit[name] for names in ROLE_DATE_FIELDS.values() for name in names):
                continue
            for role, field in ROLE_FIELDS.items():
                if unit[field]:
                    start, end = unit._warranty_role_dates(role)
                    rows.append({'unit': unit.name, 'role': labels[role],
                                 'serial': unit[field].name, 'start': start, 'end': end})
        return rows

    def _warranty_correct_dates(self, start_date, reason, end_date=False, attachments=None):
        """Correct Warranty Dates writes every unit: a unit whose dates were set by a Done
        replacement keeps them (SRS 11.3), and the note says so. An Indoor / Outdoor replacement has
        its own serial dates, which this correction does not write: the other serial follows it."""
        self.ensure_one()
        kept = {}
        for replacement in self.sudo().warranty_replacement_ids.filtered(
                lambda record: record.state == 'done' and record.dates_changed
                and record._warranty_replacement_replaces_unit()):
            unit = replacement.warranty_unit_id
            kept[unit] = (unit.start_date, unit.end_date)
        log = super()._warranty_correct_dates(start_date, reason, end_date=end_date,
                                              attachments=attachments)
        if kept:
            for unit, (start, end) in kept.items():
                unit._warranty_system_write({'start_date': start, 'end_date': end})
            self.sudo()._message_log(body=Markup('<p>%s</p>') % _(
                "Date correction: %s keep the dates set by their replacement.",
                ', '.join(unit.name for unit in kept)))
            self._warranty_restore_from_expiry(_("date correction"))
            if self.state in ('confirmed', 'expired'):
                self._regenerate_soft_copy()
        return log


class WarrantyCardDateLog(models.Model):
    _inherit = 'warranty.card.date.log'

    event = fields.Selection(selection_add=[(DATE_LOG_REPLACEMENT, 'Replacement')],
                             ondelete={DATE_LOG_REPLACEMENT: 'cascade'})
