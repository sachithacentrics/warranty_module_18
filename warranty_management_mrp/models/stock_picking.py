from odoo import models

from .mrp_bom import ROLE_FIELDS


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _warranty_allocate_sale_line(self, sale_line, moves):
        """Kit lines (component moves of a Kit BoM): the delivered Indoor / Outdoor serials
        are allocated to the warranty units in delivery order (approved K3), one serial per
        unit and role; units already holding a serial for a role, and corrected units, are
        never changed, so backorders fill the remaining units. A kit without roles is
        allocated once, from its first component. Other lines: unchanged."""
        kit_moves = moves.filtered(lambda move: move.bom_line_id.bom_id.type == 'phantom')
        if not kit_moves:
            return super()._warranty_allocate_sale_line(sale_line, moves)
        bom = kit_moves.bom_line_id.bom_id[:1]
        roles = bom._warranty_role_lines()
        if not roles:
            first_line = bom.bom_line_ids[:1]
            return super()._warranty_allocate_sale_line(
                sale_line, kit_moves.filtered(lambda move: move.bom_line_id == first_line))

        all_units = sale_line.warranty_unit_ids
        units = all_units.filtered(
            lambda unit: unit.state == 'draft' and not unit.kit_serials_corrected
        ).sorted(lambda unit: (unit.unit_number, unit.id))
        cards = self.env['warranty.card']
        for role, bom_line in roles.items():
            field = ROLE_FIELDS[role]
            used = all_units.indoor_serial_id | all_units.outdoor_serial_id
            free_units = units.filtered(lambda unit: not unit[field])
            move_lines = kit_moves.filtered(
                lambda move: move.bom_line_id == bom_line
            ).move_line_ids.filtered(lambda ml: ml.lot_id and ml.quantity).sorted('id')
            for move_line in move_lines:
                if not free_units:
                    break
                if move_line.lot_id in used:
                    continue
                unit, free_units = free_units[0], free_units[1:]
                vals = {field: move_line.lot_id.id}
                if not unit.stock_move_line_id:
                    vals['stock_move_line_id'] = move_line.id
                unit.with_context(warranty_kit_allocation=True).write(vals)
                used |= move_line.lot_id
                cards |= unit.warranty_card_id
        return cards
