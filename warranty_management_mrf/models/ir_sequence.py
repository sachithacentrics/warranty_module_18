from odoo import models

from .material_purchase_requisition import VENDOR_SEQUENCE_CODE, WARRANTY_SEQUENCE_CODE


class IrSequence(models.Model):
    _inherit = 'ir.sequence'

    def next_by_code(self, sequence_code, sequence_date=None):
        # Mapping D5: the vendor create numbers every requisition with its own code; warranty
        # requisitions are created with this context and take MRF/ numbers instead.
        if sequence_code == VENDOR_SEQUENCE_CODE and self.env.context.get('warranty_mrf_number'):
            sequence_code = WARRANTY_SEQUENCE_CODE
        return super().next_by_code(sequence_code, sequence_date=sequence_date)
