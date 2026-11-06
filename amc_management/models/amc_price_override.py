from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .amc_contract import _CONTRACT_MARKER

OVERRIDE_TYPES = [
    ('price', 'Contract Price'),
    ('pricelist', 'Pricelist / Currency'),
]
OVERRIDE_STATES = [
    ('requested', 'Requested'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
]
# Override requests are created / decided only by their methods (Python object in the context).
_OVERRIDE_MARKER = object()
FREE_PREFIXES = ('message_', 'activity_', 'website_message')


class AmcPriceOverride(models.Model):
    """Manual price / pricelist (currency) override (approved B9 / C5): requested by an AMC
    Coordinator with a reason on a Draft contract; approved or rejected by an AMC Approver of the
    company who is not the requester; original and requested values kept for the audit."""
    _name = 'amc.price.override'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'AMC Override Request'
    _order = 'id desc'

    name = fields.Char(string='Request', readonly=True, default='New', copy=False)
    contract_id = fields.Many2one('amc.contract', string='AMC Contract', required=True,
                                  index=True, ondelete='restrict')
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    override_type = fields.Selection(OVERRIDE_TYPES, string='Override', required=True,
                                     default='price')
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    original_price = fields.Monetary(string='Calculated Price', readonly=True)
    requested_price = fields.Monetary(string='Requested Price')
    original_pricelist_id = fields.Many2one('product.pricelist', string='Current Pricelist',
                                            readonly=True)
    requested_pricelist_id = fields.Many2one(
        'product.pricelist', string='Requested Pricelist',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    reason = fields.Text(string='Reason', required=True)
    state = fields.Selection(OVERRIDE_STATES, string='Status', default='requested',
                             readonly=True, tracking=True)
    requested_by_id = fields.Many2one('res.users', string='Requested By', readonly=True)
    requested_on = fields.Datetime(string='Requested On', readonly=True)
    decided_by_id = fields.Many2one('res.users', string='Decided By', readonly=True)
    decided_on = fields.Datetime(string='Decided On', readonly=True)
    decision_note = fields.Text(string='Decision Note', readonly=True)
    can_decide = fields.Boolean(compute='_compute_can_decide')

    @api.depends_context('uid')
    @api.depends('state', 'requested_by_id')
    def _compute_can_decide(self):
        for request in self:
            request.can_decide = request.state == 'requested' \
                and not request._amc_decider_problem(self.env.user)

    # ------------------------------------------------------------------ request
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group('amc_management.group_amc_coordinator'):
            raise AccessError(_("Only AMC Coordinators can request overrides."))
        for vals in vals_list:
            contract = self.env['amc.contract'].browse(vals.get('contract_id'))
            contract.check_access('write')
            problems = self._amc_request_problems(contract, vals)
            if problems:
                raise UserError(_("No override request for %(contract)s: %(problems)s.",
                                  contract=contract.name, problems='; '.join(problems)))
            vals.update({
                'name': self.env['ir.sequence'].with_company(contract.company_id).next_by_code(
                    'amc.price.override') or 'New',
                'state': 'requested',
                'currency_id': contract.currency_id.id,
                'original_price': contract.calculated_price,
                'original_pricelist_id': contract.pricelist_id.id or False,
                'requested_by_id': self.env.uid,
                'requested_on': fields.Datetime.now(),
                'reason': (vals.get('reason') or '').strip(),
            })
            for name in ('decided_by_id', 'decided_on'):
                vals.pop(name, None)
        requests = super(AmcPriceOverride, self.with_context(
            amc_override_marker=_OVERRIDE_MARKER)).create(vals_list).with_env(self.env)
        for request in requests:
            request._amc_notify_approvers()
            request._amc_log(_("Override %(name)s requested by %(user)s: %(what)s. Reason: "
                               "%(reason)s", name=request.name, user=self.env.user.name,
                               what=request._amc_summary(), reason=request.reason))
        return requests

    @api.model
    def _amc_request_problems(self, contract, vals):
        problems = []
        if contract.state != 'draft':
            problems.append(_("overrides are requested while the contract is Draft"))
        if not (vals.get('reason') or '').strip():
            problems.append(_("a reason is required"))
        kind = vals.get('override_type', 'price')
        if contract.override_ids.filtered(lambda r: r.state == 'requested'
                                          and r.override_type == kind):
            problems.append(_("an override of this kind already waits for approval"))
        if kind == 'price':
            if contract.price_state == 'none':
                problems.append(_("calculate the price first"))
            if (vals.get('requested_price') or 0.0) <= 0:
                problems.append(_("the requested price must be greater than zero"))
        else:
            pricelist = self.env['product.pricelist'].browse(vals.get('requested_pricelist_id'))
            if not pricelist:
                problems.append(_("select the requested pricelist"))
            elif pricelist == contract.pricelist_id:
                problems.append(_("the contract already uses this pricelist"))
            elif not contract.company_id._amc_pricelist_usable(pricelist):
                problems.append(_("the pricelist is archived or of another company"))
        return problems

    def write(self, vals):
        if self.env.context.get('amc_override_marker') is not _OVERRIDE_MARKER \
                and any(not key.startswith(FREE_PREFIXES) for key in vals):
            raise UserError(_("Override requests are changed only by Approve / Reject / Cancel "
                              "(audit history)."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_audit(self):
        raise UserError(_("Override requests are kept for the audit history."))

    def _amc_summary(self):
        self.ensure_one()
        if self.override_type == 'price':
            return _("price %(old)s -> %(new)s", old=self.currency_id.format(self.original_price),
                     new=self.currency_id.format(self.requested_price))
        return _("pricelist %(old)s -> %(new)s (currency %(currency)s)",
                 old=self.original_pricelist_id.display_name or _("none (company currency)"),
                 new=self.requested_pricelist_id.display_name,
                 currency=self.requested_pricelist_id.currency_id.name)

    def _amc_approvers(self):
        self.ensure_one()
        group = self.env.ref('amc_management.group_amc_approver')
        return self.env['res.users'].search([
            ('groups_id', 'in', group.ids), ('share', '=', False),
            ('company_ids', 'in', self.company_id.ids), ('id', '!=', self.requested_by_id.id)])

    def _amc_notify_approvers(self):
        self.ensure_one()
        target = self if self.env.user.email else self.with_context(
            mail_activity_quick_update=True)
        for user in self._amc_approvers():
            target.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                     summary=_("Approve AMC override %s", self.name),
                                     note=self._amc_summary())

    # ------------------------------------------------------------------ decisions
    def _amc_decider_problem(self, user):
        self.ensure_one()
        if not user.has_group('amc_management.group_amc_approver') \
                or self.company_id not in user.company_ids:
            return _("Only AMC Approvers of %s can decide override requests.",
                     self.company_id.name)
        if user == self.requested_by_id:
            return _("You cannot decide an override you requested (separation of duties).")
        return False

    def _amc_check_decider(self):
        for request in self:
            problem = request._amc_decider_problem(self.env.user)
            if problem:
                raise AccessError(problem)
            if request.state != 'requested':
                raise UserError(_("Only requested overrides can be decided."))

    def action_approve(self):
        self._amc_check_decider()
        for request in self:
            contract = request.contract_id
            if contract.state != 'draft':
                raise UserError(_("Contract %s is no longer Draft.", contract.name))
            if request.override_type == 'pricelist' \
                    and not contract.company_id._amc_pricelist_usable(
                        request.requested_pricelist_id):
                raise UserError(_("The requested pricelist is no longer usable."))
            request._amc_decide('approved')
            contract.with_context(amc_contract_marker=_CONTRACT_MARKER)._amc_apply_override(
                request)
            request._amc_log(_("Override %(name)s approved by %(user)s: %(what)s.",
                               name=request.name, user=self.env.user.name,
                               what=request._amc_summary()))
        return True

    def action_reject(self, note=None):
        self._amc_check_decider()
        note = (note or '').strip()
        if not note:
            return {
                'type': 'ir.actions.act_window',
                'name': _("Reject Override"),
                'res_model': 'amc.price.override.reject.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_override_id': self.id},
            }
        for request in self:
            request.with_context(amc_override_marker=_OVERRIDE_MARKER).write(
                {'decision_note': note})
            request._amc_decide('rejected')
            request._amc_log(_("Override %(name)s rejected by %(user)s: %(note)s",
                               name=request.name, user=self.env.user.name, note=note))
        return True

    def action_cancel(self):
        for request in self:
            if request.state != 'requested':
                raise UserError(_("Only requested overrides can be cancelled."))
            if self.env.user != request.requested_by_id \
                    and request._amc_decider_problem(self.env.user):
                raise AccessError(_("Only the requester or an AMC Approver can cancel."))
            request._amc_decide('cancelled')
            request._amc_log(_("Override %(name)s cancelled by %(user)s.", name=request.name,
                               user=self.env.user.name))
        return True

    def _amc_decide(self, state):
        self.ensure_one()
        self.with_context(amc_override_marker=_OVERRIDE_MARKER).write({
            'state': state, 'decided_by_id': self.env.uid, 'decided_on': fields.Datetime.now()})
        # sudo: the To-Dos of the other approvers are closed by the decision.
        self.sudo().activity_ids.action_feedback(feedback=dict(
            self._fields['state']._description_selection(self.env))[state])

    def _amc_log(self, text):
        body = Markup('<p>%s</p>') % text
        for record in (self, self.contract_id):
            # sudo: chatter note only (the approver may not write the contract).
            record.sudo()._message_log(body=body)


class AmcPriceOverrideRejectWizard(models.TransientModel):
    _name = 'amc.price.override.reject.wizard'
    _description = 'Reject AMC Override'

    override_id = fields.Many2one('amc.price.override', required=True, readonly=True)
    note = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        return self.override_id.action_reject(self.note)

