from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


# Approved D9: written by system code only (warranty_card._DATE_WRITE_MARKER).
UNIT_SYSTEM_DATE_FIELDS = {'start_date', 'end_date', 'source_invoice_id',
                           'source_invoice_posted_at'}

# Part 9, SRS 13: after confirmation these change only through a controlled action or system code.
UNIT_PROTECTED_FIELDS = {
    'warranty_card_id', 'sale_order_line_id', 'product_id', 'unit_number', 'stock_move_line_id',
    'serial_ids', 'usage_limit', 'usage_unit', 'current_site_id', 'original_end_date',
    'usage_correction_reading', 'usage_correction_date'}
# SRS 12 #25: "active" cards. Replaced, Cancelled and Expired units do not hold a serial.
SERIAL_HOLDING_STATES = ('draft', 'active', 'suspended')

UNIT_STATES = [
    ('draft', 'Draft'),
    ('active', 'Active'),
    ('replaced', 'Replaced'),
    ('suspended', 'Suspended'),
    ('expired', 'Expired'),
    ('cancelled', 'Cancelled'),
]


class WarrantyUnit(models.Model):
    _name = 'warranty.unit'
    _description = 'Unit Warranty Number'
    _order = 'warranty_card_id desc, name'

    name = fields.Char(string='Warranty Number', required=True, readonly=True, copy=False)
    warranty_card_id = fields.Many2one(
        'warranty.card', string='Card Number', required=True, ondelete='cascade', index=True)
    sale_order_line_id = fields.Many2one(
        'sale.order.line', string='Sales Order Line', readonly=True, index=True)
    sale_order_id = fields.Many2one(
        related='sale_order_line_id.order_id', string='Sale Order', store=True, index=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    unit_number = fields.Integer(string='Unit No.', readonly=True)
    stock_move_line_id = fields.Many2one(
        'stock.move.line', string='Delivery / Move Line', readonly=True)
    serial_ids = fields.Many2many(
        'stock.lot', 'warranty_unit_stock_lot_rel', 'unit_id', 'lot_id',
        string='Serial(s)', readonly=True)
    # Start Date Automation (D2): actual validated delivery of the unit (allocation).
    delivery_picking_id = fields.Many2one(
        related='stock_move_line_id.picking_id', string='Delivery')
    delivery_datetime = fields.Datetime(
        related='stock_move_line_id.picking_id.date_done', string='Delivered On')
    # D3: invoice covering the unit, frozen at confirmation (Invoice basis).
    source_invoice_id = fields.Many2one(
        'account.move', string='Source Invoice', readonly=True, copy=False)
    source_invoice_posted_at = fields.Datetime(
        string='Invoice Posted On', readonly=True, copy=False)
    start_date = fields.Date(string='Start Date', readonly=True)
    end_date = fields.Date(string='End Date', readonly=True)
    usage_limit = fields.Float(string='Usage Limit', readonly=True)
    usage_unit = fields.Selection([
        ('operating_hours', 'Operating Hours'),
        ('cycles', 'Cycles'),
        ('km', 'KM'),
        ('units_produced', 'Units Produced'),
        ('other', 'Other'),
    ], string='Usage Unit', readonly=True)
    state = fields.Selection(
        UNIT_STATES, string='Status', default='draft', required=True, copy=False,
        readonly=True, index=True)
    company_id = fields.Many2one(
        related='warranty_card_id.company_id', string='Company', store=True, index=True)
    # Part 9: written by controlled actions only.
    current_site_id = fields.Many2one(
        'res.partner', string='Current Site', readonly=True, copy=False,
        help="Set by a relocation or ownership change. Empty: the delivery address of the sale.")
    original_end_date = fields.Date(
        string='Original End Date', readonly=True, copy=False,
        help="The end date before the first warranty extension.")
    usage_correction_reading = fields.Float(string='Corrected Usage Reading', readonly=True,
                                            copy=False)
    usage_correction_date = fields.Datetime(string='Usage Corrected On', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env['warranty.card']._warranty_date_write_allowed() and any(
                vals.get(name) for vals in vals_list for name in UNIT_SYSTEM_DATE_FIELDS):
            raise UserError(self.env['warranty.card']._warranty_date_write_error())
        return super().create(vals_list)

    def write(self, vals):
        Card = self.env['warranty.card']
        allowed = Card._warranty_date_write_allowed()
        if UNIT_SYSTEM_DATE_FIELDS & set(vals) and not allowed:
            raise UserError(Card._warranty_date_write_error())
        if not allowed and not self.env.su:
            for unit in self:
                if ('state' in vals and vals['state'] != unit.state) or (
                        unit.state != 'draft' and UNIT_PROTECTED_FIELDS & set(vals)):
                    raise UserError(Card._warranty_protected_write_error())
        return super().write(vals)

    @api.constrains('serial_ids', 'state')
    def _check_serial_holder(self):
        """SRS 12 #25, 13: no second active warranty for one serial. Exceptions come through a
        replacement or correction, which run their own checks (system writes)."""
        if not self.env['warranty.card']._warranty_date_write_allowed():
            self._warranty_units_to_check_on_write()._warranty_check_serial_duplicates()

    def _warranty_units_to_check_on_write(self):
        return self

    def _warranty_check_serial_duplicates(self):
        for unit in self.filtered(lambda unit: unit.state in SERIAL_HOLDING_STATES):
            for lot in unit.serial_ids:
                other = unit._warranty_serial_holder(lot)
                if other:
                    raise ValidationError(_(
                        "Serial %(serial)s is already on warranty unit %(unit)s (card %(card)s). Use "
                        "a correction, replacement or return cancellation.", serial=lot.name,
                        unit=other[0].name, card=other[0].warranty_card_id.name))

    def _warranty_serial_holder(self, lot):
        """Another live unit holding `lot`. Lot-tracked products share a lot on purpose.
        sudo: other customers' units are read for this check only."""
        self.ensure_one()
        if lot.product_id.tracking != 'serial':
            return self.browse()
        return self.sudo().search([('id', '!=', self.id), ('serial_ids', 'in', lot.ids),
                                   ('state', 'in', SERIAL_HOLDING_STATES)], limit=1)

    def _warranty_service_address(self):
        """Where this unit is now (SRS 12 #4). sudo: the delivery address of the sale is read only."""
        self.ensure_one()
        return self.current_site_id or self.warranty_card_id.sudo().sale_order_id.partner_shipping_id

    def _warranty_addresses(self):
        addresses = self.env['res.partner']
        for unit in self:
            addresses |= unit._warranty_service_address()
        return addresses

    def action_view_warranty_history(self):
        self.ensure_one()
        return self.env['warranty.history']._warranty_open([
            ('card_id', '=', self.warranty_card_id.id),
            '|', ('unit_id', '=', self.id), ('unit_id', '=', False)])

    def _warranty_coverage_end(self):
        """The last day this unit is covered (SRS 9.13, 14)."""
        self.ensure_one()
        return self.end_date

    def _warranty_system_write(self, vals):
        return self.with_context(
            warranty_date_marker=self.env['warranty.card']._warranty_marker()).write(vals)
