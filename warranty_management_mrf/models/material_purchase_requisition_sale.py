from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .material_purchase_requisition_approval import RELEASED_STATES, WAITING_STATES

# Phase 5.4 (mapping 5.4, D8, D9): commercial control of Not Covered lines.
CHARGEABLE_STATES = [
    ('to_quote', 'To Quote'),
    ('waiting_customer', 'Waiting Customer'),
    ('waiting_payment', 'Waiting Payment'),
    ('released', 'Released'),
    ('released_exception', 'Released (Exception)'),
    ('blocked', 'Release Blocked (Request Not Valid)'),
    ('declined', 'Customer Declined'),
]
# Figure 7 D2: coverage conditions of rules that explicitly approve Not Covered materials.
NOT_COVERED_CONDITIONS = ('not_covered', 'only_not_covered')
# Request line fields fixed while the line is on a confirmed customer order.
SOLD_LINE_LOCKED = {'product_id', 'qty', 'uom', 'coverage_type', 'goodwill'}
RELEASED_CHARGEABLE_STATES = ('released', 'released_exception')
RELEASE_TRIGGERS = [
    ('confirmation', 'On Quotation Confirmation'),
    ('payment', 'On Payment'),
]
# Line action of Not Covered lines quoted to the customer: delivered by the quotation's own
# delivery (D8), skipped by the vendor Create Picking and PO (internal / purchase lines only).
SALE_ACTION = 'sale'
SALE_ORDER_PROTECTED = {'warranty_mrf_id', 'warranty_release_trigger',
                        'warranty_release_exception_by_id', 'warranty_release_exception_date',
                        'warranty_release_exception_reason'}
