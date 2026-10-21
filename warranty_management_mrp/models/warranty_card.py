from odoo import _, api, models

from .mrp_bom import ROLE_FIELDS


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    @api.depends('unit_warranty_ids.indoor_serial_id', 'unit_warranty_ids.outdoor_serial_id')
    def _compute_state(self):
        return super()._compute_state()

    @api.depends('unit_warranty_ids.indoor_serial_id', 'unit_warranty_ids.outdoor_serial_id')
    def _compute_missing_requirements(self):
        return super()._compute_missing_requirements()

    def write(self, vals):
        if 'unit_warranty_ids' not in vals:
            return super().write(vals)
        result = super(WarrantyCard, self.with_context(warranty_defer_kit_check=True)).write(vals)
        self.unit_warranty_ids._check_kit_serials()
        return result

    def _get_missing_requirements(self):
        """Approved requirement 8: a kit unit needs the serial of each Indoor / Outdoor Unit
        component of its Kit BoM."""
        missing = super()._get_missing_requirements()
        for unit in self.unit_warranty_ids:
            bom = unit._warranty_kit_bom()
            if not bom:
                continue
            for role, line in bom._warranty_role_lines().items():
                if not unit[ROLE_FIELDS[role]]:
                    missing.append(_("%(role)s serial number for unit %(unit)s",
                                     role=line._warranty_role_label(), unit=unit.name))
        return missing
