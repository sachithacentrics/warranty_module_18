from odoo import models


class WarrantyUnit(models.Model):
    _inherit = 'warranty.unit'

    def _amc_serial(self):
        """The unit serial of the unit's own product (kits: the main serial), else none."""
        self.ensure_one()
        return self.serial_ids.filtered(lambda lot: lot.product_id == self.product_id)[:1]
