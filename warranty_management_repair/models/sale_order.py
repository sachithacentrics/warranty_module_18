from odoo import _, api, models
from odoo.exceptions import UserError

BACKUP_CHARGE_LINE_LOCKED = {'product_id', 'product_uom', 'product_uom_qty', 'price_unit',
                             'discount'}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model_create_multi
    def create(self, vals_list):
        """The Final Repair Quotation of a case (purpose set by the existing create) is the order
        of its open Repair Order. Parts quotations have no purpose and are never linked."""
        orders = super().create(vals_list)
        for order in orders.filtered(lambda o: o.warranty_chargeable_purpose == 'repair'):
            # sudo: system link; the salesperson may have no Repair rights.
            order.warranty_case_id._warranty_active_repairs().filtered(
                lambda repair: not repair.sale_order_id).sudo().write(
                {'sale_order_id': order.id})
        return orders

    def _warranty_backup_charge_units(self):
        # sudo: the salesperson may have no access to the backup unit; read for the checks only.
        return self.env['warranty.backup.unit'].sudo().search(
            [('charge_order_id', 'in', self.ids)])

    def copy(self, default=None):
        """Duplicate billing: the charge of a backup unit has exactly one quotation."""
        units = self._warranty_backup_charge_units()
        if units:
            raise UserError(_("Quotation %(order)s is the charge of backup unit %(unit)s and "
                              "cannot be duplicated.", order=units[0].charge_order_id.name,
                              unit=units[0].name))
        return super().copy(default=default)

    def _action_confirm(self):
        """The customer confirms the approved charge: one line, as approved."""
        for unit in self._warranty_backup_charge_units():
            order = unit.charge_order_id
            lines = order.order_line.filtered(lambda line: not line.display_type)
            line = lines if len(lines) == 1 else lines.browse()
            if not line or line.product_id != unit.charge_product_id \
                    or line.product_uom_qty != 1 or line.discount \
                    or order.currency_id != unit.currency_id \
                    or order.currency_id.compare_amounts(line.price_unit, unit.charge_amount):
                raise UserError(_(
                    "Quotation %(order)s must keep the charge approved on backup unit %(unit)s: "
                    "one line of %(product)s, quantity 1, price %(amount)s, in %(currency)s.",
                    order=order.name, unit=unit.name,
                    product=unit.charge_product_id.display_name, amount=unit.charge_amount,
                    currency=unit.currency_id.name))
        return super()._action_confirm()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def write(self, vals):
        if not self.env.su and BACKUP_CHARGE_LINE_LOCKED & set(vals) \
                and self.order_id._warranty_backup_charge_units():
            raise UserError(_("The charge of a backup unit is set by its approved assessment and "
                              "cannot be changed on the quotation."))
        return super().write(vals)
