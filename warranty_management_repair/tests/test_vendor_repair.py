from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged

from .test_figure6_service_mode import Figure6Common


@tagged('post_install', '-at_install', 'warranty_repair', 'warranty_vendor_repair')
class TestVendorRepair(Figure6Common):
    """Figure 6 vendor repair: Send for Repair / Receive from Repair with standard internal
    transfers of the serial, Internal Transfer or External Vendor custody; no sale, purchase or
    revaluation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        physical = cls.env.ref('stock.stock_location_locations')
        cls.vendor = cls.env['res.partner'].create({'name': 'F6 PCB Vendor'})
        cls.other_vendor = cls.env['res.partner'].create({'name': 'F6 Other Vendor'})

        def location(name, **vals):
            return cls.env['stock.location'].create(dict({
                'name': name, 'usage': 'internal', 'company_id': cls.company.id,
                'location_id': physical.id}, **vals))
        cls.lab = location('F6 PCB Lab')
        cls.custody = location('F6 At PCB Vendor', warranty_vendor_custody=True,
                               warranty_vendor_partner_id=cls.vendor.id)
        cls.any_custody = location('F6 At Any Vendor', warranty_vendor_custody=True)
        cls.other_custody = location('F6 At Other Vendor', warranty_vendor_custody=True,
                                     warranty_vendor_partner_id=cls.other_vendor.id)

    def setUp(self):
        super().setUp()
        self.case.sudo().warranty_inspection_required = False
        self._mode('vendor')
        self.intake = self._intake()
        self.repair = self._repair()
        self.repair.with_user(self.coordinator).action_validate()
        self.repair.with_user(self.coordinator).action_repair_start()
        self.assertEqual(self.repair.state, 'under_repair')

    # ------------------------------------------------------------------ helpers
    def _wizard(self, transfer_type, partner=None, user=None):
        action = self.repair.with_user(user or self.coordinator).action_warranty_vendor_send()
        self.assertEqual(action['res_model'], 'warranty.repair.vendor.send')
        form = Form(self.env[action['res_model']].with_user(user or self.coordinator)
                    .with_context(action['context']))
        form.transfer_type = transfer_type
        if partner:
            form.partner_id = partner
        return form

    def _send(self, transfer_type, destination, partner=None):
        form = self._wizard(transfer_type, partner)
        form.location_dest_id = destination
        action = form.save().action_confirm()
        return self.env['stock.picking'].browse(action['res_id'])

    def _receive(self):
        action = self.repair.with_user(self.coordinator).action_warranty_vendor_receive()
        return self.env['stock.picking'].browse(action['res_id'])

    def _layers(self):
        return self.env['stock.valuation.layer'].search_count([('product_id', '=', self.single.id)])

    # ------------------------------------------------------------------ tests
    def test_01_external_vendor_round_trip(self):
        form = self._wizard('external', self.vendor)
        self.assertEqual(form.location_id, self.intake_location)
        self.assertEqual(set(form.available_location_ids.ids),
                         {self.custody.id, self.any_custody.id})
        form.location_dest_id = self.custody
        layers = self._layers()
        picking = self.env['stock.picking'].browse(form.save().action_confirm()['res_id'])
        self.assertEqual((picking.picking_type_id, picking.location_id, picking.location_dest_id,
                          picking.partner_id, picking.warranty_vendor_repair_id,
                          picking.warranty_vendor_direction, picking.warranty_vendor_transfer_type),
                         (self.warehouse.int_type_id, self.intake_location, self.custody,
                          self.vendor, self.repair, 'send', 'external'))
        self.assertEqual((picking.move_line_ids.lot_id, picking.move_line_ids.quantity),
                         (self.serial, 1))
        self.assertIn(self.repair.name, picking.origin)
        self.assertIn(self.case.name, picking.origin)
        self.assertEqual(self.repair.warranty_vendor_state, 'sending')
        self.assertEqual(self.repair.warranty_intake_state, 'under_repair')
        # The open transfer is reopened, never a second one.
        self.assertEqual(self.repair.with_user(self.coordinator).action_warranty_vendor_send()[
            'res_id'], picking.id)
        self._validate(picking)
        self.assertEqual((self.repair.warranty_vendor_state, self.repair.warranty_intake_state),
                         ('at_vendor', 'at_vendor'))
        self.assertEqual(self._layers(), layers, 'No valuation: the machine is not sold.')
        self.assertFalse(self.env['purchase.order'].search([('partner_id', '=', self.vendor.id)]))
        for record in (self.repair, self.case, self.card):
            with self.subTest(history=record._name):
                self.assertTrue(any('sent for repair' in body
                                    for body in record.sudo().message_ids.mapped('body')))
        # Away: no End Repair, no return to the customer, no cancellation, no second send.
        self.repair.warranty_repair_result = 'repaired'
        for method in ('action_repair_done', 'action_warranty_return_machine',
                       'action_repair_cancel', 'action_warranty_vendor_send'):
            with self.subTest(method=method), self.assertRaisesRegex(UserError, 'away for repair'):
                getattr(self.repair.with_user(self.coordinator), method)()
        back = self._receive()
        self.assertEqual((back.location_id, back.location_dest_id, back.partner_id,
                          back.warranty_vendor_direction, back.warranty_vendor_transfer_type),
                         (self.custody, self.intake_location, self.vendor, 'receive', 'external'))
        self.assertEqual(self._receive(), back, 'The open receive is reopened.')
        self.assertEqual(self.repair.warranty_intake_state, 'at_vendor')
        self._validate(back)
        self.assertEqual((self.repair.warranty_vendor_state, self.repair.warranty_intake_state),
                         ('received', 'under_repair'))
        self.assertEqual(self._layers(), layers)
        self.repair.with_user(self.coordinator).action_repair_done()
        self._return_and_complete(self.repair)

    def test_02_internal_transfer(self):
        form = self._wizard('internal')
        offered = form.available_location_ids
        self.assertIn(self.lab, offered)
        for location in (self.custody, self.any_custody, self.intake_location, self.stock):
            with self.subTest(location=location.name):
                self.assertNotIn(location, offered)
        form.location_dest_id = self.lab
        picking = self.env['stock.picking'].browse(form.save().action_confirm()['res_id'])
        self.assertFalse(picking.partner_id)
        self._validate(picking)
        back = self._receive()
        self.assertEqual((back.location_id, back.location_dest_id), (self.lab, self.intake_location))
        self._validate(back)
        self.assertEqual(self.repair.warranty_vendor_state, 'received')
        # A second round is possible after the first one came back.
        second = self._send('external', self.any_custody, partner=self.other_vendor)
        self.assertEqual(second.location_dest_id, self.any_custody)

    def test_03_send_refusals(self):
        # Invalid destinations, given directly: other vendor's custody, warehouse stock.
        for destination, partner in ((self.other_custody, self.vendor), (self.stock, self.vendor),
                                     (self.lab, self.vendor)):
            with self.subTest(destination=destination.name), \
                    self.assertRaisesRegex(UserError, 'not a valid destination'):
                self.repair.with_user(self.coordinator)._warranty_vendor_send(
                    'external', partner, destination)
        with self.assertRaisesRegex(UserError, 'Select the vendor'):
            self.repair.with_user(self.coordinator)._warranty_vendor_send(
                'external', self.env['res.partner'], self.any_custody)
        # Receive without send.
        with self.assertRaisesRegex(UserError, 'not away for repair'):
            self.repair.with_user(self.coordinator).action_warranty_vendor_receive()
        # Not the Vendor Repair mode.
        self._mode('workshop')
        with self.assertRaisesRegex(UserError, 'Vendor Repair'):
            self.repair.with_user(self.coordinator).action_warranty_vendor_send()

    def test_04_not_started_refused(self):
        repair = self.repair
        repair.sudo().state = 'confirmed'
        with self.assertRaisesRegex(UserError, 'Start the repair first'):
            repair.with_user(self.coordinator).action_warranty_vendor_send()

    def test_05_wrong_serial_or_location_on_validation(self):
        picking = self._send('external', self.custody, partner=self.vendor)
        other = self._lot(self.single, 5)
        self.env['stock.quant']._update_available_quantity(self.single, self.intake_location, 1,
                                                           lot_id=other)
        picking.move_line_ids.lot_id = other
        picking.move_ids.picked = True
        with self.assertRaisesRegex(UserError, 'must move exactly one'):
            picking.with_context(skip_backorder=True).button_validate()
        picking.move_line_ids.lot_id = self.serial
        picking.move_line_ids.location_dest_id = self.lab
        with self.assertRaisesRegex(UserError, 'must move exactly one'):
            picking.with_context(skip_backorder=True).button_validate()

    def test_06_receive_checks_where_the_machine_is(self):
        self._validate(self._send('external', self.custody, partner=self.vendor))
        Quant = self.env['stock.quant']
        Quant._update_available_quantity(self.single, self.custody, -1, lot_id=self.serial)
        Quant._update_available_quantity(self.single, self.lab, 1, lot_id=self.serial)
        with self.assertRaisesRegex(UserError, 'not where'):
            self.repair.with_user(self.coordinator).action_warranty_vendor_receive()

    def test_07_permissions_and_mode(self):
        for user in (self.helpdesk_only, self.outsider):
            with self.subTest(user=user.login), self.assertRaises(AccessError):
                self.repair.with_user(user).action_warranty_vendor_send()
        self._validate(self._send('internal', self.lab))
        with self.assertRaisesRegex(UserError, 'stays Vendor Repair'):
            self._mode('workshop')
        self.assertFalse(self.repair.with_user(self.stock_only).warranty_vendor_picking_ids
                         .filtered(lambda p: p.state != 'done'))

    def test_08_multi_company(self):
        other = self.env['res.company'].create({'name': 'F6 Other Company'})
        foreign = self.env['stock.location'].create({
            'name': 'F6 Foreign Custody', 'usage': 'internal', 'company_id': other.id,
            'warranty_vendor_custody': True,
            'location_id': self.env.ref('stock.stock_location_locations').id})
        form = self._wizard('external', self.vendor)
        self.assertNotIn(foreign, form.available_location_ids)
        with self.assertRaisesRegex(UserError, 'not a valid destination'):
            self.repair.with_user(self.coordinator)._warranty_vendor_send(
                'external', self.vendor, foreign)
        outsider = self.env['res.users'].create({
            'name': 'f6_other', 'login': 'f6_other', 'company_id': other.id,
            'company_ids': [Command.set(other.ids)],
            'groups_id': [Command.set((self.env.ref('base.group_user')
                                       | self.env.ref('stock.group_stock_user')).ids)]})
        with self.assertRaises(AccessError):
            self.repair.with_user(outsider).action_warranty_vendor_send()

    def test_09_custody_location_rules(self):
        with self.assertRaises(ValidationError):
            self.stock.warranty_vendor_custody = True
        with self.assertRaises(ValidationError):
            self.env['stock.location'].create({
                'name': 'F6 Bad Custody', 'usage': 'supplier', 'warranty_vendor_custody': True})

    def test_10_standard_return_to_customer_waits(self):
        """The standard Return of the intake (the ticket's Return button) cannot deliver the
        machine while it is away."""
        self._validate(self._send('internal', self.lab))
        wizard = Form(self.env['stock.return.picking'].with_context(
            active_id=self.intake.id, active_ids=self.intake.ids, active_model='stock.picking'))
        with wizard.product_return_moves.edit(0) as line:
            line.quantity = 1
        back = self.env['stock.picking'].browse(wizard.save().action_create_returns()['res_id'])
        back.move_ids.move_line_ids.unlink()
        back.move_ids.move_line_ids = [Command.create({
            'product_id': self.single.id, 'lot_id': self.serial.id, 'quantity': 1,
            'location_id': back.location_id.id, 'location_dest_id': back.location_dest_id.id,
            'picking_id': back.id})]
        back.move_ids.picked = True
        with self.assertRaisesRegex(UserError, 'away for repair'):
            back.with_context(skip_backorder=True).button_validate()
