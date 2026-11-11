from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import format_amount

# Part 8.3 (doc/part8_3_accounting_config_design.md): accounting configuration on existing models,
# no rule model and no journal entry. Later stages read it through res.company.
ACCOUNTING_READ_GROUPS = 'account.group_account_readonly,account.group_account_invoice'
COMPANY_METHODS = [
    ('disabled', 'Disabled'),
    ('fixed', 'Fixed Amount per Unit'),
    ('percentage', 'Percentage of Sales Value'),
]
OVERRIDE_METHODS = [
    ('inherit', 'Use Next Level'),
    ('none', 'No Provision'),
    ('fixed', 'Fixed Amount per Unit'),
    ('percentage', 'Percentage of Sales Value'),
]
EXPENSE_ACCOUNT_TYPES = ('expense', 'expense_direct_cost')
PROVISION_ACCOUNT_TYPES = ('liability_current', 'liability_non_current')
OVERRIDE_FIELDS = ('warranty_provision_method', 'warranty_provision_rate',
                   'warranty_provision_amount')
COMPANY_CONFIG_FIELDS = ('warranty_provision_enabled', 'warranty_provision_method',
                         'warranty_provision_rate', 'warranty_provision_amount',
                         'warranty_accounting_journal_id', 'warranty_expense_account_id',
                         'warranty_provision_account_id')
METHOD_HELP = ("Empty or Use Next Level: the next level decides, in the order product, category, "
               "warranty policy, company. No Provision stops there.")


def warranty_accounting_editor(env):
    """Both Settings and Accounting Manager rights. The real user counts, also in sudo; only the
    system itself (module data) is exempt."""
    return env.uid == SUPERUSER_ID or (env.user.has_group('base.group_system')
                                       and env.user.has_group('account.group_account_manager'))


def _check_provision_values(record):
    method = record.warranty_provision_method
    if method == 'percentage' and not 0 < record.warranty_provision_rate <= 100:
        raise ValidationError(_("%s: the provision percentage must be above 0 and at most 100.",
                                record.display_name))
    if method == 'fixed' and record.warranty_provision_amount <= 0:
        raise ValidationError(_("%s: the fixed provision amount per unit must be above 0.",
                                record.display_name))


class WarrantyAccountingConfigMixin(models.AbstractModel):
    """Who may change warranty accounting configuration, enforced on every create and write."""
    _name = 'warranty.accounting.config.mixin'
    _description = 'Warranty Accounting Configuration Access'
    _warranty_accounting_fields = ()

    warranty_accounting_can_edit = fields.Boolean(compute='_compute_warranty_accounting_can_edit')

    @api.depends_context('uid')
    def _compute_warranty_accounting_can_edit(self):
        self.warranty_accounting_can_edit = warranty_accounting_editor(self.env)

    def _warranty_accounting_changed(self, vals):
        """A form can send the unchanged values: only a real change needs the rights."""
        names = [name for name in self._warranty_accounting_fields if name in vals]

        def normal(value):
            value = value.id if isinstance(value, models.BaseModel) else value
            return False if value == 'inherit' else (value or False)

        return any(normal(record[name]) != normal(vals[name])
                   for record in self.sudo() for name in names)

    def _warranty_accounting_check(self):
        if not warranty_accounting_editor(self.env):
            raise AccessError(_("Only users with both Settings and Accounting Manager rights can "
                                "change warranty accounting configuration."))

    @api.model_create_multi
    def create(self, vals_list):
        empty = self.browse()
        for vals in vals_list:
            if any(vals.get(name) not in (None, False, 0, 0.0, '', 'inherit')
                   for name in empty._warranty_accounting_fields):
                self._warranty_accounting_check()
        return super().create(vals_list)

    def write(self, vals):
        if self._warranty_accounting_changed(vals):
            self._warranty_accounting_check()
        return super().write(vals)


