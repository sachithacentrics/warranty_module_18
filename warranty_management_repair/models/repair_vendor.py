from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

# Figure 6 "Repair / vendor repair" (SRS 12 scenario 18, Service Mode Vendor Repair): the machine
# leaves the workshop for repair and comes back, with standard internal transfers of the exact
# serial between valued locations of the company. Nothing is sold, purchased or revalued: the
# machine stays where the intake put it in the books (same rule as the Warranty Repair Intake).
VENDOR_TRANSFER_TYPES = [
    ('internal', 'Internal Transfer'),
    ('external', 'External Vendor'),
]
VENDOR_DIRECTIONS = [
    ('send', 'Send for Repair'),
    ('receive', 'Receive from Repair'),
]
VENDOR_STATES = [
    ('none', 'Not Sent'),
    ('sending', 'Send Transfer Open'),
    ('at_vendor', 'Sent for Repair'),
    ('receiving', 'Receive Transfer Open'),
    ('received', 'Received Back'),
]


class StockLocation(models.Model):
    _inherit = 'stock.location'

    warranty_vendor_custody = fields.Boolean(
        string='Vendor Repair Custody',
        help="Where machines sent to an external vendor for a warranty repair are recorded. An "
             "internal (or company transit) location outside the warehouses: the machine is not "
             "sold, purchased or revalued.")
    warranty_vendor_partner_id = fields.Many2one(
        'res.partner', string='Repair Vendor',
        help="Only for this vendor. Empty: any vendor.")

    @api.constrains('warranty_vendor_custody', 'usage', 'company_id', 'warehouse_id',
                    'scrap_location')
    def _check_warranty_vendor_custody(self):
        for location in self.filtered('warranty_vendor_custody'):
            if location.usage not in ('internal', 'transit') or not location.company_id \
                    or location.warehouse_id or location.scrap_location:
                raise ValidationError(_(
                    "Vendor Repair Custody location %s must be an internal or transit location of "
                    "one company, outside the warehouses and not a scrap location.",
                    location.display_name))


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    warranty_vendor_repair_id = fields.Many2one(
        'repair.order', string='Vendor Repair of', readonly=True, copy=False,
        index='btree_not_null')
    warranty_vendor_direction = fields.Selection(VENDOR_DIRECTIONS, string='Vendor Repair Step',
                                                 readonly=True, copy=False)
    warranty_vendor_transfer_type = fields.Selection(VENDOR_TRANSFER_TYPES,
                                                     string='Vendor Repair Transfer',
                                                     readonly=True, copy=False)

    def _warranty_vendor_check_pickings(self):
        """Before any stock move: a vendor repair transfer moves exactly the serial of its
        Repair Order, once, between its own locations; the repaired machine is not returned to
        the customer while it is away."""
        for picking in self.filtered('warranty_vendor_repair_id'):
            repair = picking.sudo().warranty_vendor_repair_id
            if repair.state == 'cancel' or repair.warranty_equipment_returned:
                raise UserError(_("Repair Order %(repair)s is cancelled or its machine was "
                                  "returned: cancel %(picking)s.", repair=repair.name,
                                  picking=picking.name))
            if picking.warranty_vendor_direction == 'send' and repair._warranty_vendor_away():
                raise UserError(_("The machine of Repair Order %(repair)s is already away for "
                                  "repair: cancel %(picking)s.", repair=repair.name,
                                  picking=picking.name))
            if picking.warranty_vendor_direction == 'receive' and not repair._warranty_vendor_away():
                raise UserError(_("The machine of Repair Order %(repair)s is not away for repair: "
                                  "cancel %(picking)s.", repair=repair.name, picking=picking.name))
            lines = picking.move_line_ids.filtered('quantity')
            within = self.env['warranty.backup.unit']._warranty_backup_location_within
            if len(lines) != 1 or lines.product_id != repair.product_id \
                    or lines.lot_id != repair.lot_id or lines.quantity_product_uom != 1 \
                    or not within(lines.location_id, picking.location_id) \
                    or not within(lines.location_dest_id, picking.location_dest_id):
                raise UserError(_(
                    "%(picking)s must move exactly one %(product)s, serial %(serial)s, from "
                    "%(origin)s to %(destination)s (Repair Order %(repair)s).",
                    picking=picking.name, product=repair.product_id.display_name,
                    serial=repair.lot_id.name, origin=picking.location_id.display_name,
                    destination=picking.location_dest_id.display_name, repair=repair.name))
        # The standard return of the intake (machine back to the customer) waits for the machine.
        intakes = self.move_ids.origin_returned_move_id.picking_id.filtered(
            'warranty_repair_intake')
        if intakes:
            for repair in self.env['repair.order'].sudo().search(
                    [('picking_id', 'in', intakes.ids), ('warranty_case_id', '!=', False)]):
                if repair._warranty_vendor_busy():
                    raise UserError(_("The machine of Repair Order %s is away for repair or has a "
                                      "vendor repair transfer open: receive it first.",
                                      repair.name))

    def _warranty_vendor_after_pickings(self):
        for picking in self.filtered('warranty_vendor_repair_id'):
            repair = picking.sudo().warranty_vendor_repair_id
            if picking.warranty_vendor_direction == 'send':
                repair._warranty_repair_log(_(
                    "Machine of Repair Order %(repair)s, serial %(serial)s, sent for repair to "
                    "%(location)s%(vendor)s with %(picking)s.", repair=repair.name,
                    serial=repair.lot_id.name, location=picking.location_dest_id.display_name,
                    vendor=' (%s)' % picking.partner_id.display_name
                    if picking.warranty_vendor_transfer_type == 'external' else '',
                    picking=picking.name))
                repair._warranty_repair_todo(_("receive the machine from repair"), _(
                    "The machine is at %s: use Receive from Repair when it comes back.",
                    picking.location_dest_id.display_name))
            else:
                repair._warranty_repair_log(_(
                    "Machine of Repair Order %(repair)s, serial %(serial)s, received back from "
                    "repair in %(location)s with %(picking)s.", repair=repair.name,
                    serial=repair.lot_id.name, location=picking.location_dest_id.display_name,
                    picking=picking.name))
                repair._warranty_repair_todo(_("end the repair"), _(
                    "The machine is back in the workshop: set the Repair Result, then End Repair."))

    def _action_done(self):
        self._warranty_vendor_check_pickings()
        res = super()._action_done()
        self.filtered(lambda picking: picking.state == 'done')._warranty_vendor_after_pickings()
        return res


