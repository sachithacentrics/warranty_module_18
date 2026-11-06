from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from .material_purchase_requisition_cost import COST_GROUPS, WARRANTY_BUCKETS

# Phase 5.8 (design doc/part5_8_vendor_claim_design.md rev. 2, V-1 - V-18 with corrections
# C1 - C8): vendor / manufacturer reimbursement claims on the verified actual cost of consumed
# Covered / Goodwill parts. Claims never post: recoveries are standard vendor credit notes,
# created as drafts on request and posted / reconciled by Accounting users.
GROUP_HELPDESK = 'helpdesk.group_helpdesk_user'
GROUP_REQUISITION = 'material_purchase_requisitions.group_purchase_requisition_user'
GROUP_BILLING = 'account.group_account_invoice'
CLAIM_STATES = [
    ('draft', 'Draft'),
    ('to_approve', 'Waiting Approval'),
    ('approved', 'Approved'),
    ('sent', 'Sent to Vendor'),
    ('answered', 'Vendor Responded'),
    ('closed', 'Closed'),
    ('cancel', 'Cancelled'),
]
VENDOR_RESULTS = [('accepted', 'Accepted'), ('partial', 'Partially Accepted'),
                  ('rejected', 'Rejected')]
RECOVERY_STATUSES = [
    ('pending', 'Not Recovered'),
    ('partial', 'Partially Recovered'),
    ('recovered', 'Recovered'),
    ('rejected', 'Rejected by Vendor'),
    ('written_off', 'Closed with Write-off'),
]
CASE_RECOVERY_STATUSES = [
    ('none', 'No Claim'),
    ('claimed', 'Claimed'),
    ('partial', 'Partially Recovered'),
    ('recovered', 'Recovered'),
    ('rejected', 'Rejected'),
]
PARTNER_SOURCES = [
    ('supplier', 'Supplying Vendor'),
    ('manufacturer', 'Warranty Claim Partner (product)'),
    ('pricelist', 'Product Vendor List'),
    ('manual', 'Manual Override'),
]
# Written by the claim workflow only (superuser mode after the checks).
PROTECTED_FIELDS = {
    'state', 'submitted_by_id', 'submitted_date', 'warranty_approved_by_id',
    'warranty_approved_date', 'finance_required', 'finance_approved_by_id',
    'finance_approved_date', 'approved_amount', 'approver_user_ids', 'sent_by_id', 'sent_date',
    'response_date', 'responded_by_id', 'close_reason', 'closed_by_id', 'closed_date',
    'cancel_reason', 'written_off_amount', 'company_id', 'case_id', 'proposed_partner_id',
    'partner_source',
}
DRAFT_FIELDS = {'partner_id', 'claim_type', 'partner_override_reason', 'failure_description',
                'defective_return_required', 'defective_return_ref', 'line_ids', 'user_id',
                'previous_claim_id'}
FREE_FIELDS = {'vendor_reference', 'defective_return_ref', 'message_main_attachment_id'}
FREE_PREFIXES = ('message_', 'activity_', 'website_message')
ACTIVE_LINE_STATES = ('draft', 'to_approve', 'approved', 'sent', 'answered', 'closed')


