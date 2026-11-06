from odoo import _, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    warranty_repair_intake = fields.Boolean(
        string='Warranty Repair Intake', readonly=True, copy=False,
        help="Return of a customer machine for a workshop repair (not a commercial return).")

    def _warranty_allocate_sale_line(self, sale_line, moves):
        """The machine delivered back after a repair keeps its Sales Order line: it is not a new
        delivery and is never allocated to another unit of that line. Runs before the kit logic
        (warranty_management_mrp is a dependency)."""
        moves = moves.filtered(
            lambda move: not move.origin_returned_move_id.picking_id.warranty_repair_intake)
        if not moves:
            return self.env['warranty.card']
        return super()._warranty_allocate_sale_line(sale_line, moves)

    def _warranty_repair_received(self, product, serial):
        """Whether this validated picking moved exactly this product and serial record."""
        self.ensure_one()
        return bool(self.move_line_ids.filtered(
            lambda line: line.state == 'done' and line.quantity and line.product_id == product
            and line.lot_id == serial))

    def _warranty_check_repair_intake_machine(self):
        """Before any stock move: an intake return receives only the machine of its ticket. The
        return wizard cannot check this, as the serial is entered on the receipt. A ticket without
        a serial is checked by product, including a kit's components."""
        # sudo: the warehouse user may not read the ticket; read for the check only.
        Ticket = self.env['helpdesk.ticket'].sudo()
        for picking in self.filtered('warranty_repair_intake'):
            ticket = Ticket.search([('picking_ids', 'in', picking.id)], limit=1)
            if not ticket:
                continue
            product, serial = ticket._warranty_repair_machine()
            for line in picking.move_line_ids.filtered('quantity'):
                wrong = line.lot_id != serial or line.product_id != product if serial \
                    else product and product not in (
                        line.product_id | line.move_id.sale_line_id.product_id)
                if wrong:
                    raise UserError(_(
                        "Warranty Repair Intake %(picking)s: product %(product)s, serial "
                        "%(serial)s is not the machine of Helpdesk ticket %(ticket)s (product "
                        "%(ticket_product)s, serial %(ticket_serial)s).", picking=picking.name,
                        product=line.product_id.display_name, serial=line.lot_id.name or '-',
                        ticket=ticket.name, ticket_product=product.display_name or '-',
                        ticket_serial=serial.name or '-'))

    def _action_done(self):
        self._warranty_check_repair_intake_machine()
        Backup = self.env['warranty.backup.unit']
        Backup._warranty_backup_check_pickings(self)
        Replacement = self.env['warranty.replacement']
        Replacement._warranty_replacement_check_pickings(self)
        res = super()._action_done()
        done = self.filtered(lambda picking: picking.state == 'done')
        Backup._warranty_backup_after_pickings(done)
        Replacement._warranty_replacement_after_pickings(done)
        # sudo: the warehouse user may have no Repair rights; history notes and To-Dos only.
        Repair = self.env['repair.order'].sudo()
        received = done.filtered('warranty_repair_intake')
        for repair in Repair.search([('picking_id', 'in', received.ids),
                                     ('warranty_case_id', '!=', False)]):
            repair._warranty_repair_log(_(
                "Machine received for Repair Order %(repair)s with %(picking)s.",
                repair=repair.name, picking=repair.picking_id.name))
            repair._warranty_repair_todo(_("confirm the repair"), _(
                "The machine is in the Warranty Repair Intake location."))
        origins = done.filtered(
            lambda picking: picking.picking_type_code == 'outgoing'
        ).move_ids.origin_returned_move_id.picking_id.filtered('warranty_repair_intake')
        for repair in Repair.search([('picking_id', 'in', origins.ids),
                                     ('warranty_case_id', '!=', False)]).filtered(
                'warranty_equipment_returned'):
            repair._warranty_repair_log(_(
                "Machine of Repair Order %(repair)s returned to the customer.",
                repair=repair.name))
            Backup._warranty_backup_repair_returned(repair)
            if repair.warranty_case_id.open_service_job_id:
                # The job keeps control; its completion is no longer blocked by this repair.
                repair._warranty_repair_close_todos()
            else:
                repair._warranty_repair_todo(_("complete the warranty case"), _(
                    "The machine was returned to the customer: use Complete Warranty Case."))
        return res
