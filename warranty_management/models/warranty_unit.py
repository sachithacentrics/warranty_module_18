from odoo import fields, models


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
    unit_number = fields.Integer(string='Quantity Unit', readonly=True)
    stock_move_line_id = fields.Many2one(
        'stock.move.line', string='Delivery / Move Line', readonly=True)
    serial_ids = fields.Many2many(
        'stock.lot', 'warranty_unit_stock_lot_rel', 'unit_id', 'lot_id',
        string='Serial(s)', readonly=True)
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
