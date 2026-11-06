from markupsafe import Markup, escape

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools import float_is_zero, format_amount

# Phase 5.7 (design doc/part5_7_cost_design.md rev. 1, H-1 - H-12 approved with safeguards):
# estimated, approved and actual material cost per line, request, service job and warranty
# case. Actual cost is read from the stock valuation layers of the material moves (never typed
# in, never posted: no journal entry, valuation configuration unchanged).
COST_BUCKETS = [
    ('covered', 'Covered'),
    ('goodwill', 'Goodwill'),
    ('customer', 'Customer Paid'),
    ('pending', 'Pending / Unclassified'),
]
WARRANTY_BUCKETS = ('covered', 'goodwill')
APPROVED_COST_STATES = [
    ('recorded', 'Recorded'),
    ('pre_cost', 'Not Recorded (approved before 5.7)'),
    ('legacy', 'Not Recorded (Legacy)'),
    ('not_approved', 'Not Approved'),
]
COST_STATUSES = [
    ('none', 'No Actual Cost'),
    ('verified', 'Verified'),
    ('unverified', 'Unverified / Estimated'),
]
# H-11: cost information for coordinators, requisition / store users and accountants only;
# technicians (Field Service only) cannot read it in any view, export or RPC call.
COST_GROUPS = ('helpdesk.group_helpdesk_user,'
               'material_purchase_requisitions.group_purchase_requisition_user,'
               'account.group_account_readonly,account.group_account_invoice')
