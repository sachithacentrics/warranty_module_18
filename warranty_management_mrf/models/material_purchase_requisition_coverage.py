from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.warranty_management.models.res_company import get_valid_service_alert_users
from odoo.addons.warranty_management_helpdesk.models.warranty_case import CHARGEABLE_CASE_TYPES

# Phase 5.2 (mapping 5.2, SRS 10.7 Coverage Type, G4).
COVERAGE_TYPES = [
    ('covered', 'Covered'),
    ('not_covered', 'Not Covered'),
    ('pending', 'Pending Coverage Decision'),
]
COVERAGE_STATUSES = [
    ('no_lines', 'No Lines'),
    ('pending', 'Pending Decision'),
    ('covered', 'Covered'),
    ('not_covered', 'Not Covered'),
    ('mixed', 'Mixed'),
]
COVERAGE_DECISIONS = [
    ('covered', 'Covered'),
    ('goodwill', 'Free of Charge'),
    ('not_covered', 'Not Covered'),
]
# Case eligibility results whose policy covered items are Covered by default (mapping D7).
COVERED_RESULTS = ('eligible', 'partial')
COVERAGE_DECISION_FIELDS = ('coverage_type', 'goodwill', 'coverage_decided_by_id',
                            'coverage_decision_date', 'coverage_decision_reason')
