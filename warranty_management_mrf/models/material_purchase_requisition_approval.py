from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .warranty_mrf_approval_rule import APPROVAL_LEVELS

# Phase 5.3 (design rev. 2). Vendor states: dept_confirm = Manager Approval, ir_approve =
# Finance/GM Approval, approve = Approved (D3).
WARRANTY_MRF_STATUSES = [
    ('draft', 'Draft'),
    ('manager', 'Manager Approval'),
    ('finance_gm', 'Finance/GM Approval'),
    ('approved', 'Approved'),
    ('released', 'Picking / PO Created'),
    ('received', 'Received'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
]
STATUS_BY_STATE = {
    'draft': 'draft', 'dept_confirm': 'manager', 'ir_approve': 'finance_gm', 'approve': 'approved',
    'stock': 'released', 'receive': 'received', 'reject': 'rejected', 'cancel': 'cancelled',
}
APPROVAL_STATUSES = [
    ('draft', 'Draft'),
    ('submitted', 'Submitted'),
    ('manager_approved', 'Manager Approved'),
    ('finance_approved', 'Finance Approved'),
    ('gm_approved', 'GM Approved'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]
APPROVAL_MODES = [
    ('matrix', 'Approval Matrix'),
    ('vendor', 'Requisition Workflow'),
]
WAITING_STATES = ('dept_confirm', 'ir_approve')
RELEASED_STATES = ('approve', 'stock', 'receive')
STAGE_LEVELS = {'dept_confirm': ('manager',), 'ir_approve': ('finance', 'gm')}
DONE_LINE_STATES = ('approved', 'skipped')
# Written by the approval workflow only (superuser mode after the bridge checks).
PROTECTED_FIELDS = {
    'state', 'approve_manager_id', 'reject_manager_id', 'approve_employee_id',
    'reject_employee_id', 'managerapp_date', 'manareject_date', 'userreject_date',
    'userrapp_date', 'employee_confirm_id', 'confirm_date', 'delivery_picking_id',
    'warranty_approval_mode', 'approval_round', 'warranty_approver_user_ids',
    'approval_routing_amount', 'approval_covered_amount', 'approval_not_covered_amount',
    'approval_goodwill_amount', 'approval_signature', 'submitted_by_id', 'submitted_date',
    'approved_by_id', 'approved_date', 'approved_amount', 'warranty_manager_user_id',
}
# Q4: Picking Details editable after submission by Requisition / Inventory users only.
PICKING_FIELDS = {'location_id', 'dest_location_id', 'custom_picking_type_id'}
PICKING_GROUPS = ('material_purchase_requisitions.group_purchase_requisition_user',
                  'stock.group_stock_user')
FREE_FIELD_PREFIXES = ('message_', 'activity_', 'website_message')
GROUP_DEPARTMENT = 'material_purchase_requisitions.group_purchase_requisition_department'
GROUP_REQUISITION = 'material_purchase_requisitions.group_purchase_requisition_user'
GROUP_REQUISITION_MANAGER = 'material_purchase_requisitions.group_purchase_requisition_manager'


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    warranty_approval_mode = fields.Selection(
        APPROVAL_MODES, string='Approval Mode', readonly=True, copy=False,
        help="Set at submission: the company's Material Approval Matrix, or the vendor "
             "Requisition workflow when the matrix is off.")
    approval_round = fields.Integer(string='Approval Round', readonly=True, copy=False)
    warranty_approval_ids = fields.One2many('warranty.mrf.approval', 'requisition_id',
                                            string='Approval History', readonly=True)
    warranty_approver_user_ids = fields.Many2many(
        'res.users', 'warranty_mrf_approver_user_rel', 'requisition_id', 'user_id',
        string='Named Approvers', readonly=True, copy=False,
        help="Approvers of all rounds (read access to the request).")
    routing_amount = fields.Monetary(
        string='Routing Amount', compute='_compute_routing_amount',
        help="All lines, each at the higher of its estimated cost and its product cost (D-A, D-F).")
    approval_routing_amount = fields.Monetary(string='Submitted Routing Amount', readonly=True,
                                              copy=False)
    approval_covered_amount = fields.Monetary(string='Submitted Covered', readonly=True,
                                              copy=False)
    approval_not_covered_amount = fields.Monetary(string='Submitted Not Covered', readonly=True,
                                                  copy=False)
    approval_goodwill_amount = fields.Monetary(string='Submitted Free of Charge', readonly=True,
                                               copy=False)
    approval_signature = fields.Char(readonly=True, copy=False)
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True,
                                      copy=False)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    warranty_manager_user_id = fields.Many2one(
        'res.users', string='Department / Manager Approval By', readonly=True, copy=False,
        help="User of the department / manager approval (the vendor field stores an employee).")
    approved_date = fields.Datetime(string='Approved On', readonly=True, copy=False)
    approved_amount = fields.Monetary(string='Approved Amount', readonly=True, copy=False)
    warranty_mrf_status = fields.Selection(
        WARRANTY_MRF_STATUSES, string='Warranty MRF Status', compute='_compute_warranty_mrf_status',
        store=True)
    approval_status = fields.Selection(APPROVAL_STATUSES, string='Approval Status',
                                       compute='_compute_approval_status')
    warranty_approval_legacy = fields.Boolean(compute='_compute_approval_status')
    can_warranty_approve = fields.Boolean(compute='_compute_can_warranty_actions')
    can_warranty_withdraw = fields.Boolean(compute='_compute_can_warranty_actions')
    # Requisition workflow (matrix off) of warranty requests: vendor buttons per user.
    can_warranty_vendor_manager_approve = fields.Boolean(
        compute='_compute_can_warranty_actions')
    can_warranty_vendor_user_approve = fields.Boolean(compute='_compute_can_warranty_actions')
    can_warranty_vendor_reject = fields.Boolean(compute='_compute_can_warranty_actions')

    @api.depends('requisition_line_ids.routing_cost')
    def _compute_routing_amount(self):
        for mrf in self:
            mrf.routing_amount = sum(mrf.requisition_line_ids.mapped('routing_cost'))

    @api.depends('state', 'is_warranty_mrf')
    def _compute_warranty_mrf_status(self):
        for mrf in self:
            mrf.warranty_mrf_status = STATUS_BY_STATE.get(mrf.state) if mrf.is_warranty_mrf \
                else False

    @api.depends('state', 'is_warranty_mrf', 'approval_round', 'warranty_approval_ids.state')
    def _compute_approval_status(self):
        for mrf in self:
            mrf.warranty_approval_legacy = mrf._warranty_is_legacy()
            if not mrf.is_warranty_mrf:
                mrf.approval_status = False
            elif mrf.state in ('draft', 'cancel'):
                mrf.approval_status = 'draft'
            elif mrf.state == 'reject':
                mrf.approval_status = 'rejected'
            elif mrf.state in RELEASED_STATES:
                mrf.approval_status = 'approved'
            else:
                approved = set(mrf._warranty_round_lines().filtered(
                    lambda line: line.state == 'approved').mapped('level'))
                mrf.approval_status = 'gm_approved' if 'gm' in approved else \
                    'finance_approved' if 'finance' in approved else \
                    'manager_approved' if 'manager' in approved else 'submitted'

    @api.depends_context('uid')
    @api.depends('state', 'warranty_approval_ids.state', 'warranty_approval_ids.allowed_user_ids',
                 'warranty_approval_mode', 'submitted_by_id', 'warranty_manager_user_id')
    def _compute_can_warranty_actions(self):
        for mrf in self:
            mrf.can_warranty_approve = bool(mrf._warranty_decidable_line()[0])
            mrf.can_warranty_withdraw = not mrf._warranty_withdraw_error()
            vendor = mrf.is_warranty_mrf and mrf.warranty_approval_mode == 'vendor'
            step_error = mrf._warranty_vendor_step_error
            mrf.can_warranty_vendor_manager_approve = vendor and not step_error(
                ('dept_confirm',), (GROUP_DEPARTMENT,))
            mrf.can_warranty_vendor_user_approve = vendor and not step_error(
                ('ir_approve',), (GROUP_REQUISITION,), check_manager=True)
            mrf.can_warranty_vendor_reject = vendor and not step_error(
                ('dept_confirm', 'ir_approve', 'approve'),
                (GROUP_DEPARTMENT, GROUP_REQUISITION, GROUP_REQUISITION_MANAGER))

    # ------------------------------------------------------------------ helpers
    def _warranty_is_legacy(self):
        """Submitted before the approval workflow (no valid round): never approved
        automatically, withdraw and submit again (additional requirement 9)."""
        self.ensure_one()
        return self.is_warranty_mrf and not self.approval_round \
            and self.state not in ('draft', 'cancel', 'reject')

    def _warranty_requester_user(self):
        # sudo: the requester's user is read for the checks only.
        return self.sudo().employee_id.user_id

    def _warranty_is_requester_or_creator(self, user=None):
        user = user or self.env.user
        return user == self.create_uid or user == self._warranty_requester_user()

    def _warranty_sod_users(self):
        """D-D: requester, creator and submitter never approve."""
        return self._warranty_requester_user() | self.create_uid | self.submitted_by_id

    def _warranty_round_lines(self):
        self.ensure_one()
        # sudo: the history is read by the workflow (users may have no read access to it).
        return self.sudo().warranty_approval_ids.filtered(
            lambda line: line.round == self.approval_round) if self.approval_round else \
            self.env['warranty.mrf.approval']

    def _warranty_routing_amounts(self):
        lines = self.requisition_line_ids

        def total(subset):
            return sum(subset.mapped('routing_cost'))
        return {
            'routing': total(lines),
            'covered': total(lines.filtered(lambda line: line.coverage_type == 'covered')),
            'not_covered': total(lines.filtered(lambda line: line.coverage_type == 'not_covered')),
            'goodwill': total(lines.filtered('goodwill')),
        }

    def _warranty_line_signature(self):
        self.ensure_one()
        return repr(sorted(
            (line.id, line.product_id.id, line.qty, line.uom.id, line.estimated_unit_cost,
             line.coverage_type or '', line.goodwill) for line in self.requisition_line_ids))

    def _warranty_log_links(self, text):
        for record in (self.warranty_case_id, self.warranty_service_job_id):
            if record:
                record.sudo()._message_log(body=_("Material Request %(mrf)s: %(text)s",
                                                  mrf=self.name, text=text))

    def _warranty_notify(self, text):
        """D-P: requester and submitter are notified (chatter, e-mail when configured)."""
        partners = (self._warranty_requester_user() | self.submitted_by_id).partner_id
        # sudo: approvers have read access only; the author stays the current user.
        self.sudo().message_post(body=text, partner_ids=partners.ids, message_type='comment',
                                 subtype_xmlid='mail.mt_comment')

    @staticmethod
    def _warranty_distinct_assignment(user_sets):
        """One person approves at most one level (D-D): a distinct approver must exist for
        every level."""
        def assign(index, used):
            if index == len(user_sets):
                return True
            return any(assign(index + 1, used | {user.id})
                       for user in user_sets[index] if user.id not in used)
        return assign(0, frozenset())

    # ------------------------------------------------------------------ route
    def _warranty_compute_route(self):
        """Design rev. 2, section 3.3: applicable rules (company and its parents), matching
        rules, strictest combination, goodwill Finance + GM, available approvers. Every
        problem of the route is reported with its level, rules and approvers."""
        analysis = self._warranty_route_analysis()
        if analysis['errors']:
            raise UserError('\n\n'.join(analysis['errors']))
        levels = {info['level']: (info['rules'], info['eligible'])
                  for info in analysis['levels']}
        return analysis['amounts'], analysis['matched'], levels

    def _warranty_approver_exclusions(self, user, submitter):
        """Why a configured approver cannot approve this request (empty: eligible)."""
        reasons = []
        if not user.active:
            reasons.append(_("archived user"))
        if user.share:
            reasons.append(_("portal user"))
        if self.company_id not in user.company_ids:
            reasons.append(_("not allowed in %s", self.company_id.name))
        if user == self._warranty_requester_user():
            reasons.append(_("requester"))
        if user == self.create_uid:
            reasons.append(_("creator"))
        if user == submitter:
            reasons.append(_("submitter"))
        return reasons

    def _warranty_route_analysis(self, submitter=None):
        """The approval route as Submit by ``submitter`` (default: the current user) would
        save it, without saving anything: amounts, applicable / matching rules, per level the
        configured, eligible and excluded approvers, and the errors that block the submission."""
        self.ensure_one()
        submitter = submitter or self.env.user
        amounts = self._warranty_routing_amounts()
        lines = self.requisition_line_ids
        currency = self.company_id.currency_id
        # sudo: the rules are configuration read by the workflow.
        rules = self.env['warranty.mrf.approval.rule'].sudo().search(
            [('company_id', 'in', self.company_id.parent_ids.ids)])
        matched = rules.filtered(lambda rule: rule._matches(amounts['routing'], lines))
        analysis = {'amounts': amounts, 'currency': currency, 'rules': rules,
                    'matched': matched, 'levels': [], 'errors': [], 'submitter': submitter}
        if not matched:
            analysis['errors'].append(_(
                "No material approval rule matches Material Request %(mrf)s (routing amount "
                "%(amount)s %(currency)s). Contact the Warranty administrator (Warranty / "
                "Configuration / Material Approval Rules).", mrf=self.name,
                amount=currency.round(amounts['routing']), currency=currency.name))
            return analysis
        goodwill_lines = lines.filtered('goodwill')
        for level, label in APPROVAL_LEVELS:
            level_rules = matched.filtered(lambda rule: rule['%s_required' % level])
            forced = bool(goodwill_lines) and level in ('finance', 'gm')
            if not level_rules and not forced:
                continue
            # Archived approvers are listed too, so that the reason can be shown.
            configured = level_rules.with_context(active_test=False).mapped(
                '%s_user_ids' % level)
            excluded = [(user, self._warranty_approver_exclusions(user, submitter))
                        for user in configured]
            eligible = configured.browse(
                [user.id for user, reasons in excluded if not reasons])
            info = {'level': level, 'label': label, 'rules': level_rules, 'forced': forced,
                    'configured': configured, 'eligible': eligible,
                    'excluded': [(user, reasons) for user, reasons in excluded if reasons],
                    'error': False}
            rule_names = ', '.join(level_rules.mapped('name'))
            if not configured and not level_rules:
                info['error'] = _(
                    "Goodwill materials require %(level)s approval (goodwill lines: "
                    "%(products)s), but none of the matching approval rules (%(rules)s) "
                    "requires %(level)s approval with %(level)s approvers. Add %(level)s "
                    "Approval and %(level)s approvers to a matching rule, or add a goodwill "
                    "rule.", level=label,
                    products=', '.join(goodwill_lines.mapped('product_id.display_name')),
                    rules=', '.join(matched.mapped('name')))
            elif not configured:
                info['error'] = _("The %(level)s approval required by rule(s) %(rules)s has no "
                                  "%(level)s approvers.", level=label, rules=rule_names)
            elif not eligible:
                info['error'] = _(
                    "The %(level)s approval of Material Request %(mrf)s has no available "
                    "approver. Rule(s): %(rules)s. Configured %(level)s approvers: "
                    "%(approvers)s. The requester, the creator and the submitter cannot "
                    "approve; archived users, portal users and users not allowed in the "
                    "request's company are not approvers.", level=label, mrf=self.name,
                    rules=rule_names, approvers='; '.join(
                        '%s (%s)' % (user.name, ', '.join(reasons))
                        for user, reasons in info['excluded']))
            analysis['levels'].append(info)
            if info['error']:
                analysis['errors'].append(info['error'])
        levels = analysis['levels']
        if levels and not analysis['errors'] and not self._warranty_distinct_assignment(
                [info['eligible'] for info in levels]):
            analysis['errors'].append(_(
                "Material Request %(mrf)s needs a different approver for every approval level; "
                "the configured approvers cannot cover all levels. Eligible approvers: "
                "%(levels)s.", mrf=self.name, levels='; '.join(
                    '%s: %s' % (info['label'], ', '.join(info['eligible'].mapped('name')))
                    for info in levels)))
        return analysis

    # ------------------------------------------------------------------ submit
    def requisition_confirm(self):
        """Submit (vendor Confirm). Warranty requests record by record (vendor e-mails use
        send_mail(self.id))."""
        warranty = self.filtered('is_warranty_mrf')
        for mrf in warranty:
            mrf._warranty_submit()
        others = self - warranty
        if others:
            return super(MaterialPurchaseRequisition, others).requisition_confirm()
        return True

    def _warranty_submit(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only Material Requests in status New can be submitted."))
        if not self.requisition_line_ids:
            raise UserError(_("Add the requested materials to %s before submitting.", self.name))
        self._warranty_check_coverage_decided()
        matrix = self.company_id.warranty_mrf_approval_matrix
        if matrix:
            amounts, matched, levels = self._warranty_compute_route()
        else:
            amounts, matched, levels = self._warranty_routing_amounts(), None, None
        now = fields.Datetime.now()
        self.sudo().write({
            'warranty_approval_mode': 'matrix' if matrix else 'vendor',
            'approval_round': self.approval_round + 1,
            'approval_routing_amount': amounts['routing'],
            'approval_covered_amount': amounts['covered'],
            'approval_not_covered_amount': amounts['not_covered'],
            'approval_goodwill_amount': amounts['goodwill'],
            'approval_signature': self._warranty_line_signature(),
            'submitted_by_id': self.env.uid,
            'submitted_date': now,
            'approved_by_id': False,
            'approved_date': False,
            'warranty_manager_user_id': False,
            'approved_amount': 0.0,
        })
        # Vendor Confirm (state, confirmation employee / date, e-mail - kept, Q5).
        super(MaterialPurchaseRequisition, self.sudo()).requisition_confirm()
        currency = self.company_id.currency_id
        amount = '%s %s' % (currency.round(amounts['routing']), currency.name)
        if not matrix:
            text = _("Submitted by %(user)s (round %(round)s, routing amount %(amount)s) - "
                     "Requisition workflow (Material Approval Matrix off).",
                     user=self.env.user.name, round=self.approval_round, amount=amount)
            self.sudo()._message_log(body=text)
            self._warranty_log_links(text)
            return
        Approval = self.env['warranty.mrf.approval'].sudo()
        common = {
            'requisition_id': self.id, 'round': self.approval_round,
            'routing_amount': amounts['routing'], 'covered_amount': amounts['covered'],
            'not_covered_amount': amounts['not_covered'], 'goodwill_amount': amounts['goodwill'],
        }
        if not levels:
            Approval.create(dict(common, level='none', sequence=0, state='approved',
                                 rule_ids=[(6, 0, matched.ids)], decision_date=now,
                                 reason=_("No Approval Required: %s",
                                          ', '.join(matched.mapped('name')))))
            text = _("Submitted by %(user)s (round %(round)s, routing amount %(amount)s): "
                     "approved by No Approval Required rule(s) %(rules)s.",
                     user=self.env.user.name, round=self.approval_round, amount=amount,
                     rules=', '.join(matched.mapped('name')))
            self.sudo()._message_log(body=text)
            self._warranty_log_links(text)
            self._warranty_final_approve(by_rule=True)
            return
        created = Approval.browse()
        for sequence, (level, label) in enumerate(APPROVAL_LEVELS, start=1):
            if level in levels:
                level_rules, users = levels[level]
                created |= Approval.create(dict(common, level=level, sequence=sequence,
                                                rule_ids=[(6, 0, level_rules.ids)],
                                                allowed_user_ids=[(6, 0, users.ids)]))
            else:
                Approval.create(dict(common, level=level, sequence=sequence, state='skipped',
                                     decision_date=now, reason=_("Not required by the matching "
                                                                 "rules.")))
        self.sudo().write({'warranty_approver_user_ids': [
            (4, user.id) for user in created.allowed_user_ids]})
        if 'manager' not in levels:
            self.sudo().write({'state': 'ir_approve'})
        route = ', '.join('%s (%s)' % (dict(APPROVAL_LEVELS)[line.level],
                                       ', '.join(line.allowed_user_ids.mapped('name')))
                          for line in created)
        text = _("Submitted by %(user)s (round %(round)s, routing amount %(amount)s). Approval "
                 "route: %(route)s. Rules: %(rules)s.", user=self.env.user.name,
                 round=self.approval_round, amount=amount, route=route,
                 rules=', '.join(matched.mapped('name')))
        self.sudo()._message_log(body=text)
        self._warranty_log_links(text)
        self._warranty_schedule_stage()

    def _warranty_schedule_stage(self):
        """D-M: To-Dos for the approvers of the pending level(s) of the current state."""
        self.ensure_one()
        stage = STAGE_LEVELS.get(self.state, ())
        lines = self._warranty_round_lines().filtered(
            lambda line: line.state == 'pending' and line.level in stage and not line.activity_ids)
        deadline = fields.Date.context_today(self) + timedelta(
            days=self.company_id.warranty_mrf_approval_deadline_days)
        # sudo: To-Dos are assigned by the workflow; without an e-mail address of the current
        # user they are assigned without e-mail (Part 3 pattern).
        record = self.sudo() if self.env.user.email else \
            self.sudo().with_context(mail_activity_quick_update=True)
        for line in lines:
            label = dict(APPROVAL_LEVELS)[line.level]
            activities = self.env['mail.activity']
            for user in line.allowed_user_ids:
                activities |= record.activity_schedule(
                    'mail.mail_activity_data_todo', date_deadline=deadline, user_id=user.id,
                    summary=_("%(level)s approval of Material Request %(mrf)s",
                              level=label, mrf=self.name),
                    note=_("Routing amount %(amount)s (round %(round)s).",
                           amount=self.approval_routing_amount, round=self.approval_round))
            line.activity_ids = [(6, 0, activities.ids)]

    def _warranty_close_activities(self, lines, feedback):
        activities = lines.sudo().activity_ids.exists().filtered('active')
        if activities:
            activities.sudo().action_feedback(feedback=feedback)

    # ------------------------------------------------------------------ approve / reject
    def _warranty_decidable_line(self, user=None):
        """(approval line the user may decide now, error message)."""
        self.ensure_one()
        user = user or self.env.user
        if not self.is_warranty_mrf or self.warranty_approval_mode != 'matrix':
            return False, _("%s does not use the material approval matrix.", self.name)
        if self.state not in WAITING_STATES:
            return False, _("Material Request %s is not waiting for approval.", self.name)
        if user in self._warranty_sod_users():
            return False, _("The requester, the creator and the submitter of %s cannot approve "
                            "or reject it.", self.name)
        round_lines = self._warranty_round_lines()
        if round_lines.filtered(lambda line: line.state == 'approved' and line.user_id == user):
            return False, _("You already approved a level of %s; another person must approve "
                            "the remaining levels.", self.name)
        if self.company_id not in user.company_ids:
            return False, _("You are not allowed in %s.", self.company_id.name)
        candidates = round_lines.filtered(
            lambda line: line.state == 'pending' and line.level in STAGE_LEVELS[self.state]
            and user in line.allowed_user_ids)
        if not candidates:
            return False, _("You are not an approver of the pending approval level of %s.",
                            self.name)
        return candidates.sorted('sequence')[0], False

    def _warranty_check_decidable(self):
        line, error = self._warranty_decidable_line()
        if not line:
            raise AccessError(error)
        return line

    def _warranty_check_signature(self):
        if self.approval_signature != self._warranty_line_signature():
            raise UserError(_("The lines of %s changed after submission: withdraw it and submit "
                              "it again.", self.name))

    def action_warranty_approve(self):
        self.ensure_one()
        line = self._warranty_check_decidable()
        self._warranty_check_signature()
        label = dict(APPROVAL_LEVELS)[line.level]
        line.write({'state': 'approved', 'user_id': self.env.uid,
                    'decision_date': fields.Datetime.now()})
        self._warranty_close_activities(line, _("%(level)s approval by %(user)s.", level=label,
                                                user=self.env.user.name))
        text = _("%(level)s approval by %(user)s (round %(round)s).", level=label,
                 user=self.env.user.name, round=self.approval_round)
        self.sudo()._message_log(body=text)
        self._warranty_log_links(text)
        remaining = self._warranty_round_lines().filtered(lambda rec: rec.state == 'pending')
        if line.level == 'manager':
            # Vendor Department Approve: approving manager, date, vendor e-mails (Q5).
            super(MaterialPurchaseRequisition, self.sudo()).manager_approve()
            self.sudo().write({'warranty_manager_user_id': self.env.uid})
            if remaining:
                self._warranty_schedule_stage()
                return True
        if not remaining:
            self._warranty_final_approve()
        return True

    def _warranty_final_approve(self, by_rule=False):
        """D-O: the vendor state Approved only when every required level is approved. A No
        Approval Required rule records no approving person."""
        self.ensure_one()
        if self._warranty_round_lines().filtered(lambda line: line.state not in
                                                 DONE_LINE_STATES):
            raise UserError(_("Material Request %s still waits for approvals.", self.name))
        self._warranty_check_signature()
        if self.state == 'dept_confirm':
            self.sudo().write({'state': 'ir_approve'})
        super(MaterialPurchaseRequisition, self.sudo()).user_approve()
        self.sudo().write({'approved_by_id': False if by_rule else self.env.uid,
                           'approve_employee_id': False if by_rule
                           else self.sudo().approve_employee_id.id,
                           'approved_date': fields.Datetime.now(),
                           'approved_amount': self.approval_routing_amount})
        text = _("Material Request %(mrf)s approved (round %(round)s, approved amount "
                 "%(amount)s).", mrf=self.name, round=self.approval_round,
                 amount=self.approval_routing_amount)
        self._warranty_notify(text)
        self._warranty_log_links(_("approved (round %s).", self.approval_round))

    def action_warranty_reject(self):
        self.ensure_one()
        self._warranty_check_decidable()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Material Request"),
            'res_model': 'warranty.mrf.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_requisition_id': self.id},
        }

    def _warranty_reject(self, reason):
        self.ensure_one()
        line = self._warranty_check_decidable()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to reject a Material Request."))
        now = fields.Datetime.now()
        line.write({'state': 'rejected', 'user_id': self.env.uid, 'decision_date': now,
                    'reason': reason})
        others = self._warranty_round_lines().filtered(lambda rec: rec.state == 'pending')
        others.write({'state': 'superseded', 'decision_date': now})
        label = dict(APPROVAL_LEVELS)[line.level]
        self._warranty_close_activities(line | others, _("Rejected by %s.", self.env.user.name))
        # Vendor Reject: rejecting employee / date, state Rejected.
        super(MaterialPurchaseRequisition, self.sudo()).requisition_reject()
        text = _("Material Request %(mrf)s rejected by %(user)s at the %(level)s level (round "
                 "%(round)s). Reason: %(reason)s", mrf=self.name, user=self.env.user.name,
                 level=label, round=self.approval_round, reason=reason)
        self._warranty_notify(text)
        self._warranty_log_links(_("rejected by %(user)s. Reason: %(reason)s",
                                   user=self.env.user.name, reason=reason))

    # ------------------------------------------------------------------ withdraw
    def _warranty_withdraw_error(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if not self.is_warranty_mrf:
            return _("Only warranty Material Requests can be withdrawn.")
        if not (self.state in WAITING_STATES or (self.state == 'approve'
                                                  and self._warranty_is_legacy())):
            return _("Material Request %s can only be withdrawn while it waits for approval.",
                     self.name)
        if not (self.env.su or self._warranty_is_requester_or_creator(user)):
            return _("Only the requester or the creator of %s can withdraw it.", self.name)
        return False

    def action_warranty_withdraw(self):
        """D-J / Q2: requester or creator, before the final approval; history kept."""
        for mrf in self:
            error = mrf._warranty_withdraw_error()
            if error:
                raise AccessError(error)
            pending = mrf._warranty_round_lines().filtered(lambda line: line.state == 'pending')
            pending.write({'state': 'withdrawn', 'decision_date': fields.Datetime.now(),
                           'user_id': self.env.uid})
            mrf._warranty_close_activities(pending, _("Withdrawn by %s.", self.env.user.name))
            mrf.sudo().write({'state': 'draft'})
            text = _("Withdrawn by %(user)s (round %(round)s); the request is New again and "
                     "needs a new approval round.", user=self.env.user.name,
                     round=mrf.approval_round)
            mrf.sudo()._message_log(body=text)
            mrf._warranty_log_links(text)
        return True

    # ------------------------------------------------------------------ vendor actions
    def _warranty_vendor_step_check(self, state, groups, check_manager=False):
        """Vendor buttons on warranty requests: matrix requests only through the bridge
        buttons; Requisition workflow (matrix off) with state, group and separation checks."""
        error = self._warranty_vendor_step_error(state, groups, check_manager)
        if error:
            raise error[0](error[1])

    def _warranty_vendor_step_error(self, state, groups, check_manager=False):
        """(exception class, message) when the current user may not run the vendor step."""
        self.ensure_one()
        if not self.warranty_approval_mode:
            return UserError, _("Material Request %s was submitted before the warranty approval "
                                "workflow: withdraw it and submit it again.", self.name)
        if self.warranty_approval_mode != 'vendor':
            return UserError, _("Material Request %s is approved through the material approval "
                                "matrix (Approve / Reject buttons of the named approvers).",
                                self.name)
        if self.state not in state:
            return UserError, _("This action is not allowed for Material Request %(mrf)s in its "
                                "current status.", mrf=self.name)
        if self.env.su:
            return False
        user = self.env.user
        if not any(user.has_group(group) for group in groups):
            return AccessError, _("You are not allowed to approve or reject Material Requests.")
        if user in self._warranty_sod_users():
            return AccessError, _("The requester, the creator and the submitter of %s cannot "
                                  "approve or reject it.", self.name)
        if check_manager and user in (self.warranty_manager_user_id
                                      | self.sudo().approve_manager_id.user_id):
            return AccessError, _("You approved %s as department manager; another person must "
                                  "give the final approval.", self.name)
        return False

    def manager_approve(self):
        warranty = self.filtered('is_warranty_mrf')
        for mrf in warranty:
            mrf._warranty_vendor_step_check(('dept_confirm',), (GROUP_DEPARTMENT,))
            super(MaterialPurchaseRequisition, mrf.sudo()).manager_approve()
            mrf.sudo().write({'warranty_manager_user_id': self.env.uid})
        others = self - warranty
        return super(MaterialPurchaseRequisition, others).manager_approve() if others else True

    def user_approve(self):
        warranty = self.filtered('is_warranty_mrf')
        for mrf in warranty:
            mrf._warranty_vendor_step_check(('ir_approve',), (GROUP_REQUISITION,),
                                            check_manager=True)
            super(MaterialPurchaseRequisition, mrf.sudo()).user_approve()
            mrf.sudo().write({'approved_by_id': self.env.uid,
                              'approved_date': fields.Datetime.now(),
                              'approved_amount': mrf.approval_routing_amount})
        others = self - warranty
        return super(MaterialPurchaseRequisition, others).user_approve() if others else True

    def requisition_reject(self):
        warranty = self.filtered('is_warranty_mrf')
        for mrf in warranty:
            mrf._warranty_vendor_step_check(
                ('dept_confirm', 'ir_approve', 'approve'),
                (GROUP_DEPARTMENT, GROUP_REQUISITION, GROUP_REQUISITION_MANAGER))
            super(MaterialPurchaseRequisition, mrf.sudo()).requisition_reject()
        others = self - warranty
        return super(MaterialPurchaseRequisition, others).requisition_reject() if others else True

    def _warranty_release_error(self):
        """Approved, valid round complete, unchanged lines; the commercial control of the Not
        Covered lines (Phase 5.4) adds its own condition."""
        self.ensure_one()
        return self._warranty_approved_error() or self._warranty_commercial_release_error()

    def _warranty_commercial_release_error(self):
        """Overridden by Phase 5.4 (D-L before 5.4: no Not Covered line)."""
        self.ensure_one()
        if self.requisition_line_ids.filtered(lambda line: line.coverage_type == 'not_covered'):
            return _("Material Request %s contains Not Covered lines: stock release and "
                     "purchasing wait for the commercial control (Phase 5.4).", self.name)
        return False

    def _warranty_approved_error(self):
        """Approved through the warranty workflow, round complete, lines unchanged."""
        self.ensure_one()
        if self.state not in RELEASED_STATES or not self.approval_round:
            return _("Material Request %s is not approved through the warranty approval "
                     "workflow.", self.name)
        if self.warranty_approval_mode == 'matrix' and (
                not self._warranty_round_lines()
                or self._warranty_round_lines().filtered(
                    lambda line: line.state not in DONE_LINE_STATES)):
            return _("The approval round of %s is not complete.", self.name)
        if self.approval_signature != self._warranty_line_signature():
            return _("The lines of %s changed after submission.", self.name)
        return False

    def _warranty_check_release(self):
        for mrf in self.filtered('is_warranty_mrf'):
            error = mrf._warranty_release_error()
            if error:
                raise UserError(error)

    def request_stock(self):
        warranty = self.filtered('is_warranty_mrf')
        for mrf in warranty:
            if mrf.state != 'approve':
                raise UserError(_("Pickings and purchase orders are created for approved "
                                  "Material Requests only."))
            mrf._warranty_check_release()
            if not self.env.su and not self.env.user.has_group(GROUP_REQUISITION):
                raise AccessError(_("Only Requisition users create pickings and purchase "
                                    "orders."))
            super(MaterialPurchaseRequisition, mrf.sudo()).request_stock()
        others = self - warranty
        return super(MaterialPurchaseRequisition, others).request_stock() if others else True

    def action_received(self):
        warranty = self.filtered('is_warranty_mrf')
        for mrf in warranty:
            if mrf.state != 'stock':
                raise UserError(_("Only Material Requests with pickings / purchase orders can "
                                  "be marked Received."))
            if not self.env.su and not any(self.env.user.has_group(group)
                                           for group in PICKING_GROUPS):
                raise AccessError(_("Only Requisition / Inventory users mark Material Requests "
                                    "Received."))
            super(MaterialPurchaseRequisition, mrf.sudo()).action_received()
        others = self - warranty
        return super(MaterialPurchaseRequisition, others).action_received() if others else True

    def _warranty_check_requester_action(self, states, message):
        for mrf in self:
            if mrf.state not in states:
                raise UserError(message)
            if not (self.env.su or mrf._warranty_is_requester_or_creator()):
                raise AccessError(_("Only the requester or the creator of %s can do this.",
                                    mrf.name))

    def reset_draft(self):
        """Q7: Rejected / Cancelled only (never from Received); requester or creator."""
        warranty = self.filtered('is_warranty_mrf')
        warranty._warranty_check_requester_action(
            ('reject', 'cancel'), _("Warranty Material Requests can be reset to New only when "
                                    "Rejected or Cancelled."))
        for mrf in warranty:
            super(MaterialPurchaseRequisition, mrf.sudo()).reset_draft()
            mrf.sudo()._message_log(body=_("Reset to New by %s.", self.env.user.name))
        others = self - warranty
        return super(MaterialPurchaseRequisition, others).reset_draft() if others else True

    def action_cancel(self):
        """Q6: requester or creator, in New or Rejected."""
        warranty = self.filtered('is_warranty_mrf')
        warranty._warranty_check_requester_action(
            ('draft', 'reject'), _("Warranty Material Requests can be cancelled only when New "
                                   "or Rejected."))
        for mrf in warranty:
            super(MaterialPurchaseRequisition, mrf.sudo()).action_cancel()
        others = self - warranty
        return super(MaterialPurchaseRequisition, others).action_cancel() if others else True

    # ------------------------------------------------------------------ protection
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.su:
            for mrf in records.filtered('is_warranty_mrf'):
                if mrf.state != 'draft' or any(mrf[name] for name in PROTECTED_FIELDS
                                               if name != 'state'):
                    raise UserError(_("Warranty Material Requests are created as New; the "
                                      "approval fields are set by the approval workflow."))
        return records

    def write(self, vals):
        if not self.env.su:
            self.filtered('is_warranty_mrf')._warranty_check_write(vals)
        return super().write(vals)

    def _warranty_check_write(self, vals):
        if not self:
            return
        keys = {key for key in vals if not key.startswith(FREE_FIELD_PREFIXES)}
        protected = keys & PROTECTED_FIELDS
        if protected:
            raise UserError(_("The status and approval fields of warranty Material Requests are "
                              "set by the approval workflow (%s).", ', '.join(sorted(protected))))
        submitted = self.filtered(lambda mrf: mrf.state != 'draft')
        if not submitted:
            return
        # Line commands are checked by the lines themselves.
        keys -= {'requisition_line_ids'}
        if keys - PICKING_FIELDS:
            raise UserError(_("Material Request %s is locked after submission; withdraw or "
                              "reset it to New to change it (a new approval round follows).",
                              submitted[0].name))
        if keys:
            if not any(self.env.user.has_group(group) for group in PICKING_GROUPS):
                raise AccessError(_("Only Requisition / Inventory users can change the Picking "
                                    "Details of a submitted Material Request."))
            if submitted.filtered(lambda mrf: mrf.state not in WAITING_STATES + ('approve',)):
                raise UserError(_("The Picking Details can only be changed until the picking "
                                  "is created."))

    def unlink(self):
        """Q10: warranty requests with an approval history are never deleted."""
        if self.filtered(lambda mrf: mrf.is_warranty_mrf and mrf.approval_round):
            raise UserError(_("Warranty Material Requests with an approval history cannot be "
                              "deleted; cancel them instead."))
        return super().unlink()


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    routing_cost = fields.Monetary(
        string='Routing Cost', compute='_compute_routing_cost',
        help="Higher of the estimated cost and the product cost (D-F); used for the approval "
             "thresholds. The entered estimated cost is kept unchanged.")

    @api.depends('qty', 'uom', 'product_id', 'estimated_cost')
    def _compute_routing_cost(self):
        for line in self:
            line.routing_cost = max(line.estimated_cost,
                                    line.qty * line._warranty_product_unit_cost())
