from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Status changes only through the buttons (Python object: clients cannot send it).
_OPPORTUNITY_MARKER = object()
OPPORTUNITY_STATES = [
    ('new', 'New'),
    ('offer_sent', 'Offer Sent'),
    ('won', 'Won'),
    ('lost', 'Lost'),
]


class AmcOpportunity(models.Model):
    """AMC Opportunity (approved B3; SRS 7 "Draft AMC Opportunity"): pre-sales follow-up of a
    possible AMC, distinct from the Draft AMC Contract; CRM not required. New -> Offer Sent ->
    Won (Create Contract: linked Draft contract) / Lost (reason)."""
    _name = 'amc.opportunity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'AMC Opportunity'
    _order = 'id desc'

    name = fields.Char(string='Opportunity', required=True, readonly=True, copy=False,
                       default='New')
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True,
                                 index=True)
    site_id = fields.Many2one('res.partner', string='Site', tracking=True,
                              domain="[('id', 'child_of', partner_id)]",
                              help="Service location (customer address).")
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True,
                                 default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', string='Responsible', tracking=True,
                              default=lambda self: self.env.user)
    plan_id = fields.Many2one('amc.plan', string='Expected AMC Plan', tracking=True,
                              domain="['|', ('company_id', '=', False), "
                                     "('company_id', '=', company_id)]",
                              default=lambda self: self.env.company.amc_default_plan_id)
    expected_quantity = fields.Float(string='Expected Equipment Quantity', default=1.0)
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist',
                                   compute='_compute_pricelist', store=True, precompute=True)
    currency_id = fields.Many2one('res.currency', string='Currency', compute='_compute_pricelist',
                                  store=True, precompute=True)
    expected_value = fields.Monetary(string='Expected Value', tracking=True)
    description = fields.Text(string='Equipment / Notes')
    state = fields.Selection(OPPORTUNITY_STATES, string='Status', default='new', required=True,
                             readonly=True, tracking=True, copy=False)
    lost_reason = fields.Text(string='Lost Reason', readonly=True, copy=False)
    contract_ids = fields.One2many('amc.contract', 'opportunity_id', string='AMC Contracts')
    contract_count = fields.Integer(compute='_compute_contract_count')

    @api.depends('partner_id', 'company_id')
    def _compute_pricelist(self):
        """Approved multi-currency A1 resolution: customer -> country group -> AMC Default
        Pricelist -> company currency."""
        for opportunity in self:
            company = opportunity.company_id or self.env.company
            pricelist = company._amc_resolve_pricelist(opportunity.partner_id)[0] \
                if opportunity.partner_id else self.env['product.pricelist']
            opportunity.pricelist_id = pricelist
            opportunity.currency_id = company._amc_currency(pricelist or None)

    def _compute_contract_count(self):
        for opportunity in self:
            opportunity.contract_count = len(opportunity.contract_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                company = self.env['res.company'].browse(vals.get('company_id')) \
                    or self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'amc.opportunity') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('amc_opportunity_marker') is not _OPPORTUNITY_MARKER:
            if {'state', 'lost_reason'} & set(vals):
                raise UserError(_("Use the opportunity buttons to change its status."))
            changed = {key for key in vals
                       if not key.startswith(('message_', 'activity_')) and key != 'user_id'}
            if changed and any(opp.state in ('won', 'lost') for opp in self):
                raise UserError(_("Won / Lost AMC opportunities cannot be changed."))
        return super().write(vals)

    def _set_state(self, state, **vals):
        self.with_context(amc_opportunity_marker=_OPPORTUNITY_MARKER).write(
            dict(vals, state=state))

    def action_offer_sent(self):
        for opportunity in self:
            if opportunity.state != 'new':
                raise UserError(_("Only New opportunities can be marked Offer Sent."))
            opportunity._set_state('offer_sent')
        return True

    def action_mark_lost(self, reason=None):
        reason = (reason or self.env.context.get('amc_lost_reason') or '').strip()
        if not reason:
            return {
                'type': 'ir.actions.act_window',
                'name': _("Mark as Lost"),
                'res_model': 'amc.opportunity.lost',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_opportunity_ids': [(6, 0, self.ids)]},
            }
        for opportunity in self:
            if opportunity.state not in ('new', 'offer_sent'):
                raise UserError(_("Only open opportunities can be marked Lost."))
            opportunity._set_state('lost', lost_reason=reason)
            opportunity._message_log(body=Markup('<p>%s</p>') % _("Marked Lost: %s", reason))
        return True

    def action_create_contract(self):
        """Won: a Draft AMC Contract linked to this opportunity (customer, site, company, plan);
        the contract stays Draft (activation only by its own commercial trigger)."""
        self.ensure_one()
        if self.state not in ('new', 'offer_sent'):
            raise UserError(_("A contract is created from an open opportunity."))
        contract = self.env['amc.contract'].create({
            'partner_id': self.partner_id.id,
            'site_id': self.site_id.id or False,
            'company_id': self.company_id.id,
            'plan_id': self.plan_id.id or False,
            'opportunity_id': self.id,
            'user_id': self.user_id.id,
        })
        self._set_state('won')
        self._message_log(body=Markup('<p>%s</p>') % _("Won: Draft AMC contract %s created.",
                                                       contract.name))
        return contract._amc_open()

    def action_view_contracts(self):
        self.ensure_one()
        if len(self.contract_ids) == 1:
            return self.contract_ids._amc_open()
        return {
            'type': 'ir.actions.act_window',
            'name': _("AMC Contracts"),
            'res_model': 'amc.contract',
            'view_mode': 'list,form',
            'domain': [('opportunity_id', '=', self.id)],
        }