# Line fields locked once a warranty request is submitted (T2.6).
LOCKED_LINE_FIELDS = ('product_id',) + COVERAGE_DECISION_FIELDS
# Phase 5.3 (Q4): the only line fields still editable after submission, by these groups.
SUBMITTED_LINE_FIELDS = {'requisition_type', 'partner_id', 'description', 'lot_ids'}
SUBMITTED_LINE_GROUPS = ('material_purchase_requisitions.group_purchase_requisition_user',
                         'stock.group_stock_user', 'purchase.group_purchase_user')


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    coverage_status = fields.Selection(
        COVERAGE_STATUSES, string='Coverage', compute='_compute_coverage_status', store=True,
        help="Coverage of the request lines (warranty requests only).")
    coverage_pending_count = fields.Integer(string='Pending Lines',
                                            compute='_compute_coverage_counts')
    coverage_covered_count = fields.Integer(string='Covered Lines',
                                            compute='_compute_coverage_counts')
    coverage_not_covered_count = fields.Integer(string='Not Covered Lines',
                                                compute='_compute_coverage_counts')
    coverage_requested_by_id = fields.Many2one(
        'res.users', string='Coverage Decision Requested By', readonly=True, copy=False)
    coverage_activity_ids = fields.Many2many(
        'mail.activity', 'warranty_mrf_coverage_activity_rel', 'requisition_id', 'activity_id',
        string='Coverage Decision Activities', readonly=True, copy=False,
        context={'active_test': False})
    can_decide_coverage = fields.Boolean(compute='_compute_can_decide_coverage')

    @api.depends('is_warranty_mrf', 'requisition_line_ids.coverage_type')
    def _compute_coverage_status(self):
        for mrf in self:
            types = set(mrf.requisition_line_ids.mapped('coverage_type'))
            if not mrf.is_warranty_mrf:
                mrf.coverage_status = False
            elif not types:
                mrf.coverage_status = 'no_lines'
            elif 'pending' in types:
                mrf.coverage_status = 'pending'
            elif len(types) == 1:
                mrf.coverage_status = types.pop()
            else:
                mrf.coverage_status = 'mixed'

    @api.depends('requisition_line_ids.coverage_type')
    def _compute_coverage_counts(self):
        for mrf in self:
            types = mrf.requisition_line_ids.mapped('coverage_type')
            mrf.coverage_pending_count = types.count('pending')
            mrf.coverage_covered_count = types.count('covered')
            mrf.coverage_not_covered_count = types.count('not_covered')

    @api.depends_context('uid')
    @api.depends('is_warranty_mrf', 'state', 'requisition_line_ids', 'create_uid', 'employee_id',
                 'coverage_requested_by_id', 'company_id.warranty_case_approver_ids',
                 'company_id.warranty_case_approval_required')
    def _compute_can_decide_coverage(self):
        for mrf in self:
            mrf.can_decide_coverage = mrf.is_warranty_mrf and mrf.state == 'draft' \
                and bool(mrf.requisition_line_ids) and mrf._warranty_is_coverage_reviewer()

    # ------------------------------------------------------------------ reviewers
    def _warranty_coverage_excluded_users(self):
        """No self-decision (Q40 pattern): the creator, the requester and the user who asked
        for the decision."""
        self.ensure_one()
        # sudo: the requester's user is read for the check only.
        return self.create_uid | self.sudo().employee_id.user_id | self.coverage_requested_by_id

    def _warranty_coverage_reviewers(self):
        """Mapping D7: the Warranty Case Approval Users of the company, except the excluded
        users."""
        self.ensure_one()
        users = get_valid_service_alert_users(self.company_id.warranty_case_approver_ids,
                                              self.company_id)
        return users - self._warranty_coverage_excluded_users()

    def _warranty_is_coverage_reviewer(self, user=None):
        """Warranty Case Approval Required (company, Part 3 S1 / S2): the coverage reviewers;
        off: Helpdesk users of the company. Never the excluded users."""
        self.ensure_one()
        user = user or self.env.user
        if user in self._warranty_coverage_excluded_users():
            return False
        if self.company_id.warranty_case_approval_required:
            return user in self._warranty_coverage_reviewers()
        return user.has_group('helpdesk.group_helpdesk_user') \
            and self.company_id in user.company_ids

    # ------------------------------------------------------------------ actions
    def _warranty_check_coverage_open(self):
        for mrf in self:
            if not mrf.is_warranty_mrf:
                raise UserError(_("Coverage decisions apply to warranty Material Requests only."))
            if mrf.state != 'draft':
                raise UserError(_("The coverage of Material Request %(mrf)s is locked: it was "
                                  "submitted.", mrf=mrf.name))

    def action_request_coverage_decision(self):
        """Request Coverage Decision: one To-Do per coverage reviewer, no duplicates while
        open activities exist."""
        for mrf in self:
            mrf._warranty_check_coverage_open()
            pending = mrf.requisition_line_ids.filtered(lambda line: line.coverage_type == 'pending')
            if not pending:
                raise UserError(_("Material Request %(mrf)s has no line pending a coverage "
                                  "decision.", mrf=mrf.name))
            open_activities = mrf.coverage_activity_ids.exists().filtered('active')
            if open_activities:
                mrf._message_log(body=_("Coverage decision already requested from %(users)s.",
                                        users=', '.join(open_activities.user_id.mapped('name'))))
                continue
            mrf.coverage_requested_by_id = self.env.user
            reviewers = mrf._warranty_coverage_reviewers()
            if not reviewers:
                if mrf.company_id.warranty_case_approval_required:
                    raise UserError(_("No coverage reviewer (Warranty Case Approval User other "
                                      "than you and the requester) is configured for "
                                      "%(company)s.", company=mrf.company_id.name))
                mrf._message_log(body=_("Coverage decision requested: Helpdesk users of "
                                        "%(company)s can decide.", company=mrf.company_id.name))
                continue
            products = ', '.join(pending.mapped('product_id.display_name'))
            # The assignment email is sent from the requester: without an email address the
            # activities are still assigned, without email (Part 3 pattern).
            record = mrf if self.env.user.email else \
                mrf.with_context(mail_activity_quick_update=True)
            activities = self.env['mail.activity']
            for reviewer in reviewers:
                activities |= record.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=reviewer.id,
                    summary=_("Decide warranty coverage of Material Request %s", mrf.name),
                    note=_("Pending coverage: %s", products))
            mrf.coverage_activity_ids = [(4, activity.id) for activity in activities]
            mrf._message_log(body=_("Coverage decision requested from %(users)s for %(products)s.",
                                    users=', '.join(reviewers.mapped('name')), products=products))

    def action_decide_coverage(self):
        self.ensure_one()
        self._warranty_check_coverage_open()
        if not self._warranty_is_coverage_reviewer():
            raise AccessError(self._warranty_reviewer_error())
        return {
            'type': 'ir.actions.act_window',
            'name': _("Decide Coverage"),
            'res_model': 'warranty.mrf.coverage.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_requisition_id': self.id},
        }

    def _warranty_reviewer_error(self):
        return _("Only coverage reviewers (Warranty Case Approval Users) can decide the coverage "
                 "of %(mrf)s; its creator, requester and the user who requested the decision "
                 "cannot.", mrf=self.name)

    def _warranty_decide_coverage(self, lines, decision, reason):
        """Mark the lines Covered / Covered (Goodwill) / Not Covered with a reason (mapping 5.2,
        D7); logged on the request, the case and the job."""
        self.ensure_one()
        self._warranty_check_coverage_open()
        if not self._warranty_is_coverage_reviewer():
            raise AccessError(self._warranty_reviewer_error())
        if not (reason or '').strip():
            raise UserError(_("A reason is required for a coverage decision."))
        if lines.filtered(lambda line: line.requisition_id != self):
            raise UserError(_("Only lines of %(mrf)s can be decided here.", mrf=self.name))
        if not lines:
            raise UserError(_("Select the lines of %(mrf)s to decide.", mrf=self.name))
        lines.with_context(warranty_mrf_coverage_decision=True).write({
            'coverage_type': 'not_covered' if decision == 'not_covered' else 'covered',
            'goodwill': decision == 'goodwill',
            'coverage_decided_by_id': self.env.uid,
            'coverage_decision_date': fields.Datetime.now(),
            'coverage_decision_reason': reason.strip(),
        })
        text = _("Coverage decision by %(user)s: %(products)s - %(decision)s. Reason: %(reason)s",
                 user=self.env.user.name, products=', '.join(lines.mapped('product_id.display_name')),
                 decision=dict(COVERAGE_DECISIONS)[decision], reason=reason.strip())
        self._message_log(body=text)
        for record in (self.warranty_case_id, self.warranty_service_job_id):
            if record:
                record.sudo()._message_log(body=_("Material Request %(mrf)s: %(text)s",
                                                  mrf=self.name, text=text))
        if not self.coverage_pending_count:
            activities = self.coverage_activity_ids.exists().filtered('active')
            if activities:
                # sudo: activities of the other reviewers are closed by the system.
                activities.sudo().action_feedback(
                    feedback=_("Coverage decided by %s.", self.env.user.name))

    def requisition_confirm(self):
        """Submit (vendor Confirm) is refused while warranty lines are pending a coverage
        decision (T2.3)."""
        self.filtered('is_warranty_mrf')._warranty_check_coverage_decided()
        return super().requisition_confirm()

    def _warranty_check_coverage_decided(self):
        for mrf in self:
            pending = mrf.requisition_line_ids.filtered(lambda line: line.coverage_type == 'pending')
            if pending:
                raise UserError(_("Material Request %(mrf)s cannot be confirmed: the coverage of "
                                  "%(products)s is pending. Use Request Coverage Decision.",
                                  mrf=mrf.name,
                                  products=', '.join(pending.mapped('product_id.display_name'))))


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    is_warranty_mrf = fields.Boolean(related='requisition_id.is_warranty_mrf')
    coverage_type = fields.Selection(
        COVERAGE_TYPES, string='Coverage Type', compute='_compute_coverage_default', store=True,
        readonly=True,
        help="Default from the warranty case and policy (mapping D7); Pending lines need a "
             "coverage decision before the request can be confirmed.")
    covered_under_warranty = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')], string='Covered Under Warranty?',
        compute='_compute_covered_under_warranty')
    coverage_default_reason = fields.Char(
        string='Coverage Basis', compute='_compute_coverage_default', store=True, readonly=True)
    goodwill = fields.Boolean(
        string='Goodwill', compute='_compute_coverage_default', store=True, readonly=True,
        help="Covered as goodwill by a coverage reviewer")
    coverage_decided_by_id = fields.Many2one(
        'res.users', string='Coverage Decided By', compute='_compute_coverage_default',
        store=True, readonly=True)
    coverage_decision_date = fields.Datetime(
        string='Coverage Decision Date', compute='_compute_coverage_default', store=True,
        readonly=True)
    coverage_decision_reason = fields.Text(
        string='Coverage Decision Reason', compute='_compute_coverage_default', store=True,
        readonly=True)

    @api.depends('product_id', 'requisition_id.warranty_case_id')
    def _compute_coverage_default(self):
        """A new product (or a new warranty link) resets the line to its default coverage."""
        for line in self:
            coverage, basis = line._warranty_default_coverage()
            line.update({
                'coverage_type': coverage,
                'coverage_default_reason': basis,
                'goodwill': False,
                'coverage_decided_by_id': False,
                'coverage_decision_date': False,
                'coverage_decision_reason': False,
            })

    def _warranty_default_coverage(self):
        """Mapping D7 default rules: chargeable case -> Not Covered; excluded item product of
        the policy -> Not Covered; covered item product on an Eligible / Partial case ->
        Covered; otherwise Pending."""
        self.ensure_one()
        # sudo: requesters (technicians) read the case policy for the classification only.
        case = self.requisition_id.warranty_case_id.sudo()
        if not case:
            return False, False
        if case.state == 'chargeable' or case.case_type in CHARGEABLE_CASE_TYPES:
            return 'not_covered', _("Chargeable warranty case")
        if not self.product_id:
            return 'pending', False
        policies = case.warranty_card_id.policy_id | case.service_card_ids.policy_id
        excluded = policies.excluded_item_ids.filtered(
            lambda item: item.product_id == self.product_id)
        if excluded:
            return 'not_covered', _("Excluded item %s of the warranty policy", excluded[0].name)
        covered = policies.covered_item_ids.filtered(
            lambda item: item.product_id == self.product_id)
        if covered and case.eligibility_result in COVERED_RESULTS:
            return 'covered', _("Covered item %s of the warranty policy", covered[0].name)
        if covered:
            return 'pending', _("Covered item %s, but the case is not Eligible", covered[0].name)
        return 'pending', _("Not listed in the warranty policy")

    @api.depends('coverage_type')
    def _compute_covered_under_warranty(self):
        for line in self:
            line.covered_under_warranty = {'covered': 'yes', 'not_covered': 'no'}.get(
                line.coverage_type, False)

    # ------------------------------------------------------------------ locks
    def _warranty_check_coverage_unlocked(self):
        submitted = self.requisition_id.filtered(
            lambda mrf: mrf.is_warranty_mrf and mrf.state != 'draft')
        if submitted:
            raise UserError(_("The lines and coverage of Material Request %(mrf)s are locked: it "
                              "was submitted. Request further parts with a new Material Request.",
                              mrf=submitted[0].name))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('warranty_mrf_coverage_decision'):
            for vals in vals_list:
                for field in COVERAGE_DECISION_FIELDS:
                    vals.pop(field, None)
        lines = super().create(vals_list)
        lines._warranty_check_coverage_unlocked()
        return lines

    def write(self, vals):
        if any(field in vals for field in COVERAGE_DECISION_FIELDS) \
                and not self.env.context.get('warranty_mrf_coverage_decision') \
                and any(self.mapped('is_warranty_mrf')):
            raise UserError(_("The coverage of a warranty Material Request line is set with "
                              "Decide Coverage by a coverage reviewer."))
        if any(field in vals for field in LOCKED_LINE_FIELDS):
            self._warranty_check_coverage_unlocked()
        if not self.env.su:
            self._warranty_check_submitted_line_write(vals)
        return super().write(vals)

    def _warranty_check_submitted_line_write(self, vals):
        """Phase 5.3 (control 3, Q4): after submission the lines of a warranty request are
        locked; Requisition / Inventory / Purchase users may still set the line type, vendors,
        description and requested serials until the picking is created."""
        submitted = self.filtered(lambda line: line.is_warranty_mrf
                                  and line.requisition_id.state != 'draft')
        if not submitted:
            return
        if set(vals) - SUBMITTED_LINE_FIELDS:
            raise UserError(_("The lines of Material Request %(mrf)s are locked: it was "
                              "submitted. Withdraw it or reset it to New to change products, "
                              "quantities or costs (a new approval round follows).",
                              mrf=submitted[0].requisition_id.name))
        if not any(self.env.user.has_group(group) for group in SUBMITTED_LINE_GROUPS) \
                or submitted.requisition_id.filtered(
                    lambda mrf: mrf.state not in ('dept_confirm', 'ir_approve', 'approve')):
            raise UserError(_("The lines of Material Request %(mrf)s are locked: it was "
                              "submitted.", mrf=submitted[0].requisition_id.name))

    def unlink(self):
        self._warranty_check_coverage_unlocked()
        return super().unlink()
