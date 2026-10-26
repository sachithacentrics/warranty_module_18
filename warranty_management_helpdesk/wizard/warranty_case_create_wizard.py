from odoo import api, fields, models
from odoo.tools import html2plaintext

from odoo.addons.warranty_management.models.res_company import FREE_SERVICE_SCOPE_MODES

from ..models.warranty_case import CASE_PRIORITIES, CASE_TYPES


class WarrantyCaseCreateWizard(models.TransientModel):
    """Create Warranty Case from a Helpdesk ticket (approved Part 3.1 A): link the selected
    pending free services ("Link Selected Service Entitlement") or none ("Create Warranty
    Case")."""
    _name = 'warranty.case.create.wizard'
    _description = 'Create Warranty Case'

    helpdesk_ticket_id = fields.Many2one(
        'helpdesk.ticket', string='Helpdesk Ticket', required=True, readonly=True)
    partner_id = fields.Many2one(related='helpdesk_ticket_id.partner_id', string='Customer')
    commercial_partner_id = fields.Many2one(
        related='helpdesk_ticket_id.partner_id.commercial_partner_id')
    case_type = fields.Selection(CASE_TYPES, string='Case Type', required=True)
    customer_complaint = fields.Text(
        string='Customer Complaint', compute='_compute_from_ticket', store=True,
        readonly=False)
    site_id = fields.Many2one(
        'res.partner', string='Site', compute='_compute_from_ticket', store=True,
        readonly=False, domain="[('id', 'child_of', commercial_partner_id)]")
    product_id = fields.Many2one(
        'product.product', string='Product', compute='_compute_from_ticket', store=True,
        readonly=False)
    serial_id = fields.Many2one(
        'stock.lot', string='Serial No.', compute='_compute_from_ticket', store=True,
        readonly=False, domain="[('product_id', '=', product_id)] if product_id else []")
    priority = fields.Selection(
        CASE_PRIORITIES, string='Priority', compute='_compute_from_ticket', store=True,
        readonly=False)
    available_service_ids = fields.Many2many(
        'warranty.service.entitlement', string='Pending Services',
        compute='_compute_available_service_ids')
    service_entitlement_ids = fields.Many2many(
        'warranty.service.entitlement', string='Link Pending Services',
        domain="[('id', 'in', available_service_ids)]")
    merged_adhoc_request = fields.Boolean(string='Merged Ad-hoc Request')
    merged_adhoc_description = fields.Text(string='Ad-hoc Request')
    # Free service UI shown only when the company's Warranty Scope Mode includes free
    # services (approved; display only, nothing stored).
    warranty_free_services_enabled = fields.Boolean(
        compute='_compute_warranty_free_services_enabled')

    @api.depends('helpdesk_ticket_id.company_id.warranty_scope_mode')
    def _compute_warranty_free_services_enabled(self):
        for record in self:
            record.warranty_free_services_enabled = \
                record.helpdesk_ticket_id.company_id.warranty_scope_mode in FREE_SERVICE_SCOPE_MODES

    @api.depends('helpdesk_ticket_id')
    def _compute_from_ticket(self):
        for wizard in self:
            ticket = wizard.helpdesk_ticket_id
            wizard.site_id = ticket.warranty_site_id
            wizard.product_id = ticket.warranty_product_id
            wizard.serial_id = ticket.warranty_serial_id
            wizard.priority = ticket.priority or '1'
            wizard.customer_complaint = html2plaintext(ticket.description or '').strip() \
                or ticket.name

    @api.depends('partner_id', 'site_id', 'product_id', 'serial_id')
    def _compute_available_service_ids(self):
        Entitlement = self.env['warranty.service.entitlement']
        for wizard in self:
            ticket = wizard.helpdesk_ticket_id
            wizard.available_service_ids = Entitlement._warranty_pending_services(
                ticket.partner_id, ticket.company_id, wizard.site_id, wizard.product_id,
                wizard.serial_id)

    def action_add_all_pending(self):
        """Add All Pending (approved UI 2)."""
        self.ensure_one()
        self.service_entitlement_ids = self.available_service_ids
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_create(self):
        self.ensure_one()
        case = self.env['warranty.case'].create({
            'helpdesk_ticket_id': self.helpdesk_ticket_id.id,
            'case_type': self.case_type,
            'customer_complaint': self.customer_complaint,
            'site_id': self.site_id.id,
            'product_id': self.product_id.id,
            'serial_id': self.serial_id.id,
            'priority': self.priority,
            'service_entitlement_ids': [(6, 0, self.service_entitlement_ids.ids)],
            'merged_adhoc_request': self.merged_adhoc_request,
            'merged_adhoc_description': self.merged_adhoc_description,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'warranty.case',
            'res_id': case.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }
