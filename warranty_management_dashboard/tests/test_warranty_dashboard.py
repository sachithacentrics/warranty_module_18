from datetime import date, timedelta
from unittest.mock import patch

from odoo import Command, models
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.warranty_management.models.warranty_service_entitlement import OPEN_STATES
from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation
from odoo.addons.warranty_management_dashboard.models.warranty_dashboard import (
    APPROVALS, REPORT_LINKS)


@tagged('post_install', '-at_install', 'warranty_dashboard')
class TestWarrantyDashboard(TransactionCase):
    """Warranty Dashboard: the five areas, their drill-downs (= counted records), the
    filters including the date range, access rights, multi-company, empty data and no writes.
    Card figures are read in a product category of their own so that existing records of the
    database do not count."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.company.write({
            'warranty_auto_create_services': False, 'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so', 'default_warranty_basis': 'period',
            'default_start_criterion': 'installation', 'default_warranty_duration': 0,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Dashboard Customer'})
        cls.pricelist = cls.env['product.pricelist'].create({'name': 'Dashboard Retail',
                                                             'company_id': cls.company.id})
        cls.policy = cls.env['warranty.policy'].create({
            'name': 'Dashboard Policy', 'warranty_duration': 12,
            'warranty_duration_unit': 'months', 'free_service_count': 0})
        cls.categ = cls.env['product.category'].create({'name': 'Dashboard A/C',
                                                        'warranty_policy_id': cls.policy.id})
        cls.empty_categ = cls.env['product.category'].create({'name': 'Dashboard Empty'})
        cls.product = cls.env['product.product'].create({
            'name': 'Dashboard A/C', 'type': 'service', 'categ_id': cls.categ.id,
            'warranty_applicable': True, 'warranty_start_criterion': 'installation',
            'default_warranty_period': 12, 'default_warranty_period_unit': 'months',
            'default_free_service_count': 0})
        cls.today = date.today()
        cls.Dashboard = cls.env['warranty.dashboard']
        cls.filters = {'category_id': cls.categ.id}

    def _card(self, start, confirm=True):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'pricelist_id': self.pricelist.id,
            'order_line': [Command.create({'product_id': self.product.id,
                                           'product_uom_qty': 1})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, start)
        if confirm:
            card.action_confirm_warranty()
        return card

    def _records(self, key, filters=None, extra=None, dashboard=None):
        dashboard = dashboard or self.Dashboard
        action = dashboard.action_dashboard_open(
            key, self.filters if filters is None else filters, extra or {})
        return dashboard.env[action['res_model']].search(action['domain'])

    def _period(self, start, end, **values):
        return dict(self.filters, date_from=str(start), date_to=str(end), **values)

    def _figures(self, data):
        """(figure key, extra, count) of every number shown on the dashboard."""
        warranty, services = data['warranty'], data['services']
        figures = [('active', {}, warranty['active']), ('expiring', {}, warranty['expiring']),
                   ('pending_services', {}, services['open']),
                   ('services_overdue', {}, services['overdue']),
                   ('services_due', {}, services['due']),
                   ('open_replacements', {}, data['replacements']['open']),
                   ('appr_replacement', {}, data['replacements']['submitted']),
                   ('escalations', {}, data['escalations']['pending']),
                   ('repeated_flagged', {}, data['escalations']['repeated'])]
        figures += [('card_status', line['extra'], line['value'])
                    for line in warranty['by_status']]
        figures += [('services_by_due', line['extra'], line['value'])
                    for line in services['by_due']]
        figures += [(line['key'], {}, line['count']) for line in data['approvals']['lines']]
        return figures

    # ------------------------------------------------------------------ the five areas
    def test_01_five_srs_areas_only(self):
        """The dashboard returns exactly the five dashboard areas (no trend, failure or financial
        figure) and no financial API is left."""
        data = self.Dashboard.get_dashboard_data(self.filters)
        self.assertEqual(set(data), {'filters', 'period', 'options', 'warranty', 'services',
                                     'approvals', 'replacements', 'escalations', 'reports'})
        self.assertFalse(hasattr(self.Dashboard, 'get_financial_data'))
        self.assertFalse(data['period'])

    def test_02_active_uses_validity_dates(self):
        """Active = confirmed AND valid today; a confirmed card whose end date has passed
        (expiry job not run yet) and an expired card are not active."""
        valid = self._card(self.today - timedelta(days=30))
        ended = self._card(self.today - timedelta(days=400))
        expired = self._card(self.today - timedelta(days=500))
        expired._warranty_apply_expiry(self.today)
        self.assertEqual((valid.state, ended.state, expired.state),
                         ('confirmed', 'confirmed', 'expired'))
        self.assertLess(ended.warranty_end_date, self.today)
        self.assertEqual(self.Dashboard.get_dashboard_data(self.filters)['warranty']['active'], 1)
        self.assertEqual(self._records('active'), valid)

    def test_03_expiring_window(self):
        """Expiring = active cards ending within the selected window (30 / 60 / 90 days)."""
        soon = self._card(self.today - timedelta(days=350))     # ends in about 2 weeks
        later = self._card(self.today - timedelta(days=310))    # ends in about 7 weeks
        self._card(self.today - timedelta(days=30))             # ends in about 11 months
        filters = dict(self.filters, expiring_days=30)
        self.assertEqual(self.Dashboard.get_dashboard_data(filters)['warranty']['expiring'], 1)
        self.assertEqual(self._records('expiring', filters), soon)
        filters = dict(self.filters, expiring_days=60)
        self.assertEqual(self.Dashboard.get_dashboard_data(filters)['warranty']['expiring'], 2)
        self.assertEqual(self._records('expiring', filters), soon | later)
        self.assertEqual(self.Dashboard._dashboard_filters({'expiring_days': 45})[
            'expiring_days'], 30, 'not an allowed window: the default 30 days')

    def test_04_status_breakdown_and_card_status_filter(self):
        """Each card counted once in its status; Warranty Card Status filters the Warranty
        Status area only."""
        self._card(self.today - timedelta(days=30))
        self._card(self.today - timedelta(days=30), confirm=False)
        warranty = self.Dashboard.get_dashboard_data(self.filters)['warranty']
        self.assertEqual({line['key']: line['value'] for line in warranty['by_status']},
                         {'confirmed': 1, 'ready': 1})
        filtered = self.Dashboard.get_dashboard_data(dict(self.filters, card_state='ready'))
        self.assertEqual(filtered['warranty']['active'], 0, 'Active needs Confirmed')
        self.assertEqual([line['key'] for line in filtered['warranty']['by_status']], ['ready'])
        unfiltered = self.Dashboard.get_dashboard_data(self.filters)
        for area in ('services', 'approvals', 'replacements', 'escalations'):
            self.assertEqual(filtered[area], unfiltered[area], area)

    def test_05_every_figure_drills_down_to_its_records(self):
        """Every number (with and without a date range) opens exactly the counted records."""
        self._card(self.today - timedelta(days=30))
        self._card(self.today - timedelta(days=350))
        for filters in (self.filters, {},
                        self._period(self.today - timedelta(days=400), self.today)):
            data = self.Dashboard.get_dashboard_data(filters)
            for key, extra, count in self._figures(data):
                self.assertEqual(len(self._records(key, filters, extra)), count, key)

    def test_06_breakdowns_add_up_without_double_counting(self):
        """Status lines add up to all cards, due-indicator lines to the open services, approval
        lines to the approval total; each approval line is its document's waiting state."""
        data = self.Dashboard.get_dashboard_data({})
        Card = self.env['warranty.card']
        company = [('company_id', 'in', self.env.companies.ids)]
        self.assertEqual(sum(line['value'] for line in data['warranty']['by_status']),
                         Card.search_count(company))
        self.assertEqual(sum(line['value'] for line in data['services']['by_due']),
                         data['services']['open'])
        self.assertEqual(data['services']['open'], self.env[
            'warranty.service.entitlement'].search_count(company + [('state', 'in', OPEN_STATES)]))
        approvals = data['approvals']
        self.assertEqual(approvals['total'], sum(line['count'] for line in approvals['lines']))
        self.assertEqual(len({line['key'] for line in approvals['lines']}),
                         len(approvals['lines']))
        for key, model, _title, domain, _action in APPROVALS:
            line = next(line for line in approvals['lines'] if line['key'] == key)
            self.assertEqual(line['count'], self.env[model].search_count(company + domain), key)

    def test_07_empty_data(self):
        """A category without records: zeros, empty breakdowns, no error."""
        data = self.Dashboard.get_dashboard_data({'category_id': self.empty_categ.id})
        self.assertEqual((data['warranty']['active'], data['warranty']['expiring']), (0, 0))
        self.assertEqual(data['warranty']['by_status'], [])
        self.assertEqual(data['services']['open'], 0)
        self.assertEqual(data['replacements'], {'open': 0, 'submitted': 0})
        self.assertEqual(data['escalations'], {'pending': 0, 'repeated': 0})

    # ------------------------------------------------------------------ date range
    def test_08_date_range_filter(self):
        """No default range (today's position); an inverted range is refused; either bound may
        be open; datetimes use whole local days."""
        filters = self.Dashboard._dashboard_filters({})
        self.assertEqual((filters['date_from'], filters['date_to']), (False, False))
        with self.assertRaises(UserError):
            self.Dashboard._dashboard_filters({'date_from': '2026-05-01',
                                               'date_to': '2026-04-01'})
        filters = self.Dashboard._dashboard_filters({'date_from': '2026-01-01'})
        domain = self.Dashboard._dashboard_domain('warranty.case', filters, 'create_date')
        self.assertEqual([leaf[1] for leaf in domain if leaf[0] == 'create_date'], ['>='])
        filters = self.Dashboard._dashboard_filters({'date_from': '2026-01-01',
                                                     'date_to': '2026-01-31'})
        domain = self.Dashboard._dashboard_domain('warranty.case', filters, 'create_date')
        self.assertEqual([leaf[1] for leaf in domain if leaf[0] == 'create_date'], ['>=', '<'])

    def test_09_warranty_status_in_a_period(self):
        """With a date range, the warranty figures follow the warranty period, not "today":
        in force = confirmed or since-expired card whose period overlaps the range; ending =
        end date in the range; a draft card is never in force."""
        current = self._card(self.today - timedelta(days=30))
        old = self._card(self.today - timedelta(days=500))
        old._warranty_apply_expiry(self.today)
        self.assertEqual(old.state, 'expired')
        self._card(self.today - timedelta(days=500), confirm=False)
        past = self._period(old.warranty_start_date + timedelta(days=10),
                            old.warranty_start_date + timedelta(days=20))
        self.assertEqual(self._records('active', past), old, 'expired card was in force then')
        self.assertFalse(self._records('expiring', past))
        around_end = self._period(old.warranty_end_date - timedelta(days=3),
                                  old.warranty_end_date + timedelta(days=3))
        self.assertEqual(self._records('expiring', around_end), old)
        this_year = self._period(self.today - timedelta(days=10), self.today)
        self.assertEqual(self._records('active', this_year), current)
        future = self._period(current.warranty_end_date + timedelta(days=1),
                              current.warranty_end_date + timedelta(days=30))
        self.assertFalse(self._records('active', future), 'no card in force after its end')
        data = self.Dashboard.get_dashboard_data(past)
        self.assertTrue(data['period'])
        self.assertEqual(data['warranty']['active'], 1)

    def test_10_period_uses_document_dates(self):
        """Status lines count the cards created in the range; services use the due date;
        approvals, replacements and escalations the creation date."""
        self._card(self.today - timedelta(days=30))
        today = self._period(self.today, self.today)
        last_year = self._period(self.today - timedelta(days=400),
                                 self.today - timedelta(days=370))
        lines = self.Dashboard.get_dashboard_data(today)['warranty']['by_status']
        self.assertEqual(sum(line['value'] for line in lines), 1, 'card created today')
        self.assertEqual(self.Dashboard.get_dashboard_data(last_year)['warranty']['by_status'],
                         [])
        filters = self.Dashboard._dashboard_filters(last_year)
        expected = {
            'pending_services': 'due_date', 'open_replacements': 'create_date',
            'escalations': 'create_date', 'repeated_flagged': 'create_date',
            'appr_case': 'create_date', 'appr_mrf': 'create_date',
        }
        for key, field_name in expected.items():
            _model, domain, _action, _title = self.Dashboard._dashboard_spec(key, filters)
            self.assertEqual({leaf[0] for leaf in domain if isinstance(leaf, tuple)} &
                             {'due_date', 'create_date'}, {field_name}, key)
        services = self.env['warranty.service.entitlement'].search_count([
            ('company_id', 'in', self.env.companies.ids), ('state', 'in', OPEN_STATES),
            ('due_date', '>=', filters['date_from']), ('due_date', '<=', filters['date_to'])])
        self.assertEqual(self.Dashboard.get_dashboard_data(
            dict(last_year, category_id=False))['services']['open'], services)

    # ------------------------------------------------------------------ companies, rights
    def test_11_company_and_branch(self):
        """Figures limited to the allowed companies; the branch filter is offered only when the
        selected company has branches; a company outside the user's companies is ignored."""
        other = self.env['res.company'].create({'name': 'Dashboard Other Co'})
        user = new_test_user(self.env, login='wd_company_user', groups='base.group_user',
                             company_id=self.company.id, company_ids=self.company.ids)
        dashboard = self.Dashboard.with_user(user).with_context(
            allowed_company_ids=self.company.ids)
        self._card(self.today - timedelta(days=30))
        options = dashboard.get_dashboard_data(self.filters)['options']
        self.assertEqual([c['id'] for c in options['companies']], self.company.ids)
        self.assertEqual(options['branches'], [])
        forced = dashboard.get_dashboard_data(dict(self.filters, company_id=other.id))
        self.assertEqual(forced['warranty']['active'], 1,
                         'a company the user cannot use is ignored')
        branch = self.env['res.company'].create({'name': 'Dashboard Branch',
                                                 'parent_id': self.company.id})
        admin = self.Dashboard.with_context(allowed_company_ids=(self.company | branch).ids)
        options = admin.get_dashboard_data({'company_id': self.company.id})['options']
        self.assertEqual([b['id'] for b in options['branches']], branch.ids)
        self.assertEqual(admin._dashboard_companies({'company_id': self.company.id,
                                                     'branch_id': branch.id}), branch)
        self.assertEqual(admin._dashboard_companies({'company_id': self.company.id,
                                                     'branch_id': False}),
                         self.company | branch)

    def test_12_operational_access(self):
        """Figures and approval lines follow the user's model rights; a figure the user cannot
        read is None (shown as "—"), never a sudo count, and cannot be opened."""
        employee = new_test_user(self.env, login='wd_employee2', groups='base.group_user',
                                 company_id=self.company.id, company_ids=self.company.ids)
        dashboard = self.Dashboard.with_user(employee)
        data = dashboard.get_dashboard_data({})
        for line in data['approvals']['lines']:
            model = next(a[1] for a in APPROVALS if a[0] == line['key'])
            self.assertTrue(self.env[model].with_user(employee).has_access('read'))
        for report in data['reports']:
            action = self.env.ref(report['xml_id']).sudo()
            self.assertTrue(self.env[action.res_model].with_user(employee).has_access('read'))
        if data['replacements']['open'] is None:
            with self.assertRaises(AccessError):
                dashboard.action_dashboard_open('open_replacements', {})

    def test_13_opening_and_refreshing_writes_nothing(self):
        """Loading the dashboard, with or without filters, and opening its figures create,
        write or delete no record."""
        self._card(self.today - timedelta(days=30))
        forbidden = AssertionError('the dashboard must not change records')
        with patch.object(models.BaseModel, 'create', side_effect=forbidden), \
                patch.object(models.BaseModel, 'write', side_effect=forbidden), \
                patch.object(models.BaseModel, 'unlink', side_effect=forbidden):
            for filters in ({}, self.filters, self._period(self.today, self.today)):
                data = self.Dashboard.get_dashboard_data(filters)
                for key, extra, _count in self._figures(data):
                    self.Dashboard.action_dashboard_open(key, filters, extra)

    # ------------------------------------------------------------------ reports and menus
    def test_14_report_links_and_actions(self):
        """Reports & Quick Access: the reports that lost their menu (Active / Expiring Warranty,
        Free Service Due, Draft Warranty Review) and Warranty Unit Numbers, all existing actions;
        all report actions still open; the Dashboard is the first Warranty menu."""
        reports = self.Dashboard.get_dashboard_data({})['reports']
        self.assertEqual([r['xml_id'] for r in reports], [link[0] for link in REPORT_LINKS])
        self.assertEqual([r['name'] for r in reports],
                         ['Active / Expiring Warranty', 'Free Service Due', 'Draft Warranty Review',
                          'Warranty Unit Numbers'])
        removed = ['menu_report_active_expiring', 'menu_report_draft_review',
                   'menu_report_unit_warranty', 'menu_report_free_service_due']
        self.assertFalse(self.env['ir.model.data'].search([('model', '=', 'ir.ui.menu'),
                                                           ('name', 'in', removed)]))
        for xml_id in ('action_report_active_expiring', 'action_report_free_service_due',
                       'action_report_failure_pattern', 'action_report_repeated_failure',
                       'action_report_replacement', 'action_report_chargeable_revenue',
                       'action_report_draft_review', 'action_report_service_planning',
                       'action_report_helpdesk_pending', 'action_report_repair_backup'):
            action = self.env['ir.actions.act_window']._for_xml_id(
                'warranty_management_dashboard.%s' % xml_id)
            model = self.env[action['res_model']]
            for view_type in action['view_mode'].split(','):
                model.get_views([(False, view_type)])
            model.search(safe_eval(action['domain'] or '[]'), limit=1)
        root = self.env.ref('warranty_management.menu_warranty_root')
        first = root.child_id.sorted(lambda menu: (menu.sequence, menu.id))[:1]
        self.assertEqual(first,
                         self.env.ref('warranty_management_dashboard.menu_warranty_dashboard'))
