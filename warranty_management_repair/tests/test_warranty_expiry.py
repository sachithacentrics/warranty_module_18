from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group

from ..models.warranty_replacement import _REPLACEMENT_MARKER
from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_expiry')
class TestWarrantyExpiry(ReplacementCommon):
    """Automatic expiry with the existing state fields (SRS 9.13, 13, 14)."""

    def setUp(self):
        super().setUp()
        self.company.write({'warranty_replacement_gm_user_ids': [(6, 0, self.gm.ids)],
                            'warranty_replacement_full_finance': 'not_required'})
        self.today = self.company._warranty_today()
        self.card = self._card(self.single)
        self.unit = self.card.unit_warranty_ids
        self.old = self.unit.serial_ids
        self.new = self._lot(self.single, 6)
        self.start = self.today - relativedelta(years=1)
        self._dates(self.card, self.unit, self.today + relativedelta(months=6))

    def _dates(self, card, units, end):
        card._warranty_system_write({'warranty_start_date': self.start, 'warranty_end_date': end})
        units._warranty_system_write({'start_date': self.start, 'end_date': end})

    def _end(self, days=-1):
        """The warranty ended (days < 0), ends today (0), or ends later."""
        end = self.today + relativedelta(days=days)
        self._dates(self.card, self.unit, end)
        return end

    def _expire(self):
        self.env['warranty.card']._cron_expire_warranties()

    def test_01_card_and_unit_expire_once(self):
        end = self._end()
        logs = self.env['warranty.card.date.log'].search_count([('card_id', '=', self.card.id)])
        self._expire()
        self.assertEqual((self.card.state, self.unit.state), ('expired', 'expired'))
        self.assertEqual((self.card.warranty_end_date, self.unit.end_date), (end, end))
        self.assertEqual(self.unit.serial_ids, self.old)
        self.assertEqual(self.env['warranty.card.date.log'].search_count(
            [('card_id', '=', self.card.id)]), logs, 'no date history row')
        self.assertTrue(self.card.message_ids.filtered(
            lambda message: 'Warranty expiry' in (message.body or '')))
        messages = len(self.card.message_ids)
        self._expire()
        self.assertEqual(len(self.card.message_ids), messages, 'a second run changes nothing')

    def test_02_end_date_is_still_covered(self):
        self._end(0)
        self._expire()
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'active'))

    def test_03_multi_unit_card(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.single.id, 'product_uom_qty': 2})]})
        confirm_and_group(order, 'per_so')
        picking = order.picking_ids
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        card = order.warranty_card_ids
        card.action_confirm_warranty()
        first, second = card.unit_warranty_ids
        past = self.today - relativedelta(days=1)
        self._dates(card, first, past)
        second._warranty_system_write({'start_date': self.start,
                                       'end_date': self.today + relativedelta(days=30)})
        self._expire()
        self.assertEqual((first.state, second.state, card.state),
                         ('expired', 'active', 'confirmed'))
        second._warranty_system_write({'end_date': past})
        self._expire()
        self.assertEqual((second.state, card.state), ('expired', 'expired'))

    def test_04_kit_uses_the_serial_dates(self):
        card = self._card(self.kit)
        unit = card.unit_warranty_ids
        past = self.today - relativedelta(days=1)
        self._dates(card, unit, past)
        unit.with_context(warranty_replacement_marker=_REPLACEMENT_MARKER).write(
            {'outdoor_start_date': self.today, 'outdoor_end_date': self.today + relativedelta(days=9)})
        self._expire()
        self.assertEqual((unit.state, card.state), ('active', 'confirmed'), 'the outdoor serial is valid')
        unit.with_context(warranty_replacement_marker=_REPLACEMENT_MARKER).write(
            {'outdoor_end_date': past})
        self._expire()
        self.assertEqual((unit.state, card.state), ('expired', 'expired'))

    def test_05_other_states_are_not_touched(self):
        self._end()
        for state in ('suspended', 'cancelled'):
            self.card.sudo().state = state
            self._expire()
            self.assertEqual((self.card.state, self.unit.state), (state, 'active'))
        self.card.sudo().write({'state': 'confirmed', 'warranty_basis': 'usage'})
        self._expire()
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'active'))
        self.card.sudo().warranty_basis = 'period'
        self.unit.sudo().state = 'suspended'
        self._expire()
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'suspended'),
                         'a Suspended unit holds the card')
        self.unit.sudo().state = 'replaced'
        self._expire()
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'replaced'),
                         'no covered unit: the card stays')

    def test_06_q14_and_the_ticket_date(self):
        """A ticket created while valid and checked after expiry: Not Eligible (Q14). A stored
        result stays until someone checks again."""
        self._end(0)
        checked = self._eligible_case(self.old)
        self.assertEqual(checked.eligibility_result, 'eligible', checked.eligibility_reason)
        late = self.env['helpdesk.ticket'].create({
            'name': 'Raised in time', 'team_id': self.team.id, 'is_warranty': True,
            'partner_id': self.partner.id, 'warranty_serial_id': self.old.id})
        self._end()
        case = self.env['warranty.case'].create({
            'helpdesk_ticket_id': late.id, 'case_type': 'warranty_complaint',
            'serial_id': self.old.id, 'requested_item_ids': [(6, 0, self.item.ids)]})
        self._expire()
        self.assertEqual(checked.eligibility_result, 'eligible', 'the stored result is kept')
        case.action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'not_eligible', case.eligibility_reason)
        self.assertEqual(case.warranty_card_id, self.card)

    def test_07_out_of_warranty_before_the_job(self):
        self._end()
        case = self._eligible_case(self.old)
        self.assertEqual((self.card.state, case.eligibility_result), ('confirmed', 'out_of_warranty'))

    def test_08_tickets_reach_expired_cards(self):
        self._end()
        self._expire()
        ticket = self.env['helpdesk.ticket'].create({
            'name': 'Only expired', 'team_id': self.team.id, 'is_warranty': True,
            'partner_id': self.partner.id})
        self.assertTrue(ticket.warranty_has_cards)
        self.assertIn(self.card, ticket.warranty_available_card_ids)
        self.assertIn(self.single, ticket.warranty_available_product_ids)
        self.assertTrue(ticket.action_create_warranty_case())
        self.card.sudo().state = 'cancelled'
        ticket.invalidate_recordset()
        self.assertFalse(ticket.warranty_has_cards, 'Cancelled stays out')

    def test_09_goodwill_on_expired_restores_with_a_future_date(self):
        self._end()
        self._expire()
        case = self._eligible_case(self.old)
        self.assertEqual(case.eligibility_result, 'not_eligible', case.eligibility_reason)
        replacement = self._request(case, 'goodwill', self.new, reason='goodwill',
                                    reason_note='Customer care', date_policy='manual')
        replacement.action_warranty_replacement_submit()
        as_gm = replacement.with_user(self.gm)
        manual = self.today + relativedelta(years=1)
        as_gm.write({'manual_end_date': manual, 'manual_date_reason': 'GM decision'})
        as_gm.action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(replacement.state, 'done')
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'active'))
        self.assertEqual(case.eligibility_result, 'not_eligible', 'the result is not rewritten')
        case.action_warranty_complete_goodwill_case()
        self.assertEqual((case.state, case.eligibility_result), ('completed', 'not_eligible'))
        self.assertEqual(self._eligible_case(self.new).eligibility_result, 'eligible')

    def test_10_goodwill_with_a_past_date_stays_expired(self):
        self._end(-5)
        self._expire()
        case = self._eligible_case(self.old)
        replacement = self._request(case, 'goodwill', self.new, reason='goodwill',
                                    reason_note='Customer care', date_policy='manual')
        replacement.action_warranty_replacement_submit()
        as_gm = replacement.with_user(self.gm)
        as_gm.write({'manual_end_date': self.today - relativedelta(days=1),
                     'manual_date_reason': 'GM decision'})
        as_gm.action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual((self.card.state, self.unit.state), ('expired', 'expired'))

    def _approved_full(self, **vals):
        self._end(0)
        case = self._eligible_case(self.old)
        self.assertEqual(case.eligibility_result, 'eligible', case.eligibility_reason)
        self._approved_state(case)
        replacement = self._request(case, 'full', self.new, **vals)
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        self.assertEqual(replacement.state, 'approved')
        self._end()
        self._expire()
        self.assertEqual(self.card.state, 'expired', 'the card expires on time')
        return replacement

    def test_11_approved_replacement_finishes_and_stays_expired(self):
        replacement = self._approved_full()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(replacement.state, 'done')
        self.assertEqual(self.unit.serial_ids, self.new)
        self.assertEqual(self.old.quant_ids.filtered(lambda q: q.quantity > 0).location_id,
                         self.return_location)
        self.assertEqual((self.card.state, self.unit.state), ('expired', 'expired'),
                         'Continue Original gives no new period')

    def test_12_approved_restart_restores(self):
        replacement = self._approved_full(date_policy='restart')
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual((replacement.state, self.card.state, self.unit.state),
                         ('done', 'confirmed', 'active'))

    def test_13_approved_remaining_period_finishes(self):
        replacement = self._approved_full(date_policy='remaining_period')
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(replacement.state, 'done')
        self.assertEqual(replacement.remaining_days, 0)
        self.assertEqual(self.card.state, 'expired')

    def test_14_suspended_still_blocks_an_approved_replacement(self):
        replacement = self._approved_full()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self.card.sudo().state = 'suspended'
        with self.assertRaisesRegex(UserError, 'must be Confirmed'):
            self._validate(record.delivery_picking_id)
        self.assertEqual(self.unit.serial_ids, self.old)

    def test_15_approval_needs_a_confirmed_card(self):
        self._end(0)
        case = self._eligible_case(self.old)
        self._approved_state(case)
        replacement = self._request(case, 'full', self.new)
        replacement.action_warranty_replacement_submit()
        self._end()
        self._expire()
        as_gm = replacement.with_user(self.gm)
        with self.assertRaisesRegex(UserError, 'must be Confirmed'):
            as_gm.action_warranty_replacement_approve()
        self.assertEqual(replacement.state, 'submitted')
        self.assertFalse(replacement.sudo().delivery_picking_id)
        as_gm.write({'rejection_reason': 'Warranty ended'})
        as_gm.action_warranty_replacement_reject()
        self.assertEqual(replacement.state, 'rejected')

    def test_16_correction_restores_only_a_valid_period(self):
        self._end()
        self._expire()
        recent = self.today - relativedelta(days=10)
        self.card.sudo()._warranty_correct_dates(
            self.today - relativedelta(years=2), 'Still in the past')
        self.assertEqual((self.card.state, self.unit.state), ('expired', 'expired'))
        self.card.sudo()._warranty_correct_dates(recent, 'Wrong delivery date')
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'active'))
        self.assertTrue(self.card.message_ids.filtered(
            lambda message: 'Warranty restored by' in (message.body or '')))

    def test_17_job_does_not_restore(self):
        self._end()
        self._expire()
        self._dates(self.card, self.unit, self.today + relativedelta(days=30))
        self._expire()
        self.assertEqual((self.card.state, self.unit.state), ('expired', 'expired'),
                         'only a correction or a replacement restores')

    def test_18_pdf_download_on_expired(self):
        self._end()
        self._expire()
        self.assertTrue(self.card.action_download_pdf())
