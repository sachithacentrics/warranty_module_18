from odoo import fields, models

from .warranty_replacement import EXTENSION_UNITS


class WarrantyPolicy(models.Model):
    _inherit = 'warranty.policy'

    # SRS 11 step 3: returned "if policy requires"; empty = the return is needed (SRS 11.1).
    replacement_return_required = fields.Selection(
        [('required', 'Required'), ('not_required', 'Not Required')],
        string='Replacement Return',
        help="Whether the old unit must come back before a replacement is delivered. Empty means "
             "Required.")
    # SRS 11.3: "Add fixed days/months after replacement". What it is added to: BA decision B3.
    replacement_extension_value = fields.Integer(
        string='Replacement Extension',
        help="Days or months added by the Add Fixed Extension date policy.")
    replacement_extension_unit = fields.Selection(EXTENSION_UNITS,
                                                  string='Replacement Extension Unit')
