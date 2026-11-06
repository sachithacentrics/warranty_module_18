from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.warranty_management_mrp.models.mrp_bom import ROLE_FIELDS

from .warranty_replacement import _REPLACEMENT_MARKER, ROLE_DATE_FIELDS

ROLE_DATE_NAMES = {name for names in ROLE_DATE_FIELDS.values() for name in names}


class WarrantyUnit(models.Model):
    _inherit = 'warranty.unit'

    # SRS 11.1, 11.3: an Indoor / Outdoor replacement changes the dates of that serial only. Empty:
    # the dates of the unit apply. Written by the replacement only.
    indoor_start_date = fields.Date(
        string='Indoor Start Date', readonly=True, copy=False,
        help="Set by an Indoor Unit replacement. Empty: the Start Date of the unit applies.")
    indoor_end_date = fields.Date(
        string='Indoor End Date', readonly=True, copy=False,
        help="Set by an Indoor Unit replacement. Empty: the End Date of the unit applies.")
    outdoor_start_date = fields.Date(
        string='Outdoor Start Date', readonly=True, copy=False,
        help="Set by an Outdoor Unit replacement. Empty: the Start Date of the unit applies.")
    outdoor_end_date = fields.Date(
        string='Outdoor End Date', readonly=True, copy=False,
        help="Set by an Outdoor Unit replacement. Empty: the End Date of the unit applies.")

    def _warranty_role_dates(self, role):
        """(start, end) in force for the serial of `role`."""
        self.ensure_one()
        start_field, end_field = ROLE_DATE_FIELDS[role]
        return self[start_field] or self.start_date, self[end_field] or self.end_date

    def _warranty_coverage_end(self):
        """A kit unit is covered until its last serial ends, each with its own dates if it has them."""
        self.ensure_one()
        ends = [self._warranty_role_dates(role)[1] for role, field in ROLE_FIELDS.items()
                if self[field]]
        if ends and all(ends):
            return max(ends)
        return super()._warranty_coverage_end()

    def _warranty_serial_role(self, serial):
        """'indoor' / 'outdoor' when `serial` is that serial of this unit, else False."""
        for role, field in ROLE_FIELDS.items():
            if serial and self[field] == serial:
                return role
        return False

    def _warranty_delivered_role_lots(self, role):
        """A serial delivered by a validated replacement of this unit and role is a delivered serial
        of the role too (approved K4 rule of warranty_management_mrp). sudo: read for the check."""
        lots = super()._warranty_delivered_role_lots(role)
        if not self._origin.id:  # a new record in a form: it has no replacement
            return lots
        replacements = self.env['warranty.replacement'].sudo().search(
            [('warranty_unit_id', '=', self._origin.id), ('replacement_type', '=', role),
             ('state', 'in', ('approved', 'done')), ('delivery_picking_id.state', '=', 'done')])
        return lots | self.env['stock.lot'].browse(replacements.new_serial_id.ids)

    def write(self, vals):
        """SRS 19: no direct serial overwrite without history, on the units that have a
        replacement. Every other unit keeps the existing serial rules."""
        marked = self.env.context.get('warranty_replacement_marker') is _REPLACEMENT_MARKER
        if ROLE_DATE_NAMES & set(vals) and not marked:
            raise UserError(_("The dates of an Indoor or Outdoor serial change only through a "
                              "replacement."))
        if {'serial_ids', 'indoor_serial_id', 'outdoor_serial_id'} & set(vals) \
                and not marked \
                and self.env['warranty.replacement'].sudo().search_count(
                    [('warranty_unit_id', 'in', self.ids), ('replacement_type', '!=', 'component'),
                     ('state', 'in', ('submitted', 'approved', 'done'))], limit=1):
            raise UserError(_("The serial of a unit with a replacement changes only through the "
                              "replacement."))
        return super().write(vals)
