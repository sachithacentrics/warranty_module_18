from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero, float_repr

from odoo.addons.warranty_management_fsm.models.warranty_service_job import CLOSED_JOB_STATES

from .material_purchase_requisition_approval import RELEASED_STATES, WAITING_STATES
from .material_purchase_requisition_sale import CHARGEABLE_STATES, SALE_ACTION

# Phase 5.6 (design doc/part5_6_consumption_design.md rev. 2, E-1 - E-15): actual
# consumption, installation of customer-paid parts, unused / customer returns, Cancel
# Remaining, reconciliation and the completion blocker.
ENTRY_KINDS = [
    ('used', 'Used'),
    ('installed', 'Installed'),
    ('kept', 'Customer Keeps'),
    ('unused_return', 'Unused Return'),
    ('customer_return', 'Customer Return'),
    ('cancelled', 'Cancelled Remaining'),
]
REVERSIBLE_KINDS = ('used', 'installed', 'kept')
RETURN_KINDS = ('unused_return', 'customer_return')
RECONCILE_STATES = [
    ('open', 'To Reconcile'),
    ('return_pending', 'Return Pending'),
    ('reconciled', 'Reconciled'),
]
GROUP_HELPDESK = 'helpdesk.group_helpdesk_user'
GROUP_SALES = 'sales_team.group_sale_salesman'
GROUP_STOCK = 'stock.group_stock_user'
GROUP_REQUISITION = 'material_purchase_requisitions.group_purchase_requisition_user'
GROUP_REQUISITION_MANAGER = 'material_purchase_requisitions.group_purchase_requisition_manager'