class WarrantyVendorClaim(models.Model):
    _name = 'warranty.vendor.claim'
    _description = 'Warranty Vendor / Manufacturer Claim'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Claim No.', readonly=True, copy=False, default='/')
    company_id = fields.Many2one('res.company', required=True, readonly=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    user_id = fields.Many2one('res.users', string='Responsible', default=lambda self: self.env.user,
                              tracking=True)
    partner_id = fields.Many2one('res.partner', string='Vendor / Manufacturer', required=True,
                                 tracking=True)
    claim_type = fields.Selection([('vendor', 'Vendor'), ('manufacturer', 'Manufacturer')],
                                  required=True, default='vendor', tracking=True)
    proposed_partner_id = fields.Many2one('res.partner', string='Proposed Partner', readonly=True)
    partner_source = fields.Selection(PARTNER_SOURCES, string='Partner Basis', readonly=True)
    partner_override_reason = fields.Text(string='Partner Override Reason', tracking=True)
    case_id = fields.Many2one('warranty.case', string='Warranty Case', required=True,
                              readonly=True, index=True, ondelete='restrict')
    job_ids = fields.Many2many('warranty.service.job', string='Service Jobs',
                               compute='_compute_links', store=True)
    requisition_ids = fields.Many2many('material.purchase.requisition', string='Material Requests',
                                       compute='_compute_links', store=True)
    previous_claim_id = fields.Many2one('warranty.vendor.claim', string='Re-claim of',
                                        readonly=True, copy=False)
    state = fields.Selection(CLAIM_STATES, default='draft', required=True, readonly=True,
                             tracking=True, copy=False)
    line_ids = fields.One2many('warranty.vendor.claim.line', 'claim_id', string='Claim Lines',
                               copy=False)
    failure_description = fields.Text(string='Failure Description', tracking=True)
    defective_return_required = fields.Boolean(string='Defective Part Return Required',
                                               tracking=True)
    defective_return_ref = fields.Char(string='Defective Part Return Reference', tracking=True)
    goodwill = fields.Boolean(string='Goodwill Claim', compute='_compute_amounts', store=True)
    supplier_warranty_warning = fields.Text(string='Supplier Warranty Warnings',
                                            compute='_compute_supplier_warranty')
    # Approval (V-8 / C3)
    approver_user_ids = fields.Many2many('res.users', 'warranty_vendor_claim_approver_rel',
                                         'claim_id', 'user_id', string='Named Approvers',
                                         readonly=True, copy=False)
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True,
                                      copy=False)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    warranty_approved_by_id = fields.Many2one('res.users', string='Warranty Approved By',
                                              readonly=True, copy=False, tracking=True)
    warranty_approved_date = fields.Datetime(string='Warranty Approved On', readonly=True,
                                             copy=False)
    finance_required = fields.Boolean(string='Finance Approval Required', readonly=True,
                                      copy=False)
    finance_approved_by_id = fields.Many2one('res.users', string='Finance Approved By',
                                             readonly=True, copy=False, tracking=True)
    finance_approved_date = fields.Datetime(string='Finance Approved On', readonly=True,
                                            copy=False)
    approved_amount = fields.Monetary(string='Approved Amount', readonly=True, copy=False,
                                      tracking=True)
    # Vendor (V-11)
    vendor_reference = fields.Char(string='Vendor Claim Reference', tracking=True, copy=False)
    sent_by_id = fields.Many2one('res.users', string='Sent By', readonly=True, copy=False)
    sent_date = fields.Date(string='Sent On', readonly=True, copy=False, tracking=True)
    response_date = fields.Date(string='Vendor Response Date', readonly=True, copy=False,
                                tracking=True)
    responded_by_id = fields.Many2one('res.users', string='Response Recorded By', readonly=True,
                                      copy=False)
    vendor_result = fields.Selection(VENDOR_RESULTS, string='Vendor Result',
                                     compute='_compute_amounts', store=True, tracking=True)
    # Closure (V-16)
    close_reason = fields.Text(string='Close / Write-off Reason', readonly=True, copy=False)
    closed_by_id = fields.Many2one('res.users', string='Closed By', readonly=True, copy=False)
    closed_date = fields.Datetime(string='Closed On', readonly=True, copy=False)
    cancel_reason = fields.Text(string='Cancellation Reason', readonly=True, copy=False,
                                tracking=True)
    written_off_amount = fields.Monetary(string='Written Off', readonly=True, copy=False)
    # Amounts (C6), company currency
    claimed_amount = fields.Monetary(string='Claimed', compute='_compute_amounts', store=True)
    accepted_amount = fields.Monetary(string='Accepted', compute='_compute_amounts', store=True)
    not_accepted_amount = fields.Monetary(string='Not Accepted', compute='_compute_amounts',
                                          store=True)
    recovery_ids = fields.One2many('warranty.vendor.claim.recovery', 'claim_id',
                                   string='Credit Note Allocations', copy=False,
                                   context={'active_test': False})
    allocated_amount = fields.Monetary(string='Allocated', compute='_compute_allocation_info',
                                       help="Allocations of draft or posted credit notes.")
    recovered_amount = fields.Monetary(string='Recovered', compute='_compute_recovery',
                                       store=True,
                                       help="Allocations of posted, not reversed vendor credit "
                                            "notes.")
    settled_amount = fields.Monetary(string='Settled', compute='_compute_recovery', store=True,
                                     help="Recovered amount whose credit note is reconciled "
                                          "(offset against vendor bills or refunded). A credit "
                                          "note alone is not a cash receipt.")
    outstanding_amount = fields.Monetary(string='Outstanding', compute='_compute_recovery',
                                         store=True, help="Accepted - Recovered.")
    recovery_status = fields.Selection(RECOVERY_STATUSES, string='Recovery Status',
                                       compute='_compute_recovery', store=True)
    over_claimed = fields.Boolean(string='Over-claimed', compute='_compute_over_claimed',
                                  store=True)
    credit_note_count = fields.Integer(compute='_compute_allocation_info')
    can_approve = fields.Boolean(compute='_compute_can_approve')

    _sql_constraints = [('name_company_uniq', 'unique(name, company_id)',
                         'The claim number must be unique per company.')]

    # ------------------------------------------------------------------ computes
    @api.depends('line_ids.requisition_id')
    def _compute_links(self):
        for claim in self:
            claim.requisition_ids = claim.line_ids.requisition_id
            claim.job_ids = claim.line_ids.requisition_id.warranty_service_job_id

    @api.depends('line_ids.claimed_amount', 'line_ids.accepted_amount', 'line_ids.goodwill',
                 'response_date', 'state')
    def _compute_amounts(self):
        for claim in self:
            claimed = sum(claim.line_ids.mapped('claimed_amount'))
            answered = bool(claim.response_date)
            accepted = sum(claim.line_ids.mapped('accepted_amount')) if answered else 0.0
            currency = claim.currency_id or self.env.company.currency_id
            if not answered:
                result = False
            elif currency.is_zero(accepted):
                result = 'rejected'
            elif currency.compare_amounts(accepted, claimed) >= 0:
                result = 'accepted'
            else:
                result = 'partial'
            claim.update({
                'claimed_amount': claimed, 'accepted_amount': accepted,
                'not_accepted_amount': claimed - accepted if answered else 0.0,
                'vendor_result': result, 'goodwill': any(claim.line_ids.mapped('goodwill')),
            })

    @api.depends('recovery_ids.amount', 'recovery_ids.active', 'recovery_ids.move_id.state',
                 'recovery_ids.move_id.payment_state', 'recovery_ids.move_id.amount_residual',
                 'recovery_ids.move_id.amount_untaxed_signed',
                 'recovery_ids.move_id.warranty_claim_recovery_ids.amount',
                 'recovery_ids.move_id.warranty_claim_recovery_ids.active',
                 'recovery_ids.move_id.reversal_move_ids.state',
                 'recovery_ids.move_id.reversal_move_ids.amount_total_signed',
                 'recovery_ids.move_id.reversal_move_ids.reversal_move_ids.state',
                 'accepted_amount', 'vendor_result', 'state', 'written_off_amount')
    def _compute_recovery(self):
        for claim in self:
            allocations = claim.sudo().recovery_ids.filtered('active')
            recovered = sum(allocations.mapped('recovered_amount'))
            settled = sum(allocations.mapped('settled_amount'))
            currency = claim.currency_id or self.env.company.currency_id
            if claim.vendor_result == 'rejected':
                status = 'rejected'
            elif claim.state == 'closed' and not currency.is_zero(claim.written_off_amount):
                status = 'written_off'
            elif not currency.is_zero(claim.accepted_amount) \
                    and currency.compare_amounts(recovered, claim.accepted_amount) >= 0:
                status = 'recovered'
            elif not currency.is_zero(recovered):
                status = 'partial'
            else:
                status = 'pending'
            claim.update({
                'recovered_amount': recovered, 'settled_amount': settled,
                'outstanding_amount': max(claim.accepted_amount - recovered, 0.0)
                if claim.state != 'closed' else 0.0,
                'recovery_status': status,
            })

    @api.depends('recovery_ids.amount', 'recovery_ids.active', 'recovery_ids.move_id.state',
                 'recovery_ids.move_id.amount_untaxed_signed',
                 'recovery_ids.move_id.warranty_claim_recovery_ids.amount',
                 'recovery_ids.move_id.warranty_claim_recovery_ids.active',
                 'recovery_ids.move_id.reversal_move_ids.state',
                 'recovery_ids.move_id.reversal_move_ids.amount_total_signed')
    def _compute_allocation_info(self):
        for claim in self:
            allocations = claim.sudo().recovery_ids.filtered('active')
            claim.allocated_amount = sum(allocations.filtered(
                lambda rec: rec.move_id.state != 'cancel').mapped('net_allocated_amount'))
            claim.credit_note_count = len(allocations.move_id)

    @api.depends('line_ids.over_claimed')
    def _compute_over_claimed(self):
        for claim in self:
            claim.over_claimed = any(claim.line_ids.mapped('over_claimed'))

    @api.depends('line_ids.mrf_line_id', 'line_ids.lot_ids')
    def _compute_supplier_warranty(self):
        for claim in self:
            warnings = [line._warranty_supplier_warranty()[1] for line in claim.line_ids]
            claim.supplier_warranty_warning = '\n'.join(w for w in warnings if w) or False

    @api.depends_context('uid')
    @api.depends('state', 'finance_required', 'warranty_approved_by_id', 'finance_approved_by_id')
    def _compute_can_approve(self):
        for claim in self:
            claim.can_approve = claim.state == 'to_approve' and bool(claim._pending_levels_for())

    # ------------------------------------------------------------------ creation / protection
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                if (PROTECTED_FIELDS - {'company_id', 'case_id'}) & set(vals):
                    raise UserError(_("The status and approval fields of vendor claims are set "
                                      "by the claim workflow."))
        for vals in vals_list:
            company = self.env['res.company'].browse(vals.get('company_id')) or self.env.company
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'warranty.vendor.claim') or '/'
        claims = super().create(vals_list)
        if not self.env.su:
            claims._check_creator()
        claims._lock_and_check_lines()
        for claim in claims:
            claim._log_links(_("Vendor claim %(claim)s created for %(partner)s.",
                               claim=claim.name, partner=claim.partner_id.display_name))
        return claims

    def write(self, vals):
        if not self.env.su:
            keys = {key for key in vals if not key.startswith(FREE_PREFIXES)}
            if keys & PROTECTED_FIELDS:
                raise UserError(_("The status and approval fields of vendor claims are set by "
                                  "the claim workflow (%s).",
                                  ', '.join(sorted(keys & PROTECTED_FIELDS))))
            if keys - FREE_FIELDS:
                if self.filtered(lambda claim: claim.state != 'draft'):
                    raise UserError(_("Vendor claim %s can only be changed in Draft (reset it to "
                                      "Draft or record the vendor response).",
                                      self.filtered(lambda c: c.state != 'draft')[0].name))
                self._check_editor()
        result = super().write(vals)
        if 'partner_id' in vals:
            self._check_partner_override()
        if {'line_ids', 'partner_id'} & set(vals):
            self._lock_and_check_lines()
        return result

    def unlink(self):
        if self.filtered(lambda claim: claim.submitted_date or claim.state != 'draft'):
            raise UserError(_("Submitted vendor claims are never deleted; cancel them with a "
                              "reason."))
        return super().unlink()

    # ------------------------------------------------------------------ checks
    def _is_coordinator(self, user=None):
        user = user or self.env.user
        return user.has_group(GROUP_HELPDESK) or user.has_group(GROUP_REQUISITION)

    def _check_creator(self):
        for claim in self:
            if not self._is_coordinator() or claim.company_id not in self.env.user.company_ids:
                raise AccessError(_("Only Service Coordinators (Helpdesk users) and Requisition "
                                    "users of the company create vendor claims."))
            if not claim.company_id.warranty_vendor_claim_enabled:
                raise UserError(_("Vendor claims are not enabled for %s (Warranty Settings).",
                                  claim.company_id.name))
            if claim.sudo().case_id.company_id != claim.company_id:
                raise UserError(_("Vendor claim %s: the warranty case belongs to another company.",
                                  claim.name))

    def _check_editor(self):
        user = self.env.user
        for claim in self:
            if user != claim.user_id and user != claim.create_uid and not self._is_coordinator():
                raise AccessError(_("Only the responsible person or a Service Coordinator can "
                                    "change vendor claim %s.", claim.name))

    def _check_partner_override(self):
        """C2: a partner other than the proposal needs an auditable reason."""
        for claim in self:
            if claim.proposed_partner_id and claim.partner_id != claim.proposed_partner_id \
                    and not (claim.partner_override_reason or '').strip():
                raise UserError(_("Vendor claim %(claim)s: %(partner)s differs from the proposed "
                                  "partner %(proposed)s; enter the override reason.",
                                  claim=claim.name, partner=claim.partner_id.display_name,
                                  proposed=claim.proposed_partner_id.display_name))
            if claim.partner_id and claim.partner_id != claim.proposed_partner_id:
                claim.sudo().partner_source = 'manual'

    def _warranty_line_proposals(self):
        """C2: the (partner, source) of the lines that have a proposal."""
        self.ensure_one()
        proposals = [line._warranty_claim_partner_proposal() for line in self.line_ids]
        return [proposal for proposal in proposals if proposal[0]]

    @api.onchange('line_ids')
    def _onchange_line_ids_propose_partner(self):
        """A claim started with New: the proposal of the Create Vendor Claim wizard."""
        proposals = self._warranty_line_proposals()
        if self.proposed_partner_id or not proposals:
            return
        partner, source = proposals[0]
        self.update({'proposed_partner_id': partner.id, 'partner_source': source})
        if not self.partner_id:
            self.update({'partner_id': partner.id,
                         'claim_type': 'manufacturer' if source == 'manufacturer' else 'vendor'})

    def _check_manual_partner(self):
        """C2 for lines entered on the form: the rule of the Create Vendor Claim wizard. A partner
        other than the proposal needs an auditable reason."""
        for claim in self:
            proposals = claim._warranty_line_proposals()
            record = claim.sudo()
            if proposals and not claim.proposed_partner_id:
                record.write({'proposed_partner_id': proposals[0][0].id,
                              'partner_source': proposals[0][1]})
            if claim.partner_id != claim.proposed_partner_id:
                record.partner_source = 'manual'
            partners = {partner for partner, _source in proposals}
            if partners and (len(partners) > 1 or claim.partner_id not in partners) \
                    and not (claim.partner_override_reason or '').strip():
                raise UserError(_("The selected partner differs from the proposed responsible "
                                  "partner(s) %s; enter the override reason (audit).",
                                  ', '.join(sorted(p.display_name for p in partners))))

    def _lock_and_check_lines(self):
        """C1: MRF lines of active claims are locked (row update) so concurrent transactions
        claiming the same quantities are serialised, then the quantities are checked again."""
        lines = self.line_ids
        if not lines:
            return
        mrf_lines = lines.mrf_line_id
        self.env.flush_all()
        self.env.cr.execute("UPDATE material_purchase_requisition_line SET id = id "
                            "WHERE id IN %s", (tuple(mrf_lines.ids),))
        lines._check_line()

    def _check_lines_ready(self):
        for claim in self:
            if not claim.line_ids:
                raise UserError(_("Add the claimed parts to vendor claim %s.", claim.name))
            if claim.over_claimed:
                raise UserError(_("Vendor claim %s is over-claimed: the claimed quantity exceeds "
                                  "the consumed quantity (a consumption was reversed). Correct "
                                  "the claim first.", claim.name))
            if not (claim.failure_description or '').strip():
                raise UserError(_("Enter the failure description of vendor claim %s.",
                                  claim.name))
            for line in claim.line_ids:
                if line.product_id.tracking != 'none' and not line.lot_ids:
                    raise UserError(_("%(claim)s: select the serial / lot numbers of %(product)s.",
                                      claim=claim.name, product=line.product_id.display_name))
            claim._lock_and_check_lines()

    # ------------------------------------------------------------------ approval (V-8 / C3)
    def _approver_lists(self):
        company = self.company_id
        return {'warranty': company.warranty_claim_approver_ids,
                'finance': company.warranty_claim_finance_approver_ids}

    def _excluded_approvers(self):
        return self.create_uid | self.user_id | self.submitted_by_id

    def _required_levels(self):
        return ['warranty'] + (['finance'] if self.finance_required else [])

    def _pending_levels_for(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if user in self._excluded_approvers():
            return []
        decided = {'warranty': self.warranty_approved_by_id,
                   'finance': self.finance_approved_by_id}
        if user in decided.values():
            return []
        lists = self._approver_lists()
        return [level for level in self._required_levels()
                if not decided[level] and user in lists[level]
                and self.company_id in user.company_ids]

    def action_submit(self):
        for claim in self:
            if claim.state != 'draft':
                raise UserError(_("Only Draft claims can be submitted."))
            claim._check_editor()
            claim._check_lines_ready()
            company = claim.company_id
            threshold = company.warranty_claim_finance_threshold
            finance = claim.goodwill or (not company.currency_id.is_zero(threshold) and
                                         company.currency_id.compare_amounts(
                                             claim.claimed_amount, threshold) >= 0)
            excluded = claim.create_uid | claim.user_id | self.env.user
            lists = claim._approver_lists()
            levels = ['warranty'] + (['finance'] if finance else [])
            eligible = {level: lists[level].filtered(
                lambda user: user not in excluded and company in user.company_ids
                and not user.share and user.active) for level in levels}
            labels = {'warranty': _("Warranty"), 'finance': _("Finance")}
            for level in levels:
                if not eligible[level]:
                    raise UserError(_(
                        "Vendor claim %(claim)s needs a %(level)s approver: configure Vendor "
                        "Claim %(level)s Approvers (Warranty Settings); the requester, the "
                        "responsible person and the submitter cannot approve.",
                        claim=claim.name, level=labels[level]))
            if finance and len(eligible['warranty'] | eligible['finance']) < 2:
                raise UserError(_("Vendor claim %s needs two different approvers (Warranty and "
                                  "Finance).", claim.name))
            claim.sudo().write({
                'state': 'to_approve', 'submitted_by_id': self.env.uid,
                'submitted_date': fields.Datetime.now(), 'finance_required': finance,
                'warranty_approved_by_id': False, 'warranty_approved_date': False,
                'finance_approved_by_id': False, 'finance_approved_date': False,
                'approver_user_ids': [(6, 0, (eligible['warranty'] | eligible.get(
                    'finance', self.env['res.users'])).ids)],
            })
            claim._schedule_approvals()
            claim._log_links(_("Vendor claim %(claim)s submitted for approval (%(amount)s%(gw)s).",
                               claim=claim.name, amount=claim._money(claim.claimed_amount),
                               gw=_(", goodwill") if claim.goodwill else ''))
        return True

    def _schedule_approvals(self):
        record = self.sudo() if self.env.user.email else \
            self.sudo().with_context(mail_activity_quick_update=True)
        for user in self.approver_user_ids:
            record.activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                summary=_("Approve vendor claim %s", self.name),
                note=_("Claimed %(amount)s from %(partner)s.", amount=self._money(
                    self.claimed_amount), partner=self.partner_id.display_name))

    def _close_activities(self, feedback):
        activities = self.sudo().activity_ids.filtered(
            lambda act: act.activity_type_id == self.env.ref('mail.mail_activity_data_todo'))
        if activities:
            activities.action_feedback(feedback=feedback)

    def action_approve(self):
        for claim in self:
            if claim.state != 'to_approve':
                raise UserError(_("Vendor claim %s is not waiting for approval.", claim.name))
            levels = claim._pending_levels_for()
            if not levels:
                raise AccessError(_("You are not a pending approver of vendor claim %s (named "
                                    "approvers only; the requester, responsible person, "
                                    "submitter and an approver of the other level cannot "
                                    "approve).", claim.name))
            claim._lock_and_check_lines()
            if claim.over_claimed:
                raise UserError(_("Vendor claim %s is over-claimed; it cannot be approved.",
                                  claim.name))
            level = levels[0]
            now = fields.Datetime.now()
            claim.sudo().write({'%s_approved_by_id' % level: self.env.uid,
                                '%s_approved_date' % level: now})
            claim._log_links(_("Vendor claim %(claim)s: %(level)s approval by %(user)s.",
                               claim=claim.name, level=level.capitalize(),
                               user=self.env.user.name))
            if all(claim['%s_approved_by_id' % lvl] for lvl in claim._required_levels()):
                claim.sudo().write({'state': 'approved', 'approved_amount': claim.claimed_amount})
                claim._close_activities(_("Approved"))
                claim._log_links(_("Vendor claim %(claim)s approved (%(amount)s).",
                                   claim=claim.name, amount=claim._money(claim.claimed_amount)))
        return True

    def _warranty_reject(self, reason):
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to reject a vendor claim."))
        for claim in self:
            if claim.state != 'to_approve' or not claim._pending_levels_for():
                raise AccessError(_("Only a pending approver can reject vendor claim %s.",
                                    claim.name))
            claim.sudo().write({'state': 'draft', 'warranty_approved_by_id': False,
                                'finance_approved_by_id': False,
                                'warranty_approved_date': False, 'finance_approved_date': False})
            claim._close_activities(_("Rejected"))
            claim._log_links(_("Vendor claim %(claim)s rejected by %(user)s. Reason: %(reason)s",
                               claim=claim.name, user=self.env.user.name, reason=reason))

    def _warranty_reset_draft(self, reason):
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to reset a vendor claim to Draft."))
        for claim in self:
            if claim.state not in ('to_approve', 'approved'):
                raise UserError(_("Only claims waiting for approval or approved (not sent) can "
                                  "be reset to Draft."))
            claim._check_editor()
            claim.sudo().write({'state': 'draft', 'warranty_approved_by_id': False,
                                'finance_approved_by_id': False, 'approved_amount': 0.0,
                                'warranty_approved_date': False, 'finance_approved_date': False})
            claim._close_activities(_("Reset to Draft"))
            claim._log_links(_("Vendor claim %(claim)s reset to Draft by %(user)s (a new "
                               "approval follows). Reason: %(reason)s", claim=claim.name,
                               user=self.env.user.name, reason=reason))

    # ------------------------------------------------------------------ vendor (V-9 / V-11)
    def action_mark_sent(self):
        for claim in self:
            if claim.state != 'approved':
                raise UserError(_("Only approved claims can be sent to the vendor."))
            claim._check_editor()
            claim._check_lines_ready()
            if claim.company_id.warranty_claim_evidence_required and \
                    not self.env['ir.attachment'].sudo().search_count(
                        [('res_model', '=', claim._name), ('res_id', '=', claim.id)]):
                raise UserError(_("Attach the supporting evidence (failure report, photos, "
                                  "serial labels) to vendor claim %s before sending it.",
                                  claim.name))
            claim.sudo().write({'state': 'sent', 'sent_by_id': self.env.uid,
                                'sent_date': fields.Date.context_today(self)})
            claim._log_links(_("Vendor claim %(claim)s sent to %(partner)s.", claim=claim.name,
                               partner=claim.partner_id.display_name))
        return True

    def _can_record_response(self, user=None):
        user = user or self.env.user
        finance = user in self.company_id.warranty_claim_finance_approver_ids
        if self.state == 'sent':
            return finance or user in (self.user_id | self.create_uid) or self._is_coordinator(user)
        return self.state == 'answered' and finance

    def _warranty_record_response(self, values, reference=None, date=None, reason=None):
        """values: {claim line: (accepted amount, vendor reason)}. After a first response only
        Finance approvers change it, with a reason (V-11)."""
        self.ensure_one()
        claim = self
        if not claim._can_record_response():
            raise AccessError(_("You cannot record the vendor response of %s (after the first "
                                "response: Finance approvers only).", claim.name))
        if claim.over_claimed:
            raise UserError(_("Vendor claim %s is over-claimed; correct it first.", claim.name))
        correction = claim.state == 'answered'
        if correction and not (reason or '').strip():
            raise UserError(_("A reason is required to change a recorded vendor response."))
        currency = claim.currency_id
        for line, (amount, line_reason) in values.items():
            if line.claim_id != claim:
                raise UserError(_("The line does not belong to this claim."))
            if currency.compare_amounts(amount, 0.0) < 0 or \
                    currency.compare_amounts(amount, line.claimed_amount) > 0:
                raise UserError(_("%(product)s: the accepted amount must be between 0 and the "
                                  "claimed %(claimed)s.", product=line.product_id.display_name,
                                  claimed=claim._money(line.claimed_amount)))
        accepted = sum(amount for amount, _r in values.values()) + sum(
            (claim.line_ids - self.env['warranty.vendor.claim.line'].union(*values)).mapped(
                'accepted_amount'))
        if currency.compare_amounts(claim.allocated_amount, accepted) > 0:
            raise UserError(_("Credit notes of %(allocated)s are already allocated to %(claim)s; "
                              "the accepted amount cannot be lower (an accounting correction of "
                              "the credit notes comes first).", claim=claim.name,
                              allocated=claim._money(claim.allocated_amount)))
        for line, (amount, line_reason) in values.items():
            line.sudo().write({'accepted_amount': amount, 'vendor_reason': line_reason})
        claim.sudo().write({'state': 'answered', 'responded_by_id': self.env.uid,
                            'response_date': date or fields.Date.context_today(self),
                            'vendor_reference': reference or claim.vendor_reference})
        text = _("Vendor response for %(claim)s: %(result)s, accepted %(accepted)s of "
                 "%(claimed)s.", claim=claim.name,
                 result=dict(VENDOR_RESULTS).get(claim.vendor_result),
                 accepted=claim._money(claim.accepted_amount),
                 claimed=claim._money(claim.claimed_amount))
        if correction:
            text += ' ' + _("Correction by %(user)s. Reason: %(reason)s",
                            user=self.env.user.name, reason=reason)
        claim._log_links(text)

    # ------------------------------------------------------------------ recovery (V-12 - V-14)
    def _check_recovery_allowed(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP_BILLING):
            raise AccessError(_("Only Accounting (Billing) users record vendor credit notes."))
        if self.state != 'answered' or self.currency_id.is_zero(self.accepted_amount):
            raise UserError(_("Vendor claim %s has no accepted amount to recover (record the "
                              "vendor response first).", self.name))
        if self.over_claimed:
            raise UserError(_("Vendor claim %s is over-claimed (a consumption was reversed after "
                              "the claim). Correct the claim before recording recoveries.",
                              self.name))

    def _available_to_allocate(self):
        return self.accepted_amount - self.allocated_amount

    def action_create_credit_note(self):
        """V-12 / C5: a DRAFT vendor credit note of the accepted, not yet allocated amount on the
        company's Recovery Account (required, no fallback); never posted here."""
        self.ensure_one()
        claim = self
        claim._check_recovery_allowed()
        account = claim.company_id.warranty_claim_recovery_account_id
        if not account:
            raise UserError(_("Configure the Vendor Claim Recovery Account of %s (Warranty "
                              "Settings) before creating a vendor credit note.",
                              claim.company_id.name))
        amount = claim._available_to_allocate()
        if claim.currency_id.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_("The accepted amount of %s is already allocated to credit notes.",
                              claim.name))
        if claim.sudo().recovery_ids.filtered(
                lambda rec: rec.active and rec.move_id.state == 'draft'):
            raise UserError(_("Vendor claim %s already has a draft credit note; post or delete "
                              "it first.", claim.name))
        # Phase 5.9 (report B): one credit note line and one explicit allocation per claim line
        # (its accepted amount not yet allocated).
        remaining = [(line, line._available_to_allocate()) for line in claim.line_ids]
        remaining = [(line, rest) for line, rest in remaining
                     if claim.currency_id.compare_amounts(rest, 0.0) > 0]
        if claim.currency_id.compare_amounts(sum(rest for _line, rest in remaining), amount) > 0:
            raise UserError(_("Vendor claim %s has a claim-level credit note allocation without "
                              "claim line (made before 5.9); Accounting must correct it first.",
                              claim.name))
        lines = [(0, 0, {'product_id': line.product_id.id,
                         'name': '%s - %s' % (claim.name, line.product_id.display_name),
                         'quantity': 1, 'price_unit': rest,
                         'account_id': account.id, 'tax_ids': [(5, 0, 0)]})
                 for line, rest in remaining]
        move = self.env['account.move'].with_company(claim.company_id).create({
            'move_type': 'in_refund',
            'partner_id': claim.partner_id.id,
            'company_id': claim.company_id.id,
            'currency_id': claim.currency_id.id,
            'ref': '%s%s' % (claim.name, ' / %s' % claim.vendor_reference
                             if claim.vendor_reference else ''),
            'invoice_origin': claim.name,
            'invoice_line_ids': lines,
        })
        self.env['warranty.vendor.claim.recovery'].sudo().create([{
            'claim_id': claim.id, 'claim_line_id': line.id, 'move_id': move.id, 'amount': rest,
            'note': _("Draft credit note created from the claim."),
        } for line, rest in remaining])
        claim._log_links(_("Draft vendor credit note created for %(claim)s (%(amount)s); it "
                           "counts as recovered once Accounting posts it.", claim=claim.name,
                           amount=claim._money(amount)))
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id,
                'view_mode': 'form', 'views': [(False, 'form')]}

    def _warranty_allocate(self, move, amount, note=None, line=None):
        """Link a posted vendor credit note (or part of it) to a claim line (V-14 / C6; explicit
        line allocation since 5.9, the only line of a single-line claim by default)."""
        self.ensure_one()
        claim = self
        if not line:
            if len(claim.line_ids) != 1:
                raise UserError(_("Select the claim line the credit note amount recovers."))
            line = claim.line_ids
        if line.claim_id != claim:
            raise UserError(_("The line does not belong to this claim."))
        claim._check_recovery_allowed()
        move = move.sudo()
        currency = claim.currency_id
        if move.move_type != 'in_refund' or move.state != 'posted':
            raise UserError(_("Only posted vendor credit notes can be allocated."))
        if move.company_id != claim.company_id:
            raise UserError(_("The credit note belongs to another company."))
        if move.commercial_partner_id != claim.partner_id.commercial_partner_id:
            raise UserError(_("The credit note is not from %s.", claim.partner_id.display_name))
        if move.payment_state == 'reversed':
            raise UserError(_("The credit note is reversed."))
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_("Enter a positive amount."))
        if currency.compare_amounts(amount, move._warranty_claim_available()) > 0:
            raise UserError(_("Only %(available)s of credit note %(move)s are still available "
                              "for claims.", available=claim._money(
                                  move._warranty_claim_available()), move=move.name))
        if currency.compare_amounts(amount, claim._available_to_allocate()) > 0:
            raise UserError(_("Only %(available)s of the accepted amount of %(claim)s are not yet "
                              "recovered.", available=claim._money(
                                  claim._available_to_allocate()), claim=claim.name))
        if currency.compare_amounts(amount, line._available_to_allocate()) > 0:
            raise UserError(_("Only %(available)s of the accepted amount of %(product)s are not "
                              "yet recovered.", available=claim._money(
                                  line._available_to_allocate()),
                              product=line.product_id.display_name))
        recovery = self.env['warranty.vendor.claim.recovery'].sudo().create({
            'claim_id': claim.id, 'claim_line_id': line.id, 'move_id': move.id,
            'amount': amount, 'note': note})
        claim._log_links(_("Vendor credit note %(move)s allocated to %(claim)s: %(amount)s.",
                           move=move.name, claim=claim.name, amount=claim._money(amount)))
        return recovery

    def _warranty_close(self, reason=None):
        """Close: everything accepted is recovered, or the remainder is written off with a
        reason (operational only, no posting)."""
        self.ensure_one()
        claim = self
        if claim.state != 'answered':
            raise UserError(_("Only claims with a vendor response can be closed."))
        claim._check_editor()
        if claim.over_claimed:
            raise UserError(_("Vendor claim %s is over-claimed; it cannot be closed before it "
                              "is corrected.", claim.name))
        if claim.sudo().recovery_ids.filtered(
                lambda rec: rec.active and rec.move_id.state == 'draft'):
            raise UserError(_("A draft credit note of %s is still open; post or delete it "
                              "first.", claim.name))
        outstanding = claim.outstanding_amount
        reason = (reason or '').strip()
        if not claim.currency_id.is_zero(outstanding) and not reason:
            raise UserError(_("%(amount)s of %(claim)s are not recovered; enter the write-off "
                              "reason to close it.", amount=claim._money(outstanding),
                              claim=claim.name))
        claim.sudo().write({'state': 'closed', 'written_off_amount': outstanding,
                            'close_reason': reason or False, 'closed_by_id': self.env.uid,
                            'closed_date': fields.Datetime.now()})
        claim._log_links(_("Vendor claim %(claim)s closed (recovered %(recovered)s, written off "
                           "%(off)s)%(reason)s.", claim=claim.name,
                           recovered=claim._money(claim.recovered_amount),
                           off=claim._money(outstanding),
                           reason=(_(". Reason: %s", reason) if reason else '')))

    def _warranty_cancel(self, reason):
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to cancel a vendor claim."))
        for claim in self:
            if claim.state not in ('draft', 'to_approve', 'approved', 'sent', 'answered'):
                raise UserError(_("Vendor claim %s cannot be cancelled.", claim.name))
            claim._check_editor()
            if claim.sudo().recovery_ids.filtered(lambda rec: rec.active
                                           and rec.move_id.state != 'cancel'):
                raise UserError(_("Vendor claim %s has credit note allocations; Accounting must "
                                  "correct them first.", claim.name))
            claim.sudo().write({'state': 'cancel', 'cancel_reason': reason})
            claim._close_activities(_("Cancelled"))
            claim._log_links(_("Vendor claim %(claim)s cancelled by %(user)s. Reason: %(reason)s",
                               claim=claim.name, user=self.env.user.name, reason=reason))

    # ------------------------------------------------------------------ helpers
    def _money(self, amount):
        from odoo.tools import format_amount
        return format_amount(self.env, amount, self.currency_id)

    def _log_links(self, text):
        self.sudo()._message_log(body=text)
        for records in (self.sudo().case_id, self.sudo().job_ids, self.sudo().requisition_ids):
            for record in records:
                record._message_log(body=text)

    def _notify_over_claimed(self):
        """C7: reversal after claiming -> To-Do for the responsible person and Finance."""
        for claim in self.filtered(lambda c: c.over_claimed and c.state not in ('cancel',)):
            users = claim.user_id | claim.company_id.warranty_claim_finance_approver_ids
            record = claim.sudo().with_context(mail_activity_quick_update=True)
            for user in users:
                record.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=_("Vendor claim %s is over-claimed", claim.name),
                    note=_("A consumption was reversed after the claim; the claimed quantity "
                           "exceeds the consumed quantity. Correct the claim (vendor response / "
                           "accounting correction)."))
            claim._log_links(_("Vendor claim %s is over-claimed after a consumption reversal; "
                               "recovery and closure are blocked until it is corrected.",
                               claim.name))

    # ------------------------------------------------------------------ UI actions
    def _reason_wizard(self, action, title):
        return {'type': 'ir.actions.act_window', 'name': title,
                'res_model': 'warranty.vendor.claim.reason.wizard', 'view_mode': 'form',
                'target': 'new', 'context': {'default_claim_id': self.id,
                                             'default_action': action}}

    def action_open_reject(self):
        return self._reason_wizard('reject', _("Reject Vendor Claim"))

    def action_open_reset(self):
        return self._reason_wizard('reset', _("Reset Vendor Claim to Draft"))

    def action_open_cancel(self):
        return self._reason_wizard('cancel', _("Cancel Vendor Claim"))

    def action_open_close(self):
        return self._reason_wizard('close', _("Close Vendor Claim"))

    def action_open_response(self):
        self.ensure_one()
        wizard = self.env['warranty.vendor.claim.response.wizard'].create({
            'claim_id': self.id, 'vendor_reference': self.vendor_reference,
            'line_ids': [(0, 0, {'claim_line_id': line.id,
                                 'accepted_amount': line.accepted_amount
                                 if self.state == 'answered' else line.claimed_amount,
                                 'vendor_reason': line.vendor_reason})
                         for line in self.line_ids]})
        return {'type': 'ir.actions.act_window', 'name': _("Vendor Response"),
                'res_model': wizard._name, 'res_id': wizard.id, 'view_mode': 'form',
                'target': 'new'}

    def action_open_allocate(self):
        self.ensure_one()
        self._check_recovery_allowed()
        return {'type': 'ir.actions.act_window', 'name': _("Allocate Vendor Credit Note"),
                'res_model': 'warranty.vendor.claim.allocate.wizard', 'view_mode': 'form',
                'target': 'new', 'context': {'default_claim_id': self.id,
                                             'default_amount': self._available_to_allocate()}}

    def action_view_credit_notes(self):
        self.ensure_one()
        moves = self.sudo().recovery_ids.move_id
        return {'type': 'ir.actions.act_window', 'name': _("Vendor Credit Notes"),
                'res_model': 'account.move', 'view_mode': 'list,form',
                'domain': [('id', 'in', moves.ids)],
                'context': {'default_move_type': 'in_refund', 'create': False}}


