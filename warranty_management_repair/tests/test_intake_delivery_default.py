from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_repair')
class TestIntakeDeliveryDefault(ReplacementCommon):
    """Figure 6 (ticket #29): the Warranty Repair Intake proposes the delivery of the ticket's
    machine, not the customer's latest delivery."""

    def setUp(self):
        super().setUp()
        self.coordinator.email = 'intake.coordinator@example.com'
        self.company.warranty_repair_intake_location_id = self.env['stock.location'].create({
            'name': 'WR Repair Intake', 'usage': 'internal', 'company_id': self.company.id,
            'location_id': self.env.ref('stock.stock_location_locations').id})
        self.card = self._card(self.single)
        self.serial = self.card.unit_warranty_ids.serial_ids
        self.delivery = self.card.sale_order_id.picking_ids
        # A later, unrelated delivery to the same customer (another serial).
        self.other_card = self._card(self.single)
        self.other_delivery = self.other_card.sale_order_id.picking_ids
        self.assertGreater(self.other_delivery.id, self.delivery.id)

    def _wizard(self, ticket):
        return Form(self.env['stock.return.picking'].with_user(self.coordinator).with_context(
            default_ticket_id=ticket.id, default_company_id=ticket.company_id.id))

    def _ticket(self, **vals):
        return self.env['helpdesk.ticket'].create(dict({
            'name': 'Intake ticket', 'team_id': self.team.id, 'partner_id': self.partner.id},
            **vals))

    def test_01_serial_selects_its_delivery(self):
        ticket = self._ticket(is_warranty=True)
        self.env['warranty.case'].create({
            'helpdesk_ticket_id': ticket.id, 'partner_id': self.partner.id,
            'company_id': self.company.id, 'case_type': 'warranty_complaint',
            'serial_id': self.serial.id, 'requested_item_ids': [(6, 0, self.item.ids)]
        }).action_check_eligibility()
        wizard = self._wizard(ticket)
        self.assertTrue(wizard.warranty_repair_intake)
        self.assertEqual((wizard.picking_id, wizard.sale_order_id),
                         (self.delivery, self.card.sale_order_id))

    def test_02_product_only_needs_a_single_match(self):
        ticket = self._ticket(is_warranty=True, product_id=self.single.id)
        self.assertFalse(self._wizard(ticket).picking_id, 'two deliveries: the user chooses')
        self.other_delivery.partner_id = self.env['res.partner'].create({'name': 'Elsewhere'})
        self.assertEqual(self._wizard(ticket).picking_id, self.delivery, 'one delivery')

    def test_03_non_warranty_and_unticked_stay_standard(self):
        self.assertEqual(self._wizard(self._ticket()).picking_id, self.other_delivery)
        ticket = self._ticket(is_warranty=True)
        self.env['warranty.case'].create({
            'helpdesk_ticket_id': ticket.id, 'partner_id': self.partner.id,
            'company_id': self.company.id, 'case_type': 'warranty_complaint',
            'serial_id': self.serial.id, 'requested_item_ids': [(6, 0, self.item.ids)]})
        wizard = self.env['stock.return.picking'].with_context(default_ticket_id=ticket.id).new(
            {'ticket_id': ticket.id, 'warranty_repair_intake': False})
        self.assertEqual(wizard.picking_id, self.other_delivery)

    def test_04_manual_sales_order_and_wrong_delivery(self):
        ticket = self._ticket(is_warranty=True)
        self.env['warranty.case'].create({
            'helpdesk_ticket_id': ticket.id, 'partner_id': self.partner.id,
            'company_id': self.company.id, 'case_type': 'warranty_complaint',
            'serial_id': self.serial.id, 'requested_item_ids': [(6, 0, self.item.ids)]})
        wizard = self._wizard(ticket)
        wizard.sale_order_id = self.other_card.sale_order_id
        self.assertEqual(wizard.picking_id, self.other_delivery, 'the user choice is kept')
        with wizard.product_return_moves.edit(0) as line:
            line.quantity = 1
        record = wizard.save()
        with self.assertRaisesRegex(UserError, 'does not contain the machine of this ticket'):
            record.action_create_returns()
        record.picking_id = self.delivery
        record.product_return_moves.quantity = 1
        returned = self.env['stock.picking'].browse(record.action_create_returns()['res_id'])
        self.assertEqual(returned.location_dest_id, self.company.warranty_repair_intake_location_id)
        self.assertFalse(returned.move_ids.to_refund)
