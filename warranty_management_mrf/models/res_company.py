from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Mapping D10: defaults of new warranty Material Requests (empty: the company's first
    # warehouse stock / internal transfers; the main technician's employee location first).
    warranty_mrf_source_location_id = fields.Many2one(
        'stock.location', string='MRF Source Location')
    warranty_mrf_dest_location_id = fields.Many2one(
        'stock.location', string='MRF Technician Location')
    warranty_mrf_picking_type_id = fields.Many2one(
        'stock.picking.type', string='MRF Picking Type')
    # Phase 5.3 (D-E, D-M): Material Approval Matrix (SRS settings table), enabled by default.
    warranty_mrf_approval_matrix = fields.Boolean(string='Material Approval Matrix', default=True)
    warranty_mrf_approval_deadline_days = fields.Integer(
        string='Approval To-Do Deadline (days)', default=1)
    # Phase 5.4 (D9): release of Not Covered material and release exception approvers.
    warranty_mrf_release_trigger = fields.Selection(
        [('confirmation', 'On Quotation Confirmation'), ('payment', 'On Payment')],
        string='Chargeable Parts Release', default='confirmation', required=True)
    warranty_mrf_release_exception_user_ids = fields.Many2many(
        'res.users', 'warranty_mrf_release_exception_user_rel', 'company_id', 'user_id',
        string='Chargeable Release Exception Users', domain=[('share', '=', False)])
