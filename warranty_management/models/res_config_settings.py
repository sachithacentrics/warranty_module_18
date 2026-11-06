from odoo import _, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_default_policy_id = fields.Many2one(
        related='company_id.default_warranty_policy_id', string='Default Warranty Policy',
        readonly=False,
        help="The warranty policy used when the pricelist, the product and the product "
             "category have no warranty policy. Its values are shown here read-only; edit "
             "the policy to change them.")
    warranty_default_card_grouping_mode = fields.Selection(
        related='company_id.default_card_grouping_mode', string='Default Card Grouping Mode',
        readonly=False)
    warranty_auto_create_services = fields.Boolean(
        related='company_id.warranty_auto_create_services', string='Auto-create Services',
        readonly=False,
        help="If enabled, free service entries are created automatically when a warranty "
             "card is confirmed. If disabled, they are added manually. Used only for cards "
             "without a warranty policy whose product and category do not enable it; a "
             "warranty policy's own setting always applies instead.")
    warranty_draft_job_from_service = fields.Boolean(
        related='company_id.warranty_draft_job_from_service', string='Draft Job from Service',
        readonly=False)
    warranty_default_basis = fields.Selection(
        related='company_id.default_warranty_basis', string='Default Warranty Basis',
        readonly=False,
        help="How the warranty is measured: by time (Period) or by use, such as running "
             "hours (Usage). Used when the warranty policy does not set it, or when no "
             "policy applies.")
    warranty_default_start_criterion = fields.Selection(
        related='company_id.default_start_criterion', string='Default Start Criterion',
        readonly=False,
        help="The event that starts the warranty: installation, delivery or invoice. Used "
             "when the warranty policy does not set it, or when no policy applies.")
    warranty_default_duration = fields.Integer(
        related='company_id.default_warranty_duration', string='Default Warranty Duration',
        readonly=False,
        help="How long the warranty lasts when no warranty policy applies and the product "
             "and its category have no warranty period. Required when no Default Warranty "
             "Policy is selected.")
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
        readonly=False,
        help="The number of free services given when no warranty policy applies and the "
             "product and its category have no free service count. 0 means no free services.")
    warranty_default_free_service_period = fields.Integer(
        related='company_id.default_free_service_period', string='Default Free Service Period',
        readonly=False,
        help="The period over which the free services are spread, used when the warranty "
             "policy does not set one.")
    warranty_default_free_service_period_unit = fields.Selection(
        related='company_id.default_free_service_period_unit',
        string='Default Free Service Period Unit', readonly=False)
    warranty_default_schedule_method = fields.Selection(
        related='company_id.default_schedule_method', string='Default Schedule Method',
        readonly=False,
        help="How free service due dates are calculated (equal intervals, or entered "
             "manually). Used when the warranty policy, the product and its category do not "
             "set a method.")
    warranty_service_alert_user_ids = fields.Many2many(
        related='company_id.warranty_service_alert_user_ids',
        string='Service Alert Responsible Users', readonly=False,
        help="Users who receive the free service due alerts and expiry reminders when the "
             "warranty card has no responsible users of its own. Each user gets their own "
             "task.")
    warranty_timezone = fields.Selection(
        related='company_id.warranty_timezone', string='Warranty Timezone', readonly=False,
        help="The timezone used to decide when free services are due or expired and to turn "
             "delivery, invoice posting and installation times into warranty start dates. If "
             "empty, the company's timezone is used, otherwise UTC.")
    warranty_download_approval_required = fields.Boolean(
        related='company_id.warranty_download_approval_required',
        string='Require PDF Download Approval', readonly=False,
        help="If enabled, after the free downloads each warranty card PDF download needs an "
             "approved request. If disabled, the PDF can be downloaded at any time.")
    warranty_free_download_count = fields.Integer(
        related='company_id.warranty_free_download_count', string='Free Download Count',
        readonly=False,
        help="How many times each warranty card PDF can be downloaded without approval (at "
             "least 1). The PDF created when the card is confirmed is not counted. Used only "
             "when download approval is required.")
    warranty_card_hotline = fields.Char(
        related='company_id.warranty_card_hotline', readonly=False,
        help="The hot line printed on the warranty card. If empty, the company phone is used.")
    warranty_card_return_note = fields.Text(
        related='company_id.warranty_card_return_note', readonly=False,
        help="Note printed on the Registration Copy, for example how and when to return it.")
    warranty_card_valid_note = fields.Text(
        related='company_id.warranty_card_valid_note', readonly=False,
        help="Validity note printed in red on the Registration Copy.")
    warranty_card_terms = fields.Html(
        related='company_id.warranty_card_terms', readonly=False,
        help="The warranty terms and conditions printed on the back of the warranty card.")
    warranty_exception_approver_ids = fields.Many2many(
        related='company_id.warranty_exception_approver_ids',
        string='Warranty Exception Approvers', readonly=False,
        help="Users who approve or reject warranty change requests: suspension, cancellation, "
             "correction, relocation, transfer and extension. A user never decides their own "
             "request.")
    warranty_exception_evidence_required = fields.Boolean(
        related='company_id.warranty_exception_evidence_required', readonly=False,
        help="A warranty suspension request needs an attached document or photo.")
    warranty_relocation_allowed = fields.Boolean(
        related='company_id.warranty_relocation_allowed', readonly=False,
        help="Warranty units can be moved to another site of the same customer, with approval.")
    warranty_transfer_allowed = fields.Boolean(
        related='company_id.warranty_transfer_allowed', readonly=False,
        help="A warranty card can be transferred to another customer, with approval.")
    warranty_extension_max_days = fields.Integer(
        related='company_id.warranty_extension_max_days', readonly=False,
        help="The longest controlled warranty extension in days. 0 means no maximum.")
    warranty_download_approver_ids = fields.Many2many(
        related='company_id.warranty_download_approver_ids',
        string='Download Approval Responsible Users', readonly=False,
        help="Users who approve or reject the warranty card PDF download requests. A user "
             "never approves their own request.")

    def set_values(self):
        for settings in self:
            # With a Default Warranty Policy the policy provides the duration (P4), so the
            # company default duration is only required without one.
            if not settings.warranty_default_policy_id and (
                    settings.warranty_default_duration <= 0
                    or not settings.warranty_default_duration_unit):
                raise ValidationError(_(
                    "Default Warranty Duration and unit are required when no Default Warranty "
                    "Policy is selected."))
        return super().set_values()
