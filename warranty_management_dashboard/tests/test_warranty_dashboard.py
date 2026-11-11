from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation
from odoo.addons.warranty_management_dashboard.models.warranty_dashboard import APPROVALS


@tagged('post_install', '-at_install', 'warranty_dashboard')
class TestWarrantyDashboard(TransactionCase):
    """Warranty Dashboard (SRS 6 / 15 / 17): KPI definitions, drill-down = counted records,
    filters, access rights, multi-company and empty data. The figures are read in a product
    category of their own so that existing records of the database do not count."""

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

    # ------------------------------------------------------------------ KPI definitions
    def test_01_active_uses_validity_dates(self):
        """Correction 1: Active = confirmed AND valid today; a confirmed card whose end date
        has passed (expiry job not run yet) and an expired card are not active."""
        valid = self._card(self.today - timedelta(days=30))
        ended = self._card(self.today - timedelta(days=400))
        expired = self._card(self.today - timedelta(days=500))
        expired._warranty_apply_expiry(self.today)
        self.assertEqual((valid.state, ended.state, expired.state),
                         ('confirmed', 'confirmed', 'expired'))
        self.assertLess(ended.warranty_end_date, self.today)
        kpis = self.Dashboard.get_dashboard_data(self.filters)['kpis']
        self.assertEqual(kpis['active'], 1)
        self.assertEqual(self._records('active'), valid)

    def test_02_expiring_window(self):
        """Expiring = active cards ending within the selected window (30 / 60 / 90 days)."""
        soon = self._card(self.today - timedelta(days=350))     # ends in about 2 weeks
        later = self._card(self.today - timedelta(days=310))    # ends in about 7 weeks
        self._card(self.today - timedelta(days=30))             # ends in about 11 months
        data = self.Dashboard.get_dashboard_data(dict(self.filters, expiring_days=30))
        self.assertEqual(data['kpis']['expiring'], 1)
        self.assertEqual(self._records('expiring', dict(self.filters, expiring_days=30)), soon)
        data = self.Dashboard.get_dashboard_data(dict(self.filters, expiring_days=60))
        self.assertEqual(data['kpis']['expiring'], 2)
        self.assertEqual(self._records('expiring', dict(self.filters, expiring_days=60)),
                         soon | later)
        # Not an allowed window: the default 30 days.
        self.assertEqual(self.Dashboard._dashboard_filters({'expiring_days': 45})[
            'expiring_days'], 30)
        trend = data['charts']['expiry_trend']
        self.assertEqual(len(trend), 12)
        self.assertEqual(sum(row['value'] for row in trend), 3)

    def test_03_status_chart_and_status_filter(self):
        """Status chart counts each card once; Warranty Status filters the card figures."""
        self._card(self.today - timedelta(days=30))
        self._card(self.today - timedelta(days=30), confirm=False)
        chart = self.Dashboard.get_dashboard_data(self.filters)['charts']['card_status']
        self.assertEqual({row['key']: row['value'] for row in chart},
                         {'confirmed': 1, 'ready': 1})
        for row in chart:
            self.assertEqual(len(self._records('card_status', extra=row['extra'])), row['value'])
        data = self.Dashboard.get_dashboard_data(dict(self.filters, card_state='ready'))
        self.assertEqual(data['kpis']['active'], 0, 'Active needs Confirmed')
        self.assertEqual([row['key'] for row in data['charts']['card_status']], ['ready'])

    def test_04_every_kpi_drills_down_to_its_records(self):
        """The drill-down of every KPI opens exactly the counted records."""
        self._card(self.today - timedelta(days=30))
        self._card(self.today - timedelta(days=350))
        filters = dict(self.filters)
        kpis = self.Dashboard.get_dashboard_data(filters)['kpis']
        for key in ('active', 'expiring', 'pending_services', 'services_overdue',
                    'services_due', 'open_replacements', 'escalations', 'repeated_flagged'):
            self.assertEqual(len(self._records(key, filters)), kpis[key], key)
        for line in kpis['approvals']:
            self.assertEqual(len(self._records(line['key'], filters)), line['count'],
                             line['key'])

    def test_05_approvals_total_without_duplicates(self):
        """Correction 2: one line per approval type, total = sum of the lines; each line is
        the existing waiting state of its document."""
        kpis = self.Dashboard.get_dashboard_data({})['kpis']
        self.assertEqual(kpis['approvals_total'], sum(line['count'] for line in kpis['approvals']))
        self.assertEqual(len({line['key'] for line in kpis['approvals']}),
                         len(kpis['approvals']))
        for key, model, _title, domain, _action in APPROVALS:
            expected = self.env[model].search_count(
                [('company_id', 'in', self.env.companies.ids)] + domain)
            line = next(line for line in kpis['approvals'] if line['key'] == key)
            self.assertEqual(line['count'], expected, key)

    # ------------------------------------------------------------------ filters
    def test_06_empty_data(self):
        """A category without records: zeros, empty charts, no error."""
        data = self.Dashboard.get_dashboard_data({'category_id': self.empty_categ.id})
        kpis = data['kpis']
        for key in ('active', 'expiring', 'pending_services', 'open_replacements', 'escalations'):
            self.assertEqual(kpis[key], 0, key)
        self.assertEqual(data['charts']['card_status'], [])
        self.assertEqual(sum(r['value'] for r in data['charts']['expiry_trend']), 0)
        self.assertEqual(data['charts']['failures']['products'], [])
        finance = self.Dashboard.get_financial_data({'category_id': self.empty_categ.id})
        if finance['cost']['available']:
            self.assertEqual(finance['cost']['actual'], 0)

    def test_07_date_range(self):
        """Default range: 12 months to today; an inverted range is refused; dated figures
        use the range (one month per bar)."""
        filters = self.Dashboard._dashboard_filters({})
        self.assertEqual(filters['date_to'], self.today)
        self.assertEqual(filters['date_from'].day, 1)
        with self.assertRaises(UserError):
            self.Dashboard._dashboard_filters({'date_from': '2026-05-01',
                                               'date_to': '2026-04-01'})
        trend = self.Dashboard.get_dashboard_data(
            {'date_from': '2026-01-01', 'date_to': '2026-06-30'})['charts']['replacement_trend']
        self.assertEqual([m['key'] for m in trend['months']],
                         ['2026-01-01', '2026-02-01', '2026-03-01', '2026-04-01', '2026-05-01',
                          '2026-06-01'])
        domain = self.Dashboard._dashboard_domain(
            'warranty.case', self.Dashboard._dashboard_filters(
                {'date_from': '2026-01-01', 'date_to': '2026-01-31'}), 'create_date')
        self.assertEqual(len([leaf for leaf in domain if leaf[0] == 'create_date']), 2)

    def test_08_company_and_branch(self):
        """Correction 3: figures limited to the allowed companies; the branch filter is offered
        only when the selected company has branches; a company outside the user's companies
        is ignored."""
        other = self.env['res.company'].create({'name': 'Dashboard Other Co'})
        user = new_test_user(self.env, login='wd_company_user', groups='base.group_user',
                             company_id=self.company.id, company_ids=self.company.ids)
        dashboard = self.Dashboard.with_user(user).with_context(
            allowed_company_ids=self.company.ids)
        self._card(self.today - timedelta(days=30))
        options = dashboard.get_dashboard_data(self.filters)['options']
        self.assertEqual([c['id'] for c in options['companies']], self.company.ids)
        self.assertEqual(options['branches'], [])
        forced = dashboard.get_dashboard_data(dict(self.filters, company_id=other.id))['kpis']
        self.assertEqual(forced['active'], 1, 'a company the user cannot use is ignored')
        branch = self.env['res.company'].create({'name': 'Dashboard Branch',
                                                 'parent_id': self.company.id})
        admin = self.Dashboard.with_context(
            allowed_company_ids=(self.company | branch).ids)
        options = admin.get_dashboard_data({'company_id': self.company.id})['options']
        self.assertEqual([b['id'] for b in options['branches']], branch.ids)
        self.assertEqual(admin._dashboard_companies({'company_id': self.company.id,
                                                     'branch_id': branch.id}), branch)
        self.assertEqual(admin._dashboard_companies({'company_id': self.company.id,
                                                     'branch_id': False}),
                         self.company | branch)

    # ------------------------------------------------------------------ access rights
    def test_09_financial_access(self):
        """Cost, recovery and reserve only through the existing rights: a plain internal user
        sees none; an accounting user sees the reserve."""
        employee = new_test_user(self.env, login='wd_employee', groups='base.group_user',
                                 company_id=self.company.id, company_ids=self.company.ids)
        finance = self.Dashboard.with_user(employee).get_financial_data({})
        self.assertFalse(finance['cost']['available'])
        self.assertFalse(finance['reserve']['available'])
        self.assertFalse(self.env['warranty.cost.report'].sudo().search(
            [('create_uid', '=', employee.id)]), 'no cost rows built for the employee')
        accountant = new_test_user(
            self.env, login='wd_accountant',
            groups='base.group_user,account.group_account_readonly',
            company_id=self.company.id, company_ids=self.company.ids)
        finance = self.Dashboard.with_user(accountant).get_financial_data({})
        self.assertTrue(finance['reserve']['available'])

    def test_10_operational_access(self):
        """KPIs and approval lines follow the user's model rights; a figure the user cannot
        read is None (shown as "—"), never a sudo count, and cannot be opened."""
        employee = new_test_user(self.env, login='wd_employee2', groups='base.group_user',
                                 company_id=self.company.id, company_ids=self.company.ids)
        dashboard = self.Dashboard.with_user(employee)
        data = dashboard.get_dashboard_data({})
        for line in data['kpis']['approvals']:
            model = next(a[1] for a in APPROVALS if a[0] == line['key'])
            self.assertTrue(self.env[model].with_user(employee).has_access('read'))
        for report in data['reports']:
            action = self.env.ref(report['xml_id']).sudo()
            if action._name == 'ir.actions.act_window':
                self.assertTrue(self.env[action.res_model].with_user(employee).has_access('read'),
                                report['xml_id'])
        if data['kpis']['open_replacements'] is None:
            with self.assertRaises(AccessError):
                dashboard.action_dashboard_open('open_replacements', {})

    def test_12_failure_patterns_product_and_category_only(self):
        """Failure Pattern uses existing case data only: product and Failure Category (no
        brand / model); every bar opens exactly its counted failure cases."""
        failures = self.Dashboard.get_dashboard_data({})['charts']['failures']
        self.assertEqual(set(failures), {'categories', 'products', 'top'})
        for row in failures['products']:
            self.assertEqual(set(row), {'id', 'label', 'value'})
            self.assertEqual(len(self._records('failures', {}, {'product_ids': [row['id']]})),
                             row['value'], row['label'])
        for row in failures['categories']:
            self.assertEqual(len(self._records('failures', {}, row['extra'])), row['value'],
                             row['label'])
        self.assertEqual(sum(row['value'] for row in failures['products']),
                         sum(row['value'] for row in failures['categories']))

    def test_11_reports_and_menus(self):
        """SRS 15 report actions exist and open; the Dashboard is the first Warranty menu."""
        reports = self.Dashboard.get_dashboard_data({})['reports']
        names = {report['name'] for report in reports}
        for name in ('Active / Expiring Warranty', 'Free Service Due', 'Failure Pattern',
                     'Repeated Failure Escalation', 'Replacement', 'Chargeable Service Revenue',
                     'Draft Warranty Review', 'Unit Warranty Number',
                     'Service Merge and Job Planning', 'Helpdesk Pending Service',
                     'Repair and Backup Unit', 'Warranty Cost', 'Vendor Claim Recovery',
                     'Provision / Reserve Utilization', 'Material Approval and Cost'):
            self.assertIn(name, names)
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
        self.assertEqual(first, self.env.ref('warranty_management_dashboard.menu_warranty_dashboard'))
