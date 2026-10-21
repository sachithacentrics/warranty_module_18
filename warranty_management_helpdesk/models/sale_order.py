from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    """Chargeable quotations of a warranty case (approved Part 3.6c Q54: several per case). A
    quotation never creates a Service Job (Part 4 Job Trigger)."""
    _inherit = 'sale.order'

    warranty_case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True,
                                       copy=False, index='btree_not_null')

    @api.constrains('state')
    def _check_warranty_excluded_lines(self):
        self.order_line._check_warranty_excluded_item()

    def action_warranty_customer_declined(self):
        """Customer Declined for all excluded items of this quotation."""
        self.ensure_one()
        items = self.order_line.warranty_excluded_item_id
        if not items:
            raise ValidationError(_("%s has no excluded warranty items.", self.name))
        return items.action_open_decline_wizard()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # Set only by the warranty case actions (clarification 2); read-only on the quotation.
    warranty_case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True,
                                       copy=False, index='btree_not_null')
    warranty_excluded_item_id = fields.Many2one(
        'warranty.case.excluded.item', string='Warranty Excluded Item', readonly=True,
        copy=False, ondelete='set null', index='btree_not_null')

    @api.constrains('warranty_excluded_item_id', 'order_id')
    def _check_warranty_excluded_item(self):
        for line in self.filtered('warranty_excluded_item_id'):
            item = line.warranty_excluded_item_id
            if line.order_id.warranty_case_id != item.case_id:
                raise ValidationError(_("The excluded item %(item)s belongs to warranty case "
                                        "%(case)s, not to this quotation.",
                                        item=item.coverage_item_id.name, case=item.case_id.name))
            if len(item._active_sale_lines()) > 1:
                raise ValidationError(_("The excluded item %(item)s of %(case)s is already on "
                                        "another active quotation.",
                                        item=item.coverage_item_id.name, case=item.case_id.name))
