from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group

from .test_warranty_replacement import ReplacementCommon


class ControlledActionCommon(ReplacementCommon):

    def setUp(self):
        super().setUp()
        self.company.write({'warranty_exception_approver_ids': [(6, 0, (self.gm | self.finance).ids)]})
        self.today = self.company._warranty_today()
        self.card = self._card(self.single)
        self.unit = self.card.unit_warranty_ids
        self.serial = self.unit.serial_ids
        self.moves_before = self._accounting_fingerprint()

    def _accounting_fingerprint(self):
        self.env.flush_all()
        self.env.cr.execute("""SELECT count(*), COALESCE(sum(amount_total), 0) FROM account_move""")
        return self.env.cr.fetchone()

    def _refused(self, exception, text, function, *args, **kwargs):
        with self.assertRaises(exception) as caught:
            function(*args, **kwargs)
        self.assertIn(text, str(caught.exception))

    def _evidence(self):
        return self.env['ir.attachment'].with_user(self.coordinator).create(
            {'name': 'evidence.txt', 'raw': b'evidence'})

    def _request_action(self, card, kind, units=None, **values):
        values.setdefault('reason', 'Test reason')
        return card.with_user(self.coordinator)._warranty_request_action(
            kind, units=units if units is not None else card._warranty_live_units(), **values)

    def _apply(self, card, kind, units=None, **values):
        action = self._request_action(card, kind, units, **values)
        action.with_user(self.gm).action_approve()
        self.env.invalidate_all()
        return action

    def _suspend(self, card=None, units=None):
        return self._apply(card or self.card, 'suspend', units, reason_code='misuse',
                           attachment_ids=self._evidence())

    def _two_unit_card(self):
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
        self.assertEqual(len(card.unit_warranty_ids), 2)
        return card

    def _case_for(self, serial, partner=None):
        partner = partner or self.partner
        ticket = self.env['helpdesk.ticket'].create({
            'name': 'P9 ticket', 'team_id': self.team.id, 'is_warranty': True,
            'partner_id': partner.id, 'description': '<p>Broken</p>'})
        case = self.env['warranty.case'].create({
            'helpdesk_ticket_id': ticket.id, 'partner_id': partner.id,
            'company_id': self.company.id, 'case_type': 'warranty_complaint',
            'serial_id': serial.id, 'requested_item_ids': [(6, 0, self.item.ids)]})
        case.action_check_eligibility()
        return case

    def _complete(self, cases):
        """The real completion path is not under test here."""
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_case SET state = 'completed' WHERE id IN %s",
                            (tuple(cases.ids),))
        self.env.invalidate_all()

    def _done_case(self, serial):
        case = self._case_for(serial)
        self._complete(case)
        return case

    def _return_picking(self, card):
        picking = card.unit_warranty_ids.stock_move_line_id.picking_id[:1]
        wizard = self.env['stock.return.picking'].with_context(
            active_id=picking.id, active_model='stock.picking').create({})
        wizard.product_return_moves.quantity = 1
        wizard.product_return_moves = wizard.product_return_moves[:1]
        returned = self.env['stock.picking'].browse(wizard.action_create_returns()['res_id'])
        return returned


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart91Foundation(ControlledActionCommon):
    """Stage 9.1: SRS 2.13, 12 control pattern, 13 critical fields, 16."""

    def test_01_client_writes_of_protected_values_are_refused(self):
        other = self.env['res.partner'].create({'name': 'Other'})
        card = self.card.with_user(self.coordinator)
        for vals in ({'partner_id': other.id}, {'product_id': self.indoor.id},
                     {'state': 'suspended'}, {'warranty_basis': 'usage'},
                     {'policy_id': self.policy.id if self.card.policy_id != self.policy else False}):
            self._refused(UserError, 'protected', card.write, vals)
        unit = self.unit.with_user(self.coordinator)
        for vals in ({'serial_ids': [(6, 0, self._lot(self.single, 6).ids)]},
                     {'state': 'cancelled'}, {'product_id': self.indoor.id},
                     {'current_site_id': other.id}):
            self._refused(UserError, 'protected', unit.write, vals)
        self.env.invalidate_all()
        self.assertEqual((self.card.partner_id, self.card.state, self.unit.serial_ids),
                         (self.partner, 'confirmed', self.serial))

    def test_02_import_and_create_paths_are_refused(self):
        other = self.env['res.partner'].create({'name': 'Other'})
        card = self.card.with_user(self.coordinator)
        result = card.load(['.id', 'partner_id/.id'], [[str(card.id), str(other.id)]])
        self.assertTrue(result['messages'], 'the import reports the refusal')
        self.env.invalidate_all()
        self.assertEqual(self.card.partner_id, self.partner)
        self._refused(UserError, 'protected', self.env['warranty.card'].with_user(
            self.coordinator).create, {'partner_id': self.partner.id, 'state': 'confirmed',
                                       'company_id': self.company.id})

    def test_03_unchanged_values_and_open_cards_stay_editable(self):
        self.card.with_user(self.coordinator).write({'partner_id': self.partner.id})
        draft = self.env['warranty.card'].create({'partner_id': self.partner.id,
                                                  'company_id': self.company.id})
        other = self.env['res.partner'].create({'name': 'Other'})
        draft.with_user(self.coordinator).write({'partner_id': other.id})
        self.assertEqual(draft.partner_id, other)

    def test_04_no_approver_means_no_request(self):
        self.company.warranty_exception_approver_ids = False
        self._refused(UserError, 'Warranty Exception Approver', self._request_action, self.card,
                      'suspend', reason_code='misuse', attachment_ids=self._evidence())
        self.company.warranty_exception_approver_ids = self.coordinator
        self._refused(UserError, 'Warranty Exception Approver', self._request_action, self.card,
                      'suspend', reason_code='misuse', attachment_ids=self._evidence())

    def test_05_separation_of_duties_and_rights(self):
        self.company.warranty_exception_approver_ids |= self.coordinator
        action = self._request_action(self.card, 'suspend', reason_code='misuse',
                                      attachment_ids=self._evidence())
        self._refused(AccessError, 'own request', action.with_user(self.coordinator).action_approve)
        self._refused(AccessError, 'Approvers', action.with_user(self.outsider).action_approve)
        self.assertEqual((self.unit.state, action.state), ('active', 'pending'))
        self.assertTrue(action.with_user(self.gm).can_decide)
        self.assertFalse(action.with_user(self.coordinator).can_decide)
        action.with_user(self.gm).action_approve()
        self._refused(UserError, 'already been decided', action.with_user(self.finance).action_approve)

    def test_06_action_record_is_protected(self):
        Action = self.env['warranty.card.action'].with_user(self.coordinator)
        self._refused(AccessError, '', Action.create, {
            'action_type': 'suspend', 'card_id': self.card.id, 'reason': 'x'})
        action = self._request_action(self.card, 'suspend', reason_code='misuse',
                                      attachment_ids=self._evidence())
        self._refused(AccessError, '', action.with_user(self.coordinator).write, {'state': 'done'})
        self._refused(UserError, 'cannot be deleted', action.unlink)
        action.with_user(self.gm).action_approve()
        self._refused(UserError, 'cannot be changed', action.write, {'reason': 'Changed'})

    def test_07_rejection_changes_nothing_and_second_request_waits(self):
        action = self._request_action(self.card, 'suspend', reason_code='misuse',
                                      attachment_ids=self._evidence())
        self._refused(UserError, 'waiting for approval', self._request_action, self.card, 'suspend',
                      reason_code='misuse', attachment_ids=self._evidence())
        self._refused(UserError, 'rejection reason', action.with_user(self.gm)._warranty_reject, ' ')
        action.with_user(self.gm)._warranty_reject('Not proven')
        self.assertEqual((action.state, action.decided_by_id, self.unit.state, self.card.state),
                         ('rejected', self.gm, 'active', 'confirmed'))
        self.assertFalse(action.activity_ids)
        self.assertTrue(self.card.message_ids.filtered(lambda m: 'Not proven' in (m.body or '')))
        self._suspend()

    def test_08_requests_create_approver_activities_and_notes(self):
        action = self._request_action(self.card, 'suspend', reason_code='misuse',
                                      attachment_ids=self._evidence())
        self.assertEqual(action.activity_ids.user_id, self.gm | self.finance)
        self.assertTrue(self.card.message_ids.filtered(lambda m: action.name in (m.body or '')))

    def test_09_history_from_every_entry_point(self):
        action = self._suspend()
        self.env.flush_all()
        History = self.env['warranty.history'].with_user(self.coordinator)
        rows = History.search([('card_id', '=', self.card.id)])
        self.assertIn('action', rows.mapped('entity'))
        self.assertIn('date', rows.mapped('entity'))
        row = rows.filtered(lambda r: r.reference == action.name)
        self.assertEqual((row.user_id, row.unit_id), (self.gm, self.unit))
        self.assertIn('active', row.summary)
        for result in (self.card.action_view_warranty_history(),
                       self.unit.action_view_warranty_history(),
                       self.card.sale_order_id.action_view_warranty_history()):
            self.assertEqual(History.search(result['domain']), rows)
        case = self._case_for(self.serial)
        self.assertTrue(History.search(case.action_view_warranty_history()['domain']))
        self.assertTrue(History.search(
            case.helpdesk_ticket_id.action_view_warranty_history()['domain']))
        self._refused(AccessError, '', History.create, {'reference': 'x'})

    def test_10_company_isolation(self):
        action = self._suspend()
        other = self.env['res.company'].create({'name': 'P9 Other Company'})
        user = self.env['res.users'].create({
            'name': 'P9 B', 'login': 'p9_b', 'company_id': other.id,
            'company_ids': [(6, 0, other.ids)],
            'groups_id': [(6, 0, self.env.ref('base.group_user').ids)]})
        self.env.flush_all()
        self.assertFalse(self.env['warranty.history'].with_user(user).search(
            [('card_id', '=', self.card.id)]))
        self.assertFalse(self.env['warranty.card.action'].with_user(user).search(
            [('id', '=', action.id)]))
        other.warranty_exception_approver_ids = user
        new_action = self._apply(self.card, 'reactivate', self.unit)
        self.assertEqual(new_action.state, 'done')
        self._refused(AccessError, '', self.card.with_user(user)._warranty_request_action, 'suspend',
                      units=self.unit, reason='x', reason_code='misuse')


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart910Integration(ControlledActionCommon):
    """Stage 9.10: the screens and the earlier Parts."""

    def test_01_request_and_reject_through_the_wizards(self):
        Wizard = self.env['warranty.card.action.wizard'].with_user(self.coordinator)
        result = self.card.with_user(self.coordinator).action_open_controlled_action()
        form = Form(Wizard.with_context(result['context']))
        form.action_type = 'suspend'
        form.reason_code = 'misuse'
        form.reason = 'Seal broken'
        wizard = form.save()
        wizard.attachment_ids = self._evidence()
        action = self.env['warranty.card.action'].browse(wizard.action_submit()['res_id'])
        self.assertEqual((action.state, action.unit_ids, action.requested_by_id),
                         ('pending', self.unit, self.coordinator))
        result = action.with_user(self.gm).action_open_reject_wizard()
        reject = self.env['warranty.card.action.reject.wizard'].with_user(self.gm).with_context(
            result['context']).create({'reason': 'Not proven'})
        reject.action_reject()
        self.assertEqual((action.state, action.rejection_reason), ('rejected', 'Not proven'))

    def test_02_every_action_type_opens_in_the_form(self):
        wizard = self.env['warranty.card.action.wizard'].with_context(default_card_id=self.card.id)
        for kind, __ in self.env['warranty.card.action.wizard']._fields['action_type'].selection:
            form = Form(wizard)
            form.action_type = kind
            self.assertEqual(form.action_type, kind)
        for model in ('warranty.card.action', 'warranty.history', 'warranty.card', 'warranty.unit'):
            self.assertTrue(self.env[model].get_view(view_type='list')['arch'])

    def test_03_evidence_must_be_the_requesters_own_fresh_upload(self):
        foreign = self.env['ir.attachment'].create({'name': 'other.txt', 'raw': b'other'})
        self._refused(UserError, 'Upload the evidence', self._request_action, self.card, 'suspend',
                      reason_code='misuse', attachment_ids=foreign)
        attached = self.env['ir.attachment'].with_user(self.coordinator).create({
            'name': 'card.txt', 'raw': b'x', 'res_model': 'warranty.card', 'res_id': self.card.id})
        self._refused(UserError, 'Upload the evidence', self._request_action, self.card, 'suspend',
                      reason_code='misuse', attachment_ids=attached)

    def test_04_suspended_unit_blocks_a_replacement(self):
        self.company.write({'warranty_replacement_gm_user_ids': [(6, 0, self.gm.ids)],
                            'warranty_replacement_full_finance': 'not_required'})
        case = self._case_for(self.serial)
        self._approved_state(case)
        self._suspend()

        def replace():
            self._request(case, 'vendor', self._lot(self.single, 6)) \
                .action_warranty_replacement_submit()
        with self.assertRaises(UserError):
            replace()
        self._apply(self.card, 'reactivate', self.unit)
        replace()

    def test_05_card_without_work_has_no_open_work(self):
        self.env.flush_all()
        self.assertEqual(self.card._warranty_open_work(), [])

    def test_06_new_settings_have_the_same_help_on_field_and_screen(self):
        arch = self.env.ref('warranty_management.res_config_settings_view_form_warranty').arch \
            if self.env.ref('warranty_management.res_config_settings_view_form_warranty',
                            raise_if_not_found=False) else ''
        fields_ = self.env['res.config.settings']._fields
        for name in ('warranty_exception_approver_ids', 'warranty_exception_evidence_required',
                     'warranty_relocation_allowed', 'warranty_transfer_allowed',
                     'warranty_extension_max_days'):
            self.assertTrue(fields_[name].help, name)
            if arch:
                self.assertIn(name, arch)

    def test_07_system_paths_still_work_for_normal_users(self):
        """Expiry through a date correction runs as the user, on protected states."""
        user = self.coordinator
        user.groups_id |= self.env.ref('warranty_management.group_warranty_date_correction')
        past = self.today - relativedelta(days=1)
        self.card._warranty_system_write({'warranty_end_date': past})
        self.unit._warranty_system_write({'end_date': past})
        self.env['warranty.card']._cron_expire_warranties()
        self.assertEqual(self.card.state, 'expired')
        self.card.with_user(user)._warranty_correct_dates(self.today, 'Wrong start date')
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'active'))

    def _service(self, card):
        # This card has no free services configured; only the display value is under test.
        return self.env['warranty.service.entitlement'].new({'warranty_card_id': card.id})

    def test_09_service_shows_every_product_of_its_card(self):
        normal = self._service(self.card)
        self.assertEqual(normal.warranty_units_display,
                         '%s [%s]' % (self.single.display_name, self.serial.name))
        kit_card = self._card(self.kit)
        unit = kit_card.unit_warranty_ids
        kit = self._service(kit_card).warranty_units_display
        self.assertIn(self.kit.display_name, kit)
        for lot in unit.serial_ids:
            self.assertIn(lot.name, kit)
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.kit.id, 'product_uom_qty': 1}),
                           (0, 0, {'product_id': self.single.id, 'product_uom_qty': 1})]})
        confirm_and_group(order, 'per_so')
        mixed = self._service(order.warranty_card_ids).warranty_units_display
        self.assertIn(self.kit.display_name, mixed)
        self.assertIn(self.single.display_name, mixed)

    def test_10_service_form_visibility(self):
        arch = self.env['warranty.service.entitlement'].with_user(self.coordinator).get_view(
            self.env.ref('warranty_management.warranty_service_entitlement_view_form').id,
            'form')['arch']
        root = etree.fromstring(arch)

        def node(name):
            return root.xpath("//sheet//field[@name='%s'][not(ancestor::list)]" % name)
        expected = {
            'worksheet_template_id': 'not worksheet_template_id',
            'due_date_conflict': 'not due_date_conflict',
            'due_status': 'not due_status',
            'scheduled_date': 'not scheduled_date',
            'helpdesk_ticket_id': 'not helpdesk_ticket_id',
            'grace_period_end_date': 'not grace_period_end_date',
            'alert_date': 'not alert_date',
            'expiry_reminder_date': 'not expiry_reminder_date',
            'usage_threshold': "warranty_basis != 'usage'",
            'payment_eligibility': 'not payment_eligibility',
            'reschedule_count': 'not reschedule_count',
        }
        for name, condition in expected.items():
            self.assertEqual([item.get('invisible') for item in node(name)], [condition], name)
        self.assertEqual(node('warranty_units_display')[0].get('string'), 'Product')
        customer = root.xpath("//sheet//field[@name='partner_id']")[0]
        self.assertEqual(customer.getnext().get('name'), 'warranty_units_display')
        self.assertEqual(node('warranty_units_display')[0].getnext().get('name'), 'service_no')
        for name in ('due_alert_sent', 'expiry_reminder_sent'):
            self.assertTrue(all(item.get('invisible') for item in node(name)), name)

    def test_08_date_correction_after_extension_is_visible_in_the_history(self):
        """Known limit, recorded as Q29: a date correction recalculates the end from the duration
        and so replaces an extended end date. Both remain in the history."""
        user = self.coordinator
        user.groups_id |= self.env.ref('warranty_management.group_warranty_date_correction')
        extended = self.unit.end_date + relativedelta(months=6)
        self._apply(self.card, 'extend', new_end_date=extended, extension_type='free')
        self.card.with_user(user)._warranty_correct_dates(
            self.card.warranty_start_date + relativedelta(days=1), 'Wrong start date')
        self.assertLess(self.unit.end_date, extended)
        events = self.env['warranty.card.date.log'].search(
            [('card_id', '=', self.card.id)]).mapped('event')
        self.assertIn('extension', events)
        self.assertIn('correction', events)


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart92Duplicates(ControlledActionCommon):
    """Stage 9.2: SRS 12 #25, 13."""

    def test_01_second_live_unit_with_the_serial_is_refused(self):
        other = self._card(self.single)
        self._refused(ValidationError, 'already on warranty unit',
                      other.unit_warranty_ids.write, {'serial_ids': [(6, 0, self.serial.ids)]})

    def test_02_cancelled_or_expired_holder_lets_it_go(self):
        other = self._card(self.single)
        self.unit._warranty_system_write({'state': 'expired'})
        other.unit_warranty_ids.write({'serial_ids': [(6, 0, self.serial.ids)]})
        self.assertEqual(other.unit_warranty_ids.serial_ids, self.serial)

    def test_03_confirmation_rechecks(self):
        draft = self._card(self.single)
        draft.unit_warranty_ids._warranty_system_write({'serial_ids': [(6, 0, self.serial.ids)]})
        self._refused(ValidationError, 'already on warranty unit',
                      draft.unit_warranty_ids._warranty_check_serial_duplicates)

    def test_04_lot_tracked_products_share_a_lot(self):
        product = self.env['product.product'].create({
            'name': 'P9 Lot', 'type': 'consu', 'is_storable': True, 'tracking': 'lot'})
        lot = self.env['stock.lot'].create({'name': 'P9-LOT', 'product_id': product.id})
        first, second = self.unit, self._card(self.single).unit_warranty_ids
        first.write({'serial_ids': [(4, lot.id)]})
        second.write({'serial_ids': [(4, lot.id)]})
        self.assertIn(lot, second.serial_ids)


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart93Suspension(ControlledActionCommon):
    """Stage 9.3: SRS 12 #5, 13, page 59. Void waits for Q7."""

    def test_01_suspend_blocks_and_reactivate_restores(self):
        dates = (self.card.warranty_start_date, self.card.warranty_end_date, self.unit.end_date)
        action = self._suspend()
        self.assertEqual((self.card.state, self.unit.state), ('suspended', 'suspended'))
        self.assertEqual(action.reason_code, 'misuse')
        self.assertEqual(self._case_for(self.serial).eligibility_result, 'not_eligible')
        self._apply(self.card, 'reactivate', self.unit)
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'active'))
        self.assertEqual(self._case_for(self.serial).eligibility_result, 'eligible')
        self.assertEqual((self.card.warranty_start_date, self.card.warranty_end_date,
                          self.unit.end_date), dates, 'dates never move')
        self.assertEqual(self._accounting_fingerprint(), self.moves_before)

    def test_02_invalid_requests(self):
        self._refused(UserError, 'reactivated', self._request_action, self.card, 'reactivate')
        self._refused(UserError, 'suspension reason', self._request_action, self.card, 'suspend',
                      attachment_ids=self._evidence())
        self._refused(UserError, 'evidence', self._request_action, self.card, 'suspend',
                      reason_code='misuse')
        self._refused(UserError, 'reason', self._request_action, self.card, 'suspend',
                      reason=' ', reason_code='misuse', attachment_ids=self._evidence())
        self._suspend()
        self._refused(UserError, 'Confirmed', self._request_action, self.card, 'suspend',
                      reason_code='misuse', attachment_ids=self._evidence())

    def test_03_evidence_setting(self):
        self.company.warranty_exception_evidence_required = False
        self._apply(self.card, 'suspend', reason_code='misuse')
        self.assertEqual(self.card.state, 'suspended')

    def test_04_one_unit_on_a_two_unit_card(self):
        card = self._two_unit_card()
        first, second = card.unit_warranty_ids
        self._suspend(card, first)
        self.assertEqual((card.state, first.state, second.state), ('confirmed', 'suspended', 'active'))
        self.assertEqual(self._case_for(first.serial_ids).eligibility_result, 'not_eligible')
        self.assertEqual(self._case_for(second.serial_ids).eligibility_result, 'eligible')
        self._suspend(card, second)
        self.assertEqual(card.state, 'suspended')
        self._apply(card, 'reactivate', first)
        self.assertEqual((card.state, first.state, second.state), ('confirmed', 'active', 'suspended'))

    def test_05_expiry_does_not_touch_suspended_and_runs_after_reactivation(self):
        self._suspend()
        past = self.today - relativedelta(days=1)
        self.card._warranty_system_write({'warranty_end_date': past})
        self.unit._warranty_system_write({'end_date': past})
        self.env['warranty.card']._cron_expire_warranties()
        self.assertEqual(self.card.state, 'suspended')
        self._apply(self.card, 'reactivate', self.unit)
        self.assertEqual(self.card.state, 'confirmed')
        self.env['warranty.card']._cron_expire_warranties()
        self.assertEqual((self.card.state, self.unit.state, self.card.warranty_end_date),
                         ('expired', 'expired', past))

    def test_06_open_work_is_reported_and_left_alone(self):
        case = self._case_for(self.serial)
        state, result = case.state, case.eligibility_result
        action = self._suspend()
        self.assertIn(case.name, action.open_work_note)
        self.assertEqual((case.state, case.eligibility_result), (state, result))
        case.action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'not_eligible', 'the existing recheck blocks')


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart94ReturnCancellation(ControlledActionCommon):
    """Stage 9.4: SRS 12 #14. Controlled, never automatic."""

    def _returned(self, card):
        picking = self._return_picking(card)
        self._validate(picking)
        self.env.invalidate_all()
        return picking

    def test_01_needs_a_validated_return(self):
        self._refused(UserError, 'validated return', self._request_action, self.card, 'cancel')
        picking = self._return_picking(self.card)
        self._refused(UserError, 'not a validated return', self._request_action, self.card, 'cancel',
                      source_picking_id=picking.id)
        other = self._card(self.single)
        self._validate(picking)
        self.assertEqual(self.unit.state, 'active', 'the return alone cancels nothing')
        self._refused(UserError, 'not a validated return', self._request_action, other, 'cancel',
                      source_picking_id=picking.id)

    def test_02_cancel_blocks_claims_and_keeps_the_rest(self):
        picking = self._returned(self.card)
        dates = (self.card.warranty_start_date, self.card.warranty_end_date)
        action = self._apply(self.card, 'cancel', source_picking_id=picking.id)
        self.assertEqual((self.card.state, self.unit.state), ('cancelled', 'cancelled'))
        self.assertEqual((self.card.warranty_start_date, self.card.warranty_end_date), dates)
        self.assertEqual(self.card.sale_order_id.state, 'sale')
        self.assertEqual(self._case_for(self.serial).eligibility_result, 'not_eligible')
        self.assertEqual(self._accounting_fingerprint(), self.moves_before)
        self.assertEqual(action.source_picking_id, picking)
        self._refused(UserError, 'Replaced or Cancelled', self._request_action, self.card, 'cancel',
                      self.unit, source_picking_id=picking.id)

    def test_03_serial_is_free_after_cancellation(self):
        picking = self._returned(self.card)
        self._apply(self.card, 'cancel', source_picking_id=picking.id)
        other = self._card(self.single)
        other.unit_warranty_ids.write({'serial_ids': [(6, 0, self.serial.ids)]})
        self.assertEqual(other.unit_warranty_ids.serial_ids, self.serial)

    def test_04_partial_return_cancels_one_unit(self):
        card = self._two_unit_card()
        picking = self._returned(card)
        returned = picking.move_line_ids.lot_id
        unit = card.unit_warranty_ids.filtered(lambda u: returned & u.serial_ids)
        self.assertEqual(len(unit), 1)
        # Both units share the delivery move: the return identifies the move, the user the unit.
        self._apply(card, 'cancel', unit, source_picking_id=picking.id)
        self.assertEqual(unit.state, 'cancelled')
        self.assertEqual(card.state, 'confirmed')
        kept = card.unit_warranty_ids - unit
        self.assertEqual(kept.state, 'active')
        self.assertEqual(self._case_for(kept.serial_ids).eligibility_result, 'eligible')


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart95Correction(ControlledActionCommon):
    """Stage 9.5: SRS 12 #10, #24, 13, 16. Warranty product and policy correction are not offered."""

    def test_01_serial(self):
        new = self._lot(self.single, 6)
        action = self._apply(self.card, 'correct_serial', self.unit, old_serial_id=self.serial.id,
                             new_serial_id=new.id)
        self.assertEqual(self.unit.serial_ids, new)
        self.assertEqual((action.old_value, action.new_value), (self.serial.name, new.name))
        self.assertEqual(self._case_for(new).eligibility_result, 'eligible')
        self.assertEqual(self._accounting_fingerprint(), self.moves_before)

    def test_02_invalid_serials(self):
        new = self._lot(self.single, 6)
        self._refused(UserError, 'different correct serial', self._request_action, self.card,
                      'correct_serial', self.unit, old_serial_id=new.id, new_serial_id=self.serial.id)
        self._refused(UserError, 'not a serial of', self._request_action, self.card, 'correct_serial',
                      self.unit, old_serial_id=self.serial.id,
                      new_serial_id=self._lot(self.indoor, 6).id)
        other = self._card(self.single)
        self._refused(UserError, 'already on warranty unit', self._request_action, self.card,
                      'correct_serial', self.unit, old_serial_id=self.serial.id,
                      new_serial_id=other.unit_warranty_ids.serial_ids.id)

    def test_03_open_case_blocks_correction(self):
        case = self._case_for(self.serial)
        self._refused(UserError, case.name, self._request_action, self.card, 'correct_serial',
                      self.unit, old_serial_id=self.serial.id,
                      new_serial_id=self._lot(self.single, 6).id)

    def test_04_customer(self):
        other = self.env['res.partner'].create({'name': 'Right Customer'})
        action = self._apply(self.card, 'correct_customer', new_partner_id=other.id)
        self.assertEqual(self.card.partner_id, other)
        self.assertEqual(action.old_partner_id, self.partner)
        self.assertEqual(self.card.sale_order_id.partner_id, self.partner, 'the sale is not rewritten')
        self.assertEqual(self.unit.current_site_id, other)
        self.assertEqual(self._case_for(self.serial, other).eligibility_result, 'eligible')
        self._refused(UserError, 'different customer', self._request_action, self.card,
                      'correct_customer', new_partner_id=other.id)

    def test_05_usage_cannot_decrease_without_correction(self):
        card, unit = self.card, self.unit
        card._warranty_system_write({'warranty_basis': 'usage', 'usage_limit': 1000,
                                     'usage_unit': 'operating_hours'})
        unit._warranty_system_write({'usage_limit': 1000, 'usage_unit': 'operating_hours'})

        def reading(value):
            ticket = self.env['helpdesk.ticket'].create({
                'name': 'Usage', 'team_id': self.team.id, 'is_warranty': True,
                'partner_id': self.partner.id, 'description': '<p>Usage</p>'})
            case = self.env['warranty.case'].create({
                'helpdesk_ticket_id': ticket.id, 'partner_id': self.partner.id,
                'company_id': self.company.id, 'case_type': 'warranty_complaint',
                'serial_id': self.serial.id, 'current_usage': value,
                'warranty_unit_id': unit.id, 'requested_item_ids': [(6, 0, self.item.ids)]})
            case.action_check_eligibility()
            return case
        self.assertEqual(reading(500).eligibility_result, 'eligible')
        lower = reading(100)
        self.assertEqual(lower.eligibility_result, 'manual_review')
        self._complete(self.env['warranty.case'].search([('warranty_unit_id', '=', unit.id)]))
        self._apply(card, 'correct_usage', unit, new_usage=90)
        self.assertEqual(unit.usage_correction_reading, 90)
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_unit SET usage_correction_date = usage_correction_date "
                            "- interval '1 second' WHERE id = %s", (unit.id,))
        self.env.invalidate_all()
        self.assertEqual(reading(100).eligibility_result, 'eligible')
        self.assertEqual(reading(50).eligibility_result, 'manual_review')


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart96Relocation(ControlledActionCommon):
    """Stage 9.6: SRS 12 #4, 2.13. Branch, territory and technician rules wait for Q16."""

    def setUp(self):
        super().setUp()
        self.site = self.env['res.partner'].create({
            'name': 'Kandy site', 'parent_id': self.partner.id, 'type': 'delivery', 'street': 'Kandy 1'})

    def test_01_relocate_keeps_validity_and_history(self):
        dates = (self.card.warranty_start_date, self.card.warranty_end_date)
        action = self._apply(self.card, 'relocate', new_site_id=self.site.id,
                             effective_date=self.today)
        self.assertEqual(self.unit.current_site_id, self.site)
        self.assertEqual(self.unit._warranty_service_address(), self.site)
        self.assertEqual((self.card.warranty_start_date, self.card.warranty_end_date), dates)
        self.assertEqual(action.new_value, self.site.display_name)
        self.assertEqual(self._case_for(self.serial).eligibility_result, 'eligible')
        self.assertEqual(self.card.sale_order_id.partner_shipping_id, self.partner)
        service_site = self._case_for(self.serial)._warranty_reference_site()
        self.assertEqual(service_site, self.site)

    def test_02_invalid(self):
        stranger = self.env['res.partner'].create({'name': 'Stranger'})
        self._refused(UserError, 'address of the warranty owner', self._request_action, self.card,
                      'relocate', new_site_id=stranger.id)
        self._apply(self.card, 'relocate', new_site_id=self.site.id)
        self._refused(UserError, 'already at', self._request_action, self.card, 'relocate',
                      new_site_id=self.site.id)
        self.company.warranty_relocation_allowed = False
        self._refused(UserError, 'not allowed', self._request_action, self.card, 'relocate',
                      new_site_id=self.partner.id)


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart97Transfer(ControlledActionCommon):
    """Stage 9.7: SRS 12 #3. Whole card only (Q18); free services stay with the card (Q19)."""

    def setUp(self):
        super().setUp()
        self.new_owner = self.env['res.partner'].create({'name': 'New Owner'})

    def _transfer(self, card=None, **values):
        return self._apply(card or self.card, 'transfer', new_partner_id=self.new_owner.id,
                           effective_date=self.today, attachment_ids=self._evidence(), **values)

    def test_01_transfer(self):
        dates = (self.card.warranty_start_date, self.card.warranty_end_date)
        order = self.card.sale_order_id
        action = self._transfer()
        self.assertEqual(self.card.partner_id, self.new_owner)
        self.assertEqual((action.old_partner_id, action.new_partner_id, action.effective_date),
                         (self.partner, self.new_owner, self.today))
        self.assertTrue(action.attachment_ids)
        self.assertEqual((self.card.warranty_start_date, self.card.warranty_end_date), dates)
        self.assertEqual(order.partner_id, self.partner, 'the sale keeps its customer')
        self.assertEqual(self.unit.current_site_id, self.new_owner)
        self.assertEqual(self._case_for(self.serial, self.new_owner).eligibility_result, 'eligible')
        self.assertNotEqual(self._case_for(self.serial).eligibility_result, 'eligible')
        self.assertEqual(self._accounting_fingerprint(), self.moves_before)

    def test_02_invalid(self):
        self._refused(UserError, 'transfer document', self._request_action, self.card, 'transfer',
                      new_partner_id=self.new_owner.id, effective_date=self.today)
        self._refused(UserError, 'transfer date', self._request_action, self.card, 'transfer',
                      new_partner_id=self.new_owner.id, attachment_ids=self._evidence())
        self._refused(UserError, 'different customer', self._request_action, self.card, 'transfer',
                      new_partner_id=self.partner.id, effective_date=self.today,
                      attachment_ids=self._evidence())
        self.company.warranty_transfer_allowed = False
        self._refused(UserError, 'not allowed', self._request_action, self.card, 'transfer',
                      new_partner_id=self.new_owner.id, effective_date=self.today,
                      attachment_ids=self._evidence())

    def test_03_single_unit_waits_for_q18(self):
        card = self._two_unit_card()
        self._refused(UserError, 'single-unit transfer', self._request_action, card, 'transfer',
                      card.unit_warranty_ids[:1], new_partner_id=self.new_owner.id,
                      effective_date=self.today, attachment_ids=self._evidence())

    def test_04_open_case_blocks_a_transfer_also_at_approval(self):
        case = self._case_for(self.serial)
        self._refused(UserError, case.name, self._transfer)
        self._complete(case)
        action = self._request_action(self.card, 'transfer', new_partner_id=self.new_owner.id,
                                      effective_date=self.today, attachment_ids=self._evidence())
        late = self._case_for(self.serial)
        self._refused(UserError, late.name, action.with_user(self.gm).action_approve)
        self.assertEqual(self.card.partner_id, self.partner)


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart98Extension(ControlledActionCommon):
    """Stage 9.8A: SRS 12 #13. The extended warranty product (2.4, Q21 / Q23) is not built."""

    def _new_end(self, months=6):
        return self.unit.end_date + relativedelta(months=months)

    def test_01_extend(self):
        old_end, new_end = self.unit.end_date, self._new_end()
        action = self._apply(self.card, 'extend', new_end_date=new_end, extension_type='free')
        self.assertEqual((self.card.warranty_end_date, self.unit.end_date), (new_end, new_end))
        self.assertEqual((self.card.warranty_original_end_date, self.unit.original_end_date),
                         (old_end, old_end))
        self.assertEqual((action.old_value, action.new_value), (str(old_end), str(new_end)))
        log = self.env['warranty.card.date.log'].search(
            [('card_id', '=', self.card.id), ('event', '=', 'extension')])
        self.assertEqual((log.old_end, log.new_end), (old_end, new_end))
        self._apply(self.card, 'extend', new_end_date=self._new_end(1), extension_type='free')
        self.assertEqual(self.unit.original_end_date, old_end, 'the original stays')
        self.assertEqual(self._accounting_fingerprint(), self.moves_before)

    def test_02_invalid(self):
        self._refused(UserError, 'after the current end date', self._request_action, self.card,
                      'extend', new_end_date=self.unit.end_date, extension_type='free')
        self._refused(UserError, 'extension type', self._request_action, self.card, 'extend',
                      new_end_date=self._new_end())
        self._refused(UserError, 'quotation or invoice', self._request_action, self.card, 'extend',
                      new_end_date=self._new_end(), extension_type='paid')
        self.company.warranty_extension_max_days = 30
        self._refused(UserError, 'maximum', self._request_action, self.card, 'extend',
                      new_end_date=self._new_end(), extension_type='free')

    def test_03_paid_source_must_belong_to_the_owner(self):
        stranger = self.env['res.partner'].create({'name': 'Stranger'})
        order = self.env['sale.order'].create({'partner_id': stranger.id})
        self._refused(UserError, 'warranty owner', self._request_action, self.card, 'extend',
                      new_end_date=self._new_end(), extension_type='paid', source_order_id=order.id)
        action = self._apply(self.card, 'extend', new_end_date=self._new_end(),
                             extension_type='paid', source_order_id=self.card.sale_order_id.id)
        self.assertEqual(action.source_order_id, self.card.sale_order_id)

    def test_04_expired_card_returns_to_confirmed(self):
        past = self.today - relativedelta(days=1)
        self.card._warranty_system_write({'warranty_end_date': past})
        self.unit._warranty_system_write({'end_date': past})
        self.env['warranty.card']._cron_expire_warranties()
        self.assertEqual(self.card.state, 'expired')
        self._apply(self.card, 'extend', new_end_date=self.today + relativedelta(months=3),
                    extension_type='free')
        self.assertEqual((self.card.state, self.unit.state), ('confirmed', 'active'))
        self.assertEqual(self._case_for(self.serial).eligibility_result, 'eligible')

    def test_05_one_unit_keeps_the_card_on_the_latest_end(self):
        card = self._two_unit_card()
        first, second = card.unit_warranty_ids
        new_end = first.end_date + relativedelta(months=3)
        self._apply(card, 'extend', first, new_end_date=new_end, extension_type='free')
        self.assertEqual((first.end_date, card.warranty_end_date), (new_end, new_end))
        self.assertEqual(second.original_end_date, False)
        self.assertLess(second.end_date, new_end)

    def test_06_suspended_card_is_not_extended(self):
        self._suspend()
        self._refused(UserError, 'Confirmed or Expired', self._request_action, self.card, 'extend',
                      new_end_date=self._new_end(), extension_type='free')

    def test_07_kit_unit_with_own_dates_is_not_extended(self):
        card = self._card(self.kit)
        unit = card.unit_warranty_ids
        unit.with_context(warranty_replacement_marker=self._marker()).write(
            {'indoor_end_date': unit.end_date})
        self._refused(UserError, 'Indoor / Outdoor dates', self._request_action, card, 'extend',
                      new_end_date=unit.end_date + relativedelta(months=1), extension_type='free')

    def _marker(self):
        from ..models.warranty_replacement import _REPLACEMENT_MARKER
        return _REPLACEMENT_MARKER


