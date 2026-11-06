from odoo import _, api, models
from odoo.exceptions import ValidationError

# Approved D1: consume (add) or put into stock (recycle) a part; 'remove' has no stock value.
MRF_ONLY_LINE_TYPES = ('add', 'recycle')


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.constrains('repair_id', 'repair_line_type')
    def _check_warranty_repair_parts(self):
        """Approved D1: the parts of a Repair Order linked to a warranty case are approved, issued
        and costed by the Material Request only, never consumed a second time here. Also covers
        the product catalog, which creates moves."""
        for move in self:
            if move.repair_line_type in MRF_ONLY_LINE_TYPES and move.repair_id.warranty_case_id:
                raise ValidationError(_(
                    "Repair Order %(repair)s is linked to warranty case %(case)s: request its "
                    "parts with a Material Request of the case.", repair=move.repair_id.name,
                    case=move.repair_id.warranty_case_id.name))
