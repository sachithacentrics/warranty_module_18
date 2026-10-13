from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # res.config.settings reserves the 'default_' prefix for ir.default values,
    # so the company fields are exposed here under a 'warranty_' prefix.
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