class RepairOrder(models.Model):
    _inherit = 'repair.order'

    warranty_vendor_picking_ids = fields.One2many(
        'stock.picking', 'warranty_vendor_repair_id', string='Vendor Repair Transfers',
        readonly=True)
    warranty_vendor_state = fields.Selection(VENDOR_STATES, string='Vendor Repair',
                                             compute='_compute_warranty_vendor_state')
    warranty_service_mode = fields.Selection(related='warranty_case_id.warranty_service_mode',
                                             string='Service Mode')

    @api.depends('warranty_vendor_picking_ids.state')
    def _compute_warranty_vendor_state(self):
        for repair in self:
            pickings = repair.sudo().warranty_vendor_picking_ids
            open_pickings = pickings.filtered(lambda p: p.state not in ('done', 'cancel'))
            done = pickings.filtered(lambda p: p.state == 'done').sorted('id')
            away = done[-1:].warranty_vendor_direction == 'send'
            if open_pickings:
                state = 'receiving' if away else 'sending'
            elif away:
                state = 'at_vendor'
            else:
                state = 'received' if done else 'none'
            repair.warranty_vendor_state = state

    def _warranty_vendor_away(self):
        """The last validated vendor repair transfer sent the machine away."""
        self.ensure_one()
        done = self.sudo().warranty_vendor_picking_ids.filtered(
            lambda picking: picking.state == 'done').sorted('id')
        return done[-1:].warranty_vendor_direction == 'send'

    def _warranty_vendor_open_pickings(self):
        self.ensure_one()
        return self.sudo().warranty_vendor_picking_ids.filtered(
            lambda picking: picking.state not in ('done', 'cancel'))

    def _warranty_vendor_busy(self):
        self.ensure_one()
        return bool(self._warranty_vendor_away() or self._warranty_vendor_open_pickings())

    # ------------------------------------------------------------------ checks
    def _warranty_vendor_check_user(self):
        if not self.env.user.has_group('stock.group_stock_user'):
            raise AccessError(_("Only Inventory users can send or receive machines for repair."))

    def _warranty_vendor_machine_location(self):
        """The verified location of the machine: exactly one unit of the serial, in a valued
        location of the Repair Order's company, not reserved by another transfer."""
        self.ensure_one()
        quants = self.env['stock.quant'].sudo().search([
            ('lot_id', '=', self.lot_id.id), ('product_id', '=', self.product_id.id),
            ('quantity', '>', 0)])
        if len(quants) != 1 or quants.quantity != 1:
            raise UserError(_("Serial %(serial)s of %(product)s must be in stock exactly once to "
                              "be moved for repair (found in: %(locations)s).",
                              serial=self.lot_id.name, product=self.product_id.display_name,
                              locations=', '.join(quants.location_id.mapped('display_name'))
                              or '-'))
        location = quants.location_id
        if not location._should_be_valued() or location.company_id != self.company_id:
            raise UserError(_("Serial %(serial)s is in %(location)s, not in a location of "
                              "%(company)s.", serial=self.lot_id.name,
                              location=location.display_name, company=self.company_id.name))
        if quants.reserved_quantity:
            raise UserError(_("Serial %(serial)s is reserved on another transfer: validate or "
                              "cancel it first.", serial=self.lot_id.name))
        return location

    def _warranty_vendor_intake_location(self):
        """Where the workshop keeps the machine: the destination of its validated intake."""
        self.ensure_one()
        return self.picking_id.location_dest_id

    def _warranty_vendor_send_problems(self):
        self.ensure_one()
        problems = []
        if not self.warranty_case_id:
            return [_("Repair Order %s has no warranty case.", self.name)]
        if self.warranty_case_id.sudo().warranty_service_mode != 'vendor':
            problems.append(_("Set the Service Mode of warranty case %s to Vendor Repair.",
                              self.warranty_case_id.sudo().name))
        if self.state != 'under_repair':
            problems.append(_("Start the repair first (Start Repair checks the case and its "
                              "inspection)."))
        if not self.lot_id:
            problems.append(_("The Repair Order has no serial."))
        if self.warranty_equipment_returned:
            problems.append(_("The machine has already been returned to the customer."))
        if self._warranty_vendor_busy():
            problems.append(_("The machine is already away for repair or has a vendor repair "
                              "transfer open."))
        return problems

    def _warranty_vendor_destinations(self, transfer_type, partner, source):
        """Destinations offered for the transfer type: valued locations of the company outside
        the warehouses. Internal: not a vendor custody, scrap, intake or backup location.
        External: the Vendor Repair Custody locations of this vendor (or of any vendor)."""
        self.ensure_one()
        Location = self.env['stock.location']
        if not transfer_type:
            return Location
        locations = Location.search([
            ('company_id', '=', self.company_id.id), ('usage', 'in', ('internal', 'transit')),
            ('warehouse_id', '=', False), ('scrap_location', '=', False)])
        within = self.env['warranty.backup.unit']._warranty_backup_location_within
        locations = locations.filtered(
            lambda location: location._should_be_valued() and location != source
            and not within(location, source) and not within(source, location))
        if transfer_type == 'external':
            commercial = partner.commercial_partner_id
            return locations.filtered(lambda location: location.warranty_vendor_custody and (
                not location.warranty_vendor_partner_id
                or location.warranty_vendor_partner_id.commercial_partner_id == commercial))
        company = self.company_id.sudo()
        reserved = (company.warranty_repair_intake_location_id
                    | company.warranty_backup_issue_type_id.default_location_src_id
                    | company.warranty_backup_issue_type_id.default_location_dest_id
                    | company.warranty_backup_return_type_id.default_location_dest_id)
        return locations.filtered(
            lambda location: location.usage == 'internal' and not location.warranty_vendor_custody
            and not any(within(location, other) for other in reserved))

    def _warranty_vendor_picking_type(self):
        """The existing standard Internal Transfers of the intake's warehouse, else of the
        company's only warehouse (no new operation type)."""
        self.ensure_one()
        warehouse = self.picking_id.picking_type_id.warehouse_id \
            or self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)])
        picking_type = warehouse.int_type_id if len(warehouse) == 1 \
            else self.env['stock.picking.type']
        if not picking_type.active or picking_type.code != 'internal' \
                or picking_type.company_id != self.company_id:
            raise UserError(_("No active standard Internal Transfers operation type was found for "
                              "%s.", self.company_id.name))
        return picking_type

    def _warranty_vendor_create_picking(self, direction, transfer_type, source, destination,
                                        partner):
        """Standard internal transfer of exactly this serial, reserved on that serial."""
        self.ensure_one()
        picking = self.env['stock.picking'].create({
            'picking_type_id': self._warranty_vendor_picking_type().id,
            'location_id': source.id,
            'location_dest_id': destination.id,
            'partner_id': partner.id,
            'origin': ' / '.join(filter(None, [self.name, self.warranty_case_id.sudo().name])),
            'warranty_vendor_repair_id': self.id,
            'warranty_vendor_direction': direction,
            'warranty_vendor_transfer_type': transfer_type,
            'move_ids': [(0, 0, {
                'name': self.name,
                'product_id': self.product_id.id,
                'product_uom': self.product_id.uom_id.id,
                'product_uom_qty': 1.0,
                'location_id': source.id,
                'location_dest_id': destination.id,
            })],
        })
        picking.action_confirm()
        move = picking.move_ids
        move._do_unreserve()
        if not move._update_reserved_quantity(1.0, source, lot_id=self.lot_id, strict=False):
            raise UserError(_("Serial %(serial)s is not available in %(location)s.",
                              serial=self.lot_id.name, location=source.display_name))
        move._recompute_state()
        return picking

    def _warranty_vendor_open(self, picking):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'res_id': picking.id,
        }

    # ------------------------------------------------------------------ actions
    def action_warranty_vendor_send(self):
        """Send for Repair: the open send transfer, else the wizard (transfer type, vendor,
        destination)."""
        self.ensure_one()
        self._warranty_vendor_check_user()
        open_send = self._warranty_vendor_open_pickings().filtered(
            lambda picking: picking.warranty_vendor_direction == 'send')
        if open_send:
            return self._warranty_vendor_open(open_send[:1])
        self._warranty_repair_raise(self._warranty_vendor_send_problems())
        self._warranty_vendor_machine_location()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Send for Repair"),
            'res_model': 'warranty.repair.vendor.send',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_repair_id': self.id},
        }

    def _warranty_vendor_send(self, transfer_type, partner, destination):
        """Called by the wizard, every check again."""
        self.ensure_one()
        self._warranty_vendor_check_user()
        self._warranty_repair_raise(self._warranty_vendor_send_problems())
        source = self._warranty_vendor_machine_location()
        if transfer_type == 'external' and not partner:
            raise UserError(_("Select the vendor."))
        if destination not in self._warranty_vendor_destinations(transfer_type, partner, source):
            raise UserError(_("%(location)s is not a valid destination for this %(type)s.",
                              location=destination.display_name,
                              type=dict(VENDOR_TRANSFER_TYPES)[transfer_type]))
        picking = self._warranty_vendor_create_picking(
            'send', transfer_type, source, destination,
            partner if transfer_type == 'external' else self.env['res.partner'])
        self._warranty_repair_log(_(
            "Send for Repair %(picking)s created by %(user)s: serial %(serial)s, %(origin)s -> "
            "%(destination)s (%(type)s%(vendor)s).", picking=picking.name,
            user=self.env.user.name, serial=self.lot_id.name, origin=source.display_name,
            destination=destination.display_name, type=dict(VENDOR_TRANSFER_TYPES)[transfer_type],
            vendor=', %s' % partner.display_name if transfer_type == 'external' else ''))
        return self._warranty_vendor_open(picking)

    def action_warranty_vendor_receive(self):
        """Receive from Repair: from where the machine verifiably is (the destination of the send)
        back to the workshop location of the intake; the open receive transfer is reopened."""
        self.ensure_one()
        self._warranty_vendor_check_user()
        open_receive = self._warranty_vendor_open_pickings().filtered(
            lambda picking: picking.warranty_vendor_direction == 'receive')
        if open_receive:
            return self._warranty_vendor_open(open_receive[:1])
        if not self._warranty_vendor_away():
            raise UserError(_("The machine of Repair Order %s is not away for repair.", self.name))
        if self._warranty_vendor_open_pickings():
            raise UserError(_("Repair Order %s has a vendor repair transfer open: validate or "
                              "cancel it first.", self.name))
        sent = self.sudo().warranty_vendor_picking_ids.filtered(
            lambda picking: picking.state == 'done').sorted('id')[-1:]
        source = self._warranty_vendor_machine_location()
        within = self.env['warranty.backup.unit']._warranty_backup_location_within
        if not within(source, sent.location_dest_id):
            raise UserError(_("Serial %(serial)s is in %(location)s, not where %(picking)s sent "
                              "it (%(destination)s).", serial=self.lot_id.name,
                              location=source.display_name, picking=sent.name,
                              destination=sent.location_dest_id.display_name))
        destination = self._warranty_vendor_intake_location()
        picking = self._warranty_vendor_create_picking(
            'receive', sent.warranty_vendor_transfer_type, source, destination, sent.partner_id)
        self._warranty_repair_log(_(
            "Receive from Repair %(picking)s created by %(user)s: serial %(serial)s, %(origin)s "
            "-> %(destination)s.", picking=picking.name, user=self.env.user.name,
            serial=self.lot_id.name, origin=source.display_name,
            destination=destination.display_name))
        return self._warranty_vendor_open(picking)

    # ------------------------------------------------------------------ guards
    def action_repair_done(self):
        for repair in self.filtered('warranty_case_id'):
            if repair._warranty_vendor_busy():
                raise UserError(_("Repair Order %s: the machine is away for repair or has a vendor "
                                  "repair transfer open; receive it first.", repair.name))
        return super().action_repair_done()

    def action_repair_cancel(self):
        for repair in self.filtered('warranty_case_id'):
            if repair._warranty_vendor_busy():
                raise UserError(_("Repair Order %s: the machine is away for repair or has a vendor "
                                  "repair transfer open; receive it first.", repair.name))
        return super().action_repair_cancel()

    def action_warranty_return_machine(self):
        self.ensure_one()
        if self._warranty_vendor_busy():
            raise UserError(_("Repair Order %s: the machine is away for repair; receive it first.",
                              self.name))
        return super().action_warranty_return_machine()
