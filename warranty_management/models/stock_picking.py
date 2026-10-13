from odoo import models
from odoo.fields import Command
from odoo.tools import float_round


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        res = super()._action_done()
        self.filtered(
            lambda picking: picking.picking_type_code == 'outgoing' and picking.state == 'done'
        )._warranty_allocate_delivery()
        return res

    def _warranty_allocate_delivery(self):
        """On delivery validation: update the delivery on the warranty cards and allocate
        the delivered move lines / serials (stock.move.line, stock.lot) to the unit
        warranty numbers of the delivered sale order lines."""
        Unit = self.env['warranty.unit']
        for picking in self:
            moves = picking.move_ids.filtered(lambda move: move.state == 'done' and move.sale_line_id)
            if not moves:
                continue
            units = Unit.search([
                ('sale_order_line_id', 'in', moves.sale_line_id.ids),
                ('state', '=', 'draft'),
                ('stock_move_line_id', '=', False),
            ], order='unit_number, id')
            if not units:
                continue
            cards = self.env['warranty.card']
            for move in moves:
                line_units = units.filtered(lambda unit: unit.sale_order_line_id == move.sale_line_id)
                for move_line in move.move_line_ids.filtered('quantity'):
                    qty = move_line.product_uom_id._compute_quantity(
                        move_line.quantity, move_line.product_id.uom_id)
                    count = int(float_round(qty, precision_digits=0))
                    allocated, line_units = line_units[:count], line_units[count:]
                    if not allocated:
                        break
                    vals = {'stock_move_line_id': move_line.id}
                    if move_line.lot_id:
                        vals['serial_ids'] = [Command.set(move_line.lot_id.ids)]
                    allocated.write(vals)
                    cards |= allocated.warranty_card_id
            cards.write({'delivery_ids': [Command.link(picking.id)]})

            for card in cards.filtered(lambda c: c.card_grouping_mode == 'per_delivery'):
                waiting = card.unit_warranty_ids.filtered(
                    lambda unit: unit.state == 'draft' and not unit.stock_move_line_id)
                if waiting:
                    card._split_units_to_new_card(waiting, picking.backorder_ids)
