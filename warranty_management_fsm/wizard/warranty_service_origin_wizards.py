from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WarrantyServiceJobCreateWizard(models.TransientModel):
    """Create Service Job (SRS 9.4 steps 5-6): the selected compatible free services merged
    into ONE Draft service-origin job with its planned date, or added to an open Draft
    service-origin job of the same customer, company and site."""
    _name = 'warranty.service.job.create.wizard'
    _description = 'Create Service Job from Free Services'

    entitlement_ids = fields.Many2many(
        'warranty.service.entitlement', 'warranty_job_create_wizard_entitlement_rel', 'wizard_id',
        'entitlement_id', string='Free Services', required=True)
    company_id = fields.Many2one('res.company', compute='_compute_context_values')
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 compute='_compute_context_values')
    existing_job_ids = fields.Many2many('warranty.service.job',
                                        compute='_compute_context_values')
    job_id = fields.Many2one(
        'warranty.service.job', string='Add to Draft Job',
        domain="[('id', 'in', existing_job_ids)]",
        help="Empty: a new service job. Otherwise the services are added to this open Draft job "
             "of the same customer and site (no ticket yet).")
    planned_date = fields.Datetime(string='Planned Date')
    technician_candidate_ids = fields.Many2many('res.users', compute='_compute_context_values')
    main_technician_id = fields.Many2one('res.users', string='Main Technician',
                                         domain="[('id', 'in', technician_candidate_ids)]")
    support_technician_ids = fields.Many2many(
        'res.users', 'warranty_job_create_wizard_support_rel', 'wizard_id', 'user_id',
        string='Support Technicians', domain="[('id', 'in', technician_candidate_ids)]")
    problems = fields.Text(string='Compatibility', compute='_compute_context_values')

    @api.model
    def _warranty_open(self, services):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Create Service Job"),
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_entitlement_ids': [(6, 0, services.ids)]},
        }

    @api.depends('entitlement_ids', 'job_id')
    def _compute_context_values(self):
        Job = self.env['warranty.service.job']
        for wizard in self:
            services = wizard.entitlement_ids
            cards = services.warranty_card_id
            company = cards.company_id[:1]
            wizard.company_id = company
            wizard.partner_id = cards.partner_id[:1]
            wizard.technician_candidate_ids = self.env['res.users'].search(
                Job._technician_domain(company)) if company else self.env['res.users']
            jobs = Job.search([('job_origin', '=', 'service'), ('state', '=', 'draft'),
                               ('warranty_case_id', '=', False),
                               ('origin_ticket_id', '=', False),
                               ('company_id', '=', company.id),
                               ('commercial_partner_id', '=',
                                cards.partner_id[:1].commercial_partner_id.id)]) \
                if company else Job
            wizard.existing_job_ids = jobs.filtered(
                lambda job: services[:1] and job.site_id
                == services[:1]._warranty_service_site())
            problems = services._warranty_service_job_problems(wizard.job_id or None) \
                if services else []
            wizard.problems = '\n'.join(problems) or False

    def action_create(self):
        self.ensure_one()
        job = self.entitlement_ids._warranty_create_service_job(
            planned_date=self.planned_date, main_technician=self.main_technician_id,
            support_technicians=self.support_technician_ids, job=self.job_id or None)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'warranty.service.job',
            'res_id': job.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }


class WarrantyServiceJobTicketWizard(models.TransientModel):
    """Create or Link Helpdesk Ticket (SRS 9.4 step 7, approved D-C / G6)."""
    _name = 'warranty.service.job.ticket.wizard'
    _description = 'Create or Link Helpdesk Ticket'

    job_id = fields.Many2one('warranty.service.job', string='Service Job', required=True,
                             readonly=True)
    mode = fields.Selection([('link', 'Link an Open Ticket'), ('create', 'Create a New Ticket')],
                            string='Ticket', required=True, compute='_compute_candidates',
                            store=True, readonly=False)
    candidate_ticket_ids = fields.Many2many('helpdesk.ticket', compute='_compute_candidates')
    ticket_id = fields.Many2one('helpdesk.ticket', string='Open Warranty Ticket',
                                domain="[('id', 'in', candidate_ticket_ids)]")
    description = fields.Html(string='Ticket Description')

    @api.depends('job_id')
    def _compute_candidates(self):
        for wizard in self:
            tickets = wizard.job_id._warranty_ticket_candidates() if wizard.job_id \
                else self.env['helpdesk.ticket']
            wizard.candidate_ticket_ids = tickets
            if not wizard.mode:
                wizard.mode = 'link' if tickets else 'create'

    def action_apply(self):
        self.ensure_one()
        if self.mode == 'link' and not self.ticket_id:
            raise UserError(_("Select the open warranty ticket to link."))
        self.job_id._warranty_link_ticket(
            ticket=self.ticket_id if self.mode == 'link' else None,
            description=self.description if self.mode == 'create' else None)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'warranty.service.job',
            'res_id': self.job_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }


class WarrantyFaultReportWizard(models.TransientModel):
    """Report Fault during a free-service visit (approved G5)."""
    _name = 'warranty.fault.report.wizard'
    _description = 'Report Fault'

    job_id = fields.Many2one('warranty.service.job', string='Service Job', required=True,
                             readonly=True)
    unit_candidate_ids = fields.Many2many('warranty.unit', compute='_compute_unit_candidates')
    unit_id = fields.Many2one('warranty.unit', string='Unit Warranty',
                              domain="[('id', 'in', unit_candidate_ids)]")
    description = fields.Text(string='Fault Found', required=True)

    @api.depends('job_id')
    def _compute_unit_candidates(self):
        for wizard in self:
            # sudo: technicians may not read the case; the units of the job's services only.
            case = wizard.job_id.sudo().warranty_case_id
            wizard.unit_candidate_ids = (case.service_unit_ids
                                         or case.service_entitlement_ids.warranty_card_id
                                         .unit_warranty_ids).with_env(self.env)

    def action_apply(self):
        self.ensure_one()
        self.job_id._warranty_report_fault(self.description, unit=self.unit_id or None)
        return {'type': 'ir.actions.act_window_close'}


class WarrantyCaseCreateWizard(models.TransientModel):
    _inherit = 'warranty.case.create.wizard'

    # A ticket with a service-origin job waiting for its case: the case of that job, its Case
    # Type, free services and units come from the job (the case keeps all its checks).
    warranty_from_service_job = fields.Boolean(compute='_compute_warranty_from_service_job')
    case_type = fields.Selection(compute='_compute_case_type', store=True, readonly=False)
    service_entitlement_ids = fields.Many2many(
        compute='_compute_service_entitlement_ids', store=True, readonly=False)

    def _warranty_service_job(self):
        self.ensure_one()
        ticket = self.helpdesk_ticket_id
        return ticket._warranty_waiting_service_job() if ticket else self.env['warranty.service.job']

    @api.depends('helpdesk_ticket_id')
    def _compute_warranty_from_service_job(self):
        for wizard in self:
            wizard.warranty_from_service_job = bool(wizard._warranty_service_job())

    @api.depends('helpdesk_ticket_id')
    def _compute_case_type(self):
        for wizard in self:
            wizard.case_type = 'free_service' if wizard._warranty_service_job() else False

    @api.depends('helpdesk_ticket_id')
    def _compute_service_entitlement_ids(self):
        for wizard in self:
            wizard.service_entitlement_ids = wizard._warranty_service_job().entitlement_ids

    def _compute_from_ticket(self):
        """The header Product / Serial No. only when the job covers exactly one unit (and one
        serial; a kit keeps both on its unit): the Pending Services show them per unit."""
        super()._compute_from_ticket()
        for wizard in self:
            job = wizard._warranty_service_job()
            if not job:
                continue
            # sudo: Helpdesk users may have no Inventory rights.
            units = self.env['warranty.unit'].sudo()
            for service in job.entitlement_ids:
                units |= service.sudo()._warranty_job_units(job)
            serials = units.serial_ids
            wizard.product_id = units.product_id if len(units) == 1 else False
            wizard.serial_id = serials if len(units) == 1 and len(serials) == 1 else False
            wizard.site_id = wizard.site_id or job.site_id

    def _compute_available_service_ids(self):
        """Pending Services selection (SRS Figure 4) without services of another open job;
        the job waiting for its case on this ticket stays selectable (linked on creation)."""
        super()._compute_available_service_ids()
        for wizard in self:
            wizard.available_service_ids = \
                wizard.available_service_ids._warranty_selectable_services(
                    wizard.helpdesk_ticket_id) | wizard._warranty_service_job().entitlement_ids

    def action_create(self):
        """The waiting job gets its case; a wizard left open after that opens the existing case
        (duplicate prevention)."""
        self.ensure_one()
        ticket = self.helpdesk_ticket_id
        job = self._warranty_service_job()
        if job:
            self.write({'case_type': 'free_service',
                        'service_entitlement_ids': [(6, 0, job.entitlement_ids.ids)]})
        else:
            cases = ticket._warranty_job_linked_cases()
            if cases:
                return ticket._warranty_open_job_cases(cases)
        return super().action_create()
