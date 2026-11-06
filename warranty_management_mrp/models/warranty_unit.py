from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command

from .mrp_bom import ROLE_FIELDS


class WarrantyUnit(models.Model):
    _inherit = 'warranty.unit'

    indoor_serial_id = fields.Many2one(
        'stock.lot', string='Indoor Serial No.', copy=False, index=True,
        domain="[('id', 'in', allowed_indoor_serial_ids)]",
        help="Delivered serial number of the kit's Indoor Unit component.")
    outdoor_serial_id = fields.Many2one(
        'stock.lot', string='Outdoor Serial No.', copy=False, index=True,
        domain="[('id', 'in', allowed_outdoor_serial_ids)]",
        help="Delivered serial number of the kit's Outdoor Unit component.")
    allowed_indoor_serial_ids = fields.Many2many(
        'stock.lot', compute='_compute_allowed_kit_serials')
    allowed_outdoor_serial_ids = fields.Many2many(
        'stock.lot', compute='_compute_allowed_kit_serials')
    kit_serials_corrected = fields.Boolean(
        string='Serial Pairing Corrected', readonly=True, copy=False,
        help="The Indoor / Outdoor serial numbers were changed by a user; later deliveries "
             "never change them.")

    # Display only: views cannot call the Kit BoM methods. sudo: Helpdesk users may have no Sales,
    # Inventory or Manufacturing rights.
    warranty_show_indoor_serial = fields.Boolean(compute='_compute_warranty_show_serials',
                                                 compute_sudo=True)
    warranty_show_outdoor_serial = fields.Boolean(compute='_compute_warranty_show_serials',
                                                  compute_sudo=True)

    @api.depends('product_id', 'sale_order_line_id', 'indoor_serial_id', 'outdoor_serial_id')
    def _compute_warranty_show_serials(self):
        """A role of the unit's Kit BoM, or a serial already recorded (it stays visible)."""
        for unit in self:
            bom = unit._warranty_kit_bom()
            roles = bom._warranty_role_lines() if bom else {}
            unit.warranty_show_indoor_serial = 'indoor' in roles or bool(unit.indoor_serial_id)
            unit.warranty_show_outdoor_serial = 'outdoor' in roles or bool(unit.outdoor_serial_id)

    def _warranty_kit_bom(self):
        """Kit BoM of the unit's product: the BoM its Sales Order line was delivered with,
        else the product's current Kit BoM."""
        self.ensure_one()
        bom = self.sale_order_line_id.move_ids.bom_line_id.bom_id.filtered(
            lambda b: b.type == 'phantom')[:1]
        if not bom and self.product_id:
            bom = self.env['mrp.bom']._bom_find(
                self.product_id, company_id=self.company_id.id, bom_type='phantom')[
                self.product_id]
        return bom

    def _warranty_delivered_role_lots(self, role):
        """Serials actually delivered (done outgoing moves) for the unit's Sales Order line
        and the component of `role`."""
        self.ensure_one()
        moves = self.sudo().sale_order_line_id.move_ids.filtered(
            lambda move: move.state == 'done' and move.picking_code == 'outgoing'
            and move.bom_line_id.warranty_component_role == role)
        return self.env['stock.lot'].browse(moves.move_line_ids.lot_id.ids)

    @api.depends('sale_order_line_id', 'indoor_serial_id', 'outdoor_serial_id')
    def _compute_allowed_kit_serials(self):
        for unit in self:
            others = unit.sale_order_line_id.warranty_unit_ids - unit
            used = others.indoor_serial_id | others.outdoor_serial_id
            unit.allowed_indoor_serial_ids = unit._warranty_delivered_role_lots('indoor') - used
            unit.allowed_outdoor_serial_ids = unit._warranty_delivered_role_lots('outdoor') - used

    @api.constrains('indoor_serial_id', 'outdoor_serial_id')
    def _check_kit_serials(self):
        """Approved K4: only serials delivered for the same Sales Order line and role; a
        serial is allocated to one warranty unit only."""
        if self.env.context.get('warranty_defer_kit_check'):
            return
        for unit in self:
            for role, field in ROLE_FIELDS.items():
                lot = unit[field]
                if lot and lot not in unit._warranty_delivered_role_lots(role):
                    raise ValidationError(_(
                        "Serial %(serial)s was not delivered as the %(role)s of %(unit)s.",
                        serial=lot.name, unit=unit.name,
                        role=_("Indoor Unit") if role == 'indoor' else _("Outdoor Unit")))
            lots = unit.indoor_serial_id | unit.outdoor_serial_id
            if not lots:
                continue
            if unit.indoor_serial_id and unit.indoor_serial_id == unit.outdoor_serial_id:
                raise ValidationError(_("Serial %(serial)s is used twice on %(unit)s.",
                                        serial=unit.indoor_serial_id.name, unit=unit.name))
            duplicate = self.search([
                ('id', '!=', unit.id),
                '|', ('indoor_serial_id', 'in', lots.ids), ('outdoor_serial_id', 'in', lots.ids),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "Serial %(serial)s is already allocated to warranty unit %(other)s.",
                    serial=', '.join((lots & (duplicate.indoor_serial_id
                                              | duplicate.outdoor_serial_id)).mapped('name')),
                    other=duplicate.name))

    def write(self, vals):
        role_fields = set(ROLE_FIELDS.values()) & vals.keys()
        if role_fields and not self.env.context.get('warranty_kit_allocation'):
            # Manual correction (approved K4): Draft / Ready to Confirm cards only; later
            # deliveries never change a corrected pairing.
            locked = self.filtered(
                lambda unit: unit.warranty_card_id.state not in ('draft', 'ready'))
            if locked:
                raise UserError(_(
                    "Indoor / Outdoor serial numbers can only be corrected while the warranty "
                    "card is Draft or Ready to Confirm (%s).",
                    ', '.join(locked.mapped('name'))))
            vals = dict(vals, kit_serials_corrected=True)
        previous = {unit.id: (unit.indoor_serial_id, unit.outdoor_serial_id) for unit in self}
        result = super().write(vals)
        if role_fields:
            self._sync_kit_serials(previous)
        return result

    def _warranty_units_to_check_on_write(self):
        """Kit serials have their own check (K4), which allows a swap in one save; confirmation
        still runs the common check."""
        return self.filtered(lambda unit: not unit.indoor_serial_id and not unit.outdoor_serial_id)

    def _sync_kit_serials(self, previous):
        """Serial(s) of the unit = its Indoor / Outdoor serials; a single-unit card shows them
        in its Indoor / Outdoor Serial No. unless the user entered other values there."""
        for unit in self:
            unit.with_context(warranty_kit_allocation=True).serial_ids = [
                Command.set((unit.indoor_serial_id | unit.outdoor_serial_id).ids)]
            card = unit.warranty_card_id
            if len(card.unit_warranty_ids) != 1:
                continue
            old_indoor, old_outdoor = previous[unit.id]
            card_vals = {}
            if card.indoor_serial_id in (old_indoor, self.env['stock.lot']):
                card_vals['indoor_serial_id'] = unit.indoor_serial_id.id
            if card.outdoor_serial_id in (old_outdoor, self.env['stock.lot']):
                card_vals['outdoor_serial_id'] = unit.outdoor_serial_id.id
            if card_vals:
                card.write(card_vals)
