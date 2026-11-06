from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_replacement', 'warranty_replacement_component')
class TestComponentReplacement(ReplacementCommon):
    """Part 7 Stage 3 Phase 4: Manager / GM approval, the existing Material Request, defective part
    return and part history. Parent serial, card, unit and dates stay."""

    def setUp(self):
        super().setUp()
        self.company.warranty_replacement_gm_user_ids = self.gm
        self.part = self.env['product.product'].create({
            'name': 'WR PCB', 'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'standard_price': 500.0})
        self.loose_part = self.env['product.product'].create({
            'name': 'WR Filter', 'type': 'consu', 'is_storable': True, 'standard_price': 50.0})
        Lot = self.env['stock.lot']
        self.old_part = Lot.create({'name': 'PCB-OLD', 'product_id': self.part.id})
        self.new_part = Lot.create({'name': 'PCB-NEW', 'product_id': self.part.id})
        self.card = self._card(self.single)
        self.unit = self.card.unit_warranty_ids
        self.parent = self.unit.serial_ids
        self.case = self._eligible_case(self.parent)
        self.assertEqual(self.case.eligibility_result, 'eligible', self.case.eligibility_reason)
        self._approved_state(self.case)

    def _part_request(self, *lines):
        return self.env['warranty.replacement'].with_user(self.coordinator).create({
            'warranty_case_id': self.case.id, 'replacement_type': 'component',
            'reason': 'pcb_failure', 'date_policy': 'continue_original',
            'component_line_ids': [(0, 0, line) for line in lines]})

    def _line(self, **vals):
        return dict({'product_id': self.part.id, 'qty': 1.0, 'old_lot_id': self.old_part.id}, **vals)

    def _approved(self, *lines):
        replacement = self._part_request(*(lines or (self._line(),)))
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        return replacement

    def _used_material_line(self, product=None, lots=None, qty=1.0):
        """The Material Request line of the case, with its usage recorded."""
        product = product or self.part
        employee = self.env['hr.employee'].create({
            'name': 'WR Employee', 'department_id': self.env['hr.department'].create(
                {'name': 'WR Department'}).id})
        request = self.env['material.purchase.requisition'].create({
            'employee_id': employee.id, 'department_id': employee.department_id.id,
            'warranty_case_id': self.case.id,
            'requisition_line_ids': [(0, 0, {'product_id': product.id, 'description': product.name,
                                             'qty': qty, 'uom': product.uom_id.id})]})
        line = request.requisition_line_ids
        self.env['warranty.mrf.consumption'].sudo().create({
            'line_id': line.id, 'kind': 'used', 'qty': qty,
            'lot_ids': [(6, 0, lots.ids if lots else [])]})
        self.assertEqual(line.used_qty, qty)
        return line

    def test_01_full_flow(self):
        names = (self.card.name, self.unit.name)
        dates = (self.unit.start_date, self.unit.end_date)
        pickings = self.env['stock.picking'].search_count([])
        replacement = self._part_request(self._line())
        self.assertEqual(replacement.date_policy, 'continue_original')
        replacement.action_warranty_replacement_submit()
        record = replacement.sudo()
        line = record.component_line_ids
        self.assertEqual(replacement.state, 'submitted')
        self.assertFalse(replacement.finance_required)
        self.assertFalse(replacement.old_serial_id)
        self.assertEqual(self.env['stock.picking'].search_count([]), pickings, 'no transfer yet')
        todo = record.activity_ids.filtered(lambda activity: 'approval needed' in activity.summary)
        self.assertIn('Manager / GM', todo.summary)
        self.assertEqual(todo.user_id, self.gm)
        self.assertFalse(replacement.can_approve, 'not the requester')

        replacement.with_user(self.gm).action_warranty_replacement_approve()
        self.assertEqual(replacement.state, 'approved')
        self.assertEqual(replacement.gm_approved_by_id, self.gm)
        self.assertFalse(record.delivery_picking_id, 'the Material Request issues the part')
        self.assertFalse(replacement.transfers_missing)
        self.assertEqual(self.env['stock.picking'].search_count([]), pickings + 1)
        self.assertEqual(line.return_picking_id.move_ids.product_id, self.part)
        self.assertEqual(line.return_picking_id.move_line_ids.lot_id, self.old_part)
        self.assertEqual(line.return_picking_id.location_dest_id, self.return_location)

        with self.assertRaisesRegex(UserError, 'link its Material Request line'):
            replacement.action_warranty_replacement_complete_component()
        material = self._used_material_line(lots=self.new_part)
        line.with_user(self.coordinator).write({'mrf_line_id': material.id})
        self.assertEqual(line.used_qty, 1.0)
        self.assertEqual(line.new_lot_ids, self.new_part)
        with self.assertRaisesRegex(UserError, 'validate the return'):
            replacement.action_warranty_replacement_complete_component()
        self._validate(line.return_picking_id)
        self.assertEqual(self.old_part.quant_ids.filtered(lambda q: q.quantity > 0).location_id,
                         self.return_location)

        replacement.action_warranty_replacement_complete_component()
        self.assertEqual(replacement.state, 'done')
        self.assertEqual(self.unit.serial_ids, self.parent)
        self.assertEqual((self.card.name, self.unit.name), names)
        self.assertEqual((self.unit.start_date, self.unit.end_date), dates)
        self.assertFalse(replacement.dates_changed)
        self.assertFalse(replacement.replacement_cost, 'the cost stays on the Material Request')
        self.assertTrue(replacement.updated_card_generated)
        log = self.env['warranty.card.date.log'].search(
            [('card_id', '=', self.card.id), ('event', '=', 'replacement')])
        self.assertEqual(len(log), 1)
        self.assertEqual(self.env['stock.picking'].search_count([]), pickings + 1, 'no delivery')
        self.assertTrue(record.message_ids.filtered(
            lambda message: 'PCB-OLD' in (message.body or '') and 'PCB-NEW' in (message.body or '')))
        self.assertFalse(self.case._warranty_replacement_problems())
        with self.assertRaises(UserError):
            replacement.action_warranty_replacement_complete_component()

    def test_02_request_rules(self):
        empty = self._part_request()
        with self.assertRaisesRegex(UserError, 'Add the components'):
            empty.action_warranty_replacement_submit()
        unknown = self._part_request(self._line(old_lot_id=False))
        with self.assertRaisesRegex(UserError, 'select the old serial'):
            unknown.action_warranty_replacement_submit()
        no_reason = self._part_request(self._line(old_lot_id=False, return_required=False))
        with self.assertRaisesRegex(UserError, 'Reason for No Return'):
            no_reason.action_warranty_replacement_submit()
        two = self._part_request(self._line(qty=2.0))
        with self.assertRaisesRegex(UserError, 'one line per serial'):
            two.action_warranty_replacement_submit()
        with self.assertRaises(ValidationError):
            self._part_request(self._line(old_lot_id=self.parent.id))

    def test_03_no_return_with_a_reason(self):
        pickings = self.env['stock.picking'].search_count([])
        replacement = self._approved(self._line(old_lot_id=False, return_required=False,
                                                no_return_reason='Serial label is burnt'))
        self.assertEqual(self.env['stock.picking'].search_count([]), pickings)
        self.assertFalse(replacement.transfers_missing)
        line = replacement.sudo().component_line_ids
        line.with_user(self.coordinator).write(
            {'mrf_line_id': self._used_material_line(lots=self.new_part).id})
        replacement.action_warranty_replacement_complete_component()
        self.assertEqual(replacement.state, 'done')

    def test_04_untracked_part_and_partial_usage(self):
        replacement = self._approved(dict(product_id=self.loose_part.id, qty=3.0,
                                          old_part_details='Dirty filters'))
        line = replacement.sudo().component_line_ids
        self.assertEqual(line.return_picking_id.move_ids.product_uom_qty, 3.0)
        self._validate(line.return_picking_id)
        line.with_user(self.coordinator).write(
            {'mrf_line_id': self._used_material_line(self.loose_part, qty=2.0).id})
        with self.assertRaisesRegex(UserError, 'recorded as used'):
            replacement.action_warranty_replacement_complete_component()
        self.assertEqual(replacement.state, 'approved')

    def test_05_link_rules(self):
        replacement = self._approved()
        line = replacement.sudo().component_line_ids
        with self.assertRaises(ValidationError):
            line.write({'mrf_line_id': self._used_material_line(self.loose_part).id})
        draft = self._part_request(self._line())
        material = self._used_material_line(lots=self.new_part)
        with self.assertRaisesRegex(UserError, 'linked while the replacement is Approved'):
            draft.component_line_ids.write({'mrf_line_id': material.id})
        line.with_user(self.coordinator).write({'mrf_line_id': material.id})
        with self.assertRaisesRegex(UserError, 'while the request is Draft'):
            line.with_user(self.coordinator).write({'qty': 2.0})
        with self.assertRaisesRegex(UserError, 'created by the replacement'):
            line.with_user(self.coordinator).write({'return_picking_id': False})
        with self.assertRaises(AccessError):
            line.with_user(self.outsider).write({'mrf_line_id': False})

    def test_06_reject(self):
        replacement = self._approved()
        line = replacement.sudo().component_line_ids
        picking = line.return_picking_id
        as_gm = replacement.with_user(self.gm)
        as_gm.write({'rejection_reason': 'Part not at fault'})
        line.with_user(self.coordinator).write(
            {'mrf_line_id': self._used_material_line(lots=self.new_part).id})
        with self.assertRaisesRegex(UserError, 'recorded as used'):
            as_gm.action_warranty_replacement_reject()
        line.with_user(self.coordinator).write({'mrf_line_id': False})
        as_gm.action_warranty_replacement_reject()
        self.assertEqual(replacement.state, 'rejected')
        self.assertEqual(picking.state, 'cancel')
        self.assertEqual(self.unit.serial_ids, self.parent)

    def test_07_kit_unit_keeps_its_serials(self):
        kit_card = self._card(self.kit)
        unit = kit_card.unit_warranty_ids
        serials = (unit.indoor_serial_id, unit.outdoor_serial_id)
        self.case = self._eligible_case(unit.indoor_serial_id)
        self._approved_state(self.case)
        replacement = self._approved()
        line = replacement.sudo().component_line_ids
        self._validate(line.return_picking_id)
        line.with_user(self.coordinator).write(
            {'mrf_line_id': self._used_material_line(lots=self.new_part).id})
        replacement.action_warranty_replacement_complete_component()
        self.assertEqual(replacement.state, 'done')
        self.assertEqual((unit.indoor_serial_id, unit.outdoor_serial_id), serials)

    def test_08_ineligible_case_refused(self):
        self.case.sudo().write({'state': 'eligibility_checked',
                                'eligibility_result': 'out_of_warranty'})
        replacement = self._part_request(self._line())
        with self.assertRaisesRegex(UserError, 'must be Eligible'):
            replacement.action_warranty_replacement_submit()

    def test_09_later_full_replacement_and_serial_guard(self):
        """A Done Component replacement holds no serial rule of the unit."""
        replacement = self._approved()
        line = replacement.sudo().component_line_ids
        self._validate(line.return_picking_id)
        line.with_user(self.coordinator).write(
            {'mrf_line_id': self._used_material_line(lots=self.new_part).id})
        replacement.action_warranty_replacement_complete_component()
        self.company.warranty_replacement_full_finance = 'not_required'
        full = self._request(self.case, 'full', self._lot(self.single, 6))
        full.action_warranty_replacement_submit()
        self.assertEqual(full.state, 'submitted')
