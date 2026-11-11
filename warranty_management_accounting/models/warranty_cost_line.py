from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_amount

# Part 8.1 (doc/part8_1_cost_lines_design.md): labour, travel, subcontract and other warranty cost
# (SRS 5 Warranty Cost Lines, 2.10, 16.1, 17). A line never posts: no journal entry, and timesheet,
# purchase, vendor bill and stock records are only read.
GROUP_COORDINATOR = 'helpdesk.group_helpdesk_user'
GROUP_BILLING = 'account.group_account_invoice'
GROUP_PURCHASE = 'purchase.group_purchase_user'
COST_TYPES = [
    ('labour', 'Labour'),
    ('travel', 'Travel'),
    ('subcontract', 'Subcontract'),
    ('other', 'Other'),
]
COST_LINE_STATES = [
    ('draft', 'Draft'),
    ('submitted', 'Submitted'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('reversed', 'Reversed'),
]
INACTIVE_STATES = ('rejected', 'reversed')
LINK_FIELDS = {'purchase_line_id', 'bill_line_id'}
# Written by the workflow only (superuser mode after the checks).
WORKFLOW_FIELDS = {
    'state', 'approved_amount', 'submitted_by_id', 'submitted_date', 'finance_required',
    'manager_approved_by_id', 'manager_approved_date', 'finance_approved_by_id',
    'finance_approved_date', 'approver_user_ids', 'rejected_by_id', 'rejected_date',
    'rejection_reason', 'reversed_by_id', 'reversed_date', 'reversal_reason',
}
FREE_PREFIXES = ('message_', 'activity_', 'website_message')


class WarrantyCostLine(models.Model):
    _name = 'warranty.cost.line'
    _description = 'Warranty Cost Line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')
    case_id = fields.Many2one('warranty.case', string='Warranty Case', required=True, index=True,
                              ondelete='restrict', tracking=True,
                              domain="[('state', 'not in', ('rejected', 'closed'))]")
    company_id = fields.Many2one(related='case_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    job_id = fields.Many2one('warranty.service.job', string='Service Job', index='btree_not_null',
                             ondelete='restrict', tracking=True,
                             domain="[('warranty_case_id', '=', case_id)]")
    repair_id = fields.Many2one('repair.order', string='Repair Order', index='btree_not_null',
                                ondelete='restrict', tracking=True,
                                domain="[('warranty_case_id', '=', case_id)]")
    cost_type = fields.Selection(COST_TYPES, string='Cost Type', required=True, tracking=True)
    reason = fields.Text(string='Reason', required=True, tracking=True,
                         help="Why this cost is needed (kept for audit).")
    estimated_amount = fields.Monetary(string='Estimated', tracking=True)
    approved_amount = fields.Monetary(string='Approved', readonly=True, copy=False, tracking=True)
    actual_amount = fields.Monetary(
        string='Actual', tracking=True, copy=False,
        help="Entered for Travel, Other and workshop Labour. Labour of a visit is read from its "
             "timesheets, and Subcontract from its purchase or vendor bill record.")
    # No field default: a new column with one would fill the existing lines on upgrade.
    cost_date = fields.Date(
        string='Cost Incurred Date', tracking=True, copy=False,
        help="The date this cost was incurred, used by the Warranty Cost Report. Empty on lines "
             "created before this field: the report then uses the approval date.")
    purchase_line_id = fields.Many2one('purchase.order.line', string='Purchase Order Line',
                                       index='btree_not_null', ondelete='restrict', copy=False,
                                       tracking=True)
    bill_line_id = fields.Many2one('account.move.line', string='Vendor Bill Line',
                                   index='btree_not_null', ondelete='restrict', copy=False,
                                   tracking=True)
    source_reference = fields.Char(string='Source Document', compute='_compute_source',
                                   compute_sudo=True)
    source_amount = fields.Monetary(string='Source Amount', compute='_compute_source',
                                    compute_sudo=True,
                                    help="Posted vendor bill amount, in company currency.")
    source_commitment = fields.Monetary(string='Purchase Commitment', compute='_compute_source',
                                        compute_sudo=True,
                                        help="Purchase order line amount, in company currency.")
    source_warning = fields.Char(string='Source Warning', compute='_compute_source',
                                 compute_sudo=True)
    source_invalid = fields.Boolean(string='Source Not Usable', compute='_compute_source',
                                    compute_sudo=True)
    expected_amount = fields.Monetary(string='Expected', compute='_compute_figures',
                                      compute_sudo=True)
    counted_approved_amount = fields.Monetary(string='Counted Approved', compute='_compute_figures',
                                              compute_sudo=True)
    counted_actual_amount = fields.Monetary(string='Counted Actual', compute='_compute_figures',
                                            compute_sudo=True)
    state = fields.Selection(COST_LINE_STATES, string='Status', default='draft', required=True,
                             readonly=True, tracking=True, copy=False, index=True)
    approver_user_ids = fields.Many2many('res.users', 'warranty_cost_line_approver_rel', 'line_id',
                                         'user_id', string='Named Approvers', readonly=True,
                                         copy=False)
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    finance_required = fields.Boolean(string='Finance Approval Required', readonly=True, copy=False)
    manager_approved_by_id = fields.Many2one('res.users', string='Manager Approved By',
                                             readonly=True, copy=False, tracking=True)
    manager_approved_date = fields.Datetime(string='Manager Approved On', readonly=True, copy=False)
    finance_approved_by_id = fields.Many2one('res.users', string='Finance Approved By',
                                             readonly=True, copy=False, tracking=True)
    finance_approved_date = fields.Datetime(string='Finance Approved On', readonly=True, copy=False)
    rejected_by_id = fields.Many2one('res.users', string='Rejected By', readonly=True, copy=False)
    rejected_date = fields.Datetime(string='Rejected On', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False,
                                   tracking=True)
    reversed_by_id = fields.Many2one('res.users', string='Reversed By', readonly=True, copy=False)
    reversed_date = fields.Datetime(string='Reversed On', readonly=True, copy=False)
    reversal_reason = fields.Text(string='Reversal Reason', readonly=True, copy=False,
                                  tracking=True)
    can_approve = fields.Boolean(compute='_compute_user_actions')
    can_reverse = fields.Boolean(compute='_compute_user_actions')
    can_record_actual = fields.Boolean(compute='_compute_user_actions')
    actual_is_manual = fields.Boolean(compute='_compute_actual_is_manual')

    def init(self):
        # Second line of defence against allocating one bill or purchase line twice.
        for name, column in (('warranty_cost_line_bill_uniq', 'bill_line_id'),
                             ('warranty_cost_line_purchase_uniq', 'purchase_line_id')):
            self.env.cr.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {name} ON warranty_cost_line ({column})
                 WHERE {column} IS NOT NULL AND state NOT IN ('rejected', 'reversed')
            """)

    # ------------------------------------------------------------------ computes
    @api.depends('cost_type', 'repair_id')
    def _compute_actual_is_manual(self):
        for line in self:
            line.actual_is_manual = line.cost_type in ('travel', 'other') or (
                line.cost_type == 'labour' and bool(line.repair_id))

    @api.depends('bill_line_id.balance', 'bill_line_id.parent_state',
                 'bill_line_id.move_id.payment_state',
                 'bill_line_id.move_id.reversal_move_ids.state',
                 'purchase_line_id.price_subtotal', 'purchase_line_id.state',
                 'purchase_line_id.invoice_lines.balance',
                 'purchase_line_id.invoice_lines.parent_state')
    def _compute_source(self):
        for line in self:
            bill, order = line.bill_line_id, line.purchase_line_id
            values = {'source_reference': False, 'source_amount': 0.0, 'source_commitment': 0.0,
                      'source_warning': False, 'source_invalid': False}
            if bill:
                active = bill.parent_state == 'posted' and bill.move_id.payment_state != 'reversed'
                refunded = line._warranty_bill_line_refunded() if active else 0.0
                values.update({
                    'source_reference': bill.move_id.name,
                    'source_amount': max(bill.balance - refunded, 0.0) if active else 0.0,
                    'source_invalid': not active,
                })
                if not active:
                    values['source_warning'] = _(
                        "Vendor bill %s is no longer posted or has been reversed.",
                        bill.move_id.name)
                elif not line.currency_id.is_zero(refunded):
                    values['source_warning'] = _(
                        "Vendor bill %(bill)s has credit notes: %(amount)s refunded on this line. "
                        "The actual cost is net of them.", bill=bill.move_id.name,
                        amount=format_amount(self.env, refunded, line.currency_id))
            elif order:
                billed = order.invoice_lines.filtered(lambda aml: aml.parent_state == 'posted')
                cancelled = order.state == 'cancel'
                values.update({
                    'source_reference': order.order_id.name,
                    'source_amount': sum(billed.mapped('balance')),
                    'source_commitment': 0.0 if cancelled else order.currency_id._convert(
                        order.price_subtotal, line.currency_id or order.company_id.currency_id,
                        order.company_id, order.order_id.date_order or fields.Date.context_today(line)),
                    'source_warning': _("Purchase order %s is cancelled.", order.order_id.name)
                    if cancelled else False,
                    'source_invalid': cancelled,
                })
            line.update(values)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'cost_date' in fields_list and 'cost_date' not in values:
            values['cost_date'] = fields.Date.context_today(self)
        return values

    def _warranty_effective_date(self):
        """The Cost Incurred Date, else the final approval, else the earliest record of the line."""
        self.ensure_one()
        line = self.sudo()
        if line.cost_date:
            return line.cost_date
        return line.company_id._warranty_local_date(
            line.finance_approved_date or line.manager_approved_date or line.submitted_date
            or line.create_date)

    def _warranty_actual_movements(self):
        """[(date, amount)] behind the counted actual of this line, for the cost report. A linked
        document counts on its accounting date, a credit note takes back its share on its own date;
        reversing the line takes the actual back on the reversal date."""
        self.ensure_one()
        line = self.sudo()
        if line.state not in ('approved', 'reversed'):
            return []
        raw = line._warranty_raw_actual()
        if line.cost_type != 'subcontract':
            movements = [(line._warranty_effective_date(), raw)]
        elif line.bill_line_id:
            bill = line.bill_line_id
            movements = [(bill.move_id.date, bill.balance)] if bill.parent_state == 'posted' else []
            if movements:
                def same(aml):
                    return aml.display_type == 'product' and aml.product_id == bill.product_id \
                        and aml.account_id == bill.account_id

                total = sum(bill.move_id.invoice_line_ids.filtered(same).mapped('balance'))
                for refund in bill.move_id.reversal_move_ids.filtered(
                        lambda move: move.state == 'posted'):
                    amount = sum(refund.invoice_line_ids.filtered(same).mapped('balance'))
                    if total and amount:
                        movements.append((refund.date, amount * bill.balance / total))
        else:
            movements = [(aml.move_id.date, aml.balance)
                         for aml in line.purchase_line_id.invoice_lines
                         if aml.parent_state == 'posted']
        if line.state == 'reversed' and raw:
            movements.append((line.company_id._warranty_local_date(line.reversed_date), -raw))
        return movements

    def _warranty_bill_line_refunded(self):
        """Amount refunded on the linked bill line by posted credit notes of its bill. A credit
        note line has no link to one bill line, so it is matched by product and account, and split
        by amount when several bill lines share them. A credit note entered without a link to the
        bill cannot be detected here."""
        self.ensure_one()
        bill = self.bill_line_id
        move = bill.move_id

        def same(aml):
            return aml.display_type == 'product' and aml.product_id == bill.product_id \
                and aml.account_id == bill.account_id

        refunds = move.reversal_move_ids.filtered(
            lambda refund: refund.state == 'posted').invoice_line_ids.filtered(same)
        peers = move.invoice_line_ids.filtered(same)
        total = sum(peers.mapped('balance'))
        if not total:
            return 0.0
        return self.currency_id.round(-sum(refunds.mapped('balance')) * bill.balance / total)

    @api.depends('state', 'estimated_amount', 'approved_amount', 'actual_amount', 'cost_type',
                 'source_amount', 'source_commitment')
    def _compute_figures(self):
        for line in self:
            raw_actual = line._warranty_raw_actual()
            approved = line.state == 'approved'
            line.counted_approved_amount = line.approved_amount if approved else 0.0
            line.counted_actual_amount = raw_actual if approved else 0.0
            line.expected_amount = 0.0 if line.state in INACTIVE_STATES else max(
                line.estimated_amount, line.approved_amount, raw_actual, line.source_commitment)

    @api.depends_context('uid')
    @api.depends('state', 'finance_required', 'manager_approved_by_id', 'finance_approved_by_id',
                 'cost_type', 'repair_id')
    def _compute_user_actions(self):
        for line in self:
            approved = line.state == 'approved'
            line.can_approve = line.state == 'submitted' and bool(line._pending_levels_for())
            line.can_reverse = approved and line._is_cost_approver()
            line.can_record_actual = approved and line.actual_is_manual and (
                line._is_coordinator() or line._is_cost_approver())

    def _warranty_raw_actual(self):
        self.ensure_one()
        return self.source_amount if self.cost_type == 'subcontract' else self.actual_amount

    # ------------------------------------------------------------------ constraints
    @api.constrains('estimated_amount', 'actual_amount')
    def _check_amounts(self):
        for line in self:
            if line.estimated_amount < 0 or line.actual_amount < 0:
                raise ValidationError(_("Cost amounts cannot be negative (%s). Use Reverse to "
                                        "correct an approved line.", line.name))

    @api.constrains('case_id', 'job_id', 'repair_id')
    def _check_links(self):
        for line in self.sudo():
            case = line.case_id
            if line.job_id and line.job_id.warranty_case_id != case:
                raise ValidationError(_("Service job %(job)s does not belong to warranty case "
                                        "%(case)s.", job=line.job_id.name, case=case.name))
            if line.repair_id and line.repair_id.warranty_case_id != case:
                raise ValidationError(_("Repair Order %(repair)s does not belong to warranty case "
                                        "%(case)s.", repair=line.repair_id.name, case=case.name))
            if line.job_id and line.repair_id:
                raise ValidationError(_("A cost line belongs to one service job or one Repair "
                                        "Order, so its cost is counted once."))

    @api.constrains('cost_type', 'actual_amount', 'repair_id', 'purchase_line_id', 'bill_line_id')
    def _check_cost_source(self):
        for line in self.sudo():
            if line.cost_type != 'subcontract' and (line.purchase_line_id or line.bill_line_id):
                raise ValidationError(_("Only Subcontract lines link a purchase or vendor bill "
                                        "record."))
            if line.cost_type == 'subcontract' and line.actual_amount:
                raise ValidationError(_("The actual subcontract cost is read from its purchase or "
                                        "vendor bill record."))
            if line.cost_type == 'labour' and not line.repair_id and line.actual_amount:
                raise ValidationError(_("The actual labour of a visit is read from its timesheets; "
                                        "enter only an estimate, or link a Repair Order for "
                                        "workshop labour."))
            if line.purchase_line_id and line.bill_line_id:
                raise ValidationError(_("Link one purchase order line or one vendor bill line, "
                                        "not both."))
            line._warranty_check_source_record()

    def _warranty_check_source_record(self):
        """SRS 17: the source is a real, unallocated record, and not a part that the Material
        Request cost already counts from stock valuation."""
        self.ensure_one()
        bill, order = self.bill_line_id, self.purchase_line_id
        if not bill and not order:
            return
        product = bill.product_id or order.product_id
        if product.is_storable:
            raise ValidationError(_("%s is a stockable product: its cost comes from stock "
                                    "valuation, not from a subcontract line.",
                                    product.display_name))
        linked_order = order or bill.purchase_line_id
        if linked_order.custom_requisition_line_id:
            raise ValidationError(_("Purchase line of %s belongs to a Material Request, whose cost "
                                    "is already counted.", linked_order.order_id.name))
        record_company = bill.company_id or order.company_id
        if record_company != self.company_id:
            raise ValidationError(_("The purchase or vendor bill record belongs to another "
                                    "company."))
        if bill and (bill.move_id.move_type != 'in_invoice' or bill.parent_state != 'posted'
                     or bill.display_type != 'product'):
            raise ValidationError(_("Link a product line of a posted vendor bill."))
        if order and order.state not in ('purchase', 'done'):
            raise ValidationError(_("Link a line of a confirmed purchase order."))

    def _warranty_check_allocation(self, bill, order):
        """A bill or purchase line is allocated once, also when one is the bill of the other. The
        lock serialises concurrent links; the unique indexes stay as the last line of defence."""
        if not bill and not order:
            return
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)",
                            ((bill.company_id or order.company_id).id + 880100,))
        active = self.sudo().search([
            ('id', 'not in', self.ids), ('state', 'not in', INACTIVE_STATES), '|',
            ('bill_line_id', '!=', False), ('purchase_line_id', '!=', False)])
        for other in active:
            same_bill = bill and (other.bill_line_id == bill or (
                bill.purchase_line_id and other.purchase_line_id == bill.purchase_line_id))
            same_order = order and (other.purchase_line_id == order
                                    or other.bill_line_id.purchase_line_id == order)
            if same_bill or same_order:
                raise ValidationError(_("This purchase or vendor bill line is already allocated "
                                        "to cost line %(line)s of case %(case)s.", line=other.name,
                                        case=other.case_id.name))

    def _warranty_source_records(self, vals):
        """The (bill line, purchase line) that `vals` would link, read in superuser mode: Helpdesk
        users may not read accounting records."""
        bill = self.env['account.move.line'].sudo().browse(vals.get('bill_line_id') or [])
        order = self.env['purchase.order.line'].sudo().browse(vals.get('purchase_line_id') or [])
        return bill, order

    # ------------------------------------------------------------------ creation / protection
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                if WORKFLOW_FIELDS & set(vals):
                    raise UserError(_("The status and approval fields of cost lines are set by "
                                      "the approval workflow."))
            if not self._is_coordinator():
                raise AccessError(_("Only Service Coordinators (Helpdesk users) create warranty "
                                    "cost lines."))
        for vals in vals_list:
            self.browse()._warranty_check_allocation(*self._warranty_source_records(vals))
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('warranty.cost.line') or '/'
            case = self.env['warranty.case'].sudo().browse(vals.get('case_id'))
            if case.state in ('rejected', 'closed'):
                raise UserError(_("Warranty case %s is finished: no new cost line can be added.",
                                  case.name))
        lines = super().create(vals_list)
        for line in lines:
            line._warranty_log(_("Cost line %(line)s created: %(type)s, %(reason)s", line=line.name,
                                 type=line._warranty_type_label(), reason=line.reason))
        return lines

    def write(self, vals):
        if not self.env.su:
            keys = {key for key in vals if not key.startswith(FREE_PREFIXES)}
            if keys & WORKFLOW_FIELDS:
                raise UserError(_("The status and approval fields of cost lines are set by the "
                                  "approval workflow (%s).",
                                  ', '.join(sorted(keys & WORKFLOW_FIELDS))))
            if keys:
                if self.filtered(lambda line: line.state != 'draft'):
                    raise UserError(_("Cost line %s can only be changed in Draft. Use Record Actual "
                                      "or Reverse on an approved line.",
                                      self.filtered(lambda line: line.state != 'draft')[0].name))
                if not self._is_coordinator() and keys - LINK_FIELDS:
                    raise AccessError(_("Billing and Purchase users can only link the purchase or "
                                        "vendor bill record of a Draft cost line."))
        if LINK_FIELDS & set(vals):
            self._warranty_check_allocation(*self._warranty_source_records(vals))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self.filtered(
                lambda line: line.state != 'draft' or line.submitted_date):
            raise UserError(_("Submitted cost lines are never deleted; reject or reverse them "
                              "with a reason."))
        return super().unlink()

    # ------------------------------------------------------------------ helpers
    def _warranty_type_label(self):
        self.ensure_one()
        return dict(self._fields['cost_type']._description_selection(self.env))[self.cost_type]

    def _money(self, amount):
        self.ensure_one()
        return format_amount(self.env, amount, self.currency_id)

    def _warranty_log(self, text):
        """Audit trail (SRS 2.13, 16): note on the line, its case, and its job or Repair Order."""
        record = self.sudo()
        record._message_log(body=text)
        for target in (record.case_id, record.job_id, record.repair_id):
            if target:
                target._message_log(body=text)

    def _is_coordinator(self):
        return self.env.su or self.env.user.has_group(GROUP_COORDINATOR)

    def _is_cost_approver(self):
        self.ensure_one()
        company = self.sudo().company_id
        return self.env.user in (company.warranty_cost_approver_ids
                                 | company.warranty_cost_finance_approver_ids)

    def _approver_lists(self):
        company = self.sudo().company_id
        return {'manager': company.warranty_cost_approver_ids,
                'finance': company.warranty_cost_finance_approver_ids}

    def _excluded_approvers(self):
        return self.sudo().create_uid | self.sudo().submitted_by_id

    def _required_levels(self):
        return ['manager'] + (['finance'] if self.finance_required else [])

    def _pending_levels_for(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if user in self._excluded_approvers():
            return []
        record = self.sudo()
        decided = {'manager': record.manager_approved_by_id,
                   'finance': record.finance_approved_by_id}
        if user in decided.values():
            return []
        lists = self._approver_lists()
        return [level for level in self._required_levels()
                if not decided[level] and user in lists[level]
                and record.company_id in user.company_ids]

    def _warranty_finance_needed(self):
        """SRS 16.1: by amount. The threshold is compared with the total expected cost of the case.
        0 turns this additional Finance level off (approved decision); the Manager approval of the
        line stays mandatory."""
        self.ensure_one()
        record = self.sudo()
        company = record.company_id
        threshold = company.warranty_cost_finance_threshold
        if company.currency_id.is_zero(threshold):
            return False
        return company.currency_id.compare_amounts(
            record.case_id._warranty_expected_cost(), threshold) >= 0

    def _eligible_approvers(self, finance, levels=None):
        """Approvers of `levels` (default: the levels of a new submission). The current user is
        excluded: the submitter, or the manager who approves when Finance becomes required."""
        self.ensure_one()
        record = self.sudo()
        company = record.company_id
        excluded = record.create_uid | record.submitted_by_id | self.env.user
        lists = self._approver_lists()
        levels = levels or ['manager'] + (['finance'] if finance else [])
        eligible = {level: lists[level].filtered(
            lambda user: user not in excluded and company in user.company_ids
            and not user.share and user.active) for level in levels}
        labels = {'manager': _("Warranty Cost Approver"), 'finance': _("Finance Approver")}
        for level in levels:
            if not eligible[level]:
                raise UserError(_(
                    "Cost line %(line)s needs a %(level)s: configure the approvers in Warranty "
                    "Settings. The requester and the submitter cannot approve.", line=self.name,
                    level=labels[level]))
        if len(levels) == 2 and len(eligible['manager'] | eligible['finance']) < 2:
            raise UserError(_("Cost line %s needs two different approvers (Manager and Finance).",
                              self.name))
        return eligible

    def _warranty_check_ready(self):
        self.ensure_one()
        if not (self.reason or '').strip():
            raise UserError(_("Enter the reason of cost line %s.", self.name))
        if self.cost_type == 'subcontract':
            if not self.purchase_line_id and not self.bill_line_id:
                raise UserError(_("Cost line %s needs its purchase order line or vendor bill line "
                                  "(linked by a Billing or Purchase user).", self.name))
            if self.source_invalid:
                raise UserError(self.source_warning)
        if self.currency_id.is_zero(self.expected_amount):
            raise UserError(_("Enter an estimated or actual amount on cost line %s.", self.name))

    def _schedule_approvals(self, users):
        self.ensure_one()
        record = self.sudo() if self.env.user.email else \
            self.sudo().with_context(mail_activity_quick_update=True)
        for user in users:
            record.activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                summary=_("Approve warranty cost %s", self.name),
                note=_("%(type)s on case %(case)s: expected %(amount)s.",
                       type=self._warranty_type_label(), case=record.case_id.name,
                       amount=self._money(self.expected_amount)))

    def _close_activities(self, feedback):
        activities = self.sudo().activity_ids.filtered(
            lambda act: act.activity_type_id == self.env.ref('mail.mail_activity_data_todo'))
        if activities:
            activities.action_feedback(feedback=feedback)

    # ------------------------------------------------------------------ workflow
    def action_submit(self):
        for line in self:
            if line.state != 'draft':
                raise UserError(_("Only Draft cost lines can be submitted."))
            if not self._is_coordinator():
                raise AccessError(_("Only Service Coordinators (Helpdesk users) submit warranty "
                                    "cost lines."))
            line._warranty_check_ready()
            finance = line._warranty_finance_needed()
            eligible = line._eligible_approvers(finance)
            approvers = eligible['manager'] | eligible.get('finance', self.env['res.users'])
            line.sudo().write({
                'state': 'submitted', 'submitted_by_id': self.env.uid,
                'submitted_date': fields.Datetime.now(), 'finance_required': finance,
                'approver_user_ids': [(6, 0, approvers.ids)],
            })
            line._schedule_approvals(approvers)
            line._warranty_log(_("Cost line %(line)s submitted for approval (expected %(amount)s).",
                                 line=line.name, amount=line._money(line.expected_amount)))
        return True

    def action_approve(self):
        for line in self:
            if line.state != 'submitted':
                raise UserError(_("Cost line %s is not waiting for approval.", line.name))
            levels = line._pending_levels_for()
            if not levels:
                raise AccessError(_("You are not a pending approver of cost line %s (named "
                                    "approvers only; the requester, the submitter and an approver "
                                    "of the other level cannot approve).", line.name))
            line._warranty_check_ready()
            if not line.finance_required and line._warranty_finance_needed():
                # The case total rose after this line was submitted.
                eligible = line._eligible_approvers(True, levels=['finance'])
                line.sudo().write({
                    'finance_required': True,
                    'approver_user_ids': [(4, user.id) for user in eligible['finance']],
                })
                line._schedule_approvals(eligible['finance'])
            level = levels[0]
            line.sudo().write({'%s_approved_by_id' % level: self.env.uid,
                               '%s_approved_date' % level: fields.Datetime.now()})
            line._warranty_log(_("Cost line %(line)s: %(level)s approval by %(user)s.",
                                 line=line.name, level=level.capitalize(),
                                 user=self.env.user.name))
            record = line.sudo()
            if all(record['%s_approved_by_id' % lvl] for lvl in line._required_levels()):
                amount = line.expected_amount
                record.write({'state': 'approved', 'approved_amount': amount})
                line._close_activities(_("Approved."))
                line._warranty_log(_("Cost line %(line)s approved: %(amount)s.", line=line.name,
                                     amount=line._money(amount)))
        return True

    def _warranty_reject(self, reason):
        self.ensure_one()
        reason = (reason or '').strip()
        if self.state != 'submitted':
            raise UserError(_("Cost line %s is not waiting for approval.", self.name))
        if not self._pending_levels_for():
            raise AccessError(_("You are not a pending approver of cost line %s.", self.name))
        if not reason:
            raise UserError(_("A reason is required to reject a cost line."))
        self.sudo().write({'state': 'rejected', 'rejected_by_id': self.env.uid,
                           'rejected_date': fields.Datetime.now(), 'rejection_reason': reason})
        self._close_activities(_("Rejected."))
        self._warranty_log(_("Cost line %(line)s rejected by %(user)s. Reason: %(reason)s",
                             line=self.name, user=self.env.user.name, reason=reason))

    def _warranty_reverse(self, reason):
        """The approved figures stay on the line as history; the line stops counting."""
        self.ensure_one()
        reason = (reason or '').strip()
        if self.state != 'approved':
            raise UserError(_("Only approved cost lines can be reversed (%s).", self.name))
        if not self._is_cost_approver():
            raise AccessError(_("Only Warranty Cost Approvers and Finance Approvers can reverse "
                                "cost line %s.", self.name))
        if not reason:
            raise UserError(_("A reason is required to reverse a cost line."))
        amount = self._warranty_raw_actual()
        self.sudo().write({'state': 'reversed', 'reversed_by_id': self.env.uid,
                           'reversed_date': fields.Datetime.now(), 'reversal_reason': reason})
        self._warranty_log(_("Cost line %(line)s reversed by %(user)s (approved %(approved)s, "
                             "actual %(actual)s). Reason: %(reason)s", line=self.name,
                             user=self.env.user.name, approved=self._money(self.approved_amount),
                             actual=self._money(amount), reason=reason))

    def _warranty_record_actual(self, amount, reason, cost_date=None):
        """Actual cost of an approved manual line, within the approved amount (SRS 17: approved
        manual costs require an audit reason). A higher cost needs a new approval."""
        self.ensure_one()
        reason = (reason or '').strip()
        if self.state != 'approved' or not self.actual_is_manual:
            raise UserError(_("Actual cost is recorded on approved Travel, Other and workshop "
                              "Labour lines (%s).", self.name))
        if not (self._is_coordinator() or self._is_cost_approver()):
            raise AccessError(_("Only Service Coordinators and Cost Approvers record actual "
                                "cost."))
        if not reason:
            raise UserError(_("A reason is required to record the actual cost."))
        currency = self.currency_id
        if currency.compare_amounts(amount, 0.0) < 0 or currency.compare_amounts(
                amount, self.approved_amount) > 0:
            raise UserError(_("The actual cost must be between 0 and the approved %(amount)s. For "
                              "a higher cost, reverse this line and submit a new one.",
                              amount=self._money(self.approved_amount)))
        if cost_date and fields.Date.to_date(cost_date) > fields.Date.context_today(self):
            raise UserError(_("The cost incurred date cannot be in the future."))
        before = self.actual_amount
        self.sudo().write(dict({'actual_amount': amount}, **({'cost_date': cost_date}
                                                             if cost_date else {})))
        self._warranty_log(_("Cost line %(line)s: actual changed from %(before)s to %(after)s by "
                             "%(user)s, incurred on %(date)s. Reason: %(reason)s", line=self.name,
                             before=self._money(before), after=self._money(amount),
                             user=self.env.user.name, date=self._warranty_effective_date(),
                             reason=reason))

    # ------------------------------------------------------------------ UI actions
    def _reason_wizard(self, action, title):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': title,
                'res_model': 'warranty.cost.line.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_line_id': self.id, 'default_action': action,
                            'default_amount': self.actual_amount,
                            'default_cost_date': self._warranty_effective_date()}}

    def action_open_reject(self):
        return self._reason_wizard('reject', _("Reject Cost Line"))

    def action_open_reverse(self):
        return self._reason_wizard('reverse', _("Reverse Cost Line"))

    def action_open_record_actual(self):
        return self._reason_wizard('actual', _("Record Actual Cost"))
