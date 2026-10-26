from odoo import _, api, fields, models
from odoo.exceptions import UserError

CHARGEABLE_PURPOSES = [
    ('inspection', 'Inspection'),
    ('repair', 'Repair'),
    ('excluded_items', 'Excluded Items'),
]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Phase 4.10 (approved C2): the chargeable step of the case this quotation is for; set when
    # it is created from a Chargeable case, read-only. Only these orders trigger a job.
    warranty_chargeable_purpose = fields.Selection(
        CHARGEABLE_PURPOSES, string='Chargeable Purpose', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any('warranty_chargeable_purpose' in vals for vals in vals_list) and not self.env.su:
            raise UserError(_("The chargeable purpose is set by the warranty case."))
        orders = super().create(vals_list)
        for order in orders.filtered(lambda o: o.warranty_case_id
                                     and not o.warranty_chargeable_purpose):
            # sudo: the case of the quotation is read; the purpose is set by this check only.
            case = order.warranty_case_id.sudo()
            if case.state == 'chargeable' and case.chargeable_type:
                order.sudo().warranty_chargeable_purpose = case.chargeable_type
                case._warranty_send_todo(order)
        return orders

    def write(self, vals):
        if 'warranty_chargeable_purpose' in vals and not self.env.su:
            raise UserError(_("The chargeable purpose is set by the warranty case."))
        result = super().write(vals)
        if vals.get('state') == 'sent':
            # Approved C10: the "send the quotation" To-Do is closed when it is really sent.
            for order in self.filtered('warranty_chargeable_purpose'):
                order.warranty_case_id.sudo()._warranty_close_send_todo(order)
        return result

    def action_confirm(self):
        result = super().action_confirm()
        # Approved C2 / C3: On Sales Order Confirmation trigger. sudo: the salesperson may have
        # no Helpdesk rights; only the cases of these orders are checked.
        self.sudo().warranty_case_id._warranty_check_chargeable_trigger(
            _("sales order confirmation"))
        return result
