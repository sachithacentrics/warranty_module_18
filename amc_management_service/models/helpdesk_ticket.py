from odoo import _, api, fields, models


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    # AMC-F02 (SRS 2.6 / 14 "Helpdesk ticket created -> load pending services"): pending AMC
    # visits of the customer, narrowed by the ticket site / product / serial when known.
    amc_pending_visit_ids = fields.Many2many(
        'amc.contract.visit', string='Pending AMC Services',
        compute='_compute_amc_pending_visit_ids')
    amc_pending_visit_count = fields.Integer(compute='_compute_amc_pending_visit_ids')

    @api.depends('partner_id', 'company_id', 'warranty_site_id', 'warranty_product_id',
                 'warranty_serial_id')
    def _compute_amc_pending_visit_ids(self):
        Visit = self.env['amc.contract.visit']
        for ticket in self:
            if not ticket.partner_id:
                ticket.amc_pending_visit_ids = Visit
                ticket.amc_pending_visit_count = 0
                continue
            domain = [
                ('commercial_partner_id', '=', ticket.partner_id.commercial_partner_id.id),
                ('company_id', '=', ticket.company_id.id or self.env.company.id),
                ('state', '=', 'pending'), ('contract_state', 'in', ('active', 'expiring')),
            ]
            if ticket.warranty_site_id:
                domain.append(('site_id', '=', ticket.warranty_site_id.id))
            if ticket.warranty_product_id:
                domain.append(('product_id', '=', ticket.warranty_product_id.id))
            if ticket.warranty_serial_id:
                domain.append(('serial_id', '=', ticket.warranty_serial_id.id))
            visits = Visit.search(domain, order='due_date, id')
            ticket.amc_pending_visit_ids = visits
            ticket.amc_pending_visit_count = len(visits)

    def action_open_amc_service_request(self):
        """Add pending AMC services to this (ad-hoc) request (AMC-F02)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Add AMC Services"),
            'res_model': 'amc.service.request',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visit_ids': [(6, 0, self.amc_pending_visit_ids.ids)],
                        'default_ticket_mode': 'link', 'default_ticket_id': self.id},
        }
