from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    # SRS 2.10 / mapping D14: approval, issue, consumption and cost stay with the request.
    warranty_repair_id = fields.Many2one(
        'repair.order', string='Repair Order', readonly=True, copy=False,
        index='btree_not_null', ondelete='restrict', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        """A request of a case with exactly one open repair belongs to that Repair Order."""
        records = super().create(vals_list)
        for mrf in records.filtered('warranty_case_id'):
            repairs = mrf.warranty_case_id._warranty_active_repairs().filtered(
                lambda repair: not repair.warranty_equipment_returned)
            if len(repairs) == 1:
                # sudo: system link; the requester may have no Repair rights.
                mrf.sudo().warranty_repair_id = repairs
        return records

    @api.constrains('warranty_repair_id', 'warranty_case_id')
    def _check_warranty_repair_link(self):
        for mrf in self.sudo().filtered('warranty_repair_id'):
            if mrf.warranty_repair_id.warranty_case_id != mrf.warranty_case_id:
                raise ValidationError(_(
                    "Repair Order %(repair)s does not belong to the warranty case of Material "
                    "Request %(mrf)s.", repair=mrf.warranty_repair_id.name, mrf=mrf.name))
