from odoo import models


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    def _warranty_active_cases(self):
        self.ensure_one()
        return self.warranty_case_ids.filtered(
            lambda case: case.state not in ('rejected', 'closed', 'completed'))

    def _warranty_repair_machine(self):
        """The (product, serial) of the ticket's machine: the warranty panel, or its case when
        only one is active. Serial records, never names (two products can share a serial name);
        a kit serial gives its component."""
        self.ensure_one()
        cases = self._warranty_active_cases()
        case = cases if len(cases) == 1 else self.env['warranty.case']
        serial = case.serial_id or self.warranty_serial_id or self.lot_id
        product = serial.product_id or case.product_id or self.warranty_product_id \
            or self.product_id
        return product, serial

    def _prepare_repairs_default_value(self):
        """Repair button of a warranty ticket: the Repair Order is never linked to the customer's
        original Sales Order; product and serial come from the warranty panel, the case when only
        one is active. Return: only a validated intake that received this machine, else none."""
        values = super()._prepare_repairs_default_value()
        if not self.is_warranty:
            return values
        values.pop('default_sale_order_id', None)
        cases = self._warranty_active_cases()
        product, serial = self._warranty_repair_machine()
        intakes = self.picking_ids.filtered(
            lambda picking: picking.warranty_repair_intake
            and picking._warranty_repair_received(product, serial)).sorted('id')
        values.update({
            'default_product_id': product.id,
            'default_lot_id': serial.id,
            'default_warranty_case_id': cases.id if len(cases) == 1 else False,
            'default_repair_picking_id': intakes[-1:].id,
        })
        return values