class WarrantyVendorClaimLine(models.Model):
    _name = 'warranty.vendor.claim.line'
    _description = 'Warranty Vendor Claim Line'
    _order = 'claim_id, id'

    claim_id = fields.Many2one('warranty.vendor.claim', required=True, ondelete='cascade',
                               index=True)
    company_id = fields.Many2one(related='claim_id.company_id', store=True)
    currency_id = fields.Many2one(related='claim_id.currency_id')
    claim_state = fields.Selection(related='claim_id.state', store=True, string='Claim Status')
    mrf_line_id = fields.Many2one('material.purchase.requisition.line', string='Material Line',
                                  required=True, ondelete='restrict', index=True)
    requisition_id = fields.Many2one(related='mrf_line_id.requisition_id', store=True,
                                     string='Material Request')
    job_id = fields.Many2one(related='mrf_line_id.requisition_id.warranty_service_job_id',
                             store=True, string='Service Job')
    product_id = fields.Many2one(related='mrf_line_id.product_id', store=True)
    uom_id = fields.Many2one(related='mrf_line_id.uom', string='Unit')
    qty = fields.Float(string='Quantity', digits='Product Unit of Measure', required=True)
    tracking = fields.Selection(related='mrf_line_id.product_id.tracking')
    # Selection limited to the serials / lots consumed on the MRF line (5.6 Used entries, not
    # reversed) and, for serials, not on another active claim; checked again on the server.
    allowed_lot_ids = fields.Many2many('stock.lot', compute='_compute_allowed_lot_ids',
                                       compute_sudo=True)
    lot_ids = fields.Many2many('stock.lot', string='Serial / Lot Numbers',
                               domain="[('id', 'in', allowed_lot_ids)]")
    lot_names = fields.Char(string='Serial / Lot', compute='_compute_lot_names', compute_sudo=True)
    unit_cost = fields.Monetary(string='Actual Unit Cost', readonly=True,
                                help="Verified actual unit cost of the line (5.7) when claimed.")
    claimed_amount = fields.Monetary(string='Claimed')
    accepted_amount = fields.Monetary(string='Accepted', readonly=True)
    vendor_reason = fields.Text(string='Vendor Comment / Reason', readonly=True)
    goodwill = fields.Boolean(string='Goodwill', readonly=True)
    active_claim = fields.Boolean(compute='_compute_active_claim', store=True,
                                  help="Counts against the claimable quantity (not cancelled, "
                                       "not rejected by the vendor).")
    over_claimed = fields.Boolean(compute='_compute_over_claimed', store=True)
    supplier_warranty_info = fields.Char(string='Supplier Warranty',
                                         compute='_compute_supplier_info', compute_sudo=True)
    recovery_ids = fields.One2many('warranty.vendor.claim.recovery', 'claim_line_id',
                                   string='Credit Note Allocations')
    allocated_amount = fields.Monetary(string='Allocated', compute='_compute_line_recovery',
                                       compute_sudo=True)
    recovered_amount = fields.Monetary(string='Recovered', compute='_compute_line_recovery',
                                       compute_sudo=True)
    settled_amount = fields.Monetary(string='Settled', compute='_compute_line_recovery',
                                     compute_sudo=True)

    @api.depends('recovery_ids.amount', 'recovery_ids.active', 'recovery_ids.move_id.state',
                 'recovery_ids.move_id.payment_state', 'recovery_ids.move_id.amount_residual',
                 'recovery_ids.move_id.amount_untaxed_signed',
                 'recovery_ids.move_id.warranty_claim_recovery_ids.amount',
                 'recovery_ids.move_id.warranty_claim_recovery_ids.active',
                 'recovery_ids.move_id.reversal_move_ids.state',
                 'recovery_ids.move_id.reversal_move_ids.amount_total_signed')
    def _compute_line_recovery(self):
        for line in self:
            allocations = line.recovery_ids.filtered('active')
            line.allocated_amount = sum(allocations.filtered(
                lambda rec: rec.move_id.state != 'cancel').mapped('net_allocated_amount'))
            line.recovered_amount = sum(allocations.mapped('recovered_amount'))
            line.settled_amount = sum(allocations.mapped('settled_amount'))

    def _available_to_allocate(self):
        self.ensure_one()
        accepted = self.accepted_amount if self.claim_id.response_date else 0.0
        return accepted - self.allocated_amount

    @api.depends('mrf_line_id', 'claim_id.state')
    def _compute_allowed_lot_ids(self):
        for line in self:
            line.allowed_lot_ids = line.mrf_line_id._warranty_claimable_lots(exclude=line) \
                if line.mrf_line_id else False

    @api.depends('lot_ids')
    def _compute_lot_names(self):
        for line in self:
            line.lot_names = ', '.join(line.lot_ids.mapped('name')) or False

    @api.depends('claim_id.state', 'claim_id.response_date', 'accepted_amount')
    def _compute_active_claim(self):
        for line in self:
            rejected = line.claim_id.response_date and line.currency_id.is_zero(
                line.accepted_amount)
            line.active_claim = line.claim_id.state != 'cancel' and not rejected

    @api.depends('active_claim', 'mrf_line_id.vendor_claimed_qty', 'mrf_line_id.used_qty')
    def _compute_over_claimed(self):
        for line in self:
            mrf_line = line.mrf_line_id
            rounding = (mrf_line.uom or mrf_line.product_id.uom_id).rounding or 0.01
            line.over_claimed = line.active_claim and float_compare(
                mrf_line.vendor_claimed_qty, mrf_line.used_qty, precision_rounding=rounding) > 0

    @api.depends('mrf_line_id', 'lot_ids')
    def _compute_supplier_info(self):
        for line in self:
            line.supplier_warranty_info = line._warranty_supplier_warranty()[0] or False

    def _warranty_supplier_warranty(self):
        """C2: supplier warranty months of the product, reference date (lot purchase / MRF
        purchase order / lot receipt) and expiry warning at the consumption date."""
        self.ensure_one()
        line = self.sudo()
        months = line.product_id.product_tmpl_id.warranty_vendor_warranty_months
        if not months:
            return False, False
        reference = False
        orders = line.lot_ids.purchase_order_ids or \
            line.mrf_line_id.warranty_purchase_line_ids.order_id
        if orders:
            reference = min(fields.Date.to_date(order.date_approve or order.date_order)
                            for order in orders)
        elif line.lot_ids:
            reference = min(fields.Date.to_date(lot.create_date) for lot in line.lot_ids)
        if not reference:
            return _("%s months (purchase date unknown – approver to confirm)", months), \
                _("%s: supplier warranty cannot be verified (purchase date unknown).",
                  line.product_id.display_name)
        expiry = reference + relativedelta(months=months)
        used = line.mrf_line_id.warranty_consumption_ids.filtered(
            lambda entry: entry.kind == 'used' and entry.state == 'done')
        used_date = max(fields.Date.to_date(entry.date) for entry in used) if used else \
            fields.Date.context_today(self)
        info = _("%(months)s months from %(ref)s, expires %(expiry)s", months=months,
                 ref=reference, expiry=expiry)
        if used_date > expiry:
            return info, _("%(product)s: supplier warranty expired on %(expiry)s (used "
                           "%(used)s).", product=line.product_id.display_name, expiry=expiry,
                           used=used_date)
        return info, False

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.su:
            if lines.claim_id.filtered(lambda claim: claim.state != 'draft'):
                raise UserError(_("Claim lines can only be added in Draft."))
            lines.claim_id._check_editor()
        lines._set_cost_basis()
        lines.claim_id._lock_and_check_lines()
        if not self.env.su:
            lines.claim_id._check_manual_partner()
        return lines

    @api.onchange('mrf_line_id')
    def _onchange_mrf_line_id(self):
        if self.mrf_line_id:
            self.qty = self.mrf_line_id._warranty_claimable_qty()

    def _warranty_claim_partner_proposal(self):
        self.ensure_one()
        if self.mrf_line_id:
            return self.mrf_line_id._warranty_claim_partner_proposal()
        return self.env['res.partner'], False

    def write(self, vals):
        if not self.env.su:
            if set(vals) & {'accepted_amount', 'vendor_reason', 'unit_cost', 'goodwill',
                            'mrf_line_id'}:
                raise UserError(_("Accepted amounts, cost basis and links of claim lines are "
                                  "set by the claim workflow."))
            if self.claim_id.filtered(lambda claim: claim.state != 'draft'):
                raise UserError(_("Claim lines can only be changed in Draft."))
            self.claim_id._check_editor()
        result = super().write(vals)
        if 'qty' in vals and 'claimed_amount' not in vals:
            for line in self:
                line.sudo().claimed_amount = line.claim_id.currency_id.round(
                    line.qty * line.unit_cost)
        if {'qty', 'claimed_amount', 'lot_ids'} & set(vals) \
                and not self.env.context.get('warranty_claim_no_check'):
            self.claim_id._lock_and_check_lines()
        return result

    def unlink(self):
        if not self.env.su and self.claim_id.filtered(lambda claim: claim.state != 'draft'):
            raise UserError(_("Claim lines can only be removed in Draft."))
        return super().unlink()

    def _set_cost_basis(self):
        for line in self:
            mrf_line = line.mrf_line_id.sudo()
            unit = mrf_line.actual_cost / mrf_line.used_qty if mrf_line.used_qty else 0.0
            vals = {'unit_cost': unit, 'goodwill': mrf_line.cost_bucket == 'goodwill'}
            if not line.claimed_amount:
                vals['claimed_amount'] = line.claim_id.currency_id.round(line.qty * unit)
            line.sudo().with_context(warranty_claim_no_check=True).write(vals)

    def _check_line(self):
        """V-1 / V-5 / V-6 / V-7 / C1 eligibility, quantity, amount, serial and duplicate checks
        (server side, also in superuser mode)."""
        for line in self.filtered('active_claim'):
            claim = line.claim_id
            mrf_line = line.mrf_line_id.sudo()
            mrf = mrf_line.requisition_id
            product = mrf_line.product_id.display_name
            if claim.state in ('cancel', 'closed', 'answered', 'sent'):
                continue
            problem = mrf_line._warranty_claim_problem()
            if problem:
                raise UserError(_("%(claim)s / %(product)s: %(problem)s", claim=claim.name,
                                  product=product, problem=problem))
            if mrf.warranty_case_id != claim.case_id or mrf.company_id != claim.company_id:
                raise UserError(_("%(product)s: the material request belongs to another warranty "
                                  "case or company.", product=product))
            uom = mrf_line.uom or mrf_line.product_id.uom_id
            rounding = uom.rounding or 0.01
            if float_compare(line.qty, 0.0, precision_rounding=rounding) <= 0:
                raise UserError(_("%s: enter a positive quantity.", product))
            others = mrf_line.vendor_claim_line_ids.filtered(
                lambda other: other.active_claim and other != line)
            available = mrf_line.used_qty - sum(others.mapped('qty'))
            if float_compare(line.qty, available, precision_rounding=rounding) > 0:
                raise UserError(_("%(product)s (%(mrf)s): only %(available)s %(uom)s consumed and "
                                  "not yet on another active claim (entered %(qty)s).",
                                  product=product, mrf=mrf.name, available=max(available, 0.0),
                                  uom=uom.name, qty=line.qty))
            currency = claim.currency_id
            limit = currency.round(line.qty * line.unit_cost)
            if currency.compare_amounts(line.claimed_amount, 0.0) <= 0 or \
                    currency.compare_amounts(line.claimed_amount, limit) > 0:
                raise UserError(_("%(product)s: the claimed amount must be positive and not above "
                                  "the verified actual cost %(limit)s of the claimed quantity.",
                                  product=product, limit=claim._money(limit)))
            if line.lot_ids and mrf_line.product_id.tracking == 'none':
                raise UserError(_("%s is not tracked by serial / lot numbers.", product))
            if line.lot_ids:
                used_lots = mrf_line._warranty_claimable_lots(exclude=line, claimed=False)
                if line.lot_ids - used_lots:
                    raise UserError(_("%(product)s: serial / lot numbers must be among the "
                                      "consumed ones of the line (%(lots)s).", product=product,
                                      lots=', '.join((line.lot_ids - used_lots).mapped('name'))))
                if mrf_line.product_id.tracking == 'serial' and float_compare(
                        line.qty, len(line.lot_ids), precision_rounding=rounding):
                    raise UserError(_("%s: one serial number per claimed unit.", product))
                taken = others.filtered(lambda other: other.lot_ids & line.lot_ids)
                if mrf_line.product_id.tracking == 'serial' and taken:
                    raise UserError(_("%(product)s: serial %(lot)s is already on vendor claim "
                                      "%(claim)s.", product=product,
                                      lot=', '.join((taken.lot_ids & line.lot_ids).mapped('name')),
                                      claim=taken[0].claim_id.name))


