from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

PENDING_SERVICE_STATES = ('draft', 'pending', 'scheduled', 'rescheduled', 'missed')


def warranty_address_key(partner):
    """Normalized physical address (approved D6): street, street 2, ZIP, city (case and spaces
    ignored), state, country; None for an address without street and city."""
    norm = lambda value: ' '.join((value or '').lower().split())
    key = (norm(partner.street), norm(partner.street2), norm(partner.zip), norm(partner.city),
           partner.state_id.id or 0, partner.country_id.id or 0)
    return key if (key[0] or key[3]) else None


def warranty_same_site(address, site):
    """Approved D6 rules 1 / 2: the same address record, or an address of the same
    commercial customer with the identical normalized physical address."""
    if address == site:
        return True
    if not address or not site \
            or address.commercial_partner_id != site.commercial_partner_id:
        return False
    key = warranty_address_key(address)
    return bool(key) and key == warranty_address_key(site)

INACTIVE_CASE_STATES = ('rejected', 'closed')


class WarrantyServiceEntitlement(models.Model):
    _inherit = 'warranty.service.entitlement'

    helpdesk_ticket_id = fields.Many2one(
        'helpdesk.ticket', string='Helpdesk Ticket', readonly=True, copy=False, index=True,
        help="Helpdesk ticket of the warranty case the free service is linked to.")
    warranty_case_ids = fields.Many2many(
        'warranty.case', 'warranty_case_service_entitlement_rel', 'entitlement_id', 'case_id',
        string='Warranty Cases', readonly=True, copy=False)
    # Cross-card service merge (approved UI 1-3): units of the card and date window, display.
    warranty_units_display = fields.Char(string='Units', compute='_compute_warranty_units_display')
    warranty_window_display = fields.Char(string='Service Window',
                                          compute='_compute_warranty_units_display')
    # Late Service Exceptions (BA-approved enhancement F5-F8).
    late_service_handling = fields.Selection(related='warranty_card_id.late_service_handling')
    service_date_exception_ids = fields.One2many(
        'warranty.service.date.exception', 'entitlement_id', string='Late Service Exceptions',
        readonly=True)

    def _compute_warranty_units_display(self):
        for service in self:
            units = service.warranty_card_id.unit_warranty_ids
            service.warranty_units_display = ', '.join(
                '%s%s' % (unit.product_id.display_name or unit.name,
                          ' [%s]' % ', '.join(unit.serial_ids.mapped('name'))
                          if unit.serial_ids else '') for unit in units) or False
            window = service._warranty_service_window()
            service.warranty_window_display = '%s - %s' % window if window else False

    def _warranty_service_window(self):
        """Permitted service dates used by eligibility, merge, planning and completion: the
        flexible service dates of the card (BA-approved enhancement, _warranty_allowed_range),
        else the standard D3 window (_warranty_alert_window)."""
        self.ensure_one()
        return self._warranty_allowed_range() or self._warranty_alert_window()

    def _warranty_alert_window(self):
        """Service date window (approved D3, BA interpretation of SRS 2.5 "feasible date
        window"): earliest = Alert Date (due date - the card's Service Due Alert Days), else the
        Due Date; latest = Grace Period End (due date + the card's Grace Period Days), else the
        Due Date. Taken from the card values (also when service monitoring is off). None without
        due date (usage-based: checked on the worksheet reading). Also the trigger window of the
        Part 4.11 automatic draft jobs (unchanged by the flexible service dates, K8)."""
        self.ensure_one()
        if not self.due_date:
            return None
        card = self.warranty_card_id
        earliest = self.due_date - timedelta(days=max(card.service_due_alert_days, 0))
        latest = self.due_date + timedelta(days=max(card.grace_period_days, 0))
        return earliest, latest

    def action_create_warranty_case_from_services(self):
        """Pending Services list (approved UI 1): one Free Service warranty case for the
        selected services of the ticket (context ticket, checked)."""
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can create warranty cases."))
        ticket = self.env['helpdesk.ticket'].browse(self.env.context.get('warranty_ticket_id'))
        if not ticket.exists() or not self:
            raise UserError(_("Open the Pending Services from a Helpdesk ticket and select the "
                              "free services."))
        ticket.check_access('write')
        outside = self - ticket.warranty_pending_service_ids
        if outside:
            raise UserError(_("%s is not a pending free service of this ticket.",
                              ', '.join(outside.mapped('name'))))
        case = self.env['warranty.case'].create({
            'helpdesk_ticket_id': ticket.id,
            'case_type': 'free_service',
            'service_entitlement_ids': [(6, 0, self.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'warranty.case',
            'res_id': case.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }

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
            # Approved K3: an approved Late Service Exception keeps a Missed service available.
            limit = service._warranty_expiry_limit()
            if service.state == 'missed' and not (limit and today <= limit):
                return False
            if card.free_services_balance <= 0:
                return False
            # Helpdesk users may have no Sales rights: the unit reads the address with sudo.
            if site and not warranty_same_site(
                    card.unit_warranty_ids[:1]._warranty_service_address()
                    if card.unit_warranty_ids
                    else card.sudo().sale_order_id.partner_shipping_id, site):
                return False
            if product and product not in (card.product_id | card.unit_warranty_ids.product_id):
                return False
            if serial and serial not in card.unit_warranty_ids.serial_ids:
                return False
            return True

        return services.filtered(pending)

    def _warranty_window_conflicts(self, company):
        """Approved D3, revised 2026-10-29 (cross-card merge): the service windows (due dates)
        of these services need not overlap - compatible services of different cards are
        combined into one job and visit whatever their due dates; a service whose permitted
        service dates ended before today is still refused (shared by the warranty case, the
        service-origin job and Draft Job from Service)."""
        windows = {service: service._warranty_service_window() for service in self}
        windows = {service: window for service, window in windows.items() if window}
        # Flexible service dates (BA-approved K2): a single service is checked too.
        flexible = any(service._warranty_allowed_range() for service in windows)
        if len(windows) < 2 and not (flexible and windows):
            return []
        today = company._warranty_today()
        hint = _(" A Helpdesk user can Request Late Service Exception for a service whose policy "
                 "allows it.") if any(service.late_service_handling == 'approval'
                                      for service in windows) else ''
        return [_("The permitted service dates of %(service)s (%(start)s - %(end)s) have "
                  "ended.%(hint)s", service=service.name, start=window[0], end=window[1],
                  hint=hint)
                for service, window in windows.items() if window[1] < today]

    def _warranty_active_cases(self, exclude=None):
        """Active (not Rejected / Closed) warranty cases linked to the service."""
        self.ensure_one()
        cases = self.warranty_case_ids.filtered(
            lambda case: case.state not in INACTIVE_CASE_STATES)
        return cases - exclude if exclude else cases

    # ------------------------------------------------------------------ flexible service dates
    def _warranty_approved_service_date(self):
        """Latest date of the approved Late Service Exceptions (approved F8 / K3); a requested
        exception grants nothing."""
        self.ensure_one()
        dates = self.env['warranty.service.date.exception'].search([
            ('entitlement_id', '=', self.id), ('state', '=', 'approved')]).mapped('requested_date')
        return max(dates) if dates else False

    def _warranty_after_expiry(self):
        result = super()._warranty_after_expiry()
        self.env['warranty.service.date.exception'].search([
            ('entitlement_id', 'in', self.ids), ('state', '=', 'requested')
        ])._warranty_close_on_expiry()
        return result

    def _warranty_on_open_job(self):
        """The free service is on an open service job (warranty_management_fsm)."""
        self.ensure_one()
        return False

    def _warranty_sequence_problems(self, completing=False):
        """Enforce Service Sequence (BA-approved F3 / K7, card snapshot): free services of one
        card are not serviced together; a free service needs the previous services of its card
        Completed, Expired or Cancelled - at completion always, before (eligibility, Prepare
        Service Job) unless the previous service is on another open service job."""
        problems = []
        for card, services in self.grouped('warranty_card_id').items():
            if not card.service_sequence_required:
                continue
            if len(services) > 1:
                problems.append(_("%(card)s: free services %(services)s of one card cannot be "
                                  "serviced together (Enforce Service Sequence).", card=card.name,
                                  services=', '.join(services.sorted('service_no').mapped('name'))))
            for service in services:
                previous = card.service_entitlement_ids.filtered(
                    lambda other: other.service_no < service.service_no
                    and other.state not in ('completed', 'expired', 'cancelled')
                    and other not in services)
                if not completing:
                    previous = previous.filtered(lambda other: not other._warranty_on_open_job())
                if previous:
                    problems.append(_(
                        "%(service)s (%(card)s): the previous free service %(previous)s must be "
                        "Completed, Expired or Cancelled first (Enforce Service Sequence).",
                        service=service.name, card=card.name,
                        previous=', '.join(previous.sorted('service_no').mapped('name'))))
        return problems

    def action_open_late_service_wizard(self):
        self.ensure_one()
        return self.env['warranty.service.date.exception.wizard']._warranty_open(self)
