from odoo import _, api, fields, models, tools
from odoo.tools import sql
from odoo.exceptions import UserError

from .warranty_vendor_claim import CLAIM_STATES, RECOVERY_STATUSES, VENDOR_RESULTS

# Phase 5.9 reports (design doc/part5_9_closure_audit_reporting_design.md rev. 2, section 6):
# read-only SQL views over the stored 5.7 / 5.8 values; one grain per report, so totals are
# never counted twice. Recovery is read from explicit claim-line allocations; recovered = posted,
# not reversed credit notes; settled = reconciled share (never a cash assumption).

# Allocation effect per credit note allocation (same rules as the 5.8 Python computation).
# A posted reversal linked to the credit note reduces its recovery in proportion; a reversal of that
# reversal restores it (same rule as account.move._warranty_reversed_ratio). F6-A: a posted note
# recognises at most its actual untaxed amount (same rule as _warranty_recovery_eligible_amount).
ALLOCATION_SQL = """
    WITH RECURSIVE reversal AS (
        SELECT r.id, r.reversed_entry_id AS root, 1 AS sign, ABS(r.amount_total_signed) AS amount
          FROM account_move r
         WHERE r.state = 'posted' AND r.reversed_entry_id IN (
                   SELECT move_id FROM warranty_vendor_claim_recovery)
        UNION ALL
        SELECT r.id, parent.root, -parent.sign, ABS(r.amount_total_signed)
          FROM account_move r
          JOIN reversal parent ON r.reversed_entry_id = parent.id
         WHERE r.state = 'posted'),
    reversed AS (
        SELECT root, SUM(sign * amount) AS amount FROM reversal GROUP BY root),
    allocated AS (
        SELECT move_id, SUM(amount) AS amount FROM warranty_vendor_claim_recovery
         WHERE active GROUP BY move_id)
    SELECT rec.id, rec.claim_id, rec.claim_line_id, rec.amount, rec.active,
           CASE WHEN rec.active AND m.state = 'posted'
                     AND COALESCE(m.payment_state, '') <> 'reversed'
                THEN ROUND((eligible.value * (1 - ratio.value) / cur.rounding)::numeric)
                     * cur.rounding
                ELSE 0 END AS recovered,
           CASE WHEN rec.active AND m.state = 'posted'
                     AND COALESCE(m.payment_state, '') <> 'reversed'
                     AND COALESCE(m.amount_total_signed, 0) <> 0
                THEN ROUND((eligible.value * GREATEST(LEAST(
                        1 - ABS(m.amount_residual_signed) / ABS(m.amount_total_signed), 1)
                        - ratio.value, 0)
                        / cur.rounding)::numeric) * cur.rounding
                ELSE 0 END AS settled
      FROM warranty_vendor_claim_recovery rec
      JOIN account_move m ON m.id = rec.move_id
      JOIN warranty_vendor_claim c ON c.id = rec.claim_id
      JOIN res_company co ON co.id = c.company_id
      JOIN res_currency cur ON cur.id = co.currency_id
      LEFT JOIN reversed rv ON rv.root = m.id
      LEFT JOIN allocated al ON al.move_id = m.id
      CROSS JOIN LATERAL (
          SELECT CASE WHEN m.state = 'posted' AND rec.active AND COALESCE(al.amount, 0) > 0
                           AND al.amount > ABS(COALESCE(m.amount_untaxed_signed, 0))
                      THEN ROUND((rec.amount * ABS(COALESCE(m.amount_untaxed_signed, 0)) / al.amount
                                  / cur.rounding)::numeric) * cur.rounding
                      ELSE rec.amount END AS value) eligible
      CROSS JOIN LATERAL (
          SELECT CASE WHEN COALESCE(m.amount_total_signed, 0) = 0 THEN 0
                      ELSE GREATEST(LEAST(COALESCE(rv.amount, 0)
                                          / ABS(m.amount_total_signed), 1), 0) END AS value) ratio
"""
CLAIM_LINE_SQL = """
    SELECT cl.id AS claim_line_id, cl.mrf_line_id, c.id AS claim_id, c.state AS claim_state,
           cl.claimed_amount AS claimed,
           CASE WHEN c.response_date IS NOT NULL THEN cl.accepted_amount ELSE 0 END AS accepted,
           COALESCE(a.recovered, 0) AS recovered, COALESCE(a.settled, 0) AS settled,
           CASE WHEN c.response_date IS NOT NULL AND c.state NOT IN ('closed', 'cancel')
                THEN GREATEST(cl.accepted_amount - COALESCE(a.recovered, 0), 0)
                ELSE 0 END AS outstanding,
           CASE WHEN c.state = 'closed'
                THEN GREATEST(cl.accepted_amount - COALESCE(a.recovered, 0), 0)
                ELSE 0 END AS written_off
      FROM warranty_vendor_claim_line cl
      JOIN warranty_vendor_claim c ON c.id = cl.claim_id
      LEFT JOIN (SELECT claim_line_id, SUM(recovered) AS recovered, SUM(settled) AS settled
                   FROM allocation WHERE claim_line_id IS NOT NULL
                  GROUP BY claim_line_id) a ON a.claim_line_id = cl.id
     WHERE c.state <> 'cancel'
"""
INVOICE_STATUSES = [('none', 'No Customer Billing'), ('pending', 'Pending Invoicing'),
                    ('invoiced', 'Invoiced')]