class ResCompany(models.Model):
    _name = 'res.company'
    _inherit = ['res.company', 'warranty.accounting.config.mixin']
    _warranty_accounting_fields = COMPANY_CONFIG_FIELDS

    warranty_provision_enabled = fields.Boolean(
        string='Warranty Provision Accounting', tracking=True, groups=ACCOUNTING_READ_GROUPS,
        help="Off by default. It needs the journal and the Warranty Expense and Warranty Provision "
             "accounts. When on, posting a warranty sale invoice creates a draft provision entry, "
             "which Accounting reviews and posts.")
    warranty_provision_method = fields.Selection(
        COMPANY_METHODS, string='Default Provision Method', default='disabled', tracking=True,
        groups=ACCOUNTING_READ_GROUPS,
        help="Used when no product, category or warranty policy override applies. Disabled: no "
             "provision at company level.")
    warranty_provision_rate = fields.Float(
        string='Default Provision Percentage', digits=(16, 4), tracking=True,
        groups=ACCOUNTING_READ_GROUPS,
        help="Percentage of the untaxed sales value of the invoice line, in company currency.")
    warranty_provision_amount = fields.Monetary(
        string='Default Provision Amount per Unit', currency_field='currency_id', tracking=True,
        groups=ACCOUNTING_READ_GROUPS, help="Provision = quantity x this amount.")
    warranty_accounting_journal_id = fields.Many2one(
        'account.journal', string='Warranty Accounting Journal', ondelete='restrict',
        tracking=True, groups=ACCOUNTING_READ_GROUPS,
        help="An existing Miscellaneous journal of this company.")
    warranty_expense_account_id = fields.Many2one(
        'account.account', string='Warranty Expense Account', ondelete='restrict', tracking=True,
        groups=ACCOUNTING_READ_GROUPS)
    warranty_provision_account_id = fields.Many2one(
        'account.account', string='Warranty Provision / Reserve Account', ondelete='restrict',
        tracking=True, groups=ACCOUNTING_READ_GROUPS,
        help="One account per company.")

    @api.constrains(*COMPANY_CONFIG_FIELDS)
    def _check_warranty_accounting_config(self):
        for company in self.sudo():
            _check_provision_values(company)
            journal = company.warranty_accounting_journal_id
            if journal and (journal.company_id != company or journal.type != 'general'):
                raise ValidationError(_("The Warranty Accounting Journal must be a Miscellaneous "
                                        "journal of %s.", company.name))
            for account, types, label in (
                    (company.warranty_expense_account_id, EXPENSE_ACCOUNT_TYPES,
                     _("Warranty Expense")),
                    (company.warranty_provision_account_id, PROVISION_ACCOUNT_TYPES,
                     _("Warranty Provision / Reserve"))):
                if not account:
                    continue
                if company not in account.company_ids:
                    raise ValidationError(_("The %(label)s account %(account)s does not belong to "
                                            "%(company)s.", label=label,
                                            account=account.display_name, company=company.name))
                if account.deprecated:
                    raise ValidationError(_("The %(label)s account %(account)s is deprecated.",
                                            label=label, account=account.display_name))
                if account.account_type not in types:
                    raise ValidationError(_("The %(label)s account %(account)s has the wrong "
                                            "account type.", label=label,
                                            account=account.display_name))
            if company.warranty_expense_account_id and company.warranty_expense_account_id \
                    == company.warranty_provision_account_id:
                raise ValidationError(_("The Warranty Expense and Warranty Provision accounts "
                                        "must be different."))
            if company.warranty_provision_enabled:
                missing = company._warranty_accounting_missing()
                if missing:
                    raise ValidationError(_("Warranty provision accounting cannot be enabled for "
                                            "%(company)s. Missing: %(missing)s.",
                                            company=company.name, missing=', '.join(missing)))

    def _warranty_accounting_missing(self):
        """What provision accounting cannot run without."""
        self.ensure_one()
        company = self.sudo()
        return [label for value, label in (
            (company.warranty_accounting_journal_id, _("Warranty Accounting Journal")),
            (company.warranty_expense_account_id, _("Warranty Expense Account")),
            (company.warranty_provision_account_id, _("Warranty Provision / Reserve Account")),
        ) if not value]

    def _warranty_provision_rule(self, product=None, category=None, policy=None):
        """D17: the first level with a rule wins, product, category (nearest first), warranty
        policy, company. Returns {method: none / fixed / percentage, rate, amount, level, source,
        enabled}. Read only. A later entry stores this result, so changes never alter it."""
        self.ensure_one()
        company = self.sudo().with_company(self)
        levels = []
        if product:
            template = product.product_tmpl_id if product._name == 'product.product' else product
            template = template.sudo().with_company(self)
            levels.append(('product', template))
            category = category or template.categ_id
            policy = policy or template.warranty_applied_policy_id
        category = category.sudo().with_company(self) if category else self.env['product.category']
        policy = policy or category.warranty_policy_id
        while category:
            levels.append(('category', category))
            category = category.parent_id
        if policy and policy.sudo()._is_applicable_for_company(company):
            levels.append(('policy', policy.sudo()))
        for level, record in levels:
            method = record.warranty_provision_method
            if method and method != 'inherit':
                return {'method': method, 'rate': record.warranty_provision_rate,
                        'amount': record.warranty_provision_amount, 'level': level,
                        'source': record.display_name,
                        'enabled': company.warranty_provision_enabled}
        method = company.warranty_provision_method
        return {'method': 'none' if not method or method == 'disabled' else method,
                'rate': company.warranty_provision_rate,
                'amount': company.warranty_provision_amount, 'level': 'company',
                'source': company.name, 'enabled': company.warranty_provision_enabled}

    def _warranty_provision_value(self, product, quantity, untaxed_sales_value, policy=None):
        """Provision of one sales line: quantity x fixed amount, or a percentage of its untaxed
        value in company currency (D1). 0 while provision accounting is off. It posts nothing."""
        self.ensure_one()
        rule = self._warranty_provision_rule(product=product, policy=policy)
        if not rule['enabled'] or rule['method'] == 'none':
            return 0.0
        value = quantity * rule['amount'] if rule['method'] == 'fixed' \
            else untaxed_sales_value * rule['rate'] / 100.0
        return self.currency_id.round(value)

    def _warranty_provision_rule_label(self, rule):
        self.ensure_one()
        if rule['method'] == 'none':
            text = _("No provision")
        elif rule['method'] == 'fixed':
            text = _("%s per unit", format_amount(self.env, rule['amount'], self.currency_id))
        else:
            text = _("%s%% of sales value", round(rule['rate'], 4))
        levels = {'product': _("this product"), 'category': _("category %s", rule['source']),
                  'policy': _("policy %s", rule['source']), 'company': _("company default")}
        label = _("%(text)s (from %(level)s)", text=text, level=levels[rule['level']])
        if not rule['enabled']:
            label = _("%s. Provision accounting is off for this company.", label)
        return label


