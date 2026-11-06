from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    warranty_policy_ids = fields.Many2many(
        'warranty.policy', 'warranty_policy_pricelist_rel', 'pricelist_id', 'policy_id',
        string='Customer Type Warranty Policies', readonly=True, copy=False)

    warranty_applicable = fields.Boolean(
        string='Warranty Applicable',
        help="Use the Warranty Policy of this pricelist for the warranty-applicable products of "
             "its Sales Orders (highest priority). It does not make products Warranty "
             "Applicable.")
    warranty_policy_id = fields.Many2one(
        'warranty.policy', string='Warranty Policy',
        domain="[('company_id', '=', company_id)] if company_id else [('company_id', '=', False)]",
        help="Policy of the pricelist company or a shared policy (a shared pricelist only uses "
             "shared policies).")

    # Display only: values of the selected policy (not copied to the pricelist).
    warranty_policy_duration = fields.Integer(
        related='warranty_policy_id.warranty_duration', string='Warranty Duration')
    warranty_policy_duration_unit = fields.Selection(
        related='warranty_policy_id.warranty_duration_unit', string='Warranty Duration Unit')
    warranty_policy_basis = fields.Selection(
        related='warranty_policy_id.warranty_basis', string='Warranty Basis')
    warranty_policy_start_criterion = fields.Selection(
        related='warranty_policy_id.start_date_basis', string='Start Criterion')
    warranty_policy_usage_limit = fields.Float(
        related='warranty_policy_id.usage_limit', string='Usage Limit')
    warranty_policy_usage_unit = fields.Selection(
        related='warranty_policy_id.usage_unit', string='Usage Unit')
    warranty_policy_free_service_count = fields.Integer(
        related='warranty_policy_id.free_service_count', string='Free Service Count')
    warranty_policy_frequency = fields.Integer(
        related='warranty_policy_id.free_service_frequency', string='Free Service Frequency')
    warranty_policy_frequency_unit = fields.Selection(
        related='warranty_policy_id.free_service_frequency_unit',
        string='Free Service Frequency Unit')
    warranty_policy_service_period = fields.Integer(
        related='warranty_policy_id.free_service_period', string='Free Service Period')
    warranty_policy_service_period_unit = fields.Selection(
        related='warranty_policy_id.free_service_period_unit', string='Free Service Period Unit')
    warranty_policy_schedule_method = fields.Selection(
        related='warranty_policy_id.schedule_method', string='Schedule Method')
    warranty_policy_auto_create = fields.Boolean(
        related='warranty_policy_id.auto_create_services', string='Auto-create Services')
    warranty_policy_due_alert_days = fields.Integer(
        related='warranty_policy_id.service_due_alert_days', string='Service Due Alert Days')
    warranty_policy_alert_user_ids = fields.Many2many(
        related='warranty_policy_id.service_alert_user_ids',
        string='Service Alert Responsible Users')
    warranty_policy_usage_alert_percentage = fields.Float(
        related='warranty_policy_id.usage_alert_percentage', string='Usage Alert %')
    warranty_policy_auto_expire = fields.Boolean(
        related='warranty_policy_id.auto_expire_services', string='Auto-expire')
    warranty_policy_grace_period_days = fields.Integer(
        related='warranty_policy_id.grace_period_days', string='Grace Period (Days)')
    warranty_policy_expiry_reminder_days = fields.Integer(
        related='warranty_policy_id.expiry_reminder_days', string='Expiry Reminder Days')

    @api.constrains('warranty_applicable', 'warranty_policy_id', 'company_id')
    def _check_warranty_policy(self):
        """ Warranty Policy is required when Warranty Applicable is ticked;
        a company pricelist uses a policy of its company or a shared one, a shared pricelist
        only a shared policy."""
        for pricelist in self:
            policy = pricelist.warranty_policy_id
            if pricelist.warranty_applicable and not policy:
                raise ValidationError(_(
                    "Select a Warranty Policy on pricelist \"%s\" (Warranty Applicable is "
                    "enabled).", pricelist.display_name))
            if policy.company_id and policy.company_id != pricelist.company_id:
                raise ValidationError(_(
                    "The warranty policy \"%(policy)s\" of company %(policy_company)s cannot be "
                    "used on pricelist \"%(pricelist)s\" (%(company)s): select a policy of the "
                    "pricelist company or a shared policy.",
                    policy=policy.name, policy_company=policy.company_id.name,
                    pricelist=pricelist.display_name,
                    company=pricelist.company_id.name or _("shared pricelist")))
