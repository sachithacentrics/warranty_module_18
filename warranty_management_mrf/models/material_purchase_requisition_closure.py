from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

from .material_purchase_requisition_approval import RELEASED_STATES
from .material_purchase_requisition_cost import COST_GROUPS
from .material_purchase_requisition_sale import SALE_ACTION

# Phase 5.9 (design doc/part5_9_closure_audit_reporting_design.md rev. 2, K-1 - K-7): the
# computed status Reconciled (all quantities and returns resolved) and the formal closure Closed
# (Closed By / On), freeze of closed requests, controlled reopening, batch closure of a job /
# case, and the case-closure guard. Vendor claims and recovery never block (K-3).
GROUP_HELPDESK = 'helpdesk.group_helpdesk_user'
GROUP_REQUISITION = 'material_purchase_requisitions.group_purchase_requisition_user'
GROUP_REQUISITION_MANAGER = 'material_purchase_requisitions.group_purchase_requisition_manager'
CLOSURE_FIELDS = {'warranty_closed', 'warranty_closed_by_id', 'warranty_closed_date',
                  'warranty_reopened_by_id', 'warranty_reopened_date', 'warranty_reopen_reason',
                  'warranty_reopen_admin_exception'}
FREE_PREFIXES = ('message_', 'activity_', 'website_message')
INVOICE_STATUSES = [
    ('none', 'No Customer Billing'),
    ('pending', 'Pending Invoicing'),
    ('invoiced', 'Invoiced'),
]


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    warranty_mrf_status = fields.Selection(
        selection_add=[('returned',), ('reconciled', 'Reconciled'), ('closed',)],
        ondelete={'reconciled': 'set null'}, tracking=True)
    # Audit (approved): before / after values of the important header fields.
    approval_round = fields.Integer(tracking=True)
    submitted_by_id = fields.Many2one(tracking=True)
    approved_by_id = fields.Many2one(tracking=True)
    approved_amount = fields.Monetary(tracking=True)
    estimated_cost = fields.Monetary(tracking=True)
    coverage_status = fields.Selection(tracking=True)
    employee_id = fields.Many2one(tracking=True)
    warranty_closed = fields.Boolean(string='Formally Closed', readonly=True, copy=False,
                                     tracking=True)
    warranty_closed_by_id = fields.Many2one('res.users', string='Closed By', readonly=True,
                                            copy=False, tracking=True)
    warranty_closed_date = fields.Datetime(string='Closed On', readonly=True, copy=False,
                                           tracking=True)
    warranty_reopened_by_id = fields.Many2one('res.users', string='Last Reopened By',
                                              readonly=True, copy=False, tracking=True)
    warranty_reopened_date = fields.Datetime(string='Last Reopened On', readonly=True,
                                             copy=False)
    warranty_reopen_reason = fields.Text(string='Last Reopen Reason', readonly=True, copy=False,
                                         tracking=True)
    warranty_reopen_admin_exception = fields.Boolean(string='Reopened by Administrator Exception',
                                                     readonly=True, copy=False)
    warranty_invoice_status = fields.Selection(
        INVOICE_STATUSES, string='Customer Invoicing', compute='_compute_warranty_invoice_status',
        compute_sudo=True, groups=COST_GROUPS,
        help="Financial follow-up of customer-paid parts (posted invoices net of credit notes "
             "against delivered quantities); separate from the operational closure.")
    warranty_close_problems = fields.Text(string='Closure Blockers',
                                          compute='_compute_warranty_close_info')
    can_warranty_close = fields.Boolean(compute='_compute_warranty_close_info')
    can_warranty_reopen = fields.Boolean(compute='_compute_warranty_close_info')

    @api.depends('warranty_closed')
    def _compute_warranty_mrf_status(self):
        """K-7: the computed end state of 5.6 is Reconciled; Closed only after the formal close."""
        super()._compute_warranty_mrf_status()
        for mrf in self.filtered('is_warranty_mrf'):
            if mrf.warranty_closed:
                mrf.warranty_mrf_status = 'closed'
            elif mrf.warranty_mrf_status == 'closed':
                mrf.warranty_mrf_status = 'reconciled'

    def _compute_warranty_invoice_status(self):
        for mrf in self:
            mrf.warranty_invoice_status = mrf._warranty_invoice_state()

    def _warranty_invoice_state(self):
        """K-2: delivered customer-paid quantities against posted invoices (net of posted credit
        notes), per quotation line in its unit."""
        self.ensure_one()
        lines = self.sudo().requisition_line_ids.filtered(
            lambda line: line.requisition_type == SALE_ACTION and not line.chargeable_declined)
        sale_lines = lines.sale_line_ids
        if not sale_lines.filtered('qty_delivered'):
            return 'none'
        for sale_line in sale_lines:
            invoiced = 0.0
            for aml in sale_line.invoice_lines.filtered(lambda aml: aml.parent_state == 'posted'):
                qty = aml.product_uom_id._compute_quantity(aml.quantity, sale_line.product_uom)
                invoiced += qty if aml.move_id.move_type == 'out_invoice' else -qty
            if float_compare(invoiced, sale_line.qty_delivered,
                             precision_rounding=sale_line.product_uom.rounding or 0.01) < 0:
                return 'pending'
        return 'invoiced'

    @api.depends_context('uid')
    @api.depends('warranty_closed', 'warranty_mrf_status', 'state')
    def _compute_warranty_close_info(self):
        for mrf in self:
            problems = mrf._warranty_close_problems() if mrf.is_warranty_mrf else []
            mrf.warranty_close_problems = '\n'.join(problems) or False
            mrf.can_warranty_close = mrf.is_warranty_mrf and not mrf.warranty_closed \
                and mrf.state != 'cancel' and not problems and mrf._warranty_can_close_user()
            mrf.can_warranty_reopen = mrf.warranty_closed and mrf._warranty_can_reopen_user()

    # ------------------------------------------------------------------ K-2 checks
    def _warranty_operational_problems(self):
        """Open operational obligations (K-2 / K-6): material items (5.6: approval, release
        rules, issue, usage / installation / resolution), open return transfers, stock moves of
        the request not done, open RFQs / purchase lines not received. Vendor claims, credit
        notes and recoveries are never checked (K-3)."""
        self.ensure_one()
        mrf = self.sudo()
        if mrf.state == 'cancel':
            return []
        problems = list(mrf._warranty_material_problems())
        lines = mrf.requisition_line_ids
        if any(float_compare(line.in_return_qty, 0.0, precision_rounding=0.0001) > 0
               for line in lines):
            pickings = mrf.warranty_consumption_ids.picking_id.filtered(
                lambda picking: picking.state not in ('done', 'cancel'))
            problems.append(_("return transfer(s) not validated by the store: %s",
                              ', '.join(pickings.mapped('name')) or '-'))
        moves = (lines.warranty_move_ids | lines.sale_line_ids.move_ids).filtered(
            lambda move: move.state not in ('done', 'cancel'))
        if moves:
            refs = sorted(set(moves.mapped(lambda move: move.picking_id.name or move.reference
                                           or move.name)))
            problems.append(_("stock movements not done: %s", ', '.join(refs)))
        purchase_lines = lines.warranty_purchase_line_ids.filtered(
            lambda pol: pol.order_id.state != 'cancel')
        rfqs = purchase_lines.order_id.filtered(lambda order: order.state in (
            'draft', 'sent', 'to approve'))
        if rfqs:
            problems.append(_("requests for quotation not confirmed or cancelled: %s",
                              ', '.join(rfqs.mapped('name'))))
        not_received = purchase_lines.filtered(
            lambda pol: pol.order_id.state in ('purchase', 'done') and float_compare(
                pol.qty_received, pol.product_qty,
                precision_rounding=pol.product_uom.rounding or 0.01) < 0)
        if not_received:
            problems.append(_("purchase orders not fully received: %s",
                              ', '.join(not_received.order_id.mapped('name'))))
        return problems

    def _warranty_close_problems(self):
        self.ensure_one()
        if self.state == 'cancel':
            return [_("cancelled requests are final and are not closed")]
        if self.warranty_closed:
            return [_("already closed")]
        problems = self._warranty_operational_problems()
        if self.company_id.warranty_mrf_close_requires_invoice \
                and self._warranty_invoice_state() == 'pending':
            problems.append(_("customer-paid parts are not fully invoiced (posted invoices) and "
                              "the company requires the customer invoice before closure"))
        return problems

    # ------------------------------------------------------------------ K-1 close
    def _warranty_can_close_user(self, user=None):
        user = user or self.env.user
        return (user.has_group(GROUP_HELPDESK) or user.has_group(GROUP_REQUISITION)) \
            and self.company_id in user.company_ids

    def _warranty_close(self):
        for mrf in self:
            if not mrf.is_warranty_mrf:
                raise UserError(_("Only warranty Material Requests are closed here."))
            if not mrf._warranty_can_close_user():
                raise AccessError(_("Only Service Coordinators (Helpdesk users) and Requisition / "
                                    "Store users close warranty Material Requests."))
            problems = mrf._warranty_close_problems()
            if problems:
                raise UserError(_("Material Request %(mrf)s cannot be closed:\n- %(problems)s",
                                  mrf=mrf.name, problems='\n- '.join(problems)))
            mrf.sudo().write({'warranty_closed': True, 'warranty_closed_by_id': self.env.uid,
                              'warranty_closed_date': fields.Datetime.now()})
            mrf._warranty_material_log(_("Material Request %(mrf)s closed by %(user)s.",
                                         mrf=mrf.name, user=self.env.user.name))
        return True

    def action_warranty_close(self):
        self.ensure_one()
        return self._warranty_close_wizard(self)

    @api.model
    def _warranty_close_wizard(self, requests, origin=False):
        wizard = self.env['warranty.mrf.close.wizard'].create({
            'origin': origin or (requests[:1].name if len(requests) == 1 else False),
            'line_ids': [(0, 0, {'requisition_id': mrf.id}) for mrf in requests.filtered(
                lambda mrf: mrf.is_warranty_mrf and mrf.state != 'cancel'
                and not mrf.warranty_closed)],
        })
        if not wizard.line_ids:
            raise UserError(_("There is no open warranty Material Request to close."))
        return {'type': 'ir.actions.act_window', 'name': _("Close Material Requests"),
                'res_model': wizard._name, 'res_id': wizard.id, 'view_mode': 'form',
                'target': 'new'}

    # ------------------------------------------------------------------ K-5 reopen
    def _warranty_can_reopen_user(self, user=None, admin_exception=False):
        user = user or self.env.user
        if self.company_id not in user.company_ids:
            return False
        if admin_exception:
            return user.has_group('base.group_system')
        return user.has_group(GROUP_REQUISITION_MANAGER) and user != self.warranty_closed_by_id \
            or user.has_group('base.group_system')

    def _warranty_reopen(self, reason, admin_exception=False):
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to reopen a closed Material Request."))
        for mrf in self:
            if not mrf.warranty_closed:
                raise UserError(_("Material Request %s is not closed.", mrf.name))
            user = self.env.user
            if admin_exception:
                if not user.has_group('base.group_system'):
                    raise AccessError(_("The administrator exception is reserved to Settings "
                                        "administrators."))
            elif not user.has_group(GROUP_REQUISITION_MANAGER):
                raise AccessError(_("Only Requisition Managers reopen closed Material Requests "
                                    "(administrators: administrator exception with a reason)."))
            elif user == mrf.warranty_closed_by_id:
                raise AccessError(_("The person who closed %s cannot reopen it; another "
                                    "Requisition Manager (or the administrator exception) is "
                                    "required.", mrf.name))
            if mrf.company_id not in user.company_ids:
                raise AccessError(_("Material Request %s belongs to another company.", mrf.name))
            mrf.sudo().write({'warranty_closed': False, 'warranty_reopened_by_id': user.id,
                              'warranty_reopened_date': fields.Datetime.now(),
                              'warranty_reopen_reason': reason,
                              'warranty_reopen_admin_exception': bool(admin_exception)})
            mrf._warranty_material_log(_(
                "Material Request %(mrf)s reopened by %(user)s%(exception)s (closed by %(closer)s "
                "on %(date)s). Reason: %(reason)s", mrf=mrf.name, user=user.name,
                exception=_(" (administrator exception)") if admin_exception else '',
                closer=mrf.warranty_closed_by_id.name or '-',
                date=fields.Datetime.to_string(mrf.warranty_closed_date) or '-', reason=reason))
        return True

    def action_warranty_reopen(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _("Reopen Material Request"),
                'res_model': 'warranty.mrf.reopen.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_requisition_id': self.id}}

    # ------------------------------------------------------------------ K-4 freeze
    def _warranty_check_not_closed(self):
        closed = self.filtered(lambda mrf: mrf.is_warranty_mrf and mrf.warranty_closed)
        if closed:
            raise UserError(_("Material Request %s is closed: material, coverage, issue and "
                              "quotation changes need the controlled Reopen first.",
                              closed[0].name))

    def _warranty_material_open_error(self):
        if self.warranty_closed:
            return _("Material Request %s is closed: reopen it (Requisition Manager, reason) to "
                     "correct its materials.", self.name)
        return super()._warranty_material_open_error()

    def _warranty_check_coverage_open(self):
        self._warranty_check_not_closed()
        return super()._warranty_check_coverage_open()

    def action_request_coverage_decision(self):
        self._warranty_check_not_closed()
        return super().action_request_coverage_decision()

    def _warranty_fulfil(self):
        self._warranty_check_not_closed()
        return super()._warranty_fulfil()

    def action_create_parts_quotation(self):
        self._warranty_check_not_closed()
        return super().action_create_parts_quotation()

    def _warranty_decline_chargeable(self, lines, reason):
        self._warranty_check_not_closed()
        return super()._warranty_decline_chargeable(lines, reason)

    def _warranty_approve_release_exception(self, order, reason):
        self._warranty_check_not_closed()
        return super()._warranty_approve_release_exception(order, reason)

    def _warranty_check_release(self):
        self._warranty_check_not_closed()
        return super()._warranty_check_release()

    def action_cancel(self):
        self._warranty_check_not_closed()
        return super().action_cancel()

    def reset_draft(self):
        self._warranty_check_not_closed()
        return super().reset_draft()

    def action_received(self):
        self._warranty_check_not_closed()
        return super().action_received()

    def write(self, vals):
        if not self.env.su:
            keys = {key for key in vals if not key.startswith(FREE_PREFIXES)}
            if keys & CLOSURE_FIELDS:
                raise UserError(_("Closure fields are set by Close / Reopen only."))
            if keys:
                self._warranty_check_not_closed()
        return super().write(vals)


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    def write(self, vals):
        if not self.env.su:
            self.requisition_id._warranty_check_not_closed()
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.su:
            lines.requisition_id._warranty_check_not_closed()
        return lines

    def unlink(self):
        if not self.env.su:
            self.requisition_id._warranty_check_not_closed()
        return super().unlink()