class WarrantyVendorClaimRecovery(models.Model):
    """Allocation of a vendor credit note (or part of it) to a claim (V-14 / C6). Removed only by
    Accounting users with a reason (archived, never deleted); the credit note itself is never
    changed here."""
    _name = 'warranty.vendor.claim.recovery'
    _description = 'Warranty Vendor Claim Recovery'
    _order = 'id desc'

    claim_id = fields.Many2one('warranty.vendor.claim', required=True, ondelete='cascade',
                               index=True)
    company_id = fields.Many2one(related='claim_id.company_id', store=True)
    currency_id = fields.Many2one(related='claim_id.currency_id')
    claim_line_id = fields.Many2one(
        'warranty.vendor.claim.line', string='Claim Line', index=True, ondelete='restrict',
        help="Claim line recovered by this amount (explicit allocation). Empty only for "
             "claim-level allocations made before 5.9 on claims with several lines.")
    move_id = fields.Many2one('account.move', string='Vendor Credit Note', required=True,
                              ondelete='restrict', index=True)
    move_state = fields.Selection(related='move_id.state', string='Credit Note Status')
    payment_state = fields.Selection(related='move_id.payment_state')
    amount = fields.Monetary(string='Allocated Amount', required=True)
    recovered_amount = fields.Monetary(compute='_compute_effect', string='Recovered')
    settled_amount = fields.Monetary(compute='_compute_effect', string='Settled')
    net_allocated_amount = fields.Monetary(
        compute='_compute_effect', string='Allocated (Net of Reversals)',
        help="The amount a posted reversal of the credit note has given back can be claimed again.")
    active = fields.Boolean(default=True)
    user_id = fields.Many2one('res.users', string='Recorded By', default=lambda s: s.env.user,
                              readonly=True)
    date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    note = fields.Text()
    removed_by_id = fields.Many2one('res.users', readonly=True)
    removed_reason = fields.Text(readonly=True)

    def init(self):
        # Phase 5.9: the Warranty Material Cost view reads the claim line of the allocations.
        self.env['warranty.mrf.cost.report'].init()

    @api.depends('amount', 'active', 'move_id.state', 'move_id.payment_state',
                 'move_id.amount_residual', 'move_id.amount_untaxed_signed',
                 'move_id.warranty_claim_recovery_ids.amount',
                 'move_id.warranty_claim_recovery_ids.active',
                 'move_id.reversal_move_ids.state',
                 'move_id.reversal_move_ids.amount_total_signed',
                 'move_id.reversal_move_ids.reversal_move_ids.state')
    def _compute_effect(self):
        for rec in self:
            move = rec.move_id.sudo()
            counted = rec.active and move.state == 'posted' and move.payment_state != 'reversed'
            reversed_ratio = move._warranty_reversed_ratio()
            eligible = rec._warranty_recovery_eligible_amount()
            given_back = rec.currency_id.round(eligible * reversed_ratio)
            rec.net_allocated_amount = eligible - given_back
            rec.recovered_amount = eligible - given_back if counted else 0.0
            total = abs(move.amount_total_signed)
            ratio = 0.0
            if counted and total:
                # A reversal also reconciles the note: that part is not a settled recovery.
                ratio = min(1.0 - abs(move.amount_residual_signed) / total, 1.0) - reversed_ratio
            rec.settled_amount = rec.currency_id.round(eligible * max(ratio, 0.0))

    def _warranty_recovery_eligible_amount(self):
        """F6-A: what this allocation can recognise from its credit note. Once posted, it is the
        allocation, or its share of the note's actual untaxed amount if that is lower. A draft note
        still holds its whole allocation, so the amount can't be claimed a second time."""
        self.ensure_one()
        move = self.move_id.sudo()
        if move.state != 'posted':
            return self.amount
        allocated = sum(move.warranty_claim_recovery_ids.filtered('active').mapped('amount'))
        posted = abs(move.amount_untaxed_signed)
        if not self.active or not allocated or allocated <= posted:
            return self.amount
        return self.currency_id.round(self.amount * posted / allocated)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Credit notes are allocated with Allocate Credit Note on the claim."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise UserError(_("Allocations are changed by Accounting with Remove Allocation."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise UserError(_("Allocations are never deleted; use Remove Allocation."))
        return super().unlink()

    def action_open_remove(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _("Remove Credit Note Allocation"),
                'res_model': 'warranty.vendor.claim.reason.wizard', 'view_mode': 'form',
                'target': 'new', 'context': {'default_claim_id': self.claim_id.id,
                                             'default_recovery_id': self.id,
                                             'default_action': 'remove'}}

    def _warranty_remove(self, reason):
        """C7: accounting correction of an allocation (archived with a reason)."""
        reason = (reason or '').strip()
        if not self.env.user.has_group(GROUP_BILLING):
            raise AccessError(_("Only Accounting (Billing) users correct credit note "
                                "allocations."))
        if not reason:
            raise UserError(_("A reason is required to remove a credit note allocation."))
        for rec in self:
            if rec.claim_id.state == 'closed':
                raise UserError(_("Vendor claim %s is closed.", rec.claim_id.name))
            rec.sudo().write({'active': False, 'removed_by_id': self.env.uid,
                              'removed_reason': reason})
            rec.claim_id._log_links(_("Allocation of %(move)s (%(amount)s) removed from %(claim)s "
                                      "by %(user)s. Reason: %(reason)s", move=rec.move_id.name,
                                      amount=rec.claim_id._money(rec.amount),
                                      claim=rec.claim_id.name, user=self.env.user.name,
                                      reason=reason))


