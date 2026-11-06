from odoo import _, models
from odoo.fields import Command
from odoo.tools import float_round


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        res = super()._action_done()
        done = self.filtered(lambda picking: picking.state == 'done')
        done.filtered(
            lambda picking: picking.picking_type_code == 'outgoing')._warranty_allocate_delivery()
        done.filtered(
            lambda picking: picking.picking_type_code == 'incoming')._warranty_log_returns()
        return res

    def _warranty_log_returns(self):
        """Q13: a validated return of delivered warranty units is logged on their cards; the
        allocation and the warranty dates are not changed automatically."""
        for picking in self:
            returned = picking.move_ids.filtered(
                lambda move: move.state == 'done').origin_returned_move_id
            if not returned:
                continue
            units = self.env['warranty.unit'].search(
                [('stock_move_line_id', 'in', returned.move_line_ids.ids)])
            for card, card_units in units.grouped('warranty_card_id').items():
                card._warranty_log_date_event('delivery_return', _(
                    "Return %(picking)s validated for unit(s) %(units)s (delivered with "
                    "%(delivery)s): warranty dates unchanged.", picking=picking.name,
                    units=', '.join(card_units.mapped('name')),
                    delivery=', '.join(card_units.delivery_picking_id.mapped('name'))),
                    picking_id=picking.id)

    def _warranty_allocate_delivery(self):
        """On delivery validation: update the delivery on the warranty cards and allocate
        the delivered move lines / serials (stock.move.line, stock.lot) to the unit
        warranty numbers of the delivered sale order lines."""
        for picking in self:
            moves = picking.move_ids.filtered(lambda move: move.state == 'done' and move.sale_line_id)
            if not moves:
                continue
            cards = self.env['warranty.card']
            for sale_line, line_moves in moves.grouped('sale_line_id').items():
                cards |= picking._warranty_allocate_sale_line(sale_line, line_moves)
            cards.write({'delivery_ids': [Command.link(picking.id)]})

            for card in cards.filtered(lambda c: c.card_grouping_mode == 'per_delivery'):
                waiting = card.unit_warranty_ids.filtered(
                    lambda unit: unit.state == 'draft' and not unit.stock_move_line_id)
                if waiting:
                    card._split_units_to_new_card(waiting, picking.backorder_ids)
            # D6: Installation cards completed by their tasks may now be Ready.
            cards._warranty_auto_confirm()

    def _warranty_allocate_sale_line(self, sale_line, moves):
        """Allocate the done `moves` of one Sales Order line to its Draft unit warranty
        numbers without a move line, in unit order; returns the warranty cards concerned.
        Extended by warranty_management_mrp for Kit products."""
        self.ensure_one()
        line_units = self.env['warranty.unit'].search([
            ('sale_order_line_id', '=', sale_line.id),
            ('state', '=', 'draft'),
            ('stock_move_line_id', '=', False),
        ], order='unit_number, id')
        cards = self.env['warranty.card']
        for move in moves:
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
        return cards