class WarrantyMrfConsumption(models.Model):
    """One material event of a warranty request line (E-2, E-7, E-8, E-12): used (stock move to
    the Warranty Consumption location), installed / kept by the customer (customer-paid parts,
    no stock move), unused / customer return (return transfer) or cancelled remaining quantity.
    Written by the workflow only; never deleted (reversal with a reason)."""
    _name = 'warranty.mrf.consumption'
    _description = 'Warranty Material Usage'
    _order = 'date desc, id desc'

    line_id = fields.Many2one('material.purchase.requisition.line', string='Material Line',
                              required=True, readonly=True, index=True, ondelete='restrict')
    requisition_id = fields.Many2one(related='line_id.requisition_id', store=True,
                                     string='Material Request', index=True)
    case_id = fields.Many2one(related='requisition_id.warranty_case_id', store=True,
                              string='Warranty Case')
    job_id = fields.Many2one(related='requisition_id.warranty_service_job_id', store=True,
                             string='Service Job', index='btree_not_null')
    task_id = fields.Many2one('project.task', string='Visit', readonly=True,
                              index='btree_not_null')
    company_id = fields.Many2one(related='requisition_id.company_id', store=True)
    product_id = fields.Many2one(related='line_id.product_id', store=True)
    uom_id = fields.Many2one(related='line_id.uom', string='Unit of Measure')
    kind = fields.Selection(ENTRY_KINDS, string='Type', required=True, readonly=True)
    qty = fields.Float(string='Quantity', readonly=True, digits='Product Unit of Measure')
    lot_ids = fields.Many2many('stock.lot', string='Serial / Lot Numbers', readonly=True)
    note = fields.Text(string='Notes / Reason', readonly=True)
    user_id = fields.Many2one('res.users', string='Recorded By', readonly=True,
                              default=lambda self: self.env.user)
    date = fields.Datetime(string='Date', readonly=True, default=fields.Datetime.now)
    move_ids = fields.One2many('stock.move', 'warranty_consumption_id', string='Stock Moves',
                               readonly=True)
    picking_id = fields.Many2one('stock.picking', string='Return Transfer', readonly=True)
    picking_state = fields.Selection(related='picking_id.state', string='Transfer Status')
    state = fields.Selection([('done', 'Done'), ('reversed', 'Reversed')], default='done',
                             readonly=True)
    reversed_by_id = fields.Many2one('res.users', string='Reversed By', readonly=True)
    reversed_date = fields.Datetime(string='Reversed On', readonly=True)
    reverse_reason = fields.Text(string='Reversal Reason', readonly=True)
    can_reverse = fields.Boolean(compute='_compute_can_reverse')
    # Shown to every reader of the entry (Helpdesk users may not read lots / transfers).
    lot_names = fields.Char(string='Serial / Lot', compute='_compute_stock_refs',
                            compute_sudo=True)
    transfer_ref = fields.Char(string='Transfer', compute='_compute_stock_refs',
                               compute_sudo=True)

    @api.depends('lot_ids', 'picking_id.state', 'move_ids.state')
    def _compute_stock_refs(self):
        states = dict(self.env['stock.picking']._fields['state']._description_selection(self.env))
        for entry in self:
            entry.lot_names = ', '.join(entry.lot_ids.mapped('name')) or False
            picking = entry.picking_id
            entry.transfer_ref = '%s (%s)' % (picking.name, states.get(picking.state)) \
                if picking else False

    @api.depends('line_id.product_id', 'kind', 'qty')
    def _compute_display_name(self):
        kinds = dict(ENTRY_KINDS)
        for entry in self:
            entry.display_name = '%s: %s %s %s' % (
                kinds.get(entry.kind, ''), float_repr(entry.qty, 2).rstrip('0').rstrip('.'),
                entry.uom_id.name or '', entry.product_id.display_name or '')

    @api.depends_context('uid')
    @api.depends('kind', 'state', 'job_id.state')
    def _compute_can_reverse(self):
        for entry in self:
            entry.can_reverse = entry.kind in REVERSIBLE_KINDS and entry.state == 'done' \
                and entry.job_id.state not in CLOSED_JOB_STATES \
                and entry.requisition_id._warranty_has_material_access('reverse')

    def _warranty_lot_quantities(self):
        """Serial / lot quantities of an entry without stock move (installed / kept)."""
        self.ensure_one()
        if self.product_id.tracking == 'serial':
            return {lot: 1.0 for lot in self.lot_ids}
        return {lot: self.qty for lot in self.lot_ids[:1]}

    def _warranty_create_move(self, source, destination, alloc, picking=None, done=True):
        """Stock move of the entry with the given serial / lot quantities (line UoM)."""
        self.ensure_one()
        line = self.line_id
        mrf = self.requisition_id
        uom = line.uom or line.product_id.uom_id
        qty = sum(alloc.values())
        reference = ' / '.join(name for name in (mrf.name, mrf.warranty_service_job_id.name
                                                 or mrf.warranty_case_id.name) if name)
        vals = {
            'name': '%s: %s' % (dict(ENTRY_KINDS)[self.kind], reference),
            'origin': reference,
            'company_id': mrf.company_id.id,
            'product_id': line.product_id.id,
            'product_uom': uom.id,
            'product_uom_qty': qty,
            'location_id': source.id,
            'location_dest_id': destination.id,
            'warranty_consumption_id': self.id,
            'picking_id': picking.id if picking else False,
            'picking_type_id': picking.picking_type_id.id if picking else False,
        }
        if done:
            vals.update({'picked': True, 'move_line_ids': [(0, 0, {
                'product_id': line.product_id.id, 'product_uom_id': uom.id, 'quantity': q,
                'location_id': source.id, 'location_dest_id': destination.id,
                'lot_id': lot.id if lot else False, 'picked': True,
            }) for lot, q in alloc.items()]})
        move = self.env['stock.move'].sudo().create(vals)
        if done:
            move._action_done()
            if move.state != 'done':
                raise UserError(_("The stock move of %s could not be validated.",
                                  line.product_id.display_name))
        return move

    def _warranty_reverse(self, reason):
        """Reverse Consumption (E-2): a wrong used / installed / kept entry is reversed with a
        reason (used: move back to the technician location); never deleted."""
        self.ensure_one()
        mrf = self.requisition_id
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to reverse a material entry."))
        if self.kind not in REVERSIBLE_KINDS or self.state != 'done':
            raise UserError(_("Only used, installed or customer-kept entries that are not "
                              "reversed yet can be reversed."))
        mrf._warranty_check_material_open()
        mrf._warranty_check_material_access('reverse')
        entry = self.sudo()
        if entry.kind == 'used':
            alloc = defaultdict(float)
            uom = entry.line_id.uom or entry.product_id.uom_id
            source = entry.move_ids.filtered(lambda move: move.state == 'done')[:1]
            for move_line in source.move_line_ids:
                alloc[move_line.lot_id] += move_line.product_uom_id._compute_quantity(
                    move_line.quantity, uom)
            entry._warranty_create_move(source.location_dest_id, source.location_id, alloc)
        entry.write({'state': 'reversed', 'reversed_by_id': self.env.uid,
                     'reversed_date': fields.Datetime.now(), 'reverse_reason': reason})
        mrf._warranty_material_log(_("%(entry)s reversed by %(user)s. Reason: %(reason)s",
                                     entry=entry.display_name, user=self.env.user.name,
                                     reason=reason))

    def action_open_reverse(self):
        self.ensure_one()
        if not self.can_reverse:
            raise AccessError(_("This entry cannot be reversed by you."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reverse Material Entry"),
            'res_model': 'warranty.mrf.reverse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_consumption_id': self.id},
        }


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    warranty_consumption_ids = fields.One2many('warranty.mrf.consumption', 'line_id',
                                               string='Material Usage', readonly=True)
    used_qty = fields.Float(string='Used / Installed', compute='_compute_material_qty',
                            store=True, digits='Product Unit of Measure')
    kept_qty = fields.Float(string='Customer Keeps', compute='_compute_material_qty',
                            store=True, digits='Product Unit of Measure')
    # Display only: not yet recorded as used; it is not returned until a return is validated.
    warranty_unused_qty = fields.Float(string='Unused', compute='_compute_warranty_unused_qty',
                                       digits='Product Unit of Measure')
    returned_qty = fields.Float(string='Returned', compute='_compute_material_qty', store=True,
                                digits='Product Unit of Measure',
                                help="Validated unused returns (covered parts) or customer "
                                     "returns (customer-paid parts).")
    in_return_qty = fields.Float(string='In Return', compute='_compute_material_qty',
                                 store=True, digits='Product Unit of Measure',
                                 help="On open return transfers (not cancelled, not validated).")
    cancelled_qty = fields.Float(string='Cancelled', compute='_compute_material_qty',
                                 store=True, digits='Product Unit of Measure',
                                 help="Approved quantity cancelled with Cancel Remaining.")
    to_reconcile_qty = fields.Float(string='To Reconcile', compute='_compute_material_qty',
                                    store=True, digits='Product Unit of Measure',
                                    help="Issued (delivered) but not recorded as used / "
                                         "installed, kept by the customer or returned.")
    reconcile_state = fields.Selection(RECONCILE_STATES, string='Reconciliation',
                                       compute='_compute_material_qty', store=True)

    @api.depends('warranty_consumption_ids.state', 'warranty_consumption_ids.qty',
                 'warranty_consumption_ids.kind', 'warranty_consumption_ids.move_ids.state',
                 'warranty_consumption_ids.move_ids.quantity',
                 'warranty_consumption_ids.move_ids.product_uom_qty', 'issued_qty',
                 'requisition_type', 'chargeable_declined', 'uom', 'requisition_id.is_warranty_mrf')
    def _compute_material_qty(self):
        for line in self:
            uom = line.uom or line.product_id.uom_id
            used = kept = returned = in_return = cancelled = 0.0
            for entry in line.warranty_consumption_ids:
                if entry.kind in RETURN_KINDS:
                    for move in entry.move_ids.filtered(lambda move: move.state != 'cancel'):
                        if move.state == 'done':
                            returned += move.product_uom._compute_quantity(move.quantity, uom)
                        elif move.state != 'draft':
                            in_return += move.product_uom._compute_quantity(
                                move.product_uom_qty, uom)
                elif entry.state == 'done':
                    if entry.kind in ('used', 'installed'):
                        used += entry.qty
                    elif entry.kind == 'kept':
                        kept += entry.qty
                    else:
                        cancelled += entry.qty
            if line.requisition_type == SALE_ACTION:
                # Customer returns (to refund) already reduce the delivered quantity.
                open_qty = line.issued_qty - used - kept - in_return
            else:
                open_qty = line.issued_qty - used - returned - in_return
            rounding = uom.rounding or 0.01
            if not line.requisition_id.is_warranty_mrf or line.chargeable_declined or (
                    float_is_zero(line.issued_qty, precision_rounding=rounding)
                    and float_is_zero(in_return + used + kept, precision_rounding=rounding)):
                state = False
            elif float_compare(open_qty, 0.0, precision_rounding=rounding) > 0:
                state = 'open'
            elif float_compare(in_return, 0.0, precision_rounding=rounding) > 0:
                state = 'return_pending'
            else:
                state = 'reconciled'
            line.update({'used_qty': used, 'kept_qty': kept, 'returned_qty': returned,
                         'in_return_qty': in_return, 'cancelled_qty': cancelled,
                         'to_reconcile_qty': max(open_qty, 0.0), 'reconcile_state': state})

    @api.depends('issued_qty', 'used_qty', 'kept_qty')
    def _compute_warranty_unused_qty(self):
        for line in self:
            line.warranty_unused_qty = max(line.issued_qty - line.used_qty - line.kept_qty, 0.0)

    def _warranty_is_customer_line(self):
        """Customer-paid (Not Covered) line delivered by its parts quotation (5.4 D8)."""
        self.ensure_one()
        return self.requisition_type == SALE_ACTION and not self.chargeable_declined

    def _warranty_cancellable_qty(self):
        """E-12: approved, not issued, not on an open issue transfer or purchase order."""
        self.ensure_one()
        if self.requisition_type == SALE_ACTION or self.coverage_type == 'not_covered' \
                or self.chargeable_declined:
            return 0.0
        open_purchase = max(self.purchased_qty - self.received_qty, 0.0)
        return max(self.outstanding_qty - open_purchase, 0.0)

    def _warranty_lot_balance(self):
        """Serial / lot numbers still available on this line (line UoM): issued (or delivered)
        lots minus lots used, installed, kept or on a return transfer."""
        self.ensure_one()
        line = self.sudo()
        uom = line.uom or line.product_id.uom_id
        dest = line.requisition_id.dest_location_id
        balance = defaultdict(float)

        def add(move, sign):
            for move_line in move.move_line_ids.filtered('lot_id'):
                balance[move_line.lot_id] += sign * move_line.product_uom_id._compute_quantity(
                    move_line.quantity, uom)

        customer = line._warranty_is_customer_line()
        if customer:
            for move in line.sale_line_ids.move_ids.filtered(lambda move: move.state == 'done'):
                if move.location_dest_id.usage == 'customer':
                    add(move, 1)
                elif move.location_id.usage == 'customer':
                    add(move, -1)
        else:
            for move in line.warranty_move_ids.filtered(lambda move: move.state == 'done'):
                add(move, -1 if move.location_id == dest and move.location_dest_id != dest else 1)
        for entry in line.warranty_consumption_ids:
            if entry.kind in ('installed', 'kept') and entry.state == 'done':
                for lot, qty in entry._warranty_lot_quantities().items():
                    balance[lot] -= qty
            elif entry.kind == 'used':
                for move in entry.move_ids.filtered(lambda move: move.state == 'done'):
                    add(move, -1 if move.location_id == dest else 1)
            elif entry.kind == 'unused_return':
                for move in entry.move_ids.filtered(lambda move: move.state != 'cancel'):
                    add(move, -1)
            elif entry.kind == 'customer_return':
                # Validated customer returns are already deducted from the deliveries.
                for move in entry.move_ids.filtered(
                        lambda move: move.state not in ('done', 'cancel')):
                    add(move, -1)
        rounding = uom.rounding or 0.01
        return {lot: qty for lot, qty in balance.items()
                if float_compare(qty, 0.0, precision_rounding=rounding) > 0}

    def _warranty_check_row(self, qty, lots, limit, action):
        """Quantity limit and serial / lot rules (E-3, E-6); returns {lot or False: qty}."""
        self.ensure_one()
        uom = self.uom or self.product_id.uom_id
        rounding = uom.rounding or 0.01
        product = self.product_id.display_name
        if float_compare(qty, 0.0, precision_rounding=rounding) <= 0:
            raise UserError(_("%s: enter a positive quantity.", product))
        if float_compare(qty, limit, precision_rounding=rounding) > 0:
            raise UserError(_("%(product)s: at most %(limit)s %(uom)s can be %(action)s (entered "
                              "%(qty)s).", product=product, limit=limit, uom=uom.name,
                              action=action, qty=qty))
        tracking = self.product_id.tracking
        if tracking == 'none':
            if lots:
                raise UserError(_("%s is not tracked by serial / lot numbers.", product))
            return {self.env['stock.lot']: qty}
        if not lots:
            raise UserError(_("%s: select the serial / lot numbers.", product))
        if tracking == 'serial':
            if float_compare(qty, len(lots), precision_rounding=rounding):
                raise UserError(_("%(product)s: select one serial number per unit (%(qty)s units, "
                                  "%(count)s serial numbers).", product=product, qty=qty,
                                  count=len(lots)))
            alloc = {lot: 1.0 for lot in lots}
        else:
            if len(lots) != 1:
                raise UserError(_("%s: select one lot per entry.", product))
            alloc = {lots: qty}
        balance = self._warranty_lot_balance()
        for lot, lot_qty in alloc.items():
            if float_compare(lot_qty, balance.get(lot, 0.0), precision_rounding=rounding) > 0:
                raise UserError(_("%(product)s: %(lot)s was not issued / delivered for this line "
                                  "or is already used, kept or returned.", product=product,
                                  lot=lot.name))
        return alloc

    def _warranty_check_location_stock(self, location, alloc):
        """E-3: never more than the unreserved stock at the location (no negative stock)."""
        self.ensure_one()
        product = self.product_id
        if not product.is_storable:
            return
        uom = self.uom or product.uom_id
        Quant = self.env['stock.quant'].sudo()
        for lot, qty in alloc.items():
            needed = uom._compute_quantity(qty, product.uom_id)
            available = Quant._get_available_quantity(product, location, lot_id=lot or None,
                                                      strict=bool(lot))
            if float_compare(needed, available, precision_rounding=product.uom_id.rounding) > 0:
                raise UserError(_(
                    "Only %(available)s %(uom)s of %(product)s%(lot)s are available at "
                    "%(location)s (needed %(needed)s): negative stock is not allowed.",
                    available=available, uom=product.uom_id.name, product=product.display_name,
                    lot=' (%s)' % lot.name if lot else '', location=location.display_name,
                    needed=needed))


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    warranty_mrf_status = fields.Selection(selection_add=[
        ('returned', 'Returned'), ('closed', 'Closed')],
        ondelete={'returned': 'set null', 'closed': 'set null'})
    warranty_consumption_ids = fields.One2many('warranty.mrf.consumption', 'requisition_id',
                                               string='Material Usage', readonly=True)
    warranty_return_picking_count = fields.Integer(compute='_compute_material_actions')
    can_warranty_record_usage = fields.Boolean(compute='_compute_material_actions')
    can_warranty_return_unused = fields.Boolean(compute='_compute_material_actions')
    can_warranty_customer_resolve = fields.Boolean(compute='_compute_material_actions')
    can_warranty_cancel_remaining = fields.Boolean(compute='_compute_material_actions')
    warranty_material_issues = fields.Text(string='Open Material Items',
                                           compute='_compute_material_actions')

    @api.depends('requisition_line_ids.to_reconcile_qty', 'requisition_line_ids.in_return_qty',
                 'requisition_line_ids.cancelled_qty', 'requisition_line_ids.returned_qty',
                 'requisition_line_ids.in_issue_qty', 'requisition_line_ids.chargeable_state',
                 'approval_round')
    def _compute_warranty_mrf_status(self):
        """E-11: Returned (everything reconciled, unused / customer returns still open for the
        store) and Closed (everything reconciled, nothing open)."""
        super()._compute_warranty_mrf_status()
        for mrf in self.filtered(lambda mrf: mrf.is_warranty_mrf and mrf.state in RELEASED_STATES
                                 and (mrf.approval_round or mrf._warranty_is_legacy_issued())):
            if mrf._warranty_material_problems():
                continue
            rounding = 0.0001
            pending = any(not float_is_zero(qty, precision_rounding=rounding)
                          for qty in mrf.requisition_line_ids.mapped('in_return_qty'))
            mrf.warranty_mrf_status = 'returned' if pending else 'closed'

    @api.depends_context('uid')
    @api.depends('state', 'requisition_line_ids.to_reconcile_qty',
                 'requisition_line_ids.outstanding_qty', 'warranty_consumption_ids.picking_id')
    def _compute_material_actions(self):
        for mrf in self:
            lines = mrf.requisition_line_ids
            open_request = mrf.is_warranty_mrf and not mrf._warranty_material_open_error()
            reconcile = lines.filtered(lambda line: line.to_reconcile_qty > 0)
            mrf.warranty_return_picking_count = len(mrf.sudo().warranty_consumption_ids.filtered(
                lambda entry: entry.kind in RETURN_KINDS).picking_id)
            mrf.can_warranty_record_usage = open_request and bool(reconcile) \
                and mrf._warranty_has_material_access('record')
            mrf.can_warranty_return_unused = mrf.can_warranty_record_usage and bool(
                reconcile.filtered(lambda line: not line._warranty_is_customer_line()))
            mrf.can_warranty_customer_resolve = open_request and bool(
                reconcile.filtered(lambda line: line._warranty_is_customer_line())) \
                and mrf._warranty_has_material_access('commercial')
            mrf.can_warranty_cancel_remaining = open_request and any(
                line._warranty_cancellable_qty() > 0 for line in lines) \
                and mrf._warranty_has_material_access('cancel')
            issues = mrf._warranty_material_problems() if mrf.is_warranty_mrf else []
            mrf.warranty_material_issues = '\n'.join(issues) or False

    # ------------------------------------------------------------------ rules
    def _warranty_material_problems(self):
        """E-13: unresolved material requirements of a warranty request ([] = nothing blocks
        the completion of its service job). Cancelled requests and Customer Declined lines do
        not block; open unused / customer returns (Return Pending) do not block."""
        self.ensure_one()
        if self.state == 'cancel':
            return []
        if self.state == 'draft':
            return [_("not submitted (New): submit it or cancel it with a reason")]
        if self.state == 'reject':
            return [_("rejected: reset it to New and submit it again, or cancel it with a "
                      "reason")]
        if self.state in WAITING_STATES:
            return [_("waiting for approval")]
        if self._warranty_is_legacy():
            if not self._warranty_is_legacy_issued():
                return [_("submitted before the approval workflow: withdraw it and submit it "
                          "again")]
            return self._warranty_legacy_problems()
        problems = []
        chargeable = dict(CHARGEABLE_STATES)
        for line in self.requisition_line_ids.filtered(lambda line: not line.chargeable_declined):
            uom = line.uom or line.product_id.uom_id
            rounding = uom.rounding or 0.01
            product = line.product_id.display_name

            def amount(qty):
                return '%s %s' % (float_repr(qty, 4).rstrip('0').rstrip('.'), uom.name)
            if line.coverage_type == 'not_covered' and line.chargeable_state:
                if line.chargeable_state in ('to_quote', 'waiting_customer', 'waiting_payment'):
                    problems.append(_("%(product)s %(state)s", product=product,
                                      state=chargeable[line.chargeable_state]))
                    continue
                missing = line.qty - line.issued_qty - line.returned_qty
                if float_compare(missing, 0.0, precision_rounding=rounding) > 0:
                    problems.append(_("%(product)s: %(qty)s not delivered to the customer",
                                      product=product, qty=amount(missing)))
                if float_compare(line.to_reconcile_qty, 0.0, precision_rounding=rounding) > 0:
                    problems.append(_("%(product)s: %(qty)s delivered but not recorded as "
                                      "installed, kept by the customer or returned",
                                      product=product, qty=amount(line.to_reconcile_qty)))
                continue
            if float_compare(line.outstanding_qty, 0.0, precision_rounding=rounding) > 0:
                problems.append(_("%(product)s: %(qty)s not issued yet (issue it or use Cancel "
                                  "Remaining)", product=product, qty=amount(line.outstanding_qty)))
            if float_compare(line.in_issue_qty, 0.0, precision_rounding=rounding) > 0:
                problems.append(_("%(product)s: %(qty)s on an issue transfer that is not "
                                  "validated", product=product, qty=amount(line.in_issue_qty)))
            if float_compare(line.to_reconcile_qty, 0.0, precision_rounding=rounding) > 0:
                problems.append(_("%(product)s: %(qty)s issued but not recorded as used or "
                                  "returned", product=product, qty=amount(line.to_reconcile_qty)))
        return problems

    def _warranty_is_legacy_issued(self):
        """Request processed before the approval matrix (5.3 requirement 9) whose earlier
        workflow already created its transfers (Picking / PO Created or Received): only the
        quantities of its validated issue moves are reconciled; it is never approved or issued
        again."""
        self.ensure_one()
        return self._warranty_is_legacy() and self.state in ('stock', 'receive')

    def _warranty_legacy_problems(self):
        """Open items of a pre-matrix issued request: its own validated stock moves only (the
        Received status does not mean that everything was issued)."""
        self.ensure_one()
        problems = []
        for line in self.requisition_line_ids:
            uom = line.uom or line.product_id.uom_id
            rounding = uom.rounding or 0.01
            product = line.product_id.display_name

            def amount(qty):
                return '%s %s' % (float_repr(qty, 4).rstrip('0').rstrip('.'), uom.name)
            if float_compare(line.in_issue_qty, 0.0, precision_rounding=rounding) > 0:
                problems.append(_("%(product)s: %(qty)s on a transfer of the earlier workflow that "
                                  "is not validated - cancel that transfer (it cannot be validated "
                                  "without an approval round)", product=product,
                                  qty=amount(line.in_issue_qty)))
            if float_compare(line.to_reconcile_qty, 0.0, precision_rounding=rounding) > 0:
                problems.append(_("%(product)s: %(qty)s issued but not recorded as used or "
                                  "returned", product=product, qty=amount(line.to_reconcile_qty)))
        return problems

    def _warranty_material_open_error(self):
        self.ensure_one()
        if not self.is_warranty_mrf:
            return _("Only warranty Material Requests record material usage.")
        if self.state not in RELEASED_STATES or (
                self._warranty_is_legacy() and not self._warranty_is_legacy_issued()):
            return _("Material usage, returns and cancellations are recorded on approved warranty "
                     "Material Requests only (%s).", self.name)
        job = self.sudo().warranty_service_job_id
        if job.state in CLOSED_JOB_STATES:
            return _("Service job %(job)s is closed: the materials of %(mrf)s can no longer be "
                     "changed.", job=job.name, mrf=self.name)
        return False

    def _warranty_check_material_open(self):
        error = self._warranty_material_open_error()
        if error:
            raise UserError(error)

    def _warranty_has_material_access(self, action, user=None):
        """E-1 / E-12 / E-13b authorisation (checked again by every action):
        record - technicians of the service job, Service Coordinators (Helpdesk users),
                 Store (Requisition / Inventory users);
        reverse - Service Coordinators, Store;
        commercial - Helpdesk or Sales users (customer keeps / customer return);
        cancel - requester, creator, Requisition Managers, Store (Requisition + Inventory);
        cancel_request - requester, creator, Service Coordinators (Helpdesk + Requisition)."""
        self.ensure_one()
        user = user or self.env.user
        if self.env.su:
            return True
        if self.company_id not in user.company_ids:
            return False
        has = user.has_group
        store = has(GROUP_REQUISITION) or has(GROUP_STOCK)
        coordinator = has(GROUP_HELPDESK)
        if action == 'record':
            job = self.sudo().warranty_service_job_id
            return user in (job.main_technician_id | job.support_technician_ids) \
                or coordinator or store
        if action == 'reverse':
            return coordinator or store
        if action == 'commercial':
            return coordinator or has(GROUP_SALES)
        if action == 'cancel':
            return self._warranty_is_requester_or_creator(user) \
                or has(GROUP_REQUISITION_MANAGER) or (has(GROUP_REQUISITION) and has(GROUP_STOCK))
        if action == 'cancel_request':
            return self._warranty_is_requester_or_creator(user) \
                or (coordinator and has(GROUP_REQUISITION))
        return False

    def _warranty_check_material_access(self, action):
        if not self._warranty_has_material_access(action):
            messages = {
                'record': _("Only the technicians of the service job, Service Coordinators and "
                            "Store users record used or returned material."),
                'reverse': _("Only Service Coordinators and Store users reverse material "
                             "entries."),
                'commercial': _("Customer decisions on delivered parts are recorded by Helpdesk "
                                "or Sales users."),
                'cancel': _("Only the requester, the creator, Requisition Managers and Store "
                            "users (Requisition and Inventory rights) cancel remaining "
                            "quantities."),
                'cancel_request': _("Only the requester, the creator and Service Coordinators "
                                    "(Helpdesk and Requisition rights) cancel warranty Material "
                                    "Requests."),
            }
            raise AccessError(messages[action])

    def _warranty_material_log(self, text):
        self.sudo()._message_log(body=text)
        self._warranty_log_links(text)

    def _warranty_clean_rows(self, rows, customer):
        """[(line, qty, lots)] of this request with a quantity; customer: True = customer-paid
        lines only, False = covered (issued) lines only."""
        result = []
        for line, qty, lots in rows:
            if line.requisition_id != self or line.chargeable_declined:
                raise UserError(_("Only lines of %s can be used here.", self.name))
            rounding = (line.uom or line.product_id.uom_id).rounding or 0.01
            if float_is_zero(qty, precision_rounding=rounding):
                continue
            if customer is not None and line._warranty_is_customer_line() != customer:
                raise UserError(_(
                    "%(product)s: this action is for %(kind)s.",
                    product=line.product_id.display_name,
                    kind=_("customer-paid parts delivered by the quotation") if customer
                    else _("parts issued to the technician")))
            result.append((line, qty, lots))
        return result

    # ------------------------------------------------------------------ actions
    def _warranty_record_usage(self, rows, task=False, note=False):
        """Record Used Parts (E-2, E-7): covered lines -> validated move technician location ->
        Warranty Consumption; customer-paid lines -> installation (no second stock move)."""
        self.ensure_one()
        self._warranty_check_material_open()
        self._warranty_check_material_access('record')
        rows = self._warranty_clean_rows(rows, None)
        if not rows:
            raise UserError(_("Enter the used / installed quantity of at least one line."))
        mrf = self.sudo()
        location = mrf.company_id._warranty_mrf_consumption_location()
        Entry = self.env['warranty.mrf.consumption'].sudo()
        entries = Entry
        for line, qty, lots in rows:
            customer = line._warranty_is_customer_line()
            alloc = line._warranty_check_row(qty, lots, line.to_reconcile_qty,
                                             _("installed") if customer else _("used"))
            if not customer:
                line._warranty_check_location_stock(mrf.dest_location_id, alloc)
            entry = Entry.create({
                'line_id': line.id, 'kind': 'installed' if customer else 'used', 'qty': qty,
                'lot_ids': [(6, 0, [lot.id for lot in alloc if lot])],
                'task_id': task.id if task else False, 'note': note or False,
            })
            if not customer:
                entry._warranty_create_move(mrf.dest_location_id, location, alloc)
            entries |= entry
        self._warranty_material_log(_("Material usage recorded by %(user)s: %(entries)s.",
                                      user=self.env.user.name,
                                      entries=', '.join(entries.mapped('display_name'))))
        return entries

    def _warranty_full_rows(self):
        """Confirm Full Consumption (E-9): every remaining issued / delivered quantity with the
        remaining serial / lot numbers."""
        self.ensure_one()
        rows = []
        for line in self.requisition_line_ids.filtered(
                lambda line: line.to_reconcile_qty > 0 and not line.chargeable_declined):
            if line.product_id.tracking == 'none':
                rows.append((line, line.to_reconcile_qty, self.env['stock.lot']))
                continue
            balance = line._warranty_lot_balance()
            if float_compare(sum(balance.values()), line.to_reconcile_qty,
                             precision_rounding=(line.uom or line.product_id.uom_id).rounding) < 0:
                raise UserError(_("%s: the remaining serial / lot numbers do not cover the "
                                  "remaining quantity; record the usage line by line.",
                                  line.product_id.display_name))
            if line.product_id.tracking == 'serial':
                rows.append((line, float(len(balance)), self.env['stock.lot'].union(*balance)))
            else:
                for lot, qty in balance.items():
                    rows.append((line, qty, lot))
        return rows

    def _warranty_confirm_full_consumption(self, task=False, note=False):
        self.ensure_one()
        self._warranty_check_material_open()
        self._warranty_check_material_access('record')
        rows = self._warranty_full_rows()
        if not rows:
            raise UserError(_("Nothing issued or delivered is left to record on %s.", self.name))
        entries = self.env['warranty.mrf.consumption']
        for row in rows:
            entries |= self._warranty_record_usage([row], task=task, note=note)
        return entries

    def _warranty_return_unused(self, rows, note=False, task=False):
        """Return Unused (E-8): one internal return transfer technician location -> request
        source location, validated by Inventory users (Store)."""
        self.ensure_one()
        self._warranty_check_material_open()
        self._warranty_check_material_access('record')
        rows = self._warranty_clean_rows(rows, False)
        if not rows:
            raise UserError(_("Enter the quantity to return for at least one line."))
        mrf = self.sudo()
        mrf._warranty_check_locations()
        checked = []
        for line, qty, lots in rows:
            alloc = line._warranty_check_row(qty, lots, line.to_reconcile_qty, _("returned"))
            line._warranty_check_location_stock(mrf.dest_location_id, alloc)
            checked.append((line, qty, alloc))
        picking = self.env['stock.picking'].sudo().create({
            'partner_id': mrf.employee_id.user_partner_id.id,
            'location_id': mrf.dest_location_id.id,
            'location_dest_id': mrf.location_id.id,
            'picking_type_id': mrf.custom_picking_type_id.id,
            'origin': _("Unused return %s", mrf.name),
            'custom_requisition_id': mrf.id,
            'company_id': mrf.company_id.id,
            'warranty_unused_return': True,
            'note': note or False,
        })
        Entry = self.env['warranty.mrf.consumption'].sudo()
        moves = self.env['stock.move']
        for line, qty, alloc in checked:
            entry = Entry.create({
                'line_id': line.id, 'kind': 'unused_return', 'qty': qty,
                'lot_ids': [(6, 0, [lot.id for lot in alloc if lot])], 'picking_id': picking.id,
                'task_id': task.id if task else False, 'note': note or False,
            })
            moves |= entry._warranty_create_move(mrf.dest_location_id, mrf.location_id, alloc,
                                                 picking=picking, done=False)
        picking.action_confirm()
        for move, (line, qty, alloc) in zip(moves, checked):
            if line.product_id.tracking == 'none':
                move._action_assign()
                continue
            # sudo: the workflow replaces the reserved lines (technicians have no stock rights).
            move.sudo().move_line_ids.unlink()
            self.env['stock.move.line'].sudo().create([{
                'move_id': move.id, 'picking_id': picking.id, 'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id, 'quantity': lot_qty, 'lot_id': lot.id,
                'location_id': move.location_id.id, 'location_dest_id': move.location_dest_id.id,
            } for lot, lot_qty in alloc.items()])
        self._warranty_material_log(_(
            "Unused return %(picking)s created by %(user)s (%(lines)s); to be validated by the "
            "store.", picking=picking.name, user=self.env.user.name,
            lines=', '.join('%s %s' % (qty, line.product_id.display_name)
                            for line, qty, _alloc in checked)))
        return picking

    def _warranty_customer_keep(self, rows, reason):
        """Customer Keeps (E-7): delivered customer-paid parts that are not installed stay with
        the customer (no stock move); reason required."""
        self.ensure_one()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required when the customer keeps parts that were not "
                              "installed."))
        self._warranty_check_material_open()
        self._warranty_check_material_access('commercial')
        rows = self._warranty_clean_rows(rows, True)
        if not rows:
            raise UserError(_("Enter the quantity the customer keeps for at least one line."))
        Entry = self.env['warranty.mrf.consumption'].sudo()
        entries = Entry
        for line, qty, lots in rows:
            alloc = line._warranty_check_row(qty, lots, line.to_reconcile_qty, _("kept"))
            entries |= Entry.create({'line_id': line.id, 'kind': 'kept', 'qty': qty,
                                     'lot_ids': [(6, 0, [lot.id for lot in alloc if lot])],
                                     'note': reason})
        self._warranty_material_log(_("Customer keeps %(entries)s (recorded by %(user)s). "
                                      "Reason: %(reason)s",
                                      entries=', '.join(entries.mapped('display_name')),
                                      user=self.env.user.name, reason=reason))
        return entries

    def _warranty_customer_return(self, rows, reason):
        """Customer Return (E-7): standard return of the quotation delivery (quantities on the
        sales order updated -> credit note by Sales), validated by the store."""
        self.ensure_one()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required for a customer return."))
        self._warranty_check_material_open()
        self._warranty_check_material_access('commercial')
        rows = self._warranty_clean_rows(rows, True)
        if not rows:
            raise UserError(_("Enter the quantity to return for at least one line."))
        Entry = self.env['warranty.mrf.consumption'].sudo()
        pickings = self.env['stock.picking']
        for line, qty, lots in rows:
            alloc = line._warranty_check_row(qty, lots, line.to_reconcile_qty, _("returned"))
            uom = line.uom or line.product_id.uom_id
            remaining = qty
            deliveries = line.sudo().sale_line_ids.move_ids.filtered(
                lambda move: move.state == 'done' and move.location_dest_id.usage == 'customer')
            for move in deliveries.sorted('date', reverse=True):
                if float_is_zero(remaining, precision_rounding=uom.rounding):
                    break
                returned = sum(move.returned_move_ids.filtered(
                    lambda ret: ret.state != 'cancel').mapped('product_uom_qty'))
                available = move.product_uom._compute_quantity(move.quantity - returned, uom)
                take = min(remaining, available)
                if take <= 0:
                    continue
                wizard = self.env['stock.return.picking'].sudo().with_context(
                    active_id=move.picking_id.id, active_ids=move.picking_id.ids,
                    active_model='stock.picking').create({'picking_id': move.picking_id.id})
                for return_line in wizard.product_return_moves:
                    return_line.quantity = uom._compute_quantity(
                        take, return_line.uom_id) if return_line.move_id == move else 0.0
                    if 'to_refund' in return_line._fields:
                        return_line.to_refund = True
                picking = wizard._create_return()
                entry = Entry.create({
                    'line_id': line.id, 'kind': 'customer_return', 'qty': take,
                    'lot_ids': [(6, 0, [lot.id for lot in alloc if lot])],
                    'picking_id': picking.id, 'note': reason,
                })
                picking.move_ids.filtered(lambda ret: ret.origin_returned_move_id == move).write(
                    {'warranty_consumption_id': entry.id})
                picking.write({'warranty_customer_return': True})
                pickings |= picking
                remaining -= take
            if float_compare(remaining, 0.0, precision_rounding=uom.rounding) > 0:
                raise UserError(_("%s: the deliveries do not contain enough quantity to return.",
                                  line.product_id.display_name))
        self._warranty_material_log(_(
            "Customer return %(pickings)s created by %(user)s (to be validated by the store; "
            "credit note by Sales). Reason: %(reason)s", pickings=', '.join(pickings.mapped('name')),
            user=self.env.user.name, reason=reason))
        return pickings

    def _warranty_cancel_remaining(self, rows, reason):
        """Cancel Remaining (E-12): approved quantity that is not issued, not on an open issue
        transfer and not on an open purchase order; reason required; approval history
        unchanged."""
        self.ensure_one()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to cancel remaining quantities."))
        self._warranty_check_material_open()
        self._warranty_check_material_access('cancel')
        rows = self._warranty_clean_rows(rows, False)
        if not rows:
            raise UserError(_("Enter the quantity to cancel for at least one line."))
        Entry = self.env['warranty.mrf.consumption'].sudo()
        entries = Entry
        for line, qty, lots in rows:
            if lots:
                raise UserError(_("Cancel Remaining does not take serial / lot numbers."))
            limit = line._warranty_cancellable_qty()
            uom = line.uom or line.product_id.uom_id
            if float_compare(qty, limit, precision_rounding=uom.rounding) > 0:
                raise UserError(_(
                    "%(product)s: only %(limit)s %(uom)s can be cancelled (issued, delivered, "
                    "consumed quantities and quantities on open transfers or purchase orders "
                    "cannot).", product=line.product_id.display_name, limit=limit, uom=uom.name))
            entries |= Entry.create({'line_id': line.id, 'kind': 'cancelled', 'qty': qty,
                                     'note': reason})
        self._warranty_material_log(_("Remaining quantity cancelled by %(user)s: %(entries)s. "
                                      "Reason: %(reason)s", user=self.env.user.name,
                                      entries=', '.join(entries.mapped('display_name')),
                                      reason=reason))
        return entries

    def _warranty_open_material_wizard(self, mode, task=False):
        self.ensure_one()
        return self.env['warranty.mrf.material.wizard']._warranty_open(self, mode, task=task)

    def action_warranty_record_usage(self):
        return self._warranty_open_material_wizard('use')

    def action_warranty_full_consumption(self):
        return self._warranty_open_material_wizard('full')

    def action_warranty_return_unused(self):
        return self._warranty_open_material_wizard('return')

    def action_warranty_customer_keep(self):
        return self._warranty_open_material_wizard('keep')

    def action_warranty_customer_return(self):
        return self._warranty_open_material_wizard('customer_return')

    def action_warranty_cancel_remaining(self):
        return self._warranty_open_material_wizard('cancel')

    def action_view_warranty_returns(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('stock.action_picking_tree_all')
        pickings = self.sudo().warranty_consumption_ids.filtered(
            lambda entry: entry.kind in RETURN_KINDS).picking_id
        action.update({'domain': [('id', 'in', pickings.ids)], 'context': {'create': False}})
        return action

    # ------------------------------------------------------------------ cancel (E-13b)
    def action_cancel(self):
        """E-13b: warranty requests are cancelled with a mandatory reason (wizard) by the
        requester, the creator or a Service Coordinator; New / Rejected only (5.3 Q6)."""
        warranty = self.filtered('is_warranty_mrf')
        reason = (self.env.context.get('warranty_cancel_reason') or '').strip()
        if warranty and not reason and not self.env.su:
            warranty._warranty_check_cancel_request()
            if len(self) > 1:
                raise UserError(_("Cancel warranty Material Requests one by one (a reason is "
                                  "required)."))
            return {
                'type': 'ir.actions.act_window',
                'name': _("Cancel Material Request"),
                'res_model': 'warranty.mrf.cancel.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_requisition_id': self.id},
            }
        if warranty and not self.env.su:
            warranty._warranty_check_cancel_request()
        result = super(MaterialPurchaseRequisition, self.with_context(
            warranty_cancel_checked=True)).action_cancel()
        for mrf in warranty:
            mrf._warranty_material_log(_("Cancelled by %(user)s. Reason: %(reason)s",
                                         user=self.env.user.name, reason=reason or '-'))
        return result

    def _warranty_check_cancel_request(self):
        for mrf in self:
            if mrf.state not in ('draft', 'reject'):
                raise UserError(_("Warranty Material Requests can be cancelled only when New or "
                                  "Rejected."))
            mrf._warranty_check_material_access('cancel_request')

    def _warranty_check_requester_action(self, states, message):
        """5.3 Q6 extended by E-13b: Service Coordinators may also cancel (checked by
        _warranty_check_cancel_request before)."""
        if self.env.context.get('warranty_cancel_checked'):
            for mrf in self:
                if mrf.state not in states:
                    raise UserError(message)
            return
        return super()._warranty_check_requester_action(states, message)


