"""SRS service flow alignment (doc/srs_service_flow_alignment_design.md, approved 2026-10-29):
service-origin route of SRS 9.4 - compatible free services -> one Draft Service Job with the
planned date -> Create or Link Helpdesk Ticket -> manual warranty case on the ticket + eligibility ->
technicians + Confirm (existing) -> Field Service visit and worksheets (existing). Also the
complaint case reported from a free-service visit (G5) and the usage alerts (D-E)."""
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.warranty_management_helpdesk.models.warranty_service_entitlement import (
    INACTIVE_CASE_STATES, warranty_same_site)

from .warranty_service_job import CLOSED_JOB_STATES, OPEN_VISIT_JOB_STATES

# Free services that can still get a service job / a usage alert.
OPEN_SERVICE_STATES = ('draft', 'pending', 'scheduled', 'rescheduled', 'missed')
USAGE_ALERT_STATES = ('draft', 'pending', 'scheduled', 'rescheduled')


def _check_helpdesk_user(env):
    # Approved D-F: Helpdesk users initiate service-origin jobs.
    if not env.user.has_group('helpdesk.group_helpdesk_user'):
        raise AccessError(_("Only Helpdesk users can create service jobs from free services."))


class WarrantyServiceEntitlement(models.Model):
    _inherit = 'warranty.service.entitlement'

    usage_alert_reading = fields.Float(string='Usage Alert Reading', readonly=True, copy=False,
                                       digits=(16, 2))
    usage_alert_date = fields.Date(string='Usage Alert Date', readonly=True, copy=False)

    def _warranty_service_site(self):
        self.ensure_one()
        units = self.warranty_card_id.unit_warranty_ids
        # sudo: the delivery address of the warranty sale is read only.
        return units[:1]._warranty_service_address() if units \
            else self.warranty_card_id.sudo().sale_order_id.partner_shipping_id

    def _warranty_service_job_problems(self, job=None):
        """Select Compatible Services (SRS 9.4 step 5; same rules as the case merge, approved
        G4 / D3 / D6 / D7 / K7): one customer and company, same site, confirmed cards within
        the warranty period, available (status, grace period, balance), not on another open job
        or active case, overlapping service windows, service sequence."""
        if not self:
            return [_("Select at least one free service.")]
        cards = self.warranty_card_id
        company = cards.company_id
        partner = cards.partner_id.commercial_partner_id
        if len(company) > 1 or len(partner) > 1:
            return [_("The free services must belong to one customer and one company.")]
        site = job.site_id if job else self[:1]._warranty_service_site()
        available = self._warranty_pending_services(partner, company)
        today = company._warranty_today()
        problems = []
        for service in self:
            card = service.warranty_card_id
            reasons = []
            if card.state != 'confirmed':
                reasons.append(_("warranty card is not confirmed"))
            elif service not in available:
                reasons.append(_("conflicting status: no longer available (status, grace period "
                                 "or balance)"))
            if card.warranty_basis == 'period' and not (
                    card.warranty_start_date and card.warranty_end_date
                    and card.warranty_start_date <= today <= card.warranty_end_date):
                reasons.append(_("outside the warranty period"))
            jobs = service.service_job_ids.filtered(
                lambda other: other.state not in CLOSED_JOB_STATES and other != job)
            if jobs:
                reasons.append(_("already on the open service job %s",
                                 ', '.join(jobs.mapped('name'))))
            cases = service._warranty_active_cases()
            if cases:
                reasons.append(_("linked to the active warranty case %s",
                                 ', '.join(cases.mapped('name'))))
            if not warranty_same_site(service._warranty_service_site(), site):
                reasons.append(_("other service address than %s", site.display_name or '-'))
            if reasons:
                problems.append('%s (%s): %s' % (service.name, card.name, '; '.join(reasons)))
        services = self | (job.entitlement_ids if job else self.browse())
        return problems + services._warranty_window_conflicts(company) \
            + services._warranty_sequence_problems()

    def _warranty_lock_services(self):
        """Duplicate prevention: row locks of the selected services (as Draft Job from Service,
        approved A5); services processed in another transaction are refused."""
        self.env.cr.execute(
            "SELECT id FROM warranty_service_entitlement WHERE id IN %s FOR UPDATE SKIP LOCKED",
            [tuple(self.ids)])
        locked = {row[0] for row in self.env.cr.fetchall()}
        if len(locked) < len(self):
            raise UserError(_("%s is being processed by another user: try again.", ', '.join(
                self.filtered(lambda service: service.id not in locked).mapped('name'))))
        self.invalidate_recordset()

    def _warranty_create_service_job(self, planned_date=False, main_technician=False,
                                     support_technicians=None, job=None):
        """Merge the services into ONE Draft service-origin job (SRS 9.4 step 6), or add them
        to the open Draft service-origin job `job`; no ticket / case yet."""
        self._warranty_lock_services()
        Job = self.env['warranty.service.job']
        if job and (job.job_origin != 'service' or job.warranty_case_id or job.origin_ticket_id
                    or job.state != 'draft'):
            raise UserError(_("Free services are added only to a Draft service-origin job without "
                              "Helpdesk ticket (%s).", job.name))
        problems = self._warranty_service_job_problems(job)
        if problems:
            raise UserError(_("The free services cannot be merged into one service job:\n%s",
                              '\n'.join(problems)))
        if job:
            job._warranty_service_marker().write(
                {'entitlement_ids': [(4, service.id) for service in self]})
            title = _("Free services %(services)s added to service job %(job)s.",
                      services=', '.join(self.mapped('name')), job=job.name)
        else:
            card = self.warranty_card_id[:1]
            vals = {
                'job_origin': 'service',
                'origin_company_id': card.company_id.id,
                'origin_partner_id': card.partner_id.id,
                'origin_site_id': self[:1]._warranty_service_site().id,
                'entitlement_ids': [(6, 0, self.ids)],
            }
            if planned_date:
                vals['planned_date'] = planned_date
            if main_technician:
                vals['main_technician_id'] = main_technician.id
            if support_technicians:
                vals['support_technician_ids'] = [(6, 0, support_technicians.ids)]
            job = Job._warranty_service_marker().create(vals).with_env(self.env)
            title = _("Service job %(job)s created (Draft) from the free services %(services)s; "
                      "next: Create or Link Helpdesk Ticket.", job=job.name,
                      services=', '.join(self.mapped('name')))
        services = job.entitlement_ids
        services.write({'merge_status': 'selected' if len(services) == 1 else 'merged'})
        body = Markup('<p><b>%s</b></p>') % title
        job._message_log(body=body)
        for service in self:
            service._message_log(body=body)
        return job

    def action_open_service_job_wizard(self):
        """Create Service Job (free services list / form)."""
        _check_helpdesk_user(self.env)
        return self.env['warranty.service.job.create.wizard']._warranty_open(self)

    # ------------------------------------------------------------------ usage alerts (D-E)
    @api.model
    def _warranty_check_usage_alerts(self, cards=None):
        """Usage alert for job creation (SRS 9.4 step 6, approved D-E): the latest reading of
        a completed (signed-off) visit worksheet of a usage-based card reaches the Usage
        Threshold (usage due x Usage Alert %) of its next open free service -> one To-Do for
        the service alert users, once per service."""
        domain = [('warranty_card_id.state', '=', 'confirmed'),
                  ('warranty_card_id.warranty_basis', '=', 'usage'),
                  ('warranty_card_id.service_monitoring_active', '=', True),
                  ('state', 'in', USAGE_ALERT_STATES), ('usage_due', '>', 0)]
        if cards is not None:
            domain.append(('warranty_card_id', 'in', cards.ids))
        Sheet = self.env['warranty.job.worksheet'].sudo()
        for card, services in self.search(domain).grouped('warranty_card_id').items():
            service = services.sorted(lambda s: (s.service_no, s.id))[:1]
            if service.usage_alert_date or service.usage_threshold <= 0:
                continue
            # sudo: worksheets of completed visits, read for the reading only.
            sheets = Sheet.search([('warranty_card_id', '=', card.id), ('state', '=', 'completed'),
                                   ('usage_required', '=', True), ('current_usage', '>', 0)])
            if not sheets:
                continue
            latest = max(sheets, key=lambda sheet: (
                sheet.job_id.actual_completion_date or sheet.write_date, sheet.id))
            if latest.current_usage < service.usage_threshold:
                continue
            service.sudo().write({'usage_alert_reading': latest.current_usage,
                                  'usage_alert_date': card.company_id._warranty_today()})
            note = _("Usage reading %(reading)s %(unit)s (worksheet %(sheet)s) reached the usage "
                     "threshold %(threshold)s of %(service)s (usage due %(due)s): create the "
                     "service job (Create Service Job).", reading=latest.current_usage,
                     unit=dict(service._fields['usage_unit']._description_selection(self.env))
                     .get(service.usage_unit, ''), sheet=latest.name,
                     threshold=service.usage_threshold, service=service.name,
                     due=service.usage_due)
            service.sudo()._message_log(body=Markup('<p>%s</p>') % note)
            for user in card._get_service_alert_users():
                service.sudo().activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=_("Usage alert: %s", service.name), note=note)

    def _cron_monitor_free_services(self):
        result = super()._cron_monitor_free_services()
        self._warranty_check_usage_alerts()
        return result


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    service_job_count = fields.Integer(string='Service Jobs',
                                       compute='_compute_service_job_count')

    def _warranty_service_job_domain(self):
        """Service jobs of the card (any status): case, service-origin and cross-card jobs, from
        the stored Warranty Cards of the job."""
        return [('warranty_card_ids', 'in', self.ids)]

    def _compute_service_job_count(self):
        # Counted as the current user (company / record rules), like the smart button list.
        jobs = self.env['warranty.service.job']
        counts = {}
        if self.ids and jobs.has_access('read'):
            counts = {card.id: count for card, count in jobs._read_group(
                self._warranty_service_job_domain(), ['warranty_card_ids'], ['__count'])}
        for card in self:
            card.service_job_count = counts.get(card.id, 0)

    def action_view_service_jobs(self):
        """Service Jobs smart button: one job opens its form, several the filtered list
        (no creation from here)."""
        self.ensure_one()
        jobs = self.env['warranty.service.job'].search(self._warranty_service_job_domain())
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_fsm.action_warranty_service_job')
        action.update({'domain': [('id', 'in', jobs.ids)], 'context': {'create': False}})
        if len(jobs) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')], 'res_id': jobs.id})
        return action

    def action_open_service_job_wizard(self):
        """Create Service Job from the warranty card: its open, available free services."""
        self.ensure_one()
        _check_helpdesk_user(self.env)
        services = self.service_entitlement_ids.filtered(
            lambda service: service.state in OPEN_SERVICE_STATES
            and not service.service_job_ids.filtered(
                lambda job: job.state not in CLOSED_JOB_STATES)
            and not service._warranty_active_cases())
        if not services:
            raise UserError(_("%s has no open free service without service job or warranty case.",
                              self.name))
        return self.env['warranty.service.job.create.wizard']._warranty_open(services)


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    reported_case_ids = fields.One2many('warranty.case', 'source_service_job_id',
                                        string='Reported Complaint Cases', readonly=True)
    # Check Eligibility before Confirm: the linked case's status, result and reason.
    case_state = fields.Selection(related='warranty_case_id.state', string='Case Status')
    case_eligibility_result = fields.Selection(related='warranty_case_id.eligibility_result',
                                               string='Case Eligibility Result')
    case_eligibility_reason = fields.Text(related='warranty_case_id.eligibility_reason',
                                          string='Case Eligibility Reason')

    helpdesk_ticket_count = fields.Integer(string='Helpdesk Ticket Count',
                                           compute='_compute_helpdesk_ticket_count')

    @api.depends_context('uid')
    @api.depends('helpdesk_ticket_id')
    def _compute_helpdesk_ticket_count(self):
        # Helpdesk Ticket smart button: the job's own ticket, counted as the current user
        # (Helpdesk access rights and record rules), like the opened record.
        Ticket = self.env['helpdesk.ticket']
        readable = Ticket.browse()
        if Ticket.has_access('read'):
            readable = Ticket.search([('id', 'in', self.helpdesk_ticket_id.ids)])
        for job in self:
            job.helpdesk_ticket_count = 1 if job.helpdesk_ticket_id in readable else 0

    def action_view_helpdesk_ticket(self):
        self.ensure_one()
        ticket = self.env['helpdesk.ticket'].search([('id', '=', self.helpdesk_ticket_id.id)])
        if not ticket:
            raise UserError(_("Service job %s has no Helpdesk ticket you can open.", self.name))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Helpdesk Ticket"),
            'res_model': 'helpdesk.ticket',
            'res_id': ticket.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }

    def action_check_case_eligibility(self):
        """Check Eligibility of the linked warranty case from the job (Draft / Planned): the
        case's own action, with its permissions and checks; Confirm stays blocked until the
        case is ready."""
        self.ensure_one()
        if not self.warranty_case_id:
            raise UserError(_("Service job %s has no warranty case yet: use Create or Link "
                              "Helpdesk Ticket.", self.name))
        if self.state not in ('draft', 'planned'):
            raise UserError(_("The eligibility is checked before the service job is confirmed "
                              "(%s).", self.name))
        return self.warranty_case_id.action_check_eligibility()

    def _warranty_complete_visit(self, task, batch=False, inspection=None):
        result = super()._warranty_complete_visit(task, batch=batch, inspection=inspection)
        # D-E: a completed visit may record the reading that reaches the usage threshold.
        self.env['warranty.service.entitlement']._warranty_check_usage_alerts(
            self.sudo().worksheet_ids.warranty_card_id)
        return result

    # ------------------------------------------------------------------ Create or Link Ticket
    def _warranty_check_ticket_link(self):
        self.ensure_one()
        _check_helpdesk_user(self.env)
        if self.job_origin != 'service' or self.warranty_case_id or self.helpdesk_ticket_id:
            raise UserError(_("Service job %s already has its Helpdesk ticket.", self.name))
        if self.state not in ('draft', 'planned'):
            raise UserError(_("The Helpdesk ticket is linked before the service job is confirmed "
                              "(%s).", self.name))
        if not self.entitlement_ids:
            raise UserError(_("Service job %s has no free service.", self.name))

    def _warranty_ticket_candidates(self):
        """Approved D-C: open warranty tickets of the job's customer, company and site (or
        without site)."""
        self.ensure_one()
        tickets = self.env['helpdesk.ticket'].search([
            ('company_id', '=', self.company_id.id), ('is_warranty', '=', True),
            ('partner_id', 'child_of', self.commercial_partner_id.id),
            ('stage_id.fold', '=', False)])
        return tickets.filtered(lambda ticket: not ticket.warranty_site_id
                                or warranty_same_site(ticket.warranty_site_id, self.site_id))

    def action_open_ticket_wizard(self):
        self._warranty_check_ticket_link()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Create or Link Helpdesk Ticket"),
            'res_model': 'warranty.service.job.ticket.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_job_id': self.id},
        }

    def _warranty_single_unit_values(self):
        """Header Product / Serial No. of a job whose free services cover exactly one unit:
        {'product': product, 'serial': the unit's only serial, else an empty lot}. Several
        units (or none): {} - no arbitrary choice; the linked services show each unit."""
        self.ensure_one()
        # sudo: Helpdesk users may have no Inventory rights.
        units = self.env['warranty.unit'].sudo()
        for service in self.entitlement_ids:
            units |= service.sudo()._warranty_job_units(self)
        if len(units) != 1:
            return {}
        serials = units.serial_ids
        return {'product': units.product_id,
                'serial': serials if len(serials) == 1 else serials.browse()}

    def _warranty_fill_ticket_unit(self, ticket, values):
        """A linked ticket keeps its own Product / Serial No.: only an empty Product is filled
        (with the serial when the ticket has none), or an empty Serial No. of the same product.
        sudo: a system write of the link (the ticket's warranty fields are locked once
        linked)."""
        product, serial = values.get('product'), values.get('serial')
        if not product:
            return
        if not ticket.warranty_product_id and not ticket.warranty_serial_id:
            ticket.sudo().write({'warranty_product_id': product.id,
                                 'warranty_serial_id': serial.id})
        elif ticket.warranty_product_id == product and not ticket.warranty_serial_id and serial:
            ticket.sudo().write({'warranty_serial_id': serial.id})

    def _warranty_link_ticket(self, ticket=None, description=None):
        """Create or Link Helpdesk Ticket (SRS 9.4 step 7): the ticket only; the warranty case
        is created manually on the ticket (Warranty Cases > New) and linked to the job by
        warranty.case._warranty_link_waiting_job (customer requirement 2026-10-29)."""
        self.ensure_one()
        self._warranty_check_ticket_link()
        services = self.entitlement_ids
        names = ', '.join('%s (%s)' % (service.name, service.warranty_card_id.name)
                          for service in services)
        if ticket:
            if ticket not in self._warranty_ticket_candidates():
                raise UserError(_("Ticket %(ticket)s is not an open warranty ticket of the "
                                  "customer, company and site of %(job)s.",
                                  ticket=ticket.display_name, job=self.name))
            if not ticket.warranty_site_id:
                ticket.warranty_site_id = self.site_id
            self._warranty_fill_ticket_unit(ticket, self._warranty_single_unit_values())
        else:
            team = self.company_id.warranty_draft_job_team_id
            if not team:
                raise UserError(_("Set the Draft Job Helpdesk Team of %s in the Warranty "
                                  "Settings to create the ticket.", self.company_id.name))
            unit_values = self._warranty_single_unit_values()
            ticket = self.env['helpdesk.ticket'].with_context(mail_create_nosubscribe=True).create({
                'name': _("Free service: %s", names),
                'team_id': team.id,
                'partner_id': self.partner_id.id,
                'is_warranty': True,
                'warranty_site_id': self.site_id.id,
                'warranty_site_address': self.site_id.contact_address or False,
                'warranty_product_id': unit_values.get('product', self.env['product.product']).id,
                'warranty_serial_id': unit_values.get('serial', self.env['stock.lot']).id,
                'description': description or Markup('<p>%s</p>') % _(
                    "Created from service job %(job)s for the free services %(services)s.",
                    job=self.name, services=names),
            })
        self._warranty_service_marker().write({'origin_ticket_id': ticket.id})
        self._message_log(body=Markup('<p><b>%s</b></p>') % _(
            "Helpdesk ticket %(ticket)s linked to service job %(job)s (free services "
            "%(services)s): create its Free Service warranty case on this ticket.",
            ticket=ticket.display_name,
            job=self.name, services=names))
        return ticket

    # ------------------------------------------------------------------ G5 fault report
    def action_open_fault_wizard(self):
        self.ensure_one()
        self._warranty_check_fault_report()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Report Fault"),
            'res_model': 'warranty.fault.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_job_id': self.id},
        }

    def _warranty_check_fault_report(self):
        self.ensure_one()
        if not (self.env.user.has_group('helpdesk.group_helpdesk_user')
                or self.env.user.has_group('industry_fsm.group_fsm_user')):
            raise AccessError(_("Only Field Service and Helpdesk users can report a fault."))
        self.check_access('write')
        if self.job_type != 'warranty' or not self.entitlement_ids \
                or self.state not in OPEN_VISIT_JOB_STATES:
            raise UserError(_("A fault is reported from an open free-service job (%s).",
                              self.name))

    def _warranty_report_fault(self, description, unit=None, product=None, serial=None):
        """Fault found during a free-service visit (approved G5): a separate Warranty Complaint
        case on the same Helpdesk ticket; the Free Service case and its consumption are not
        changed; one open complaint per job and unit / product / serial."""
        self.ensure_one()
        self._warranty_check_fault_report()
        description = (description or '').strip()
        if not description:
            raise UserError(_("Describe the fault."))
        product = unit.product_id if unit else product
        serial = serial or (unit.serial_ids[:1] if unit else self.env['stock.lot'])
        Case = self.env['warranty.case'].sudo()
        duplicate = Case.search([
            ('source_service_job_id', '=', self.id),
            ('state', 'not in', INACTIVE_CASE_STATES + ('completed',)),
            ('product_id', '=', product.id if product else False),
            ('serial_id', '=', serial.id if serial else False)], limit=1)
        if duplicate:
            raise UserError(_("The fault is already reported in warranty case %s.",
                              duplicate.name))
        source = self.warranty_case_id.sudo()
        # sudo: technicians report the fault without Helpdesk rights; the job access was
        # checked as the user; the case follows the complaint route (eligibility, approval).
        case = Case.create({
            'helpdesk_ticket_id': source.helpdesk_ticket_id.id,
            'case_type': 'warranty_complaint',
            'customer_complaint': description,
            'site_id': source.site_id.id,
            'product_id': product.id if product else False,
            'serial_id': serial.id if serial else False,
            'warranty_unit_id': unit.id if unit else False,
            'source_service_job_id': self.id,
        })
        body = Markup('<p><b>%s</b></p><p>%s</p>') % (_(
            "Fault reported by %(user)s during service job %(job)s: warranty complaint case "
            "%(case)s created on ticket %(ticket)s (free service case %(origin)s unchanged).",
            user=self.env.user.name, job=self.name, case=case.name,
            ticket=source.helpdesk_ticket_id.display_name, origin=source.name), description)
        self._message_log(body=body)
        source._message_log(body=body)
        case._message_log(body=body)
        return case


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    def _sync_case_approval_activities(self):
        """Approved D-A: the Free Service case of a service-origin job needs no general case
        approval (the job is confirmed once the case is Eligible)."""
        if self.service_job_ids.filtered(lambda job: job.job_origin == 'service'):
            return self._close_case_approval_activities(_(
                "Service-origin job: no general case approval.")) + [(True, _(
                    "Service-origin job: confirmed without general case approval once Eligible "
                    "(eligibility-based approvals still apply)."))]
        return super()._sync_case_approval_activities()