@tagged('post_install', '-at_install', 'warranty_part9')
class TestPart99RepeatComplaint(ControlledActionCommon):
    """Stage 9.9: SRS 12 #22. Reopening a closed case waits for Q25; the repeat window for Q24."""

    def _repeat(self, previous, **values):
        ticket = self.env['helpdesk.ticket'].create({
            'name': 'Repeat', 'team_id': self.team.id, 'is_warranty': True,
            'partner_id': self.partner.id, 'description': '<p>Again</p>'})
        return self.env['warranty.case'].create(dict({
            'helpdesk_ticket_id': ticket.id, 'partner_id': self.partner.id,
            'company_id': self.company.id, 'case_type': 'repeat_complaint',
            'serial_id': self.serial.id, 'warranty_card_id': self.card.id,
            'warranty_unit_id': self.unit.id, 'repeat_of_case_id': previous.id,
            'requested_item_ids': [(6, 0, self.item.ids)]}, **values))

    def test_01_new_linked_case_leaves_the_original(self):
        previous = self._done_case(self.serial)
        result = previous.action_create_repeat_complaint()
        self.assertEqual(result['context']['default_repeat_of_case_id'], previous.id)
        self.assertEqual(result['context']['default_case_type'], 'repeat_complaint')
        self.assertFalse(result.get('res_id'))
        repeat = self._repeat(previous)
        self.assertEqual(previous.state, 'completed', 'not reopened')
        self.assertEqual(previous.repeat_case_ids, repeat)
        repeat.action_check_eligibility()
        self.assertIn(repeat.eligibility_result, ('eligible', 'preliminary_passed'), repeat.eligibility_reason)
        self.assertFalse(repeat.service_entitlement_ids, 'no free service is consumed')

    def test_02_linked_job_is_offered(self):
        previous = self._done_case(self.serial)
        self.assertFalse(previous._warranty_repeat_defaults()['default_repeat_of_job_id'])
        job = self.env['warranty.service.job'].create({'warranty_case_id': previous.id})
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_service_job SET state = 'completed' WHERE id = %s",
                            (job.id,))
        self.env.invalidate_all()
        self.assertEqual(previous._warranty_repeat_defaults()['default_repeat_of_job_id'], job.id)
        repeat = self._repeat(previous, repeat_of_job_id=job.id)
        self.assertEqual(repeat.repeat_of_job_id, job)

    def test_03_invalid_links(self):
        open_case = self._case_for(self.serial)
        self._refused(ValidationError, 'Completed or Closed', self._repeat, open_case)
        self._complete(open_case)
        self._refused(ValidationError, 'Only a Reopen/Repeat', self._repeat, open_case,
                      case_type='warranty_complaint')
        other = self._card(self.single)
        other_case = self._done_case(other.unit_warranty_ids.serial_ids)
        self._refused(ValidationError, 'same warranty card', self._repeat, other_case)

    def test_04_one_open_repeat_per_case(self):
        previous = self._done_case(self.serial)
        first = self._repeat(previous)
        self._refused(ValidationError, 'open repeat complaint', self._repeat, previous)
        self._complete(first)
        self._repeat(previous)

    def test_05_open_case_has_no_repeat_action(self):
        case = self._case_for(self.serial)
        self._refused(UserError, 'Completed or Closed', case.action_create_repeat_complaint)

    def test_06_counts_as_a_failure(self):
        previous = self._done_case(self.serial)
        self.assertIn('repeat_complaint', self._repeat(previous).case_type)
        self.env.flush_all()
        self.assertTrue(self.env['warranty.history'].search(
            [('card_id', '=', self.card.id), ('entity', '=', 'case')]))
