from odoo import fields, models


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    # Internal users only: portal users read tickets but not backup units.
    warranty_backup_unit_count = fields.Integer(compute='_compute_warranty_backup_unit_count',
                                                groups='base.group_user')

    def _compute_warranty_backup_unit_count(self):
        counts = self.env['warranty.backup.unit']._warranty_backup_counts('ticket_id', self)
        for ticket in self:
            ticket.warranty_backup_unit_count = counts.get(ticket._origin.id, 0)

    def action_view_warranty_backup_units(self):
        self.ensure_one()
        return self.env['warranty.backup.unit']._warranty_backup_action([('ticket_id', '=', self.id)])

    def _get_last_sol_of_customer(self):
        """helpdesk_sale_timesheet proposes the customer's latest prepaid service line (often an
        inspection or charge quotation of another case). Warranty tickets are billed through
        their own quotations (SRS 2.6 / 2.11): no line is proposed, so a cleared Sales Order
        Item stays empty. A line chosen by the user or a fixed-price project line is kept."""
        self.ensure_one()
        if self.is_warranty:
            return self.env['sale.order.line']
        return super()._get_last_sol_of_customer()

    def _warranty_active_cases(self):
        self.ensure_one()
        return self.warranty_case_ids.filtered(
            lambda case: case.state not in ('rejected', 'closed', 'completed'))

    def _warranty_repair_machine(self):
        """The (product, serial) of the ticket's machine: the warranty panel, or its case when
        only one is active, or the case given by a service job (Figure 6 F1: a ticket with several
        active cases). Serial records, never names (two products can share a serial name); a kit
        serial gives its component."""
        self.ensure_one()
        cases = self._warranty_active_cases()
        given = cases.filtered(lambda case: case.id == self.env.context.get('warranty_repair_case_id'))
        case = given or (cases if len(cases) == 1 else self.env['warranty.case'])
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
            'default_warranty_case_id': cases.id if len(cases) == 1 else cases.filtered(
                lambda case: case.id == self.env.context.get('warranty_repair_case_id')).id,
            'default_repair_picking_id': intakes[-1:].id,
        })
        return values