class WarrantyMrfReportMixin(models.AbstractModel):
    """SQL-view reports read stored values of several models: pending changes are written
    before every query so the figures always match the forms."""
    _name = 'warranty.mrf.report.mixin'
    _description = 'Warranty Material Report Mixin'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        self.env.flush_all()
        # Rows are derived values: never serve them from an earlier read of the same rows.
        self.invalidate_model()
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)


def _mrf_selection(field):
    return lambda self: self.env['material.purchase.requisition']._fields[field].selection


class WarrantyMrfApprovalCostReport(models.Model):
    """A. Material Approval and Cost (SRS 15): one row per warranty Material Request."""
    _name = 'warranty.mrf.approval.cost.report'
    _inherit = 'warranty.mrf.report.mixin'
    _description = 'Material Approval and Cost Report'
    _auto = False
    _order = 'date desc, requisition_id desc'
    _rec_name = 'requisition_id'

    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    date = fields.Date(string='Request Date', readonly=True)
    case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True)
    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    state = fields.Selection(_mrf_selection('state'), string='Request State', readonly=True)
    warranty_mrf_status = fields.Selection(_mrf_selection('warranty_mrf_status'),
                                           string='MRF Stage', readonly=True)
    approval_mode = fields.Selection(_mrf_selection('warranty_approval_mode'),
                                     string='Approval Mode', readonly=True)
    approval_round = fields.Integer(readonly=True)
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approved_date = fields.Datetime(string='Approved On', readonly=True)
    approvers = fields.Char(string='Approvers (current round)', readonly=True)
    routing_amount = fields.Monetary(string='Submitted Routing Amount', readonly=True)
    approved_amount = fields.Monetary(string='Approved Amount (header)', readonly=True)
    estimated_cost = fields.Monetary(string='Estimated', readonly=True)
    approved_cost = fields.Monetary(string='Approved (lines)', readonly=True)
    approved_net_cost = fields.Monetary(string='Approved (Net)', readonly=True)
    actual_cost = fields.Monetary(string='Actual (Verified)', readonly=True)
    actual_unverified_cost = fields.Monetary(string='Actual (Unverified)', readonly=True)
    covered_estimated = fields.Monetary(string='Covered Estimated', readonly=True)
    covered_actual = fields.Monetary(string='Covered Actual', readonly=True)
    goodwill_estimated = fields.Monetary(string='Goodwill Estimated', readonly=True)
    goodwill_actual = fields.Monetary(string='Goodwill Actual', readonly=True)
    customer_estimated = fields.Monetary(string='Customer Paid Estimated', readonly=True)
    customer_actual = fields.Monetary(string='Customer Paid Actual', readonly=True)
    warranty_cost = fields.Monetary(string='Warranty Material Cost', readonly=True)
    invoiced_amount = fields.Monetary(string='Customer Invoiced', readonly=True)
    credited_amount = fields.Monetary(string='Customer Credited', readonly=True)
    billed_amount = fields.Monetary(string='Customer Billed (Net)', readonly=True)
    invoice_status = fields.Selection(INVOICE_STATUSES, string='Customer Invoicing',
                                      readonly=True)
    qty_requested = fields.Float(string='Qty Requested', readonly=True)
    qty_issued = fields.Float(string='Qty Issued / Delivered', readonly=True)
    qty_used = fields.Float(string='Qty Used / Installed', readonly=True)
    qty_returned = fields.Float(string='Qty Returned', readonly=True)
    qty_cancelled = fields.Float(string='Qty Cancelled', readonly=True)
    has_goodwill = fields.Boolean(string='Has Goodwill Lines', readonly=True)
    has_customer_paid = fields.Boolean(string='Has Customer-Paid Lines', readonly=True)
    has_unverified = fields.Boolean(string='Has Unverified Cost', readonly=True)
    approved_not_recorded = fields.Boolean(string='Approved Cost Not Recorded', readonly=True)
    vendor_claimed = fields.Monetary(string='Vendor Claimed', readonly=True)
    vendor_accepted = fields.Monetary(string='Vendor Accepted', readonly=True)
    vendor_recovered = fields.Monetary(string='Vendor Recovered', readonly=True)
    vendor_settled = fields.Monetary(string='Vendor Settled', readonly=True)
    vendor_outstanding = fields.Monetary(string='Vendor Outstanding', readonly=True)
    net_warranty_cost = fields.Monetary(string='Net Warranty Cost after Recovery', readonly=True)
    closed = fields.Boolean(string='Formally Closed', readonly=True)
    closed_by_id = fields.Many2one('res.users', string='Closed By', readonly=True)
    closed_date = fields.Datetime(string='Closed On', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
            WITH allocation AS (%(allocation)s),
            claim_line AS (%(claim_line)s),
            line AS (
                SELECT l.requisition_id,
                       SUM(COALESCE(l.estimated_cost, 0)) AS est,
                       SUM(COALESCE(l.approved_cost, 0)) AS appr,
                       SUM(COALESCE(l.approved_net_cost, 0)) AS appr_net,
                       SUM(COALESCE(l.actual_cost, 0)) AS act,
                       SUM(COALESCE(l.actual_unverified_cost, 0)) AS unver,
                       SUM(CASE WHEN l.cost_bucket = 'covered' THEN COALESCE(l.estimated_cost, 0) ELSE 0 END) AS cov_est,
                       SUM(CASE WHEN l.cost_bucket = 'covered' THEN COALESCE(l.actual_cost, 0) ELSE 0 END) AS cov_act,
                       SUM(CASE WHEN l.cost_bucket = 'goodwill' THEN COALESCE(l.estimated_cost, 0) ELSE 0 END) AS gw_est,
                       SUM(CASE WHEN l.cost_bucket = 'goodwill' THEN COALESCE(l.actual_cost, 0) ELSE 0 END) AS gw_act,
                       SUM(CASE WHEN l.cost_bucket = 'customer' THEN COALESCE(l.estimated_cost, 0) ELSE 0 END) AS cu_est,
                       SUM(CASE WHEN l.cost_bucket = 'customer' THEN COALESCE(l.actual_cost, 0) ELSE 0 END) AS cu_act,
                       SUM(COALESCE(l.invoiced_amount, 0)) AS invoiced,
                       SUM(COALESCE(l.credited_amount, 0)) AS credited,
                       SUM(COALESCE(l.billed_amount, 0)) AS billed,
                       SUM(COALESCE(l.qty, 0)) AS qty, SUM(COALESCE(l.issued_qty, 0)) AS issued,
                       SUM(COALESCE(l.used_qty, 0)) AS used,
                       SUM(COALESCE(l.returned_qty, 0)) AS returned,
                       SUM(COALESCE(l.cancelled_qty, 0)) AS cancelled,
                       BOOL_OR(l.cost_bucket = 'goodwill') AS has_gw,
                       BOOL_OR(l.cost_bucket = 'customer') AS has_cu,
                       BOOL_OR(l.cost_status = 'unverified') AS has_unver,
                       BOOL_OR(l.approved_cost_state IN ('pre_cost', 'legacy')) AS not_recorded
                  FROM material_purchase_requisition_line l GROUP BY l.requisition_id),
            claim AS (
                SELECT ml.requisition_id, SUM(cl.claimed) AS claimed,
                       SUM(cl.accepted) AS accepted, SUM(cl.recovered) AS recovered,
                       SUM(cl.settled) AS settled, SUM(cl.outstanding) AS outstanding
                  FROM claim_line cl
                  JOIN material_purchase_requisition_line ml ON ml.id = cl.mrf_line_id
                 GROUP BY ml.requisition_id),
            approver AS (
                SELECT a.requisition_id,
                       STRING_AGG(CASE a.level WHEN 'gm' THEN 'GM' ELSE INITCAP(a.level) END
                                  || ': ' || p.name, ', ' ORDER BY a.sequence)
                           AS names
                  FROM warranty_mrf_approval a
                  JOIN material_purchase_requisition r
                    ON r.id = a.requisition_id AND a.round = r.approval_round
                  JOIN res_users u ON u.id = a.user_id
                  JOIN res_partner p ON p.id = u.partner_id
                 WHERE a.state = 'approved'
                 GROUP BY a.requisition_id),
            invoicing AS (
                SELECT ml.requisition_id,
                       BOOL_OR(sol.qty_delivered > 0) AS delivered,
                       BOOL_OR(sol.qty_delivered > COALESCE(inv.qty, 0) + 0.00001) AS pending
                  FROM sale_order_line sol
                  JOIN material_purchase_requisition_line ml ON ml.id = sol.warranty_mrf_line_id
                  LEFT JOIN (
                      SELECT rel.order_line_id,
                             SUM(CASE WHEN am.move_type = 'out_invoice' THEN aml.quantity
                                      ELSE -aml.quantity END) AS qty
                        FROM sale_order_line_invoice_rel rel
                        JOIN account_move_line aml ON aml.id = rel.invoice_line_id
                        JOIN account_move am ON am.id = aml.move_id
                       WHERE am.state = 'posted' AND am.move_type IN ('out_invoice', 'out_refund')
                       GROUP BY rel.order_line_id) inv ON inv.order_line_id = sol.id
                 WHERE NOT COALESCE(ml.chargeable_declined, FALSE)
                 GROUP BY ml.requisition_id)
            SELECT r.id AS id, r.id AS requisition_id, r.company_id, co.currency_id,
                   r.request_date AS date, r.warranty_case_id AS case_id,
                   r.warranty_service_job_id AS job_id, r.warranty_partner_id AS partner_id,
                   r.state, r.warranty_mrf_status, r.warranty_approval_mode AS approval_mode,
                   r.approval_round, r.submitted_by_id, r.submitted_date, r.approved_by_id,
                   r.approved_date, ap.names AS approvers,
                   r.approval_routing_amount AS routing_amount, r.approved_amount,
                   CASE WHEN r.state IN ('cancel', 'reject') THEN 0 ELSE COALESCE(ln.est, 0) END AS estimated_cost,
                   CASE WHEN r.state IN ('cancel', 'reject') THEN 0 ELSE COALESCE(ln.appr, 0) END AS approved_cost,
                   CASE WHEN r.state IN ('cancel', 'reject') THEN 0 ELSE COALESCE(ln.appr_net, 0) END AS approved_net_cost,
                   COALESCE(ln.act, 0) AS actual_cost, COALESCE(ln.unver, 0) AS actual_unverified_cost,
                   CASE WHEN r.state IN ('cancel', 'reject') THEN 0 ELSE COALESCE(ln.cov_est, 0) END AS covered_estimated,
                   COALESCE(ln.cov_act, 0) AS covered_actual,
                   CASE WHEN r.state IN ('cancel', 'reject') THEN 0 ELSE COALESCE(ln.gw_est, 0) END AS goodwill_estimated,
                   COALESCE(ln.gw_act, 0) AS goodwill_actual,
                   CASE WHEN r.state IN ('cancel', 'reject') THEN 0 ELSE COALESCE(ln.cu_est, 0) END AS customer_estimated,
                   COALESCE(ln.cu_act, 0) AS customer_actual,
                   COALESCE(ln.cov_act, 0) + COALESCE(ln.gw_act, 0) AS warranty_cost,
                   COALESCE(ln.invoiced, 0) AS invoiced_amount,
                   COALESCE(ln.credited, 0) AS credited_amount,
                   COALESCE(ln.billed, 0) AS billed_amount,
                   CASE WHEN NOT COALESCE(iv.delivered, FALSE) THEN 'none'
                        WHEN iv.pending THEN 'pending' ELSE 'invoiced' END AS invoice_status,
                   COALESCE(ln.qty, 0) AS qty_requested, COALESCE(ln.issued, 0) AS qty_issued,
                   COALESCE(ln.used, 0) AS qty_used, COALESCE(ln.returned, 0) AS qty_returned,
                   COALESCE(ln.cancelled, 0) AS qty_cancelled,
                   COALESCE(ln.has_gw, FALSE) AS has_goodwill,
                   COALESCE(ln.has_cu, FALSE) AS has_customer_paid,
                   COALESCE(ln.has_unver, FALSE) AS has_unverified,
                   COALESCE(ln.not_recorded, FALSE) AS approved_not_recorded,
                   COALESCE(cl.claimed, 0) AS vendor_claimed,
                   COALESCE(cl.accepted, 0) AS vendor_accepted,
                   COALESCE(cl.recovered, 0) AS vendor_recovered,
                   COALESCE(cl.settled, 0) AS vendor_settled,
                   COALESCE(cl.outstanding, 0) AS vendor_outstanding,
                   COALESCE(ln.cov_act, 0) + COALESCE(ln.gw_act, 0) - COALESCE(cl.recovered, 0)
                       AS net_warranty_cost,
                   COALESCE(r.warranty_closed, FALSE) AS closed,
                   r.warranty_closed_by_id AS closed_by_id, r.warranty_closed_date AS closed_date
              FROM material_purchase_requisition r
              JOIN res_company co ON co.id = r.company_id
              LEFT JOIN line ln ON ln.requisition_id = r.id
              LEFT JOIN claim cl ON cl.requisition_id = r.id
              LEFT JOIN approver ap ON ap.requisition_id = r.id
              LEFT JOIN invoicing iv ON iv.requisition_id = r.id
             WHERE r.is_warranty_mrf
            )""" % {'table': self._table, 'allocation': ALLOCATION_SQL,
                    'claim_line': CLAIM_LINE_SQL})

    def action_open_request(self):
        self.ensure_one()
        return self.requisition_id._warranty_action_view()


class WarrantyVendorClaimRecoveryReport(models.Model):
    """B. Vendor Claim Recovery (SRS 15): one row per claim line (explicit line allocations) and
    one row per claim for allocations without line (pre-5.9, never distributed)."""
    _name = 'warranty.vendor.claim.recovery.report'
    _inherit = 'warranty.mrf.report.mixin'
    _description = 'Vendor Claim Recovery Report'
    _auto = False
    _order = 'claim_id desc, id'
    _rec_name = 'claim_id'

    claim_id = fields.Many2one('warranty.vendor.claim', string='Claim', readonly=True)
    claim_line_id = fields.Many2one('warranty.vendor.claim.line', string='Claim Line',
                                    readonly=True)
    allocation_scope = fields.Selection([('line', 'Claim Line'),
                                         ('claim', 'Unassigned (claim level)')],
                                        string='Allocation Basis', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Vendor / Manufacturer', readonly=True)
    claim_type = fields.Selection([('vendor', 'Vendor'), ('manufacturer', 'Manufacturer')],
                                  readonly=True)
    state = fields.Selection(CLAIM_STATES, string='Claim Status', readonly=True)
    vendor_result = fields.Selection(VENDOR_RESULTS, readonly=True)
    recovery_status = fields.Selection(RECOVERY_STATUSES, readonly=True)
    case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True)
    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True)
    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    sent_date = fields.Date(readonly=True)
    response_date = fields.Date(readonly=True)
    goodwill = fields.Boolean(readonly=True)
    over_claimed = fields.Boolean(readonly=True)
    claimed_amount = fields.Monetary(string='Claimed', readonly=True)
    accepted_amount = fields.Monetary(string='Accepted', readonly=True)
    not_accepted_amount = fields.Monetary(string='Not Accepted', readonly=True)
    recovered_amount = fields.Monetary(string='Recovered', readonly=True)
    settled_amount = fields.Monetary(string='Settled', readonly=True)
    outstanding_amount = fields.Monetary(string='Outstanding', readonly=True)
    written_off_amount = fields.Monetary(string='Written Off', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
            WITH allocation AS (%(allocation)s),
            claim_line AS (%(claim_line)s)
            SELECT cl.claim_line_id * 2 AS id, c.id AS claim_id, cl.claim_line_id,
                   'line' AS allocation_scope, c.company_id, co.currency_id, c.partner_id,
                   c.claim_type, c.state, c.vendor_result, c.recovery_status, c.case_id,
                   l.job_id, l.requisition_id, l.product_id, c.sent_date, c.response_date,
                   COALESCE(l.goodwill, FALSE) AS goodwill,
                   COALESCE(l.over_claimed, FALSE) AS over_claimed,
                   cl.claimed AS claimed_amount, cl.accepted AS accepted_amount,
                   CASE WHEN c.response_date IS NOT NULL THEN cl.claimed - cl.accepted ELSE 0 END
                       AS not_accepted_amount,
                   cl.recovered AS recovered_amount, cl.settled AS settled_amount,
                   cl.outstanding AS outstanding_amount, cl.written_off AS written_off_amount
              FROM claim_line cl
              JOIN warranty_vendor_claim_line l ON l.id = cl.claim_line_id
              JOIN warranty_vendor_claim c ON c.id = cl.claim_id
              JOIN res_company co ON co.id = c.company_id
            UNION ALL
            SELECT c.id * 2 + 1 AS id, c.id AS claim_id, NULL AS claim_line_id,
                   'claim' AS allocation_scope, c.company_id, co.currency_id, c.partner_id,
                   c.claim_type, c.state, c.vendor_result, c.recovery_status, c.case_id,
                   NULL AS job_id, NULL AS requisition_id, NULL AS product_id, c.sent_date,
                   c.response_date, FALSE AS goodwill, FALSE AS over_claimed,
                   0 AS claimed_amount, 0 AS accepted_amount, 0 AS not_accepted_amount,
                   SUM(a.recovered) AS recovered_amount, SUM(a.settled) AS settled_amount,
                   0 AS outstanding_amount, 0 AS written_off_amount
              FROM allocation a
              JOIN warranty_vendor_claim c ON c.id = a.claim_id
              JOIN res_company co ON co.id = c.company_id
             WHERE a.claim_line_id IS NULL AND a.active AND c.state <> 'cancel'
             GROUP BY c.id, co.currency_id
            )""" % {'table': self._table, 'allocation': ALLOCATION_SQL,
                    'claim_line': CLAIM_LINE_SQL})


