from odoo import fields, models


class HelpdeskTeam(models.Model):
    """Inspection configuration (SRS 2.11 / 9.7, approved Part 3.6c Q50): the team decides
    whether a chargeable case gets an inspection quotation."""
    _inherit = 'helpdesk.team'

    warranty_inspection_required = fields.Boolean(
        string='Inspection Required',
        help="Converting a warranty case to chargeable creates a draft inspection quotation.")
    warranty_inspection_product_id = fields.Many2one(
        'product.product', string='Inspection Product', domain=[('sale_ok', '=', True)],
        check_company=True)
    warranty_inspection_currency_id = fields.Many2one(related='company_id.currency_id')
    warranty_inspection_amount = fields.Monetary(
        string='Inspection Amount', currency_field='warranty_inspection_currency_id',
        help="Price of the inspection line (e.g. Rs. 850); 0 = product sales price.")
