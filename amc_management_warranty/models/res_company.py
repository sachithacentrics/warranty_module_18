from odoo import fields, models

# SRS 7 "AMC Auto-create Mode" (AMC-A03 / A04).
AMC_AUTO_CREATE_MODES = [
    ('none', 'None'),
    ('opportunity', 'Draft AMC Opportunity'),
    ('contract', 'Draft AMC Contract'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    amc_auto_create_mode = fields.Selection(
        AMC_AUTO_CREATE_MODES, string='AMC Auto-create Mode', default='none', required=True,
        help="After warranty confirmation, optionally create a draft AMC opportunity or contract "
             "in the AMC module. It never activates AMC coverage (own commercial trigger).")
    amc_offer_on_warranty_expiry = fields.Boolean(
        string='Offer AMC on Warranty Expiry',
        help="When a warranty card expires, a to-do reminds the responsible user to offer an "
             "AMC (Convert to AMC).")