AUDIT_EVENT_TYPES = [
    ('message', 'Note / Message'),
    ('tracking', 'Field Change'),
    ('approval', 'Approval Decision'),
    ('usage', 'Material Usage'),
    ('reversal', 'Usage Reversal'),
    ('stock', 'Stock Movement'),
    ('recovery', 'Credit Note Allocation'),
    ('credit_note', 'Credit Note Change'),
]
TEXT = "regexp_replace(COALESCE(m.body::text, ''), '<[^>]*>', '', 'g')"
OLD = ("COALESCE(tv.old_value_char, tv.old_value_text, tv.old_value_datetime::text, "
       "tv.old_value_float::text, tv.old_value_integer::text)")
NEW = ("COALESCE(tv.new_value_char, tv.new_value_text, tv.new_value_datetime::text, "
       "tv.new_value_float::text, tv.new_value_integer::text)")
FIELD = "COALESCE(f.field_description->>'en_US', tv.field_info->>'desc')"


class WarrantyMrfAuditEvent(models.Model):
    """C. Material Audit Trail (material / claim part of the SRS 15 Warranty History Report):
    chronological union of the existing records - chatter and field tracking of requests and
    claims, approval decisions, usage records and reversals, stock moves of the requests and
    their customer deliveries, credit note allocations and the credit notes' own tracking.
    Nothing is copied; the source document is opened from the row."""
    _name = 'warranty.mrf.audit.event'
    _inherit = 'warranty.mrf.report.mixin'
    _description = 'Warranty Material Audit Trail'
    _auto = False
    _order = 'date desc, id desc'

    date = fields.Datetime(readonly=True)
    event_type = fields.Selection(AUDIT_EVENT_TYPES, string='Event Type', readonly=True)
    entity = fields.Selection([('request', 'Material Request'), ('claim', 'Vendor Claim')],
                              readonly=True)
    event = fields.Char(readonly=True)
    field_name = fields.Char(string='Field', readonly=True)
    old_value = fields.Char(string='Before', readonly=True)
    new_value = fields.Char(string='After', readonly=True)
    amount = fields.Float(readonly=True, digits='Product Price')
    note = fields.Text(string='Details / Reason', readonly=True)
    user_id = fields.Many2one('res.users', string='User', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True)
    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True)
    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     readonly=True)
    claim_id = fields.Many2one('warranty.vendor.claim', string='Vendor Claim', readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    res_model = fields.Char(string='Source Model', readonly=True)
    res_id = fields.Integer(string='Source ID', readonly=True)
    document = fields.Char(string='Source Document', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        mrf_join = ("JOIN material_purchase_requisition r ON m.model = "
                    "'material.purchase.requisition' AND m.res_id = r.id AND r.is_warranty_mrf")
        claim_join = ("JOIN warranty_vendor_claim c ON m.model = 'warranty.vendor.claim' "
                      "AND m.res_id = c.id")
        mrf_cols = ("r.company_id, r.warranty_case_id, r.warranty_service_job_id, r.id, "
                    "NULL::integer, NULL::integer")
        claim_cols = "c.company_id, c.case_id, NULL::integer, NULL::integer, c.id, NULL::integer"
        query = """
            CREATE OR REPLACE VIEW {table} (id, date, event_type, entity, event, field_name,
                old_value, new_value, amount, note, user_id, company_id, case_id, job_id,
                requisition_id, claim_id, product_id, res_model, res_id, document) AS (
            SELECT m.id::bigint * 16 + 1, m.date, 'message', 'request',
                   COALESCE(st.name->>'en_US', m.message_type), NULL, NULL, NULL,
                   NULL::numeric, {text}, m.create_uid, {mrf_cols},
                   'material.purchase.requisition', r.id, r.name
              FROM mail_message m {mrf_join}
              LEFT JOIN mail_message_subtype st ON st.id = m.subtype_id
             WHERE {text} <> ''
            UNION ALL
            SELECT tv.id::bigint * 16 + 2, m.date, 'tracking', 'request', 'Field change',
                   {field}, {old}, {new}, NULL::numeric, NULL, m.create_uid, {mrf_cols},
                   'material.purchase.requisition', r.id, r.name
              FROM mail_tracking_value tv JOIN mail_message m ON m.id = tv.mail_message_id
              {mrf_join} LEFT JOIN ir_model_fields f ON f.id = tv.field_id
            UNION ALL
            SELECT m.id::bigint * 16 + 3, m.date, 'message', 'claim',
                   COALESCE(st.name->>'en_US', m.message_type), NULL, NULL, NULL,
                   NULL::numeric, {text}, m.create_uid, {claim_cols},
                   'warranty.vendor.claim', c.id, c.name
              FROM mail_message m {claim_join}
              LEFT JOIN mail_message_subtype st ON st.id = m.subtype_id
             WHERE {text} <> ''
            UNION ALL
            SELECT tv.id::bigint * 16 + 4, m.date, 'tracking', 'claim', 'Field change',
                   {field}, {old}, {new}, NULL::numeric, NULL, m.create_uid, {claim_cols},
                   'warranty.vendor.claim', c.id, c.name
              FROM mail_tracking_value tv JOIN mail_message m ON m.id = tv.mail_message_id
              {claim_join} LEFT JOIN ir_model_fields f ON f.id = tv.field_id
            UNION ALL
            SELECT a.id::bigint * 16 + 5, a.decision_date, 'approval', 'request',
                   'Approval ' || CASE a.level WHEN 'gm' THEN 'GM' ELSE INITCAP(a.level) END
                       || ' ' || a.state || ' (round '
                       || a.round || ')',
                   NULL, NULL, a.state, a.routing_amount, a.reason, a.user_id, r.company_id,
                   r.warranty_case_id, r.warranty_service_job_id, r.id, NULL, NULL,
                   'material.purchase.requisition', r.id, r.name
              FROM warranty_mrf_approval a
              JOIN material_purchase_requisition r ON r.id = a.requisition_id
             WHERE a.decision_date IS NOT NULL
            UNION ALL
            SELECT e.id::bigint * 16 + 6, e.date, 'usage', 'request', 'Usage: ' || e.kind,
                   NULL, NULL, e.qty::text,
                   (SELECT -SUM(v.value) FROM stock_move mv
                      JOIN stock_valuation_layer v ON v.stock_move_id = mv.id
                     WHERE mv.warranty_consumption_id = e.id AND e.kind = 'used'
                       AND mv.location_dest_id IN (SELECT id FROM stock_location
                                                   WHERE usage NOT IN ('internal', 'transit'))),
                   e.note, e.user_id, e.company_id, e.case_id, e.job_id, e.requisition_id,
                   NULL, e.product_id, 'warranty.mrf.consumption', e.id, r.name
              FROM warranty_mrf_consumption e
              JOIN material_purchase_requisition r ON r.id = e.requisition_id
            UNION ALL
            SELECT e.id::bigint * 16 + 7, e.reversed_date, 'reversal', 'request',
                   'Reversed: ' || e.kind, NULL, 'done', 'reversed', NULL::numeric,
                   e.reverse_reason, e.reversed_by_id, e.company_id, e.case_id, e.job_id,
                   e.requisition_id, NULL, e.product_id, 'warranty.mrf.consumption', e.id, r.name
              FROM warranty_mrf_consumption e
              JOIN material_purchase_requisition r ON r.id = e.requisition_id
             WHERE e.state = 'reversed'
            UNION ALL
            SELECT mv.id::bigint * 16 + 8, mv.date, 'stock', 'request', 'Stock move done',
                   NULL, src.complete_name, dst.complete_name,
                   (SELECT SUM(v.value) FROM stock_valuation_layer v
                     WHERE v.stock_move_id = mv.id),
                   mv.reference || ' - ' || mv.product_qty::text, mv.write_uid, r.company_id,
                   r.warranty_case_id, r.warranty_service_job_id, r.id, NULL, mv.product_id,
                   CASE WHEN mv.picking_id IS NOT NULL THEN 'stock.picking' ELSE 'stock.move' END,
                   COALESCE(mv.picking_id, mv.id), mv.reference
              FROM stock_move mv
              JOIN material_purchase_requisition_line ml ON ml.id = mv.custom_requisition_line_id
              JOIN material_purchase_requisition r ON r.id = ml.requisition_id AND r.is_warranty_mrf
              JOIN stock_location src ON src.id = mv.location_id
              JOIN stock_location dst ON dst.id = mv.location_dest_id
             WHERE mv.state = 'done'
            UNION ALL
            SELECT mv.id::bigint * 16 + 9, mv.date, 'stock', 'request',
                   'Customer delivery / return done', NULL, src.complete_name,
                   dst.complete_name,
                   (SELECT SUM(v.value) FROM stock_valuation_layer v
                     WHERE v.stock_move_id = mv.id),
                   mv.reference || ' - ' || mv.product_qty::text, mv.write_uid, r.company_id,
                   r.warranty_case_id, r.warranty_service_job_id, r.id, NULL, mv.product_id,
                   CASE WHEN mv.picking_id IS NOT NULL THEN 'stock.picking' ELSE 'stock.move' END,
                   COALESCE(mv.picking_id, mv.id), mv.reference
              FROM stock_move mv
              JOIN sale_order_line sol ON sol.id = mv.sale_line_id
              JOIN material_purchase_requisition_line ml ON ml.id = sol.warranty_mrf_line_id
              JOIN material_purchase_requisition r ON r.id = ml.requisition_id
              JOIN stock_location src ON src.id = mv.location_id
              JOIN stock_location dst ON dst.id = mv.location_dest_id
             WHERE mv.state = 'done' AND mv.custom_requisition_line_id IS NULL
            UNION ALL
            SELECT rec.id::bigint * 16 + 10, rec.date, 'recovery', 'claim',
                   'Credit note allocated', NULL, NULL, am.name, rec.amount, rec.note,
                   rec.user_id, c.company_id, c.case_id, NULL, NULL, c.id, cl.product_id,
                   'account.move', am.id, am.name
              FROM warranty_vendor_claim_recovery rec
              JOIN warranty_vendor_claim c ON c.id = rec.claim_id
              JOIN account_move am ON am.id = rec.move_id
              LEFT JOIN warranty_vendor_claim_line cl ON cl.id = rec.claim_line_id
            UNION ALL
            SELECT rec.id::bigint * 16 + 11, rec.write_date, 'recovery', 'claim',
                   'Credit note allocation removed', NULL, am.name, NULL, rec.amount,
                   rec.removed_reason, rec.removed_by_id, c.company_id, c.case_id, NULL, NULL,
                   c.id, cl.product_id, 'account.move', am.id, am.name
              FROM warranty_vendor_claim_recovery rec
              JOIN warranty_vendor_claim c ON c.id = rec.claim_id
              JOIN account_move am ON am.id = rec.move_id
              LEFT JOIN warranty_vendor_claim_line cl ON cl.id = rec.claim_line_id
             WHERE NOT rec.active
            UNION ALL
            SELECT tv.id::bigint * 16 + 12, m.date, 'credit_note', 'claim',
                   'Credit note ' || am.name || ': field change', {field}, {old}, {new},
                   NULL::numeric, NULL, m.create_uid, c.company_id, c.case_id, NULL, NULL, c.id,
                   NULL, 'account.move', am.id, am.name
              FROM mail_tracking_value tv JOIN mail_message m ON m.id = tv.mail_message_id
              JOIN (SELECT DISTINCT ON (move_id) move_id, claim_id
                      FROM warranty_vendor_claim_recovery ORDER BY move_id, id) link
                ON m.model = 'account.move' AND m.res_id = link.move_id
              JOIN account_move am ON am.id = link.move_id
              JOIN warranty_vendor_claim c ON c.id = link.claim_id
              LEFT JOIN ir_model_fields f ON f.id = tv.field_id
            )""".format(table=self._table, text=TEXT, old=OLD, new=NEW, field=FIELD,
                        mrf_join=mrf_join, claim_join=claim_join, mrf_cols=mrf_cols,
                        claim_cols=claim_cols)
        self.env.cr.execute(query)

    def action_open_document(self):
        """Open the source record with the user's own access rights."""
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            raise UserError(_("No source document."))
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(_("The source document no longer exists."))
        record.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': self.res_model,
                'res_id': self.res_id, 'view_mode': 'form', 'views': [(False, 'form')],
                'target': 'current'}


class WarrantyMrfCostReport(models.Model):
    """D. Warranty Material Cost (5.7, unchanged values) + recovery of the line's claim lines
    (explicit line allocations; one row per request line, so nothing is counted twice)."""
    _name = 'warranty.mrf.cost.report'
    _inherit = ['warranty.mrf.cost.report', 'warranty.mrf.report.mixin']

    vendor_claimed_amount = fields.Monetary(string='Vendor Claimed', readonly=True)
    vendor_accepted_amount = fields.Monetary(string='Vendor Accepted', readonly=True)
    vendor_recovered_amount = fields.Monetary(string='Vendor Recovered', readonly=True)
    vendor_settled_amount = fields.Monetary(string='Vendor Settled', readonly=True)
    net_warranty_cost = fields.Monetary(
        string='Net Warranty Cost after Recovery', readonly=True,
        help="Warranty Material Cost (Covered + Goodwill, verified) minus the vendor recovery "
             "allocated to the line's claim lines.")

    def init(self):
        # Models are initialised in registration order: this 5.7 view is created before the
        # allocation table has its claim line column; the allocation model rebuilds it.
        if not sql.column_exists(self.env.cr, 'warranty_vendor_claim_recovery', 'claim_line_id'):
            return super().init()
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
            WITH allocation AS (%(allocation)s),
            claim_line AS (%(claim_line)s),
            recovery AS (
                SELECT mrf_line_id, SUM(claimed) AS claimed, SUM(accepted) AS accepted,
                       SUM(recovered) AS recovered, SUM(settled) AS settled
                  FROM claim_line GROUP BY mrf_line_id)
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
                       COALESCE(l.billed_amount, 0) AS billed_amount,
                       COALESCE(rv.claimed, 0) AS vendor_claimed_amount,
                       COALESCE(rv.accepted, 0) AS vendor_accepted_amount,
                       COALESCE(rv.recovered, 0) AS vendor_recovered_amount,
                       COALESCE(rv.settled, 0) AS vendor_settled_amount,
                       CASE WHEN l.cost_bucket IN ('covered', 'goodwill')
                            THEN COALESCE(l.actual_cost, 0) ELSE 0 END
                           - COALESCE(rv.recovered, 0) AS net_warranty_cost
                  FROM material_purchase_requisition_line l
                  JOIN material_purchase_requisition r ON r.id = l.requisition_id
                  JOIN res_company c ON c.id = r.company_id
                  LEFT JOIN recovery rv ON rv.mrf_line_id = l.id
                 WHERE r.is_warranty_mrf
            )""" % {'table': self._table, 'allocation': ALLOCATION_SQL,
                    'claim_line': CLAIM_LINE_SQL})
