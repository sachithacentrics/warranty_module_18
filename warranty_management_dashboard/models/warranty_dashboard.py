from datetime import date, timedelta

from babel.dates import format_date as babel_format_date
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import babel_locale_parse, get_lang

from odoo.addons.warranty_management.models.warranty_service_entitlement import OPEN_STATES
from odoo.addons.warranty_management_accounting.models.warranty_reserve_report import \
    ACCOUNTING_GROUPS
from odoo.addons.warranty_management_helpdesk.models.warranty_case import FAILURE_CASE_TYPES

EXPIRING_WINDOWS = (30, 60, 90)
OPEN_REPLACEMENT_STATES = ('draft', 'submitted', 'approved')
# Financial report rows are rebuilt by the existing report builders at most this often.
REPORT_REFRESH = timedelta(minutes=10)
TOP_PRODUCTS = 8

# Path from each source model to the company and to the product category of its record.
CATEGORY_PATHS = {
    'warranty.card': 'product_id.categ_id',
    'warranty.service.entitlement': 'warranty_card_id.product_id.categ_id',
    'warranty.case': 'product_id.categ_id',
    'warranty.replacement': 'product_id.categ_id',
    'warranty.vendor.claim': 'case_id.product_id.categ_id',
    'material.purchase.requisition': 'warranty_case_id.product_id.categ_id',
    'warranty.card.action': 'card_id.product_id.categ_id',
    'warranty.card.download.request': 'warranty_card_id.product_id.categ_id',
    'warranty.service.date.exception.group': 'case_id.product_id.categ_id',
    'warranty.cost.report': 'product_id.categ_id',
    'warranty.reserve.report': 'category_id',
}
# Card status filter: path to the warranty card status (card-based figures only).
CARD_STATE_PATHS = {
    'warranty.card': 'state',
}

# Pending approvals (SRS 15 / 16): one line per approval type, each record counted once. The
# domains are those of the existing "waiting" filters / states of each document.
APPROVALS = [
    ('appr_case', 'warranty.case', "Warranty cases",
     [('state', '=', 'eligibility_checked'), ('eligibility_result', '=', 'eligible')],
     'warranty_management_helpdesk.action_warranty_case'),
    ('appr_mrf', 'material.purchase.requisition', "Material requests",
     [('is_warranty_mrf', '=', True), ('warranty_mrf_status', 'in', ('manager', 'finance_gm'))],
     'warranty_management_mrf.action_warranty_material_request'),
    ('appr_replacement', 'warranty.replacement', "Replacements",
     [('state', '=', 'submitted')],
     'warranty_management_repair.action_warranty_replacement'),
    ('appr_vendor_claim', 'warranty.vendor.claim', "Vendor claims",
     [('state', '=', 'to_approve')],
     'warranty_management_mrf.action_warranty_vendor_claim'),
    ('appr_card_action', 'warranty.card.action', "Card controlled actions",
     [('state', '=', 'pending')],
     'warranty_management.action_warranty_card_action'),
    ('appr_download', 'warranty.card.download.request', "Card download requests",
     [('state', '=', 'to_approve')],
     'warranty_management.action_warranty_card_download_request'),
    ('appr_date_exception', 'warranty.service.date.exception.group', "Service date exceptions",
     [('state', '=', 'requested')],
     'warranty_management_helpdesk.action_warranty_service_date_exception_group'),
]