class StockMove(models.Model):
    _inherit = 'stock.move'

    warranty_consumption_id = fields.Many2one('warranty.mrf.consumption',
                                              string='Warranty Material Usage', readonly=True,
                                              index='btree_not_null', copy=True)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    warranty_unused_return = fields.Boolean(string='Warranty Unused Return', readonly=True,
                                            copy=False)
    warranty_customer_return = fields.Boolean(string='Warranty Customer Return', readonly=True,
                                              copy=False)

    def button_validate(self):
        """E-8: unused returns of warranty requests are validated by Inventory users (Store)
        only, never above the recorded quantity and with the recorded serial / lot numbers."""
        returns = self.filtered(lambda picking: picking.warranty_unused_return
                                or picking.warranty_customer_return)
        if returns and not self.env.su and not self.env.user.has_group(GROUP_STOCK):
            raise AccessError(_("Warranty return transfers are validated by Inventory users "
                                "(Store) only."))
        for move in returns.sudo().move_ids.filtered(
                lambda move: move.warranty_consumption_id and move.state not in ('done', 'cancel')):
            entry = move.warranty_consumption_id
            if float_compare(move.quantity, move.product_uom_qty,
                             precision_rounding=move.product_uom.rounding) > 0:
                raise UserError(_("%(product)s: the return of %(mrf)s cannot exceed the recorded "
                                  "%(qty)s.", product=move.product_id.display_name,
                                  mrf=entry.requisition_id.name, qty=move.product_uom_qty))
            if entry.lot_ids and move.move_line_ids.lot_id - entry.lot_ids:
                raise UserError(_("%(product)s: only the recorded serial / lot numbers %(lots)s "
                                  "may be returned.", product=move.product_id.display_name,
                                  lots=', '.join(entry.lot_ids.mapped('name'))))
        return super().button_validate()


