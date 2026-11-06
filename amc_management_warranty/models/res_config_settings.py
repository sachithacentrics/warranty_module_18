from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    amc_auto_create_mode = fields.Selection(related='company_id.amc_auto_create_mode',
                                            readonly=False)
    amc_offer_on_warranty_expiry = fields.Boolean(
        related='company_id.amc_offer_on_warranty_expiry', readonly=False)
