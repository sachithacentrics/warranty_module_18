from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero

from .material_purchase_requisition_approval import RELEASED_STATES
from .material_purchase_requisition_sale import SALE_ACTION

# Phase 5.5 (mapping 5.5, decisions F-1 - F-8): availability, issue, purchasing, backorders.
AVAILABILITY_STATES = [
    ('available', 'Available'),
    ('partial', 'Partially Available'),
    ('unavailable', 'Not Available'),
]
ISSUE_STATES = [
    ('to_issue', 'To Issue'),
    ('partial', 'Partially Issued'),
    ('issued', 'Issued'),
]
JOB_MATERIAL_STATES = [
    ('none', 'No Material Requests'),
    ('approval', 'Waiting Approval'),
    ('to_issue', 'To Issue'),
    ('shortage', 'Shortage'),
    ('partial', 'Partially Issued'),
    ('issued', 'Issued'),
]
ISSUE_GROUPS = ('material_purchase_requisitions.group_purchase_requisition_user',
                'stock.group_stock_user')
PURCHASE_GROUPS = ('material_purchase_requisitions.group_purchase_requisition_user',
                   'purchase.group_purchase_user')


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    warranty_move_ids = fields.One2many('stock.move', 'custom_requisition_line_id',
                                        string='Stock Moves', readonly=True)
    warranty_purchase_line_ids = fields.One2many('purchase.order.line',
                                                 'custom_requisition_line_id',
                                                 string='Purchase Lines', readonly=True)
    issued_qty = fields.Float(string='Issued', compute='_compute_fulfilment_qty', store=True,
                              digits='Product Unit of Measure',
                              help="Done issue moves (MRF pickings, or the quotation delivery for "
                                   "Customer Quotation lines) minus returns, in the line UoM.")
    in_issue_qty = fields.Float(string='In Picking', compute='_compute_fulfilment_qty',
                                store=True, digits='Product Unit of Measure')
    purchased_qty = fields.Float(string='Purchased', compute='_compute_fulfilment_qty',
                                 store=True, digits='Product Unit of Measure')
    received_qty = fields.Float(string='Received', compute='_compute_fulfilment_qty', store=True,
                                digits='Product Unit of Measure')
    approved_qty = fields.Float(string='Approved Qty', compute='_compute_approved_qty',
                                digits='Product Unit of Measure')
    outstanding_qty = fields.Float(string='Outstanding', compute='_compute_approved_qty',
                                   digits='Product Unit of Measure',
                                   help="Approved quantity not issued and not in an open picking.")
    available_qty = fields.Float(string='Free at Source', compute='_compute_availability',
                                 digits='Product Unit of Measure')
    availability = fields.Selection(AVAILABILITY_STATES, string='Stock Availability',
                                    compute='_compute_availability')
    issue_state = fields.Selection(ISSUE_STATES, string='Issue Status',
                                   compute='_compute_approved_qty')

    @api.depends('warranty_move_ids.state', 'warranty_move_ids.product_uom_qty',
                 'warranty_move_ids.quantity', 'warranty_move_ids.location_id',
                 'warranty_move_ids.location_dest_id', 'warranty_purchase_line_ids.state',
                 'warranty_purchase_line_ids.product_qty', 'warranty_purchase_line_ids.qty_received',
                 'sale_line_ids.qty_delivered', 'sale_line_ids.state', 'requisition_type',
                 'requisition_id.dest_location_id', 'uom')
    def _compute_fulfilment_qty(self):
        for line in self:
            issued = in_issue = purchased = received = 0.0
            uom = line.uom or line.product_id.uom_id
            if line.requisition_type == SALE_ACTION:
                for sol in line.sale_line_ids.filtered(lambda sol: sol.state != 'cancel'):
                    issued += sol.product_uom._compute_quantity(sol.qty_delivered, uom)
            else:
                dest = line.requisition_id.dest_location_id
                for move in line.warranty_move_ids.filtered(lambda move: move.state != 'cancel'):
                    qty = move.product_uom._compute_quantity(
                        move.quantity if move.state == 'done' else move.product_uom_qty, uom)
                    returning = move.location_id == dest and move.location_dest_id != dest
                    if move.state == 'done':
                        issued += -qty if returning else qty
                    elif not returning:
                        in_issue += qty
            for pol in line.warranty_purchase_line_ids.filtered(
                    lambda pol: pol.state != 'cancel'):
                purchased += pol.product_uom._compute_quantity(pol.product_qty, uom)
                received += pol.product_uom._compute_quantity(pol.qty_received, uom)
            line.update({'issued_qty': issued, 'in_issue_qty': in_issue,
                         'purchased_qty': purchased, 'received_qty': received})

    @api.depends('qty', 'issued_qty', 'in_issue_qty', 'chargeable_declined', 'cancelled_qty',
                 'returned_qty', 'requisition_type', 'requisition_id.state',
                 'requisition_id.approval_round')
    def _compute_approved_qty(self):
        for line in self:
            mrf = line.requisition_id
            approved = line.qty if (line.is_warranty_mrf and mrf.state in RELEASED_STATES
                                    and mrf.approval_round and not line.chargeable_declined) \
                else 0.0
            rounding = (line.uom or line.product_id.uom_id).rounding
            # Phase 5.6: Cancel Remaining (E-12) and validated customer returns of customer-paid
            # parts (E-7, the delivered quantity is reduced by the return) are not issued again.
            target = approved - line._warranty_not_to_issue_qty()
            outstanding = max(target - line.issued_qty - line.in_issue_qty, 0.0)
            line.approved_qty = approved
            line.outstanding_qty = outstanding
            if not approved or (float_compare(target, 0.0, precision_rounding=rounding) <= 0
                                and float_is_zero(line.issued_qty, precision_rounding=rounding)):
                line.issue_state = False
            elif float_compare(line.issued_qty, target, precision_rounding=rounding) >= 0:
                line.issue_state = 'issued'
            elif float_is_zero(line.issued_qty, precision_rounding=rounding):
                line.issue_state = 'to_issue'
            else:
                line.issue_state = 'partial'

    @api.depends('product_id', 'requisition_id.location_id', 'outstanding_qty', 'uom')
    def _compute_availability(self):
        for line in self:
            line.available_qty = line._warranty_free_qty()
            needed = line.outstanding_qty
            if not line.is_warranty_mrf or line.requisition_type == SALE_ACTION \
                    or not needed or not line.product_id.is_storable:
                line.availability = False if not needed else 'available'
            elif line.available_qty >= needed:
                line.availability = 'available'
            elif line.available_qty > 0:
                line.availability = 'partial'
            else:
                line.availability = 'unavailable'

    def _warranty_not_to_issue_qty(self):
        """Approved quantity that is not issued (again): cancelled (5.6 E-12) or returned by the
        customer (customer-paid parts, 5.6 E-7)."""
        self.ensure_one()
        returned = self.returned_qty if self.requisition_type == SALE_ACTION else 0.0
        return self.cancelled_qty + returned

    def _warranty_free_qty(self):
        """Free quantity at the request's source location (children included), line UoM."""
        self.ensure_one()
        location = self.requisition_id.location_id
        if not self.product_id or not location:
            return 0.0
        # sudo: the free quantity is read for the check only.
        product = self.product_id.sudo().with_company(self.requisition_id.company_id) \
            .with_context(location=location.id)
        if not product.is_storable:
            return float('inf')
        return max(product.uom_id._compute_quantity(product.free_qty, self.uom or product.uom_id),
                   0.0)


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    # Display only: the vendor Internal Picking / Purchase Order buttons (same domains as
    # show_picking / action_show_po) are shown when they have something to open.
    # sudo: Helpdesk / Field Service users may have no Inventory or Purchase rights.
    warranty_picking_count = fields.Integer(compute='_compute_warranty_document_counts',
                                            compute_sudo=True)
    warranty_purchase_count = fields.Integer(compute='_compute_warranty_document_counts',
                                             compute_sudo=True)

    def _compute_warranty_document_counts(self):
        Picking, Order = self.env['stock.picking'], self.env['purchase.order']
        for mrf in self:
            domain = [('custom_requisition_id', '=', mrf.id)] if mrf.id else [('id', '=', 0)]
            mrf.warranty_picking_count = Picking.search_count(domain)
            mrf.warranty_purchase_count = Order.search_count(domain)

    warranty_mrf_status = fields.Selection(selection_add=[
        ('partially_issued', 'Partially Issued'), ('issued', 'Issued')],
        ondelete={'partially_issued': 'set null', 'issued': 'set null'})
    issue_progress = fields.Char(string='Issue Progress', compute='_compute_issue_progress')
    can_warranty_fulfil = fields.Boolean(compute='_compute_issue_progress')

    @api.depends('state', 'is_warranty_mrf', 'requisition_line_ids.issued_qty',
                 'requisition_line_ids.qty', 'requisition_line_ids.chargeable_declined')
    def _compute_warranty_mrf_status(self):
        super()._compute_warranty_mrf_status()
        for mrf in self.filtered(lambda mrf: mrf.is_warranty_mrf
                                 and mrf.state in ('stock', 'receive')):
            lines = mrf.requisition_line_ids.filtered(lambda line: not line.chargeable_declined)
            done = [float_compare(line.issued_qty, line.qty - line._warranty_not_to_issue_qty(),
                                  precision_rounding=(line.uom or line.product_id.uom_id).rounding)
                    >= 0 for line in lines]
            if lines and all(done):
                mrf.warranty_mrf_status = 'issued'
            elif any(lines.mapped('issued_qty')):
                mrf.warranty_mrf_status = 'partially_issued'

    @api.depends('requisition_line_ids.issue_state', 'requisition_line_ids.outstanding_qty',
                 'state')
    def _compute_issue_progress(self):
        for mrf in self:
            lines = mrf.requisition_line_ids.filtered('approved_qty')
            issued = len(lines.filtered(lambda line: line.issue_state == 'issued'))
            mrf.issue_progress = _("%(issued)s / %(total)s lines issued", issued=issued,
                                   total=len(lines)) if lines else False
            mrf.can_warranty_fulfil = mrf.is_warranty_mrf and mrf.state in ('approve', 'stock') \
                and bool(mrf._warranty_fulfil_lines().filtered('outstanding_qty'))

    # ------------------------------------------------------------------ fulfilment
    def _warranty_fulfil_lines(self):
        """Lines issued by the request itself: not Customer Quotation (delivered by the
        quotation, D8) and not declined."""
        return self.requisition_line_ids.filtered(
            lambda line: line.requisition_type != SALE_ACTION and not line.chargeable_declined)

    def request_stock(self):
        """F-1: for warranty requests Create Picking and PO is availability-driven: the free
        quantity at the source location is issued by one internal picking, the shortage is
        bought by RFQs; it can be repeated (Issue / Purchase Remaining) until everything is
        issued. Standalone requests keep the vendor behaviour."""
        warranty = self.filtered('is_warranty_mrf')
        for mrf in warranty:
            mrf._warranty_fulfil()
        others = self - warranty
        return super(MaterialPurchaseRequisition, others).request_stock() if others else True

    def action_warranty_fulfil(self):
        return self.request_stock()

    def _warranty_fulfil(self):
        self.ensure_one()
        if self.state not in ('approve', 'stock'):
            raise UserError(_("Pickings and purchase orders are created for approved Material "
                              "Requests only."))
        self._warranty_check_release()
        user = self.env.user
        if not self.env.su and not any(user.has_group(group) for group in ISSUE_GROUPS):
            raise AccessError(_("Only Requisition / Inventory users issue materials."))
        if self.company_id not in self.env.companies and not self.env.su:
            raise AccessError(_("You are not working in %s.", self.company_id.name))
        self._warranty_check_locations()
        to_issue, to_buy, missing = [], defaultdict(list), self.env['material.purchase.requisition.line']
        for line in self._warranty_fulfil_lines():
            outstanding = line.outstanding_qty
            if float_is_zero(outstanding, precision_rounding=line.uom.rounding or 0.01):
                continue
            issue = min(outstanding, line._warranty_free_qty())
            if issue > 0:
                to_issue.append((line, issue))
            open_purchase = max(line.purchased_qty - line.received_qty, 0.0)
            shortage = outstanding - issue - open_purchase
            if shortage > 0:
                vendor = line.partner_id[:1] or line.product_id._select_seller(
                    quantity=shortage, uom_id=line.uom).partner_id[:1]
                if vendor:
                    to_buy[vendor].append((line, shortage))
                else:
                    missing |= line
        if missing:
            raise UserError(_("No stock and no vendor for %(products)s: set a vendor on the line "
                              "(Vendors) or on the product, or wait for stock.",
                              products=', '.join(missing.mapped('product_id.display_name'))))
        if not to_issue and not to_buy:
            raise UserError(_("Nothing to issue or purchase for %s now: the outstanding "
                              "quantities are in open pickings or purchase orders.", self.name))
        if to_buy and not self.env.su and not any(user.has_group(group)
                                                  for group in PURCHASE_GROUPS):
            raise AccessError(_("Only Requisition / Purchase users create purchase orders."))
        # sudo after the checks: pickings / RFQs are created by the workflow for the store user
        # (creator stays the current user).
        mrf = self.sudo()
        notes = []
        if to_issue:
            picking = mrf._warranty_create_issue_picking(to_issue)
            notes.append(_("issue picking %(picking)s (%(lines)s)", picking=picking.name,
                           lines=', '.join('%s %s %s' % (qty, line.uom.name,
                                                         line.product_id.display_name)
                                           for line, qty in to_issue)))
        for vendor, lines in to_buy.items():
            order = mrf._warranty_create_purchase(vendor, lines)
            notes.append(_("RFQ %(order)s to %(vendor)s (%(lines)s)", order=order.name,
                           vendor=vendor.name,
                           lines=', '.join('%s %s %s' % (qty, line.uom.name,
                                                         line.product_id.display_name)
                                           for line, qty in lines)))
        if mrf.state == 'approve':
            mrf.write({'state': 'stock'})
        text = _("Materials processed by %(user)s: %(notes)s.", user=user.name,
                 notes='; '.join(notes))
        mrf._message_log(body=text)
        self._warranty_log_links(text)
        return True

    def _warranty_check_locations(self):
        company = self.company_id
        # sudo: locations of other companies are read for the check only.
        mrf = self.sudo()
        for location in (mrf.location_id, mrf.dest_location_id):
            if not location:
                raise UserError(_("Set the source and destination locations (Picking Details) "
                                  "of %s.", self.name))
            if location.company_id and location.company_id != company:
                raise UserError(_("Location %(location)s does not belong to %(company)s.",
                                  location=location.display_name, company=company.name))
        if not mrf.custom_picking_type_id or mrf.custom_picking_type_id.company_id != company:
            raise UserError(_("Set an internal picking type of %s (Picking Details).",
                              company.name))

    def _warranty_create_issue_picking(self, to_issue):
        picking = self.env['stock.picking'].create({
            'partner_id': self.employee_id.user_partner_id.id,
            'location_id': self.location_id.id,
            'location_dest_id': self.dest_location_id.id,
            'picking_type_id': self.custom_picking_type_id.id,
            'note': self.reason,
            'custom_requisition_id': self.id,
            'origin': self.name,
            'company_id': self.company_id.id,
        })
        for line, qty in to_issue:
            vals = self._prepare_pick_vals(line, picking)
            vals['product_uom_qty'] = qty
            self.env['stock.move'].create(vals)
        picking.action_confirm()
        picking.action_assign()
        if not self.delivery_picking_id:
            self.write({'delivery_picking_id': picking.id})
        return picking

    def _warranty_create_purchase(self, vendor, lines):
        order = self.env['purchase.order'].with_company(self.company_id).create({
            'partner_id': vendor.id,
            'company_id': self.company_id.id,
            'custom_requisition_id': self.id,
            'origin': self.name,
            'user_id': self.env.uid,
        })
        for line, qty in lines:
            vals = self.with_context(partner_id=vendor)._prepare_po_line(line, order)
            vals['product_qty'] = qty
            self.env['purchase.order.line'].create(vals)
        return order

    def action_received(self):
        """F-5: a warranty request is Received only when every line is issued."""
        for mrf in self.filtered('is_warranty_mrf'):
            open_lines = mrf._warranty_fulfil_lines().filtered(
                lambda line: line.issue_state != 'issued') | mrf.requisition_line_ids.filtered(
                lambda line: line.requisition_type == SALE_ACTION
                and not line.chargeable_declined and line.issue_state != 'issued')
            if open_lines and mrf.state == 'stock':
                raise UserError(_("Material Request %(mrf)s is not completely issued yet "
                                  "(%(products)s).", mrf=mrf.name, products=', '.join(
                                      open_lines.mapped('product_id.display_name'))))
        return super().action_received()

    def action_view_warranty_purchases(self):
        self.ensure_one()
        return self.action_show_po()


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    warranty_mrf_id = fields.Many2one(
        'material.purchase.requisition', string='Warranty Material Request',
        compute='_compute_warranty_mrf_links', store=True, index='btree_not_null')
    warranty_mrf_case_id = fields.Many2one('warranty.case', string='MRF Warranty Case',
                                           compute='_compute_warranty_mrf_links', store=True)
    warranty_mrf_job_id = fields.Many2one('warranty.service.job', string='MRF Service Job',
                                          compute='_compute_warranty_mrf_links', store=True)

    @api.depends('custom_requisition_id', 'purchase_id.custom_requisition_id',
                 'sale_id.warranty_mrf_id')
    def _compute_warranty_mrf_links(self):
        """Issue pickings, backorders, purchase receipts and quotation deliveries of a warranty
        request (requirement 6)."""
        for picking in self:
            mrf = picking.custom_requisition_id or picking.purchase_id.custom_requisition_id \
                or picking.sale_id.warranty_mrf_id
            mrf = mrf if mrf.is_warranty_mrf else mrf.browse()
            picking.warranty_mrf_id = mrf
            picking.warranty_mrf_case_id = mrf.warranty_case_id
            picking.warranty_mrf_job_id = mrf.warranty_service_job_id

    def button_validate(self):
        """F-5 / F-6: issue moves of warranty requests never exceed the approved quantity;
        requested serial / lot numbers must be used when set."""
        for move in self.sudo().move_ids.filtered(
                lambda move: move.custom_requisition_line_id.is_warranty_mrf
                and move.state not in ('done', 'cancel')):
            line = move.custom_requisition_line_id
            dest = line.requisition_id.dest_location_id
            if move.location_id == dest:
                continue
            uom = line.uom or line.product_id.uom_id
            qty = move.product_uom._compute_quantity(move.quantity, uom)
            if float_compare(line.issued_qty + qty, line.qty - line.cancelled_qty,
                             precision_rounding=uom.rounding) > 0:
                raise UserError(_("Issuing %(qty)s %(uom)s of %(product)s would exceed the approved "
                                  "quantity of %(mrf)s (%(approved)s, already issued "
                                  "%(issued)s).", qty=qty, uom=uom.name,
                                  product=line.product_id.display_name,
                                  mrf=line.requisition_id.name,
                                  approved=line.qty - line.cancelled_qty,
                                  issued=line.issued_qty))
            if line.lot_ids and move.move_line_ids.lot_id - line.lot_ids:
                raise UserError(_("%(product)s of %(mrf)s: only the requested serial / lot "
                                  "numbers %(lots)s may be issued.",
                                  product=line.product_id.display_name,
                                  mrf=line.requisition_id.name,
                                  lots=', '.join(line.lot_ids.mapped('name'))))
        return super().button_validate()


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    warranty_mrf_case_id = fields.Many2one(related='custom_requisition_id.warranty_case_id',
                                           string='MRF Warranty Case', store=True)
    warranty_mrf_job_id = fields.Many2one(related='custom_requisition_id.warranty_service_job_id',
                                          string='MRF Service Job', store=True)


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    material_status = fields.Selection(JOB_MATERIAL_STATES, string='Material Status',
                                       compute='_compute_material_status')
    material_shortage = fields.Boolean(compute='_compute_material_status')

    @api.depends('material_request_ids.state', 'material_request_ids.warranty_mrf_status',
                 'material_request_ids.requisition_line_ids.issued_qty',
                 'material_request_ids.requisition_line_ids.in_issue_qty')
    def _compute_material_status(self):
        """Requirement 10 / D15: fulfilment of the job's warranty requests (suggestion only, no
        automatic Awaiting Parts)."""
        for job in self:
            # sudo: shown to technicians / coordinators without requisition rights.
            mrfs = job.sudo().material_request_ids.filtered(
                lambda mrf: mrf.state not in ('cancel', 'reject'))
            lines = mrfs.requisition_line_ids.filtered('approved_qty')
            shortage = any(line.availability in ('partial', 'unavailable')
                           and line.outstanding_qty for line in lines)
            job.material_shortage = shortage
            if not mrfs:
                job.material_status = 'none'
            elif mrfs.filtered(lambda mrf: mrf.state in ('draft', 'dept_confirm', 'ir_approve')):
                job.material_status = 'approval'
            elif lines and all(line.issue_state == 'issued' for line in lines):
                job.material_status = 'issued'
            elif shortage:
                job.material_status = 'shortage'
            elif any(lines.mapped('issued_qty')):
                job.material_status = 'partial'
            else:
                job.material_status = 'to_issue'