SNAPSHOT_FIELDS = {'approved_unit_cost', 'approved_cost', 'approved_cost_recorded'}
# Requests whose estimated / approved cost no longer counts in job / case totals (H-6).
INACTIVE_REQUEST_STATES = ('cancel', 'reject')


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    cost_bucket = fields.Selection(COST_BUCKETS, string='Cost Bucket',
                                   compute='_compute_cost_bucket', store=True)
    approved_unit_cost = fields.Monetary(string='Approved Unit Cost', readonly=True, copy=False,
                                         groups=COST_GROUPS)
    approved_cost = fields.Monetary(string='Approved Cost', readonly=True, copy=False,
                                    groups=COST_GROUPS,
                                    help="Snapshot taken at final approval; never changed.")
    approved_cost_recorded = fields.Boolean(readonly=True, copy=False, groups=COST_GROUPS)
    approved_cost_state = fields.Selection(
        APPROVED_COST_STATES, string='Approved Cost Status', compute='_compute_approved_cost_state',
        store=True, groups=COST_GROUPS)
    cancelled_cost = fields.Monetary(string='Cancelled Cost', compute='_compute_actual_cost',
                                     store=True, groups=COST_GROUPS,
                                     help="Cancelled quantity at the approved unit cost.")
    approved_net_cost = fields.Monetary(string='Approved (Net)', compute='_compute_actual_cost',
                                        store=True, groups=COST_GROUPS,
                                        help="Approved cost minus cancelled quantities.")
    actual_cost = fields.Monetary(
        string='Actual Cost (Verified)', compute='_compute_actual_cost', store=True,
        groups=COST_GROUPS,
        help="From validated stock valuation layers: consumption net of reversals (covered "
             "parts), customer deliveries net of customer returns (customer-paid parts).")
    actual_unverified_cost = fields.Monetary(
        string='Actual Cost (Unverified)', compute='_compute_actual_cost', store=True,
        groups=COST_GROUPS,
        help="Moves without a stock valuation layer, valued at the move price or the product "
             "cost: an estimate, not a verified actual cost.")
    reversed_cost = fields.Monetary(string='Reversed Cost', compute='_compute_actual_cost',
                                    store=True, groups=COST_GROUPS,
                                    help="Value of reversed consumption entries (not counted).")
    returned_cost = fields.Monetary(string='Customer Returned Cost', compute='_compute_actual_cost',
                                    store=True, groups=COST_GROUPS,
                                    help="Cost of validated customer returns (deducted).")
    cost_variance = fields.Monetary(string='Variance', compute='_compute_actual_cost', store=True,
                                    groups=COST_GROUPS,
                                    help="Actual (verified + unverified) minus Approved (Net).")
    cost_status = fields.Selection(COST_STATUSES, string='Cost Status',
                                   compute='_compute_actual_cost', store=True, groups=COST_GROUPS)
    invoiced_amount = fields.Monetary(string='Customer Invoiced', compute='_compute_actual_cost',
                                      store=True, groups=COST_GROUPS)
    credited_amount = fields.Monetary(string='Customer Credited', compute='_compute_actual_cost',
                                      store=True, groups=COST_GROUPS)
    billed_amount = fields.Monetary(string='Customer Billed (Net)', compute='_compute_actual_cost',
                                    store=True, groups=COST_GROUPS,
                                    help="Posted customer invoices minus credit notes of the parts "
                                         "quotation lines, untaxed, company currency.")

    @api.depends('coverage_type', 'goodwill')
    def _compute_cost_bucket(self):
        for line in self:
            if line.coverage_type == 'not_covered':
                line.cost_bucket = 'customer'
            elif line.coverage_type == 'covered':
                line.cost_bucket = 'goodwill' if line.goodwill else 'covered'
            else:
                line.cost_bucket = 'pending'

    @api.depends('approved_cost_recorded', 'requisition_id.approval_round',
                 'requisition_id.state', 'requisition_id.approved_date')
    def _compute_approved_cost_state(self):
        for line in self:
            mrf = line.requisition_id
            if line.approved_cost_recorded:
                line.approved_cost_state = 'recorded'
            elif mrf.is_warranty_mrf and mrf._warranty_is_legacy():
                line.approved_cost_state = 'legacy'
            elif mrf.approved_date:
                line.approved_cost_state = 'pre_cost'
            else:
                line.approved_cost_state = 'not_approved'

    @api.depends(
        'requisition_id.is_warranty_mrf', 'cancelled_qty', 'approved_unit_cost', 'approved_cost',
        'approved_cost_recorded',
        'warranty_consumption_ids.state', 'warranty_consumption_ids.kind',
        'warranty_consumption_ids.move_ids.state',
        'warranty_consumption_ids.move_ids.stock_valuation_layer_ids.value',
        'sale_line_ids.move_ids.state',
        'sale_line_ids.move_ids.stock_valuation_layer_ids.value',
        'sale_line_ids.invoice_lines.parent_state', 'sale_line_ids.invoice_lines.balance')
    def _compute_actual_cost(self):
        for line in self:
            values = line._warranty_cost_values() if line.requisition_id.is_warranty_mrf else {}
            actual = values.get('verified', 0.0)
            unverified = values.get('unverified', 0.0)
            currency = line.currency_id or line.env.company.currency_id
            cancelled = line.cancelled_qty * line.approved_unit_cost \
                if line.approved_cost_recorded else 0.0
            if values.get('unverified_count'):
                status = 'unverified'
            elif values.get('valued_count'):
                status = 'verified'
            else:
                status = 'none'
            line.update({
                'actual_cost': actual,
                'actual_unverified_cost': unverified,
                'reversed_cost': values.get('reversed', 0.0),
                'returned_cost': values.get('returned', 0.0),
                'cancelled_cost': cancelled,
                'approved_net_cost': line.approved_cost - cancelled
                if line.approved_cost_recorded else 0.0,
                'cost_variance': currency.round(actual + unverified - line.approved_cost + cancelled)
                if line.approved_cost_recorded else 0.0,
                'cost_status': status,
                'invoiced_amount': values.get('invoiced', 0.0),
                'credited_amount': values.get('credited', 0.0),
                'billed_amount': values.get('invoiced', 0.0) - values.get('credited', 0.0),
            })

    # ------------------------------------------------------------------ cost sources
    @api.model
    def _warranty_move_value(self, move):
        """(cost, verified) of a done move: −Σ of its valuation layers (H-1; landed cost /
        revaluation layers of the move included), else the move price or the product cost at
        the move's company (H-2: unverified estimate)."""
        layers = move.stock_valuation_layer_ids
        if layers:
            return -sum(layers.mapped('value')), True
        qty = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
        price = abs(move.price_unit) or move.product_id.with_company(move.company_id).standard_price
        sign = -1 if move.location_id.usage not in ('internal', 'transit') else 1
        return sign * qty * price, False

    @api.model
    def _warranty_return_value(self, move):
        """(cost reduction, verified) of a customer return: the returned quantity at the unit
        cost of the delivery it returns (so a later product cost change cannot over-reduce the
        actual cost), else the return's own layer, else an unverified estimate."""
        origin = move.origin_returned_move_id
        if origin.stock_valuation_layer_ids:
            layers = origin.stock_valuation_layer_ids
            qty = sum(layers.mapped('quantity'))
            if not float_is_zero(qty, precision_rounding=origin.product_id.uom_id.rounding):
                unit = abs(sum(layers.mapped('value')) / qty)
                returned = move.product_uom._compute_quantity(move.quantity,
                                                              move.product_id.uom_id)
                return returned * unit, True
        value, verified = self._warranty_move_value(move)
        return abs(value), verified

    def _warranty_cost_values(self):
        """Actual cost figures of a warranty line (company currency of the moves' company).
        Moves counted once: consumption moves of Used entries (reversal moves excluded), sales
        deliveries / returns of the line's quotation lines; internal moves (issue, unused
        return) carry no cost (H-7)."""
        self.ensure_one()
        line = self.sudo()
        values = dict.fromkeys(('verified', 'unverified', 'reversed', 'returned', 'invoiced',
                                'credited'), 0.0)
        values.update(valued_count=0, unverified_count=0)

        def add(amount, verified):
            values['verified' if verified else 'unverified'] += amount
            values['valued_count' if verified else 'unverified_count'] += 1

        for entry in line.warranty_consumption_ids.filtered(lambda e: e.kind == 'used'):
            moves = entry.move_ids.filtered(
                lambda move: move.state == 'done'
                and move.location_id.usage in ('internal', 'transit')
                and move.location_dest_id.usage not in ('internal', 'transit'))
            for move in moves:
                amount, verified = self._warranty_move_value(move)
                if entry.state == 'done':
                    add(amount, verified)
                else:
                    values['reversed'] += amount
        for move in line.sale_line_ids.move_ids.filtered(lambda move: move.state == 'done'):
            if move.location_dest_id.usage == 'customer' \
                    and move.location_id.usage != 'customer':
                add(*self._warranty_move_value(move))
            elif move.location_id.usage == 'customer' \
                    and move.location_dest_id.usage != 'customer':
                amount, verified = self._warranty_return_value(move)
                add(-amount, verified)
                values['returned'] += amount
        # Invoices: posted customer invoice / credit note lines, each counted for one request
        # line only (the one of its first warranty quotation line).
        for aml in line.sale_line_ids.invoice_lines.filtered(
                lambda aml: aml.parent_state == 'posted'):
            owner = aml.sale_line_ids.filtered('warranty_mrf_line_id').sorted('id')[:1]
            if owner.warranty_mrf_line_id != line:
                continue
            if aml.move_id.move_type == 'out_invoice':
                values['invoiced'] -= aml.balance
            elif aml.move_id.move_type == 'out_refund':
                values['credited'] += aml.balance
        return values

    # ------------------------------------------------------------------ snapshot protection
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                if SNAPSHOT_FIELDS & set(vals):
                    raise UserError(_("The approved cost is recorded by the approval workflow."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and SNAPSHOT_FIELDS & set(vals):
            raise UserError(_("The approved cost is recorded by the approval workflow."))
        return super().write(vals)


def _cost_totals(lines, include_inactive=False):
    """Bucket totals of request lines (H-3, H-6): estimated / approved only for active requests
    (job / case), actual always (a cancelled request may still carry consumed parts)."""
    totals = {bucket: dict.fromkeys(('estimated', 'approved', 'approved_net', 'cancelled',
                                     'actual', 'unverified', 'reversed', 'returned', 'billed'),
                                    0.0) for bucket, _label in COST_BUCKETS}
    flags = {'not_recorded': 0, 'unverified': 0}
    for line in lines.sudo():
        if not line.requisition_id.is_warranty_mrf:
            continue
        values = totals[line.cost_bucket or 'pending']
        if include_inactive or line.requisition_id.state not in INACTIVE_REQUEST_STATES:
            values['estimated'] += line.estimated_cost
            if line.approved_cost_recorded:
                values['approved'] += line.approved_cost
                values['approved_net'] += line.approved_net_cost
                values['cancelled'] += line.cancelled_cost
            elif line.approved_cost_state in ('pre_cost', 'legacy'):
                flags['not_recorded'] += 1
        values['actual'] += line.actual_cost
        values['unverified'] += line.actual_unverified_cost
        values['reversed'] += line.reversed_cost
        values['returned'] += line.returned_cost
        values['billed'] += line.billed_amount
        if line.cost_status == 'unverified':
            flags['unverified'] += 1
    return totals, flags


def _cost_summary_html(env, totals, flags, currency):
    labels = dict(COST_BUCKETS)
    columns = [('estimated', env._("Estimated")), ('approved', env._("Approved")),
               ('approved_net', env._("Approved (Net)")), ('actual', env._("Actual (Verified)")),
               ('unverified', env._("Actual (Unverified)")), ('reversed', env._("Reversed")),
               ('returned', env._("Customer Returned")), ('billed', env._("Customer Billed"))]

    def money(amount):
        return escape(format_amount(env, amount, currency))

    rows = []
    for bucket, label in COST_BUCKETS:
        rows.append(Markup('<tr><th>%s</th>%s</tr>') % (labels[bucket], Markup('').join(
            Markup('<td class="text-end">%s</td>') % money(totals[bucket][key])
            for key, _title in columns)))
    warranty = {key: sum(totals[bucket][key] for bucket in WARRANTY_BUCKETS)
                for key, _title in columns}
    rows.append(Markup('<tr class="fw-bold"><th>%s</th>%s</tr>') % (
        env._("Warranty Material Cost (Covered + Goodwill)"), Markup('').join(
            Markup('<td class="text-end">%s</td>') % money(warranty[key])
            for key, _title in columns)))
    notes = []
    if flags['unverified']:
        notes.append(env._("%s line(s) have actual cost without a stock valuation layer: shown as "
                       "Unverified / Estimated, not as verified actual cost.", flags['unverified']))
    if flags['not_recorded']:
        notes.append(env._("%s line(s) have no approved cost snapshot (approved before Phase 5.7 or "
                       "legacy requests): Not Recorded.", flags['not_recorded']))
    head = Markup('').join(Markup('<th class="text-end">%s</th>') % title
                           for _key, title in columns)
    html = Markup('<table class="table table-sm o_warranty_cost_summary"><thead><tr><th>%s</th>'
                  '%s</tr></thead><tbody>%s</tbody></table>') % (
        env._("Bucket"), head, Markup('').join(rows))
    for note in notes:
        html += Markup('<div class="alert alert-warning mb-1" role="alert">%s</div>') % note
    return html


class CostTotalsMixin(models.AbstractModel):
    """Read-only material cost totals of a request, service job or warranty case (H-10)."""
    _name = 'warranty.mrf.cost.totals.mixin'
    _description = 'Warranty Material Cost Totals'

    cost_currency_id = fields.Many2one('res.currency', compute='_compute_warranty_cost_totals',
                                       groups=COST_GROUPS)
    warranty_estimated_cost = fields.Monetary(
        string='Estimated Material Cost', compute='_compute_warranty_cost_totals',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    warranty_approved_cost = fields.Monetary(
        string='Approved Material Cost (Net)', compute='_compute_warranty_cost_totals',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    warranty_material_cost = fields.Monetary(
        string='Warranty Material Cost', compute='_compute_warranty_cost_totals',
        currency_field='cost_currency_id', groups=COST_GROUPS,
        help="Verified actual cost of Covered and Goodwill parts.")
    warranty_material_cost_unverified = fields.Monetary(
        string='Warranty Material Cost (Unverified)', compute='_compute_warranty_cost_totals',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    customer_paid_cost = fields.Monetary(
        string='Customer-Paid Parts Cost', compute='_compute_warranty_cost_totals',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    customer_billed_amount = fields.Monetary(
        string='Customer Billed (Parts)', compute='_compute_warranty_cost_totals',
        currency_field='cost_currency_id', groups=COST_GROUPS)
    warranty_cost_summary = fields.Html(string='Material Cost Summary', sanitize=False,
                                        compute='_compute_warranty_cost_totals',
                                        groups=COST_GROUPS)

    def _warranty_cost_lines(self):
        raise NotImplementedError

    def _warranty_cost_include_inactive(self):
        return False

    def _compute_warranty_cost_totals(self):
        for record in self:
            currency = record.sudo().company_id.currency_id or self.env.company.currency_id
            totals, flags = _cost_totals(record._warranty_cost_lines(),
                                         record._warranty_cost_include_inactive())
            customer = totals['customer']
            record.update({
                'cost_currency_id': currency.id,
                'warranty_estimated_cost': sum(values['estimated'] for values in totals.values()),
                'warranty_approved_cost': sum(values['approved_net'] for values in totals.values()),
                'warranty_material_cost': sum(totals[bucket]['actual']
                                              for bucket in WARRANTY_BUCKETS),
                'warranty_material_cost_unverified': sum(totals[bucket]['unverified']
                                                         for bucket in WARRANTY_BUCKETS),
                'customer_paid_cost': customer['actual'] + customer['unverified'],
                'customer_billed_amount': sum(values['billed'] for values in totals.values()),
                'warranty_cost_summary': _cost_summary_html(self.env, totals, flags, currency),
            })


class MaterialPurchaseRequisition(models.Model):
    _name = 'material.purchase.requisition'
    _inherit = ['material.purchase.requisition', 'warranty.mrf.cost.totals.mixin']

    def _warranty_cost_lines(self):
        self.ensure_one()
        return self.requisition_line_ids

    def _warranty_cost_include_inactive(self):
        # A request always shows its own figures, also when it is cancelled / rejected.
        return True

    def write(self, vals):
        result = super().write(vals)
        if vals.get('approved_date'):
            # H-5: both approval paths (matrix final approval, vendor 2-step) write the date.
            self.filtered('is_warranty_mrf')._warranty_snapshot_approved_cost()
        return result

    def _warranty_snapshot_approved_cost(self):
        """Per-line approved cost at final approval: the routing cost the approvers decided on
        (so the lines add up to the header Approved Amount)."""
        for line in self.sudo().requisition_line_ids:
            unit = line.routing_cost / line.qty if line.qty else 0.0
            line.write({'approved_unit_cost': unit, 'approved_cost': line.routing_cost,
                        'approved_cost_recorded': True})

    def _warranty_migrate_approved_cost(self):
        """Upgrade to 5.7 (H-5): requests approved before 5.7 get the snapshot only when their
        current line routing costs still add up to the header Approved Amount (verified);
        otherwise, and for legacy requests, the cost stays Not Recorded. Nothing else changes."""
        done, skipped = self.browse(), self.browse()
        for mrf in self.sudo().search([('is_warranty_mrf', '=', True),
                                       ('approved_date', '!=', False),
                                       ('approval_round', '!=', 0)]):
            lines = mrf.requisition_line_ids
            lines.invalidate_recordset(['routing_cost'])
            if not lines or lines.filtered('approved_cost_recorded'):
                continue
            if mrf.currency_id.compare_amounts(sum(lines.mapped('routing_cost')),
                                               mrf.approved_amount) == 0:
                mrf._warranty_snapshot_approved_cost()
                done |= mrf
            else:
                skipped |= mrf
        for mrf in done:
            mrf.message_post(body=_("Phase 5.7 upgrade: approved cost per line recorded from the "
                                    "approved amount %s (round %s).",
                                    format_amount(self.env, mrf.approved_amount, mrf.currency_id),
                                    mrf.approval_round))
        for mrf in skipped:
            mrf.message_post(body=_("Phase 5.7 upgrade: the current line costs no longer add up "
                                    "to the approved amount %s; the approved cost per line is "
                                    "Not Recorded.",
                                    format_amount(self.env, mrf.approved_amount, mrf.currency_id)))
        return done, skipped


class WarrantyServiceJob(models.Model):
    _name = 'warranty.service.job'
    _inherit = ['warranty.service.job', 'warranty.mrf.cost.totals.mixin']

    def _warranty_cost_lines(self):
        self.ensure_one()
        return self.sudo().material_request_ids.requisition_line_ids


class WarrantyCase(models.Model):
    _name = 'warranty.case'
    _inherit = ['warranty.case', 'warranty.mrf.cost.totals.mixin']

    def _warranty_cost_lines(self):
        self.ensure_one()
        return self.sudo().material_request_ids.requisition_line_ids


class WarrantyMrfCostReport(models.Model):
    """Warranty Material Cost report (H-10): one row per warranty request line, figures from
    the stored line costs (same values as the forms). Estimated / approved figures of cancelled
    or rejected requests are 0 here as in the job / case totals; their actual cost counts."""
    _name = 'warranty.mrf.cost.report'
    _description = 'Warranty Material Cost Report'
    _auto = False
    _order = 'date desc, requisition_id desc'
    _rec_name = 'requisition_id'
    _depends = {
        'material.purchase.requisition.line': [
            'requisition_id', 'product_id', 'qty', 'cost_bucket', 'approved_cost_state',
            'cost_status', 'cancelled_qty', 'estimated_cost', 'approved_cost', 'cancelled_cost',
            'approved_net_cost', 'actual_cost', 'actual_unverified_cost', 'reversed_cost',
            'returned_cost', 'cost_variance', 'invoiced_amount', 'credited_amount',
            'billed_amount'],
        'material.purchase.requisition': [
            'company_id', 'request_date', 'warranty_case_id', 'warranty_service_job_id',
            'warranty_partner_id', 'state', 'warranty_mrf_status', 'is_warranty_mrf'],
    }

    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    date = fields.Date(string='Request Date', readonly=True)
    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     readonly=True)
    line_id = fields.Many2one('material.purchase.requisition.line', string='Request Line',
                              readonly=True)
    case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True)
    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    request_state = fields.Selection(
        lambda self: self.env['material.purchase.requisition']._fields['state'].selection,
        string='Request State', readonly=True)
    warranty_mrf_status = fields.Selection(
        lambda self: self.env['material.purchase.requisition']._fields[
            'warranty_mrf_status'].selection, string='Warranty MRF Status', readonly=True)
    cost_bucket = fields.Selection(COST_BUCKETS, string='Cost Bucket', readonly=True)
    approved_cost_state = fields.Selection(APPROVED_COST_STATES, string='Approved Cost Status',
                                           readonly=True)
    cost_status = fields.Selection(COST_STATUSES, string='Cost Status', readonly=True)
    qty = fields.Float(string='Requested Qty', readonly=True)
    cancelled_qty = fields.Float(string='Cancelled Qty', readonly=True)
    estimated_cost = fields.Monetary(string='Estimated', readonly=True)
    approved_cost = fields.Monetary(string='Approved', readonly=True)
    cancelled_cost = fields.Monetary(string='Cancelled', readonly=True)
    approved_net_cost = fields.Monetary(string='Approved (Net)', readonly=True)
    actual_cost = fields.Monetary(string='Actual (Verified)', readonly=True)
    actual_unverified_cost = fields.Monetary(string='Actual (Unverified)', readonly=True)
    reversed_cost = fields.Monetary(string='Reversed', readonly=True)
    returned_cost = fields.Monetary(string='Customer Returned', readonly=True)
    cost_variance = fields.Monetary(string='Variance', readonly=True)
    warranty_cost = fields.Monetary(string='Warranty Material Cost', readonly=True,
                                    help="Verified actual cost of Covered and Goodwill lines.")
    invoiced_amount = fields.Monetary(string='Customer Invoiced', readonly=True)
    credited_amount = fields.Monetary(string='Customer Credited', readonly=True)
    billed_amount = fields.Monetary(string='Customer Billed (Net)', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT l.id AS id,
                       l.id AS line_id,
                       r.id AS requisition_id,
                       r.company_id AS company_id,
                       c.currency_id AS currency_id,
                       r.request_date AS date,
                       r.warranty_case_id AS case_id,
                       r.warranty_service_job_id AS job_id,
                       r.warranty_partner_id AS partner_id,
                       l.product_id AS product_id,
                       r.state AS request_state,
                       r.warranty_mrf_status AS warranty_mrf_status,
                       COALESCE(l.cost_bucket, 'pending') AS cost_bucket,
                       l.approved_cost_state AS approved_cost_state,
                       l.cost_status AS cost_status,
                       l.qty AS qty,
                       l.cancelled_qty AS cancelled_qty,
                       CASE WHEN r.state IN ('cancel', 'reject') THEN 0
                            ELSE COALESCE(l.estimated_cost, 0) END AS estimated_cost,
                       CASE WHEN r.state IN ('cancel', 'reject') THEN 0
                            ELSE COALESCE(l.approved_cost, 0) END AS approved_cost,
                       CASE WHEN r.state IN ('cancel', 'reject') THEN 0
                            ELSE COALESCE(l.cancelled_cost, 0) END AS cancelled_cost,
                       CASE WHEN r.state IN ('cancel', 'reject') THEN 0
                            ELSE COALESCE(l.approved_net_cost, 0) END AS approved_net_cost,
                       COALESCE(l.actual_cost, 0) AS actual_cost,
                       COALESCE(l.actual_unverified_cost, 0) AS actual_unverified_cost,
                       COALESCE(l.reversed_cost, 0) AS reversed_cost,
                       COALESCE(l.returned_cost, 0) AS returned_cost,
                       COALESCE(l.cost_variance, 0) AS cost_variance,
                       CASE WHEN l.cost_bucket IN ('covered', 'goodwill')
                            THEN COALESCE(l.actual_cost, 0) ELSE 0 END AS warranty_cost,
                       COALESCE(l.invoiced_amount, 0) AS invoiced_amount,
                       COALESCE(l.credited_amount, 0) AS credited_amount,
                       COALESCE(l.billed_amount, 0) AS billed_amount
                  FROM material_purchase_requisition_line l
                  JOIN material_purchase_requisition r ON r.id = l.requisition_id
                  JOIN res_company c ON c.id = r.company_id
                 WHERE r.is_warranty_mrf
            )""" % self._table)
