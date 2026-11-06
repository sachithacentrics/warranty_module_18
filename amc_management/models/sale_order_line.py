from odoo import _, api, models
from odoo.exceptions import UserError

from .sale_order import LOCKED_LINE_FIELDS, _amc_marked


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        if not _amc_marked(self.env):
            orders = self.env['sale.order'].browse(
                [vals['order_id'] for vals in vals_list if vals.get('order_id')])
            if orders.filtered('amc_contract_id'):
                raise UserError(_("Lines of AMC quotations come from the AMC contract (no added "
                                  "lines or down payments)."))
        return super().create(vals_list)

    def write(self, vals):
        if not _amc_marked(self.env) and LOCKED_LINE_FIELDS & set(vals) \
                and self.filtered('order_id.amc_contract_id'):
            raise UserError(_("Quantity, price, discount and delivered quantity of AMC lines are "
                              "set by the AMC contract (approved billing safeguards)."))
        return super().write(vals)

    def unlink(self):
        if not _amc_marked(self.env) and self.filtered('order_id.amc_contract_id') \
                and any(line.order_id.state != 'cancel' for line in self):
            raise UserError(_("Lines of AMC quotations cannot be deleted."))
        return super().unlink()
