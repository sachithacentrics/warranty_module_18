from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.warranty_management.models.warranty_service_entitlement import OPEN_STATES

EXPIRING_WINDOWS = (30, 60, 90)
OPEN_REPLACEMENT_STATES = ('draft', 'submitted', 'approved')
# Cards that were in force at some time: confirmed now, or confirmed and since expired.
IN_FORCE_STATES = ('confirmed', 'expired')

# Path from each source model to the product category of its record.
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
}

# Pending approvals: one line per approval type, each record counted once. The
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

# Reports & Quick Access: the reports whose Warranty > Reports menu was removed (2026-11-11)
# and the existing Warranty Unit Numbers list (also under Cards).
REPORT_LINKS = [
    ('warranty_management_dashboard.action_report_active_expiring', "Active / Expiring Warranty"),
    ('warranty_management_dashboard.action_report_free_service_due', "Free Service Due"),
    ('warranty_management_dashboard.action_report_draft_review', "Draft Warranty Review"),
    ('warranty_management.action_warranty_unit', "Warranty Unit Numbers"),
]


class WarrantyDashboard(models.AbstractModel):
    """Warranty Dashboard: quick view of warranty status, pending services,
    approvals, replacements and escalations, filtered by company, branch, product category,
    card status and date range. Reads the existing records with the user's own access rights
    (record rules, allowed companies) and writes nothing. Every figure is defined once
    (`_dashboard_spec`) and its drill-down opens the same domain in the existing action.

    Date range (empty = today's position) - the document date of each area:
    * Warranty Status: the warranty period (in force / ending in the period); the status
      breakdown counts the cards created in the period.
    * Pending Services: the due date.
    * Approvals, Replacements, Escalations: the creation date of the waiting document,
      replacement or warranty case."""
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
        """Validated filters: unknown keys and values outside the user's options are dropped.
        The date range is optional; either bound may be left open."""
        filters = dict(filters or {})
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
        if date_from and date_to and date_from > date_to:
            raise UserError(_("The start of the date range is after its end."))
        values.update(date_from=date_from or False, date_to=date_to or False)
        return values

    @api.model
    def _dashboard_period(self, filters):
        return bool(filters['date_from'] or filters['date_to'])

    @api.model
    def _dashboard_domain(self, model, filters, date_field=None):
        """Company, product category, card status (warranty cards) and, when `date_field` is
        given, the date range on that field."""
        domain = [('company_id', 'in', self._dashboard_companies(filters).ids)]
        if filters['category_id'] and model in CATEGORY_PATHS:
            domain.append((CATEGORY_PATHS[model], 'child_of', filters['category_id']))
        if filters['card_state'] and model == 'warranty.card':
            domain.append(('state', '=', filters['card_state']))
        if date_field:
            domain += self._dashboard_date_domain(model, date_field, filters)
        return domain

    @api.model
    def _dashboard_date_domain(self, model, date_field, filters):
        """`date_field` within the selected range (inclusive days; datetimes in the user's
        time zone)."""
        start, end = filters['date_from'], filters['date_to']
        domain = []
        if self.env[model]._fields[date_field].type == 'datetime':
            if start:
                domain.append((date_field, '>=', self._dashboard_utc(start)))
            if end:
                domain.append((date_field, '<', self._dashboard_utc(end + timedelta(days=1))))
        else:
            if start:
                domain.append((date_field, '>=', start))
            if end:
                domain.append((date_field, '<=', end))
        return domain

    @api.model
    def _dashboard_utc(self, day):
        """UTC datetime of the start of `day` in the user's time zone."""
        moment = fields.Datetime.to_datetime(day)
        offset = fields.Datetime.context_timestamp(self, moment).utcoffset() or timedelta()
        return moment - offset

    # ------------------------------------------------------------------ figure definitions
    @api.model
    def _dashboard_spec(self, key, filters, extra=None):
        """(model, domain, action xml id, title) of a figure; `extra` narrows it to one
        breakdown line (a card status or due indicator). The single source of every count and
        of its drill-down."""
        extra = extra or {}
        today = self._dashboard_today()
        period = self._dashboard_period(filters)
        approvals = {line[0]: line for line in APPROVALS}
        if key in approvals:
            _key, model, title, domain, action = approvals[key]
            return (model, self._dashboard_domain(
                model, filters, 'create_date' if period else None) + domain, action, _(title))
        card_action = 'warranty_management.action_warranty_card'
        if key in ('active', 'expiring'):
            domain = self._dashboard_domain('warranty.card', filters)
            if period:
                return self._dashboard_card_period(key, filters, domain, card_action)
            domain += [('state', '=', 'confirmed'), ('warranty_start_date', '<=', today)]
            if key == 'active':
                # Valid today: end date not passed (usage-based cards may have no end date).
                domain += ['|', ('warranty_end_date', '>=', today),
                           '&', ('warranty_end_date', '=', False), ('warranty_basis', '=', 'usage')]
                return 'warranty.card', domain, card_action, _("Active Warranties")
            end = today + timedelta(days=filters['expiring_days'])
            domain += [('warranty_end_date', '>=', today), ('warranty_end_date', '<=', end)]
            return 'warranty.card', domain, card_action, _(
                "Warranties Expiring within %s Days", filters['expiring_days'])
        if key == 'card_status':
            domain = self._dashboard_domain('warranty.card', filters,
                                            'create_date' if period else None)
            if extra.get('state'):
                domain.append(('state', '=', extra['state']))
            return 'warranty.card', domain, card_action, _("Warranty Cards")
        if key in ('pending_services', 'services_overdue', 'services_due', 'services_by_due'):
            domain = self._dashboard_domain('warranty.service.entitlement', filters,
                                            'due_date' if period else None)
            domain.append(('state', 'in', OPEN_STATES))
            if key == 'services_overdue':
                domain.append(('due_status', '=', 'overdue'))
            elif key == 'services_due':
                domain.append(('due_status', '=', 'due'))
            elif key == 'services_by_due' and 'due_status' in extra:
                domain.append(('due_status', '=', extra['due_status'] or False))
            return ('warranty.service.entitlement', domain,
                    'warranty_management.action_warranty_service_entitlement',
                    _("Pending Warranty Services"))
        if key == 'open_replacements':
            domain = self._dashboard_domain('warranty.replacement', filters,
                                            'create_date' if period else None)
            domain.append(('state', 'in', OPEN_REPLACEMENT_STATES))
            return ('warranty.replacement', domain,
                    'warranty_management_repair.action_warranty_replacement',
                    _("Open Replacements"))
        if key in ('escalations', 'repeated_flagged'):
            domain = self._dashboard_domain('warranty.case', filters,
                                            'create_date' if period else None)
            if key == 'escalations':
                domain.append(('escalation_pending', '=', True))
                title = _("Repeated Failure Escalations")
            else:
                domain += [('repeated_failure_flag', '=', True),
                           ('state', 'not in', ('closed', 'rejected'))]
                title = _("Open Repeated Failure Cases")
            return ('warranty.case', domain,
                    'warranty_management_helpdesk.action_warranty_case', title)
        raise UserError(_("Unknown dashboard figure %s.", key))

    @api.model
    def _dashboard_card_period(self, key, filters, domain, card_action):
        """Warranty Status for a date range. In force: a confirmed or since-expired card whose
        warranty period overlaps the range. Ending: such a card whose end date is in the
        range. Suspended / cancelled cards are not counted (their current status only is
        known)."""
        start, end = filters['date_from'], filters['date_to']
        domain = domain + [('state', 'in', IN_FORCE_STATES)]
        if key == 'active':
            domain.append(('warranty_start_date', '!=', False))
            if end:
                domain.append(('warranty_start_date', '<=', end))
            if start:
                domain += ['|', ('warranty_end_date', '>=', start),
                           '&', ('warranty_end_date', '=', False), ('warranty_basis', '=', 'usage')]
            return 'warranty.card', domain, card_action, _("Warranties in Force in the Period")
        domain.append(('warranty_end_date', '!=', False))
        domain += self._dashboard_date_domain('warranty.card', 'warranty_end_date', filters)
        return 'warranty.card', domain, card_action, _("Warranties Ending in the Period")

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
    def _dashboard_group(self, key, filters, groupby):
        model, domain, _action, _title = self._dashboard_spec(key, filters)
        if not self._dashboard_readable(model):
            return None
        return dict(self.env[model]._read_group(domain, [groupby], ['__count']))

    # ------------------------------------------------------------------ public API
    @api.model
    def get_dashboard_data(self, filters=None):
        """Filter options and the five dashboard areas."""
        filters = self._dashboard_filters(filters)
        return {
            'filters': {key: (fields.Date.to_string(value) if key.startswith('date_') and value
                              else value)
                        for key, value in filters.items()},
            'period': self._dashboard_period(filters),
            'options': self._dashboard_options(filters),
            'warranty': self._area_warranty(filters),
            'services': self._area_services(filters),
            'approvals': self._area_approvals(filters),
            'replacements': {
                'open': self._dashboard_count('open_replacements', filters),
                'submitted': self._dashboard_count('appr_replacement', filters),
            },
            'escalations': {
                'pending': self._dashboard_count('escalations', filters),
                'repeated': self._dashboard_count('repeated_flagged', filters),
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
                            self._dashboard_selection('warranty.card', 'state').items()],
            'expiring_windows': list(EXPIRING_WINDOWS),
        }

    @api.model
    def _area_warranty(self, filters):
        counts = self._dashboard_group('card_status', filters, 'state')
        by_status = None
        if counts is not None:
            labels = self._dashboard_selection('warranty.card', 'state')
            by_status = [{'key': state, 'label': labels[state], 'value': counts[state],
                          'extra': {'state': state}}
                         for state in labels if counts.get(state)]
        return {
            'active': self._dashboard_count('active', filters),
            'expiring': self._dashboard_count('expiring', filters),
            'expiring_days': filters['expiring_days'],
            'by_status': by_status,
        }

    @api.model
    def _area_services(self, filters):
        counts = self._dashboard_group('services_by_due', filters, 'due_status')
        by_due = None
        if counts is not None:
            labels = self._dashboard_selection('warranty.service.entitlement', 'due_status')
            by_due = [{'key': status, 'label': labels[status], 'value': counts.get(status, 0),
                       'extra': {'due_status': status}}
                      for status in ('overdue', 'due', 'upcoming')]
            by_due.append({'key': 'none', 'label': _("Not Yet in Alert Window"),
                           'value': counts.get(False, 0), 'extra': {'due_status': False}})
        return {
            'open': self._dashboard_count('pending_services', filters),
            'overdue': self._dashboard_count('services_overdue', filters),
            'due': self._dashboard_count('services_due', filters),
            'by_due': by_due,
        }

    @api.model
    def _area_approvals(self, filters):
        lines = []
        for key, _model, title, _domain, _action in APPROVALS:
            count = self._dashboard_count(key, filters)
            if count is not None:
                lines.append({'key': key, 'label': _(title), 'count': count})
        return {'lines': lines, 'total': sum(line['count'] for line in lines)}

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

    # ------------------------------------------------------------------ report links
    @api.model
    def _dashboard_reports(self):
        """Links to the reports that have no Warranty > Reports menu, for the users who
        may open them."""
        result = []
        for xml_id, name in REPORT_LINKS:
            action = self.env.ref(xml_id, raise_if_not_found=False)
            if not action or not self._dashboard_action_allowed(action):
                continue
            result.append({'xml_id': xml_id, 'name': _(name)})
        return result

    @api.model
    def _dashboard_action_allowed(self, action):
        action = action.sudo()
        if action.groups_id and not (action.groups_id & self.env.user.groups_id):
            return False
        return action._name == 'ir.actions.act_window' and \
            self._dashboard_readable(action.res_model)