class AccountMove(models.Model):
    _inherit = 'account.move'

    warranty_claim_recovery_ids = fields.One2many('warranty.vendor.claim.recovery', 'move_id',
                                                  string='Warranty Claim Allocations')
    warranty_vendor_claim_count = fields.Integer(compute='_compute_warranty_vendor_claims')

    def _compute_warranty_vendor_claims(self):
        for move in self:
            move.warranty_vendor_claim_count = len(
                move.sudo().warranty_claim_recovery_ids.filtered('active').claim_id)

    def _warranty_claim_available(self):
        """Untaxed company-currency amount of the credit note not reversed and not yet allocated
        to claims."""
        self.ensure_one()
        allocated = sum(self.sudo().warranty_claim_recovery_ids.filtered('active').mapped(
            'net_allocated_amount'))
        return abs(self.amount_untaxed_signed) * (1.0 - self._warranty_reversed_ratio()) - allocated

    def _warranty_reversed_amount(self):
        """Amount given back by posted reversals linked to this move (`reversed_entry_id`), not
        by its payment state: a vendor bill that offsets the note is a settlement, not a reversal.
        A reversal that was itself reversed gives nothing back."""
        self.ensure_one()
        move = self.sudo()
        return sum(max(abs(reversal.amount_total_signed) - reversal._warranty_reversed_amount(), 0.0)
                   for reversal in move.reversal_move_ids.filtered(
                       lambda reversal: reversal.state == 'posted'))

    def _warranty_reversed_ratio(self):
        """The reversed share of this move, 0 to 1."""
        self.ensure_one()
        total = abs(self.sudo().amount_total_signed)
        return min(self._warranty_reversed_amount() / total, 1.0) if total else 0.0

    def unlink(self):
        allocations = self.sudo().with_context(active_test=False).warranty_claim_recovery_ids
        for rec in allocations:
            rec.claim_id._log_links(_("Draft credit note %(move)s of %(claim)s deleted by "
                                      "%(user)s.", move=rec.move_id.display_name,
                                      claim=rec.claim_id.name, user=self.env.user.name))
        allocations.with_context(active_test=False).sudo().unlink()
        return super().unlink()

    def action_view_warranty_vendor_claims(self):
        claims = self.sudo().warranty_claim_recovery_ids.filtered('active').claim_id
        return {'type': 'ir.actions.act_window', 'name': _("Warranty Vendor Claims"),
                'res_model': 'warranty.vendor.claim', 'view_mode': 'list,form',
                'domain': [('id', 'in', claims.ids)], 'context': {'create': False}}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    warranty_vendor_claimable = fields.Boolean(
        string='Vendor Claimable', help="Warranty consumption of this part may be claimed from "
                                        "the supplier / manufacturer (SRS 12 #15 claimable parts).")
    warranty_claim_partner_id = fields.Many2one(
        'res.partner', string='Warranty Claim Partner',
        help="Manufacturer / supplier responsible for warranty claims of this part (used when the "
             "supplying vendor cannot be identified).")
    warranty_vendor_warranty_months = fields.Integer(
        string='Vendor Warranty (months)',
        help="Supplier / manufacturer warranty period; shown to claim approvers with an expiry "
             "warning.")


