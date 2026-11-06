from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged

from .common import confirm_and_group, set_installation


@tagged('post_install', '-at_install', 'warranty_part2')
class TestWarrantyFreeServiceScheduling(TransactionCase):
    """Free service Schedule / Reschedule, Free Service Calendar and S2 monitoring of
    Scheduled / Rescheduled services (approved S1-S7, S2, R1)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.coordinator = cls.env['res.users'].create({
            'name': 'Schedule Coordinator', 'login': 'warranty_schedule_coordinator',
            'email': 'coordinator@example.com',
            'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
            'groups_id': [(6, 0, cls.env.ref('base.group_user').ids)],
        })
        cls.company.write({
            'warranty_scope_mode': 'free_services',
            'warranty_auto_create_services': False,
            'default_warranty_policy_id': False,
            'default_warranty_basis': 'period',
            'default_start_criterion': 'installation',
            'default_warranty_duration': 0,
            'warranty_service_alert_user_ids': [(5, 0, 0)],
            'warranty_timezone': 'Asia/Colombo',
            'email': 'warranty@example.com',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Scheduling Customer'})
        cls.policy = cls.env['warranty.policy'].create({
            'name': 'Scheduling Policy', 'warranty_duration': 12,
            'warranty_duration_unit': 'months', 'free_service_count': 3,
            'free_service_period': 12, 'free_service_period_unit': 'months',
            'schedule_method': 'equal_interval', 'auto_create_services': True,
            'grace_period_days': 30, 'auto_expire_services': True,
            'service_due_alert_days': 14, 'expiry_reminder_days': 7,
            'service_alert_user_ids': [(6, 0, cls.coordinator.ids)],
        })
        cls.categ = cls.env['product.category'].create({
            'name': 'Scheduling ACs', 'warranty_policy_id': cls.policy.id})
        cls.Entitlement = cls.env['warranty.service.entitlement']
        cls.due_type = cls.env.ref('warranty_management.mail_activity_type_free_service_due')
        cls.expiry_type = cls.env.ref('warranty_management.mail_activity_type_free_service_expiry')

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _today(self, today):
        with patch.object(type(self.env['res.company']), '_warranty_today',
                          lambda company, log_missing_timezone=False: today):
            yield

    def _first(self):
        """Service 1 of a new card started 2026-07-15: due 2026-11-15, grace end 2026-12-15,
        due alert 2026-11-01, expiry reminder 2026-12-08."""
        product = self.env['product.product'].create({
            'name': 'Scheduling AC', 'type': 'service', 'categ_id': self.categ.id,
            'warranty_applicable': True})
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, date(2026, 7, 15))
        card.action_confirm_warranty()
        service = card.service_entitlement_ids.filtered(lambda e: e.service_no == 1)
        self.assertEqual((service.due_date, service.grace_period_end_date),
                         (date(2026, 11, 15), date(2026, 12, 15)))
        return service

    def _run(self, today):
        with self._today(today):
            self.Entitlement._cron_monitor_free_services()

    def _schedule(self, service, today, scheduled_date, reason=False):
        with self._today(today):
            action = service.action_open_schedule_wizard()
            wizard = service.env[action['res_model']].with_context(action['context']).create({
                'scheduled_date': scheduled_date, 'reason': reason})
            wizard.action_confirm()
        return action

    def _activities(self, service, activity_type, active=None):
        domain = [('res_model', '=', service._name), ('res_id', '=', service.id),
                  ('activity_type_id', '=', activity_type.id)]
        if active is not None:
            domain.append(('active', '=', active))
        return self.env['mail.activity'].with_context(active_test=False).search(domain)

    def _emails(self, service, text):
        return self.env['mail.mail'].search([
            ('model', '=', service._name), ('res_id', '=', service.id),
            ('subject', 'ilike', text)])

    # ------------------------------------------------------------------ schedule
    def test_01_schedule(self):
        """Schedule: wizard defaults to the due date; status Scheduled, Scheduled Service
        Date, one history line; Due Date unchanged; open due alert activities Done "Service
        scheduled"; never Completed."""
        service = self._first()
        self._run(date(2026, 11, 1))
        due_activity = self._activities(service, self.due_type, active=True)
        self.assertTrue(due_activity)
        mails_before = self.env['mail.mail'].search_count([('model', '=', service._name)])

        with self._today(date(2026, 11, 1)):
            action = service.action_open_schedule_wizard()
            self.assertEqual(action['name'], 'Schedule Free Service')
            wizard = Form(self.env[action['res_model']].with_context(action['context']))
            self.assertEqual((wizard.scheduled_date, wizard.mode), (date(2026, 11, 15), 'schedule'))
            wizard.scheduled_date = date(2026, 11, 20)
            wizard.save().action_confirm()

        self.assertEqual((service.state, service.scheduled_date, service.due_date),
                         ('scheduled', date(2026, 11, 20), date(2026, 11, 15)))
        log = service.schedule_log_ids
        self.assertEqual((len(log), log.action, log.previous_scheduled_date, log.scheduled_date,
                          log.user_id), (1, 'schedule', False, date(2026, 11, 20), self.env.user))
        self.assertEqual(service.reschedule_count, 0)
        self.assertFalse(due_activity.active, 'due alert activity marked Done')
        self.assertTrue(service.message_ids.filtered(
            lambda m: 'Service scheduled' in (m.body or '')), 'Done note in the chatter')
        self.assertEqual(self.env['mail.mail'].search_count([('model', '=', service._name)]),
                         mails_before, 'no new due alert email')
        self.assertNotEqual(service.state, 'completed')

    def test_02_reschedule(self):
        """Reschedule: reason required, another date required; status Rescheduled, date
        moved, history kept, Reschedule Count; still one calendar entry."""
        service = self._first()
        self._schedule(service, date(2026, 11, 1), date(2026, 11, 20))
        with self.assertRaises(UserError):
            self._schedule(service, date(2026, 11, 2), date(2026, 11, 25))
        with self.assertRaises(UserError):
            self._schedule(service, date(2026, 11, 2), date(2026, 11, 20), 'Same day')
        action = self._schedule(service, date(2026, 11, 2), date(2026, 11, 25), 'Customer away')
        self.assertEqual(action['name'], 'Reschedule Free Service')
        self.assertEqual((service.state, service.scheduled_date, service.due_date,
                          service.reschedule_count),
                         ('rescheduled', date(2026, 11, 25), date(2026, 11, 15), 1))
        logs = service.schedule_log_ids.sorted('id')
        self.assertEqual([(l.action, l.previous_scheduled_date, l.scheduled_date, l.reason or False)
                          for l in logs],
                         [('schedule', False, date(2026, 11, 20), False),
                          ('reschedule', date(2026, 11, 20), date(2026, 11, 25), 'Customer away')])
        self._schedule(service, date(2026, 11, 3), date(2026, 11, 27), 'Technician change')
        self.assertEqual((service.state, service.reschedule_count), ('rescheduled', 2))
        self.assertEqual(self.Entitlement.search_count([
            ('id', '=', service.id), ('scheduled_date', '!=', False)]), 1)
        self.assertEqual(self.Entitlement.search([
            ('warranty_card_id', '=', service.warranty_card_id.id),
            ('scheduled_date', '>=', date(2026, 11, 1)),
            ('scheduled_date', '<=', date(2026, 11, 30))]), service, 'one calendar entry')

    def test_03_validations(self):
        """No past date; not after the Grace Period End; no direct / drag-and-drop date write;
        Completed / Expired / Cancelled / In Progress cannot be scheduled; Missed only within
        the grace period."""
        service = self._first()
        with self.assertRaises(UserError):
            self._schedule(service, date(2026, 11, 10), date(2026, 11, 9))
        with self.assertRaises(UserError):
            self._schedule(service, date(2026, 11, 10), date(2026, 12, 16))
        with self.assertRaises(UserError):
            service.write({'scheduled_date': date(2026, 11, 20)})
        self._schedule(service, date(2026, 11, 10), date(2026, 12, 15))
        with self.assertRaises(UserError):
            service.write({'scheduled_date': date(2026, 11, 21)})  # calendar drag-and-drop
        self.assertEqual(service.scheduled_date, date(2026, 12, 15))

        for state in ('completed', 'expired', 'cancelled', 'in_progress'):
            other = self._first()
            other.state = state
            with self.assertRaises(UserError):
                self._schedule(other, date(2026, 11, 10), date(2026, 11, 20))

        # Auto-expire off: Missed after the grace period cannot be scheduled any more.
        self.policy.auto_expire_services = False
        missed = self._first()
        self._run(date(2026, 11, 16))
        self.assertEqual(missed.state, 'missed')
        self._run(date(2026, 12, 20))
        self.assertEqual(missed.state, 'missed')
        with self.assertRaises(UserError):
            self._schedule(missed, date(2026, 12, 20), date(2026, 12, 21))

    # ------------------------------------------------------------------ S2 monitoring
    def test_04_s2_transitions(self):
        """Approved example: Scheduled while the booked date is ahead; Missed when the booked
        date and the due date have passed; rescheduled within the grace period (Rescheduled);
        Missed again; expiry reminder (existing rule); Expired after the grace period with the
        Expired email; history and dates kept."""
        service = self._first()
        self._run(date(2026, 11, 1))
        self._schedule(service, date(2026, 11, 10), date(2026, 11, 20))
        self._run(date(2026, 11, 16))
        self.assertEqual(service.state, 'scheduled', 'booked date still ahead')
        self.assertEqual(service.due_status, 'overdue', 'due indicator unchanged')
        self._run(date(2026, 11, 20))
        self.assertEqual(service.state, 'scheduled')
        self._run(date(2026, 11, 21))
        self.assertEqual(service.state, 'missed')
        self._schedule(service, date(2026, 11, 25), date(2026, 12, 5), 'Customer away')
        self.assertEqual(service.state, 'rescheduled')
        self._run(date(2026, 12, 6))
        self.assertEqual(service.state, 'missed')
        self._run(date(2026, 12, 8))
        self.assertTrue(service.expiry_reminder_sent)
        self.assertEqual(len(self._activities(service, self.expiry_type)), 1)
        self.assertEqual(len(self._emails(service, 'expires after')), 1)
        self._run(date(2026, 12, 16))
        self.assertEqual(service.state, 'expired')
        self.assertEqual(len(self._emails(service, 'EXPIRED')), 1)
        self.assertFalse(self._activities(service, self.expiry_type, active=True))
        self.assertEqual((service.due_date, service.scheduled_date, len(service.schedule_log_ids)),
                         (date(2026, 11, 15), date(2026, 12, 5), 2))
        with self.assertRaises(UserError):
            self._schedule(service, date(2026, 12, 16), date(2026, 12, 17), 'Too late')

    def test_05_booked_before_due_date(self):
        """Booked before the due date and not done: stays Scheduled until the due date has
        passed as well, then Missed."""
        service = self._first()
        self._schedule(service, date(2026, 11, 5), date(2026, 11, 10))
        self._run(date(2026, 11, 11))
        self.assertEqual(service.state, 'scheduled')
        self._run(date(2026, 11, 16))
        self.assertEqual(service.state, 'missed')

    def test_06_r1_reminder_kept_no_duplicates(self):
        """R1: rescheduling a Missed service keeps its open expiry reminder; no duplicate
        reminder activity or email when it becomes Missed again."""
        service = self._first()
        self._run(date(2026, 11, 16))
        self._run(date(2026, 12, 8))
        reminder = self._activities(service, self.expiry_type, active=True)
        self.assertEqual((service.state, len(reminder)), ('missed', 1))
        self._schedule(service, date(2026, 12, 9), date(2026, 12, 12))
        self.assertEqual(service.state, 'scheduled', 'first schedule of a Missed service')
        self.assertTrue(reminder.active, 'expiry reminder left open')
        self._run(date(2026, 12, 10))
        self._run(date(2026, 12, 13))
        self.assertEqual(service.state, 'missed')
        self.assertEqual(len(self._activities(service, self.expiry_type)), 1)
        self.assertEqual(len(self._emails(service, 'expires after')), 1)

    def test_07_late_run_and_blocked(self):
        """Late run after the grace period: Scheduled -> Expired directly (existing rule);
        merged services are never changed; Carry-forward keeps them Missed."""
        late = self._first()
        self._schedule(late, date(2026, 11, 10), date(2026, 11, 20))
        self._run(date(2026, 12, 20))
        self.assertEqual(late.state, 'expired')

        merged = self._first()
        self._schedule(merged, date(2026, 11, 10), date(2026, 11, 20))
        merged.merge_status = 'selected'
        self._run(date(2026, 12, 20))
        self.assertEqual(merged.state, 'scheduled')

        self.policy.carry_forward_allowed = True
        carried = self._first()
        self._schedule(carried, date(2026, 11, 10), date(2026, 11, 20))
        self._run(date(2026, 12, 20))
        self.assertEqual(carried.state, 'missed')

    # ------------------------------------------------------------------ views
    def test_08_views_and_calendar(self):
        """Form buttons, Schedule History tab, Free Service Calendar (scheduled date, no quick
        create) and its menu; wizard shows the services already scheduled in the month."""
        Views = self.env.ref
        form = etree.fromstring(Views(
            'warranty_management.warranty_service_entitlement_view_form').arch)
        buttons = form.xpath("//button[@name='action_open_schedule_wizard']")
        self.assertEqual([b.get('string') for b in buttons], ['Schedule', 'Reschedule'])
        self.assertTrue(form.xpath("//page[@name='schedule_history']"))
        calendar = etree.fromstring(Views(
            'warranty_management.warranty_service_entitlement_view_calendar').arch)
        self.assertEqual((calendar.get('date_start'), calendar.get('quick_create'),
                          calendar.get('create')), ('scheduled_date', '0', '0'))
        action = Views('warranty_management.action_warranty_service_entitlement_calendar')
        self.assertTrue(action.view_mode.startswith('calendar'))
        self.assertEqual(Views('warranty_management.menu_warranty_service_entitlement_calendar')
                         .action, action)
        self.assertIn('calendar', Views(
            'warranty_management.action_warranty_service_entitlement').view_mode)

        first, second = self._first(), self._first()
        self._schedule(first, date(2026, 11, 1), date(2026, 11, 20))
        with self._today(date(2026, 11, 1)):
            wizard = self.env['warranty.service.entitlement.schedule.wizard'].create({
                'entitlement_id': second.id, 'scheduled_date': date(2026, 11, 3)})
            self.assertEqual(wizard.month_entitlement_ids, first)
            wizard.scheduled_date = date(2026, 12, 3)
            self.assertFalse(wizard.month_entitlement_ids)

    def test_09_internal_user_and_history_company(self):
        """An internal user schedules (due alert activities of another user are closed); the
        history belongs to the service company."""
        service = self._first()
        self._run(date(2026, 11, 1))
        user = self.env['res.users'].create({
            'name': 'Scheduling Clerk', 'login': 'warranty_schedule_clerk',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, self.env.ref('base.group_user').ids)]})
        self._schedule(service.with_user(user), date(2026, 11, 1), date(2026, 11, 22))
        self.assertEqual((service.state, service.schedule_log_ids.user_id,
                          service.schedule_log_ids.company_id),
                         ('scheduled', user, self.company))
        self.assertFalse(self._activities(service, self.due_type, active=True))
        self.assertTrue(self.env.ref(
            'warranty_management.warranty_entitlement_schedule_log_company_rule'))
