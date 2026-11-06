from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    amc_enabled = fields.Boolean(related='company_id.amc_enabled', readonly=False)
    amc_default_plan_id = fields.Many2one(
        related='company_id.amc_default_plan_id', readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    amc_default_pricelist_id = fields.Many2one(
        related='company_id.amc_default_pricelist_id', readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    amc_fallback_currency_id = fields.Many2one(
        'res.currency', string='Fallback AMC Currency', compute='_compute_amc_fallback_currency',
        help="Currency used when the customer has no applicable pricelist: the Default "
             "Pricelist's currency, else the company currency.")
    amc_default_billing_plan_id = fields.Many2one(
        related='company_id.amc_default_billing_plan_id', readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    amc_default_start_rule = fields.Selection(related='company_id.amc_default_start_rule',
                                              readonly=False)
    amc_default_renewal_rule = fields.Selection(related='company_id.amc_default_renewal_rule',
                                                readonly=False)
    amc_default_alert_days = fields.Integer(related='company_id.amc_default_alert_days',
                                            readonly=False)
    amc_activation_trigger = fields.Selection(related='company_id.amc_activation_trigger',
                                              readonly=False)
    amc_product_id = fields.Many2one(related='company_id.amc_product_id', readonly=False)

    @api.depends('company_id', 'amc_default_pricelist_id')
    def _compute_amc_fallback_currency(self):
        for settings in self:
            company = settings.company_id
            pricelist = settings.amc_default_pricelist_id
            settings.amc_fallback_currency_id = company._amc_currency(
                pricelist if company._amc_pricelist_usable(pricelist) else None)
