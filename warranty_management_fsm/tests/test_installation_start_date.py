import base64
from datetime import date, datetime
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group

SIGNATURE = base64.b64encode(b'customer signature')


@tagged('post_install', '-at_install', 'warranty_installation_start')
class TestInstallationStartDate(TransactionCase):
    """Installation basis of the Warranty Start Date Automation (start_date_design.md §7.3,
    IN-xx)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.project = cls.env['project.project'].create({
            'name': 'Warranty Installations', 'is_fsm': True, 'allow_billable': True,
            'company_id': cls.company.id})
        cls.company.write({
            'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'installation',
            'default_warranty_duration': 0,
            'warranty_timezone': 'Asia/Colombo',
            'warranty_signoff_required': False,
            'warranty_fsm_project_id': cls.project.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Installation Customer'})
        cls.stock_location = cls.env.ref('stock.stock_location_stock')
        cls.ac = cls._product('IN Split AC')
        cls.other = cls._product('IN Water Heater')
        cls.install = cls.env['product.product'].create({
            'name': 'AC Installation', 'type': 'service', 'invoice_policy': 'order',
            'service_tracking': 'task_global_project', 'project_id': cls.project.id,
            'warranty_installation_service': True,
            'warranty_installation_product_ids': [Command.set(cls.ac.product_tmpl_id.ids)]})
        cls.repair = cls.env['product.product'].create({
            'name': 'AC Repair Visit', 'type': 'service', 'invoice_policy': 'order',
            'service_tracking': 'task_global_project', 'project_id': cls.project.id})
        cls.corrector = cls.env['res.users'].create({
            'name': 'Installation Date Corrector', 'login': 'win_corrector',
            'groups_id': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('industry_fsm.group_fsm_user').id,
                cls.env.ref('warranty_management.group_warranty_date_correction').id])]})
        cls.technician = cls.env['res.users'].create({
            'name': 'Installation Technician', 'login': 'win_technician',
            'groups_id': [Command.set([cls.env.ref('industry_fsm.group_fsm_user').id])]})

    @classmethod
    def _product(cls, name):
        product = cls.env['product.product'].create({
            'name': name, 'type': 'consu', 'is_storable': True, 'invoice_policy': 'order',
            'warranty_applicable': True, 'warranty_start_criterion': 'installation',
            'default_warranty_period': 12, 'default_warranty_period_unit': 'months'})
        cls.env['stock.quant']._update_available_quantity(product, cls.stock_location, 20)
        return product

    def _order(self, lines, grouping='per_so'):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': qty})
                           for product, qty in lines],
        })
        confirm_and_group(order, grouping)
        return order

    def _deliver(self, order, when='2026-10-01 05:00:00'):
        picking = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))[:1]
        picking.action_assign()
        for move in picking.move_ids:
            move.picked = True
        with freeze_time(when):
            res = picking.button_validate()
            if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
                Form(self.env[res['res_model']].with_context(res['context'])).save().process()
        return picking

    def _tasks(self, order):
        return order.order_line.task_id.filtered(
            lambda task: task.warranty_task_purpose == 'installation')

    def _complete(self, task, when):
        with freeze_time(when):
            task.write({'state': '1_done'})

    # ------------------------------------------------------------------ tests
    def test_01_identification_and_relevant_links(self):
        """IN-01 / IN-05 / Q8: flagged service -> installation task linked only to the cards of
        the products it installs; the repair task is not an installation task."""
        order = self._order([(self.ac, 1), (self.other, 1), (self.install, 1), (self.repair, 1)],
                            grouping='per_product')
        task = self._tasks(order)
        repair_task = order.order_line.filtered(lambda l: l.product_id == self.repair).task_id
        self.assertEqual(len(task), 1)
        self.assertTrue(task.is_fsm)
        self.assertFalse(repair_task.warranty_task_purpose)
        ac_card = order.warranty_card_ids.filtered(lambda c: c.product_id == self.ac)
        other_card = order.warranty_card_ids - ac_card
        self.assertEqual(task.warranty_installation_card_ids, ac_card)
        self.assertEqual(ac_card.installation_task_ids, task)
        self.assertFalse(other_card.installation_task_ids, 'unrelated card never linked')
        self.assertIn('no installation Field Service task', other_card.missing_requirements)
        with self.assertRaises(ValidationError) as error:
            repair_task.sudo()._warranty_system_write(
                {'warranty_installation_card_ids': [Command.link(other_card.id)]})
        self.assertIn('Only installation tasks', str(error.exception))
        self.assertFalse(other_card.installation_task_ids)
        self._deliver(order)
        self._complete(repair_task, '2026-10-02 05:00:00')
        self.assertEqual(other_card.state, 'pending_installation', 'repair never activates')

    def test_02_completion_activates_once(self):
        """IN-02 / D6 / D7: Pending Installation until the task is done; then automatic
        confirmation from the completion time (Warranty Timezone), exactly once."""
        order = self._order([(self.ac, 1), (self.install, 1)])
        card, task = order.warranty_card_ids, self._tasks(order)
        self._deliver(order)
        self.assertEqual(card.state, 'pending_installation')
        self.assertIn(task.name, card.missing_requirements)
        self._complete(task.with_user(self.technician), '2026-10-04 20:00:00')  # 01:30 Colombo
        self.assertEqual(task.warranty_installation_done_at, datetime(2026, 10, 4, 20, 0))
        self.assertEqual((card.state, card.installation_date, card.warranty_start_date,
                          card.warranty_end_date),
                         ('confirmed', date(2026, 10, 5), date(2026, 10, 5), date(2027, 10, 4)))
        self.assertEqual((card.start_date_source, card.source_task_id),
                         ('installation', task))
        self.assertIn(task.name, card.start_source_note)
        activation = card.date_log_ids.filtered(lambda l: l.event == 'activation')
        self.assertEqual(len(activation), 1)
        self.assertEqual(activation.user_id, self.technician)
        # Reopened and completed again after confirmation: note only, no second activation.
        with freeze_time('2026-10-10 05:00:00'):
            task.write({'state': '01_in_progress'})
        self._complete(task, '2026-10-11 05:00:00')
        self.assertEqual((card.warranty_start_date, task.warranty_installation_done_at),
                         (date(2026, 10, 5), datetime(2026, 10, 4, 20, 0)))
        self.assertEqual(len(card.date_log_ids.filtered(lambda l: l.event == 'activation')), 1)
        self.assertIn('task_reopened', card.date_log_ids.mapped('event'))

    def test_03_waits_for_all_tasks(self):
        """IN-03 / D5: two installation tasks -> the card waits for both; latest completion."""
        second = self.env['product.product'].create({
            'name': 'Outdoor Unit Installation', 'type': 'service', 'invoice_policy': 'order',
            'service_tracking': 'task_global_project', 'project_id': self.project.id,
            'warranty_installation_service': True,
            'warranty_installation_product_ids': [Command.set(self.ac.product_tmpl_id.ids)]})
        order = self._order([(self.ac, 1), (self.install, 1), (second, 1)])
        card, tasks = order.warranty_card_ids, self._tasks(order)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(card.installation_task_ids, tasks)
        self._deliver(order)
        self._complete(tasks[0], '2026-10-03 05:00:00')
        self.assertEqual(card.state, 'pending_installation')
        self._complete(tasks[1], '2026-10-06 05:00:00')
        self.assertEqual((card.state, card.warranty_start_date), ('confirmed', date(2026, 10, 6)))
        self.assertEqual(card.source_task_id, tasks[1])

    def test_04_one_task_two_cards(self):
        """IN-04: one task covers both relevant cards of its Sales Order (per unit grouping);
        cards of another Sales Order cannot be linked."""
        order = self._order([(self.ac, 2), (self.install, 1)], grouping='per_unit')
        cards, task = order.warranty_card_ids, self._tasks(order)
        self.assertEqual(len(cards), 2)
        self.assertEqual(task.warranty_installation_card_ids, cards)
        self._deliver(order)
        self._complete(task, '2026-10-03 05:00:00')
        self.assertEqual(set(cards.mapped('state')), {'confirmed'})
        other_order = self._order([(self.ac, 1)])
        with self.assertRaisesRegex(ValidationError, 'own Sales Order'):
            task.sudo()._warranty_system_write(
                {'warranty_installation_card_ids': [Command.link(other_order.warranty_card_ids.id)]})

    def test_05_signoff_required(self):
        """IN-06 / Q6: Customer Sign-off Required -> no completion without the signature."""
        self.company.warranty_signoff_required = True
        order = self._order([(self.ac, 1), (self.install, 1)])
        card, task = order.warranty_card_ids, self._tasks(order)
        self._deliver(order)
        with self.assertRaises(UserError) as error:
            self._complete(task, '2026-10-03 05:00:00')
        self.assertIn('sign-off', str(error.exception))
        self.assertEqual((task.state, task.warranty_installation_done_at), ('01_in_progress', False))
        task.worksheet_signature = SIGNATURE
        with freeze_time('2026-10-03 06:00:00'):
            task.action_fsm_validate()
        self.assertEqual((card.state, card.warranty_start_date), ('confirmed', date(2026, 10, 3)))

    def test_06_delivery_after_completion(self):
        """IN-07 / IN-08 / Q7: completed before the delivery -> Draft; reopened -> waits; the
        original completion is kept; the delivery then activates the card."""
        order = self._order([(self.ac, 1), (self.install, 1)])
        card, task = order.warranty_card_ids, self._tasks(order)
        self._complete(task, '2026-10-02 05:00:00')
        self.assertEqual(card.state, 'draft', 'delivery still missing')
        self.assertEqual(card.installation_date, date(2026, 10, 2))
        with freeze_time('2026-10-03 05:00:00'):
            task.write({'state': '01_in_progress'})
        self.assertFalse(card.installation_date)
        self._complete(task, '2026-10-07 05:00:00')
        self.assertEqual(task.warranty_installation_done_at, datetime(2026, 10, 2, 5, 0))
        self.assertEqual(card.installation_date, date(2026, 10, 2), 'original completion kept')
        self.assertIn('original completion', ' '.join(card.message_ids.mapped('body')))
        self._deliver(order, when='2026-10-08 05:00:00')
        self.assertEqual((card.state, card.warranty_start_date), ('confirmed', date(2026, 10, 2)))

    def test_07_cancelled_task_and_exception(self):
        """IN-09 / D8: all tasks cancelled -> Pending Installation; exception -> manual Confirm."""
        order = self._order([(self.ac, 1), (self.install, 1)])
        card, task = order.warranty_card_ids, self._tasks(order)
        self._deliver(order)
        task.write({'state': '1_canceled'})
        self.assertEqual(card.state, 'pending_installation')
        self.assertIn('task_cancelled', card.date_log_ids.mapped('event'))
        with self.assertRaisesRegex(UserError, 'Date Correction'):
            card.with_user(self.technician)._warranty_apply_exception(date(2026, 10, 9), 'x')
        card.with_user(self.corrector)._warranty_apply_exception(
            date(2026, 10, 9), 'Installed by the dealer, report received')
        self.assertEqual((card.state, card.installation_date), ('ready', date(2026, 10, 9)))
        card.action_confirm_warranty()
        self.assertEqual((card.warranty_start_date, card.start_date_source),
                         (date(2026, 10, 9), 'exception'))

    def test_08_create_installation_task_button(self):
        """IN-10 / Q9: Create Installation Task -> task in the Warranty Field Service Project,
        linked to this card only; its completion activates the card."""
        order = self._order([(self.ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        action = card.with_user(self.corrector).action_create_installation_task()
        task = self.env['project.task'].browse(action['res_id'])
        self.assertEqual((task.project_id, task.warranty_task_purpose,
                          task.warranty_installation_card_ids),
                         (self.project, 'installation', card))
        self._complete(task, '2026-10-05 05:00:00')
        self.assertEqual((card.state, card.warranty_start_date), ('confirmed', date(2026, 10, 5)))
        with self.assertRaises(UserError):
            card.action_create_installation_task()

    def test_09_protection(self):
        """IN-11: installation date, purpose, completion time and links are not user data."""
        order = self._order([(self.ac, 1), (self.install, 1)])
        card, task = order.warranty_card_ids, self._tasks(order)
        with self.assertRaises(UserError):
            card.installation_date = date(2026, 10, 1)
        with self.assertRaises(UserError):
            task.warranty_installation_done_at = datetime(2026, 10, 1)
        with self.assertRaises(UserError):
            task.warranty_task_purpose = False
        with self.assertRaises(UserError):
            card.write({'installation_task_ids': [Command.clear()]})
        with self.assertRaisesRegex(UserError, 'Date Correction'):
            task.with_user(self.technician).write(
                {'warranty_installation_card_ids': [Command.clear()]})
        task.with_user(self.corrector).write({'warranty_installation_card_ids': [Command.clear()]})
        self.assertFalse(card.installation_task_ids)
        self.assertIn('source_change', card.date_log_ids.mapped('event'))
        with self.assertRaises(UserError):
            self.env['project.task'].create({
                'name': 'Fake installation', 'project_id': self.project.id,
                'warranty_task_purpose': 'installation'})

    def test_10_auto_confirm_failure(self):
        """IN-12: an activation refused by the confirmation leaves the task done and the card
        Ready, with a note and an activity."""
        self.company.warranty_service_alert_user_ids = self.corrector
        order = self._order([(self.ac, 1), (self.install, 1)])
        card, task = order.warranty_card_ids, self._tasks(order)
        self._deliver(order)
        with patch.object(type(card), '_generate_soft_copy',
                          side_effect=UserError('PDF service unavailable')):
            self._complete(task, '2026-10-03 05:00:00')
        self.assertEqual((task.state, card.state), ('1_done', 'ready'))
        self.assertIn('activation_failed', card.date_log_ids.mapped('event'))
        self.assertEqual(card.activity_ids.user_id, self.corrector)
        card.action_confirm_warranty()
        self.assertEqual(card.warranty_start_date, date(2026, 10, 3))

    def test_11_product_flag_constraint(self):
        """IN-13: only Field Service task services can be Warranty Installation Services."""
        with self.assertRaises(ValidationError):
            self.env['product.product'].create({
                'name': 'Bad installation', 'type': 'consu',
                'warranty_installation_service': True})