SALE_LINE_LOCKED = {'product_id', 'product_uom_qty', 'product_uom', 'warranty_mrf_line_id'}


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    parts_quotation_ids = fields.One2many('sale.order', 'warranty_mrf_id',
                                          string='Parts Quotations', readonly=True)
    parts_quotation_count = fields.Integer(compute='_compute_parts_quotation')
    parts_delivery_count = fields.Integer(compute='_compute_parts_quotation')
    can_create_parts_quotation = fields.Boolean(compute='_compute_parts_quotation')
    can_decline_chargeable = fields.Boolean(compute='_compute_parts_quotation')
    can_approve_release_exception = fields.Boolean(compute='_compute_can_release_exception')

    @api.depends('parts_quotation_ids', 'requisition_line_ids.chargeable_state', 'state',
                 'approval_round', 'approval_signature')
    def _compute_parts_quotation(self):
        for mrf in self:
            # sudo: counts shown to users without sales rights.
            orders = mrf.sudo().parts_quotation_ids
            mrf.parts_quotation_count = len(orders)
            mrf.parts_delivery_count = len(orders.picking_ids)
            states = mrf.requisition_line_ids.mapped('chargeable_state')
            mrf.can_create_parts_quotation = mrf.is_warranty_mrf and 'to_quote' in states \
                and not mrf._warranty_quotation_error()
            mrf.can_decline_chargeable = mrf.is_warranty_mrf \
                and mrf.state in WAITING_STATES + ('approve', 'stock') \
                and bool({'to_quote', 'waiting_customer'} & set(states))

    @api.depends_context('uid')
    @api.depends('requisition_line_ids.chargeable_state',
                 'company_id.warranty_mrf_release_exception_user_ids')
    def _compute_can_release_exception(self):
        for mrf in self:
            mrf.can_approve_release_exception = bool(mrf._warranty_exception_orders()) \
                and mrf._warranty_is_release_exception_user()

    # ------------------------------------------------------------------ release rule
    def _warranty_commercial_release_error(self):
        """Figure 7 D2: Covered and Not Covered lines follow their own release conditions. Not
        Covered lines are never issued by the internal picking (_warranty_fulfil_lines), only by
        the parts quotation's delivery (D8), so they no longer hold back the covered lines."""
        self.ensure_one()
        return False

    def _warranty_chargeable_request_error(self):
        """Figure 7 D2 (Not Covered -> customer quotation, N5): why the Not Covered lines of the
        request may not be quoted or released now (False: they may). The request must be
        submitted with its coverage decided (Pending blocks the submission), unchanged since,
        and not rejected, withdrawn or cancelled. A matching rule that explicitly approves Not
        Covered materials (coverage condition Not Covered Lines Present / Only Not Covered
        Lines with approval levels) makes them wait for the final approval; the Requisition
        workflow (matrix off) too."""
        self.ensure_one()
        if not self.is_warranty_mrf:
            return _("Parts quotations are created for warranty Material Requests.")
        if self.state in RELEASED_STATES:
            return self._warranty_approved_error()
        if self.state not in WAITING_STATES:
            status = dict(self._fields['state']._description_selection(self.env)).get(
                self.state, self.state)
            return _("Material Request %(mrf)s is %(status)s: customer quotations and the release "
                     "of Not Covered materials need a submitted request (not approved or "
                     "submitted yet, or rejected / withdrawn / cancelled).",
                     mrf=self.name, status=status)
        if self.warranty_approval_mode != 'matrix' or not self.approval_round:
            return _("Material Request %s is not approved yet: with the Requisition workflow the "
                     "Not Covered materials are quoted after the final approval.", self.name)
        if self.approval_signature != self._warranty_line_signature():
            return _("The lines of %s changed after submission.", self.name)
        explicit = self._warranty_round_lines().filtered(
            lambda line: line.level != 'none').rule_ids.filtered(
            lambda rule: rule.coverage_condition in NOT_COVERED_CONDITIONS)
        if explicit:
            return _("Material Request %(mrf)s is not approved yet: rule(s) %(rules)s require the "
                     "approval of Not Covered materials before the customer quotation.",
                     mrf=self.name, rules=', '.join(explicit.mapped('name')))
        return False

    def _warranty_quotation_error(self):
        """Figure 7 change request (2026-11-07, MRF/000013 UAT): new parts quotations only for
        a request with every required approval level completed (Approved, or Approved - No
        Approval Required at submission). The release of orders that already exist keeps
        _warranty_chargeable_request_error (historical early quotations stay valid)."""
        self.ensure_one()
        error = self._warranty_chargeable_request_error()
        if error:
            return error
        if self.state not in RELEASED_STATES:
            return _("Material Request %s is waiting for approval: Create Parts Quotation is "
                     "available after all required approval levels are completed.", self.name)
        return False

    def _warranty_cancel_open_parts_quotations(self, text):
        """Rejected / withdrawn request (Figure 7 D2): quotations the customer has not confirmed
        are cancelled (no accounting impact); confirmed orders are never cancelled, their
        delivery waits until the request is valid again (chargeable state Release Blocked)."""
        self.ensure_one()
        # sudo: system cancellation after the approval workflow checks.
        orders = self.sudo().parts_quotation_ids.filtered(
            lambda order: order.state in ('draft', 'sent'))
        if not orders:
            return
        orders._action_cancel()
        note = _("Parts quotation(s) %(orders)s cancelled: %(text)s", text=text,
                 orders=', '.join(orders.mapped('name')))
        self.sudo()._message_log(body=note)
        for order in orders:
            order._message_log(body=note)
        self._warranty_log_links(note)

    def _warranty_reject(self, reason):
        super()._warranty_reject(reason)
        self._warranty_cancel_open_parts_quotations(_("Material Request %s rejected.", self.name))

    def action_warranty_withdraw(self):
        result = super().action_warranty_withdraw()
        for mrf in self:
            mrf._warranty_cancel_open_parts_quotations(
                _("Material Request %s withdrawn.", mrf.name))
        return result

    def _warranty_check_open_customer_orders(self):
        """Cancel Material Request (E-13b check): a request whose Not Covered lines are on a
        confirmed customer order is not cancelled; the order stays valid until Sales cancels
        it (Figure 7 D2)."""
        for mrf in self.filtered('is_warranty_mrf'):
            confirmed = mrf.sudo().parts_quotation_ids.filtered(lambda order: order.state == 'sale')
            if confirmed:
                raise UserError(_("Material Request %(mrf)s has confirmed customer order(s) "
                                  "%(orders)s: cancel them in Sales first, or keep the request.",
                                  mrf=mrf.name, orders=', '.join(confirmed.mapped('name'))))

    # ------------------------------------------------------------------ quotation
    def _warranty_quotable_lines(self):
        return self.requisition_line_ids.filtered(lambda line: line.chargeable_state == 'to_quote')

    def action_create_parts_quotation(self):
        """Create Parts Quotation (mapping 5.4, Figure 7 D2): Not Covered lines without active
        quotation of a fully approved request (_warranty_quotation_error) -> draft quotation
        for the commercial customer, delivery to the site; no Service Job (no chargeable
        purpose), no e-mail (Send To-Do, Part 4 C10)."""
        self.ensure_one()
        error = self._warranty_quotation_error()
        if error:
            raise UserError(error)
        lines = self._warranty_quotable_lines()
        if not lines:
            raise UserError(_("Material Request %s has no Not Covered line to quote.",
                              self.name))
        case = self.warranty_case_id
        case._warranty_check_quotation_rights()
        commercial = case.partner_id.commercial_partner_id
        # sudo after the Sales rights check: the warranty link fields are set by the workflow
        # only. The current user stays the salesperson / creator.
        order = self.env['sale.order'].sudo().with_company(self.company_id).create({
            'partner_id': commercial.id,
            'partner_shipping_id': (case.site_id or commercial).id,
            'company_id': self.company_id.id,
            'user_id': self.env.uid,
            'origin': '%s / %s' % (self.name, case.name),
            'warranty_mrf_id': self.id,
            'warranty_release_trigger': self.company_id.warranty_mrf_release_trigger,
            'order_line': [(0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.uom.id,
                'warranty_mrf_line_id': line.id,
            }) for line in lines],
        })
        # Linked to the case after creation: a quotation created with the case of a Chargeable
        # case would get a Chargeable Purpose and trigger a Service Job (Part 4.10, T4.6).
        order.write({'warranty_case_id': case.id})
        order.order_line.write({'warranty_case_id': case.id})
        lines.sudo().write({'requisition_type': SALE_ACTION})
        case._warranty_send_todo(order)
        text = _("Parts quotation %(order)s created by %(user)s for %(products)s (release "
                 "%(trigger)s).", order=order.name, user=self.env.user.name,
                 products=', '.join(lines.mapped('product_id.display_name')),
                 trigger=dict(RELEASE_TRIGGERS)[order.warranty_release_trigger])
        self.sudo()._message_log(body=text)
        self._warranty_log_links(text)
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'view_mode': 'form',
                'res_id': order.id}

    def action_view_parts_quotations(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sale.action_quotations_with_onboarding')
        action.update({'domain': [('warranty_mrf_id', '=', self.id)], 'context': {'create': False}})
        return action

    def action_view_parts_deliveries(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('stock.action_picking_tree_all')
        action.update({'domain': [('id', 'in', self.sudo().parts_quotation_ids.picking_ids.ids)],
                       'context': {'create': False}})
        return action

    # ------------------------------------------------------------------ decline
    def _warranty_check_commercial_user(self):
        user = self.env.user
        if not (user.has_group('helpdesk.group_helpdesk_user')
                or user.has_group('sales_team.group_sale_salesman')):
            raise AccessError(_("Customer decisions are recorded by Helpdesk or Sales users."))

    def action_open_chargeable_decline(self):
        self.ensure_one()
        self._warranty_check_commercial_user()
        lines = self.requisition_line_ids.filtered(
            lambda line: line.chargeable_state in ('to_quote', 'waiting_customer'))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Customer Declined"),
            'res_model': 'warranty.mrf.decline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_requisition_id': self.id,
                        'default_line_ids': [(6, 0, lines.ids)]},
        }

    def _warranty_decline_chargeable(self, lines, reason):
        """Customer Declined (mapping 5.4): the lines are never issued; their open quotation
        lines are removed (the quotation is cancelled when nothing else remains); the covered
        lines continue. Not after the customer confirmed the quotation."""
        self.ensure_one()
        self._warranty_check_commercial_user()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required for the customer decline."))
        lines = lines.filtered(lambda line: line.requisition_id == self)
        if not lines or lines.filtered(
                lambda line: line.chargeable_state not in ('to_quote', 'waiting_customer')):
            raise UserError(_("Only Not Covered lines that are not quoted yet or waiting for the "
                              "customer can be declined."))
        sale_lines = lines.sudo().sale_line_ids.filtered(
            lambda line: line.order_id.state in ('draft', 'sent'))
        lines.sudo().write({
            'chargeable_declined': True, 'chargeable_decline_reason': reason,
            'chargeable_declined_by_id': self.env.uid,
            'chargeable_declined_date': fields.Datetime.now(),
            'requisition_type': SALE_ACTION,
        })
        for order in sale_lines.order_id:
            remaining = order.order_line.filtered(
                lambda line: not line.display_type and line not in sale_lines)
            if remaining:
                (order.order_line & sale_lines).with_context(warranty_mrf_decline=True).unlink()
            else:
                order._action_cancel()
        text = _("Customer declined %(products)s (recorded by %(user)s). Reason: %(reason)s",
                 products=', '.join(lines.mapped('product_id.display_name')),
                 user=self.env.user.name, reason=reason)
        self.sudo()._message_log(body=text)
        self._warranty_log_links(text)

    # ------------------------------------------------------------------ release exception
    def _warranty_exception_orders(self):
        self.ensure_one()
        return self.sudo().parts_quotation_ids.filtered(
            lambda order: order._warranty_parts_release_state() == 'waiting_payment')

    def _warranty_is_release_exception_user(self, user=None):
        """D9: Chargeable Release Exception Users of the company, never the requester,
        creator or submitter (D-D)."""
        self.ensure_one()
        user = user or self.env.user
        return user in self.company_id.warranty_mrf_release_exception_user_ids \
            and user not in self._warranty_sod_users()

    def action_open_release_exception(self):
        self.ensure_one()
        if not self._warranty_is_release_exception_user():
            raise AccessError(_("Only Chargeable Release Exception Users (not the requester, "
                                "creator or submitter) approve release exceptions."))
        orders = self._warranty_exception_orders()
        if not orders:
            raise UserError(_("No parts quotation of %s is waiting for payment.", self.name))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Approve Release Exception"),
            'res_model': 'warranty.mrf.release.exception.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_requisition_id': self.id,
                        'default_order_id': orders[:1].id},
        }

    def _warranty_approve_release_exception(self, order, reason):
        self.ensure_one()
        if not self._warranty_is_release_exception_user():
            raise AccessError(_("Only Chargeable Release Exception Users (not the requester, "
                                "creator or submitter) approve release exceptions."))
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required for a release exception."))
        order = order.sudo()
        if order not in self._warranty_exception_orders():
            raise UserError(_("Quotation %s is not waiting for payment.", order.name))
        order.write({'warranty_release_exception_by_id': self.env.uid,
                     'warranty_release_exception_date': fields.Datetime.now(),
                     'warranty_release_exception_reason': reason})
        text = _("Release exception for %(order)s approved by %(user)s (payment pending). "
                 "Reason: %(reason)s", order=order.name, user=self.env.user.name, reason=reason)
        self.sudo()._message_log(body=text)
        order._message_log(body=text)
        self._warranty_log_links(text)


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    requisition_type = fields.Selection(
        selection_add=[(SALE_ACTION, 'Customer Quotation')],
        ondelete={SALE_ACTION: 'set default'})
    sale_line_ids = fields.One2many('sale.order.line', 'warranty_mrf_line_id',
                                    string='Quotation Lines', readonly=True)
    chargeable_state = fields.Selection(
        CHARGEABLE_STATES, string='Chargeable Release', compute='_compute_chargeable_state',
        help="Not Covered lines: customer quotation, approval and payment before issue.")
    chargeable_declined = fields.Boolean(string='Customer Declined', readonly=True, copy=False)
    chargeable_decline_reason = fields.Text(string='Decline Reason', readonly=True, copy=False)
    chargeable_declined_by_id = fields.Many2one('res.users', string='Declined Recorded By',
                                                readonly=True, copy=False)
    chargeable_declined_date = fields.Datetime(string='Declined On', readonly=True, copy=False)

    @api.depends('coverage_type', 'chargeable_declined', 'sale_line_ids.order_id.state',
                 'sale_line_ids.order_id.invoice_status',
                 'sale_line_ids.order_id.warranty_release_exception_by_id',
                 'requisition_id.state', 'requisition_id.approval_round',
                 'requisition_id.approval_signature')
    def _compute_chargeable_state(self):
        for line in self:
            if not line.is_warranty_mrf or line.coverage_type != 'not_covered':
                line.chargeable_state = False
            elif line.chargeable_declined:
                line.chargeable_state = 'declined'
            else:
                # sudo: the quotation is read for the status only.
                sale_line = line.sudo().sale_line_ids.filtered(
                    lambda sol: sol.order_id.state != 'cancel')[:1]
                if not sale_line:
                    line.chargeable_state = 'to_quote'
                elif sale_line.order_id.state in ('draft', 'sent'):
                    line.chargeable_state = 'waiting_customer'
                else:
                    state = sale_line.order_id._warranty_parts_release_state()
                    # Figure 7 D2: a confirmed order never overrides a rejected, withdrawn,
                    # cancelled or changed request; its delivery waits (history kept).
                    if state in RELEASED_CHARGEABLE_STATES \
                            and line.requisition_id._warranty_chargeable_request_error():
                        state = 'blocked'
                    line.chargeable_state = state

    def _warranty_confirmed_sale_lines(self):
        """Quotation lines of a confirmed customer order (sudo: read for the checks)."""
        return self.sudo().sale_line_ids.filtered(lambda sol: sol.order_id.state == 'sale')

    def _warranty_check_not_sold(self, action):
        """Figure 7 D2: a request line on a confirmed customer order keeps its product,
        quantity, unit and coverage, also when the request is New again after a rejection or a
        withdrawal; it is not deleted."""
        sold = self.filtered(lambda line: line.is_warranty_mrf
                             and line._warranty_confirmed_sale_lines())
        if sold:
            line = sold[0]
            raise UserError(_("%(product)s of Material Request %(mrf)s is on confirmed customer "
                              "order %(order)s: it cannot be %(action)s. Cancel the order in "
                              "Sales first, or keep the line unchanged.",
                              product=line.product_id.display_name,
                              mrf=line.requisition_id.name, action=action,
                              order=', '.join(line._warranty_confirmed_sale_lines()
                                              .order_id.mapped('name'))))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(vals.get('requisition_type') == SALE_ACTION
                                   for vals in vals_list):
            raise UserError(_("The line action Customer Quotation is set by Create Parts "
                              "Quotation."))
        return super().create(vals_list)

    def write(self, vals):
        if 'requisition_type' in vals and not self.env.su and (
                vals['requisition_type'] == SALE_ACTION
                or any(line.requisition_type == SALE_ACTION for line in self)):
            raise UserError(_("The line action Customer Quotation is set by Create Parts "
                              "Quotation and cannot be changed (the quotation delivers these "
                              "materials)."))
        if SOLD_LINE_LOCKED & set(vals):
            self._warranty_check_not_sold(_("changed"))
        return super().write(vals)

    def unlink(self):
        self._warranty_check_not_sold(_("deleted"))
        return super().unlink()


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    warranty_mrf_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                      readonly=True, copy=False, index='btree_not_null')
    warranty_release_trigger = fields.Selection(
        RELEASE_TRIGGERS, string='Parts Release Trigger', readonly=True, copy=False,
        help="Company setting when the quotation was created (D9).")
    warranty_release_exception_by_id = fields.Many2one(
        'res.users', string='Release Exception By', readonly=True, copy=False, tracking=True)
    warranty_release_exception_date = fields.Datetime(string='Release Exception On',
                                                      readonly=True, copy=False)
    warranty_release_exception_reason = fields.Text(string='Release Exception Reason',
                                                    readonly=True, copy=False)
    warranty_parts_release_state = fields.Selection(
        CHARGEABLE_STATES, string='Parts Release', compute='_compute_warranty_parts_release_state')

    def _compute_warranty_parts_release_state(self):
        for order in self:
            if not order.warranty_mrf_id:
                order.warranty_parts_release_state = False
            elif order.state in ('draft', 'sent'):
                order.warranty_parts_release_state = 'waiting_customer'
            else:
                order.warranty_parts_release_state = order._warranty_parts_release_state() \
                    or False

    def _warranty_parts_paid(self):
        """Fully invoiced and every posted invoice settled (Part 3.3 rule: Paid, or In Payment
        covered by registered payments); partial payments and reversed invoices do not
        release."""
        self.ensure_one()
        order = self.sudo()
        if order.invoice_status != 'invoiced':
            return False
        invoices = order.invoice_ids.filtered(
            lambda move: move.move_type == 'out_invoice' and move.state == 'posted')
        if not invoices:
            return False
        uncovered = self.env['warranty.case'].sudo()._warranty_uncovered_amounts(invoices)
        return all(invoice.currency_id.is_zero(uncovered[invoice.id]) for invoice in invoices)

    def _warranty_parts_release_state(self):
        """D9: On Quotation Confirmation -> released when confirmed; On Payment -> released
        when paid, or by an approved exception."""
        self.ensure_one()
        if self.state != 'sale':
            return False
        if self.warranty_release_trigger != 'payment' or self._warranty_parts_paid():
            return 'released'
        if self.warranty_release_exception_by_id:
            return 'released_exception'
        return 'waiting_payment'

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(SALE_ORDER_PROTECTED & set(vals) for vals in vals_list):
            raise UserError(_("The material request fields of a quotation are set by the "
                              "warranty workflow."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and SALE_ORDER_PROTECTED & set(vals):
            raise UserError(_("The material request fields of a quotation are set by the "
                              "warranty workflow."))
        return super().write(vals)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    warranty_mrf_line_id = fields.Many2one(
        'material.purchase.requisition.line', string='Material Request Line', readonly=True,
        copy=False, ondelete='restrict', index='btree_not_null')

    @api.constrains('warranty_mrf_line_id', 'order_id')
    def _check_warranty_mrf_line(self):
        for line in self.filtered('warranty_mrf_line_id'):
            mrf_line = line.warranty_mrf_line_id
            if line.order_id.warranty_mrf_id != mrf_line.requisition_id:
                raise ValidationError(_("The quotation line of %s must belong to a parts "
                                        "quotation of its Material Request.",
                                        mrf_line.requisition_id.name))
            if mrf_line.coverage_type != 'not_covered':
                raise ValidationError(_("Only Not Covered material is quoted to the customer."))
            active = mrf_line.sale_line_ids.filtered(lambda sol: sol.order_id.state != 'cancel')
            if len(active) > 1:
                raise ValidationError(_("%(product)s of %(mrf)s is already on another active "
                                        "quotation.", product=mrf_line.product_id.display_name,
                                        mrf=mrf_line.requisition_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any('warranty_mrf_line_id' in vals for vals in vals_list):
            raise UserError(_("Material request lines are quoted with Create Parts Quotation."))
        # Figure 7 change request (2026-11-07): every quotation path, sudo included.
        mrf_lines = self.env['material.purchase.requisition.line'].browse(
            [vals['warranty_mrf_line_id'] for vals in vals_list
             if vals.get('warranty_mrf_line_id')])
        for mrf in mrf_lines.sudo().requisition_id:
            error = mrf._warranty_quotation_error()
            if error:
                raise UserError(error)
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and SALE_LINE_LOCKED & set(vals) \
                and self.filtered('warranty_mrf_line_id'):
            raise UserError(_("Product and quantity of a parts quotation line come from the "
                              "approved Material Request; record a customer decline and request "
                              "a new Material Request to change them."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and not self.env.context.get('warranty_mrf_decline') \
                and self.filtered(lambda line: line.warranty_mrf_line_id
                                  and line.order_id.state != 'cancel'):
            raise UserError(_("Parts quotation lines are removed with Customer Declined on the "
                              "Material Request."))
        return super().unlink()


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """D8: the quotation's delivery issues the Not Covered material - only after the
        release (customer confirmation / payment / exception)."""
        mrf_lines = self.sudo().move_ids.sale_line_id.warranty_mrf_line_id
        blocked = mrf_lines.filtered(
            lambda line: line.chargeable_state not in RELEASED_CHARGEABLE_STATES)
        if blocked:
            raise UserError(_("Delivery of %(products)s is blocked: the chargeable material of "
                              "%(mrf)s is not released yet (%(state)s).",
                              products=', '.join(blocked.mapped('product_id.display_name')),
                              mrf=', '.join(blocked.requisition_id.mapped('name')),
                              state=', '.join(set(blocked.mapped(lambda l: dict(
                                  CHARGEABLE_STATES).get(l.chargeable_state, '-'))))))
        return super().button_validate()
