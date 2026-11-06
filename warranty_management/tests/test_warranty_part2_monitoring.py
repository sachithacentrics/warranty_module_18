from datetime import date
from unittest.mock import patch

from freezegun import freeze_time
from lxml import etree

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

ENTITLEMENT_LOGGER = 'odoo.addons.warranty_management.models.warranty_service_entitlement'
COMPANY_LOGGER = 'odoo.addons.warranty_management.models.res_company'

from .common import confirm_and_group, set_installation


@tagged('post_install', '-at_install', 'warranty_part2')
class TestWarrantyPart2Monitoring(TransactionCase):
    """Part 2 - Free service due monitoring: due indicator, due alerts, expiry reminders,
    grace period, Missed / Expired transitions (doc/part2_design_decisions.md)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.alert_user = cls.env['res.users'].create({
            'name': 'Service Coordinator', 'login': 'warranty_p2m_coordinator',
            'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
            'groups_id': [(6, 0, cls.env.ref('base.group_user').ids)],
        })
        cls.fallback_user = cls.env['res.users'].create({
            'name': 'Warranty Fallback', 'login': 'warranty_p2m_fallback',
            'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
            'groups_id': [(6, 0, cls.env.ref('base.group_user').ids)],
        })
        cls.company.write({
            'warranty_scope_mode': 'free_services',
            'warranty_auto_create_services': False,
            'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'installation',
            'default_warranty_duration': 0,
            'warranty_service_alert_user_ids': [(5, 0, 0)],
            'warranty_timezone': 'Asia/Colombo',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Monitoring Customer'})
        cls.retail = cls.env['product.pricelist'].create({'name': 'Retail Pricelist P2M'})
        cls.policy = cls.env['warranty.policy'].create({
            'name': 'Retail A/C Warranty Monitoring',
            'warranty_duration': 12,
            'warranty_duration_unit': 'months',
            'free_service_count': 3,
            'free_service_period': 12,
            'free_service_period_unit': 'months',
            'schedule_method': 'equal_interval',
            'auto_create_services': True,
            'grace_period_days': 30,
            'auto_expire_services': True,
            'carry_forward_allowed': False,
            'service_due_alert_days': 14,
            'expiry_reminder_days': 7,
            'usage_alert_percentage': 90,
            'service_alert_user_ids': [(6, 0, cls.alert_user.ids)],
        })
        cls.categ = cls.env['product.category'].create({
            'name': 'Air Conditioners P2M', 'warranty_policy_id': cls.policy.id})
        cls.Entitlement = cls.env['warranty.service.entitlement']
        cls.due_type = cls.env.ref('warranty_management.mail_activity_type_free_service_due')
        cls.expiry_type = cls.env.ref('warranty_management.mail_activity_type_free_service_expiry')

    # ------------------------------------------------------------------ helpers
    def _product(self, name, **vals):
        values = {
            'name': name,
            'type': 'service',
            'categ_id': self.categ.id,
            'warranty_applicable': True,
            'warranty_start_criterion': 'installation',
            'default_warranty_period': 12,
            'default_warranty_period_unit': 'months',
            'default_free_service_count': 3,
            'free_service_frequency': 4,
            'free_service_frequency_unit': 'months',
        }
        values.update(vals)
        return self.env['product.product'].create(values)

    def _card(self, name='AC Monitor', **product_vals):
        """Card started 2026-07-15: services due 2026-11-15, 2027-03-15, 2027-07-15."""
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'pricelist_id': self.retail.id,
            'order_line': [(0, 0, {'product_id': self._product(name, **product_vals).id,
                                   'product_uom_qty': 1})],
        })
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, date(2026, 7, 15))
        card.action_confirm_warranty()
        self.assertEqual(card.state, 'confirmed')
        return card

    def _first(self, card):
        return card.service_entitlement_ids.filtered(lambda e: e.service_no == 1)

    def _run(self, today):
        """Run the daily scheduled action as if the company's local date were `today`."""
        with patch.object(type(self.env['res.company']), '_warranty_today',
                          lambda company, log_missing_timezone=False: today):
            self.Entitlement._cron_monitor_free_services()

    def _activities(self, entitlement, activity_type, active=None):
        domain = [('res_model', '=', entitlement._name), ('res_id', '=', entitlement.id),
                  ('activity_type_id', '=', activity_type.id)]
        if active is not None:
            domain.append(('active', '=', active))
        return self.env['mail.activity'].with_context(active_test=False).search(domain)

    # ------------------------------------------------------------------ configuration
    def test_01_policy_and_company_validation(self):
        """Monitoring values must be valid; the responsible user must be an active internal
        user allowed in the company."""
        with self.assertRaises(ValidationError):
            self.policy.grace_period_days = -1
        with self.assertRaises(ValidationError):
            self.policy.expiry_reminder_days = -1
        with self.assertRaises(ValidationError):
            self.policy.usage_alert_percentage = 150
        portal_user = self.env['res.users'].create({
            'name': 'Portal', 'login': 'warranty_p2m_portal',
            'groups_id': [(6, 0, self.env.ref('base.group_portal').ids)],
        })
        with self.assertRaises(ValidationError):
            self.policy.service_alert_user_ids = portal_user
        other_company = self.env['res.company'].create({'name': 'Other Monitoring Company'})
        with self.assertRaises(ValidationError):
            self.policy.write({'company_id': other_company.id})
        with self.assertRaises(ValidationError):
            other_company.warranty_service_alert_user_ids = self.alert_user

    def test_02_snapshot_and_monitoring_dates(self):
        """Confirmation copies the monitoring values to the card; later policy changes do not
        affect it; grace end, alert and expiry reminder dates are calculated."""
        card = self._card()
        self.assertTrue(card.service_monitoring_active)
        self.assertEqual(
            (card.grace_period_days, card.auto_expire_services, card.carry_forward_allowed,
             card.service_due_alert_days, card.expiry_reminder_days,
             card.usage_alert_percentage, card.service_alert_user_ids),
            (30, True, False, 14, 7, 90, self.alert_user))
        first = self._first(card)
        self.assertEqual(
            (first.due_date, first.grace_period_end_date, first.alert_date,
             first.expiry_reminder_date),
            (date(2026, 11, 15), date(2026, 12, 15), date(2026, 11, 1), date(2026, 12, 8)))
        self.assertEqual(first.state, 'draft')
        self.assertFalse(first.due_status)

        self.policy.write({'grace_period_days': 5,
                           'service_alert_user_ids': self.fallback_user.ids})
        self.assertEqual((card.grace_period_days, card.service_alert_user_ids),
                         (30, self.alert_user), 'snapshot is not affected by policy changes')
        self.assertEqual(first.grace_period_end_date, date(2026, 12, 15))

    def test_03_zero_days_disable_reminders(self):
        """Service Due Alert Days = 0 and Expiry Reminder Days = 0 disable both activities."""
        self.policy.write({'service_due_alert_days': 0, 'expiry_reminder_days': 0})
        first = self._first(self._card())
        self.assertFalse(first.alert_date)
        self.assertFalse(first.expiry_reminder_date)
        for today in (date(2026, 11, 1), date(2026, 11, 15), date(2026, 12, 10)):
            self._run(today)
        self.assertFalse(first.activity_ids)
        self.assertFalse(self._activities(first, self.due_type))
        self.assertEqual(first.state, 'missed')

    # ------------------------------------------------------------------ indicator and alerts
    def test_04_due_indicator_and_single_due_alert(self):
        """Upcoming from the alert date, Due on the due date; the alert date does not change
        the status; exactly one due alert, assigned to the responsible user."""
        first = self._first(self._card())
        self._run(date(2026, 10, 31))
        self.assertFalse(first.due_status)
        self.assertFalse(first.activity_ids)

        self._run(date(2026, 11, 1))
        self.assertEqual((first.due_status, first.state), ('upcoming', 'draft'))
        alert = self._activities(first, self.due_type)
        self.assertEqual(len(alert), 1)
        self.assertEqual((alert.user_id, alert.date_deadline), (self.alert_user, date(2026, 11, 15)))
        self.assertEqual(first.due_alert_activity_ids, alert)
        self.assertTrue(first.due_alert_sent)

        self._run(date(2026, 11, 5))
        self._run(date(2026, 11, 15))
        self.assertEqual((first.due_status, first.state), ('due', 'draft'))
        self.assertEqual(len(self._activities(first, self.due_type)), 1, 'no duplicate alert')
        # The responsible user can open the entitlement of the activity.
        self.assertTrue(first.with_user(self.alert_user).read(['name']))

    def test_05_missed_reminder_expired_and_activity_closure(self):
        """Missed after the due date (within grace), one expiry reminder, Expired after the
        grace period; only the system activities are closed and kept as history."""
        card = self._card()
        first = self._first(card)
        self._run(date(2026, 11, 1))
        manual = first.activity_schedule('mail.mail_activity_data_todo', summary='Call customer',
                                         user_id=self.alert_user.id)

        self._run(date(2026, 11, 16))
        self.assertEqual((first.state, first.due_status), ('missed', 'overdue'))
        self.assertEqual((card.free_services_missed, card.free_services_balance), (1, 3))

        self._run(date(2026, 12, 7))
        self.assertFalse(self._activities(first, self.expiry_type))
        self._run(date(2026, 12, 8))
        self._run(date(2026, 12, 9))
        reminder = self._activities(first, self.expiry_type)
        self.assertEqual(len(reminder), 1, 'no duplicate reminder')
        self.assertEqual(reminder.date_deadline, date(2026, 12, 15))

        self._run(date(2026, 12, 15))
        self.assertEqual(first.state, 'missed', 'still within the grace period')
        self._run(date(2026, 12, 16))
        self.assertEqual(first.state, 'expired')
        self.assertFalse(first.due_status)
        self.assertEqual((card.free_services_expired, card.free_services_missed,
                          card.free_services_balance), (1, 0, 2))
        self.assertFalse(self._activities(first, self.due_type, active=True))
        self.assertFalse(self._activities(first, self.expiry_type, active=True))
        self.assertEqual(len(self._activities(first, self.due_type, active=False)), 1,
                         'closed system activity is kept')
        self.assertTrue(manual.exists() and manual.active, 'manual activity is not closed')
        self.assertTrue(first.message_ids.filtered(
            lambda message: 'Service expired' in (message.body or '')))

    def test_06_late_run_no_obsolete_reminders(self):
        """A delayed first run after the grace period expires the service without creating
        obsolete due alerts or expiry reminders."""
        first = self._first(self._card())
        self._run(date(2026, 12, 20))
        self.assertEqual(first.state, 'expired')
        self.assertFalse(self._activities(first, self.due_type))
        self.assertFalse(self._activities(first, self.expiry_type))

        # Run delayed but still inside the alert window: one alert is created.
        second = first.warranty_card_id.service_entitlement_ids.filtered(
            lambda e: e.service_no == 2)
        self._run(date(2027, 3, 10))
        self.assertEqual(len(self._activities(second, self.due_type)), 1)
        # Due date passed before the next run: no further due alert.
        self._run(date(2027, 3, 20))
        self.assertEqual(len(self._activities(second, self.due_type)), 1)

    def test_07_auto_expire_off_and_carry_forward(self):
        """Auto-expire off or Carry-forward on: Missed after the grace period, never Expired,
        no expiry reminder."""
        self.policy.auto_expire_services = False
        first = self._first(self._card('AC No Expire'))
        self.assertFalse(first.expiry_reminder_date)
        self._run(date(2027, 1, 30))
        self.assertEqual(first.state, 'missed')
        self.assertFalse(self._activities(first, self.expiry_type))

        self.policy.write({'auto_expire_services': True, 'carry_forward_allowed': True})
        first = self._first(self._card('AC Carry'))
        self.assertFalse(first.expiry_reminder_date)
        self._run(date(2027, 1, 30))
        self.assertEqual(first.state, 'missed')
        self.assertEqual(first.warranty_card_id.free_services_balance, 3)

    def test_08_zero_grace_period(self):
        """Grace period 0: the expiry rule is evaluated from the day after the due date."""
        self.policy.grace_period_days = 0
        first = self._first(self._card('AC Grace 0'))
        self.assertEqual(first.grace_period_end_date, first.due_date)
        self._run(date(2026, 11, 15))
        self.assertEqual(first.state, 'draft')
        self._run(date(2026, 11, 16))
        self.assertEqual(first.state, 'expired')

        self.policy.auto_expire_services = False
        first = self._first(self._card('AC Grace 0 Keep'))
        self._run(date(2026, 11, 16))
        self.assertEqual(first.state, 'missed')

    def test_09_expiry_blocked_by_merge_status(self):
        """Selected / merged entitlements: no Missed, no Expired, no reminders; only the due
        indicator is updated."""
        first = self._first(self._card())
        first.merge_status = 'selected'
        self.assertTrue(first._is_expiry_blocked())
        self._run(date(2026, 11, 1))
        self._run(date(2026, 12, 10))
        self._run(date(2027, 1, 30))
        self.assertEqual((first.state, first.due_status), ('draft', 'overdue'))
        self.assertFalse(first.activity_ids)

    def test_10_closed_states_untouched(self):
        """Completed, Cancelled and Expired entitlements are never changed by the scheduled
        action; their due indicator is cleared."""
        card = self._card()
        lines = card.service_entitlement_ids.sorted('service_no')
        lines[0].state = 'completed'
        lines[1].state = 'cancelled'
        lines[2].state = 'expired'
        lines.due_status = 'overdue'
        self._run(date(2028, 1, 1))
        self.assertEqual(lines.mapped('state'), ['completed', 'cancelled', 'expired'])
        self.assertFalse(any(lines.mapped('due_status')))
        self.assertFalse(lines.activity_ids)

    # ------------------------------------------------------------------ responsible user
    def test_11_missing_responsible_user(self):
        """No valid responsible user: no activity, not marked as sent, warning on the card and
        in the log; the company fallback is used later without changing the card snapshot."""
        self.policy.service_alert_user_ids = False
        card = self._card()
        first = self._first(card)
        self.assertFalse(card.service_alert_user_ids)
        self.assertIn('No valid Service Alert Responsible User', card.free_service_schedule_note)
        with self.assertLogs(ENTITLEMENT_LOGGER, 'WARNING') as logs:
            self._run(date(2026, 11, 1))
        self.assertIn(first.name, logs.output[0])
        self.assertFalse(first.activity_ids)
        self.assertFalse(first.due_alert_sent)

        self.company.warranty_service_alert_user_ids = self.fallback_user
        self.assertNotIn('Responsible User', card.free_service_schedule_note or '')
        self._run(date(2026, 11, 2))
        alert = self._activities(first, self.due_type)
        self.assertEqual(alert.user_id, self.fallback_user)
        self.assertFalse(card.service_alert_user_ids, 'snapshot is not overwritten')

    def test_12_responsible_user_company_fallback_at_confirmation(self):
        """A shared policy whose user is not allowed in the card company resolves to the
        company fallback user at confirmation."""
        other_company = self.env['res.company'].create({'name': 'Other P2M Company'})
        outsider = self.env['res.users'].create({
            'name': 'Outsider', 'login': 'warranty_p2m_outsider',
            'company_id': other_company.id, 'company_ids': [(6, 0, other_company.ids)],
            'groups_id': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        self.policy.write({'company_id': False, 'service_alert_user_ids': outsider.ids})
        self.company.warranty_service_alert_user_ids = self.fallback_user
        card = self._card()
        self.assertEqual(card.service_alert_user_ids, self.fallback_user)

    # ------------------------------------------------------------------ due date change
    def test_13_due_date_change_reschedules_activities(self):
        """Open system activity: deadline moved, no new activity. Closed activity: one new
        alert for the new due date."""
        first = self._first(self._card())
        self._run(date(2026, 11, 1))
        alert = first.due_alert_activity_ids

        def change(new_date):
            action = first.action_open_due_date_wizard()
            self.env[action['res_model']].with_context(action['context']).create({
                'new_due_date': new_date, 'reason': 'Customer request'}).action_apply()

        change(date(2026, 11, 20))
        self.assertEqual(first.due_alert_activity_ids, alert)
        self.assertEqual(alert.date_deadline, date(2026, 11, 20))
        self.assertEqual(first.grace_period_end_date, date(2026, 12, 20))
        self.assertEqual(len(self._activities(first, self.due_type)), 1)

        alert.action_feedback(feedback='Called the customer')
        change(date(2026, 11, 25))
        self.assertFalse(first.due_alert_sent)
        self._run(date(2026, 11, 12))
        activities = self._activities(first, self.due_type)
        self.assertEqual(len(activities), 2)
        self.assertEqual(first.due_alert_activity_ids.date_deadline, date(2026, 11, 25))
        self._run(date(2026, 11, 13))
        self.assertEqual(len(self._activities(first, self.due_type)), 2)

    # ------------------------------------------------------------------ deletion and balance
    def test_14_deletion_restrictions(self):
        """Draft entitlements can be deleted (administrator); Completed, Missed, Expired and
        Cancelled cannot, not even through the warranty card."""
        card = self._card()
        lines = card.service_entitlement_ids.sorted('service_no')
        lines[0].unlink()
        for state in ('completed', 'missed', 'expired', 'cancelled'):
            lines[1].state = state
            with self.assertRaises(UserError):
                lines[1].unlink()
            with self.assertRaises(UserError):
                card.unlink()
        self.assertTrue(lines[1].exists())

    def test_15_balance_formula(self):
        """Balance = Allowed - Completed - Expired - Cancelled; Missed stays available."""
        card = self._card()
        lines = card.service_entitlement_ids.sorted('service_no')
        lines[0].state = 'completed'
        lines[1].state = 'expired'
        lines[2].state = 'missed'
        self.assertEqual(
            (card.free_services_allowed, card.free_services_used, card.free_services_expired,
             card.free_services_missed, card.free_services_cancelled,
             card.free_services_balance), (3, 1, 1, 1, 0, 1))
        lines[2].state = 'cancelled'
        self.assertEqual((card.free_services_cancelled, card.free_services_balance), (1, 0))

    # ------------------------------------------------------------------ scope limits
    def test_16_usage_and_legacy_cards_not_monitored(self):
        """Usage-based cards and cards confirmed before monitoring existed are not changed."""
        product = self._product('AC Usage Monitor')
        product.product_tmpl_id.warranty_policy_id = self.policy.copy({
            'name': 'Usage Monitoring Policy', 'warranty_basis': 'usage', 'usage_limit': 2000,
            'usage_unit': 'operating_hours', 'free_service_count': 2,
            'free_service_frequency': 4, 'free_service_frequency_unit': 'months'})
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'pricelist_id': self.retail.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})]})
        confirm_and_group(order)
        usage_card = order.warranty_card_ids
        set_installation(usage_card, date(2026, 7, 15))
        usage_card.action_confirm_warranty()
        usage_line = self._first(usage_card)
        self.assertEqual(usage_line.usage_threshold, 900, '90% of 1,000 hours')

        legacy_card = self._card('AC Legacy')
        legacy_card.service_monitoring_active = False
        legacy = self._first(legacy_card)
        self.assertFalse(legacy.grace_period_end_date)
        self.assertFalse(legacy.alert_date)

        self._run(date(2027, 3, 1))
        self.assertEqual((usage_line.state, usage_line.due_status), ('draft', False))
        self.assertEqual((legacy.state, legacy.due_status), ('draft', False))
        self.assertFalse((usage_line | legacy).activity_ids)

    # ------------------------------------------------------------------ timezone
    @freeze_time('2026-11-14 12:00:00')
    def test_17_company_timezone(self):
        """Today is evaluated in the Warranty Timezone, then the company contact timezone,
        then UTC (with a warning)."""
        self.company.warranty_timezone = 'Pacific/Kiritimati'   # UTC+14 -> 2026-11-15
        self.assertEqual(self.company._warranty_today(), date(2026, 11, 15))
        self.company.warranty_timezone = 'Pacific/Pago_Pago'    # UTC-11 -> 2026-11-14
        self.assertEqual(self.company._warranty_today(), date(2026, 11, 14))

        self.company.warranty_timezone = False
        self.company.partner_id.tz = 'Pacific/Kiritimati'
        self.assertEqual(self.company._warranty_today(), date(2026, 11, 15))

        self.company.partner_id.tz = False
        with self.assertLogs(COMPANY_LOGGER, 'WARNING'):
            self.assertEqual(self.company._warranty_today(log_missing_timezone=True),
                             date(2026, 11, 14))

        # The scheduled action uses the company timezone: due today in Kiritimati.
        self.company.warranty_timezone = 'Pacific/Kiritimati'
        first = self._first(self._card('AC Timezone'))
        self.Entitlement._cron_monitor_free_services()
        self.assertEqual(first.due_status, 'due')

    # ------------------------------------------------------------------ several responsible users
    def test_18_multiple_users_validation(self):
        """Every selected responsible user must be valid on the company and the policy."""
        portal_user = self.env['res.users'].create({
            'name': 'Portal Multi', 'login': 'warranty_p2m_portal_multi',
            'groups_id': [(6, 0, self.env.ref('base.group_portal').ids)],
        })
        self.company.warranty_service_alert_user_ids = self.alert_user | self.fallback_user
        self.assertEqual(len(self.company.warranty_service_alert_user_ids), 2)
        with self.assertRaises(ValidationError):
            self.company.warranty_service_alert_user_ids = self.alert_user | portal_user
        with self.assertRaises(ValidationError):
            self.policy.service_alert_user_ids = self.alert_user | portal_user
        settings = self.env['res.config.settings'].create({})
        self.assertEqual(settings.warranty_service_alert_user_ids,
                         self.alert_user | self.fallback_user)

    def test_19_one_activity_per_user(self):
        """Each valid responsible user receives their own due alert and expiry reminder;
        a due date change moves all open ones; expiry closes all of them."""
        self.policy.service_alert_user_ids = self.alert_user | self.fallback_user
        card = self._card()
        self.assertEqual(card.service_alert_user_ids, self.alert_user | self.fallback_user)
        first = self._first(card)

        self._run(date(2026, 11, 1))
        alerts = self._activities(first, self.due_type)
        self.assertEqual(alerts.user_id, self.alert_user | self.fallback_user)
        self.assertEqual(len(alerts), 2)
        self.assertEqual(first.due_alert_activity_ids, alerts)
        self._run(date(2026, 11, 2))
        self.assertEqual(len(self._activities(first, self.due_type)), 2, 'no duplicates')

        def change(new_date):
            action = first.action_open_due_date_wizard()
            self.env[action['res_model']].with_context(action['context']).create({
                'new_due_date': new_date, 'reason': 'Customer request'}).action_apply()

        change(date(2026, 11, 20))
        self.assertEqual(set(alerts.mapped('date_deadline')), {date(2026, 11, 20)})
        # One user closes their activity: only the other one moves, nothing new is created.
        done = alerts.filtered(lambda a: a.user_id == self.alert_user)
        done.action_feedback(feedback='Called the customer')
        change(date(2026, 11, 22))
        self.assertTrue(first.due_alert_sent)
        open_alert = self._activities(first, self.due_type, active=True)
        self.assertEqual((open_alert.user_id, open_alert.date_deadline),
                         (self.fallback_user, date(2026, 11, 22)))
        self._run(date(2026, 11, 10))
        self.assertEqual(len(self._activities(first, self.due_type)), 2)

        self._run(date(2026, 12, 16))
        reminders = self._activities(first, self.expiry_type)
        self.assertEqual(len(reminders), 2)
        self.assertEqual(first.expiry_reminder_activity_ids, reminders)
        self._run(date(2026, 12, 23))
        self.assertEqual(first.state, 'expired')
        self.assertFalse(self._activities(first, self.due_type, active=True))
        self.assertFalse(self._activities(first, self.expiry_type, active=True))
        self.assertEqual(len(self._activities(first, self.expiry_type, active=False)), 2,
                         'closed system activities are kept')

    def test_20_invalid_user_skipped(self):
        """A responsible user who became invalid after confirmation is skipped and logged;
        the other users still receive their activity. When no snapshot user is valid any
        more, the company users are used."""
        self.policy.service_alert_user_ids = self.alert_user | self.fallback_user
        first = self._first(self._card())
        self.fallback_user.active = False
        with self.assertLogs(ENTITLEMENT_LOGGER, 'WARNING') as logs:
            self._run(date(2026, 11, 1))
        self.assertIn('Warranty Fallback', '\n'.join(logs.output))
        alerts = self._activities(first, self.due_type)
        self.assertEqual(alerts.user_id, self.alert_user)

        # Confirmed after the archive: only the valid policy user is snapshotted.
        second = self._first(self._card('AC Company Users'))
        self.assertEqual(second.warranty_card_id.service_alert_user_ids, self.alert_user)
        self.alert_user.active = False
        company_user = self.env['res.users'].create({
            'name': 'Company Coordinator', 'login': 'warranty_p2m_company_coordinator',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        self.company.warranty_service_alert_user_ids = company_user
        self._run(date(2026, 11, 2))
        self.assertEqual(self._activities(second, self.due_type).user_id, company_user)
        self.assertEqual(second.warranty_card_id.service_alert_user_ids, self.alert_user,
                         'snapshot is not overwritten')

    def test_30_due_alert_email(self):
        """One dedicated Due Alert email per valid responsible user (whatever the notification
        preference), queued and kept, with the card / customer / product / service / due date
        and link; no duplicates on later runs; a user without email still gets the activity."""
        self.company.email = 'warranty-company@example.com'
        self.alert_user.write({'email': 'coordinator@example.com', 'notification_type': 'inbox'})
        self.fallback_user.write({'email': 'fallback@example.com', 'notification_type': 'email'})
        no_email_user = self.env['res.users'].create({
            'name': 'No Email Coordinator', 'login': 'warranty_p2m_no_email',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        no_email_user.partner_id.email = False
        self.policy.service_alert_user_ids = self.alert_user | self.fallback_user | no_email_user
        template = self.env.ref('warranty_management.mail_template_free_service_due_alert')
        card = self._card('AC Email Alert')
        first = self._first(card)
        Mail = self.env['mail.mail'].with_context(active_test=False)

        def emails():
            return Mail.search([('model', '=', first._name), ('res_id', '=', first.id),
                                ('mail_message_id.subject', 'ilike', 'Free Service 1 due on')])

        self._run(date(2026, 10, 31))
        self.assertFalse(emails())
        self._run(date(2026, 11, 1))
        self.assertEqual(len(self._activities(first, self.due_type)), 3, 'activities unchanged')
        mails = emails()
        self.assertEqual(len(mails), 2, 'one per user with an email address')
        self.assertEqual(sorted(mails.recipient_ids.mapped('email')),
                         ['coordinator@example.com', 'fallback@example.com'])
        for mail in mails:
            self.assertEqual(len(mail.recipient_ids), 1)
            self.assertEqual((mail.state, mail.auto_delete), ('outgoing', False))
            self.assertIn('warranty-company@example.com', mail.email_from)
            self.assertEqual(mail.reply_to, mail.email_from)
            self.assertIn(card.name, mail.subject)
            for text in (card.name, 'Monitoring Customer', 'AC Email Alert', first.name,
                         '/mail/view?model=warranty.service.entitlement&amp;res_id=%s' % first.id):
                self.assertIn(text, mail.body_html)
        self.assertEqual(template.auto_delete, False)

        # Later runs: no duplicate email (nor activity).
        self._run(date(2026, 11, 5))
        self._run(date(2026, 11, 15))
        self.assertEqual(len(emails()), 2)
        self.assertEqual(len(self._activities(first, self.due_type)), 3)

        # Expiry reminder: its own dedicated emails (see test_33); no extra due alert email.
        self._run(date(2026, 12, 8))
        self.assertTrue(self._activities(first, self.expiry_type))
        self.assertEqual(len(emails()), 2)

    def test_31_due_alert_email_sender_fallback(self):
        """Company without email: the server default sender address is used."""
        self.company.email = False
        self.alert_user.email = 'coordinator@example.com'
        first = self._first(self._card('AC Email Fallback'))
        with patch.object(type(self.env['ir.mail_server']), '_get_default_from_address',
                          lambda server: 'notifications@example.com'):
            self._run(date(2026, 11, 1))
        mail = self.env['mail.mail'].search([('model', '=', first._name),
                                             ('res_id', '=', first.id)])
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.email_from, 'notifications@example.com')

    def test_32_policy_monitoring_layout(self):
        """Policy form: Service Due Alert Configuration (alert days, responsible users) and
        Service Expiry Configuration (grace period, auto-expire, expiry reminder days)."""
        arch = etree.fromstring(
            self.env.ref('warranty_management.warranty_policy_view_form').arch)
        for group_name, title, names in (
                ('service_due_alert_configuration', 'Service Due Alert Configuration',
                 ['service_due_alert_days', 'service_alert_user_ids', 'usage_alert_percentage']),
                ('service_expiry_configuration', 'Service Expiry Configuration',
                 ['auto_expire_services', 'grace_period_days', 'expiry_reminder_days'])):
            group = arch.xpath("//group[@name='%s']" % group_name)[0]
            self.assertEqual(group.get('string'), title)
            self.assertEqual([field.get('name') for field in group.xpath('./field')], names)
        self.assertEqual(len(arch.xpath("//field[@name='service_alert_user_ids']")), 1)

    # ------------------------------------------------------------------ expiry emails
    def _service_emails(self, entitlement, subject_part):
        return self.env['mail.mail'].with_context(active_test=False).search([
            ('model', '=', entitlement._name), ('res_id', '=', entitlement.id),
            ('mail_message_id.subject', 'ilike', subject_part)])

    def _email_users(self):
        self.company.email = 'warranty-company@example.com'
        self.alert_user.write({'email': 'coordinator@example.com', 'notification_type': 'inbox'})
        self.fallback_user.email = 'fallback@example.com'
        no_email_user = self.env['res.users'].create({
            'name': 'No Email Expiry', 'login': 'warranty_p2m_no_email_expiry',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        no_email_user.partner_id.email = False
        self.policy.service_alert_user_ids = self.alert_user | self.fallback_user | no_email_user

    def test_33_expiry_reminder_and_expired_emails(self):
        """Expiry reminder: one dedicated email per user with an email (activities unchanged);
        Expired: one EXPIRED email per user with the due date, expiry date and Expired On;
        later runs send nothing again."""
        self._email_users()
        card = self._card('AC Expiry Email')
        first = self._first(card)
        self._run(date(2026, 12, 7))
        self.assertFalse(self._service_emails(first, 'expires after'))

        self._run(date(2026, 12, 8))
        self.assertEqual(len(self._activities(first, self.expiry_type)), 3, 'activities unchanged')
        reminders = self._service_emails(first, 'expires after')
        self.assertEqual(sorted(reminders.recipient_ids.mapped('email')),
                         ['coordinator@example.com', 'fallback@example.com'])
        for mail in reminders:
            self.assertEqual((len(mail.recipient_ids), mail.state, mail.auto_delete),
                             (1, 'outgoing', False))
            self.assertIn('warranty-company@example.com', mail.email_from)
            self.assertIn('12/15/2026', mail.subject)
            for text in (card.name, 'Monitoring Customer', 'AC Expiry Email', first.name,
                         'Grace Period End Date', 'res_id=%s' % first.id):
                self.assertIn(text, mail.body_html)
        self._run(date(2026, 12, 9))
        self.assertEqual(len(self._service_emails(first, 'expires after')), 2, 'no duplicates')

        self._run(date(2026, 12, 15))
        self.assertFalse(self._service_emails(first, 'EXPIRED'))
        self._run(date(2026, 12, 18))
        self.assertEqual(first.state, 'expired')
        self.assertFalse(self._activities(first, self.expiry_type, active=True), 'closed')
        expired = self._service_emails(first, 'EXPIRED')
        self.assertEqual(sorted(expired.recipient_ids.mapped('email')),
                         ['coordinator@example.com', 'fallback@example.com'])
        for mail in expired:
            self.assertEqual((len(mail.recipient_ids), mail.auto_delete), (1, False))
            for text in ('has expired', first.name, card.name, 'Monitoring Customer',
                         'AC Expiry Email', '11/15/2026', '12/15/2026', '12/18/2026'):
                self.assertIn(text, mail.body_html)
        self._run(date(2026, 12, 19))
        self._run(date(2027, 1, 20))
        self.assertEqual(len(self._service_emails(first, 'EXPIRED')), 2, 'no duplicates')

    def test_34_no_expiry_no_expiry_emails(self):
        """Auto-expire off: Missed only, no expiry reminder or expired email."""
        self._email_users()
        self.policy.auto_expire_services = False
        first = self._first(self._card('AC No Expiry Email'))
        self._run(date(2026, 12, 8))
        self._run(date(2027, 1, 30))
        self.assertEqual(first.state, 'missed')
        self.assertFalse(self._service_emails(first, 'expires after'))
        self.assertFalse(self._service_emails(first, 'EXPIRED'))

    def test_35_expired_email_failure_does_not_block_expiry(self):
        """An error while preparing the email is logged; the service still expires and its
        activities are closed."""
        self._email_users()
        first = self._first(self._card('AC Email Failure'))
        self._run(date(2026, 11, 1))
        MailTemplate = type(self.env['mail.template'])

        def failing_send_mail(template, *args, **kwargs):
            raise ValueError('simulated rendering error')

        with patch.object(MailTemplate, 'send_mail', failing_send_mail), \
                self.assertLogs('odoo.addons.warranty_management.models.'
                                'warranty_service_entitlement', level='ERROR') as logs:
            self._run(date(2026, 12, 18))
        self.assertEqual(first.state, 'expired')
        self.assertFalse(self._activities(first, self.due_type, active=True))
        self.assertTrue(any('could not be prepared' in line for line in logs.output))
        self.assertFalse(self._service_emails(first, 'EXPIRED'))

    def test_36_expired_email_without_reminders(self):
        """Expiry Reminder Days 0: no reminder email, but the expired email is sent."""
        self._email_users()
        self.policy.expiry_reminder_days = 0
        first = self._first(self._card('AC Expired No Reminder'))
        self._run(date(2026, 12, 18))
        self.assertEqual(first.state, 'expired')
        self.assertFalse(self._service_emails(first, 'expires after'))
        self.assertEqual(len(self._service_emails(first, 'EXPIRED')), 2)