class ResCompany(models.Model):
    _inherit = 'res.company'

    warranty_mrf_consumption_location_id = fields.Many2one(
        'stock.location', string='Warranty Consumption Location',
        help="E-4: virtual location receiving the parts used on warranty jobs (created "
             "automatically when empty).")

    def _warranty_mrf_consumption_location(self):
        """The company's Warranty Consumption location (Inventory Loss type, under Virtual
        Locations); created on first use."""
        self.ensure_one()
        company = self.sudo()
        if company.warranty_mrf_consumption_location_id:
            return company.warranty_mrf_consumption_location_id
        Location = self.env['stock.location'].sudo()
        location = Location.search([('name', '=', 'Warranty Consumption'),
                                    ('usage', '=', 'inventory'),
                                    ('company_id', '=', company.id)], limit=1)
        if not location:
            parent = self.env.ref('stock.stock_location_locations_virtual',
                                  raise_if_not_found=False)
            location = Location.create({'name': 'Warranty Consumption', 'usage': 'inventory',
                                        'location_id': parent.id if parent else False,
                                        'company_id': company.id})
        company.warranty_mrf_consumption_location_id = location
        return location


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_mrf_consumption_location_id = fields.Many2one(
        related='company_id.warranty_mrf_consumption_location_id', readonly=False,
        domain="[('usage', '=', 'inventory'), ('company_id', 'in', (company_id, False))]",
        help="Where parts used on warranty jobs are recorded as consumed. If empty, a "
             "location is created automatically the first time parts are used.")


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    warranty_material_line_ids = fields.Many2many(
        'material.purchase.requisition.line', string='Materials',
        compute='_compute_warranty_materials')
    warranty_consumption_ids = fields.One2many('warranty.mrf.consumption', 'job_id',
                                               string='Material Usage', readonly=True)
    warranty_material_issues = fields.Text(string='Open Material Items',
                                           compute='_compute_warranty_materials')
    can_warranty_record_usage = fields.Boolean(compute='_compute_warranty_materials')

    @api.depends_context('uid')
    @api.depends('material_request_ids.requisition_line_ids',
                 'material_request_ids.warranty_mrf_status')
    def _compute_warranty_materials(self):
        for job in self:
            # sudo: technicians and coordinators see the job's materials (read-only).
            mrfs = job.sudo().material_request_ids
            job.warranty_material_line_ids = mrfs.requisition_line_ids
            issues = job._warranty_material_blockers()
            job.warranty_material_issues = '\n'.join(issues) or False
            job.can_warranty_record_usage = any(
                not mrf._warranty_material_open_error() and mrf.requisition_line_ids.filtered(
                    lambda line: line.to_reconcile_qty > 0)
                and mrf.with_env(self.env)._warranty_has_material_access('record')
                for mrf in mrfs)

    def _warranty_material_blockers(self):
        self.ensure_one()
        problems = []
        for mrf in self.sudo().material_request_ids:
            issues = mrf._warranty_material_problems()
            if issues:
                problems.append(_("Material Request %(mrf)s: %(issues)s.", mrf=mrf.name,
                                  issues='; '.join(issues)))
        return problems

    def _warranty_completion_blockers(self):
        """E-13 (D16): full completion (Complete Visit 4.7, Batch Complete 4.9, visit closure)
        waits for the job's material requests; Incomplete / Reschedule (4.8) does not use
        this hook."""
        problems = super()._warranty_completion_blockers()
        return problems + self._warranty_material_blockers()

    def _warranty_material_requests_for_usage(self):
        self.ensure_one()
        return self.material_request_ids.filtered(
            lambda mrf: not mrf._warranty_material_open_error())

    def action_warranty_record_usage(self):
        self.ensure_one()
        return self.env['warranty.mrf.material.wizard']._warranty_open_for_job(self, 'use')

    def action_warranty_full_consumption(self):
        self.ensure_one()
        return self.env['warranty.mrf.material.wizard']._warranty_open_for_job(self, 'full')

    def action_warranty_return_unused(self):
        self.ensure_one()
        return self.env['warranty.mrf.material.wizard']._warranty_open_for_job(self, 'return')