class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = ['product.template', 'warranty.accounting.config.mixin']
    _warranty_accounting_fields = OVERRIDE_FIELDS

    warranty_provision_method = fields.Selection(
        OVERRIDE_METHODS, string='Provision Method', company_dependent=True, copy=False,
        tracking=True, groups=ACCOUNTING_READ_GROUPS, help=METHOD_HELP)
    warranty_provision_rate = fields.Float(
        string='Provision Percentage', digits=(16, 4), company_dependent=True, copy=False,
        tracking=True, groups=ACCOUNTING_READ_GROUPS)
    warranty_provision_amount = fields.Float(
        string='Provision Amount per Unit', digits=(16, 2), company_dependent=True, copy=False,
        tracking=True, groups=ACCOUNTING_READ_GROUPS)
    warranty_provision_effective = fields.Char(
        string='Effective Provision', compute='_compute_warranty_provision_effective',
        compute_sudo=True, groups=ACCOUNTING_READ_GROUPS)

    @api.depends_context('company')
    @api.depends('warranty_provision_method', 'warranty_provision_rate',
                 'warranty_provision_amount', 'categ_id')
    def _compute_warranty_provision_effective(self):
        company = self.env.company
        for template in self:
            template.warranty_provision_effective = company._warranty_provision_rule_label(
                company._warranty_provision_rule(product=template))

    @api.constrains(*OVERRIDE_FIELDS)
    def _check_warranty_provision_override(self):
        for template in self.sudo():
            _check_provision_values(template)