class ResCompany(models.Model):
    _inherit = 'res.company'

    warranty_vendor_claim_enabled = fields.Boolean(string='Vendor Claims')
    warranty_claim_approver_ids = fields.Many2many(
        'res.users', 'warranty_claim_approver_company_rel', 'company_id', 'user_id',
        string='Vendor Claim Warranty Approvers', domain=[('share', '=', False)])
    warranty_claim_finance_approver_ids = fields.Many2many(
        'res.users', 'warranty_claim_finance_company_rel', 'company_id', 'user_id',
        string='Vendor Claim Finance Approvers', domain=[('share', '=', False)])
    warranty_claim_finance_threshold = fields.Monetary(
        string='Finance Approval Threshold', currency_field='currency_id',
        help="Claims of this amount or more (and every goodwill claim) also need a Finance "
             "approver; 0 = Warranty approval only (goodwill claims always need Finance).")
    warranty_claim_evidence_required = fields.Boolean(string='Claim Evidence Required',
                                                      default=True)
    warranty_claim_recovery_account_id = fields.Many2one(
        'account.account', string='Vendor Claim Recovery Account',
        help="Account of the draft vendor credit notes created from claims (required).")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_vendor_claim_enabled = fields.Boolean(
        related='company_id.warranty_vendor_claim_enabled', readonly=False,
        help="If enabled, the cost of eligible warranty parts can be claimed back from "
             "suppliers or manufacturers. If disabled, vendor claims cannot be created.")
    warranty_claim_approver_ids = fields.Many2many(
        related='company_id.warranty_claim_approver_ids', readonly=False,
        help="Users who approve every vendor claim. They cannot approve a claim they created "
             "or are responsible for.")
    warranty_claim_finance_approver_ids = fields.Many2many(
        related='company_id.warranty_claim_finance_approver_ids', readonly=False,
        help="Users who also approve claims at or above the Finance Approval Threshold, and "
             "every goodwill claim.")
    warranty_claim_finance_threshold = fields.Monetary(
        related='company_id.warranty_claim_finance_threshold', readonly=False,
        help="Claims of this amount or more also need Finance approval. 0 means that only "
             "goodwill claims need Finance approval.")
    warranty_claim_evidence_required = fields.Boolean(
        related='company_id.warranty_claim_evidence_required', readonly=False,
        help="If enabled, a vendor claim needs at least one attachment before it is sent to "
             "the vendor. If disabled, attachments are optional.")
    warranty_claim_recovery_account_id = fields.Many2one(
        related='company_id.warranty_claim_recovery_account_id', readonly=False,
        domain="[('company_ids', 'in', company_id)]",
        help="The account used on the vendor credit notes created from claims. It must be "
             "set before a credit note can be created.")


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    vendor_claim_line_ids = fields.One2many('warranty.vendor.claim.line', 'mrf_line_id',
                                            string='Vendor Claim Lines', groups=COST_GROUPS)
    vendor_claimed_qty = fields.Float(string='Claimed Qty', compute='_compute_vendor_claimed',
                                      store=True, digits='Product Unit of Measure',
                                      groups=COST_GROUPS)

    @api.depends('vendor_claim_line_ids.qty', 'vendor_claim_line_ids.active_claim')
    def _compute_vendor_claimed(self):
        for line in self:
            line.vendor_claimed_qty = sum(line.sudo().vendor_claim_line_ids.filtered(
                'active_claim').mapped('qty'))

    def _warranty_claimable_qty(self):
        self.ensure_one()
        return max(self.sudo().used_qty - self.sudo().vendor_claimed_qty, 0.0)

    def _warranty_claim_problem(self):
        """V-1 / C1: why the line cannot be claimed (False = eligible)."""
        self.ensure_one()
        line = self.sudo()
        mrf = line.requisition_id
        if not mrf.is_warranty_mrf or mrf.state in ('cancel', 'reject'):
            return _("not an active warranty material request")
        if not mrf.company_id.warranty_vendor_claim_enabled:
            return _("vendor claims are not enabled for the company")
        if line.cost_bucket not in WARRANTY_BUCKETS:
            return _("only Covered or Goodwill parts can be claimed (customer-paid or "
                     "unclassified parts are not claimable)")
        if not line.product_id.product_tmpl_id.warranty_vendor_claimable:
            return _("the product is not marked Vendor Claimable")
        if line.cost_status != 'verified' or not line.currency_id.is_zero(
                line.actual_unverified_cost) or line.currency_id.compare_amounts(
                line.actual_cost, 0.0) <= 0:
            return _("no verified actual cost (stock valuation) for the consumed quantity")
        if float_is_zero(line.used_qty, precision_rounding=(line.uom or line.product_id.uom_id)
                         .rounding or 0.01):
            return _("nothing consumed")
        return False

    def _warranty_claimable_lots(self, exclude=None, claimed=True):
        """Serials / lots consumed on this line (Used entries not reversed; issued, returned or
        unused ones are not consumed); claimed=True also removes serials already on another
        active claim line (all but `exclude`)."""
        self.ensure_one()
        line = self.sudo()
        lots = line.warranty_consumption_ids.filtered(
            lambda entry: entry.kind == 'used' and entry.state == 'done').lot_ids \
            .filtered(lambda lot: lot.product_id == line.product_id)
        if claimed and line.product_id.tracking == 'serial':
            others = line.vendor_claim_line_ids.filtered(
                lambda other: other.active_claim and other not in (exclude or []))
            lots -= others.lot_ids
        return lots

    def _warranty_claim_partner_proposal(self):
        """C2: (partner, source): the supplying vendor (lot purchase order, else the line's
        purchase order), else the product's Warranty Claim Partner, else its vendor list."""
        self.ensure_one()
        line = self.sudo()
        used_lots = line.warranty_consumption_ids.filtered(
            lambda entry: entry.kind == 'used' and entry.state == 'done').lot_ids
        orders = used_lots.purchase_order_ids.filtered(lambda o: o.state in ('purchase', 'done'))
        if not orders:
            orders = line.warranty_purchase_line_ids.order_id.filtered(
                lambda o: o.state in ('purchase', 'done'))
        if orders:
            return orders.sorted('id')[0].partner_id, 'supplier'
        template = line.product_id.product_tmpl_id
        if template.warranty_claim_partner_id:
            return template.warranty_claim_partner_id, 'manufacturer'
        sellers = line.product_id.seller_ids.filtered(lambda s: s.company_id in (
            line.requisition_id.company_id, self.env['res.company']))
        if sellers:
            return sellers[0].partner_id, 'pricelist'
        return self.env['res.partner'], False


