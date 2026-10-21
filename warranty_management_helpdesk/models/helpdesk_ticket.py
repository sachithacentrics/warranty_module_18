from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HelpdeskTicket(models.Model):
    """Helpdesk Warranty Panel (SRS): site, product and serial of the request, pending free
    services of the customer and the warranty cases of the ticket (approved Part 3.1)."""
    _inherit = 'helpdesk.ticket'

    warranty_site_id = fields.Many2one(
        'res.partner', string='Site', domain="[('id', 'child_of', commercial_partner_id)]",
        help="Customer delivery address (child contact) of the request.")
    warranty_product_id = fields.Many2one('product.product', string='Product')
    warranty_serial_id = fields.Many2one(
        'stock.lot', string='Serial No.',
        domain="[('product_id', '=', warranty_product_id)] if warranty_product_id else []")
    warranty_pending_service_ids = fields.Many2many(
        'warranty.service.entitlement', string='Pending Services',
        compute='_compute_warranty_pending_service_ids')
    warranty_card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', compute='_compute_warranty_card_unit')
    warranty_unit_id = fields.Many2one(
        'warranty.unit', string='Unit Warranty', compute='_compute_warranty_card_unit')
    # Helpdesk Warranty Panel "Overdue Warning" (approved Part 3.3 Q16): always shown.
    warranty_overdue_warning = fields.Char(
        string='Overdue Warning', compute='_compute_warranty_overdue_warning')
    warranty_case_ids = fields.One2many(
        'warranty.case', 'helpdesk_ticket_id', string='Warranty Cases', readonly=True)
    warranty_case_count = fields.Integer(compute='_compute_warranty_case_count')

    @api.depends('partner_id', 'company_id', 'warranty_site_id', 'warranty_product_id',
                 'warranty_serial_id')
    def _compute_warranty_pending_service_ids(self):
        Entitlement = self.env['warranty.service.entitlement']
        for ticket in self:
            ticket.warranty_pending_service_ids = Entitlement._warranty_pending_services(
                ticket.partner_id, ticket.company_id, ticket.warranty_site_id,
                ticket.warranty_product_id, ticket.warranty_serial_id)

    @api.depends('partner_id', 'company_id', 'warranty_product_id', 'warranty_serial_id')
    def _compute_warranty_card_unit(self):
        Case = self.env['warranty.case']
        for ticket in self:
            card, unit, __ = Case._warranty_find_card(
                ticket.partner_id, ticket.company_id, ticket.warranty_product_id,
                ticket.warranty_serial_id)
            ticket.warranty_card_id = card
            ticket.warranty_unit_id = unit

    @api.depends('partner_id', 'company_id')
    def _compute_warranty_overdue_warning(self):
        Case = self.env['warranty.case']
        for ticket in self:
            ticket.warranty_overdue_warning = Case._warranty_overdue_warning(
                ticket.partner_id, ticket.company_id)

    @api.depends('warranty_case_ids')
    def _compute_warranty_case_count(self):
        for ticket in self:
            ticket.warranty_case_count = len(ticket.warranty_case_ids)

    @api.constrains('partner_id', 'warranty_site_id')
    def _check_warranty_site(self):
        for ticket in self:
            if ticket.warranty_site_id and ticket.warranty_site_id.commercial_partner_id \
                    != ticket.partner_id.commercial_partner_id:
                raise ValidationError(_(
                    "The site of ticket %s must be an address of its customer.",
                    ticket.display_name))

    @api.onchange('warranty_product_id')
    def _onchange_warranty_product_id(self):
        if self.warranty_serial_id and self.warranty_serial_id.product_id \
                != self.warranty_product_id:
            self.warranty_serial_id = False

    def action_create_warranty_case(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Set the customer of the ticket before creating a warranty case."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Create Warranty Case"),
            'res_model': 'warranty.case.create.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_helpdesk_ticket_id': self.id},
        }

    def action_view_warranty_cases(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_helpdesk.action_warranty_case')
        action['domain'] = [('helpdesk_ticket_id', '=', self.id)]
        action['context'] = {'default_helpdesk_ticket_id': self.id}
        if len(self.warranty_case_ids) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')],
                           'res_id': self.warranty_case_ids.id})
        return action
