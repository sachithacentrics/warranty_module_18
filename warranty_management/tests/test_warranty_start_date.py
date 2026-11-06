from datetime import date, datetime

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, tagged

from .common import confirm_and_group, set_installation


@tagged('post_install', '-at_install', 'warranty_start_date')
class TestWarrantyStartDate(TransactionCase):
    """Warranty Start Date Automation (doc/start_date_design.md §15, SD-xx)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'delivery',
            'default_warranty_duration': 0,
            'warranty_timezone': 'Asia/Colombo',
        })
        cls.env.user.tz = 'Pacific/Pago_Pago'   # UTC-11: never used for warranty dates
        cls.partner = cls.env['res.partner'].create({'name': 'Start Date Customer'})
        cls.categ = cls.env['product.category'].create({'name': 'Start Date ACs'})
        cls.stock_location = cls.env.ref('stock.stock_location_stock')
        cls.corrector = cls.env['res.users'].create({
            'name': 'Date Corrector', 'login': 'wsd_corrector',
            'groups_id': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('warranty_management.group_warranty_date_correction').id])]})
        cls.plain_user = cls.env['res.users'].create({
            'name': 'Plain Warranty User', 'login': 'wsd_plain',
            'groups_id': [Command.set([cls.env.ref('base.group_user').id])]})

    # ------------------------------------------------------------------ helpers
    def _product(self, name, criterion='delivery', **vals):
        values = {
            'name': name, 'type': 'consu', 'is_storable': True, 'categ_id': self.categ.id,
            'invoice_policy': 'order', 'warranty_applicable': True,
            'default_warranty_period': 12, 'default_warranty_period_unit': 'months',
            'warranty_start_criterion': criterion,
        }
        values.update(vals)
        if values.get('type') == 'service':
            values['is_storable'] = False
        product = self.env['product.product'].create(values)
        if values['type'] == 'consu':
            self.env['stock.quant']._update_available_quantity(product, self.stock_location, 20)
        return product

    def _order(self, lines, grouping='per_so'):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': qty})
                           for product, qty in lines],
        })
        confirm_and_group(order, grouping)
        return order

    def _deliver(self, order, quantities=None, when='2026-10-26 10:00:00'):
        picking = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))[:1]
        picking.action_assign()
        for move in picking.move_ids:
            if quantities and move.product_id in quantities:
                move.quantity = quantities[move.product_id]
            move.picked = True
        with freeze_time(when):
            res = picking.button_validate()
            if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
                Form(self.env[res['res_model']].with_context(res['context'])).save().process()
        return picking

    def _invoice(self, order, when='2026-10-26 10:00:00', quantity=None, post=True,
                 invoice_date=None):
        invoice = order._create_invoices()
        if quantity is not None:
            invoice.invoice_line_ids.filtered('sale_line_ids').quantity = quantity
        if invoice_date:
            invoice.invoice_date = invoice_date
        if post:
            with freeze_time(when):
                invoice.action_post()
        return invoice

    def _refund(self, invoice, when='2026-10-28 10:00:00'):
        wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({
                'journal_id': invoice.journal_id.id, 'reason': 'Return'})
        refund = self.env['account.move'].browse(wizard.refund_moves()['res_id'])
        with freeze_time(when):
            refund.action_post()
        return refund

    def _notes(self, card):
        return ' '.join(card.message_ids.mapped('body'))

    # ------------------------------------------------------------------ delivery basis
    def test_01_delivery_warranty_timezone(self):
        """SD-01 / SD-04: the validation time in the Warranty Timezone (not the user's
        timezone, not the order / scheduled date)."""
        ac = self._product('SD AC TZ')
        order = self._order([(ac, 1)])
        order.picking_ids.scheduled_date = datetime(2026, 1, 1, 8, 0)
        card = order.warranty_card_ids
        self.assertFalse(card.expected_start_date)
        picking = self._deliver(order, when='2026-10-26 20:00:00')   # 01:30 next day Colombo
        self.assertEqual(card.state, 'ready')
        self.assertEqual((card.expected_start_date, card.expected_end_date),
                         (date(2026, 10, 27), date(2027, 10, 26)))
        self.assertIn(picking.name, card.start_source_note)
        card.action_confirm_warranty()
        self.assertEqual((card.warranty_start_date, card.warranty_end_date),
                         (date(2026, 10, 27), date(2027, 10, 26)))
        self.assertEqual((card.start_date_source, card.source_picking_id, card.source_datetime,
                          card.source_verification),
                         ('delivery', picking, datetime(2026, 10, 26, 20, 0), 'event'))
        self.assertEqual(card.unit_warranty_ids.delivery_datetime, datetime(2026, 10, 26, 20, 0))
        log = card.date_log_ids
        self.assertEqual((log.event, log.new_start, log.picking_id), ('activation', card.warranty_start_date, picking))
        self.assertIn('Warranty activated', self._notes(card))

    def test_02_partial_deliveries_latest(self):
        """SD-02: partial deliveries -> the card waits; start = latest unit delivery."""
        ac = self._product('SD AC Partial')
        order = self._order([(ac, 3)])
        card = order.warranty_card_ids
        self._deliver(order, {ac: 2}, when='2026-10-01 05:00:00')
        self.assertEqual(card.state, 'draft')
        self.assertIn('Delivery for unit', card.missing_requirements)
        self.assertFalse(card.expected_start_date)
        backorder = self._deliver(order, when='2026-10-05 05:00:00')
        self.assertEqual(card.state, 'ready')
        self.assertEqual(card.expected_start_date, date(2026, 10, 5))
        card.action_confirm_warranty()
        self.assertEqual((card.warranty_start_date, card.source_picking_id),
                         (date(2026, 10, 5), backorder))
        self.assertEqual(sorted(card.unit_warranty_ids.mapped('delivery_datetime')),
                         [datetime(2026, 10, 1, 5, 0)] * 2 + [datetime(2026, 10, 5, 5, 0)])

    def test_03_unrelated_delivery_ignored(self):
        """SD-03: a card only dates from the deliveries of its own units."""
        ac, other = self._product('SD AC Own'), self._product('SD Other')
        order = self._order([(ac, 1), (other, 1)], grouping='per_product')
        card = order.warranty_card_ids.filtered(lambda c: c.product_id == ac)
        other_card = order.warranty_card_ids - card
        self._deliver(order, {ac: 0, other: 1}, when='2026-10-02 05:00:00')
        self.assertEqual(other_card.expected_start_date, date(2026, 10, 2))
        self.assertEqual(card.state, 'draft', 'the delivery of another product never counts')
        self.assertFalse(card.expected_start_date)
        self._deliver(order, when='2026-10-09 05:00:00')
        self.assertEqual(card.expected_start_date, date(2026, 10, 9))

    def test_04_delivery_without_goods_needs_exception(self):
        """SD-18 / Q14: Delivery basis without physical delivery -> authorized exception."""
        service = self._product('SD Service Warranty', type='service')
        order = self._order([(service, 1)])
        card = order.warranty_card_ids
        self.assertEqual(card.state, 'draft')
        self.assertIn('no physical delivery', card.missing_requirements)
        with self.assertRaisesRegex(UserError, 'Date Correction'):
            card.with_user(self.plain_user)._warranty_apply_exception(date(2026, 9, 1), 'x')
        with self.assertRaisesRegex(UserError, 'reason'):
            card.with_user(self.corrector)._warranty_apply_exception(date(2026, 9, 1), ' ')
        wizard = self.env['warranty.card.date.wizard'].with_user(self.corrector).create({
            'card_id': card.id, 'mode': 'exception', 'new_start_date': date(2026, 9, 1),
            'reason': 'Customer collected at the counter'})
        self.assertEqual(wizard.expected_end_date, date(2027, 8, 31))
        wizard.action_apply()
        self.assertEqual((card.state, card.start_date_source), ('ready', 'exception'))
        card.action_confirm_warranty()
        self.assertEqual((card.warranty_start_date, card.source_verification),
                         (date(2026, 9, 1), 'exception'))
        self.assertEqual(card.date_log_ids.sorted('id').mapped('event'),
                         ['exception', 'activation'])
        self.assertIn('Customer collected', self._notes(card))

    # ------------------------------------------------------------------ invoice basis
    def test_05_invoice_posting_time_not_invoice_date(self):
        """SD-05 / SD-06: the actual posting time (Warranty Timezone), not the backdated
        invoice date; a draft invoice never counts."""
        ac = self._product('SD AC Inv', criterion='invoice')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order, when='2026-09-01 05:00:00')
        invoice = self._invoice(order, post=False, invoice_date=date(2026, 1, 15))
        self.assertEqual(card.state, 'draft')
        self.assertIn('Posted invoice for unit', card.missing_requirements)
        with freeze_time('2026-10-26 19:00:00'):    # 00:30 on 27/10 in Colombo
            invoice.action_post()
        self.assertEqual(invoice.warranty_posted_at, datetime(2026, 10, 26, 19, 0))
        self.assertEqual(card.state, 'ready')
        card.action_confirm_warranty()
        self.assertEqual((card.warranty_start_date, card.source_invoice_id,
                          card.source_verification), (date(2026, 10, 27), invoice, 'event'))
        self.assertEqual((card.unit_warranty_ids.source_invoice_id,
                          card.unit_warranty_ids.source_invoice_posted_at),
                         (invoice, datetime(2026, 10, 26, 19, 0)))
        with self.assertRaises(UserError):
            invoice.warranty_posted_at = datetime(2026, 1, 1)

    def test_06_reset_and_repost_latest_posting(self):
        """SD-07 / D1b: the latest valid posting; earlier events kept."""
        ac = self._product('SD AC Repost', criterion='invoice')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        invoice = self._invoice(order, when='2026-10-01 05:00:00')
        self.assertEqual(card.expected_start_date, date(2026, 10, 1))
        with freeze_time('2026-10-03 05:00:00'):
            invoice.button_draft()
        self.assertFalse(invoice.warranty_posted_at)
        self.assertEqual(card.state, 'draft')
        with freeze_time('2026-10-10 05:00:00'):
            invoice.action_post()
        self.assertEqual(card.expected_start_date, date(2026, 10, 10))
        self.assertEqual(invoice.warranty_posting_event_ids.sorted('id').mapped('event'),
                         ['posted', 'reset_to_draft', 'posted'])
        with self.assertRaises(UserError):
            invoice.warranty_posting_event_ids[:1].event = 'cancelled'

    def test_07_down_payment_not_counted(self):
        """SD-08: a down-payment invoice never covers a unit."""
        ac = self._product('SD AC DP', criterion='invoice', list_price=1000)
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        wizard = self.env['sale.advance.payment.inv'].with_context(
            active_model='sale.order', active_ids=order.ids).create({
                'advance_payment_method': 'fixed', 'fixed_amount': 100})
        down_payment = self.env['account.move'].browse(wizard._create_invoices(order).ids)
        with freeze_time('2026-10-01 05:00:00'):
            down_payment.action_post()
        self.assertEqual(card.state, 'draft')
        self.assertIn('Posted invoice for unit', card.missing_requirements)
        final = self._invoice(order, when='2026-10-12 05:00:00')
        self.assertEqual((card.state, card.expected_start_date), ('ready', date(2026, 10, 12)))
        card.action_confirm_warranty()
        self.assertEqual(card.source_invoice_id, final)

    def test_08_partial_invoices_allocation_and_credit_note(self):
        """SD-09 / SD-10: units covered in unit order by whole cumulative quantities; the card
        starts at the latest covering invoice; a credit note removes coverage from the invoice
        it reverses."""
        ac = self._product('SD AC Split', criterion='invoice')
        order = self._order([(ac, 3)])
        card = order.warranty_card_ids
        self._deliver(order)
        first = self._invoice(order, when='2026-10-01 05:00:00', quantity=2.5)
        self.assertEqual(card.state, 'draft')
        self.assertIn('Posted invoice for unit %s' % card.unit_warranty_ids.sorted(
            'unit_number')[2].name, card.missing_requirements)
        second = self._invoice(order, when='2026-10-05 05:00:00', quantity=0.5)
        allocation = card._warranty_invoice_allocation()
        units = card.unit_warranty_ids.sorted('unit_number')
        self.assertEqual([allocation[unit][0] for unit in units], [first, first, second])
        self.assertEqual(card.expected_start_date, date(2026, 10, 5))
        self._refund(second)
        self.assertEqual(card.state, 'draft', 'the reversed quantity no longer covers unit 3')
        self.assertNotIn(units[2], card._warranty_invoice_allocation())

    def test_09_unrelated_invoice_ignored(self):
        """SD-11: an invoice of other products never covers the card."""
        ac, other = self._product('SD AC Rel', criterion='invoice'), self._product('SD Other Inv')
        order = self._order([(ac, 1), (other, 1)], grouping='per_product')
        card = order.warranty_card_ids.filtered(lambda c: c.product_id == ac)
        self._deliver(order)
        invoice = order._create_invoices()
        invoice.invoice_line_ids.filtered(lambda line: line.product_id == ac).unlink()
        with freeze_time('2026-10-01 05:00:00'):
            invoice.action_post()
        self.assertIn('Posted invoice for unit', card.missing_requirements)

    def test_10_historical_posting(self):
        """SD-12 / D1a: an invoice posted before the automation dates from its verified
        posting tracking; without one it needs an exception (no create / invoice date)."""
        ac = self._product('SD AC Hist', criterion='invoice')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        invoice = self._invoice(order, when='2026-10-01 05:00:00')
        self.env.flush_all()
        # Simulate an invoice posted before the module: no recorded posting time / events,
        # only the standard status tracking of a posting made in an earlier request.
        self.env.cr.execute("UPDATE account_move SET warranty_posted_at = NULL WHERE id = %s",
                            [invoice.id])
        self.env.cr.execute("DELETE FROM warranty_invoice_posting_event WHERE move_id = %s",
                            [invoice.id])
        invoice.invalidate_recordset()
        card.invalidate_recordset()
        self.assertEqual(invoice._warranty_posting_info(), (False, False),
                         'no tracking: never guessed (create / invoice date unused)')
        self.assertFalse(card.expected_start_date)
        field = self.env['ir.model.fields']._get('account.move', 'state')
        with freeze_time('2026-09-20 20:00:00'):
            invoice.sudo()._message_log(body='', tracking_value_ids=[Command.create({
                'field_id': field.id, 'old_value_char': 'Draft', 'new_value_char': 'Posted'})])
        self.assertEqual(invoice._warranty_posting_info(),
                         (datetime(2026, 9, 20, 20, 0), 'history'))
        card.invalidate_recordset()
        self.assertEqual(card.expected_start_date, date(2026, 9, 21))
        card.action_confirm_warranty()
        self.assertEqual(card.source_verification, 'history')
        self.assertIn('posting history', card.start_source_note)

    def test_10b_unverifiable_posting_needs_exception(self):
        """D1a: without a recorded or tracked posting the card needs an exception."""
        ac = self._product('SD AC Unverified', criterion='invoice')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        invoice = self._invoice(order, when='2026-10-01 05:00:00')
        self.env.flush_all()
        self.env.cr.execute("UPDATE account_move SET warranty_posted_at = NULL WHERE id = %s",
                            [invoice.id])
        invoice.invalidate_recordset()
        card.invalidate_recordset()
        self.assertEqual(invoice._warranty_posting_info(), (False, False))
        self.assertFalse(card.expected_start_date)
        self.assertIn('cannot be established', ' '.join(card._get_missing_requirements()))
        card.with_user(self.corrector)._warranty_apply_exception(date(2026, 10, 2), 'Paper copy')
        self.assertEqual(card.state, 'ready')

    def test_11_credit_note_after_confirmation(self):
        """SD-13 / Q16: chatter note, log and activity; dates unchanged."""
        self.company.warranty_service_alert_user_ids = self.corrector
        ac = self._product('SD AC Rev', criterion='invoice')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        invoice = self._invoice(order, when='2026-10-01 05:00:00')
        card.action_confirm_warranty()
        refund = self._refund(invoice)
        self.assertEqual((card.state, card.warranty_start_date), ('confirmed', date(2026, 10, 1)))
        log = card.date_log_ids.filtered(lambda l: l.event == 'invoice_reversal')
        self.assertEqual(log.invoice_id, refund)
        self.assertIn(refund.name, self._notes(card))
        self.assertEqual(card.activity_ids.user_id, self.corrector)

    # ------------------------------------------------------------------ protection / audit
    def test_12_confirmed_dates_protected(self):
        """SD-15: confirmed dates and sources are refused for users, sudo and import."""
        ac = self._product('SD AC Lock')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        card.action_confirm_warranty()
        for vals in ({'warranty_start_date': date(2020, 1, 1)},
                     {'warranty_end_date': date(2030, 1, 1)},
                     {'installation_date': date(2020, 1, 1)},
                     {'start_date_source': 'custom'},
                     {'start_criterion': 'invoice'}):
            with self.assertRaises(UserError):
                card.sudo().write(vals)
        with self.assertRaises(UserError):
            card.unit_warranty_ids.sudo().write({'start_date': date(2020, 1, 1)})
        xmlid = card.export_data(['id'])['datas'][0][0]
        result = self.env['warranty.card'].load(['id', 'warranty_end_date'],
                                                [[xmlid, '2030-01-01']])
        self.assertTrue(result['messages'], 'import refused')
        self.assertEqual(card.warranty_end_date, date(2027, 10, 25))
        with self.assertRaises(UserError):
            card.date_log_ids.write({'reason': 'changed'})
        with self.assertRaises(AccessError):
            card.date_log_ids.with_user(self.plain_user).unlink()

    def test_13_custom_and_usage_unchanged(self):
        """SD-16 / SD-17: Custom Date Range manual dates; Usage basis without end date."""
        custom = self._product('SD AC Custom', criterion='custom')
        order = self._order([(custom, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        card.write({'warranty_start_date': date(2026, 9, 1), 'warranty_end_date': date(2028, 8, 31)})
        self.assertEqual(card.expected_end_date, date(2028, 8, 31))
        card.action_confirm_warranty()
        self.assertEqual((card.warranty_start_date, card.warranty_end_date, card.start_date_source),
                         (date(2026, 9, 1), date(2028, 8, 31), 'custom'))
        usage_policy = self.env['warranty.policy'].create({
            'name': 'SD Usage Policy', 'warranty_duration': 12, 'warranty_duration_unit': 'months',
            'warranty_basis': 'usage', 'start_date_basis': 'delivery', 'usage_limit': 1000,
            'usage_unit': 'operating_hours'})
        usage = self._product('SD AC Usage', categ_id=self.env['product.category'].create({
            'name': 'SD Usage', 'warranty_policy_id': usage_policy.id}).id)
        order = self._order([(usage, 1)])
        card = order.warranty_card_ids
        self._deliver(order, when='2026-10-01 05:00:00')
        card.action_confirm_warranty()
        self.assertEqual((card.warranty_start_date, card.warranty_end_date),
                         (date(2026, 10, 1), False))

    def test_14_installation_without_fsm(self):
        """Installation basis: Pending Installation until the installation is recorded (core:
        authorized exception only); the installation date is not entered manually."""
        ac = self._product('SD AC Inst', criterion='installation')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self.assertEqual(card.state, 'draft')
        self._deliver(order)
        self.assertEqual(card.state, 'pending_installation')
        with self.assertRaises(UserError):
            card.installation_date = date(2026, 10, 1)
        set_installation(card, date(2026, 10, 2))
        self.assertEqual((card.state, card.installation_date), ('ready', date(2026, 10, 2)))
        card.action_confirm_warranty()
        self.assertEqual(card.warranty_start_date, date(2026, 10, 2))

    def test_15_correction(self):
        """SD-19 / SD-20 / D10 / Q11 / Q12: correction of a confirmed card."""
        policy = self.env['warranty.policy'].create({
            'name': 'SD Service Policy', 'warranty_duration': 12,
            'warranty_duration_unit': 'months', 'start_date_basis': 'delivery',
            'free_service_count': 3, 'free_service_period': 12,
            'free_service_period_unit': 'months', 'schedule_method': 'equal_interval',
            'auto_create_services': True})
        ac = self._product('SD AC Corr', categ_id=self.env['product.category'].create({
            'name': 'SD Services', 'warranty_policy_id': policy.id}).id)
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order, when='2026-10-01 05:00:00')
        card.action_confirm_warranty()
        services = card.service_entitlement_ids.sorted('service_no')
        self.assertEqual(services.mapped('due_date'),
                         [date(2027, 2, 1), date(2027, 6, 1), date(2027, 10, 1)])
        self.env['warranty.service.entitlement.due.date.wizard'].create({
            'entitlement_id': services[1].id, 'new_due_date': date(2027, 7, 15),
            'reason': 'Customer request'}).action_apply()
        with self.assertRaisesRegex(UserError, 'Date Correction'):
            card.with_user(self.plain_user).action_open_date_wizard()
        action = card.with_user(self.corrector).action_open_date_wizard()
        self.assertEqual(action['context']['default_mode'], 'correction')
        wizard = self.env['warranty.card.date.wizard'].with_user(self.corrector).create({
            'card_id': card.id, 'mode': 'correction', 'new_start_date': date(2026, 9, 1),
            'reason': 'Delivery validated late in the system'})
        self.assertEqual(wizard.expected_end_date, date(2027, 8, 31))
        self.assertIn(services[1].name, wizard.entitlement_note)
        pdf = card.sudo().pdf_attachment_id
        wizard.action_apply()
        self.assertEqual((card.warranty_start_date, card.warranty_end_date),
                         (date(2026, 9, 1), date(2027, 8, 31)))
        self.assertEqual(card.unit_warranty_ids.start_date, date(2026, 9, 1))
        self.assertEqual(services.mapped('due_date'),
                         [date(2027, 1, 1), date(2027, 7, 15), date(2027, 9, 1)],
                         'manually re-dated service kept')
        log = card.date_log_ids.filtered(lambda l: l.event == 'correction')
        self.assertEqual((log.old_start, log.new_start, log.user_id),
                         (date(2026, 10, 1), date(2026, 9, 1), self.corrector))
        self.assertEqual(card.sudo().pdf_attachment_id, pdf, 'same protected attachment')
        self.assertEqual(card.print_count, 0)
        with self.assertRaisesRegex(UserError, 'current warranty dates'):
            card.with_user(self.corrector)._warranty_correct_dates(date(2026, 9, 1), 'again')

    def test_16_existing_confirmed_card_unchanged(self):
        """SD-22: cards confirmed before the automation keep their values (no source)."""
        ac = self._product('SD AC Legacy')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order, when='2026-10-01 05:00:00')
        card.action_confirm_warranty()
        self.env.flush_all()
        self.env.cr.execute("""UPDATE warranty_card SET start_date_source = NULL,
            source_picking_id = NULL, source_datetime = NULL, source_verification = NULL
            WHERE id = %s""", [card.id])
        card.invalidate_recordset()
        self.assertEqual(card.expected_start_date, date(2026, 10, 1))
        self.assertIn('Not recorded', card.start_source_note)
        self.assertEqual(card.state, 'confirmed')
