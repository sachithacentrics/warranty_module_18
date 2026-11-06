from odoo import _, api, fields, models

from ..models.warranty_card_action import ACTION_TYPES, EXTENSION_TYPES, SUSPEND_REASONS


class WarrantyCardActionWizard(models.TransientModel):
    """Request a controlled action (SRS 12 step 2). The approver applies it."""
    _name = 'warranty.card.action.wizard'
    _description = 'Warranty Controlled Action Request'

    card_id = fields.Many2one('warranty.card', string='Warranty Card', required=True, readonly=True)
    action_type = fields.Selection(ACTION_TYPES, string='Action', required=True)
    available_unit_ids = fields.Many2many('warranty.unit', compute='_compute_available')
    unit_ids = fields.Many2many('warranty.unit', 'warranty_card_action_wizard_unit_rel', 'wizard_id',
                                'unit_id', string='Units',
                                domain="[('id', 'in', available_unit_ids)]",
                                help="Empty: every unit this action applies to.")
    open_work = fields.Text(string='Open Work on the Card', compute='_compute_available',
                            help="These stay as they are: the action never changes them.")
    reason_code = fields.Selection(SUSPEND_REASONS, string='Suspension Reason')
    reason = fields.Text(string='Reason', required=True)
    effective_date = fields.Date(string='Effective Date', default=fields.Date.context_today)
    attachment_ids = fields.Many2many('ir.attachment', 'warranty_card_action_wizard_attachment_rel',
                                      'wizard_id', 'attachment_id', string='Evidence / Document')
    new_partner_id = fields.Many2one('res.partner', string='New Customer')
    new_site_id = fields.Many2one('res.partner', string='New Site')
    old_serial_id = fields.Many2one('stock.lot', string='Wrong Serial')
    new_serial_id = fields.Many2one('stock.lot', string='Correct Serial')
    new_usage = fields.Float(string='Corrected Usage Reading')
    new_end_date = fields.Date(string='New End Date')
    extension_type = fields.Selection(EXTENSION_TYPES, string='Extension Type')
    source_picking_id = fields.Many2one('stock.picking', string='Validated Return')
    source_move_id = fields.Many2one('account.move', string='Invoice / Credit Note')
    source_order_id = fields.Many2one('sale.order', string='Quotation / Sales Order')

    @api.depends('card_id')
    def _compute_available(self):
        for wizard in self:
            wizard.available_unit_ids = wizard.card_id.unit_warranty_ids
            wizard.open_work = ', '.join(wizard.card_id._warranty_open_work()) or False

    def _warranty_default_units(self):
        """Empty selection: the units the action can apply to."""
        live = self.card_id._warranty_live_units()
        if self.action_type == 'suspend':
            return live.filtered(lambda unit: unit.state == 'active')
        if self.action_type == 'reactivate':
            return live.filtered(lambda unit: unit.state == 'suspended')
        return live

    def action_submit(self):
        self.ensure_one()
        units = self.unit_ids or self._warranty_default_units()
        action = self.card_id._warranty_request_action(
            self.action_type, units=units, reason=self.reason, reason_code=self.reason_code,
            effective_date=self.effective_date, attachment_ids=self.attachment_ids,
            new_partner_id=self.new_partner_id.id, new_site_id=self.new_site_id.id,
            old_serial_id=self.old_serial_id.id, new_serial_id=self.new_serial_id.id,
            new_usage=self.new_usage, new_end_date=self.new_end_date,
            extension_type=self.extension_type, source_picking_id=self.source_picking_id.id,
            source_move_id=self.source_move_id.id, source_order_id=self.source_order_id.id)
        return {
            'type': 'ir.actions.act_window', 'name': _("Warranty Change Request"),
            'res_model': action._name, 'res_id': action.id, 'view_mode': 'form',
        }


class WarrantyCardActionRejectWizard(models.TransientModel):
    _name = 'warranty.card.action.reject.wizard'
    _description = 'Reject Warranty Controlled Action'

    action_id = fields.Many2one('warranty.card.action', string='Action', required=True,
                                readonly=True)
    reason = fields.Text(string='Rejection Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        self.action_id._warranty_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
