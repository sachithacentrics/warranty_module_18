from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockReturnPickingLine(models.TransientModel):
    _inherit = 'stock.return.picking.line'

    def _prepare_move_default_values(self, new_picking):
        """Neither the intake nor the delivery back changes the Sales Order delivered quantity
        (sale_stock: a returned move only counts with to_refund, in both directions)."""
        vals = super()._prepare_move_default_values(new_picking)
        if self.wizard_id.warranty_repair_intake \
                or self.move_id.picking_id.warranty_repair_intake:
            vals['to_refund'] = False
        return vals


class StockReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    warranty_repair_intake = fields.Boolean(
        string='Warranty Repair Intake', compute='_compute_warranty_repair_intake', store=True,
        readonly=False,
        help="Ticked: the customer's machine comes in for a workshop repair; the Sales Order "
             "quantities do not change. Untick it for a commercial return of the goods.")

    @api.depends('ticket_id')
    def _compute_warranty_repair_intake(self):
        for wizard in self:
            wizard.warranty_repair_intake = wizard.ticket_id.is_warranty

    def _compute_picking_id(self):
        """Warranty Repair Intake: the default delivery is the one of the ticket's machine (the
        standard takes the customer's latest delivery when the ticket has no product): with a
        serial the latest delivery of it, without one only a single matching delivery. A
        delivery or Sales Order chosen by the user and other returns stay standard."""
        standard = self.browse()
        for wizard in self:
            if not wizard.ticket_id or not wizard.warranty_repair_intake:
                standard |= wizard
            elif wizard.picking_id:
                # Chosen delivery, or its own Sales Order recomputed from it: kept.
                if wizard.sale_order_id and wizard.picking_id.sale_id != wizard.sale_order_id:
                    standard |= wizard
            elif wizard.sale_order_id:
                standard |= wizard
            else:
                deliveries = wizard._warranty_machine_deliveries()
                if deliveries is None:
                    standard |= wizard
                elif wizard.ticket_id._warranty_repair_machine()[1] or len(deliveries) == 1:
                    wizard.picking_id = deliveries[:1]
                    # Read above while empty: its Sales Order follows the delivery.
                    wizard.invalidate_recordset(['sale_order_id'])
        super(StockReturnPicking, standard)._compute_picking_id()

    def _warranty_machine_deliveries(self):
        """Done customer deliveries of the ticket's customer and company holding its machine,
        latest first; None when the machine is unknown."""
        ticket = self.ticket_id
        product, serial = ticket._warranty_repair_machine()
        if not product:
            return None
        deliveries = self.env['stock.picking'].search([
            ('state', '=', 'done'), ('picking_type_code', '=', 'outgoing'),
            ('location_dest_id.usage', '=', 'customer'),
            ('partner_id', 'child_of', ticket.partner_id.commercial_partner_id.id),
            ('company_id', '=', ticket.company_id.id),
        ], order='id desc')
        return deliveries.filtered(lambda picking: self._warranty_machine_lines(
            picking, product, serial))

    @api.model
    def _warranty_machine_lines(self, picking, product, serial):
        """Done lines of the delivery holding the machine (serial record, else the product,
        including a kit's components)."""
        lines = picking.move_line_ids.filtered(lambda line: line.state == 'done')
        if serial:
            return lines.filtered(lambda line: line.product_id == product and line.lot_id == serial)
        return lines.filtered(lambda line: product in (
            line.product_id | line.move_id.sale_line_id.product_id))

    def _prepare_picking_default_values(self):
        vals = super()._prepare_picking_default_values()
        if self.env['warranty.backup.unit']._warranty_backup_units_of(self.picking_id):
            raise UserError(_("%s is a backup unit transfer: use Create Return Transfer on the "
                              "backup unit.", self.picking_id.name))
        self.env['warranty.replacement']._warranty_replacement_check_standard_return(self)
        if self.warranty_repair_intake:
            location = self.picking_id.company_id.warranty_repair_intake_location_id
            if not location:
                raise UserError(_("Set the Warranty Repair Intake Location of %s in Settings > "
                                  "Warranty.", self.picking_id.company_id.name))
            if self.picking_id.location_dest_id.usage != 'customer':
                raise UserError(_("A warranty repair intake returns a delivery to the customer "
                                  "(%s is not one).", self.picking_id.name))
            self._warranty_check_repair_intake_delivery()
            vals.update({'location_dest_id': location.id, 'warranty_repair_intake': True})
        return vals

    def _warranty_check_repair_intake_delivery(self):
        """Before the return exists: the delivery holds the ticket's machine (product and serial
        records, never names) and only its line is returned. A ticket without a serial is checked
        by product, including a kit's components."""
        self.ensure_one()
        if not self.ticket_id:
            return
        product, serial = self.ticket_id._warranty_repair_machine()
        if not product:
            return
        machine = self._warranty_machine_lines(self.picking_id, product, serial)
        if not machine:
            raise UserError(_(
                "Delivery %(picking)s does not contain the machine of this ticket (product "
                "%(product)s, serial %(serial)s): select the correct Delivery to Return.",
                picking=self.picking_id.name, product=product.display_name,
                serial=serial.name or '-'))
        other = self.product_return_moves.filtered('quantity').move_id - machine.move_id
        if other:
            raise UserError(_(
                "Return only the machine of this ticket (product %(product)s, serial %(serial)s), "
                "not %(others)s.", product=product.display_name, serial=serial.name or '-',
                others=', '.join(other.product_id.mapped('display_name'))))

    def action_create_exchanges(self):
        if self.warranty_repair_intake:
            raise UserError(_("A warranty repair intake is not an exchange: use Return, or untick "
                              "Warranty Repair Intake."))
        return super().action_create_exchanges()
