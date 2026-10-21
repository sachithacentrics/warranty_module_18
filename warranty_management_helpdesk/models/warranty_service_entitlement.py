from odoo import api, fields, models

PENDING_SERVICE_STATES = ('draft', 'pending', 'scheduled', 'rescheduled', 'missed')

INACTIVE_CASE_STATES = ('rejected', 'closed')


class WarrantyServiceEntitlement(models.Model):
    _inherit = 'warranty.service.entitlement'

    helpdesk_ticket_id = fields.Many2one(
        'helpdesk.ticket', string='Helpdesk Ticket', readonly=True, copy=False, index=True,
        help="Helpdesk ticket of the warranty case the free service is linked to.")
    warranty_case_ids = fields.Many2many(
        'warranty.case', 'warranty_case_service_entitlement_rel', 'entitlement_id', 'case_id',
        string='Warranty Cases', readonly=True, copy=False)

    @api.model
    def _warranty_pending_services(self, partner, company, site=None, product=None,
                                   serial=None):
        """Pending free services of `partner` (commercial entity) in `company confirmed
        card, status Draft / Pending / Scheduled / Rescheduled or Missed within the grace
        period, Free Services Balance > 0; optionally only for the site (Sales Order delivery
        address of the card), product and serial (unit serials, kit Indoor / Outdoor too)."""
        if not partner or not company:
            return self.browse()
        services = self.search([
            ('company_id', '=', company.id),
            ('warranty_card_id.state', '=', 'confirmed'),
            ('warranty_card_id.partner_id', 'child_of', partner.commercial_partner_id.id),
            ('state', 'in', PENDING_SERVICE_STATES),
        ], order='due_date, warranty_card_id, service_no')
        today = company._warranty_today()

        def pending(service):
            card = service.warranty_card_id
            if service.state == 'missed' and not (
                    service.grace_period_end_date and today <= service.grace_period_end_date):
                return False
            if card.free_services_balance <= 0:
                return False
            if site and card.sale_order_id.partner_shipping_id != site:
                return False
            if product and product not in (card.product_id | card.unit_warranty_ids.product_id):
                return False
            if serial and serial not in card.unit_warranty_ids.serial_ids:
                return False
            return True

        return services.filtered(pending)

    def _warranty_active_cases(self, exclude=None):
        """Active (not Rejected / Closed) warranty cases linked to the service."""
        self.ensure_one()
        cases = self.warranty_case_ids.filtered(
            lambda case: case.state not in INACTIVE_CASE_STATES)
        return cases - exclude if exclude else cases
