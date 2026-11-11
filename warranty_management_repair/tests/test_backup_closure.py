from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_repair', 'warranty_backup_closure')
class TestBackupClosure(ReplacementCommon):
    """Figure 6 C2: Damaged / Lost backup Close after an approved assessment, a settled charge
    and a verified standard stock operation; Lost -> Found recovery; written-off serials never
    issued again. Close itself creates no stock or accounting record."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coordinator.email = 'closure@example.com'
        cls.helpdesk_only = cls._user('bc_helpdesk', 'helpdesk.group_helpdesk_user')
        cls.approver = cls._user('bc_approver', 'helpdesk.group_helpdesk_user',
                                 'stock.group_stock_user')
        physical = cls.env.ref('stock.stock_location_locations')
        cls.backup_stock, cls.loan, cls.inspection = (cls.env['stock.location'].create({
            'name': name, 'usage': 'internal', 'company_id': cls.company.id,
            'location_id': physical.id}) for name in ('BC Backup Stock', 'BC Loan', 'BC Inspection'))
        issue_type, return_type = (cls.env['stock.picking.type'].create({
            'name': name, 'code': 'internal', 'sequence_code': code, 'company_id': cls.company.id,
            'default_location_src_id': source.id, 'default_location_dest_id': destination.id,
        }) for name, code, source, destination in (
            ('BC Backup Issue', 'BCBI', cls.backup_stock, cls.loan),
            ('BC Backup Return', 'BCBR', cls.loan, cls.inspection)))
        cls.charge_product = cls.env['product.product'].create({
            'name': 'BC Backup Charge', 'type': 'service', 'sale_ok': True,
            'invoice_policy': 'order'})
        cls.company.write({'warranty_backup_issue_type_id': issue_type.id,
                           'warranty_backup_return_type_id': return_type.id,
                           'warranty_backup_approver_user_ids': [Command.set(cls.approver.ids)],
                           'warranty_backup_charge_product_id': cls.charge_product.id})
        warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)])
        cls.internal_type = warehouse.int_type_id
        cls.internal_type.active = True
        cls.backup_product = cls.env['product.product'].create({
            'name': 'BC Backup AC', 'type': 'consu', 'is_storable': True, 'tracking': 'serial'})
        cls.lot, cls.lot2 = (cls.env['stock.lot'].create({
            'name': name, 'product_id': cls.backup_product.id}) for name in ('BC-01', 'BC-02'))
        for lot in (cls.lot, cls.lot2):
            cls.env['stock.quant']._update_available_quantity(
                cls.backup_product, cls.backup_stock, 1, lot_id=lot)

    def setUp(self):
        super().setUp()
        self.case = self._eligible_case(self._card(self.single).unit_warranty_ids.serial_ids)
        self.ticket = self.case.helpdesk_ticket_id

    # ------------------------------------------------------------------ helpers
    def _issued(self, lot=None):
        unit = self.env['warranty.backup.unit'].with_user(self.coordinator).create({
            'ticket_id': self.ticket.id, 'partner_id': self.partner.id,
            'warranty_case_id': self.case.id, 'product_id': self.backup_product.id,
            'lot_id': (lot or self.lot).id, 'issue_condition': 'good',
            'expected_return_date': fields.Date.today() + timedelta(days=7)})
        unit.action_warranty_backup_issue()
        self._validate(unit.issue_picking_id)
        self.assertEqual(unit.state, 'issued')
        return unit

    def _receive(self, unit, condition):
        unit.with_user(self.coordinator).write({'return_condition': condition})
        unit.with_user(self.coordinator).action_warranty_backup_return()
        self._validate(unit.return_picking_id)

    def _damaged(self, charge=0.0, lot=None):
        unit = self._issued(lot)
        self._receive(unit, 'damaged')
        self.assertEqual(unit.state, 'damaged')
        self._approve(unit, charge)
        return unit

    def _lost(self, charge=0.0):
        unit = self._issued()
        unit.with_user(self.coordinator).write({'assessment_notes': 'Lost on site',
                                                'charge_amount': charge})
        unit.with_user(self.coordinator).action_warranty_backup_report_lost()
        self._decide(unit, charge)
        self.assertEqual(unit.state, 'lost')
        return unit

    def _approve(self, unit, charge):
        unit.with_user(self.coordinator).write({'assessment_notes': 'Cracked panel',
                                                'charge_amount': charge})
        unit.with_user(self.coordinator).action_warranty_backup_submit_assessment()
        self._decide(unit, charge)

    def _decide(self, unit, charge):
        unit.with_user(self.approver).write({'assessment_decision_note': 'Checked'})
        unit.with_user(self.approver).action_warranty_backup_approve_assessment()
        self.assertEqual(unit.assessment_state, 'approved')
        self.assertEqual(bool(unit.charge_order_id), bool(charge))

    def _invoice(self, unit):
        order = unit.sudo().charge_order_id
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        return invoice

    def _pay(self, invoice):
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()

    def _scrap(self, location, lot=None):
        scrap = self.env['stock.scrap'].create({
            'product_id': self.backup_product.id, 'lot_id': (lot or self.lot).id,
            'scrap_qty': 1, 'location_id': location.id, 'company_id': self.company.id})
        scrap.action_validate()
        self.assertEqual(scrap.state, 'done')
        return scrap

    def _count(self, location, quantity, lot=None):
        """Physical Inventory: counted quantity of the serial, applied (Inventory Administrator)."""
        Quant = self.env['stock.quant'].with_context(inventory_mode=True)
        quant = Quant.search([('lot_id', '=', (lot or self.lot).id),
                              ('location_id', '=', location.id)]) or Quant.create({
            'product_id': self.backup_product.id, 'lot_id': (lot or self.lot).id,
            'location_id': location.id})
        quant.inventory_quantity = quantity
        quant.action_apply_inventory()

    def _transfer_out_of_scrap(self, scrap, destination):
        """A standard stock correction: an internal transfer of the serial back from scrap."""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.internal_type.id, 'location_id': scrap.scrap_location_id.id,
            'location_dest_id': destination.id,
            'move_ids': [Command.create({
                'name': 'correction', 'product_id': self.backup_product.id, 'product_uom_qty': 1,
                'product_uom': self.backup_product.uom_id.id,
                'location_id': scrap.scrap_location_id.id, 'location_dest_id': destination.id})]})
        picking.action_confirm()
        picking.move_ids.move_line_ids.unlink()
        picking.move_ids.move_line_ids = [Command.create({
            'product_id': self.backup_product.id, 'lot_id': self.lot.id, 'quantity': 1,
            'location_id': scrap.scrap_location_id.id, 'location_dest_id': destination.id,
            'picking_id': picking.id})]
        picking.move_ids.picked = True
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, 'done')

    def _close(self, unit, user=None):
        return unit.with_user(user or self.coordinator).action_warranty_backup_close()

    def _records(self):
        return (self.env['stock.move'].search_count([]), self.env['stock.scrap'].search_count([]),
                self.env['account.move'].search_count([]), self.env['stock.picking'].search_count([]))

    def _issuable(self, lot=None):
        new = self.env['warranty.backup.unit'].with_user(self.coordinator).new({
            'ticket_id': self.ticket.id, 'product_id': self.backup_product.id})
        return (lot or self.lot).id in new.available_lot_ids._origin.ids

    # ------------------------------------------------------------------ Damaged
    def test_01_damaged_no_charge_scrapped(self):
        unit = self._damaged()
        with self.assertRaisesRegex(UserError, 'Scrap serial BC-01'):
            self._close(unit)
        scrap = self._scrap(self.inspection)
        before = self._records()
        self._close(unit)
        self.assertEqual(self._records(), before, 'Close creates no stock or accounting record.')
        self.assertEqual((unit.state, unit.disposal_type), ('closed', 'scrap'))
        self.assertEqual(unit.disposal_move_line_id.move_id.scrap_id, scrap)
        self.assertTrue(any('Disposition Scrapped' in body
                            for body in unit.sudo().message_ids.mapped('body')))
        self.assertFalse(self._issuable())

    def test_02_damaged_refusals_listed(self):
        unit = self._issued()
        self._receive(unit, 'damaged')
        with self.assertRaisesRegex(UserError, 'assessment must be approved'):
            self._close(unit)
        unit.with_user(self.coordinator).write({'assessment_notes': 'Dent', 'charge_amount': 500})
        unit.with_user(self.coordinator).action_warranty_backup_submit_assessment()
        self._decide(unit, 500)
        with self.assertRaises(UserError) as error:
            self._close(unit)
        message = str(error.exception)
        self.assertIn('Financial Recovery is Quotation', message)
        self.assertIn('Scrap serial BC-01', message)
        # B7: Close of a Damaged unit confirms the physical state: Inventory users only.
        with self.assertRaises(AccessError):
            self._close(unit, user=self.helpdesk_only)

    def test_03_damaged_charge_paid_then_scrapped(self):
        unit = self._damaged(charge=2500)
        invoice = self._invoice(unit)
        self._scrap(self.inspection)
        with self.assertRaisesRegex(UserError, 'Financial Recovery is Invoiced'):
            self._close(unit)
        self._pay(invoice)
        unit.invalidate_recordset(['charge_status'])
        self.assertEqual(unit.charge_status, 'paid')
        self._close(unit)
        self.assertEqual(unit.state, 'closed')

    def test_04_damaged_restored_back_to_service(self):
        unit = self._damaged()
        with self.assertRaisesRegex(UserError, 'Restored Condition'):
            unit.with_user(self.coordinator).action_warranty_backup_confirm_restored()
        with self.assertRaises(AccessError):
            unit.with_user(self.helpdesk_only).action_warranty_backup_confirm_restored()
        unit.with_user(self.coordinator).write({'restored_condition': 'good',
                                                'restored_note': 'Panel replaced, tested'})
        unit.with_user(self.coordinator).action_warranty_backup_confirm_restored()
        self.assertTrue(unit.restored_date)
        with self.assertRaisesRegex(UserError, 'before Confirm Restored'):
            unit.with_user(self.coordinator).write({'restored_note': 'changed'})
        with self.assertRaisesRegex(UserError, 'once'):
            unit.with_user(self.coordinator).action_warranty_backup_confirm_restored()
        picking = self.env['stock.picking'].browse(
            unit.with_user(self.coordinator).action_warranty_backup_restock()['res_id'])
        # The restock transfer is open: Close lists it.
        with self.assertRaisesRegex(UserError, 'not validated yet'):
            self._close(unit)
        self._validate(picking)
        self._close(unit)
        self.assertEqual((unit.state, unit.disposal_type), ('closed', 'restored'))
        self.assertTrue(self._issuable(), 'A confirmed restoration may be issued again.')

    def test_05_damaged_credit_note_or_cancelled_not_closable(self):
        unit = self._damaged(charge=1000)
        invoice = self._invoice(unit)
        invoice._reverse_moves(cancel=True)
        self._scrap(self.inspection)
        unit.invalidate_recordset(['charge_status'])
        self.assertEqual(unit.charge_status, 'credited')
        with self.assertRaisesRegex(UserError, 'write-off rule'):
            self._close(unit)
        other = self._damaged(charge=1000, lot=self.lot2)
        other.sudo().charge_order_id._action_cancel()
        self._scrap(self.inspection, lot=self.lot2)
        with self.assertRaisesRegex(UserError, 'Quotation Cancelled'):
            self._close(other)

    def test_06_damaged_scrap_elsewhere_refused(self):
        """Scrapped from another location than Returned-Inspection: not the verified path."""
        unit = self._damaged()
        Quant = self.env['stock.quant']
        Quant._update_available_quantity(self.backup_product, self.inspection, -1, lot_id=self.lot)
        Quant._update_available_quantity(self.backup_product, self.stock, 1, lot_id=self.lot)
        self._scrap(self.stock)
        with self.assertRaisesRegex(UserError, 'Scrap serial BC-01'):
            self._close(unit)

    # ------------------------------------------------------------------ Lost
    def test_10_lost_scrapped(self):
        unit = self._lost()
        with self.assertRaisesRegex(UserError, 'count it missing'):
            self._close(unit)
        self._scrap(self.loan)
        self._close(unit)
        self.assertEqual((unit.state, unit.disposal_type), ('closed', 'scrap'))
        # B5e: a manual stock correction into Backup Stock never makes it issuable.
        self.env['stock.quant']._update_available_quantity(self.backup_product, self.backup_stock,
                                                           1, lot_id=self.lot)
        self.assertFalse(self._issuable())
        with self.assertRaisesRegex(ValidationError, 'written off'):
            self.env['warranty.backup.unit'].with_user(self.coordinator).create({
                'ticket_id': self.ticket.id, 'partner_id': self.partner.id,
                'product_id': self.backup_product.id, 'lot_id': self.lot.id,
                'expected_return_date': fields.Date.today() + timedelta(days=7)})
        # L6: a Closed Lost unit cannot be recorded as found (Part 9).
        with self.assertRaisesRegex(UserError, 'once'):
            unit.with_user(self.approver).action_warranty_backup_record_found()

    def test_11_lost_counted_missing(self):
        unit = self._lost()
        before = self.env['account.move'].search_count([])
        self._count(self.loan, 0)
        self._close(unit)
        self.assertEqual((unit.state, unit.disposal_type), ('closed', 'missing'))
        self.assertTrue(unit.disposal_move_line_id.is_inventory)
        self.assertEqual(self.env['account.move'].search_count([]), before)
        self.assertFalse(self._issuable())

    def test_12_lost_charge_must_be_paid(self):
        unit = self._lost(charge=3000)
        self._scrap(self.loan)
        with self.assertRaisesRegex(UserError, 'Financial Recovery is Quotation'):
            self._close(unit)
        self._pay(self._invoice(unit))
        self._close(unit)
        self.assertEqual(unit.state, 'closed')

    def test_13_lost_pending_approval_not_closable(self):
        unit = self._issued()
        unit.with_user(self.coordinator).write({'assessment_notes': 'Lost'})
        unit.with_user(self.coordinator).action_warranty_backup_report_lost()
        self.assertEqual((unit.state, unit.assessment_state), ('issued', 'to_approve'))
        with self.assertRaisesRegex(UserError, 'Only Returned, Damaged or Lost'):
            self._close(unit)
        with self.assertRaisesRegex(UserError, 'loss report waiting for approval'):
            unit.with_user(self.coordinator).action_warranty_backup_return()

    # ------------------------------------------------------------------ Lost -> Found
    def test_20_found_before_write_off_good(self):
        unit = self._lost()
        with self.assertRaisesRegex(UserError, 'Record Found'):
            unit.with_user(self.coordinator).action_warranty_backup_return()
        with self.assertRaises(AccessError):
            unit.with_user(self.coordinator).action_warranty_backup_record_found()
        with self.assertRaisesRegex(UserError, 'Found Note'):
            unit.with_user(self.approver).action_warranty_backup_record_found()
        unit.with_user(self.coordinator).write({'found_note': 'Found at the customer site'})
        unit.with_user(self.approver).action_warranty_backup_record_found()
        self.assertEqual(unit.state, 'lost')
        with self.assertRaisesRegex(UserError, 'once'):
            unit.with_user(self.approver).action_warranty_backup_record_found()
        with self.assertRaisesRegex(UserError, 'receive it'):
            self._close(unit)
        self._receive(unit, 'good')
        self.assertEqual(unit.state, 'returned')
        self.assertEqual((unit.assessment_type, unit.assessment_state), ('loss', 'approved'))
        picking = self.env['stock.picking'].browse(
            unit.with_user(self.coordinator).action_warranty_backup_restock()['res_id'])
        self._validate(picking)
        self._close(unit)
        self.assertEqual((unit.state, unit.disposal_type), ('closed', 'stock'))
        self.assertTrue(self._issuable(), 'Recovered and back in stock: issuable.')

    def test_21_found_after_scrap_needs_stock_correction(self):
        unit = self._lost()
        scrap = self._scrap(self.loan)
        unit.with_user(self.coordinator).write({'found_note': 'Found in the warehouse'})
        with self.assertRaisesRegex(UserError, 'written off'):
            unit.with_user(self.approver).action_warranty_backup_record_found()
        # A count alone does not remove the scrap: still written off.
        self._count(self.loan, 1)
        with self.assertRaisesRegex(UserError, 'written off'):
            unit.with_user(self.approver).action_warranty_backup_record_found()
        self._count(self.loan, 0)
        self._transfer_out_of_scrap(scrap, self.loan)
        unit.with_user(self.approver).action_warranty_backup_record_found()
        self._receive(unit, 'damaged')
        self.assertEqual(unit.state, 'damaged')
        # B5d: one assessment; no second damage charge.
        with self.assertRaisesRegex(UserError, 'cannot be submitted'):
            unit.with_user(self.coordinator).action_warranty_backup_submit_assessment()
        self.assertEqual((unit.assessment_type, unit.charge_amount), ('loss', 0))
        self._scrap(self.inspection)
        self._close(unit)
        self.assertEqual((unit.state, unit.disposal_type), ('closed', 'scrap'))

    def test_22_found_after_missing_count(self):
        unit = self._lost()
        self._count(self.loan, 0)
        unit.with_user(self.coordinator).write({'found_note': 'Found'})
        with self.assertRaisesRegex(UserError, 'written off'):
            unit.with_user(self.approver).action_warranty_backup_record_found()
        self._count(self.loan, 1)
        unit.with_user(self.approver).action_warranty_backup_record_found()
        self.assertTrue(unit.found_date)

    def test_23_recovered_credit_note_must_be_settled(self):
        unit = self._lost(charge=4000)
        invoice = self._invoice(unit)
        unit.with_user(self.coordinator).write({'found_note': 'Found'})
        unit.with_user(self.approver).action_warranty_backup_record_found()
        self._receive(unit, 'good')
        picking = self.env['stock.picking'].browse(
            unit.with_user(self.coordinator).action_warranty_backup_restock()['res_id'])
        self._validate(picking)
        # A partial credit note (posted, reconciled with the invoice by Odoo) leaves the rest of
        # the invoice open: not a valid correction yet.
        refund = invoice._reverse_moves()
        refund.invoice_line_ids.price_unit = 1000
        refund.action_post()
        unit.invalidate_recordset(['charge_status'])
        self.assertEqual(unit.charge_status, 'credited')
        self.assertTrue(refund.currency_id.is_zero(refund.amount_residual))
        self.assertFalse(invoice.currency_id.is_zero(invoice.amount_residual))
        with self.assertRaisesRegex(UserError, 'not settled'):
            self._close(unit)
        # The remainder paid: every document settled.
        self._pay(invoice)
        self._close(unit)
        self.assertEqual(unit.state, 'closed')

    def test_24_recovered_return_checks(self):
        unit = self._lost()
        unit.with_user(self.coordinator).write({'found_note': 'Found'})
        unit.with_user(self.approver).action_warranty_backup_record_found()
        unit.with_user(self.coordinator).write({'return_condition': 'good'})
        first = unit.with_user(self.coordinator).action_warranty_backup_return()['res_id']
        self.assertEqual(unit.with_user(self.coordinator).action_warranty_backup_return()['res_id'],
                         first, 'No duplicate recovery transfer.')
        picking = unit.return_picking_id
        self.assertEqual((picking.location_id, picking.location_dest_id), (self.loan, self.inspection))
        Quant = self.env['stock.quant']
        Quant._update_available_quantity(self.backup_product, self.loan, 1, lot_id=self.lot2)
        picking.action_assign()
        picking.move_line_ids.lot_id = self.lot2
        picking.move_ids.picked = True
        with self.assertRaisesRegex(UserError, 'must move exactly one'):
            picking.with_context(skip_backorder=True).button_validate()

    def test_30_good_return_unchanged(self):
        """The UAT-tested Good path: Return to Backup Stock, Close; no assessment needed and no
        Inventory-user check added."""
        unit = self._issued()
        self._receive(unit, 'good')
        picking = self.env['stock.picking'].browse(
            unit.with_user(self.coordinator).action_warranty_backup_restock()['res_id'])
        self._validate(picking)
        self._close(unit)
        self.assertEqual((unit.state, unit.disposal_type), ('closed', 'stock'))
        self.assertTrue(self._issuable())