class ProductCategory(models.Model):
    _name = 'product.category'
    _inherit = ['product.category', 'warranty.accounting.config.mixin']
    _warranty_accounting_fields = OVERRIDE_FIELDS

    warranty_provision_method = fields.Selection(
        OVERRIDE_METHODS, string='Provision Method', company_dependent=True, copy=False,
        tracking=True, groups=ACCOUNTING_READ_GROUPS, help=METHOD_HELP)
    warranty_provision_rate = fields.Float(
        string='Provision Percentage', digits=(16, 4), company_dependent=True, copy=False,
        tracking=True, groups=ACCOUNTING_READ_GROUPS)
    warranty_provision_amount = fields.Float(
        string='Provision Amount per Unit', digits=(16, 2), company_dependent=True, copy=False,
        tracking=True, groups=ACCOUNTING_READ_GROUPS)
    warranty_provision_effective = fields.Char(
        string='Effective Provision', compute='_compute_warranty_provision_effective',
        compute_sudo=True, groups=ACCOUNTING_READ_GROUPS)

    @api.depends_context('company')
    @api.depends('warranty_provision_method', 'warranty_provision_rate',
                 'warranty_provision_amount', 'parent_id', 'warranty_policy_id')
    def _compute_warranty_provision_effective(self):
        company = self.env.company
        for category in self:
            category.warranty_provision_effective = company._warranty_provision_rule_label(
                company._warranty_provision_rule(category=category))

    @api.constrains(*OVERRIDE_FIELDS)
    def _check_warranty_provision_override(self):
        for category in self.sudo():
            _check_provision_values(category)


class WarrantyPolicy(models.Model):
    _name = 'warranty.policy'
    _inherit = ['warranty.policy', 'warranty.accounting.config.mixin']
    _warranty_accounting_fields = OVERRIDE_FIELDS

    warranty_provision_method = fields.Selection(
        OVERRIDE_METHODS, string='Provision Method', copy=False, groups=ACCOUNTING_READ_GROUPS,
        help=METHOD_HELP)
    warranty_provision_rate = fields.Float(
        string='Provision Percentage', digits=(16, 4), copy=False, groups=ACCOUNTING_READ_GROUPS)
    warranty_provision_amount = fields.Float(
        string='Provision Amount per Unit', digits=(16, 2), copy=False,
        groups=ACCOUNTING_READ_GROUPS)

    @api.constrains(*OVERRIDE_FIELDS)
    def _check_warranty_provision_override(self):
        for policy in self.sudo():
            _check_provision_values(policy)

    def write(self, vals):
        """A policy has no chatter: the history is kept on its company."""
        before = {policy: {name: policy.sudo()[name] for name in OVERRIDE_FIELDS if name in vals}
                  for policy in self}
        result = super().write(vals)
        for policy, values in before.items():
            changes = [_("%(field)s: %(old)s to %(new)s",
                         field=policy._fields[name].get_description(self.env)['string'],
                         old=old or '-', new=policy.sudo()[name] or '-')
                       for name, old in values.items() if policy.sudo()[name] != old]
            if changes:
                (policy.sudo().company_id or self.env.company).sudo()._message_log(body=_(
                    "Warranty policy %(policy)s, provision override changed by %(user)s. "
                    "%(changes)s", policy=policy.display_name, user=self.env.user.name,
                    changes='; '.join(changes)))
        return result


