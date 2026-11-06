# Phase 5.7 – Estimated, Approved and Actual Warranty Material Cost – Design (revision 1)

| Status | Revision 1 – H-1 – H-12 **approved 2026-10-27 with safeguards** and implemented (18.0.1.7.0) on `wt_p5_mrf`; see `part5_design_decisions.md` Phase 5.7. |
|---|---|
| Module | `warranty_management_mrf` only (inheritance + one reporting view); `material_purchase_requisitions`, Parts 1–4, AMC unchanged |
| Database | disposable `wt_p5_mrf` only; `warranty_management_18_4` untouched until approved |

## 1. Sources

* SRS §2.10 b7 / b8 ("Actual cost includes stock valuation, labour, travel, subcontract and approved
  other costs. Estimated vs approved vs actual cost must be reportable." / "Warranty cost may be
  expensed directly or applied against warranty provision/reserve according to company accounting
  configuration"), §9.8 step 8 ("Part cost is captured against warranty case"), §10.7 *Estimated
  Cost* / *Actual Cost* ("Captured from valuation, purchase/subcontract and manual approved costs"),
  §14 "Warranty cost incurred → update warranty cost/provision reports", §15 *Material Approval and
  Cost Report* (estimated / approved / actual, covered / non-covered billing, reimbursement),
  §16 Accountant (views warranty costs), §16.1 matrix ("post actual warranty cost", goodwill
  "accounting treatment"), **§17** (covered issue: "Use standard inventory valuation/stock
  accounting. Allocate actual cost to warranty case/job; optionally debit Provision/Reserve or
  Expense according to company policy"; non-covered: "invoice sales price and recognize standard
  COGS/stock valuation"; "Actual cost is locked from valuation/purchase/subcontract records;
  approved manual costs require an audit reason"), p. 79 phasing ("If accounting automation is
  postponed, track operational warranty cost first and post manual journals").
* Mapping §5.7 and D11 (accounting), D12 (labour / travel / subcontract → Part 8), D20.
* Master mapping: Part 8 = labour / travel / subcontract / provision / vendor recovery accounting.

## 2. Facts checked (read-only)

| Fact | Consequence |
|---|---|
| Line *Estimated Unit Cost / Estimated Cost* (5.1, stored). Lines are locked after Submit (5.3). | Estimated = existing fields. |
| Header snapshot at Submit: *Submitted Routing / Covered / Not Covered / Goodwill* amounts; *Approved Amount* = routing amount at final approval (5.3, also matrix-off path). Line *Routing Cost* = max(estimated, product cost) is **not stored** – it follows later product cost changes. Covered amount **includes** goodwill. | A per-line approved snapshot is missing; header snapshot stays authoritative. |
| Consumption (5.6): Used = validated move technician location → *Warranty Consumption* (Inventory Loss) with one outgoing valuation layer; Reverse = incoming layer; Unused Return = internal → internal (no layer); Installed / Customer Keeps = no move. | Covered actual cost = − Σ layers of the line's consumption moves. |
| Not Covered parts leave by the quotation delivery (5.4, WH/Stock → Customers, outgoing layer); customer returns = standard return (incoming layer). | Customer-paid cost = − Σ layers of the line's sales delivery / return moves. |
| Valuation on `warranty_management_18_4`: **Manual** everywhere; cost method Standard, one category **FIFO**, one **AVCO**. `wt_p5_mrf`: Manual / Standard. All requested products are storable. | Layer values (not product cost) are the only correct actual cost for FIFO / AVCO. |
| Helpdesk users cannot read stock moves / layers (5.6 finding). | Costs computed in superuser mode, shown read-only. |
| `wt_p5_mrf` currently holds version 18.0.1.6.0 and no request lines (earlier manual data gone). | Upgrade to 18.0.1.6.1 + new 5.7 test data before manual testing there. |

## 3. Decision table

| ID | Topic | Recommended (safest) option | Alternatives | Accounting implication |
|---|---|---|---|---|
| **H-1** | Actual cost source | Stock valuation layers of the line's moves: covered = consumption moves (net of reversals); customer-paid = sales delivery moves (net of customer returns). Read-only, never typed in ("locked from valuation", §17). Works for Standard / FIFO / AVCO. | a) qty × current product cost (wrong for FIFO / AVCO, changes with later cost updates); b) PO price of purchased parts | None – reads existing layers only. |
| **H-2** | Products without valuation layers (non-storable consumables) | Not expected today (all requested products storable). If a move has no layer: qty × product cost **at the move date is unknown**, so use the move's own unit price, else current product cost, and flag the line *Cost Source: Product Cost (not valued)*. | Treat as zero | None. |
| **H-3** | Cost buckets | Three disjoint buckets per line: **Covered** (covered, no goodwill), **Goodwill** (covered + goodwill), **Customer Paid** (Not Covered). **Warranty Cost (company-borne) = Covered + Goodwill.** Pending lines appear only in Estimated (*Pending Decision*); they can never be issued. | Goodwill inside Covered (as the 5.3 Submitted Covered amount) | None. |
| **H-4** | Customer-paid parts | Show their **cost** (delivered net of returns, COGS) and the **billed amount** (posted customer invoices − credit notes of the parts quotation lines, untaxed, company currency). Excluded from Warranty Cost. No margin calculation. | Cost only | Revenue / receivable posted by the standard invoice, as today (5.4). |
| **H-5** | Approved cost | New stored per-line snapshot *Approved Unit Cost / Approved Cost* written by the workflow at final approval (= the line's routing cost then, so Σ lines = header *Approved Amount*). Requests already approved before 5.7: filled once at upgrade from the current routing cost (lines are locked since Submit); difference to the header amount logged on the request. Pre-matrix requests (no round): **no approved cost** (shown "not recorded"). Header snapshot unchanged. | Compute live (changes when product cost changes) | None. |
| **H-6** | Cancellations | Approved snapshot is never changed (audit). **Approved (Net)** = approved − cancelled qty × approved unit cost. Variance = Actual − Approved (Net). Cancelled / Rejected requests: shown on the request, **excluded** from job / case Estimated and Approved totals; any actual cost they still carry (e.g. used before cancel) is always counted. | Reduce the snapshot | None. |
| **H-7** | Returns and reversals | Unused returns never create cost (part was not consumed). Reversals and customer returns reduce actual by their incoming layer. Issued but not yet reconciled quantities are **not** cost – shown as *Open (issued, not reconciled)* qty. | Count issue as cost | None. |
| **H-8** | Accounting posting | **No journal entries in 5.7**, no change to valuation configuration, no accounts set on the Warranty Consumption location. Warranty cost is operational (reports) – SRS p. 79 fallback "track operational warranty cost first and post manual journals". Expense / provision / reserve posting = Part 8 (D11). | Post Dr Warranty Expense / Cr Stock on consumption (would double-count with periodic manual inventory adjustments; needs accounts and a policy) | See section 4. |
| **H-9** | Labour, travel, subcontract, manual approved costs | Not in 5.7 (D12 → Part 8). 5.7 totals are labelled **Warranty Material Cost**. | Manual cost lines now | None. |
| **H-10** | Where shown | Request: cost columns per line + header totals (Estimated / Approved / Approved (Net) / Actual / Variance per bucket). Job and case: new **Material Cost** tab with the bucket × Estimated / Approved / Actual table and the per-request list. Case totals = all requests of the case (job-linked and case-only); job totals = requests of the job. Report **Warranty Material Cost** (one row per request line: company, case, job, request, status, product, bucket, qty, estimated, approved, approved net, actual, variance, billed) with pivot / graph / list. | Totals only | None. |
| **H-11** | Access | Costs visible to: Helpdesk users (coordinators), Requisition users, Accounting *Billing* / *Read-only* users (report only, via Accounting → Reporting → Warranty Material Cost and Warranty → Reporting). **Technicians** (Field Service only) do not see cost fields on jobs / visits / requests. Company record rules on the report. Nobody can edit cost values. | Everyone who sees the request | None. |
| **H-12** | Currency / company | Company currency of the request (layers are in company currency); multi-company via the request company; no conversion. | - | None. |

## 4. Accounting implications (manual valuation kept)

| Event | Inventory valuation report | General ledger (manual valuation) | 5.7 report |
|---|---|---|---|
| Purchase receipt | layer + | none; vendor bill posts the category **expense** account | – |
| Issue to technician | none (internal) | none | – |
| Covered consumption | layer − (qty × cost) | none | Actual Covered / Goodwill + |
| Reverse consumption | layer + | none | Actual − |
| Unused return | none | none | – |
| Customer-paid delivery | layer − | none for the move; customer invoice posts revenue | Actual Customer Paid +, Billed from invoice |
| Customer return | layer + | credit note by Sales | Actual Customer Paid − |

* The ledger shows **no separate warranty expense**; the accountant's periodic inventory adjustment
  covers the stock decrease. The 5.7 report is the operational source for warranty cost and for
  manual journals (Dr Warranty Expense or Provision / Cr Inventory adjustment) if Finance wants them.
* If a category is later switched to **Automated** valuation, standard Odoo posts the consumption
  move itself (Dr the Warranty Consumption location's account if set, else the category's stock
  output account / Cr Stock Valuation). 5.7 never posts, it only reads layers, so **no duplicate
  posting** is possible and the report stays correct in both modes.
* Provision / reserve utilisation (§17 "optionally debit Warranty Provision/Reserve") needs a
  provision policy and accounts → Part 8.

## 5. Model outline

* Request line (+): `approved_unit_cost`, `approved_cost` (stored snapshot), computed (superuser,
  not stored): `actual_cost`, `actual_qty_valued`, `cost_source`, `billed_amount`, `cost_bucket`,
  `approved_net_cost`, `cost_variance`.
* Request (+): header totals per bucket (computed).
* Job / case (+): bucket totals (computed), Material Cost tab.
* `warranty.mrf.cost.report` (SQL view, read-only): one row per warranty request line with stored
  bucket, estimated, approved, approved net, actual (from `stock_valuation_layer`), billed
  (posted invoice lines).
* Approval (5.3): one hook at final approval writes the line snapshot (both matrix and matrix-off
  paths). Upgrade: post-migration fills existing approved requests (H-5).

## 6. Tests (planned)

T7.1 estimated / approved / actual per line, request, job and case; T7.2 reversal reduces actual;
T7.3 unused return creates no cost; T7.4 Cancel Remaining reduces Approved (Net) only; cancelled /
rejected requests excluded from Estimated / Approved totals; T7.5 buckets Covered / Goodwill /
Customer Paid; customer-paid cost and billed amount, customer return reduces cost; T7.6 FIFO /
AVCO layer values used, not product cost; product cost change after consumption does not change
actual; T7.7 approved snapshot at final approval (matrix and matrix off); pre-matrix requests show
no approved cost; T7.8 no journal entry created by any 5.7 action, valuation settings unchanged;
T7.9 access: technician cannot read cost fields / report; accountant reads report; company rule;
T7.10 report totals equal form totals; full regression.
