from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group

from ..models.warranty_replacement import REPLACEMENT_TYPES


class ReplacementCommon(TransactionCase):
    """A confirmed kit card with one unit, delivered IN-01 / OUT-01, and a non-kit card."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'warranty_scope_mode': 'warranty_only',
            'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'delivery',
            'default_warranty_duration': 12,
            'default_warranty_duration_unit': 'months',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Replacement Customer'})
        cls.stock = cls.env.ref('stock.stock_location_stock')
        cls.item = cls.env['warranty.coverage.item'].create({'name': 'WR Standard Service'})
        cls.policy = cls.env['warranty.policy'].create({
            'name': 'WR Policy', 'covered_item_ids': [(6, 0, cls.item.ids)],
            'warranty_duration': 12, 'warranty_duration_unit': 'months'})
        cls.categ = cls.env['product.category'].create({
            'name': 'WR ACs', 'warranty_policy_id': cls.policy.id})
        cls.indoor = cls._component('WR Indoor Unit', 'WRIN')
        cls.outdoor = cls._component('WR Outdoor Unit', 'WROUT')
        cls.kit = cls.env['product.product'].create({
            'name': 'WR Split Kit', 'type': 'consu', 'warranty_applicable': True,
            'invoice_policy': 'order', 'categ_id': cls.categ.id})
        cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.kit.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1,
            'bom_line_ids': [
                (0, 0, {'product_id': cls.indoor.id, 'product_qty': 1,
                        'warranty_component_role': 'indoor'}),
                (0, 0, {'product_id': cls.outdoor.id, 'product_qty': 1,
                        'warranty_component_role': 'outdoor'}),
            ]})
        cls.single = cls._component('WR Single AC', 'WRONE', warranty=True)
        warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.return_location = cls.env['stock.location'].create({
            'name': 'WR Warranty Return', 'usage': 'internal',
            'location_id': cls.env.ref('stock.stock_location_locations').id})
        cls.return_type = cls.env['stock.picking.type'].create({
            'name': 'WR Return', 'code': 'incoming', 'sequence_code': 'WRR',
            'warehouse_id': warehouse.id, 'company_id': cls.company.id,
            'default_location_dest_id': cls.return_location.id})
        cls.delivery_type = cls.env['stock.picking.type'].create({
            'name': 'WR Delivery', 'code': 'outgoing', 'sequence_code': 'WRD',
            'warehouse_id': warehouse.id, 'company_id': cls.company.id,
            'default_location_src_id': cls.stock.id,
            'default_location_dest_id': cls.env.ref('stock.stock_location_customers').id})
        cls.company.write({'warranty_replacement_return_type_id': cls.return_type.id,
                           'warranty_replacement_delivery_type_id': cls.delivery_type.id})
        cls.coordinator = cls._user('wr_coordinator', 'helpdesk.group_helpdesk_user',
                                    'stock.group_stock_user')
        cls.outsider = cls._user('wr_outsider')
        cls.gm = cls._user('wr_gm')
        cls.finance = cls._user('wr_finance')
        cls.team = cls.env['helpdesk.team'].create({'name': 'WR Team'})

    @classmethod
    def _component(cls, name, prefix, warranty=False):
        product = cls.env['product.product'].create({
            'name': name, 'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'warranty_applicable': warranty, 'categ_id': cls.categ.id})
        for index in range(1, 7):
            lot = cls.env['stock.lot'].create({
                'name': '%s-%02d' % (prefix, index), 'product_id': product.id})
            cls.env['stock.quant']._update_available_quantity(product, cls.stock, 1, lot_id=lot)
        return product

    @classmethod
    def _user(cls, login, *groups):
        group_ids = cls.env.ref('base.group_user').ids
        for group in groups:
            group_ids += cls.env.ref(group).ids
        return cls.env['res.users'].create({
            'name': login, 'login': login, 'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)], 'groups_id': [(6, 0, group_ids)]})

    def _card(self, product):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})]})
        confirm_and_group(order, 'per_so')
        picking = order.picking_ids
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        card = order.warranty_card_ids
        self.assertEqual(card.state, 'ready', card.missing_requirements)
        card.action_confirm_warranty()
        self.assertEqual(card.state, 'confirmed')
        return card

    def _eligible_case(self, serial):
        ticket = self.env['helpdesk.ticket'].create({
            'name': 'Replacement ticket', 'team_id': self.team.id, 'is_warranty': True,
            'partner_id': self.partner.id, 'description': '<p>Broken</p>'})
        case = self.env['warranty.case'].create({
            'helpdesk_ticket_id': ticket.id, 'partner_id': self.partner.id,
            'company_id': self.company.id, 'case_type': 'warranty_complaint',
            'serial_id': serial.id, 'requested_item_ids': [(6, 0, self.item.ids)]})
        case.action_check_eligibility()
        return case

    def _approved_state(self, case):
        """The replacement starts from an approved case; the case approval is not under test."""
        case.sudo().write({'state': 'approved'})

    def _request(self, case, kind, new, **vals):
        return self.env['warranty.replacement'].with_user(self.coordinator).create(dict({
            'warranty_case_id': case.id, 'replacement_type': kind, 'new_serial_id': new.id,
            'reason': 'compressor_failure', 'date_policy': 'continue_original'}, **vals))

    def _validate(self, picking):
        self.env.invalidate_all()
        picking.action_assign()
        picking.move_ids.picked = True
        result = picking.with_context(skip_backorder=True).button_validate()
        self.assertIs(result, True, result)

    def _lot(self, product, number):
        prefix = {self.indoor: 'WRIN', self.outdoor: 'WROUT', self.single: 'WRONE'}[product]
        return self.env['stock.lot'].search([('name', '=', '%s-%02d' % (prefix, number))])


@tagged('post_install', '-at_install', 'warranty_replacement')
class TestIndoorOutdoorReplacement(ReplacementCommon):
    """Part 7 Stage 2: mandatory Manager / GM approval, no Finance level (SRS 11.2, Figure 3)."""

    def setUp(self):
        super().setUp()
        self.company.warranty_replacement_gm_user_ids = self.gm
        self.card = self._card(self.kit)
        self.unit = self.card.unit_warranty_ids
        # Delivered 6 months ago, so that Restart gives other dates than the unit's.
        start = fields.Date.today() - relativedelta(months=6)
        end = start + relativedelta(months=12) - relativedelta(days=1)
        self.card._warranty_system_write({'warranty_start_date': start, 'warranty_end_date': end})
        self.unit._warranty_system_write({'start_date': start, 'end_date': end})
        self.old_indoor = self.unit.indoor_serial_id
        self.old_outdoor = self.unit.outdoor_serial_id
        self.new_indoor = self.indoor.env['stock.lot'].search(
            [('product_id', '=', self.indoor.id), ('id', '!=', self.old_indoor.id)], limit=1)
        self.new_outdoor = self.outdoor.env['stock.lot'].search(
            [('product_id', '=', self.outdoor.id), ('id', '!=', self.old_outdoor.id)], limit=1)
        self.case = self._eligible_case(self.old_indoor)
        self.assertEqual(self.case.eligibility_result, 'eligible', self.case.eligibility_reason)
        self._approved_state(self.case)

    def _submit_and_approve(self, replacement):
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()

    def _run(self, replacement):
        self._submit_and_approve(replacement)
        self._validate(replacement.sudo().return_picking_id)
        self._validate(replacement.sudo().delivery_picking_id)

    def _outdoor_case(self):
        case = self._eligible_case(self.unit.outdoor_serial_id)
        self._approved_state(case)
        return case

    def test_01_submit_waits_then_approval_creates_transfers(self):
        """Submit: Submitted, a To-Do, no transfer. Manager / GM approval: Approved, both transfers.
        No Finance level, whatever the Full Product setting says."""
        self.assertFalse(self.company.warranty_replacement_finance_user_ids
                         or self.company.warranty_replacement_full_finance)
        replacement = self._request(self.case, 'indoor', self.new_indoor)
        self.assertEqual(replacement.product_id, self.indoor)
        self.assertEqual(replacement.old_serial_id, self.old_indoor)
        self.assertEqual(replacement.unaffected_serial_id, self.old_outdoor)
        replacement.action_warranty_replacement_submit()
        record = replacement.sudo()
        self.assertEqual(replacement.state, 'submitted')
        self.assertEqual(replacement.requested_by_id, self.coordinator)
        self.assertFalse(replacement.finance_required)
        self.assertFalse(record.return_picking_id | record.delivery_picking_id)
        self.assertEqual(self.env['stock.picking'].search_count([('origin', '=', replacement.name)]), 0)
        todo = record.activity_ids.filtered(lambda activity: 'approval needed' in activity.summary)
        self.assertEqual(todo.user_id, self.gm)
        self.assertIn('Manager / GM', todo.summary)
        self.assertEqual(self.unit.indoor_serial_id, self.old_indoor)
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        self.assertEqual(replacement.state, 'approved')
        self.assertEqual(replacement.gm_approved_by_id, self.gm)
        self.assertTrue(replacement.gm_approved_date)
        self.assertFalse(replacement.finance_approved_by_id)
        self.assertFalse(replacement.with_user(self.gm).can_approve)
        self.assertEqual(record.return_picking_id.move_ids.product_id, self.indoor)
        self.assertEqual(record.return_picking_id.move_line_ids.lot_id, self.old_indoor)
        self.assertEqual(record.delivery_picking_id.move_ids.product_id, self.indoor)
        self.assertEqual(record.delivery_picking_id.move_line_ids.lot_id, self.new_indoor)
        self.assertFalse(record.activity_ids.filtered(
            lambda activity: 'approval' in (activity.summary or '')))
        decision = record.message_ids.filtered(
            lambda message: 'decision Approved' in (message.body or ''))
        self.assertEqual(len(decision), 1)
        self.assertIn(self.gm.name, decision.body)
        with self.assertRaises(UserError):
            replacement.with_user(self.gm).action_warranty_replacement_approve()

    def test_14_who_can_decide(self):
        """Only a Manager / GM approver other than the requester; a Finance approver has no level
        here; both refused decisions leave the request waiting."""
        self.company.warranty_replacement_finance_user_ids = self.finance
        self.company.warranty_replacement_gm_user_ids = self.gm | self.coordinator
        replacement = self._request(self.case, 'indoor', self.new_indoor)
        replacement.action_warranty_replacement_submit()
        for user in (self.coordinator, self.finance, self.outsider):
            as_user = replacement.with_user(user)
            self.assertFalse(as_user.can_approve, user.login)
            self.assertFalse(as_user.can_reject, user.login)
            with self.assertRaises(AccessError):
                as_user.action_warranty_replacement_approve()
            with self.assertRaises(AccessError):
                as_user.action_warranty_replacement_reject()
        self.assertEqual(replacement.state, 'submitted')
        as_gm = replacement.with_user(self.gm)
        self.assertTrue(as_gm.can_approve)
        with self.assertRaises(UserError):
            as_gm.action_warranty_replacement_reject()
        as_gm.write({'rejection_reason': 'Repair is possible'})
        as_gm.action_warranty_replacement_reject()
        self.assertEqual(replacement.state, 'rejected')
        self.assertEqual(replacement.rejected_by_id, self.gm)
        self.assertFalse(replacement.sudo().delivery_picking_id)
        self.assertEqual(self.unit.indoor_serial_id, self.old_indoor)

    def test_15_submit_needs_a_manager(self):
        self.company.warranty_replacement_gm_user_ids = self.coordinator
        replacement = self._request(self.case, 'indoor', self.new_indoor)
        with self.assertRaisesRegex(UserError, 'GM Approvers'):
            replacement.action_warranty_replacement_submit()
        self.assertEqual(replacement.state, 'draft')

    def test_16_request_approved_without_approval_stays_blocked(self):
        """The earlier no-approval version left Approved requests with transfers and no signature
        (UAT WR/000002): no execution; the record stays as it is until an approver rejects it."""
        replacement = self._request(self.case, 'indoor', self.new_indoor)
        replacement.action_warranty_replacement_submit()
        record = replacement.sudo()
        record._warranty_replacement_marked().write({'state': 'approved'})
        record._warranty_replacement_create_transfers()
        self.assertTrue(replacement.approval_missing)
        self.assertFalse(replacement.transfers_missing)
        for picking in (record.return_picking_id, record.delivery_picking_id):
            with self.assertRaisesRegex(UserError, 'without the Manager / GM approval'):
                self._validate(picking)
        spare = self.env['stock.lot'].search([('product_id', '=', self.indoor.id),
                                              ('id', 'not in', (self.new_indoor | self.old_indoor).ids)],
                                             limit=1)
        as_gm = replacement.with_user(self.gm)
        as_gm.write({'recovery_new_serial_id': spare.id, 'recovery_reason': 'Damaged'})
        with self.assertRaisesRegex(UserError, 'without the Manager / GM approval'):
            as_gm.action_warranty_replacement_change_serial()
        with self.assertRaisesRegex(UserError, 'without the Manager / GM approval'):
            replacement.action_warranty_replacement_create_transfers()
        self.assertEqual(replacement.state, 'approved')
        self.assertEqual(self.unit.indoor_serial_id, self.old_indoor)
        as_gm.write({'rejection_reason': 'Created before approval became mandatory'})
        as_gm.action_warranty_replacement_reject()
        self.assertEqual(replacement.state, 'rejected')
        self.assertEqual((record.return_picking_id.state, record.delivery_picking_id.state),
                         ('cancel', 'cancel'))
        self.assertFalse(replacement.gm_approved_by_id)
        self.assertFalse(self.case._warranty_replacement_problems())
        fresh = self._request(self.case, 'indoor', self.new_indoor)
        self._run(fresh)
        self.assertEqual(fresh.state, 'done')
        self.assertEqual(self.unit.indoor_serial_id, self.new_indoor)

    def test_02_indoor_swap_keeps_outdoor(self):
        original = (self.unit.start_date, self.unit.end_date)
        header = (self.card.warranty_start_date, self.card.warranty_end_date)
        names = (self.card.name, self.unit.name)
        replacement = self._request(self.case, 'indoor', self.new_indoor)
        replacement.action_warranty_replacement_submit()
        self.assertEqual(self.unit.indoor_serial_id, self.old_indoor, 'no swap before approval')
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        self.assertEqual(self.unit.indoor_serial_id, self.old_indoor, 'no swap before stock')
        self._validate(replacement.sudo().return_picking_id)
        self.assertEqual(self.unit.indoor_serial_id, self.old_indoor, 'no swap before delivery')
        self._validate(replacement.sudo().delivery_picking_id)
        self.assertEqual(replacement.state, 'done')
        self.assertTrue(replacement.updated_card_generated)
        self.assertEqual((self.unit.indoor_serial_id, self.unit.outdoor_serial_id),
                         (self.new_indoor, self.old_outdoor))
        self.assertEqual(self.unit.serial_ids, self.new_indoor | self.old_outdoor)
        self.assertEqual((self.card.indoor_serial_id, self.card.outdoor_serial_id),
                         (self.new_indoor, self.old_outdoor))
        self.assertEqual((self.card.name, self.unit.name), names)
        self.assertEqual((self.unit.start_date, self.unit.end_date), original)
        self.assertEqual((self.card.warranty_start_date, self.card.warranty_end_date), header)
        self.assertFalse(self.unit.indoor_end_date or self.unit.outdoor_end_date,
                         'Continue Original writes no dates of the serial')
        log = self.card.env['warranty.card.date.log'].search(
            [('card_id', '=', self.card.id), ('event', '=', 'replacement')])
        self.assertEqual(len(log), 1)
        self.assertEqual(self.old_indoor.quant_ids.filtered(lambda q: q.quantity > 0).location_id,
                         self.return_location)
        self.assertEqual(
            self.old_outdoor.quant_ids.filtered(lambda q: q.quantity > 0).location_id.usage,
            'customer')
        sold = self.card.sale_order_line_ids
        self.assertEqual(sold.qty_delivered, 1, 'Sales Order delivered quantity unchanged')
        self.assertTrue(replacement.replacement_cost >= 0)

    def test_03_delivery_needs_the_return_first(self):
        replacement = self._request(self.case, 'indoor', self.new_indoor)
        self._submit_and_approve(replacement)
        with self.assertRaises(UserError):
            self._validate(replacement.sudo().delivery_picking_id)
        self.assertEqual(self.unit.indoor_serial_id, self.old_indoor)

    def test_04_outdoor_swap_keeps_indoor_and_restart_dates(self):
        case = self._outdoor_case()
        original = (self.unit.start_date, self.unit.end_date)
        replacement = self._request(case, 'outdoor', self.new_outdoor, date_policy='restart')
        self._run(replacement)
        self.assertEqual(replacement.state, 'done')
        self.assertEqual((self.unit.indoor_serial_id, self.unit.outdoor_serial_id),
                         (self.old_indoor, self.new_outdoor))
        delivery = replacement.delivery_date
        self.assertEqual(self.unit.outdoor_start_date, delivery)
        self.assertEqual(self.unit.outdoor_end_date,
                         delivery + relativedelta(months=12) - relativedelta(days=1))
        self.assertEqual((self.unit.start_date, self.unit.end_date), original)
        self.assertFalse(self.unit.indoor_start_date or self.unit.indoor_end_date)
        self.assertEqual(self.unit._warranty_role_dates('indoor'), original)
        self.assertEqual(len(self.card._warranty_replacement_serial_date_rows()), 2)

    def test_05_eligibility_is_per_serial(self):
        """The check uses the dates of the case serial; the other serial is not extended."""
        case = self._outdoor_case()
        self._run(self._request(case, 'outdoor', self.new_outdoor, date_policy='restart'))
        today = fields.Date.today()
        old_start = today - relativedelta(years=3)
        self.card._warranty_system_write({'warranty_start_date': old_start,
                                          'warranty_end_date': today - timedelta(days=30)})
        self.unit._warranty_system_write({'start_date': old_start,
                                          'end_date': today - timedelta(days=30)})
        outdoor = self._eligible_case(self.new_outdoor)
        self.assertNotEqual(outdoor.eligibility_result, 'out_of_warranty',
                            outdoor.eligibility_reason)
        indoor = self._eligible_case(self.old_indoor)
        self.assertEqual(indoor.eligibility_result, 'out_of_warranty')

    def test_06_second_replacement_and_kit_rule(self):
        """A replaced serial stays valid for the kit serial rule when the other role changes."""
        self._run(self._request(self.case, 'indoor', self.new_indoor))
        case = self._outdoor_case()
        self._run(self._request(case, 'outdoor', self.new_outdoor))
        self.assertEqual(self.unit.serial_ids, self.new_indoor | self.new_outdoor)
        self.unit._check_kit_serials()

    def test_07_validations(self):
        # Case checked on the indoor serial.
        wrong_role = self._request(self.case, 'outdoor', self.new_outdoor)
        with self.assertRaisesRegex(UserError, 'was checked on serial'):
            wrong_role.action_warranty_replacement_submit()
        self.assertEqual(wrong_role.state, 'draft')
        self.assertFalse(wrong_role.sudo().delivery_picking_id)
        # Component of the other role.
        wrong_product = self._request(self.case, 'indoor', self.new_outdoor)
        with self.assertRaisesRegex(UserError, 'belongs to'):
            wrong_product.action_warranty_replacement_submit()
        # Full Product on a kit.
        full = self._request(self.case, 'full', self.new_indoor)
        with self.assertRaises(UserError):
            full.action_warranty_replacement_submit()
        # Goodwill reason.
        goodwill = self._request(self.case, 'indoor', self.new_indoor, reason='goodwill')
        with self.assertRaises(UserError):
            goodwill.action_warranty_replacement_submit()
        # Serial already on an active warranty.
        taken = self._request(self.case, 'indoor', self.old_outdoor)
        with self.assertRaises(UserError):
            taken.action_warranty_replacement_submit()
        # Not in stock.
        away = self.env['stock.lot'].create({'name': 'WRIN-AWAY', 'product_id': self.indoor.id})
        missing = self._request(self.case, 'indoor', away)
        with self.assertRaisesRegex(UserError, 'not available'):
            missing.action_warranty_replacement_submit()
        # A second open request on the same role.
        first = self._request(self.case, 'indoor', self.new_indoor)
        first.action_warranty_replacement_submit()
        other = self.env['stock.lot'].search([('product_id', '=', self.indoor.id),
                                              ('id', 'not in', (self.new_indoor | self.old_indoor).ids)],
                                             limit=1)
        second = self._request(self.case, 'indoor', other)
        with self.assertRaisesRegex(UserError, 'already has the open replacement'):
            second.action_warranty_replacement_submit()
        self.assertFalse(self.env['stock.picking'].search([('origin', '=', first.name)]))
        first.with_user(self.gm).action_warranty_replacement_approve()
        self.assertEqual(len(self.env['stock.picking'].search([('origin', '=', first.name)])), 2)

    def test_08_manual_date_by_the_approver(self):
        """SRS 11.3: the manager decides the date; the requester cannot write it."""
        manual = fields.Date.today() + relativedelta(years=4)
        replacement = self._request(self.case, 'indoor', self.new_indoor, date_policy='manual')
        with self.assertRaises(UserError):
            replacement.write({'manual_end_date': manual})
        replacement.action_warranty_replacement_submit()
        self.assertEqual(replacement.state, 'submitted')
        with self.assertRaises(UserError):
            replacement.write({'manual_end_date': manual})
        as_gm = replacement.with_user(self.gm)
        with self.assertRaisesRegex(UserError, 'Manual End Date'):
            as_gm.action_warranty_replacement_approve()
        as_gm.write({'manual_end_date': manual, 'manual_date_reason': 'Customer agreement'})
        as_gm.action_warranty_replacement_approve()
        with self.assertRaises(UserError):
            as_gm.write({'manual_end_date': manual + timedelta(days=1)})
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(self.unit.indoor_end_date, manual)
        self.assertFalse(self.unit.outdoor_end_date)

    def test_09_remaining_and_extension_policies(self):
        replacement = self._request(self.case, 'indoor', self.new_indoor,
                                    date_policy='remaining_period')
        self._run(replacement)
        self.assertTrue(replacement.remaining_days > 0)
        self.assertFalse(self.unit.indoor_end_date)
        case = self._outdoor_case()
        extended = self._request(case, 'outdoor', self.new_outdoor, date_policy='fixed_extension',
                                 extension_value=2, extension_unit='months')
        with self.assertRaisesRegex(UserError, 'BA B3'):
            extended.action_warranty_replacement_submit()
        self.company.warranty_replacement_extension_base = 'original_end'
        self._run(extended)
        self.assertEqual(self.unit.outdoor_end_date,
                         self.unit.end_date + relativedelta(months=2))
        self.assertFalse(self.unit.indoor_end_date)

    def test_10_recovery(self):
        requester = self._request(self.case, 'indoor', self.new_indoor)
        self._submit_and_approve(requester)
        record = requester.sudo()
        self._validate(record.return_picking_id)
        self.assertFalse(requester.with_user(self.outsider).can_reject)
        self.assertFalse(requester.can_reject, 'not the requester')
        replacement = requester.with_user(self.gm)
        self.assertTrue(replacement.can_reject)
        # Change New Serial: one open delivery, of the other serial.
        spare = self.env['stock.lot'].search([('product_id', '=', self.indoor.id),
                                              ('id', 'not in', (self.new_indoor | self.old_indoor).ids)],
                                             limit=1)
        first_delivery = record.delivery_picking_id
        replacement.write({'recovery_new_serial_id': spare.id, 'recovery_reason': 'Damaged'})
        replacement.action_warranty_replacement_change_serial()
        self.assertEqual(first_delivery.state, 'cancel')
        self.assertEqual(record.delivery_picking_id.move_line_ids.lot_id, spare)
        self.assertNotEqual(record.delivery_picking_id, first_delivery)
        self.assertFalse(replacement.transfers_missing)
        requester.action_warranty_replacement_create_transfers()
        self.assertEqual(len(self.env['stock.picking'].search([('origin', '=', replacement.name)])), 3)
        # Reject: the validated return stays, nothing swapped, completion waits.
        with self.assertRaises(UserError):
            replacement.action_warranty_replacement_reject()
        replacement.write({'rejection_reason': 'Customer changed their mind'})
        replacement.action_warranty_replacement_reject()
        self.assertEqual(replacement.state, 'rejected')
        self.assertEqual(record.return_picking_id.state, 'done')
        self.assertEqual(record.delivery_picking_id.state, 'cancel')
        self.assertEqual(self.unit.indoor_serial_id, self.old_indoor)
        self.assertTrue(self.case._warranty_replacement_problems())
        with self.assertRaises(AccessError):
            replacement.with_user(self.outsider).action_warranty_replacement_reject()
        with self.assertRaises(AccessError):
            requester.action_warranty_replacement_reject()

    def test_11_direct_edits_refused(self):
        replacement = self._request(self.case, 'indoor', self.new_indoor)
        replacement.action_warranty_replacement_submit()
        with self.assertRaises(UserError):
            self.unit.indoor_serial_id = self.new_indoor
        with self.assertRaises(UserError):
            self.unit.indoor_end_date = fields.Date.today()
        with self.assertRaises(UserError):
            replacement.write({'state': 'done'})

    def test_12_correction_keeps_serial_dates(self):
        case = self._outdoor_case()
        self._run(self._request(case, 'outdoor', self.new_outdoor, date_policy='restart'))
        kept = (self.unit.outdoor_start_date, self.unit.outdoor_end_date)
        start = self.card.warranty_start_date - timedelta(days=10)
        self.card.sudo()._warranty_correct_dates(start, 'Wrong delivery date')
        self.assertEqual((self.unit.outdoor_start_date, self.unit.outdoor_end_date), kept)
        self.assertEqual(self.unit.start_date, start)
        self.assertEqual(self.unit._warranty_role_dates('indoor')[0], start)

    def test_13_pdf_with_serial_dates(self):
        case = self._outdoor_case()
        self._run(self._request(case, 'outdoor', self.new_outdoor, date_policy='restart'))
        report = self.env.ref('warranty_management.report_warranty_card')
        html = self.env['ir.qweb']._render(report.id, {
            'docs': self.card, 'doc_ids': self.card.ids, 'doc_model': 'warranty.card',
            'company': self.company, 'res_company': self.company, 'user': self.env.user})
        html = str(html)
        self.assertIn('Updated Copy after replacement', html)
        self.assertIn(self.new_outdoor.name, html)
        self.assertIn('Component', html)


@tagged('post_install', '-at_install', 'warranty_replacement')
class TestFullProductStillApproved(ReplacementCommon):
    """Stage 1 is unchanged by the Indoor / Outdoor approval."""

    def setUp(self):
        super().setUp()
        self.card = self._card(self.single)
        self.unit = self.card.unit_warranty_ids
        self.old = self.unit.serial_ids
        self.new = self.env['stock.lot'].search([('product_id', '=', self.single.id),
                                                 ('id', '!=', self.old.id)], limit=1)
        self.case = self._eligible_case(self.old)
        self.assertEqual(self.case.eligibility_result, 'eligible', self.case.eligibility_reason)
        self._approved_state(self.case)

    def test_01_pending_settings_refuse(self):
        replacement = self._request(self.case, 'full', self.new)
        with self.assertRaisesRegex(UserError, 'BA B1'):
            replacement.action_warranty_replacement_submit()
        self.assertEqual(replacement.state, 'draft')

    def test_03_date_policy_of_the_draft_survives_submit(self):
        """Submit and a change of type in Draft keep the policy chosen on the draft."""
        self.company.write({'warranty_replacement_full_finance': 'not_required',
                            'warranty_replacement_gm_user_ids': [(6, 0, self.gm.ids)]})
        replacement = self._request(self.case, 'full', self.new, date_policy='restart')
        replacement.write({'replacement_type': 'indoor'})
        replacement.write({'replacement_type': 'full'})
        self.assertEqual(replacement.date_policy, 'restart')
        replacement.action_warranty_replacement_submit()
        self.assertEqual(replacement.date_policy, 'restart')
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(self.unit.start_date, replacement.delivery_date)

    def test_02_two_levels_then_swap(self):
        self.company.write({'warranty_replacement_full_finance': 'required',
                            'warranty_replacement_gm_user_ids': [(6, 0, self.gm.ids)],
                            'warranty_replacement_finance_user_ids': [(6, 0, self.finance.ids)]})
        replacement = self._request(self.case, 'full', self.new)
        replacement.action_warranty_replacement_submit()
        self.assertEqual(replacement.state, 'submitted')
        self.assertTrue(replacement.finance_required)
        self.assertFalse(replacement.sudo().delivery_picking_id, 'no transfer before approval')
        self.assertFalse(replacement.with_user(self.coordinator).can_approve)
        with self.assertRaises(AccessError):
            replacement.with_user(self.coordinator).action_warranty_replacement_approve()
        self.assertFalse(replacement.with_user(self.coordinator).can_reject,
                         'the submitter of a Full Product cannot reject')
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        self.assertEqual(replacement.state, 'submitted')
        replacement.with_user(self.finance).action_warranty_replacement_approve()
        self.assertEqual(replacement.state, 'approved')
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(replacement.state, 'done')
        self.assertEqual(self.unit.serial_ids, self.new)

    def _full_product_settings(self, finance='required'):
        self.company.write({'warranty_replacement_full_finance': finance,
                            'warranty_replacement_gm_user_ids': [(6, 0, self.gm.ids)],
                            'warranty_replacement_finance_user_ids': [(6, 0, self.finance.ids)]})

    def test_04_rules_of_each_type(self):
        """Stage 3 Phase 1: the named rules give today's answer for every type."""
        Replacement = self.env['warranty.replacement']
        for kind, __ in REPLACEMENT_TYPES:
            with self.subTest(kind=kind):
                record = Replacement.new({'replacement_type': kind})
                self.assertEqual(record._warranty_replacement_finance_applies(), kind == 'full')
                self.assertEqual(record._warranty_replacement_replaces_unit(),
                                 kind in ('full', 'goodwill', 'vendor'))

    def test_05_labels_and_reject_rights_of_full_product(self):
        self._full_product_settings()
        replacement = self._request(self.case, 'full', self.new)
        replacement.action_warranty_replacement_submit()
        record = replacement.sudo()
        todos = record.activity_ids.filtered(
            lambda activity: 'approval needed' in activity.summary)
        self.assertIn('(GM + Finance)', todos[0].summary)
        self.assertEqual(todos.user_id, self.gm | self.finance)
        self.assertTrue(replacement.with_user(self.gm).can_reject)
        self.assertTrue(replacement.with_user(self.finance).can_reject,
                        'a Finance approver can reject a Full Product')
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        self.assertTrue(record.message_ids.filtered(
            lambda message: 'GM approval by' in (message.body or '')))
        self.assertFalse(record.message_ids.filtered(
            lambda message: 'decision Approved' in (message.body or '')))

    def test_07_date_correction_keeps_full_product_dates(self):
        self._full_product_settings('not_required')
        # Delivered 6 months ago, so that Restart gives other dates than the unit's.
        start = fields.Date.today() - relativedelta(months=6)
        end = start + relativedelta(months=12) - relativedelta(days=1)
        self.card._warranty_system_write({'warranty_start_date': start, 'warranty_end_date': end})
        self.unit._warranty_system_write({'start_date': start, 'end_date': end})
        replacement = self._request(self.case, 'full', self.new, date_policy='restart')
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertTrue(replacement.dates_changed)
        kept = (self.unit.start_date, self.unit.end_date)
        start = self.card.warranty_start_date - timedelta(days=10)
        self.card.sudo()._warranty_correct_dates(start, 'Wrong delivery date')
        self.assertEqual(self.card.warranty_start_date, start)
        self.assertEqual((self.unit.start_date, self.unit.end_date), kept)

    def test_08_replacement_cost_from_valuation(self):
        """A product with a cost gets that cost. UAT shows 0.00 because its products have none."""
        self.single.standard_price = 100.0
        self._full_product_settings('not_required')
        replacement = self._request(self.case, 'full', self.new)
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(replacement.replacement_cost, 100.0)
        self.assertTrue(replacement.replacement_cost_verified)
