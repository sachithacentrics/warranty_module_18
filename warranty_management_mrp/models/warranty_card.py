from odoo import _, api, fields, models

from .mrp_bom import ROLE_FIELDS


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    # Display only, see warranty.unit. sudo: read for the visibility of the fields.
    warranty_show_indoor_serial = fields.Boolean(compute='_compute_warranty_show_serials',
                                                 compute_sudo=True)
    warranty_show_outdoor_serial = fields.Boolean(compute='_compute_warranty_show_serials',
                                                  compute_sudo=True)

    @api.depends('product_id', 'indoor_serial_id', 'outdoor_serial_id',
                 'unit_warranty_ids.warranty_show_indoor_serial',
                 'unit_warranty_ids.warranty_show_outdoor_serial')
    def _compute_warranty_show_serials(self):
        for card in self:
            roles = {}
            if card.product_id:
                bom = self.env['mrp.bom']._bom_find(
                    card.product_id, company_id=card.company_id.id,
                    bom_type='phantom')[card.product_id]
                roles = bom._warranty_role_lines() if bom else {}
            units = card.unit_warranty_ids
            card.warranty_show_indoor_serial = 'indoor' in roles or bool(card.indoor_serial_id) \
                or any(units.mapped('warranty_show_indoor_serial'))
            card.warranty_show_outdoor_serial = 'outdoor' in roles or bool(card.outdoor_serial_id) \
                or any(units.mapped('warranty_show_outdoor_serial'))

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
