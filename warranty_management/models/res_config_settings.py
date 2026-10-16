from odoo import _, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'


    warranty_scope_mode = fields.Selection(
        related='company_id.warranty_scope_mode', string='Warranty Scope Mode',
        readonly=False)
    warranty_default_policy_id = fields.Many2one(
        related='company_id.default_warranty_policy_id', string='Default Warranty Policy',
        readonly=False)
    warranty_default_card_grouping_mode = fields.Selection(
        related='company_id.default_card_grouping_mode', string='Default Card Grouping Mode',
        readonly=False)
    warranty_auto_create_services = fields.Boolean(
        related='company_id.warranty_auto_create_services', string='Auto-create Services',
        readonly=False)
    warranty_draft_job_from_service = fields.Boolean(
        related='company_id.warranty_draft_job_from_service', string='Draft Job from Service',
        readonly=False)
    warranty_default_basis = fields.Selection(
        related='company_id.default_warranty_basis', string='Default Warranty Basis',
        readonly=False)
    warranty_default_start_criterion = fields.Selection(
        related='company_id.default_start_criterion', string='Default Start Criterion',
        readonly=False)
    warranty_default_duration = fields.Integer(
        related='company_id.default_warranty_duration', string='Default Warranty Duration',
        readonly=False)
    warranty_default_duration_unit = fields.Selection(
        related='company_id.default_warranty_duration_unit', string='Default Duration Unit',
        readonly=False)
    warranty_default_free_service_count = fields.Integer(
        related='company_id.default_free_service_count', string='Default Free Service Count',
        readonly=False)
    warranty_default_free_service_period = fields.Integer(
        related='company_id.default_free_service_period', string='Default Free Service Period',
        readonly=False)
    warranty_default_free_service_period_unit = fields.Selection(
        related='company_id.default_free_service_period_unit',
        string='Default Free Service Period Unit', readonly=False)
    warranty_default_schedule_method = fields.Selection(
        related='company_id.default_schedule_method', string='Default Schedule Method',
        readonly=False)
    warranty_service_alert_user_ids = fields.Many2many(
        related='company_id.warranty_service_alert_user_ids',
        string='Service Alert Responsible Users', readonly=False)
    warranty_timezone = fields.Selection(
        related='company_id.warranty_timezone', string='Warranty Timezone', readonly=False)

    def set_values(self):
        for settings in self:
            if settings.warranty_scope_mode and (
                    settings.warranty_default_duration <= 0
                    or not settings.warranty_default_duration_unit):
                raise ValidationError(_(
                    "Default Warranty Duration and unit are required when a Warranty Scope Mode "
                    "is set."))
        return super().set_values()
