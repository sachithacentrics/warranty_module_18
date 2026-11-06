from datetime import date, timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import AmcCommon


@tagged('post_install', '-at_install', 'amc')
class TestAmcLifecycle(AmcCommon):
    """Functional, negative and lifecycle tests of the core AMC module (docs/17)."""

    # ------------------------------------------------------------------ defects fixed
    def test_tc001_factor_locked_on_active_formula(self):
        """TC-001 / AMC-D11 (defect DEF-01): factors of an Active formula version are locked."""
        formula = self.plan_retail.current_formula_id
        with self.assertRaises(UserError):
            self.env['amc.pricing.factor'].create({'formula_id': formula.id,
                                                   'category_id': self.category.id,
                                                   'factor': 2.0})
        draft = self.env['amc.pricing.formula'].browse(
            formula.action_new_version()['res_id'])
        factor = self.env['amc.pricing.factor'].create({'formula_id': draft.id,
                                                        'category_id': self.category.id,
                                                        'factor': 2.0})
        self.assertEqual(factor.formula_id.state, 'draft')

    def test_tc002_usage_pricing_uses_expected_usage(self):
        """TC-002 / AMC-D07 (defect DEF-02): Usage-Based price = base + rate x expected usage."""
        plan = self._create_plan('Usage AMC (test)', visits=1, free=0, method='usage',
                                 amount=20000.0)
        contract = self._create_contract(plan=plan, expected_usage=1000.0)
        contract.action_compute_price()
        self.assertEqual(contract.price, 20000.0 + 15.0 * 1000.0)

    def test_tc003_end_date_not_moved_by_plan_change(self):
        """TC-003 / AMC-B07 (defect DEF-03): editing the plan duration does not move the end
        date of a sold contract; a Draft contract follows the plan when re-priced."""
        plan = self._create_plan('Duration AMC (test)', visits=1, free=0)
        sold = self._create_contract(plan=plan)
        self._sell(sold)
        end = sold.end_date
        self.assertEqual(end, sold.start_date + relativedelta(months=12, days=-1))
        draft = self._create_contract(plan=plan)
        plan.write({'duration_value': 24})
        self.assertEqual(sold.end_date, end)
        draft.action_compute_price()
        self.assertEqual(draft.contract_months, 24)

    def test_tc004_plan_pricelist_applicability(self):
        """TC-004 / AMC-B02: a plan restricted to customer types (pricelists) refuses others."""
        pricelist = self.env['product.pricelist'].create({'name': 'Project Pricelist',
                                                          'currency_id': self.currency.id})
        self.plan_project.pricelist_ids = [Command.set(pricelist.ids)]
        contract = self._create_contract(plan=self.plan_project)
        with self.assertRaises(UserError):
            contract.action_compute_price()

    def test_tc005_fractional_quantity_rejected(self):
        """TC-005 / AMC-E01: entitlements are per covered unit: whole quantities only."""
        with self.assertRaises(ValidationError):
            self._create_contract(lines=[{'product_id': self.equipment_untracked.id,
                                          'quantity': 1.5}])

    # ------------------------------------------------------------------ activation (A4)
    def test_tc010_no_entitlement_before_activation(self):
        """TC-010 / AMC-C03 / A05: Draft and Quotation contracts have no visits."""
        contract = self._create_contract()
        contract.action_compute_price()
        contract.action_create_quotation()
        self.assertEqual(contract.state, 'quotation')
        self.assertFalse(contract.visit_ids)
        self.assertFalse(contract.billing_line_ids)

    def test_tc011_activation_generates_schedule(self):
        """TC-011 / AMC-E01 / E02 / B04 / B06: Retail AMC 3 visits / year on 2 units: 6
        preventive visits due at 4, 8 and 12 months (capped to the end date) + 2 free."""
        contract = self._create_contract(lines=[{'product_id': self.equipment_untracked.id,
                                                 'quantity': 2.0}])
        self._sell(contract)
        self.assertEqual(contract.state, 'active')
        start = contract.start_date
        preventive = contract.visit_ids.filtered(lambda v: v.visit_type == 'preventive')
        free = contract.visit_ids - preventive
        self.assertEqual(len(preventive), 6)
        self.assertEqual(len(free), 2)
        unit1 = preventive.filtered(lambda v: v.unit_no == 1).sorted('sequence_no')
        self.assertEqual(unit1.mapped('due_date'), [
            start + relativedelta(months=4), start + relativedelta(months=8), contract.end_date])
        self.assertTrue(all(v.state == 'pending' for v in contract.visit_ids))
        self.assertEqual(contract.preventive_balance, 6)
        self.assertEqual(contract.free_balance, 2)
        self.assertEqual(contract.next_visit_date, start + relativedelta(months=4))
        # Idempotent generation (AMC-E09): no duplicate on a second call.
        contract._amc_generate_visits()
        self.assertEqual(len(contract.visit_ids), 8)

    def test_tc012_project_plan_two_visits(self):
        """TC-012 / AMC-B05: Project AMC 2 visits / year: due at 6 and 12 months."""
        contract = self._create_contract(plan=self.plan_project)
        self._sell(contract)
        dues = contract.visit_ids.sorted('sequence_no').mapped('due_date')
        self.assertEqual(dues, [contract.start_date + relativedelta(months=6),
                                contract.end_date])

    def test_tc013_usage_based_visits(self):
        """TC-013 / AMC-E10: usage plans schedule by usage; completion needs a reading that
        does not decrease."""
        plan = self._create_plan('Usage visits (test)', visits=2, free=0,
                                 service_basis='usage', usage_interval=500.0,
                                 usage_unit='hours')
        contract = self._create_contract(plan=plan)
        self._sell(contract)
        visits = contract.visit_ids.sorted('sequence_no')
        self.assertEqual(visits.mapped('usage_due'), [500.0, 1000.0])
        self.assertFalse(any(visits.mapped('due_date')))
        with self.assertRaises(UserError):
            visits[0]._amc_consume(self._today(), usage_reading=0.0)
        visits[0]._amc_consume(self._today(), usage_reading=520.0)
        with self.assertRaises(UserError):
            visits[1]._amc_consume(self._today(), usage_reading=400.0)

    # ------------------------------------------------------------------ visits
    def test_tc020_manual_completion_and_single_consumption(self):
        """TC-020 / AMC-E06 / E07 / E09: completion consumes once; next visit moves on. Core
        manual completion (the service bridge, when installed, disables it: TC-095)."""
        self.startPatcher(patch.object(type(self.env['amc.contract.visit']),
                                       '_amc_manual_completion_allowed', lambda visits: True))
        contract = self._create_contract()
        self._sell(contract)
        first = contract.visit_ids.filtered(lambda v: v.visit_type == 'preventive') \
            .sorted('sequence_no')[0]
        wizard = self.env['amc.visit.action.wizard'].with_user(self.user_coordinator).create({
            'visit_ids': [Command.set(first.ids)], 'action': 'complete',
            'completion_date': self._today(), 'note': 'Filters cleaned'})
        wizard.action_confirm()
        self.assertEqual(first.state, 'completed')
        self.assertEqual(contract.preventive_done, 1)
        self.assertEqual(contract.next_visit_date,
                         contract.start_date + relativedelta(months=8))
        with self.assertRaises(UserError):
            first._amc_consume(self._today())

    def test_tc021_visit_fields_protected(self):
        """TC-021 / AMC-H05: status / dates of entitlements cannot be written directly."""
        contract = self._create_contract()
        self._sell(contract)
        visit = contract.visit_ids[0]
        with self.assertRaises(UserError):
            visit.with_user(self.user_coordinator).write({'state': 'completed'})
        with self.assertRaises(UserError):
            self.env['amc.contract.visit'].create({'contract_id': contract.id,
                                                   'line_id': contract.line_ids.id,
                                                   'visit_type': 'preventive'})
        with self.assertRaises(UserError):
            visit.unlink()

    def test_tc022_manual_planning(self):
        """TC-022: planning a date sets Scheduled; planning outside the period is refused."""
        contract = self._create_contract()
        self._sell(contract)
        visit = contract.visit_ids.filtered(lambda v: v.visit_type == 'preventive')[0]
        planned = fields.Datetime.to_datetime(contract.start_date) + timedelta(days=30, hours=10)
        visit.with_user(self.user_coordinator).scheduled_date = planned
        self.assertEqual(visit.state, 'scheduled')
        visit.with_user(self.user_coordinator).scheduled_date = False
        self.assertEqual(visit.state, 'pending')
        with self.assertRaises(ValidationError):
            visit.scheduled_date = fields.Datetime.to_datetime(contract.end_date) + timedelta(days=5)

    def test_tc023_cancel_and_reopen_rights(self):
        """TC-023: cancellation needs an AMC Manager and a reason; not consumed."""
        contract = self._create_contract()
        self._sell(contract)
        visit = contract.visit_ids[0]
        with self.assertRaises(AccessError):
            visit.with_user(self.user_coordinator)._amc_cancel('no access')
        with self.assertRaises(UserError):
            visit.with_user(self.user_manager)._amc_cancel('  ')
        visit.with_user(self.user_manager)._amc_cancel('Customer declined')
        self.assertEqual(visit.state, 'cancelled')

    def test_tc024_alert_and_missed_scheduler(self):
        """TC-024 / AMC-E04 / E08: the daily scheduler creates one alert X days before the due
        date, marks Overdue, then Missed after the grace period; repeated runs add nothing."""
        self.plan_retail.write({'grace_days': 10, 'auto_mark_missed': True})
        contract = self._create_contract()
        self._sell(contract)
        visit = contract.visit_ids.filtered(lambda v: v.visit_type == 'preventive') \
            .sorted('sequence_no')[0]
        visits = self.env['amc.contract.visit']
        visits._cron_amc_visits(visit.due_date - timedelta(days=8))
        self.assertFalse(visit.alert_sent)
        self.assertEqual(visit.due_status, 'upcoming')
        visits._cron_amc_visits(visit.due_date - timedelta(days=7))
        self.assertTrue(visit.alert_sent)
        self.assertEqual(visit.due_status, 'due')
        activity = visit.alert_activity_id
        visits._cron_amc_visits(visit.due_date - timedelta(days=6))
        self.assertEqual(visit.alert_activity_id, activity)
        self.assertEqual(len(visit.activity_ids), 1)
        visits._cron_amc_visits(visit.due_date + timedelta(days=5))
        self.assertEqual(visit.due_status, 'overdue')
        self.assertEqual(visit.state, 'pending')
        visits._cron_amc_visits(visit.due_date + timedelta(days=11))
        self.assertEqual(visit.state, 'missed')
        visit.with_user(self.user_manager).action_reopen()
        self.assertEqual(visit.state, 'pending')

    # ------------------------------------------------------------------ billing (A5)
    def test_tc030_upfront_billing_on_confirmation(self):
        """TC-030 / AMC-B09 / G03: Upfront = one period released at activation; invoiced
        through the standard Sales invoicing; nothing posted automatically."""
        contract = self._create_contract()
        order = self._sell(contract)
        self.assertEqual(len(contract.billing_line_ids), 1)
        line = contract.billing_line_ids
        self.assertEqual(line.state, 'released')
        self.assertEqual(line.date, contract.start_date)
        self.assertEqual(order.order_line.qty_delivered, 1)
        contract.with_user(self.user_coordinator).action_create_invoice()
        invoice = order.invoice_ids
        self.assertEqual(invoice.state, 'draft')
        self.assertEqual(invoice.amount_untaxed, 30000.0)
        self.assertTrue(line.invoiced)
        with self.assertRaises(UserError):
            contract.action_create_invoice()

    def test_tc031_quarterly_in_advance(self):
        """TC-031 / AMC-B09: Quarterly in advance: 4 periods of the contract value, dated on
        each period start; the scheduler releases each once."""
        plan = self._create_plan('Quarterly (test)', visits=2, free=0,
                                 billing=self.billing_quarterly, amount=10000.0)
        contract = self._create_contract(plan=plan)
        order = self._sell(contract)
        lines = contract.billing_line_ids.sorted('sequence')
        self.assertEqual(len(lines), 4)
        self.assertAlmostEqual(sum(lines.mapped('amount')), 10000.0)
        self.assertEqual(lines.mapped('date'), [contract.start_date + relativedelta(months=3 * i)
                                                for i in range(4)])
        self.assertEqual(lines.mapped('state'), ['released', 'planned', 'planned', 'planned'])
        day = contract.start_date + relativedelta(months=3)
        contract._cron_amc_daily(day)
        contract._cron_amc_daily(day)
        self.assertEqual(lines.mapped('state'), ['released', 'released', 'planned', 'planned'])
        self.assertEqual(sum(order.order_line.mapped('qty_delivered')), 2)

    def test_tc032_per_visit_billing(self):
        """TC-032 / AMC-B09: Per Preventive Visit: one period per visit, released when the
        visit is consumed."""
        plan = self._create_plan('Per visit (test)', visits=2, free=0,
                                 billing=self.billing_per_visit, method='per_visit',
                                 amount=8000.0)
        contract = self._create_contract(plan=plan)
        self._sell(contract)
        self.assertEqual(contract.price, 16000.0)
        lines = contract.billing_line_ids.sorted('sequence')
        self.assertEqual(lines.mapped('state'), ['planned', 'planned'])
        self.assertTrue(all(lines.mapped('visit_id')))
        lines[0].visit_id._amc_consume(self._today())
        self.assertEqual(lines.mapped('state'), ['released', 'planned'])

    def test_tc033_activation_on_payment(self):
        """TC-033 / AMC-A05 / G03 / G04: On Payment: confirmation -> Awaiting Payment with the
        first period invoiceable, no entitlements; payment of the invoice activates."""
        self.plan_retail.activation_trigger = 'payment'
        contract = self._create_contract()
        self._sell(contract)
        self.assertEqual(contract.state, 'awaiting_payment')
        self.assertFalse(contract.visit_ids)
        self.assertEqual(contract.billing_line_ids.state, 'released')
        self._invoice_and_pay(contract)
        self.assertEqual(contract.state, 'active')
        self.assertEqual(contract.start_date, self._today())
        self.assertEqual(len(contract.visit_ids), 4)

    def test_tc034_quotation_cancel_returns_to_draft(self):
        """TC-034: cancelling an Awaiting Payment order returns the contract to Draft and
        removes the planned billing schedule."""
        self.plan_retail.activation_trigger = 'payment'
        contract = self._create_contract()
        order = self._sell(contract)
        order._action_cancel()
        self.assertEqual(contract.state, 'draft')
        self.assertFalse(contract.billing_line_ids.filtered(lambda l: l.state != 'cancelled'))

    # ------------------------------------------------------------------ lifecycle (A6)
    def test_tc040_hold_and_resume(self):
        """TC-040 / AMC-C04: On Hold blocks planning and alerts; Resume restores Active."""
        contract = self._create_contract()
        self._sell(contract)
        with self.assertRaises(AccessError):
            contract.with_user(self.user_coordinator)._amc_hold('test')
        contract.with_user(self.user_manager)._amc_hold('Customer site closed')
        self.assertEqual(contract.state, 'on_hold')
        visit = contract.visit_ids.filtered(lambda v: v.visit_type == 'preventive') \
            .sorted('sequence_no')[0]
        with self.assertRaises(UserError):
            visit.with_user(self.user_coordinator).scheduled_date = fields.Datetime.now()
        self.env['amc.contract.visit']._cron_amc_visits(visit.due_date)
        self.assertFalse(visit.alert_sent)
        contract.with_user(self.user_manager).action_resume()
        self.assertEqual(contract.state, 'active')

    def test_tc041_expiring_and_auto_offer(self):
        """TC-041 / AMC-B08 / C05: inside the renewal notice the contract becomes Expiring and
        an Auto Offer plan prepares one renewal contract."""
        self.plan_retail.renewal_rule = 'auto_offer'
        contract = self._create_contract()
        self._sell(contract)
        contract._cron_amc_daily(contract.end_date - timedelta(days=31))
        self.assertEqual(contract.state, 'active')
        contract._cron_amc_daily(contract.end_date - timedelta(days=30))
        self.assertEqual(contract.state, 'expiring')
        self.assertEqual(len(contract.renewal_ids), 1)
        renewal = contract.renewal_ids
        self.assertEqual(renewal.state, 'draft')
        self.assertEqual(renewal.start_date, contract.end_date + timedelta(days=1))
        contract._cron_amc_daily(contract.end_date - timedelta(days=29))
        self.assertEqual(len(contract.renewal_ids), 1)

    def test_tc042_renewal_then_renewed(self):
        """TC-042 / AMC-C05: the renewal (same serial allowed) is sold; at the end of the old
        contract the scheduler marks it Renewed (not Closed) and expires its open visits."""
        serial = self._new_serial('SN-R-1')
        contract = self._create_contract(lines=[{'product_id': self.equipment.id,
                                                 'serial_id': serial.id, 'quantity': 1.0}])
        self._sell(contract)
        renewal = self.env['amc.contract'].browse(
            contract.with_user(self.user_coordinator).action_renew()['res_id'])
        self.assertEqual(renewal.renewal_of_id, contract)
        self._sell(renewal)
        self.assertEqual(renewal.state, 'active')
        self.assertEqual(renewal.start_date, contract.end_date + timedelta(days=1))
        with self.assertRaises(UserError):
            contract.action_renew()
        contract._cron_amc_daily(contract.end_date + timedelta(days=1))
        self.assertEqual(contract.state, 'renewed')
        self.assertTrue(all(v.state == 'expired' for v in contract.visit_ids))

    def test_tc043_closed_at_end(self):
        """TC-043 / AMC-C04: without renewal the scheduler closes at the end date; open visits
        expire (not consumed), unreleased billing periods are cancelled."""
        plan = self._create_plan('Close (test)', visits=2, free=0,
                                 billing=self.billing_quarterly)
        contract = self._create_contract(plan=plan)
        self._sell(contract)
        contract._cron_amc_daily(contract.end_date + timedelta(days=1))
        self.assertEqual(contract.state, 'closed')
        self.assertTrue(contract.close_reason)
        self.assertTrue(all(v.state == 'expired' for v in contract.visit_ids))
        # Released on the way (daily run): periods 1-4 dated before the end; none left planned.
        self.assertFalse(contract.billing_line_ids.filtered(lambda l: l.state == 'planned'))

    def test_tc044_manual_close_and_cancel_rules(self):
        """TC-044 / AMC-C04: an Active contract cannot be cancelled, only closed (Manager,
        reason); its Sales Order cannot be cancelled."""
        contract = self._create_contract()
        order = self._sell(contract)
        with self.assertRaises(UserError):
            contract.with_user(self.user_manager).action_cancel_contract('wrong')
        with self.assertRaises(UserError):
            order._action_cancel()
        with self.assertRaises(UserError):
            contract.with_user(self.user_manager)._amc_close('')
        contract.with_user(self.user_manager)._amc_close('Customer terminated')
        self.assertEqual(contract.state, 'closed')
        renewal = contract.with_user(self.user_coordinator)._amc_create_renewal()
        self.assertEqual(renewal.state, 'draft')

    def test_tc045_late_renewal_of_closed_contract(self):
        """TC-045: a renewal activated after its predecessor was closed marks it Renewed."""
        contract = self._create_contract()
        self._sell(contract)
        contract._cron_amc_daily(contract.end_date + timedelta(days=1))
        self.assertEqual(contract.state, 'closed')
        renewal = contract._amc_create_renewal()
        self._sell(renewal)
        self.assertEqual(contract.state, 'renewed')

    def test_tc046_protected_contract_fields(self):
        """TC-046 / AMC-H05: status and lifecycle fields only by actions."""
        contract = self._create_contract()
        for vals in ({'state': 'active'}, {'renewal_of_id': contract.id},
                     {'close_reason': 'x'}, {'contract_months': 3}):
            with self.assertRaises(UserError):
                contract.write(vals)

    def test_tc047_report_renders(self):
        """TC-047 / AMC-H01: the AMC Visit Schedule renders for an Active contract."""
        contract = self._create_contract()
        self._sell(contract)
        html, __ = self.env['ir.actions.report']._render_qweb_html(
            'amc_management.action_report_amc_visit_schedule', contract.ids)
        self.assertIn(contract.name.encode(), html)
        self.assertIn(contract.visit_ids[0].name.encode(), html)

    def test_tc048_today_helper_dates(self):
        """TC-048: due dates with a start at month end (calendar edge case)."""
        plan = self._create_plan('Manual start (test)', visits=3, free=0, start_rule='manual')
        contract = self._create_contract(plan=plan, start_date=date(2026, 1, 31))
        self._sell(contract)
        dues = contract.visit_ids.sorted('sequence_no').mapped('due_date')
        self.assertEqual(dues, [date(2026, 5, 31), date(2026, 9, 30), date(2027, 1, 30)])
        self.assertEqual(contract.end_date, date(2027, 1, 30))
