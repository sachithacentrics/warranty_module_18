from datetime import timedelta

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged
from odoo.tools.safe_eval import safe_eval

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_repair', 'warranty_backup_restock')
class TestBackupRestock(ReplacementCommon):
    """Return to Backup Stock (Figure 6): a standard Internal Transfer Returned-Inspection ->
    Backup Stock of the backup serial, validated by the user; Close stays manual (D-R1) and keeps
    its stock check; the warehouse's existing Internal Transfers type is used (D-R2)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.helpdesk_only = cls._user('rs_helpdesk', 'helpdesk.group_helpdesk_user')
        cls.stock_only = cls._user('rs_stock', 'stock.group_stock_user')
        cls.approver = cls._user('rs_approver', 'helpdesk.group_helpdesk_user')
        physical = cls.env.ref('stock.stock_location_locations')
        locations = {name: cls.env['stock.location'].create({
            'name': name, 'usage': 'internal', 'company_id': cls.company.id,
            'location_id': physical.id}) for name in ('RS Backup Stock', 'RS Loan', 'RS Inspection')}
        cls.backup_stock = locations['RS Backup Stock']
        cls.inspection = locations['RS Inspection']
        issue_type, return_type = (cls.env['stock.picking.type'].create({
            'name': name, 'code': 'internal', 'sequence_code': code, 'company_id': cls.company.id,
            'default_location_src_id': source.id, 'default_location_dest_id': destination.id,
        }) for name, code, source, destination in (
            ('RS Backup Issue', 'RSBI', cls.backup_stock, locations['RS Loan']),
            ('RS Backup Return', 'RSBR', locations['RS Loan'], cls.inspection)))
        cls.company.write({'warranty_backup_issue_type_id': issue_type.id,
                           'warranty_backup_return_type_id': return_type.id,
                           'warranty_backup_approver_user_ids': [Command.set(cls.approver.ids)]})
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)])
        assert len(cls.warehouse) == 1, cls.warehouse
        cls.internal_type = cls.warehouse.int_type_id
        cls.internal_type.active = True
        cls.backup_product = cls.env['product.product'].create({
            'name': 'RS Backup AC', 'type': 'consu', 'is_storable': True, 'tracking': 'serial'})
        cls.lot, cls.other_lot = (cls.env['stock.lot'].create({
            'name': name, 'product_id': cls.backup_product.id}) for name in ('RS-BK-01', 'RS-BK-02'))
        for lot in (cls.lot, cls.other_lot):
            cls.env['stock.quant']._update_available_quantity(
                cls.backup_product, cls.backup_stock, 1, lot_id=lot)

    def setUp(self):
        super().setUp()
        self.case = self._eligible_case(self._card(self.single).unit_warranty_ids.serial_ids)
        self.ticket = self.case.helpdesk_ticket_id

    # ------------------------------------------------------------------ helpers
    def _returned(self, condition='good', lot=None):
        """A backup unit issued, then received in Returned-Inspection with `condition`."""
        unit = self.env['warranty.backup.unit'].with_user(self.coordinator).create({
            'ticket_id': self.ticket.id, 'partner_id': self.partner.id,
            'warranty_case_id': self.case.id, 'product_id': self.backup_product.id,
            'lot_id': (lot or self.lot).id, 'issue_condition': 'good',
            'expected_return_date': fields.Date.today() + timedelta(days=7)})
        unit.action_warranty_backup_issue()
        self._validate(unit.issue_picking_id)
        unit.return_condition = condition
        unit.action_warranty_backup_return()
        self._validate(unit.return_picking_id)
        self.assertEqual(unit.state, 'damaged' if condition == 'damaged' else 'returned')
        return unit

    def _restock(self, unit, user=None):
        action = unit.with_user(user or self.coordinator).action_warranty_backup_restock()
        self.assertEqual(action['res_model'], 'stock.picking')
        return self.env['stock.picking'].browse(action['res_id'])

    def _manual_transfer(self, destination, lot=None):
        """An internal transfer entered by hand in Inventory, reserved, not validated."""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.internal_type.id, 'location_id': self.inspection.id,
            'location_dest_id': destination.id,
            'move_ids': [Command.create({
                'name': 'manual', 'product_id': self.backup_product.id, 'product_uom_qty': 1,
                'product_uom': self.backup_product.uom_id.id, 'location_id': self.inspection.id,
                'location_dest_id': destination.id})]})
        picking.action_confirm()
        picking.move_ids._do_unreserve()
        picking.move_ids._update_reserved_quantity(1.0, self.inspection, lot_id=lot or self.lot,
                                                   strict=False)
        picking.move_ids._recompute_state()
        self.assertEqual(picking.move_line_ids.lot_id, lot or self.lot)
        return picking

    def _move(self, location_from, location_to, lot=None):
        Quant = self.env['stock.quant']
        Quant._update_available_quantity(self.backup_product, location_from, -1,
                                         lot_id=lot or self.lot)
        Quant._update_available_quantity(self.backup_product, location_to, 1,
                                         lot_id=lot or self.lot)

    def _invisible(self, **values):
        view = self.env.ref('warranty_management_repair.warranty_backup_unit_view_form')
        arch = etree.fromstring(self.env['warranty.backup.unit'].get_view(view.id, 'form')['arch'])
        node = arch.xpath("//header//button[@name='action_warranty_backup_restock']")[0]
        # Figure 6 C2: the expression also reads the restoration / recovery dates.
        return bool(safe_eval(node.get('invisible'),
                              dict({'found_date': False, 'restored_date': False}, **values)))

    def _todos(self, unit):
        return unit.sudo().activity_ids.mapped('summary')

    # ------------------------------------------------------------------ tests
    def test_01_good_return_restock_validate_close(self):
        unit = self._returned()
        self.assertEqual(unit.asset_status, 'inspection')
        with self.assertRaisesRegex(UserError, 'not back in'):
            unit.with_user(self.coordinator).action_warranty_backup_close()
        pickings = self.env['stock.picking'].search_count([])
        picking = self._restock(unit)
        self.assertEqual(self.env['stock.picking'].search_count([]), pickings + 1)
        self.assertEqual(unit.restock_picking_id, picking)
        self.assertEqual((picking.picking_type_id, picking.company_id, picking.origin),
                         (self.internal_type, self.company, unit.name))
        self.assertEqual((picking.location_id, picking.location_dest_id),
                         (self.inspection, self.backup_stock))
        self.assertEqual((picking.move_ids.product_id, picking.move_ids.product_uom_qty),
                         (self.backup_product, 1))
        self.assertEqual(picking.state, 'assigned')
        self.assertEqual((picking.move_line_ids.lot_id, picking.move_line_ids.quantity),
                         (self.lot, 1))
        self.assertEqual((picking.move_line_ids.location_id, picking.move_line_ids.location_dest_id),
                         (self.inspection, self.backup_stock))
        self.assertIn(picking.name, unit.sudo().message_ids.mapped('body')[0])
        # Not validated: Close still refused; the same transfer is opened again.
        with self.assertRaisesRegex(UserError, 'not back in'):
            unit.with_user(self.coordinator).action_warranty_backup_close()
        self.assertEqual(self._restock(unit), picking)
        self.assertEqual(self.env['stock.picking'].search_count([]), pickings + 1)
        # The user validates it; the unit is not closed automatically (D-R1).
        self._validate(picking)
        self.assertEqual(unit.state, 'returned')
        unit.invalidate_recordset(['asset_status'])
        self.assertEqual(unit.asset_status, 'backup_stock')
        self.assertIn('Backup Unit %s: close' % unit.name, self._todos(unit))
        for record in (unit, self.ticket, self.case):
            with self.subTest(history=record._name):
                self.assertTrue(any('returned to Backup Stock with %s' % picking.name in body
                                    for body in record.sudo().message_ids.mapped('body')))
        with self.assertRaisesRegex(UserError, 'use Close'):
            unit.with_user(self.coordinator).action_warranty_backup_restock()
        unit.with_user(self.coordinator).action_warranty_backup_close()
        self.assertEqual(unit.state, 'closed')
        self.assertFalse(self._todos(unit))
        self.assertEqual(unit.restock_picking_id, picking, 'The reference stays on the record.')
        # The serial can be issued again.
        new = self.env['warranty.backup.unit'].with_user(self.coordinator).new({
            'ticket_id': self.ticket.id, 'product_id': self.backup_product.id})
        self.assertIn(self.lot.id, new.available_lot_ids._origin.ids)

    def test_02_button_visibility(self):
        base = {'state': 'returned', 'return_condition': 'good', 'assessment_state': 'none',
                'asset_status': 'inspection'}
        self.assertFalse(self._invisible(**base))
        for change in ({'state': state} for state in (
                'draft', 'issued', 'overdue', 'damaged', 'lost', 'closed')):
            with self.subTest(**change):
                self.assertTrue(self._invisible(**dict(base, **change)))
        # C3 (Figure 6): Minor Scratch gets the button too.
        self.assertFalse(self._invisible(**dict(base, return_condition='minor_scratch')))
        for change in ({'return_condition': 'damaged'},
                       {'assessment_state': 'to_approve'}, {'assessment_state': 'approved'},
                       {'asset_status': 'backup_stock'}):
            with self.subTest(**change):
                self.assertTrue(self._invisible(**dict(base, **change)))
        view = self.env.ref('warranty_management_repair.warranty_backup_unit_view_form')
        node = etree.fromstring(view.arch).xpath(
            "//button[@name='action_warranty_backup_restock']")[0]
        self.assertEqual(node.get('groups'), 'stock.group_stock_user')

    def test_03_permitted_users(self):
        unit = self._returned()
        for user in (self.helpdesk_only, self.outsider):
            with self.subTest(user=user.login), self.assertRaises(AccessError):
                unit.with_user(user).action_warranty_backup_restock()
        self.assertFalse(unit.restock_picking_id)
        # An Inventory user without Helpdesk rights may create and validate it.
        picking = self._restock(unit, user=self.stock_only)
        self.assertEqual(unit.restock_picking_id, picking)
        # The reference is written only by the action.
        with self.assertRaisesRegex(UserError, 'set by its actions'):
            unit.with_user(self.coordinator).write({'restock_picking_id': False})

    def test_04_wrong_serial_or_location_refused(self):
        unit = self._returned()
        picking = self._restock(unit)
        line = picking.move_line_ids
        # Another serial of the same product in Returned-Inspection.
        self._move(self.backup_stock, self.inspection, lot=self.other_lot)
        line.lot_id = self.other_lot
        picking.move_ids.picked = True
        with self.assertRaisesRegex(UserError, 'must move exactly one'):
            picking.with_context(skip_backorder=True).button_validate()
        line.lot_id = self.lot
        line.location_dest_id = self.stock
        with self.assertRaisesRegex(UserError, 'must move exactly one'):
            picking.with_context(skip_backorder=True).button_validate()
        line.location_dest_id = self.backup_stock
        self._validate(picking)
        self.assertEqual(picking.state, 'done')
        # Standard Return of the transfer: refused, as for the other backup transfers.
        wizard = Form(self.env['stock.return.picking'].with_context(
            active_id=picking.id, active_ids=picking.ids, active_model='stock.picking'))
        wizard = wizard.save()
        with self.assertRaisesRegex(UserError, 'backup unit transfer'):
            wizard.action_create_returns()

    def test_05_pending_and_duplicate_transfers(self):
        unit = self._returned()
        # One unlinked manual transfer of exactly this unit: opened, never linked.
        manual = self._manual_transfer(self.backup_stock)
        self.assertEqual(self._restock(unit), manual)
        self.assertFalse(unit.restock_picking_id)
        # Another pending transfer of the serial elsewhere: none is chosen.
        manual.action_cancel()
        elsewhere = self._manual_transfer(self.stock)
        with self.assertRaisesRegex(UserError, elsewhere.name):
            unit.with_user(self.coordinator).action_warranty_backup_restock()
        elsewhere.action_cancel()
        # A cancelled linked transfer is replaced, never two open ones.
        picking = self._restock(unit)
        picking.action_cancel()
        second = self._restock(unit)
        self.assertNotEqual(second, picking)
        self.assertEqual(unit.restock_picking_id, second)
        self.assertEqual(self._restock(unit), second)

    def test_06_manual_path_still_closes(self):
        """The serial already moved to Backup Stock by hand (as in UAT): no transfer, Close."""
        unit = self._returned()
        self._move(self.inspection, self.backup_stock)
        with self.assertRaisesRegex(UserError, 'already in'):
            unit.with_user(self.coordinator).action_warranty_backup_restock()
        self.assertFalse(unit.restock_picking_id)
        unit.with_user(self.coordinator).action_warranty_backup_close()
        self.assertEqual(unit.state, 'closed')

    def test_07_minor_scratch_damaged_lost_unchanged(self):
        # Minor Scratch (C3): Return to Backup Stock, validate, Close.
        scratched = self._returned('minor_scratch')
        self.assertIn('Backup Unit %s: inspect and close' % scratched.name, self._todos(scratched))
        picking = self._restock(scratched)
        self.assertEqual((picking.location_id, picking.location_dest_id),
                         (self.inspection, self.backup_stock))
        self._validate(picking)
        scratched.with_user(self.coordinator).action_warranty_backup_close()
        self.assertEqual(scratched.state, 'closed')
        # Damaged: refused; the assessment path is unchanged and Close stays refused.
        damaged = self._returned('damaged', lot=self.other_lot)
        with self.assertRaisesRegex(UserError, 'Minor Scratch condition'):
            damaged.with_user(self.coordinator).action_warranty_backup_restock()
        # Figure 6 C2: Damaged closes only after approval, settlement and disposition.
        with self.assertRaisesRegex(UserError, 'assessment must be approved'):
            damaged.with_user(self.coordinator).action_warranty_backup_close()
        self.assertIn('Backup Unit %s: submit the damage assessment' % damaged.name,
                      self._todos(damaged))

    def test_08_assessment_after_restock_blocks_validation(self):
        """Damage found during the inspection, after the transfer was created: the transfer
        cannot be validated; the assessment rules are unchanged."""
        unit = self._returned()
        picking = self._restock(unit)
        unit.with_user(self.coordinator).write({'assessment_notes': 'Cracked panel',
                                                'charge_amount': 0})
        unit.with_user(self.coordinator).action_warranty_backup_submit_assessment()
        self.assertEqual((unit.state, unit.assessment_state), ('damaged', 'to_approve'))
        with self.assertRaisesRegex(UserError, 'no longer Returned in Good'):
            self._validate(picking)
        with self.assertRaisesRegex(UserError, 'Minor Scratch condition'):
            unit.with_user(self.coordinator).action_warranty_backup_restock()

    def test_09_lost_unit_refused(self):
        unit = self.env['warranty.backup.unit'].with_user(self.coordinator).create({
            'ticket_id': self.ticket.id, 'partner_id': self.partner.id,
            'product_id': self.backup_product.id,
            'lot_id': self.lot.id, 'issue_condition': 'good',
            'expected_return_date': fields.Date.today() + timedelta(days=7)})
        unit.action_warranty_backup_issue()
        self._validate(unit.issue_picking_id)
        unit.with_user(self.coordinator).write({'assessment_notes': 'Lost on site'})
        unit.with_user(self.coordinator).action_warranty_backup_report_lost()
        unit.with_user(self.approver).write({'assessment_decision_note': 'No charge'})
        unit.with_user(self.approver).action_warranty_backup_approve_assessment()
        self.assertEqual(unit.state, 'lost')
        with self.assertRaisesRegex(UserError, 'Minor Scratch condition'):
            unit.with_user(self.coordinator).action_warranty_backup_restock()

    def test_10_multi_company(self):
        unit = self._returned()
        other = self.env['res.company'].create({'name': 'RS Other Company'})
        self.assertTrue(self.env['stock.warehouse'].search([('company_id', '=', other.id)]))
        other_user = self.env['res.users'].create({
            'name': 'rs_other', 'login': 'rs_other', 'company_id': other.id,
            'company_ids': [Command.set(other.ids)],
            'groups_id': [Command.set((self.env.ref('base.group_user')
                                       | self.env.ref('stock.group_stock_user')).ids)]})
        with self.assertRaises(AccessError):
            unit.with_user(other_user).action_warranty_backup_restock()
        # The company's own warehouse type, not the other company's.
        picking = self._restock(unit)
        self.assertEqual(picking.picking_type_id.company_id, self.company)
        self.assertEqual(picking.company_id, self.company)
        # A pending transfer of another company is never proposed.
        self.assertEqual(unit._warranty_backup_pending_transfers()[0], self.env['stock.picking'])

    def test_11_inactive_internal_type_refused(self):
        unit = self._returned()
        self.internal_type.active = False
        with self.assertRaisesRegex(UserError, 'Internal Transfers'):
            unit.with_user(self.coordinator).action_warranty_backup_restock()
        self.assertFalse(unit.restock_picking_id)
