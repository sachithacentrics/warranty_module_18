import re
from datetime import date, timedelta
from unittest.mock import patch

from lxml import etree
from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from .common import confirm_and_group, set_installation


@tagged('post_install', '-at_install', 'warranty_part2')
class TestWarrantyPart2(TransactionCase):
    """Part 2 - Free Service Entitlements, up to Generate Free Service Schedule."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'warranty_scope_mode': 'free_services',
            'warranty_auto_create_services': False,
            'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'installation',
            'default_warranty_duration': 0,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Free Service Customer'})
        cls.retail = cls.env['product.pricelist'].create({
            'name': 'Retail Pricelist P2', 'company_id': cls.company.id})
        cls.policy = cls.env['warranty.policy'].create({
            'name': 'Retail A/C Warranty',
            'warranty_duration': 12,
            'warranty_duration_unit': 'months',
            'free_service_count': 3,
            'free_service_period': 12,
            'free_service_period_unit': 'months',
            'schedule_method': 'equal_interval',
            'auto_create_services': True,
        })
        cls.categ = cls.env['product.category'].create({
            'name': 'Air Conditioners P2', 'warranty_policy_id': cls.policy.id})

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

    def _card(self, products, start=date(2026, 7, 15), confirm=True):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'pricelist_id': self.retail.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})
                           for product in products],
        })
        confirm_and_group(order)
        card = order.warranty_card_ids
        self.assertEqual(len(card), 1)
        set_installation(card, start)
        if confirm:
            self.assertEqual(card.state, 'ready', card.missing_requirements)
            card.action_confirm_warranty()
        return card

    def _resolve(self, product):
        line = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'pricelist_id': self.retail.id,
            'order_line': [(0, 0, {'product_id': product.id})]}).order_line
        values = line._warranty_resolve_rule()
        return (values['policy_source'], values['free_service_count'],
                values['free_service_frequency'], values['free_service_frequency_unit'])

    def _policy_as_company_default(self):
        """Card policy without mapping it to the products (a category policy is inherited
        by the products, which then ignore their own warranty values)."""
        self.categ.warranty_policy_id = False
        self.company.default_warranty_policy_id = self.policy

    def _due_dates(self, card):
        return card.service_entitlement_ids.sorted('service_no').mapped('due_date')

    # ------------------------------------------------------------------ tests
    def test_01_models_fields_and_sequence(self):
        """Entitlement model, Mapping fields, SRS 10.3 statuses + Draft, WSE sequence."""
        fields = self.env['warranty.service.entitlement']._fields
        for name in ('name', 'warranty_card_id', 'service_no', 'service_type', 'due_date',
                     'grace_period_end_date', 'state', 'payment_eligibility',
                     'reschedule_count', 'usage_due', 'alert_date', 'usage_threshold',
                     'merge_status', 'worksheet_template_id'):
            self.assertIn(name, fields)
        # 'job_created' is added by Part 4 (warranty_management_fsm, approved G1) when installed.
        self.assertEqual([s[0] for s in fields['state'].selection if s[0] != 'job_created'], [
            'draft', 'pending', 'scheduled', 'in_progress', 'completed', 'missed', 'expired',
            'cancelled', 'rescheduled'])
        self.assertEqual([s[0] for s in fields['merge_status'].selection],
                         ['not_merged', 'selected', 'merged', 'completed'])
        card = self._card(self._product('AC Fields'))
        for entitlement in card.service_entitlement_ids:
            self.assertRegex(entitlement.name, r'^WSE/\d{5}$')

    def test_02_scope_warranty_only(self):
        """BA decision 2026-10-28: the (kept, unused) company Scope Mode Warranty Only no longer
        limits free services; the resolved count and Auto-create Services decide."""
        self.company.warranty_scope_mode = 'warranty_only'
        card = self._card(self._product('AC Scope'))
        self.assertEqual(card.state, 'confirmed')
        self.assertTrue(card.free_services_included)
        self.assertEqual(len(card.service_entitlement_ids), card.free_services_allowed)
        self.assertTrue(card.schedule_method, 'free service values are snapshotted')

    def test_03_no_free_services(self):
        """Free Services Allowed = 0 (no count at any level): no entitlements and no error."""
        self.policy.free_service_count = 0
        self.company.default_free_service_count = 0
        card = self._card(self._product('AC Zero', default_free_service_count=0))
        self.assertEqual((card.state, card.free_services_allowed), ('confirmed', 0))
        self.assertFalse(card.service_entitlement_ids)

    def test_04_auto_create_equal_interval(self):
        """Auto-create: 3 Draft lines 1..3, Free Preventive; dates 4/8/12 months from the
        start; service 3 after the warranty end is flagged, not capped, not blocking."""
        card = self._card(self._product('AC Auto'))
        self.assertEqual(card.state, 'confirmed')
        self.assertEqual(card.warranty_end_date, date(2027, 7, 14))
        lines = card.service_entitlement_ids.sorted('service_no')
        self.assertEqual(lines.mapped('service_no'), [1, 2, 3])
        self.assertEqual(set(lines.mapped('state')), {'draft'})
        self.assertEqual(set(lines.mapped('service_type')), {'free_preventive'})
        self.assertEqual(set(lines.mapped('merge_status')), {'not_merged'})
        self.assertEqual(lines.mapped('due_date'),
                         [date(2026, 11, 15), date(2027, 3, 15), date(2027, 7, 15)])
        self.assertEqual(lines.mapped('due_date_conflict'), [False, False, True])
        self.assertIn('Service 3 is due on 2027-07-15', card.free_service_schedule_note)
        self.assertEqual(card.service_entitlement_count, 3)
        self.assertEqual((card.free_services_used, card.free_services_balance), (0, 3))
        self.assertEqual(card.schedule_method, 'equal_interval')
        self.assertEqual((card.free_service_period, card.free_service_period_unit),
                         (12, 'months'))
        self.assertTrue(card.pdf_attachment_id)

    def test_05_policy_disabled_not_overridden(self):
        """Policy auto-create unticked is not overridden by the company setting."""
        self.policy.auto_create_services = False
        self.company.warranty_auto_create_services = True
        card = self._card(self._product('AC Policy Off'))
        self.assertFalse(card.service_entitlement_ids)
        self.assertIn('Auto-create Services is disabled', card.free_service_schedule_note)

    def test_06_no_policy_company_fallback(self):
        """No policy: company auto-create applies; no Schedule Method -> no dates + notice."""
        self.categ.warranty_policy_id = False
        self.company.warranty_auto_create_services = True
        card = self._card(self._product('AC No Policy'))
        self.assertFalse(card.policy_id)
        self.assertEqual(len(card.service_entitlement_ids), 3)
        self.assertFalse(any(self._due_dates(card)))
        self.assertIn('Schedule Method not resolved', card.free_service_schedule_note)

    def test_07_policy_period_interval(self):
        """Company Default Warranty Policy (P4) without frequency: 12 months / 3 services =
        4-month interval; the product's own values (frequency 4 months) are not used."""
        self._policy_as_company_default()
        card = self._card(self._product('AC Period', free_service_frequency=6))
        self.assertEqual((card.policy_source, card.policy_id), ('company_policy', self.policy))
        self.assertEqual(card.free_service_frequency, 0)
        self.assertEqual(self._due_dates(card),
                         [date(2026, 11, 15), date(2027, 3, 15), date(2027, 7, 15)])

    def test_08_non_divisible_period(self):
        """12 months / 5 services: day-based, rounded down, last service on the period end."""
        self.policy.free_service_count = 5
        self.company.write({'default_warranty_duration': 12,
                            'default_warranty_duration_unit': 'months'})
        card = self._card(self._product(
            'AC Days', default_warranty_period=0, default_free_service_count=0,
            free_service_frequency=0, free_service_frequency_unit=False))
        start = date(2026, 7, 15)
        self.assertEqual(self._due_dates(card),
                         [start + timedelta(days=365 * n // 5) for n in range(1, 6)])
        self.assertEqual(self._due_dates(card)[-1], date(2027, 7, 15))

    def test_09_month_end_and_leap_year(self):
        """Dates are calculated from the start date (policy Free Service Frequency): no
        month-end drift; leap-year day."""
        self.policy.write({'free_service_frequency': 1, 'free_service_frequency_unit': 'months'})
        card = self._card(self._product('AC Month End'), start=date(2027, 1, 31))
        self.assertEqual(self._due_dates(card),
                         [date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)])
        self.policy.write({'free_service_count': 1, 'free_service_frequency': 12})
        card = self._card(self._product('AC Leap'), start=date(2028, 2, 29))
        self.assertEqual(self._due_dates(card), [date(2029, 2, 28)])

    def test_10_frequency_period_conflict_notice(self):
        """Policy frequency and period that do not end together -> visible notice; the
        frequency is used."""
        self.policy.write({'free_service_frequency': 6, 'free_service_frequency_unit': 'months'})
        card = self._card(self._product('AC Conflict'))
        self.assertEqual((card.free_service_frequency, card.free_service_frequency_unit),
                         (6, 'months'))
        self.assertEqual(self._due_dates(card)[0], date(2027, 1, 15), 'frequency is used')
        self.assertIn('differs from the policy Free Service Period',
                      card.free_service_schedule_note)

    def test_11_fixed_offsets(self):
        """Fixed Offsets: dates from the snapshot; snapshot unaffected by policy edits;
        incomplete offsets -> no dates + notice; policy offsets validated."""
        self.policy.write({'schedule_method': 'fixed_offsets', 'service_offset_ids': [
            (0, 0, {'service_no': 1, 'offset': 3, 'offset_unit': 'months'}),
            (0, 0, {'service_no': 2, 'offset': 6, 'offset_unit': 'months'}),
            (0, 0, {'service_no': 3, 'offset': 1, 'offset_unit': 'years'}),
        ]})
        card = self._card(self._product('AC Offsets'))
        self.assertEqual(self._due_dates(card),
                         [date(2026, 10, 15), date(2027, 1, 15), date(2027, 7, 15)])
        self.assertEqual(len(card.service_offset_ids), 3)
        self.policy.service_offset_ids.filtered(lambda o: o.service_no == 1).offset = 2
        self.assertEqual(card.service_offset_ids.sorted('service_no')[0].offset, 3)

        # Resolved count 4 (policy) but only 3 offsets -> incomplete
        self.policy.free_service_count = 4
        card = self._card(self._product('AC Offsets 4'))
        self.assertEqual(len(card.service_entitlement_ids), 4)
        self.assertFalse(any(self._due_dates(card)))
        self.assertIn('Fixed Offsets incomplete', card.free_service_schedule_note)

        with self.assertRaises(ValidationError):
            self.policy.write({'service_offset_ids': [
                (0, 0, {'service_no': 5, 'offset': 9, 'offset_unit': 'months'})]})
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['warranty.policy.service.offset'].create({
                'policy_id': self.policy.id, 'service_no': 1, 'offset': 1,
                'offset_unit': 'months'})
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['warranty.policy.service.offset'].create({
                'service_no': 9, 'offset': 1, 'offset_unit': 'months'})

    def test_12_calendar_manual_amc(self):
        """Manual: no dates. AMC Plan: nothing. Calendar Month is no longer a Schedule
        Method."""
        for model in ('warranty.policy', 'warranty.card', 'res.company', 'product.category',
                      'product.template'):
            field = self.env[model]._fields.get('schedule_method') \
                or self.env[model]._fields['default_schedule_method']
            self.assertNotIn('calendar_month', [key for key, __ in field.selection], model)

        self.policy.schedule_method = 'manual'
        card = self._card(self._product('AC Manual'))
        self.assertEqual(len(card.service_entitlement_ids), 3)
        self.assertFalse(any(self._due_dates(card)))
        self.assertIn('Manual Schedule', card.free_service_schedule_note)

        self.policy.schedule_method = 'amc_plan'
        card = self._card(self._product('AC AMC'))
        self.assertFalse(card.service_entitlement_ids)
        self.assertIn('AMC Plan', card.free_service_schedule_note)
        with self.assertRaises(ValidationError):
            self.env['warranty.service.entitlement'].create({'warranty_card_id': card.id})

    def test_13_usage_due(self):
        """Usage basis: usage due = limit / count x n, last milestone = limit, unit kept.
        Usage-based policy: limit and unit from the policy, missing -> configuration error.
        Without any policy (P5): the mapping line's limit, missing -> notice only."""
        usage_policy = self.env['warranty.policy'].create({
            'name': 'Usage Policy', 'warranty_duration': 12, 'warranty_duration_unit': 'months',
            'warranty_basis': 'usage', 'usage_limit': 2000, 'usage_unit': 'operating_hours',
            'free_service_count': 4, 'free_service_frequency': 4,
            'free_service_frequency_unit': 'months', 'schedule_method': 'equal_interval',
            'auto_create_services': True})
        self.categ.warranty_policy_id = usage_policy
        card = self._card(self._product('AC Usage 4'))
        self.assertEqual((card.policy_source, card.warranty_basis, card.usage_limit,
                          card.usage_unit), ('category_policy', 'usage', 2000, 'operating_hours'))
        lines = card.service_entitlement_ids.sorted('service_no')
        self.assertEqual(lines.mapped('usage_due'), [500, 1000, 1500, 2000])
        self.assertEqual(set(lines.mapped('usage_unit')), {'operating_hours'})
        self.assertTrue(all(lines.mapped('due_date')), 'calendar dates kept separately')
        self.assertFalse(any(lines.mapped('due_date_conflict')), 'usage basis has no end date')

        usage_policy.free_service_count = 3
        card = self._card(self._product('AC Usage 3'))
        self.assertEqual(card.service_entitlement_ids.sorted('service_no').mapped('usage_due'),
                         [666.67, 1333.33, 2000])

        # Usage-based policy without Usage Limit or Usage Unit: configuration error.
        for vals in ({'usage_limit': 0}, {'usage_limit': 2000, 'usage_unit': False}):
            usage_policy.write(vals)
            order = self.env['sale.order'].create({
                'partner_id': self.partner.id, 'pricelist_id': self.retail.id,
                'order_line': [(0, 0, {'product_id': self._product('AC Usage Missing').id})]})
            with self.assertRaises(UserError) as error:
                order.action_confirm()
            self.assertIn('needs a Usage Limit and a Usage Unit', str(error.exception))
            self.assertIn('Usage Policy', str(error.exception))

        # No policy at any level (P5): no usage limit source (the legacy mapping lines are not
        # used) -> notice only, no error.
        self.categ.warranty_policy_id = False
        self.company.warranty_auto_create_services = True
        product = self._product('AC Usage 0', warranty_basis='usage')
        product.product_tmpl_id.write({'warranty_pricelist_rule_ids': [(0, 0, {
            'pricelist_id': self.retail.id, 'warranty_period': 0, 'free_service_count': 3,
            'usage_limit': 2000, 'usage_unit': 'operating_hours'})]})
        card = self._card(product)
        self.assertEqual((card.policy_source, card.usage_limit), ('product', 0))
        self.assertFalse(any(card.service_entitlement_ids.mapped('usage_due')))
        self.assertIn('Usage Due not calculated', card.free_service_schedule_note)

    def test_14_no_duplicates(self):
        """Generation is idempotent; duplicate and extra service numbers are rejected."""
        card = self._card(self._product('AC Dup'))
        card._generate_free_service_entitlements()
        self.assertEqual(len(card.service_entitlement_ids), 3)
        with self.assertRaises(ValidationError):
            self.env['warranty.service.entitlement'].create({'warranty_card_id': card.id})
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['warranty.service.entitlement'].create(
                {'warranty_card_id': card.id, 'service_no': 2})

    def test_15_manual_creation(self):
        """Auto-create off: manual lines on a confirmed card get the next number and the
        scheduled values; unconfirmed cards and invalid numbers are rejected."""
        self.policy.auto_create_services = False
        card = self._card(self._product('AC Man'))
        self.assertFalse(card.service_entitlement_ids)
        Entitlement = self.env['warranty.service.entitlement']
        first = Entitlement.create({'warranty_card_id': card.id})
        self.assertEqual((first.service_no, first.due_date, first.state),
                         (1, date(2026, 11, 15), 'draft'))
        third = Entitlement.create({'warranty_card_id': card.id, 'service_no': 3,
                                    'due_date': date(2027, 6, 1)})
        self.assertEqual(third.due_date, date(2027, 6, 1), 'entered date is kept')
        with self.assertRaises(ValidationError):
            Entitlement.create({'warranty_card_id': card.id, 'service_no': 5})

        draft_card = self._card(self._product('AC Man Draft'), confirm=False)
        with self.assertRaises(ValidationError):
            Entitlement.create({'warranty_card_id': draft_card.id})

    def test_16_due_date_change_audit(self):
        """Due dates change only through the audited action: user, date, previous, new value
        and reason are logged; the conflict flag is recalculated."""
        card = self._card(self._product('AC Audit'))
        third = card.service_entitlement_ids.filtered(lambda e: e.service_no == 3)
        self.assertTrue(third.due_date_conflict)
        with self.assertRaises(UserError):
            third.due_date = date(2027, 7, 1)
        action = third.action_open_due_date_wizard()
        wizard = self.env[action['res_model']].with_context(action['context']).create({
            'new_due_date': date(2027, 7, 14), 'reason': 'Customer requested before expiry'})
        wizard.action_apply()
        self.assertEqual(third.due_date, date(2027, 7, 14))
        self.assertFalse(third.due_date_conflict)
        self.assertNotIn('Service 3', card.free_service_schedule_note or '')
        log = third.due_date_log_ids
        self.assertEqual((log.user_id, log.previous_due_date, log.new_due_date, log.reason),
                         (self.env.user, date(2027, 7, 15), date(2027, 7, 14),
                          'Customer requested before expiry'))
        self.assertTrue(log.change_date)

        third.state = 'pending'
        with self.assertRaises(UserError):
            third.action_open_due_date_wizard()

    def test_17_pdf_failure_rolls_back(self):
        """A PDF error during confirmation leaves no confirmed card and no entitlements."""
        card = self._card(self._product('AC PDF'), confirm=False)
        with patch.object(type(self.env['ir.actions.report']), '_render_qweb_pdf',
                          side_effect=UserError('PDF failure')):
            with self.assertRaises(UserError):
                card.action_confirm_warranty()
        self.env.invalidate_all()
        self.assertEqual(card.state, 'ready')
        self.assertFalse(card.service_entitlement_ids)
        self.assertFalse(self.env['warranty.service.entitlement'].search(
            [('warranty_card_id', '=', card.id)]))

    def test_18_worksheet_template(self):
        """Single-product card: product worksheet template; multi-product card: none."""
        template = self.env['worksheet.template'].with_context(
            worksheet_no_generation=True).create({'name': 'A/C Service', 'res_model': 'res.partner'})
        ac = self._product('AC WS', warranty_worksheet_template_id=template.id)
        card = self._card(ac)
        self.assertEqual(set(card.service_entitlement_ids.mapped('worksheet_template_id')),
                         {template})
        fan = self._product('Fan WS')
        card = self._card(ac + fan)
        self.assertEqual(len(card.unit_warranty_ids.product_id), 2)
        self.assertFalse(card.service_entitlement_ids.worksheet_template_id)

    def test_19_multi_company(self):
        """Entitlements follow the warranty card company record rule."""
        card = self._card(self._product('AC MC'))
        other_company = self.env['res.company'].create({'name': 'Other Warranty Company'})
        user = self.env['res.users'].create({
            'name': 'Other Company User', 'login': 'warranty_p2_other',
            'company_id': other_company.id, 'company_ids': [(6, 0, other_company.ids)],
            'groups_id': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        Entitlement = self.env['warranty.service.entitlement'].with_user(user)
        self.assertFalse(Entitlement.search([('warranty_card_id', '=', card.id)]))
        self.assertTrue(re.match(r'^WSE/', card.service_entitlement_ids[:1].name))

    def test_20_company_free_service_defaults(self):
        """Company Default Free Service Count / Period / Schedule Method: used at the company
        fallback level and when the card has no policy; a policy's period and schedule method
        still win; only shown for scope modes with free services."""
        self.categ.warranty_policy_id = False
        self.company.write({
            'default_warranty_duration': 12, 'default_warranty_duration_unit': 'months',
            'default_free_service_count': 2, 'default_free_service_period': 12,
            'default_free_service_period_unit': 'months',
            'default_schedule_method': 'equal_interval', 'warranty_auto_create_services': True,
        })
        bare = dict(default_warranty_period=0, default_free_service_count=0,
                    free_service_frequency=0, free_service_frequency_unit=False)
        card = self._card(self._product('AC Company Defaults', **bare))
        self.assertFalse(card.policy_id)
        self.assertEqual((card.policy_source, card.free_services_allowed, card.schedule_method,
                          card.free_service_period, card.free_service_period_unit),
                         ('company', 2, 'equal_interval', 12, 'months'))
        self.assertEqual(self._due_dates(card), [date(2027, 1, 15), date(2027, 7, 15)])

        # A card policy keeps its own schedule method and period; its count comes before
        # the company count.
        self.categ.warranty_policy_id = self.policy
        self.company.write({'default_schedule_method': 'manual', 'default_free_service_period': 24})
        card = self._card(self._product('AC Policy Wins', **bare))
        self.assertEqual((card.policy_id, card.free_services_allowed, card.schedule_method,
                          card.free_service_period), (self.policy, 3, 'equal_interval', 12))

        with self.assertRaises(ValidationError):
            self.company.default_free_service_count = -1

        arch = etree.fromstring(self.env.ref(
            'warranty_management.res_config_settings_view_form_warranty').arch)
        # Free Service Settings / Free Service Monitoring blocks: always shown (BA decision
        # 2026-10-28, no Scope Mode limitation).
        visible_rule = None
        general = arch.xpath("//block[@name='warranty_general_settings']")[0]
        self.assertIsNone(general.get('invisible'))
        self.assertEqual([s.get('id') for s in general.xpath('./setting')], [
            'warranty_default_policy', 'warranty_default_card_grouping',
            'warranty_default_basis', 'warranty_default_start_criterion',
            'warranty_default_duration'])
        # Duration shown only while no Default Warranty Policy is selected; Basis / Start
        # Criterion also while the selected policy leaves them empty (they fill it).
        for setting_id, invisible in (
                ('warranty_default_basis',
                 'warranty_default_policy_id and warranty_default_policy_basis'),
                ('warranty_default_start_criterion',
                 'warranty_default_policy_id and warranty_default_policy_start_criterion'),
                ('warranty_default_duration', 'warranty_default_policy_id')):
            setting = general.xpath("./setting[@id='%s']" % setting_id)[0]
            self.assertEqual(setting.get('invisible'), invisible)
        free = arch.xpath("//block[@name='warranty_free_service_settings']")[0]
        self.assertEqual((free.get('title'), free.get('invisible')),
                         ('Free Service Settings', visible_rule))
        self.assertEqual([s.get('id') for s in free.xpath('./setting')], [
            'warranty_default_policy_free_services', 'warranty_default_free_service_count', 'warranty_default_free_service_period',
            'warranty_default_schedule_method', 'warranty_draft_job_from_service'])
        # Auto-create Services is configured on the Warranty Policy only (not in the Settings).
        self.assertNotIn('warranty_auto_create_services', etree.tostring(arch).decode())
        self.assertEqual(
            free.xpath("./setting[@id='warranty_draft_job_from_service']")[0].get('invisible'), '1')
        monitoring = arch.xpath("//block[@name='warranty_service_monitoring_settings']")[0]
        self.assertEqual(monitoring.get('invisible'), visible_rule)

    def test_21_category_rule_schedule_method_and_auto_create(self):
        """Category without a Warranty Policy: its Default Schedule Method and Auto-create
        Services are used, whatever the Policy Source. Category with a mapped policy: the
        policy's values are used, never the category's own (readonly) values."""
        self.categ.write({
            'warranty_policy_id': False, 'default_warranty_period': 12,
            'default_warranty_period_unit': 'months', 'default_free_service_count': 2,
            'default_schedule_method': 'equal_interval', 'auto_create_services': True,
        })
        self.company.write({'default_free_service_period': 12,
                            'default_free_service_period_unit': 'months',
                            'default_schedule_method': 'manual',
                            'warranty_auto_create_services': False})
        bare = dict(default_warranty_period=0, default_free_service_count=0,
                    free_service_frequency=0, free_service_frequency_unit=False)
        card = self._card(self._product('AC Category Rule', **bare))
        self.assertEqual((card.policy_source, card.policy_id, card.schedule_method,
                          card.free_services_allowed), ('category', self.policy.browse(),
                                                        'equal_interval', 2))
        self.assertEqual(self._due_dates(card), [date(2027, 1, 15), date(2027, 7, 15)])

        # Another Policy Source (product default) also uses the category values.
        self.categ.default_schedule_method = 'manual'
        card = self._card(self._product('AC Product Rule'))
        self.assertEqual((card.policy_source, card.schedule_method), ('product', 'manual'))
        self.assertEqual(len(card.service_entitlement_ids), 3)

        # Category with a mapped policy: the policy's count, schedule method and (unticked)
        # Auto-create Services; the category's own values are ignored.
        self.policy.write({'auto_create_services': False, 'schedule_method': 'manual'})
        self.categ.warranty_policy_id = self.policy
        card = self._card(self._product('AC Category Policy', **bare))
        self.assertEqual((card.policy_source, card.policy_id, card.free_services_allowed,
                          card.schedule_method), ('category_policy', self.policy, 3, 'manual'))
        self.assertFalse(card.service_entitlement_ids)
        card = self._card(self._product('AC Product Rule Policy'))
        self.assertEqual((card.policy_source, card.schedule_method),
                         ('category_policy', 'manual'))
        self.assertFalse(card.service_entitlement_ids)

    def test_22_free_service_priority_separate_from_duration(self):
        """No policy at any level (P5): free service count / frequency, product > category >
        Company Warranty Settings; 0 / empty falls through (legacy mapping lines are not
        used). With a selected policy (P1-P4) every value comes from that policy only."""
        self.categ.write({'warranty_policy_id': False, 'default_free_service_count': 4,
                          'free_service_frequency': 2, 'free_service_frequency_unit': 'months'})
        self.company.write({'default_free_service_count': 1, 'default_free_service_period': 12,
                            'default_free_service_period_unit': 'months'})

        product = self._product('AC Levels')
        self.env['warranty.product.pricelist.rule'].create({
            'product_tmpl_id': product.product_tmpl_id.id, 'pricelist_id': self.retail.id,
            'warranty_period': 6, 'warranty_period_unit': 'months', 'free_service_count': 6})
        # Product values (3 / 4 months) win over the category and the company; the legacy
        # mapping line is ignored.
        self.assertEqual(self._resolve(product), ('product', 3, 4, 'months'))
        # Product without values: the category's own count and frequency.
        bare = self._product('AC Bare', default_free_service_count=0, free_service_frequency=0,
                             free_service_frequency_unit=False)
        self.assertEqual(self._resolve(bare), ('product', 4, 2, 'months'))
        # Nothing on the product / category: the Company Warranty Settings.
        self.categ.write({'default_free_service_count': 0, 'free_service_frequency': 0})
        self.assertEqual(self._resolve(bare), ('product', 1, 0, False))

        # P3 category policy: only its values (no frequency: 0), not the category's own.
        self.categ.write({'warranty_policy_id': self.policy.id, 'default_free_service_count': 4,
                          'free_service_frequency': 2})
        self.assertEqual(self._resolve(bare), ('category_policy', 3, 0, False))
        self.policy.write({'free_service_frequency': 6, 'free_service_frequency_unit': 'months'})
        self.assertEqual(self._resolve(bare), ('category_policy', 3, 6, 'months'))
        # P2 product policy: wins over the category policy; its count 0 is kept.
        product.product_tmpl_id.warranty_policy_id = self.env['warranty.policy'].create({
            'name': 'Product Level Policy', 'warranty_duration': 6,
            'warranty_duration_unit': 'months', 'free_service_count': 0})
        self.assertEqual(self._resolve(product), ('product_policy', 0, 0, False))
        # P1 pricelist policy: wins over the product policy.
        self.retail.write({'warranty_applicable': True, 'warranty_policy_id': self.env[
            'warranty.policy'].create({
                'name': 'Pricelist Level Policy', 'warranty_duration': 24,
                'warranty_duration_unit': 'months', 'free_service_count': 2}).id})
        self.assertEqual(self._resolve(product), ('pricelist_policy', 2, 0, False))

    def test_25_pricelist_rule_schedule_method(self):
        """No policy (P5): the product's, else the category's Default Schedule Method (the
        legacy mapping line's is not used). Pricelist policy (P1): the policy's schedule
        method."""
        self.categ.write({'warranty_policy_id': False, 'default_schedule_method': 'equal_interval'})
        self.company.warranty_auto_create_services = True
        product = self._product('AC Rule Method')
        self.env['warranty.product.pricelist.rule'].create({
            'product_tmpl_id': product.product_tmpl_id.id, 'pricelist_id': self.retail.id,
            'warranty_period': 12, 'warranty_period_unit': 'months', 'free_service_count': 2,
            'default_schedule_method': 'manual'})
        card = self._card(product)
        self.assertEqual((card.policy_source, card.schedule_method), ('product', 'equal_interval'))
        product.product_tmpl_id.default_schedule_method = 'manual'
        card = self._card(product)
        self.assertEqual(card.schedule_method, 'manual')

        self.retail.write({'warranty_applicable': True, 'warranty_policy_id': self.policy.id})
        card = self._card(product)
        self.assertEqual((card.policy_source, card.policy_id, card.schedule_method,
                          card.free_services_allowed),
                         ('pricelist_policy', self.policy, 'equal_interval', 3))

    def test_26_pricelist_rule_auto_create(self):
        """No policy (P5): Auto-create Services ticked on the product (or category) creates
        the Draft services; the legacy mapping line's tick is not used; no duplicates.
        Pricelist policy (P1): the policy's Auto-create Services decides alone."""
        self.categ.warranty_policy_id = False
        self.company.warranty_auto_create_services = False
        product = self._product('AC Rule Auto', default_free_service_count=2,
                                free_service_frequency=6, default_schedule_method='equal_interval')
        self.env['warranty.product.pricelist.rule'].create({
            'product_tmpl_id': product.product_tmpl_id.id, 'pricelist_id': self.retail.id,
            'warranty_period': 12, 'warranty_period_unit': 'months',
            'auto_create_services': True})
        card = self._card(product)
        self.assertEqual(card.policy_source, 'product')
        self.assertFalse(card.service_entitlement_ids, 'legacy line tick not used')

        product.product_tmpl_id.auto_create_services = True
        card = self._card(product)
        self.assertEqual((card.schedule_method, card.free_services_allowed), ('equal_interval', 2))
        self.assertEqual(card.service_entitlement_ids.mapped('state'), ['draft', 'draft'])
        self.assertEqual(self._due_dates(card), [date(2027, 1, 15), date(2027, 7, 15)])
        card._generate_free_service_entitlements()
        self.assertEqual(len(card.service_entitlement_ids), 2, 'no duplicates')

        # Pricelist policy with Auto-create Services unticked: no services, whatever the
        # product tick.
        self.policy.auto_create_services = False
        self.retail.write({'warranty_applicable': True, 'warranty_policy_id': self.policy.id})
        card = self._card(product)
        self.assertEqual((card.policy_source, card.free_services_allowed), ('pricelist_policy', 3))
        self.assertFalse(card.service_entitlement_ids)

        # The (kept, unused) company Scope Mode Warranty Only no longer prevents free services.
        self.retail.write({'warranty_applicable': False})
        self.company.warranty_scope_mode = 'warranty_only'
        card = self._card(product)
        self.assertEqual(len(card.service_entitlement_ids), 2)

    def test_24_product_schedule_method_and_auto_create(self):
        """Product without a mapped policy: its Default Schedule Method and Auto-create
        Services come before the category; with a mapped policy they are ignored."""
        self.categ.write({'warranty_policy_id': False, 'default_schedule_method': 'manual',
                          'auto_create_services': False})
        self.company.warranty_auto_create_services = False
        card = self._card(self._product('AC Product Method', default_schedule_method='equal_interval',
                                        auto_create_services=True))
        self.assertEqual((card.policy_source, card.schedule_method), ('product', 'equal_interval'))
        self.assertEqual(self._due_dates(card),
                         [date(2026, 11, 15), date(2027, 3, 15), date(2027, 7, 15)])
        # Product values empty: the category's.
        card = self._card(self._product('AC Category Method'))
        self.assertEqual(card.schedule_method, 'manual')
        self.assertFalse(card.service_entitlement_ids)

        # Mapped policy: its values, not the product's own (readonly) ones.
        self.policy.write({'schedule_method': 'manual', 'auto_create_services': False})
        mapped = self._product('AC Mapped Method', default_schedule_method='equal_interval',
                               auto_create_services=True)
        mapped.product_tmpl_id.warranty_policy_id = self.policy
        card = self._card(mapped)
        self.assertEqual((card.policy_source, card.policy_id, card.schedule_method),
                         ('product_policy', self.policy, 'manual'))
        self.assertFalse(card.service_entitlement_ids)

    def test_23_free_service_examples(self):
        """The confirmed Free Service Count examples under the strict policy priority."""
        self.categ.warranty_policy_id = False
        self.company.default_free_service_count = 7

        # Example 1: product count 3, product policy count 2 -> 2.
        product = self._product('AC Example 1')
        product.product_tmpl_id.warranty_policy_id = self.env['warranty.policy'].create({
            'name': 'Example 1 Policy', 'warranty_duration': 12,
            'warranty_duration_unit': 'months', 'free_service_count': 2})
        self.assertEqual(self._resolve(product)[:2], ('product_policy', 2))

        # Example 2: no policy, no product count, category count 4 -> 4 (P5).
        bare = self._product('AC Example 2', default_free_service_count=0,
                             free_service_frequency=0, free_service_frequency_unit=False)
        self.categ.default_free_service_count = 4
        self.assertEqual(self._resolve(bare)[:2], ('product', 4))

        # Example 3: a legacy Customer Type mapping (Applies To / pricelists stored on the
        # policy) is not used any more -> Company Warranty Settings count 7 (P5).
        self.categ.default_free_service_count = 0
        self.env['warranty.policy'].create({
            'name': 'Example 3 Legacy Customer Type', 'applies_to': 'customer_type',
            'warranty_duration': 12, 'warranty_duration_unit': 'months',
            'free_service_count': 3, 'pricelist_ids': [(6, 0, self.retail.ids)]})
        self.assertEqual(self._resolve(bare)[:2], ('product', 7))

        # Example 4: Company Default Warranty Policy (P4) count 2 -> 2; its count 0 stays 0
        # (the Company Warranty Settings count is not mixed in).
        self.company.default_warranty_policy_id = self.env['warranty.policy'].create({
            'name': 'Example 4 Company Policy', 'warranty_duration': 12,
            'warranty_duration_unit': 'months', 'free_service_count': 2})
        self.assertEqual(self._resolve(bare)[:2], ('company_policy', 2))
        self.company.default_warranty_policy_id.free_service_count = 0
        self.assertEqual(self._resolve(bare)[:2], ('company_policy', 0))
