from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_replacement')
class TestGoodwillReplacement(ReplacementCommon):
    """Part 7 Stage 3 Phase 2: one serial, Manager / GM approval, manual date, result kept."""

    def setUp(self):
        super().setUp()
        self.company.warranty_replacement_gm_user_ids = self.gm
        self.card = self._card(self.single)
        self.unit = self.card.unit_warranty_ids
        self.old = self.unit.serial_ids
        self.new = self._lot(self.single, 6)
        self.assertNotEqual(self.new, self.old)
        self.manual = fields.Date.today() + relativedelta(years=1)

    def _expire_dates(self):
        start = fields.Date.today() - relativedelta(years=3)
        end = start + relativedelta(years=1)
        self.card._warranty_system_write({'warranty_start_date': start, 'warranty_end_date': end})
        self.unit._warranty_system_write({'start_date': start, 'end_date': end})

    def _out_of_warranty_case(self):
        self._expire_dates()
        case = self._eligible_case(self.old)
        self.assertEqual((case.state, case.eligibility_result),
                         ('eligibility_checked', 'out_of_warranty'), case.eligibility_reason)
        return case

    def _goodwill(self, case, **vals):
        return self._request(case, 'goodwill', self.new, **dict(
            {'reason': 'goodwill', 'reason_note': 'Long-standing customer',
             'date_policy': 'manual'}, **vals))

    def _approve(self, replacement):
        as_gm = replacement.with_user(self.gm)
        as_gm.write({'manual_end_date': self.manual, 'manual_date_reason': 'GM decision'})
        as_gm.action_warranty_replacement_approve()

    def _run(self, replacement):
        replacement.action_warranty_replacement_submit()
        self._approve(replacement)
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)

    def test_01_out_of_warranty_full_flow(self):
        case = self._out_of_warranty_case()
        names = (self.card.name, self.unit.name)
        header = (self.card.warranty_start_date, self.card.warranty_end_date)
        old_start = self.unit.start_date
        replacement = self._goodwill(case)
        self.assertEqual(replacement.date_policy, 'manual')
        self.assertEqual(replacement.case_eligibility_result, 'out_of_warranty')
        replacement.action_warranty_replacement_submit()
        record = replacement.sudo()
        self.assertEqual(replacement.state, 'submitted')
        self.assertFalse(replacement.finance_required)
        self.assertFalse(record.return_picking_id | record.delivery_picking_id)
        todo = record.activity_ids.filtered(lambda activity: 'approval needed' in activity.summary)
        self.assertIn('Manager / GM', todo.summary)
        self.assertEqual(todo.user_id, self.gm)
        self.assertEqual(self.unit.serial_ids, self.old)
        exception = record.message_ids.filtered(
            lambda message: 'Goodwill exception' in (message.body or ''))
        self.assertEqual(len(exception), 1)
        self.assertIn('Out of Warranty', exception.body)
        self.assertIn('Long-standing customer', exception.body)
        self.assertTrue(case.message_ids.filtered(
            lambda message: 'Goodwill exception' in (message.body or '')))

        as_gm = replacement.with_user(self.gm)
        with self.assertRaisesRegex(UserError, 'Manual End Date'):
            as_gm.action_warranty_replacement_approve()
        self._approve(replacement)
        self.assertEqual(replacement.state, 'approved')
        self.assertEqual(replacement.gm_approved_by_id, self.gm)
        self.assertFalse(replacement.finance_approved_by_id)
        self.assertTrue(record.message_ids.filtered(
            lambda message: 'decision Approved' in (message.body or '')))
        self.assertEqual(record.return_picking_id.move_line_ids.lot_id, self.old)
        self.assertEqual(record.delivery_picking_id.move_line_ids.lot_id, self.new)
        self.assertEqual(self.unit.serial_ids, self.old, 'no swap before the delivery')

        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(replacement.state, 'done')
        self.assertEqual(self.unit.serial_ids, self.new)
        self.assertEqual((self.unit.start_date, self.unit.end_date), (old_start, self.manual))
        self.assertEqual((self.card.name, self.unit.name), names)
        self.assertEqual((self.card.warranty_start_date, self.card.warranty_end_date), header)
        self.assertTrue(replacement.updated_card_generated)
        self.assertEqual(len(self.env['warranty.card.date.log'].search(
            [('card_id', '=', self.card.id), ('event', '=', 'replacement')])), 1)
        self.assertEqual((case.state, case.eligibility_result),
                         ('eligibility_checked', 'out_of_warranty'))

        self.assertTrue(case.warranty_goodwill_can_complete)
        case.with_user(self.coordinator).action_warranty_complete_goodwill_case()
        self.assertEqual((case.state, case.eligibility_result), ('completed', 'out_of_warranty'))
        self.assertFalse(case.warranty_goodwill_can_complete)
        with self.assertRaises(UserError):
            case.action_warranty_complete_goodwill_case()

    def test_02_not_eligible_expired_status_card(self):
        self.card.sudo().state = 'expired'
        case = self._eligible_case(self.old)
        self.assertEqual(case.eligibility_result, 'not_eligible', case.eligibility_reason)
        replacement = self._goodwill(case)
        self._run(replacement)
        self.assertEqual(replacement.state, 'done')
        self.assertEqual(self.unit.serial_ids, self.new)
        self.assertEqual(self.unit.end_date, self.manual)
        self.assertEqual(case.eligibility_result, 'not_eligible')
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'active'),
                         'a future manual date gives a valid period again')
        case.action_warranty_complete_goodwill_case()
        self.assertEqual((case.state, case.eligibility_result), ('completed', 'not_eligible'))

    def test_03_cancelled_and_suspended_stay_blocked(self):
        for state in ('cancelled', 'suspended'):
            with self.subTest(state=state):
                self.card.sudo().state = state
                case = self._eligible_case(self.old)
                self.assertEqual(case.eligibility_result, 'not_eligible')
                replacement = self._goodwill(case)
                with self.assertRaisesRegex(UserError, 'stays blocked'):
                    replacement.action_warranty_replacement_submit()
                self.assertEqual(replacement.state, 'draft')
                replacement.unlink()

    def test_04_card_blocked_after_submit_stops_approval(self):
        case = self._out_of_warranty_case()
        replacement = self._goodwill(case)
        replacement.action_warranty_replacement_submit()
        self.card.sudo().state = 'suspended'
        with self.assertRaisesRegex(UserError, 'stays blocked'):
            self._approve(replacement)
        self.assertEqual(replacement.state, 'submitted')
        self.assertFalse(replacement.sudo().delivery_picking_id)

    def test_05_eligible_case_is_refused(self):
        case = self._eligible_case(self.old)
        self.assertEqual(case.eligibility_result, 'eligible', case.eligibility_reason)
        for state in ('eligibility_checked', 'approved'):
            with self.subTest(state=state):
                case.sudo().write({'state': state})
                replacement = self._goodwill(case)
                with self.assertRaisesRegex(UserError, 'Not Eligible or Out of Warranty'):
                    replacement.action_warranty_replacement_submit()
                replacement.unlink()

    def test_06_kit_is_refused(self):
        kit_card = self._card(self.kit)
        unit = kit_card.unit_warranty_ids
        past = fields.Date.today() - relativedelta(years=3)
        kit_card._warranty_system_write({'warranty_start_date': past,
                                         'warranty_end_date': past + relativedelta(years=1)})
        unit._warranty_system_write({'start_date': past, 'end_date': past + relativedelta(years=1)})
        case = self._eligible_case(unit.indoor_serial_id)
        self.assertEqual(case.eligibility_result, 'out_of_warranty')
        replacement = self._request(case, 'goodwill', self._lot(self.indoor, 6),
                                    reason='goodwill', reason_note='Customer care')
        with self.assertRaisesRegex(UserError, 'must hold one product with one serial'):
            replacement.action_warranty_replacement_submit()
        self.assertEqual(unit.indoor_serial_id, case.serial_id)

    def test_07_only_manager_gm_decides(self):
        self.company.warranty_replacement_finance_user_ids = self.finance
        self.company.warranty_replacement_full_finance = 'required'
        self.company.warranty_replacement_gm_user_ids = self.gm | self.coordinator
        replacement = self._goodwill(self._out_of_warranty_case())
        replacement.action_warranty_replacement_submit()
        self.assertFalse(replacement.finance_required, 'the Full Product setting does not apply')
        for user in (self.coordinator, self.finance, self.outsider):
            as_user = replacement.with_user(user)
            self.assertFalse(as_user.can_approve, user.login)
            self.assertFalse(as_user.can_reject, user.login)
            with self.assertRaises(AccessError):
                as_user.action_warranty_replacement_approve()
        self.assertTrue(replacement.with_user(self.gm).can_approve)

    def test_08_submit_needs_a_manager(self):
        self.company.warranty_replacement_gm_user_ids = self.coordinator
        replacement = self._goodwill(self._out_of_warranty_case())
        with self.assertRaisesRegex(UserError, 'GM Approvers'):
            replacement.action_warranty_replacement_submit()

    def test_09_reason_and_manual_policy(self):
        case = self._out_of_warranty_case()
        missing = self._request(case, 'goodwill', self.new, reason='goodwill')
        with self.assertRaisesRegex(UserError, 'Reason Details'):
            missing.action_warranty_replacement_submit()
        missing.unlink()
        forced = self._goodwill(case, reason='other', date_policy='restart')
        forced.action_warranty_replacement_submit()
        self.assertEqual((forced.reason, forced.date_policy), ('goodwill', 'manual'))
        with self.assertRaises(UserError):
            forced.write({'date_policy': 'restart'})
        with self.assertRaises(UserError):
            forced.write({'manual_end_date': self.manual})

    def test_10_goodwill_reason_stays_refused_on_other_types(self):
        case = self._eligible_case(self.old)
        self._approved_state(case)
        replacement = self._request(case, 'full', self.new, reason='goodwill')
        with self.assertRaisesRegex(UserError, 'Goodwill replacement type'):
            replacement.action_warranty_replacement_submit()

    def test_11_case_is_frozen_until_completion(self):
        """Submitted, Approved and Done: the result cannot be rewritten or the case ended. A rejected
        replacement frees the case."""
        case = self._out_of_warranty_case()
        self.assertFalse(case.warranty_goodwill_can_complete)
        draft = self._goodwill(case)
        case.action_check_eligibility()  # a Draft holds nothing
        draft.action_warranty_replacement_submit()

        def refused():
            for action in (case.action_check_eligibility,
                           lambda: case.write({'state': 'rejected'}),
                           lambda: case.write({'eligibility_result': 'eligible'}),
                           lambda: case.write({'serial_id': self.new.id})):
                with self.assertRaisesRegex(UserError, 'stay as checked'):
                    action()
            with self.assertRaisesRegex(UserError, 'stay as checked'):
                case.sudo().write({'state': 'chargeable'})
            self.assertEqual((case.state, case.eligibility_result),
                             ('eligibility_checked', 'out_of_warranty'))

        refused()
        self._approve(draft)
        refused()
        record = draft.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(draft.state, 'done')
        refused()

    def test_12_rejection_frees_the_case(self):
        case = self._out_of_warranty_case()
        replacement = self._goodwill(case)
        replacement.action_warranty_replacement_submit()
        as_gm = replacement.with_user(self.gm)
        as_gm.write({'rejection_reason': 'Not justified'})
        as_gm.action_warranty_replacement_reject()
        self.assertEqual(replacement.state, 'rejected')
        self.assertEqual(self.unit.serial_ids, self.old)
        self.assertFalse(case.warranty_goodwill_can_complete)
        with self.assertRaisesRegex(UserError, 'no Done Goodwill'):
            case.action_warranty_complete_goodwill_case()
        case.action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'out_of_warranty')

    def test_13_completion_keeps_the_blockers(self):
        case = self._out_of_warranty_case()
        replacement = self._goodwill(case)
        with self.assertRaisesRegex(UserError, 'no Done Goodwill'):
            case.action_warranty_complete_goodwill_case()
        self._run(replacement)
        other = self._request(case, 'goodwill', self._lot(self.single, 5),
                              reason='goodwill', reason_note='Second request')
        with self.assertRaisesRegex(UserError, 'is not finished'):
            case.action_warranty_complete_goodwill_case()
        other.unlink()
        with self.assertRaises(AccessError):
            case.with_user(self.outsider).action_warranty_complete_goodwill_case()
        self.assertEqual(case.state, 'eligibility_checked')
        case.action_warranty_complete_goodwill_case()
        self.assertEqual(case.state, 'completed')

    def test_14_case_without_case_type_is_refused(self):
        case = self._out_of_warranty_case()
        case.sudo().with_context(warranty_case_type_marker=None).write({'case_type': False})
        replacement = self._goodwill(case)
        with self.assertRaisesRegex(UserError, 'no Case Type'):
            replacement.action_warranty_replacement_submit()

    def test_15_request_from_the_form(self):
        """The screen: the button of the case gives Goodwill, its reason and the manual policy."""
        case = self._out_of_warranty_case()
        action = case.with_user(self.coordinator).action_warranty_create_goodwill_replacement()
        form = Form(self.env['warranty.replacement'].with_user(self.coordinator).with_context(
            **action['context']))
        self.assertEqual(form.replacement_type, 'goodwill')
        self.assertEqual(form.reason, 'goodwill')
        self.assertEqual(form.date_policy, 'manual')
        self.assertEqual(form.warranty_card_id, self.card)
        form.new_serial_id = self.new
        form.reason_note = 'Long-standing customer'
        replacement = form.save()
        self.assertEqual((replacement.reason, replacement.date_policy), ('goodwill', 'manual'))
        replacement.action_warranty_replacement_submit()
        self.assertEqual(replacement.state, 'submitted')

    def test_16_type_change_on_the_form(self):
        case = self._out_of_warranty_case()
        form = Form(self.env['warranty.replacement'].with_user(self.coordinator).with_context(
            default_warranty_case_id=case.id))
        self.assertEqual(form.replacement_type, 'full')
        form.replacement_type = 'goodwill'
        self.assertEqual((form.reason, form.date_policy), ('goodwill', 'manual'))

    def test_17_later_eligibility_uses_the_manual_date(self):
        """A Confirmed card: the new serial is eligible until the manual date."""
        case = self._out_of_warranty_case()
        self._run(self._goodwill(case))
        case.action_warranty_complete_goodwill_case()
        later = self._eligible_case(self.new)
        self.assertEqual(later.eligibility_result, 'eligible', later.eligibility_reason)

    def test_18_date_correction_keeps_goodwill_dates(self):
        case = self._out_of_warranty_case()
        self._run(self._goodwill(case))
        kept = (self.unit.start_date, self.unit.end_date)
        start = self.card.warranty_start_date - relativedelta(days=10)
        self.card.sudo()._warranty_correct_dates(start, 'Wrong delivery date')
        self.assertEqual((self.unit.start_date, self.unit.end_date), kept)

    def test_19_pdf_of_goodwill(self):
        case = self._out_of_warranty_case()
        self._run(self._goodwill(case))
        report = self.env.ref('warranty_management.report_warranty_card')
        html = str(self.env['ir.qweb']._render(report.id, {
            'docs': self.card, 'doc_ids': self.card.ids, 'doc_model': 'warranty.card',
            'company': self.company, 'res_company': self.company, 'user': self.env.user}))
        self.assertIn('Updated Copy after replacement', html)
        self.assertIn(self.new.name, html)
        self.assertNotIn(self.old.name, html)
