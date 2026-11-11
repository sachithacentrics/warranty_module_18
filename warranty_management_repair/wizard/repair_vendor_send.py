from odoo import api, fields, models

from ..models.repair_vendor import VENDOR_TRANSFER_TYPES


class WarrantyRepairVendorSend(models.TransientModel):
    """Send for Repair (Figure 6 vendor repair): the transfer type decides the destinations; the
    source is where the serial verifiably is. The Repair Order checks everything again."""
    _name = 'warranty.repair.vendor.send'
    _description = 'Send Machine for Repair'

    repair_id = fields.Many2one('repair.order', required=True, readonly=True, ondelete='cascade')
    company_id = fields.Many2one(related='repair_id.company_id')
    product_id = fields.Many2one(related='repair_id.product_id')
    lot_id = fields.Many2one(related='repair_id.lot_id')
    location_id = fields.Many2one('stock.location', string='From', compute='_compute_location_id')
    transfer_type = fields.Selection(VENDOR_TRANSFER_TYPES, string='Transfer Type', required=True)
    partner_id = fields.Many2one('res.partner', string='Vendor')
    available_location_ids = fields.Many2many('stock.location',
                                              compute='_compute_available_location_ids')
    location_dest_id = fields.Many2one(
        'stock.location', string='To', required=True,
        domain="[('id', 'in', available_location_ids)]")

    @api.depends('repair_id')
    def _compute_location_id(self):
        for wizard in self:
            wizard.location_id = wizard.repair_id._warranty_vendor_machine_location() \
                if wizard.repair_id else False

    @api.depends('repair_id', 'transfer_type', 'partner_id', 'location_id')
    def _compute_available_location_ids(self):
        for wizard in self:
            wizard.available_location_ids = wizard.repair_id._warranty_vendor_destinations(
                wizard.transfer_type, wizard.partner_id, wizard.location_id) \
                if wizard.repair_id and wizard.location_id else False

    @api.onchange('transfer_type', 'partner_id')
    def _onchange_transfer_type(self):
        if self.transfer_type != 'external':
            self.partner_id = False
        if self.location_dest_id not in self.available_location_ids:
            self.location_dest_id = False
        if not self.location_dest_id and len(self.available_location_ids) == 1:
            self.location_dest_id = self.available_location_ids

    def action_confirm(self):
        self.ensure_one()
        return self.repair_id._warranty_vendor_send(self.transfer_type, self.partner_id,
                                                    self.location_dest_id)
