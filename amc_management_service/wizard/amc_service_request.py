from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

TICKET_MODES = [
    ('new', 'Create New'),
    ('link', 'Link Existing'),
]


class AmcServiceRequest(models.TransientModel):
    """Create Service Request (AMC-F01 / F02 / F03; SRS 2.6 "Service Job confirmed from one or
    more services: create or link a Helpdesk ticket first"): compatible pending AMC visits ->
    Helpdesk ticket (new or existing) -> warranty case of type AMC. The Service Job, Field
    Service task, worksheets and sign-off follow the standard warranty process."""
    _name = 'amc.service.request'
    _description = 'AMC Service Request'

    visit_ids = fields.Many2many('amc.contract.visit', string='AMC Visits', required=True)
    contract_id = fields.Many2one('amc.contract', compute='_compute_context')
    partner_id = fields.Many2one('res.partner', string='Customer', compute='_compute_context')
    site_id = fields.Many2one('res.partner', compute='_compute_context')
    company_id = fields.Many2one('res.company', compute='_compute_context')
    ticket_mode = fields.Selection(TICKET_MODES, string='Helpdesk Action', default='new',
                                   required=True)
    team_id = fields.Many2one('helpdesk.team', string='Helpdesk Team',
                              domain="[('company_id', '=', company_id)]")
    ticket_id = fields.Many2one(
        'helpdesk.ticket', string='Helpdesk Ticket',
        domain="[('partner_id', 'child_of', partner_id), ('company_id', '=', company_id), "
               "('stage_id.fold', '=', False)]")
    description = fields.Text(string='Request')
    problems = fields.Text(compute='_compute_context')

    @api.depends('visit_ids')
    def _compute_context(self):
        for wizard in self:
            visits = wizard.visit_ids
            wizard.contract_id = visits.contract_id[:1]
            wizard.partner_id = visits.contract_id[:1].partner_id
            wizard.site_id = visits.site_id[:1]
            wizard.company_id = visits.company_id[:1]
            problems = visits._amc_service_problems() if visits else []
            wizard.problems = '\n'.join(problems) or False

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if not self.team_id and self.company_id:
            self.team_id = self._amc_default_team(self.company_id)

    @api.model
    def _amc_ticket_labels(self, visits):
        """Short ticket title part: "3 x Preventive Visit 1 of 3, Included Free Service 1 of 1"."""
        counts = {}
        for label in visits.sorted('id').mapped('label'):
            counts[label] = counts.get(label, 0) + 1
        return ', '.join('%s x %s' % (count, label) if count > 1 else label
                         for label, count in counts.items())

    @api.model
    def _amc_default_team(self, company):
        return company.warranty_draft_job_team_id or self.env['helpdesk.team'].search(
            [('company_id', '=', company.id)], limit=1)

    def action_confirm(self):
        self.ensure_one()
        self.visit_ids._amc_check_coordinator()
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise UserError(_("Only Helpdesk users can create AMC service requests."))
        visits = self.visit_ids
        problems = visits._amc_service_problems()
        if problems:
            raise UserError(_("The AMC visits cannot be requested together:\n%s",
                              '\n'.join('- %s' % problem for problem in problems)))
        contract = visits.contract_id
        if self.ticket_mode == 'link':
            ticket = self.ticket_id
            if not ticket:
                raise UserError(_("Select the Helpdesk ticket to link."))
            if ticket.partner_id.commercial_partner_id != contract.commercial_partner_id \
                    or ticket.company_id != contract.company_id:
                raise UserError(_("Ticket %s belongs to another customer or company.",
                                  ticket.display_name))
        else:
            team = self.team_id or self._amc_default_team(contract.company_id)
            if not team:
                raise UserError(_("Select the Helpdesk team of the AMC service request."))
            ticket = self.env['helpdesk.ticket'].create({
                'name': _("AMC service %(contract)s: %(labels)s", contract=contract.name,
                          labels=self._amc_ticket_labels(visits)),
                'team_id': team.id,
                'partner_id': contract.partner_id.id,
                'company_id': contract.company_id.id,
                'description': self.description or False,
                'tag_ids': [(4, self.env.ref('amc_management_service.helpdesk_tag_amc').id)],
            })
        products = visits.product_id
        serials = visits.serial_id
        case = self.env['warranty.case'].create({
            'helpdesk_ticket_id': ticket.id,
            'case_type': 'amc',
            'site_id': self.site_id.id or False,
            'product_id': products.id if len(products) == 1 else False,
            'serial_id': serials.id if len(serials) == 1 else False,
            'customer_complaint': self.description or _(
                "AMC preventive / included services: %s", ', '.join(visits.mapped('name'))),
            'warranty_inspection_required': False,
            'amc_contract_id': contract.id,
        })
        visits._amc_link_case(case)
        case._message_log(body=Markup('<p>%s</p>') % _(
            "AMC service request from %(contract)s: %(visits)s.", contract=contract.name,
            visits=', '.join(visits.mapped('name'))))
        contract._amc_log(_("Service request: ticket %(ticket)s, warranty case %(case)s for "
                            "%(visits)s.", ticket=ticket.display_name, case=case.name,
                            visits=', '.join(visits.mapped('name'))))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'warranty.case',
            'res_id': case.id,
            'view_mode': 'form',
        }
