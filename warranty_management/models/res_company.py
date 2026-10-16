import logging

from odoo import _, api, fields, models
from odoo.addons.base.models.res_partner import _tz_get
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


def is_valid_service_alert_user(user, company):
    """A service alert responsible user must be an active internal user allowed in the
    company of the warranty card (activities are only assigned to users who can open them)."""
    return bool(user and user.active and not user.share and company in user.company_ids)


def get_valid_service_alert_users(users, company):
    """The users of `users` that are valid service alert responsible users for `company`."""
    return users.filtered(lambda user: is_valid_service_alert_user(user, company))


class ResCompany(models.Model):
    _inherit = 'res.company'

    warranty_scope_mode = fields.Selection([
        ('warranty_only', 'Warranty Only'),
        ('free_services', 'Free Services'),
        ('amc', 'AMC'),
        ('amc_free_services', 'AMC with Free Services'),
    ], string='Warranty Scope Mode', default='warranty_only')
    default_warranty_policy_id = fields.Many2one('warranty.policy', string='Default Warranty Policy')
    default_card_grouping_mode = fields.Selection([
        ('per_so', 'Per Sales Order'),
        ('per_product', 'Per Product'),
        ('per_delivery', 'Per Delivery'),
        ('per_unit', 'Per Unit/Serial'),
    ], string='Default Card Grouping Mode')
    warranty_auto_create_services = fields.Boolean(string='Auto-create Services')
    warranty_draft_job_from_service = fields.Boolean(string='Draft Job from Service')
    default_warranty_basis = fields.Selection([
        ('period', 'Period'),
        ('usage', 'Usage'),
    ], string='Default Warranty Basis')
    default_start_criterion = fields.Selection([
        ('installation', 'Installation/Commissioning'),
        ('delivery', 'Delivery'),
        ('invoice', 'Invoice'),
        ('custom', 'Custom Date Range'),
    ], string='Default Start Criterion')
    default_warranty_duration = fields.Integer(string='Default Warranty Duration')
    default_warranty_duration_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Default Duration Unit')
    # Company free service defaults: used at the company fallback level (count) and when the
    # card's policy has no schedule method / free service period (see warranty.card).
    default_free_service_count = fields.Integer(string='Default Free Service Count')
    default_free_service_period = fields.Integer(string='Default Free Service Period')
    default_free_service_period_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Default Free Service Period Unit')
    default_schedule_method = fields.Selection([
        ('equal_interval', 'Equal Interval'),
        ('manual', 'Manual Schedule'),
        ('calendar_month', 'Calendar Month'),
    ], string='Default Schedule Method')
    warranty_service_alert_user_ids = fields.Many2many(
        'res.users', 'warranty_company_alert_user_rel', 'company_id', 'user_id',
        string='Service Alert Responsible Users', domain=[('share', '=', False)],
        context={'active_test': False},
        help="Fallback users for free service due alerts and expiry reminders when the "
             "warranty card has no valid responsible user of its own. Each user receives "
             "their own activity.")
    warranty_timezone = fields.Selection(
        _tz_get, string='Warranty Timezone',
        help="Timezone used to evaluate free service due and expiry dates. When empty, the "
             "timezone of the company contact is used, then UTC.")

    @api.constrains('default_free_service_count', 'default_free_service_period')
    def _check_default_free_service_values(self):
        for company in self:
            if company.default_free_service_count < 0 or company.default_free_service_period < 0:
                raise ValidationError(_(
                    "The default free service count and period of %s must not be negative.",
                    company.name))

    @api.constrains('warranty_service_alert_user_ids')
    def _check_warranty_service_alert_users(self):
        for company in self:
            users = company.warranty_service_alert_user_ids
            invalid = users - get_valid_service_alert_users(users, company)
            if invalid:
                raise ValidationError(_(
                    "The Service Alert Responsible Users of %(company)s must be active internal "
                    "users allowed in that company: %(users)s",
                    company=company.name, users=', '.join(invalid.mapped('name'))))

    def _warranty_today(self, log_missing_timezone=False):
        """Today's date in the warranty timezone of the company:
        Warranty Timezone > company contact timezone > UTC."""
        self.ensure_one()
        tz_name = self.warranty_timezone or self.partner_id.tz
        if not tz_name:
            if log_missing_timezone:
                _logger.warning(
                    "Warranty service monitoring: no Warranty Timezone or company timezone "
                    "configured for company %s (id %s); UTC is used.", self.name, self.id)
            tz_name = 'UTC'
        return fields.Date.context_today(self.with_context(tz=tz_name))