class ResCompany(models.Model):
    _inherit = 'res.company'

    warranty_mrf_close_requires_invoice = fields.Boolean(
        string='Require Customer Invoice to Close',
        help="Warranty Material Requests with customer-paid parts can only be closed when the "
             "delivered quantities are invoiced (posted invoices). Off: invoicing is followed up "
             "separately (Customer Invoicing status).")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_mrf_close_requires_invoice = fields.Boolean(
        related='company_id.warranty_mrf_close_requires_invoice', readonly=False,
        help="Enable this option to require customer-paid materials to be invoiced before "
             "closing a material request. If disabled, the request can be closed when all "
             "operational requirements are completed.")


class ClosureRecordsMixin(models.AbstractModel):
    """Close Material Requests on a service job / warranty case (batch, validated, confirmed)."""
    _inherit = 'warranty.mrf.cost.totals.mixin'

    def action_warranty_close_requests(self):
        self.ensure_one()
        return self.env['material.purchase.requisition']._warranty_close_wizard(
            self.sudo().material_request_ids.with_env(self.env), origin=self.display_name)


def _compute_warranty_has_open_requests(records):
    """Display only: the Close Material Requests button follows the wizard's selection."""
    for record in records:
        record.warranty_has_open_requests = bool(record.material_request_ids.filtered(
            lambda mrf: mrf.is_warranty_mrf and mrf.state != 'cancel' and not mrf.warranty_closed))


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    warranty_has_open_requests = fields.Boolean(
        compute='_compute_warranty_has_open_requests', compute_sudo=True)

    @api.depends('material_request_ids.warranty_closed', 'material_request_ids.state')
    def _compute_warranty_has_open_requests(self):
        _compute_warranty_has_open_requests(self)


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    warranty_has_open_requests = fields.Boolean(
        compute='_compute_warranty_has_open_requests', compute_sudo=True)

    @api.depends('material_request_ids.warranty_closed', 'material_request_ids.state')
    def _compute_warranty_has_open_requests(self):
        _compute_warranty_has_open_requests(self)

    def write(self, vals):
        if vals.get('state') == 'closed':
            self._warranty_check_requests_closed()
        return super().write(vals)

    def _warranty_check_requests_closed(self):
        """K-6: a case is not closed while a linked request (not cancelled) is not formally
        closed; open obligations and requests ready to close are listed. Vendor claims never
        block."""
        for case in self:
            requests = case.sudo().material_request_ids.filtered(
                lambda mrf: mrf.is_warranty_mrf and mrf.state != 'cancel'
                and not mrf.warranty_closed)
            if not requests:
                continue
            blocked = []
            ready = []
            for mrf in requests:
                problems = mrf._warranty_operational_problems()
                if problems:
                    blocked.append('%s: %s' % (mrf.name, '; '.join(problems)))
                else:
                    ready.append(mrf.name)
            message = _("Warranty case %s cannot be closed while Material Requests are not "
                        "closed.", case.name)
            if blocked:
                message += '\n' + _("Open obligations:") + '\n- ' + '\n- '.join(blocked)
            if ready:
                message += '\n' + _("Ready to close (use Close Material Requests): %s",
                                    ', '.join(ready))
            raise UserError(message)