class HelpdeskTeam(models.Model):
    _name = 'helpdesk.team'
    _inherit = ['helpdesk.team', 'warranty.accounting.config.mixin']
    _warranty_accounting_fields = ('warranty_inspection_deduction_product_id',)

    warranty_inspection_deduction_product_id = fields.Many2one(
        'product.product', string='Inspection Deduction Product', domain=[('sale_ok', '=', True)],
        check_company=True, tracking=True,
        help="Deducts the inspection fee from the final repair bill when no inspection invoice is "
             "posted (SRS 7, 9.7). Its income account is the deduction account.")


class ResConfigSettings(models.TransientModel):
    """Plain fields, saved in one write: the checks need the whole configuration at once, and
    related fields would be written one at a time."""
    _inherit = 'res.config.settings'

    warranty_accounting_can_edit = fields.Boolean(compute='_compute_warranty_accounting_settings')
    warranty_accounting_issues = fields.Char(string='Warranty Accounting Readiness',
                                             compute='_compute_warranty_accounting_settings')
    warranty_provision_enabled = fields.Boolean(
        string='Warranty Provision Accounting',
        help="Off by default. It needs the journal and the Warranty Expense and Warranty Provision "
             "accounts. When on, posting a warranty sale invoice creates a draft provision entry, "
             "which Accounting reviews and posts.")
    warranty_provision_method = fields.Selection(COMPANY_METHODS, string='Default Method')
    warranty_provision_rate = fields.Float(string='Default Percentage', digits=(16, 4))
    warranty_provision_amount = fields.Monetary(string='Default Amount per Unit',
                                                currency_field='company_currency_id')
    warranty_accounting_journal_id = fields.Many2one(
        'account.journal', string='Warranty Journal',
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]")
    warranty_expense_account_id = fields.Many2one(
        'account.account', string='Warranty Expense',
        domain="[('company_ids', 'in', company_id), ('deprecated', '=', False), "
               "('account_type', 'in', %s)]" % (EXPENSE_ACCOUNT_TYPES,))
    warranty_provision_account_id = fields.Many2one(
        'account.account', string='Provision / Reserve',
        domain="[('company_ids', 'in', company_id), ('deprecated', '=', False), "
               "('account_type', 'in', %s)]" % (PROVISION_ACCOUNT_TYPES,))

    @api.depends('warranty_accounting_journal_id', 'warranty_expense_account_id',
                 'warranty_provision_account_id', 'warranty_claim_recovery_account_id')
    @api.depends_context('uid')
    def _compute_warranty_accounting_settings(self):
        for settings in self:
            missing = [label for value, label in (
                (settings.warranty_accounting_journal_id, _("Warranty Accounting Journal")),
                (settings.warranty_expense_account_id, _("Warranty Expense Account")),
                (settings.warranty_provision_account_id, _("Warranty Provision / Reserve Account")),
                (settings.warranty_claim_recovery_account_id, _("Vendor Recovery Account")),
            ) if not value]
            settings.warranty_accounting_can_edit = warranty_accounting_editor(self.env)
            settings.warranty_accounting_issues = _("Not ready: %s is missing.", ', '.join(missing)) \
                if missing else _("Ready.")

    @api.model
    def get_values(self):
        values = super().get_values()
        company = self.env.company.sudo()
        for name in COMPANY_CONFIG_FIELDS:
            value = company[name]
            values[name] = value.id if isinstance(value, models.BaseModel) else value
        return values

    def set_values(self):
        super().set_values()
        for settings in self:
            company = settings.company_id.sudo()
            vals = {}
            for name in COMPANY_CONFIG_FIELDS:
                value = settings[name]
                vals[name] = value.id if isinstance(value, models.BaseModel) else value
            if company._warranty_accounting_changed(vals):
                company.write(vals)
