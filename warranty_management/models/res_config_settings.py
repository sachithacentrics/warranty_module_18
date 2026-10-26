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
    # Read-only display of the selected Default Warranty Policy (related to the form's policy
    # field so the values refresh when the policy changes; nothing stored or copied).
    warranty_default_policy_basis = fields.Selection(
        related='warranty_default_policy_id.warranty_basis', string='Warranty Basis',
        readonly=True)
    warranty_default_policy_duration = fields.Integer(
        related='warranty_default_policy_id.warranty_duration', string='Warranty Duration',
        readonly=True)
    warranty_default_policy_duration_unit = fields.Selection(
        related='warranty_default_policy_id.warranty_duration_unit',
        string='Warranty Duration Unit', readonly=True)
    warranty_default_policy_start_criterion = fields.Selection(
        related='warranty_default_policy_id.start_date_basis', string='Start Criterion',
        readonly=True)
    warranty_default_policy_usage_limit = fields.Float(
        related='warranty_default_policy_id.usage_limit', string='Usage Limit', readonly=True)
    warranty_default_policy_usage_unit = fields.Selection(
        related='warranty_default_policy_id.usage_unit', string='Usage Unit', readonly=True)
    warranty_default_policy_free_service_count = fields.Integer(
        related='warranty_default_policy_id.free_service_count', string='Free Service Count',
        readonly=True)
    warranty_default_policy_free_service_period = fields.Integer(
        related='warranty_default_policy_id.free_service_period', string='Free Service Period',
        readonly=True)
    warranty_default_policy_free_service_period_unit = fields.Selection(
        related='warranty_default_policy_id.free_service_period_unit',
        string='Free Service Period Unit', readonly=True)
    warranty_default_policy_free_service_frequency = fields.Integer(
        related='warranty_default_policy_id.free_service_frequency',
        string='Free Service Frequency', readonly=True)
    warranty_default_policy_free_service_frequency_unit = fields.Selection(
        related='warranty_default_policy_id.free_service_frequency_unit',
        string='Free Service Frequency Unit', readonly=True)
    warranty_default_policy_schedule_method = fields.Selection(
        related='warranty_default_policy_id.schedule_method', string='Schedule Method',
        readonly=True)
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
    warranty_download_approval_required = fields.Boolean(
        related='company_id.warranty_download_approval_required',
        string='Require PDF Download Approval', readonly=False)
    warranty_free_download_count = fields.Integer(
        related='company_id.warranty_free_download_count', string='Free Download Count',
        readonly=False)
    warranty_download_approver_ids = fields.Many2many(
        related='company_id.warranty_download_approver_ids',
        string='Download Approval Responsible Users', readonly=False)

    def set_values(self):
        for settings in self:
            # With a Default Warranty Policy the policy provides the duration (P4), so the
            # company default duration is only required without one.
            if settings.warranty_scope_mode and not settings.warranty_default_policy_id and (
                    settings.warranty_default_duration <= 0
                    or not settings.warranty_default_duration_unit):
                raise ValidationError(_(
                    "Default Warranty Duration and unit are required when a Warranty Scope Mode "
                    "is set and no Default Warranty Policy is selected."))
        return super().set_values()