class WarrantyMrfConsumption(models.Model):
    _inherit = 'warranty.mrf.consumption'

    def _warranty_reverse(self, reason):
        result = super()._warranty_reverse(reason)
        # C7: claims of the line may now exceed the consumed quantity.
        claims = self.sudo().line_id.vendor_claim_line_ids.claim_id
        claims.invalidate_recordset(['over_claimed'])
        claims._notify_over_claimed()
        return result


class CostTotalsMixin(models.AbstractModel):
    """V-17: claims and recovery figures of a case, job or request (cost groups), added to
    the 5.7 cost totals of the same records."""
    _inherit = 'warranty.mrf.cost.totals.mixin'

    vendor_claim_count = fields.Integer(compute='_compute_vendor_claim_figures',
                                        groups=COST_GROUPS)
    vendor_claimed_amount = fields.Monetary(
        string='Vendor Claimed', compute='_compute_vendor_claim_figures',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    vendor_accepted_amount = fields.Monetary(
        string='Vendor Accepted', compute='_compute_vendor_claim_figures',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    vendor_recovered_amount = fields.Monetary(
        string='Vendor Recovered', compute='_compute_vendor_claim_figures',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    vendor_settled_amount = fields.Monetary(
        string='Vendor Settled', compute='_compute_vendor_claim_figures',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    vendor_outstanding_amount = fields.Monetary(
        string='Vendor Outstanding', compute='_compute_vendor_claim_figures',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    vendor_recovery_status = fields.Selection(
        CASE_RECOVERY_STATUSES, string='Vendor Recovery', compute='_compute_vendor_claim_figures',
        groups=COST_GROUPS)
    net_warranty_material_cost = fields.Monetary(
        string='Net Warranty Material Cost after Recovery',
        compute='_compute_vendor_claim_figures', currency_field='cost_currency_id',
        groups=COST_GROUPS)

    def _warranty_vendor_claims(self):
        raise NotImplementedError

    def _warranty_vendor_claim_line_scope(self):
        """Claim lines whose figures belong to this record (request / job: only the lines of its
        own material lines, so a claim over several jobs is never counted twice); False = whole
        claims (warranty case: every claim belongs to one case)."""
        return False

    def _compute_vendor_claim_figures(self):
        for record in self:
            scope = record._warranty_vendor_claim_line_scope()
            if scope is False:
                claims = record._warranty_vendor_claims().filtered(lambda c: c.state != 'cancel')
                accepted = sum(claims.mapped('accepted_amount'))
                recovered = sum(claims.mapped('recovered_amount'))
                claimed = sum(claims.mapped('claimed_amount'))
                settled = sum(claims.mapped('settled_amount'))
                outstanding = sum(claims.mapped('outstanding_amount'))
            else:
                lines = scope.filtered(lambda line: line.claim_id.state != 'cancel')
                claims = lines.claim_id
                answered = lines.filtered(lambda line: line.claim_id.response_date)
                accepted = sum(answered.mapped('accepted_amount'))
                recovered = sum(lines.mapped('recovered_amount'))
                claimed = sum(lines.mapped('claimed_amount'))
                settled = sum(lines.mapped('settled_amount'))
                outstanding = sum(max(line.accepted_amount - line.recovered_amount, 0.0)
                                  for line in answered if line.claim_id.state != 'closed')
            currency = record.sudo().company_id.currency_id
            if not claims:
                status = 'none'
            elif not currency.is_zero(accepted) and \
                    currency.compare_amounts(recovered, accepted) >= 0:
                status = 'recovered'
            elif not currency.is_zero(recovered):
                status = 'partial'
            elif all(claim.vendor_result == 'rejected' for claim in claims):
                status = 'rejected'
            else:
                status = 'claimed'
            record.update({
                'vendor_claim_count': len(claims),
                'vendor_claimed_amount': claimed,
                'vendor_accepted_amount': accepted,
                'vendor_recovered_amount': recovered,
                'vendor_settled_amount': settled,
                'vendor_outstanding_amount': outstanding,
                'vendor_recovery_status': status,
                'net_warranty_material_cost': record.warranty_material_cost - recovered,
            })

    def action_view_vendor_claims(self):
        self.ensure_one()
        claims = self._warranty_vendor_claims()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_mrf.action_warranty_vendor_claim')
        action['domain'] = [('id', 'in', claims.ids)]
        action['context'] = {'create': False}
        return action

    def action_create_vendor_claim(self):
        self.ensure_one()
        lines = self._warranty_claim_candidate_lines()
        if not lines:
            raise UserError(_("No consumed Covered / Goodwill part of a Vendor Claimable product "
                              "with verified actual cost and unclaimed quantity."))
        wizard = self.env['warranty.vendor.claim.wizard'].create({
            'case_id': lines.requisition_id.warranty_case_id[:1].id,
            'line_ids': [(0, 0, {'mrf_line_id': line.id, 'selected': True,
                                 'qty': line._warranty_claimable_qty()}) for line in lines]})
        wizard._propose_partner()
        return {'type': 'ir.actions.act_window', 'name': _("Create Vendor Claim"),
                'res_model': wizard._name, 'res_id': wizard.id, 'view_mode': 'form',
                'target': 'new'}

    def _warranty_claim_candidate_lines(self):
        lines = self._warranty_cost_lines().sudo()
        return lines.filtered(lambda line: not line._warranty_claim_problem()
                              and line._warranty_claimable_qty() > 0)


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    # Display only: the button follows the check of action_create_vendor_claim.
    can_warranty_vendor_claim = fields.Boolean(compute='_compute_can_warranty_vendor_claim')

    @api.depends('state', 'requisition_line_ids.used_qty')
    def _compute_can_warranty_vendor_claim(self):
        for mrf in self:
            mrf.can_warranty_vendor_claim = mrf.is_warranty_mrf \
                and bool(mrf._warranty_claim_candidate_lines())

    def _warranty_vendor_claims(self):
        return self.sudo().requisition_line_ids.vendor_claim_line_ids.claim_id

    def _warranty_vendor_claim_line_scope(self):
        return self.sudo().requisition_line_ids.vendor_claim_line_ids


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    def _warranty_vendor_claims(self):
        return self.env['warranty.vendor.claim'].sudo().search([('job_ids', 'in', self.ids)])

    def _warranty_vendor_claim_line_scope(self):
        return self.sudo().material_request_ids.requisition_line_ids.vendor_claim_line_ids


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    def _warranty_vendor_claims(self):
        return self.env['warranty.vendor.claim'].sudo().search([('case_id', 'in', self.ids)])
