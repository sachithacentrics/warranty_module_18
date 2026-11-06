from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HelpdeskTicket(models.Model):
    """Helpdesk Warranty Panel (SRS): site, product and serial of the request, pending free
    services of the customer and the warranty cases of the ticket (approved Part 3.1)."""
    _inherit = 'helpdesk.ticket'


    is_warranty = fields.Boolean(
        string='Is Warranty', default=False, tracking=True,
        help="Warranty request: shows the Warranty tab and allows Create Warranty Case when the "
             "customer has a confirmed or expired warranty card.")
    warranty_available_card_ids = fields.Many2many(
        'warranty.card', string='Available Warranty Cards',
        compute='_compute_warranty_available_cards',
        help="Confirmed and Expired warranty cards of the customer in the ticket company. The "
             "eligibility check decides on the status (Q14).")
    warranty_available_product_ids = fields.Many2many(
        'product.product', compute='_compute_warranty_available_cards')
    warranty_has_cards = fields.Boolean(compute='_compute_warranty_available_cards')
    warranty_site_id = fields.Many2one(
        'res.partner', string='Site', domain="[('id', 'child_of', commercial_partner_id)]",
        help="Customer delivery address (child contact) of the request.")
    # Informational only (2026-10-29): never used for free service matching or eligibility;
    # the Site (warranty_site_id) keeps its logic but is no longer shown on the ticket form.
    warranty_site_address = fields.Char(
        string='Site Address', help="Enter the service location or installation address.")
    warranty_product_id = fields.Many2one(
        'product.product', string='Product',
        domain="[('id', 'in', warranty_available_product_ids)] if is_warranty else []")
    warranty_serial_id = fields.Many2one(
        'stock.lot', string='Serial No.',
        domain="['|', ('product_id', '=', warranty_product_id), "
               "('id', 'in', warranty_unit_serial_ids)] if warranty_product_id else []")
    warranty_unit_serial_ids = fields.Many2many(
        'stock.lot', string='Unit Serials', compute='_compute_warranty_unit_serials',
        help="Serials on the customer's units of the product (kit Indoor / Outdoor too).")
    warranty_pending_service_ids = fields.Many2many(
        'warranty.service.entitlement', string='Pending Services',
        compute='_compute_warranty_pending_service_ids')
    warranty_pending_service_count = fields.Integer(
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
    # Display only: the ticket's linked warranty records (see _warranty_check_linked_write).
    warranty_is_linked = fields.Boolean(compute='_compute_warranty_linked', compute_sudo=True)
    warranty_linked_service_ids = fields.Many2many(
        'warranty.service.entitlement', string='Linked Free Services',
        compute='_compute_warranty_linked', compute_sudo=True)

    def _warranty_linked_cases(self):
        """The cases that bind the ticket: all but Rejected (final, a new case may follow)."""
        self.ensure_one()
        return self.warranty_case_ids.filtered(lambda case: case.state != 'rejected')

    def _warranty_is_linked_ticket(self):
        self.ensure_one()
        return bool(self._warranty_linked_cases())

    def _warranty_linked_services(self):
        self.ensure_one()
        return self._warranty_linked_cases().service_entitlement_ids

    @api.depends('warranty_case_ids.state', 'warranty_case_ids.service_entitlement_ids')
    def _compute_warranty_linked(self):
        for ticket in self:
            ticket.warranty_is_linked = ticket._warranty_is_linked_ticket()
            ticket.warranty_linked_service_ids = ticket._warranty_linked_services()

    def _warranty_check_linked_write(self, vals):
        """A ticket linked to a warranty case or service job keeps its warranty records and
        customer: the case and job carry them. Standalone tickets are free; system writes
        (sudo) and the controlled change workflows, which do not write here, are not affected."""
        labels = {'warranty_product_id': _("Product"), 'warranty_serial_id': _("Serial No."),
                  'warranty_case_ids': _("Warranty Cases"), 'partner_id': _("Customer"),
                  'company_id': _("Company"), 'team_id': _("Helpdesk Team (other company)")}
        if not labels.keys() & vals.keys():
            return
        partner = self.env['res.partner'].browse(vals.get('partner_id'))
        team = self.env['helpdesk.team'].browse(vals.get('team_id'))
        for ticket in self:
            changed = [
                field for field in ('warranty_product_id', 'warranty_serial_id')
                if field in vals and ticket[field].id != (vals[field] or False)]
            if 'warranty_case_ids' in vals:
                changed.append('warranty_case_ids')
            # Another contact of the same customer changes no warranty record.
            if 'partner_id' in vals and partner.commercial_partner_id \
                    != ticket.partner_id.commercial_partner_id:
                changed.append('partner_id')
            if 'company_id' in vals and ticket.company_id.id != vals['company_id']:
                changed.append('company_id')
            if 'team_id' in vals and team.company_id != ticket.company_id:
                changed.append('team_id')
            if changed and ticket.sudo()._warranty_is_linked_ticket():
                raise UserError(_(
                    "Ticket %(ticket)s is linked to a warranty case or service job: %(fields)s "
                    "cannot be changed on the ticket. Use the controlled change on the warranty "
                    "records, or reject the case / cancel the job first.",
                    ticket=ticket.display_name,
                    fields=', '.join(labels[field] for field in changed)))

    def write(self, vals):
        if not self.env.su:
            self._warranty_check_linked_write(vals)
        return super().write(vals)

    @api.depends('is_warranty', 'partner_id', 'company_id')
    def _compute_warranty_available_cards(self):
        Card = self.env['warranty.card']
        for ticket in self:
            cards = Card
            if ticket.is_warranty and ticket.partner_id and ticket.company_id:
                # Search as the user: company record rules apply.
                cards = Card.search([
                    ('state', 'in', ('confirmed', 'expired')),
                    ('company_id', '=', ticket.company_id.id),
                    ('partner_id', 'child_of', ticket.partner_id.commercial_partner_id.id)])
            ticket.warranty_available_card_ids = cards
            ticket.warranty_available_product_ids =                 cards.product_id | cards.unit_warranty_ids.product_id
            ticket.warranty_has_cards = bool(cards)

    @api.onchange('partner_id', 'company_id')
    def _onchange_warranty_partner(self):
        """A new customer / company: drop the warranty selections of the previous one."""
        if self.warranty_site_id and self.warranty_site_id.commercial_partner_id                 != self.partner_id.commercial_partner_id:
            self.warranty_site_id = False
        if self.is_warranty and self.warranty_product_id                 and self.warranty_product_id not in self.warranty_available_product_ids:
            self.warranty_product_id = False
            self.warranty_serial_id = False

    @api.depends('partner_id', 'company_id', 'warranty_product_id')
    def _compute_warranty_unit_serials(self):
        Case = self.env['warranty.case']
        for ticket in self:
            ticket.warranty_unit_serial_ids = Case._warranty_unit_serials(
                ticket.partner_id, ticket.company_id, ticket.warranty_product_id)

    def _warranty_serial_fits_product(self):
        """The serial is one the Serial No. list offers for the product of the ticket. _origin: in
        an onchange the x2many holds new records."""
        self.ensure_one()
        return self.warranty_serial_id.product_id == self.warranty_product_id \
            or self.warranty_serial_id._origin in self.warranty_unit_serial_ids._origin

    def _warranty_check_case_creation(self):
        """Server side of the Create Warranty Case button: warranty ticket, customer and at
        least one confirmed or expired warranty card. Eligibility, approval and duplicate rules are those
        of the warranty case."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Set the customer of the ticket before creating a warranty case."))
        if not self.is_warranty:
            raise UserError(_("Tick Is Warranty on ticket %s before creating a warranty case.",
                              self.display_name))
        if not self.warranty_has_cards:
            raise UserError(_("%s has no confirmed warranty card in %s: no warranty case can be "
                              "created.", self.partner_id.display_name, self.company_id.name))

    @api.depends('partner_id', 'company_id', 'warranty_site_id', 'warranty_product_id',
                 'warranty_serial_id')
    def _compute_warranty_pending_service_ids(self):
        Entitlement = self.env['warranty.service.entitlement']
        for ticket in self:
            ticket.warranty_pending_service_ids = Entitlement._warranty_pending_services(
                ticket.partner_id, ticket.company_id, ticket.warranty_site_id,
                ticket.warranty_product_id, ticket.warranty_serial_id) \
                - ticket.sudo()._warranty_linked_services()
            ticket.warranty_pending_service_count = len(ticket.warranty_pending_service_ids)

    def action_view_warranty_pending_services(self):
        """Pending Services multi-select -> Create Warranty Case."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Pending Services"),
            'res_model': 'warranty.service.entitlement',
            'view_mode': 'list',
            'views': [(self.env.ref(
                'warranty_management_helpdesk.warranty_service_entitlement_view_list_pending').id,
                'list')],
            'domain': [('id', 'in', self.warranty_pending_service_ids.ids)],
            'context': {'warranty_ticket_id': self.id, 'create': False},
        }

    def action_view_warranty_history(self):
        self.ensure_one()
        return self.env['warranty.history']._warranty_open(
            [('card_id', 'in', self.warranty_case_ids.warranty_card_id.ids)])

    @api.depends('partner_id', 'company_id', 'warranty_product_id', 'warranty_serial_id')
    def _compute_warranty_card_unit(self):
        Case = self.env['warranty.case']
        for ticket in self:
            card, unit, __ = Case._warranty_find_card(
                ticket.partner_id, ticket.company_id, ticket.warranty_product_id,
                ticket.warranty_serial_id)
            # Linked ticket: the actual card and unit; several (merged): none, never an arbitrary one.
            linked = ticket.sudo()._warranty_linked_cases()
            cards = ticket.sudo()._warranty_linked_services().warranty_card_id | linked.warranty_card_id
            if cards:
                units = linked.warranty_unit_id or cards.unit_warranty_ids
                card = cards.with_env(self.env) if len(cards) == 1 else card.browse()
                unit = units.with_env(self.env) if len(cards) == 1 and len(units) == 1 \
                    else unit.browse()
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
        if self.warranty_serial_id and not self._warranty_serial_fits_product():
            self.warranty_serial_id = False

    def action_create_warranty_case(self):
        self.ensure_one()
        self._warranty_check_case_creation()
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
