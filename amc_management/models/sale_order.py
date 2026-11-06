from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .amc_contract import RUNNING_STATES, _CANCELLING_MARKER, _CONTRACT_MARKER

# AMC quotation values set only by the AMC contract (approved B4a safeguards / C2).
LOCKED_ORDER_FIELDS = {'partner_id', 'pricelist_id', 'currency_id', 'company_id',
                       'amc_contract_id'}
LOCKED_LINE_FIELDS = {'product_id', 'product_uom_qty', 'product_uom', 'price_unit',
                      'technical_price_unit', 'discount', 'order_id', 'qty_delivered'}


def _amc_marked(env):
    return env.context.get('amc_contract_marker') is _CONTRACT_MARKER


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    amc_contract_id = fields.Many2one('amc.contract', string='AMC Contract', readonly=True,
                                      copy=False, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('amc_contract_id') for vals in vals_list) and not _amc_marked(self.env):
            raise UserError(_("AMC quotations are created from the AMC contract (Create "
                              "Quotation)."))
        return super().create(vals_list)

    def write(self, vals):
        amc = self.filtered('amc_contract_id')
        if amc and LOCKED_ORDER_FIELDS & set(vals) and not _amc_marked(self.env):
            raise UserError(_("The customer, pricelist and currency of AMC quotation %s are set "
                              "by its AMC contract (pricelist change: override request on the "
                              "contract).", ', '.join(amc.mapped('name'))))
        return super().write(vals)

    def copy(self, default=None):
        if self.filtered('amc_contract_id'):
            raise UserError(_("AMC quotations cannot be duplicated: create the quotation from "
                              "the AMC contract."))
        return super().copy(default=default)

    def action_update_prices(self):
        if self.filtered('amc_contract_id'):
            raise UserError(_("AMC quotation prices come from the AMC contract."))
        return super().action_update_prices()

    def action_confirm(self):
        """Approved C3: an expired AMC quotation is reissued (price of today), not confirmed."""
        today = fields.Date.context_today(self)
        for order in self.filtered('amc_contract_id'):
            if order.validity_date and order.validity_date < today:
                raise UserError(_("AMC quotation %s has expired: use Reissue Quotation on the AMC "
                                  "contract (the price is calculated again).", order.name))
            if order.amc_contract_id.sale_order_id != order \
                    or order.amc_contract_id.state != 'quotation':
                raise UserError(_("Quotation %s is not the open quotation of its AMC contract.",
                                  order.name))
        result = super().action_confirm()
        for order in self.filtered('amc_contract_id'):
            # sudo: the confirmation by an authorized sales user drives the contract (billing
            # schedule, activation, entitlements) whatever the user's AMC role.
            order.amc_contract_id.sudo()._amc_on_order_confirmed(order.sudo())
        return result

    def _action_cancel(self):
        result = super()._action_cancel()
        if self.env.context.get('amc_contract_cancelling') is _CANCELLING_MARKER:
            return result
        for order in self.filtered('amc_contract_id'):
            contract = order.amc_contract_id
            if contract.state in RUNNING_STATES + ('closed', 'renewed'):
                raise UserError(_("The Sales Order of activated AMC contract %s cannot be "
                                  "cancelled: close the contract instead (Close Contract).",
                                  contract.name))
            contract.sudo()._amc_on_order_cancelled(order.sudo())
        return result


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
