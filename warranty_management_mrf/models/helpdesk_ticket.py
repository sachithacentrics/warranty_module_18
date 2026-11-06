from odoo import api, fields, models


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    warranty_material_request_ids = fields.One2many(
        'material.purchase.requisition', 'warranty_helpdesk_ticket_id', string='Material Requests')
    warranty_material_request_count = fields.Integer(
        compute='_compute_warranty_material_request_count')

    @api.depends('warranty_material_request_ids')
    def _compute_warranty_material_request_count(self):
        for ticket in self:
            ticket.warranty_material_request_count = len(ticket.warranty_material_request_ids)

    def action_warranty_view_material_requests(self):
        self.ensure_one()
        return self.warranty_material_request_ids._warranty_action_view()
