from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.warranty_management_repair.tests.test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_accounting', 'warranty_close_backup')
class TestCloseCaseBackup(ReplacementCommon):
    """Figure 6 (C4): Close Case waits for a backup machine still with the customer; the
    assessment, charge and disposition of a returned unit never block it (SRS 17)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approver = cls._user('cb_approver', 'helpdesk.group_helpdesk_user')
        physical = cls.env.ref('stock.stock_location_locations')
        stock, loan, inspection = (cls.env['stock.location'].create({
            'name': name, 'usage': 'internal', 'company_id': cls.company.id,
            'location_id': physical.id}) for name in ('CB Backup', 'CB Loan', 'CB Inspection'))
        issue_type, return_type = (cls.env['stock.picking.type'].create({
            'name': name, 'code': 'internal', 'sequence_code': code, 'company_id': cls.company.id,
            'default_location_src_id': source.id, 'default_location_dest_id': destination.id,
        }) for name, code, source, destination in (
            ('CB Issue', 'CBI', stock, loan), ('CB Return', 'CBR', loan, inspection)))
        cls.company.write({'warranty_backup_issue_type_id': issue_type.id,
                           'warranty_backup_return_type_id': return_type.id,
                           'warranty_backup_approver_user_ids': [Command.set(cls.approver.ids)]})
        cls.backup_product = cls.env['product.product'].create({
            'name': 'CB Backup AC', 'type': 'consu', 'is_storable': True, 'tracking': 'serial'})
        cls.lot = cls.env['stock.lot'].create({'name': 'CB-01', 'product_id': cls.backup_product.id})
        cls.env['stock.quant']._update_available_quantity(cls.backup_product, stock, 1,
                                                          lot_id=cls.lot)

    def setUp(self):
        super().setUp()
        self.case = self._eligible_case(self._card(self.single).unit_warranty_ids.serial_ids)

    def _blocked(self):
        return [problem for problem in self.case._warranty_close_operation_problems()
                if 'Backup unit' in problem]

    def test_01_backup_custody_blocks_close(self):
        unit = self.env['warranty.backup.unit'].with_user(self.coordinator).create({
            'ticket_id': self.case.helpdesk_ticket_id.id, 'partner_id': self.partner.id,
            'warranty_case_id': self.case.id, 'product_id': self.backup_product.id,
            'lot_id': self.lot.id, 'issue_condition': 'good',
            'expected_return_date': fields.Date.today() + timedelta(days=7)})
        self.assertFalse(self._blocked(), 'A Draft unit without transfer does not block.')
        unit.action_warranty_backup_issue()
        self.assertIn(unit.name, self._blocked()[0], 'Open issue transfer.')
        self._validate(unit.issue_picking_id)
        self.assertEqual(unit.state, 'issued')
        self.assertIn(unit.name, self._blocked()[0])
        unit.sudo()._warranty_backup_marked().write({'state': 'overdue'})
        self.assertTrue(self._blocked())
        unit.sudo()._warranty_backup_marked().write({'state': 'issued'})
        # Returned Damaged, assessment approved with no charge: never blocks (SRS 17).
        unit.return_condition = 'damaged'
        unit.action_warranty_backup_return()
        self._validate(unit.return_picking_id)
        self.assertEqual(unit.state, 'damaged')
        self.assertFalse(self._blocked())
        unit.with_user(self.coordinator).write({'assessment_notes': 'Dent'})
        unit.with_user(self.coordinator).action_warranty_backup_submit_assessment()
        self.assertFalse(self._blocked(), 'Waiting approval does not block either.')

    def test_02_lost_and_found(self):
        """C2 B5f: an approved Lost unit does not block; once found, until it is received, it
        is with the customer again."""
        unit = self.env['warranty.backup.unit'].with_user(self.coordinator).create({
            'ticket_id': self.case.helpdesk_ticket_id.id, 'partner_id': self.partner.id,
            'warranty_case_id': self.case.id, 'product_id': self.backup_product.id,
            'lot_id': self.lot.id, 'issue_condition': 'good',
            'expected_return_date': fields.Date.today() + timedelta(days=7)})
        unit.action_warranty_backup_issue()
        self._validate(unit.issue_picking_id)
        unit.with_user(self.coordinator).write({'assessment_notes': 'Lost'})
        unit.with_user(self.coordinator).action_warranty_backup_report_lost()
        self.assertTrue(self._blocked(), 'A loss waiting approval: still with the customer.')
        unit.with_user(self.approver).write({'assessment_decision_note': 'No charge'})
        unit.with_user(self.approver).action_warranty_backup_approve_assessment()
        self.assertEqual(unit.state, 'lost')
        self.assertFalse(self._blocked())
        unit.with_user(self.coordinator).write({'found_note': 'Found on site'})
        unit.with_user(self.approver).action_warranty_backup_record_found()
        self.assertIn(unit.name, self._blocked()[0])
        unit.return_condition = 'good'
        unit.action_warranty_backup_return()
        self._validate(unit.return_picking_id)
        self.assertEqual(unit.state, 'returned')
        self.assertFalse(self._blocked())