class WarrantyDashboard(models.AbstractModel):
    """Warranty Dashboard (SRS 6 / 15 / 17). Reads the existing warranty records with the
    user's own access rights (record rules, allowed companies); writes nothing except the
    rows of the existing cost and reserve reports, through their own builders and access
    checks. Every figure is defined once (`_dashboard_spec`) and its drill-down opens the same
    domain in the existing action."""
    _name = 'warranty.dashboard'
    _description = 'Warranty Dashboard'

    # ------------------------------------------------------------------ filters
    @api.model
    def _dashboard_today(self):
        return fields.Date.context_today(self)

    @api.model
    def _dashboard_companies(self, filters):
        """Companies of the figures: the selected branch, else the selected company and its
        branches, else all companies selected in the company switcher."""
        allowed = self.env.companies
        branch = filters.get('branch_id') and allowed.filtered(
            lambda company: company.id == filters['branch_id'])
        if branch:
            return branch
        company = filters.get('company_id') and allowed.filtered(
            lambda company: company.id == filters['company_id'])
        if company:
            return allowed.filtered(lambda other: other == company or other.parent_id == company)
        return allowed

    @api.model
    def _dashboard_filters(self, filters):
        """Validated filters: unknown keys and values outside the user's options are dropped."""
        filters = dict(filters or {})
        today = self._dashboard_today()
        values = {
            'company_id': filters.get('company_id') or False,
            'branch_id': filters.get('branch_id') or False,
            'category_id': filters.get('category_id') or False,
            'card_state': filters.get('card_state') or False,
            'expiring_days': filters.get('expiring_days') if filters.get('expiring_days') in
            EXPIRING_WINDOWS else EXPIRING_WINDOWS[0],
        }
        states = dict(self.env['warranty.card']._fields['state'].selection)
        if values['card_state'] not in states:
            values['card_state'] = False
        date_from = filters.get('date_from') and fields.Date.to_date(filters['date_from'])
        date_to = filters.get('date_to') and fields.Date.to_date(filters['date_to'])
        if not date_to:
            date_to = today
        if not date_from:
            date_from = date_to.replace(day=1) - relativedelta(months=11)
        if date_from > date_to:
            raise UserError(_("The start of the date range is after its end."))
        values.update(date_from=date_from, date_to=date_to)
        return values

    @api.model
    def _dashboard_domain(self, model, filters, date_field=None):
        """Company, product category, card status (card figures) and date range of a figure."""
        domain = [('company_id', 'in', self._dashboard_companies(filters).ids)]
        if filters['category_id'] and model in CATEGORY_PATHS:
            domain.append((CATEGORY_PATHS[model], 'child_of', filters['category_id']))
        if filters['card_state'] and model in CARD_STATE_PATHS:
            domain.append((CARD_STATE_PATHS[model], '=', filters['card_state']))
        if date_field:
            field = self.env[model]._fields[date_field]
            start, end = filters['date_from'], filters['date_to']
            if field.type == 'datetime':
                start, end = self._dashboard_datetime_range(start, end)
                domain += [(date_field, '>=', start), (date_field, '<', end)]
            else:
                domain += [(date_field, '>=', start), (date_field, '<=', end)]
        return domain

    @api.model
    def _dashboard_datetime_range(self, start, end):
        """UTC bounds of the user's local days start .. end (inclusive)."""
        tz_start = fields.Datetime.context_timestamp(self, fields.Datetime.to_datetime(start))
        offset = tz_start.utcoffset() or timedelta()
        return (fields.Datetime.to_datetime(start) - offset,
                fields.Datetime.to_datetime(end + timedelta(days=1)) - offset)

    # ------------------------------------------------------------------ figure definitions
    @api.model
    def _dashboard_spec(self, key, filters, extra=None):
        """(model, domain, action xml id, title) of a figure; `extra` narrows it to one chart
        segment (a status, month, product, ...). The single source of every count and of its
        drill-down."""
        extra = extra or {}
        today = self._dashboard_today()
        approvals = {line[0]: line for line in APPROVALS}
        if key in approvals:
            _key, model, title, domain, action = approvals[key]
            return model, self._dashboard_domain(model, filters) + domain, action, _(title)
        card_action = 'warranty_management.action_warranty_card'
        if key in ('active', 'expiring', 'expiry_trend'):
            domain = self._dashboard_domain('warranty.card', filters) + [
                ('state', '=', 'confirmed'), ('warranty_start_date', '<=', today)]
            if key == 'active':
                # Valid today: end date not passed (usage-based cards may have no end date).
                domain += ['|', ('warranty_end_date', '>=', today),
                           '&', ('warranty_end_date', '=', False), ('warranty_basis', '=', 'usage')]
                return 'warranty.card', domain, card_action, _("Active Warranties")
            if key == 'expiring':
                end = today + timedelta(days=filters['expiring_days'])
                domain += [('warranty_end_date', '>=', today), ('warranty_end_date', '<=', end)]
                return 'warranty.card', domain, card_action, _(
                    "Warranties Expiring within %s Days", filters['expiring_days'])
            start = today.replace(day=1)
            month = extra.get('month')
            if month:
                start = max(fields.Date.to_date(month), today)
                end = fields.Date.to_date(month) + relativedelta(months=1, days=-1)
            else:
                end = start + relativedelta(months=12, days=-1)
            domain += [('warranty_end_date', '>=', max(start, today)),
                       ('warranty_end_date', '<=', end)]
            return 'warranty.card', domain, card_action, _("Active Warranties by Expiry Month")
        if key == 'card_status':
            domain = self._dashboard_domain('warranty.card', filters)
            if extra.get('state'):
                domain.append(('state', '=', extra['state']))
            return 'warranty.card', domain, card_action, _("Warranty Cards")
        if key in ('pending_services', 'services_overdue', 'services_due', 'service_due_chart'):
            domain = self._dashboard_domain('warranty.service.entitlement', filters) + [
                ('state', 'in', OPEN_STATES)]
            if key == 'services_overdue':
                domain.append(('due_status', '=', 'overdue'))
            elif key == 'services_due':
                domain.append(('due_status', '=', 'due'))
            elif key == 'service_due_chart' and 'due_status' in extra:
                domain.append(('due_status', '=', extra['due_status'] or False))
            return ('warranty.service.entitlement', domain,
                    'warranty_management.action_warranty_service_entitlement',
                    _("Pending Warranty Services"))
        if key in ('open_replacements', 'replacement_trend'):
            model = 'warranty.replacement'
            action = 'warranty_management_repair.action_warranty_replacement'
            if key == 'open_replacements':
                domain = self._dashboard_domain(model, filters) + [
                    ('state', 'in', OPEN_REPLACEMENT_STATES)]
                return model, domain, action, _("Open Replacements")
            domain = self._dashboard_domain(model, filters, 'requested_date') + [
                ('state', '!=', 'rejected')]
            domain += self._dashboard_month_domain(model, 'requested_date', extra.get('month'))
            if extra.get('replacement_type'):
                domain.append(('replacement_type', '=', extra['replacement_type']))
            return model, domain, action, _("Replacements")
        case_action = 'warranty_management_helpdesk.action_warranty_case'
        if key == 'escalations':
            domain = self._dashboard_domain('warranty.case', filters) + [
                ('escalation_pending', '=', True)]
            return 'warranty.case', domain, case_action, _("Repeated Failure Escalations")
        if key == 'repeated_flagged':
            domain = self._dashboard_domain('warranty.case', filters) + [
                ('repeated_failure_flag', '=', True), ('state', 'not in', ('closed', 'rejected'))]
            return 'warranty.case', domain, case_action, _("Open Repeated Failure Cases")
        if key == 'repeated_trend':
            domain = self._dashboard_domain('warranty.case', filters, 'create_date') + [
                ('repeated_failure_flag', '=', True)]
            domain += self._dashboard_month_domain('warranty.case', 'create_date',
                                                   extra.get('month'))
            return 'warranty.case', domain, case_action, _("Repeated Failure Cases")
        if key == 'failures':
            domain = self._dashboard_domain('warranty.case', filters, 'create_date') + [
                ('case_type', 'in', FAILURE_CASE_TYPES)]
            if 'failure_category' in extra:
                domain.append(('failure_category', '=', extra['failure_category'] or False))
            if extra.get('product_ids') is not None:
                domain.append(('product_id', 'in', extra['product_ids'] or [False]))
            return 'warranty.case', domain, case_action, _("Failure Cases")
        if key == 'vendor_claims':
            domain = self._dashboard_domain('warranty.vendor.claim', filters, 'create_date') + [
                ('state', '!=', 'cancel')]
            if extra.get('recovery_status'):
                domain.append(('recovery_status', '=', extra['recovery_status']))
            return ('warranty.vendor.claim', domain,
                    'warranty_management_mrf.action_warranty_vendor_claim', _("Vendor Claims"))
        if key == 'cost':
            domain = self._dashboard_domain('warranty.cost.report', filters, 'cost_date') + [
                ('create_uid', '=', self.env.uid)]
            if extra.get('cost_type'):
                domain.append(('cost_type', '=', extra['cost_type']))
            return ('warranty.cost.report', domain,
                    'warranty_management_accounting.action_warranty_cost_report',
                    _("Warranty Cost"))
        if key == 'reserve':
            domain = self._dashboard_domain('warranty.reserve.report', filters, 'date') + [
                ('create_uid', '=', self.env.uid)]
            if extra.get('movement_type'):
                domain.append(('movement_type', '=', extra['movement_type']))
            return ('warranty.reserve.report', domain,
                    'warranty_management_accounting.action_warranty_reserve_report',
                    _("Warranty Provision / Reserve"))
        raise UserError(_("Unknown dashboard figure %s.", key))

    @api.model
    def _dashboard_month_domain(self, model, field_name, month):
        if not month:
            return []
        start = fields.Date.to_date(month)
        end = start + relativedelta(months=1)
        if self.env[model]._fields[field_name].type == 'datetime':
            start, end = self._dashboard_datetime_range(start, end - timedelta(days=1))
        return [(field_name, '>=', start), (field_name, '<', end)]

    # ------------------------------------------------------------------ helpers
    @api.model
    def _dashboard_readable(self, model):
        return model in self.env and self.env[model].has_access('read')

    @api.model
    def _dashboard_count(self, key, filters, extra=None):
        model, domain, _action, _title = self._dashboard_spec(key, filters, extra)
        if not self._dashboard_readable(model):
            return None
        return self.env[model].search_count(domain)

    @api.model
    def _dashboard_selection(self, model, field_name):
        return dict(self.env[model]._fields[field_name]._description_selection(self.env))

    @api.model
    def _dashboard_group(self, key, filters, groupby, aggregates=('__count',), extra=None):
        model, domain, _action, _title = self._dashboard_spec(key, filters, extra)
        if not self._dashboard_readable(model):
            return None
        return self.env[model]._read_group(domain, list(groupby), list(aggregates))

    @api.model
    def _dashboard_months(self, start, count):
        return [start + relativedelta(months=index) for index in range(count)]

    @api.model
    def _dashboard_month_label(self, month):
        """Month name in the user's language (e.g. "Nov 2026", "nov. 2026")."""
        return babel_format_date(month, format='MMM y',
                                 locale=babel_locale_parse(get_lang(self.env).code))

    # ------------------------------------------------------------------ public API
    @api.model
    def get_dashboard_data(self, filters=None):
        """Filter options, KPI cards and the operational charts (no financial figure)."""
        filters = self._dashboard_filters(filters)
        return {
            'filters': {key: (fields.Date.to_string(value) if isinstance(value, date) else value)
                        for key, value in filters.items()},
            'options': self._dashboard_options(filters),
            'kpis': self._dashboard_kpis(filters),
            'charts': {
                'card_status': self._chart_card_status(filters),
                'expiry_trend': self._chart_expiry_trend(filters),
                'service_due': self._chart_service_due(filters),
                'failures': self._chart_failures(filters),
                'replacement_trend': self._chart_replacement_trend(filters),
            },
            'reports': self._dashboard_reports(),
        }

    @api.model
    def _dashboard_options(self, filters):
        allowed = self.env.companies
        company = filters['company_id'] and allowed.filtered(
            lambda c: c.id == filters['company_id'])
        # Branch filter only where the selected company has branches the user may see.
        branches = allowed.filtered(lambda c: company and c.parent_id == company)
        Category = self.env['product.category']
        categories = Category.search_read([], ['display_name'], order='complete_name') \
            if Category.has_access('read') else []
        return {
            'companies': [{'id': c.id, 'name': c.name} for c in allowed],
            'branches': [{'id': c.id, 'name': c.name} for c in branches],
            'categories': [{'id': c['id'], 'name': c['display_name']} for c in categories],
            'card_states': [{'id': key, 'name': label} for key, label in
                            self.env['warranty.card']._fields['state']._description_selection(
                                self.env)],
            'expiring_windows': list(EXPIRING_WINDOWS),
            'currency': self._dashboard_currency(filters),
        }

    @api.model
    def _dashboard_currency(self, filters):
        currencies = self._dashboard_companies(filters).currency_id
        currency = currencies if len(currencies) == 1 else self.env.company.currency_id
        return {'id': currency.id, 'symbol': currency.symbol, 'position': currency.position,
                'mixed': len(currencies) > 1}

    @api.model
    def _dashboard_kpis(self, filters):
        approvals = []
        for key, model, title, _domain, _action in APPROVALS:
            count = self._dashboard_count(key, filters)
            if count is not None:
                approvals.append({'key': key, 'label': _(title), 'count': count})
        return {
            'active': self._dashboard_count('active', filters),
            'expiring': self._dashboard_count('expiring', filters),
            'expiring_days': filters['expiring_days'],
            'pending_services': self._dashboard_count('pending_services', filters),
            'services_overdue': self._dashboard_count('services_overdue', filters),
            'services_due': self._dashboard_count('services_due', filters),
            'approvals': approvals,
            'approvals_total': sum(line['count'] for line in approvals),
            'open_replacements': self._dashboard_count('open_replacements', filters),
            'replacements_submitted': self._dashboard_count('appr_replacement', filters),
            'escalations': self._dashboard_count('escalations', filters),
            'repeated_flagged': self._dashboard_count('repeated_flagged', filters),
        }

    # ------------------------------------------------------------------ operational charts
    @api.model
    def _chart_card_status(self, filters):
        groups = self._dashboard_group('card_status', filters, ['state'])
        if groups is None:
            return None
        labels = self._dashboard_selection('warranty.card', 'state')
        counts = dict(groups)
        return [{'key': state, 'label': labels[state], 'value': counts.get(state, 0),
                 'extra': {'state': state}}
                for state in labels if counts.get(state)]

    @api.model
    def _chart_expiry_trend(self, filters):
        groups = self._dashboard_group('expiry_trend', filters, ['warranty_end_date:month'])
        if groups is None:
            return None
        counts = {month: count for month, count in groups}
        start = self._dashboard_today().replace(day=1)
        return [{'key': fields.Date.to_string(month), 'label': self._dashboard_month_label(month),
                 'value': counts.get(month, 0), 'extra': {'month': fields.Date.to_string(month)}}
                for month in self._dashboard_months(start, 12)]

    @api.model
    def _chart_service_due(self, filters):
        groups = self._dashboard_group('service_due_chart', filters, ['due_status'])
        if groups is None:
            return None
        labels = self._dashboard_selection('warranty.service.entitlement', 'due_status')
        counts = dict(groups)
        rows = [{'key': status, 'label': labels[status], 'value': counts.get(status, 0),
                 'extra': {'due_status': status}}
                for status in ('overdue', 'due', 'upcoming')]
        rows.append({'key': 'none', 'label': _("Not Yet in Alert Window"),
                     'value': counts.get(False, 0), 'extra': {'due_status': False}})
        return rows

    @api.model
    def _chart_failures(self, filters):
        """Failure cases (SRS 15 Failure Pattern) by product and by the case's Failure Category
        (existing warranty case fields only; brand / model are not used, decision 2026-11-08)."""
        by_category = self._dashboard_group('failures', filters, ['failure_category'])
        if by_category is None:
            return None
        labels = self._dashboard_selection('warranty.case', 'failure_category')
        categories = [{'key': key or 'none', 'label': labels.get(key, _("Not Set")),
                       'value': count, 'extra': {'failure_category': key or False}}
                      for key, count in sorted(by_category, key=lambda row: -row[1])]
        products = [{'id': product.id,
                     'label': product.display_name if product else _("No Product"),
                     'value': count}
                    for product, count in sorted(
                        self._dashboard_group('failures', filters, ['product_id']),
                        key=lambda row: -row[1])]
        return {'categories': categories, 'products': products, 'top': TOP_PRODUCTS}

    @api.model
    def _chart_replacement_trend(self, filters):
        months = self._dashboard_months(
            filters['date_from'].replace(day=1),
            (filters['date_to'].year - filters['date_from'].year) * 12
            + filters['date_to'].month - filters['date_from'].month + 1)
        replacements = self._dashboard_group('replacement_trend', filters,
                                             ['requested_date:month'])
        repeated = self._dashboard_group('repeated_trend', filters, ['create_date:month'])
        if replacements is None and repeated is None:
            return None

        def series(groups):
            if groups is None:
                return None
            counts = {(value.date() if hasattr(value, 'date') else value): count
                      for value, count in groups}
            return [counts.get(month, 0) for month in months]

        return {
            'months': [{'key': fields.Date.to_string(m), 'label': self._dashboard_month_label(m)}
                       for m in months],
            'replacements': series(replacements),
            'repeated': series(repeated),
        }

    # ------------------------------------------------------------------ financial sections
    @api.model
    def get_financial_data(self, filters=None, refresh=False):
        """Cost (SRS 17 / 15 Warranty Cost), vendor recovery and provision / reserve figures.
        Each section is shown only to users the existing report or record rights allow."""
        filters = self._dashboard_filters(filters)
        return {
            'cost': self._financial_cost(filters, refresh),
            'recovery': self._financial_recovery(filters),
            'reserve': self._financial_reserve(filters, refresh),
            'currency': self._dashboard_currency(filters),
        }

    @api.model
    def _dashboard_fresh(self, model):
        latest = self.env[model].search([('create_uid', '=', self.env.uid)],
                                        order='create_date desc', limit=1)
        return latest and fields.Datetime.now() - latest.create_date < REPORT_REFRESH

    @api.model
    def _financial_cost(self, filters, refresh):
        Report = self.env['warranty.cost.report']
        if not Report._warranty_report_companies() or not Report.has_access('read'):
            return {'available': False}
        if refresh or not self._dashboard_fresh('warranty.cost.report'):
            Report._warranty_report_rebuild()   # the report's own builder and access check
        groups = self._dashboard_group(
            'cost', filters, ['cost_type'],
            ['actual_amount:sum', 'recovered_amount:sum', 'net_amount:sum',
             'estimated_amount:sum', 'approved_amount:sum'])
        labels = self._dashboard_selection('warranty.cost.report', 'cost_type')
        rows = [{'key': cost_type, 'label': labels[cost_type], 'actual': actual,
                 'recovered': recovered, 'extra': {'cost_type': cost_type}}
                for cost_type, actual, recovered, _net, _est, _appr in groups
                if actual or recovered]
        return {
            'available': True,
            'rows': rows,
            'actual': sum(row[1] for row in groups),
            'recovered': sum(row[2] for row in groups),
            'net': sum(row[3] for row in groups),
            'estimated': sum(row[4] for row in groups),
            'approved': sum(row[5] for row in groups),
        }

    @api.model
    def _financial_recovery(self, filters):
        if not self._dashboard_readable('warranty.vendor.claim'):
            return {'available': False}
        fields_ = ['claimed_amount', 'accepted_amount', 'recovered_amount', 'outstanding_amount',
                   'written_off_amount']
        groups = self._dashboard_group('vendor_claims', filters, ['recovery_status'],
                                       ['__count'] + ['%s:sum' % name for name in fields_])
        labels = self._dashboard_selection('warranty.vendor.claim', 'recovery_status')
        totals = dict.fromkeys(fields_, 0.0)
        statuses = []
        for row in groups:
            status, count, amounts = row[0], row[1], row[2:]
            for name, amount in zip(fields_, amounts):
                totals[name] += amount
            statuses.append({'key': status, 'label': labels.get(status, status),
                             'count': count, 'extra': {'recovery_status': status}})
        return dict(available=True, statuses=statuses,
                    claims=sum(line['count'] for line in statuses), **totals)

    @api.model
    def _financial_reserve(self, filters, refresh):
        if not any(self.env.user.has_group(group) for group in ACCOUNTING_GROUPS):
            return {'available': False}
        Report = self.env['warranty.reserve.report']
        if refresh or not self._dashboard_fresh('warranty.reserve.report'):
            Report.action_open_warranty_reserve_report()   # the report's own builder
        names = ['provision_amount', 'reversal_amount', 'utilization_amount', 'release_amount',
                 'other_amount', 'reserve_amount', 'draft_amount', 'actual_cost_amount']
        groups = self._dashboard_group('reserve', filters, [], ['%s:sum' % n for n in names])
        totals = dict(zip(names, groups[0])) if groups else dict.fromkeys(names, 0.0)
        return dict(available=True, **{name: totals[name] or 0.0 for name in names})

    # ------------------------------------------------------------------ drill-down
    @api.model
    def action_dashboard_open(self, key, filters=None, extra=None):
        """The existing action of a figure, restricted to the records it counts."""
        filters = self._dashboard_filters(filters)
        model, domain, xml_id, title = self._dashboard_spec(key, filters, extra)
        if not self._dashboard_readable(model):
            raise AccessError(_("You cannot open these records."))
        action = self.env['ir.actions.act_window']._for_xml_id(xml_id)
        action.update({
            'name': title,
            'display_name': title,
            'domain': domain,
            'context': {'create': False},
            'target': 'current',
        })
        return action

    # ------------------------------------------------------------------ SRS 15 reports
    @api.model
    def _dashboard_reports(self):
        """Report shortcuts the user may open (existing actions + this module's report
        actions); AMC Visit Schedule only with the AMC module and its rights."""
        reports = [
            ('warranty_management_dashboard.action_report_active_expiring', "Active / Expiring Warranty"),
            ('warranty_management_dashboard.action_report_free_service_due', "Free Service Due"),
            ('warranty_management_accounting.action_server_warranty_cost_report', "Warranty Cost"),
            ('warranty_management_dashboard.action_report_failure_pattern', "Failure Pattern"),
            ('warranty_management_dashboard.action_report_repeated_failure',
             "Repeated Failure Escalation"),
            ('warranty_management_dashboard.action_report_replacement', "Replacement"),
            ('warranty_management_mrf.action_warranty_vendor_claim_recovery_report',
             "Vendor Claim Recovery"),
            ('warranty_management_dashboard.action_report_chargeable_revenue',
             "Chargeable Service Revenue"),
            ('warranty_management_accounting.action_server_warranty_reserve_report',
             "Provision / Reserve Utilization"),
            ('warranty_management_dashboard.action_report_draft_review', "Draft Warranty Review"),
            ('warranty_management.action_warranty_unit', "Unit Warranty Number"),
            ('warranty_management_dashboard.action_report_service_planning',
             "Service Merge and Job Planning"),
            ('warranty_management_dashboard.action_report_helpdesk_pending',
             "Helpdesk Pending Service"),
            ('warranty_management_dashboard.action_report_repair_backup',
             "Repair and Backup Unit"),
            ('warranty_management_mrf.action_warranty_mrf_approval_cost_report',
             "Material Approval and Cost"),
            ('warranty_management.action_warranty_history', "Warranty History"),
            ('amc_management.amc_contract_visit_action_schedule_report', "AMC Visit Schedule"),
        ]
        result = []
        for xml_id, name in reports:
            action = self.env.ref(xml_id, raise_if_not_found=False)
            if not action or not self._dashboard_action_allowed(action):
                continue
            result.append({'xml_id': xml_id, 'name': _(name),
                           'amc': xml_id.startswith('amc_management.')})
        return result

    @api.model
    def _dashboard_action_allowed(self, action):
        action = action.sudo()
        if action.groups_id and not (action.groups_id & self.env.user.groups_id):
            return False
        if action._name == 'ir.actions.act_window':
            return self._dashboard_readable(action.res_model)
        if action._name == 'ir.actions.server':
            # The server actions of the cost / reserve reports check their own rights; list
            # them only for the users of their menus.
            menus = self.env['ir.ui.menu'].sudo().search(
                [('action', '=', '%s,%s' % (action._name, action.id))])
            return any(not menu.groups_id or menu.groups_id & self.env.user.groups_id
                       for menu in menus)
        return True
