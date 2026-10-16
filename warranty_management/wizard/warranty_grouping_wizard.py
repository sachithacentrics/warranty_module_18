from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


def _card_selection(field_name):
    return lambda self: self.env['warranty.card']._fields[field_name].selection


class WarrantyGroupingWizard(models.TransientModel):
    _name = 'warranty.grouping.wizard'
    _description = 'Warranty Grouping'

    sale_order_id = fields.Many2one(
        'sale.order', string='Sales Order', required=True, readonly=True, ondelete='cascade')
    company_id = fields.Many2one(related='sale_order_id.company_id')
    # No default: the user selects the mode explicitly for the whole Sales Order.
    card_grouping_mode = fields.Selection(
        _card_selection('card_grouping_mode'), string='Card Grouping Mode', required=True)
    line_ids = fields.One2many(
        'warranty.grouping.wizard.line', 'wizard_id', string='Warranty Products', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env['sale.order'].browse(res.get('sale_order_id'))
        if order and 'line_ids' in fields_list:
            lines = []
            for line in order._warranty_pending_lines():
                values = line._warranty_resolve_rule()
                lines.append(Command.create({
                    'sale_order_line_id': line.id,
                    'product_id': line.product_id.id,
                    'quantity': line.product_uom_qty,
                    'policy_id': values['policy'].id,
                    'policy_source': values['policy_source'],
                    'warranty_duration': values['warranty_duration'],
                    'warranty_duration_unit': values['warranty_duration_unit'],
                }))
            res['line_ids'] = lines
        return res

    def action_confirm(self):
        """Create the Draft Warranty Cards of the pending lines with the selected mode; lines
        that already have Unit Warranty Numbers are never processed again."""
        self.ensure_one()
        order = self.sale_order_id
        if order.state != 'sale':
            raise UserError(_("Warranty grouping is only possible on a confirmed Sales Order."))
        if not order._warranty_pending_lines():
            raise UserError(_("Warranty cards were already created for %s.", order.name))
        order._warranty_create_draft_cards(self.card_grouping_mode)
        return {'type': 'ir.actions.act_window_close'}


class WarrantyGroupingWizardLine(models.TransientModel):
    _name = 'warranty.grouping.wizard.line'
    _description = 'Warranty Grouping Product'

    wizard_id = fields.Many2one(
        'warranty.grouping.wizard', required=True, ondelete='cascade')
    sale_order_line_id = fields.Many2one('sale.order.line', string='Order Line', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    quantity = fields.Float(string='Quantity', digits='Product Unit of Measure', readonly=True)
    policy_id = fields.Many2one('warranty.policy', string='Warranty Policy', readonly=True)
    policy_source = fields.Selection(
        _card_selection('policy_source'), string='Policy Source', readonly=True)
    warranty_duration = fields.Integer(string='Warranty Duration', readonly=True)
    warranty_duration_unit = fields.Selection(
        _card_selection('warranty_duration_unit'), string='Duration Unit', readonly=True)
