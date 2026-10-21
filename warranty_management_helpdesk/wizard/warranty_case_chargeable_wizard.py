from odoo import fields, models

from ..models.warranty_case import CHARGEABLE_TYPES


class WarrantyCaseChargeableWizard(models.TransientModel):
    """Convert to Chargeable (approved Part 3.6c Q49): Chargeable Type, original case type
    kept."""
    _name = 'warranty.case.chargeable.wizard'
    _description = 'Convert Warranty Case to Chargeable'

    case_id = fields.Many2one('warranty.case', string='Warranty Case', required=True,
                              readonly=True, ondelete='cascade')
    eligibility_result = fields.Selection(related='case_id.eligibility_result')
    chargeable_type = fields.Selection(CHARGEABLE_TYPES, string='Chargeable Type', required=True)

    def action_convert(self):
        self.ensure_one()
        return self.case_id._warranty_convert_chargeable(self.chargeable_type)