class ProjectTask(models.Model):
    _inherit = 'project.task'

    warranty_consumption_ids = fields.One2many('warranty.mrf.consumption', 'task_id',
                                               string='Material Usage', readonly=True)
    can_warranty_record_usage = fields.Boolean(related='warranty_service_job_id.can_warranty_record_usage')

    def _warranty_visit_job(self):
        self.ensure_one()
        job = self.warranty_service_job_id
        if self.sudo().warranty_shared_job_ids:
            raise UserError(_("%s is a shared visit: record material usage from its Service Job "
                              "(each job keeps its own materials).", self.sudo().name))
        if not job:
            raise UserError(_("Material usage is recorded on warranty visits."))
        if self.state in ('1_done', '1_canceled'):
            raise UserError(_("Visit %s is closed.", self.display_name))
        return job

    def action_warranty_record_usage(self):
        self.ensure_one()
        return self.env['warranty.mrf.material.wizard']._warranty_open_for_job(
            self._warranty_visit_job(), 'use', task=self)

    def action_warranty_full_consumption(self):
        self.ensure_one()
        return self.env['warranty.mrf.material.wizard']._warranty_open_for_job(
            self._warranty_visit_job(), 'full', task=self)

    def action_warranty_return_unused(self):
        self.ensure_one()
        return self.env['warranty.mrf.material.wizard']._warranty_open_for_job(
            self._warranty_visit_job(), 'return', task=self)

    # E-15 (D18): the Material Request is the only parts path of warranty visits.
    def action_fsm_view_material(self):
        if self.filtered('warranty_is_visit'):
            raise UserError(_("Parts of warranty visits are requested with Material Requests "
                              "(Create Material Request), not with Products."))
        return super().action_fsm_view_material()


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _warranty_check_fsm_task(self):
        task = self._get_contextual_fsm_task()
        if task and task.sudo().warranty_is_visit:
            raise UserError(_("Parts of warranty visits are requested with Material Requests, "
                              "not with Products."))

    def set_fsm_quantity(self, quantity):
        self._warranty_check_fsm_task()
        return super().set_fsm_quantity(quantity)

    def _inverse_fsm_quantity(self):
        self._warranty_check_fsm_task()
        return super()._inverse_fsm_quantity()
