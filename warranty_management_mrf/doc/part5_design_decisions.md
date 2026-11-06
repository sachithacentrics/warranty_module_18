# Warranty Management – Part 5 (Material Request / MRF Integration) – Design Decisions

Sources: SRS (`Warranty_Module_SRS (1) (1).pdf`), `Part5_MRF_Integration_Mapping.md`,
`part5.drawio.svg`, `part5_integration architecture.drawio.svg`.

| Status | Phase 5.0 development and automated tests **accepted** (2026-10-26); not approved for deployment (B1). Phase 5.1 implemented and tested on disposable databases (2026-10-26), **waiting for review**. Phase 5.2 implemented, tested on disposable databases, main workflow manually tested. Phase 5.3 implemented per `doc/part5_3_approval_design.md` rev. 2 (approved 2026-10-26), tested on disposable databases; manual testing open (blocker below). Phase 5.4 implemented and tested on disposable databases. Phase 5.5 implemented and tested on disposable databases; combined manual acceptance 5.3 - 5.5 prepared (`tests/Part5_Combined_Acceptance_5_3_to_5_5.md`), **waiting for review**. Not installed on `warranty_test` / `warranty_management_18_2`. **Deployment blocker B1 open.** |
|---|---|

## Basic decisions (approved 2026-10-26)

| ID | Topic | Approved resolution |
|---|---|---|
| A1 | Module | Separate bridge `warranty_management_mrf`; the vendor module `material_purchase_requisitions` is not modified (Python, XML, security, manifest). |
| A2 | Vendor build | Keep the current vendor build unchanged (version **11.9.12**, files dated 2026-10-26 11:57). No backport. |
| A3 | Structure | Sub-phases 5.0 - 5.9 of the mapping; one sub-phase at a time, each approved before the next. |
| A4 | Databases | Development and automated tests on disposable copies of `warranty_test` until the install on `warranty_test` is coordinated with the AMC session; `warranty_management_18_2` untouched. |

## Phase 5.0 - Foundation

* Bridge depends on `warranty_management_fsm` (brings helpdesk and core), `material_purchase_requisitions`,
  `purchase_stock`, `sale_stock`; `auto_install` off (installed explicitly).
* No model, field, view, menu, group or data in 5.0 (verified: the module owns no `ir.model.data`
  record). Warranty behaviour will only apply to requisitions linked to a warranty record (5.1);
  standalone requisitions keep the vendor workflow (test T0.3).
* **R1 - Role mapping** (SRS section 16 roles to existing groups, no new group in 5.0):

| SRS role | Groups |
|---|---|
| Service Coordinator | Helpdesk User + Requisitions User |
| Technician | Field Service User |
| Store User | Inventory User + Requisitions User |
| Material Approver | Requisitions Department Manager / Manager (+ named approver in the 5.3 rules) |
| Purchasing | Purchase User |
| Accountant | Accounting Read-only / Billing |

### Vendor module review (11.9.12)

* `material.purchase.requisition`: states New, Waiting Department Approval, Waiting IR Approval,
  Approved, Picking / Purchase Created, Received, Cancelled, Rejected. Methods
  `requisition_confirm`, `manager_approve`, `user_approve`, `requisition_reject`, `reset_draft`,
  `request_stock` (one internal picking for all Internal lines + one RFQ per vendor for Purchase
  lines), `action_received`, `action_cancel`, helpers `_prepare_pick_vals`, `_prepare_po_line`.
  Employee **and** Department required. Sequence `EPR`.
* Lines: product, description, qty, UoM, vendors, action Internal Picking / Purchase Order.
* Links: `stock.picking.custom_requisition_id`, `stock.move.custom_requisition_line_id`,
  `purchase.order.custom_requisition_id`, `purchase.order.line.custom_requisition_line_id`;
  `hr.employee` / `hr.department.dest_location_id`.
* Groups: Requisitions User, Manager (implies User), Department Manager; internal users full CRUD
  on their own requisitions (record rule), all requisitions for Requisitions User, Purchase User,
  Department Manager; multi-company rules.
* Known vendor limitations (not changed): approval e-mails use `send_mail(self.id)` (fails when
  several requisitions are confirmed / approved at once).

### B1 - Compatibility blocker (open)

`models/purchase_requisition_line.py` line 4 `import odoo.addons.decimal_precision as dp`;
`decimal_precision` was removed in Odoo 13. Loading the unchanged module on this Odoo 18 server
fails with `ModuleNotFoundError: No module named 'odoo.addons.decimal_precision'` (verified by a
plain import, no database). `dp` is never used. Everything else of the build loads on Odoo 18.

Verification only (disposable `wt_p5_mrf`): a two-file shim package `decimal_precision`
(not installable, `get_precision()` stub) on a **temporary** `--addons-path` in the session
scratchpad. With it the vendor module and the bridge install and all tests pass. The shim is
**not** part of this repository, not on the server addons path and **not an approved solution**.

Permanent resolution options (none applied):
1. **Recommended:** an Odoo 18-compatible build from the vendor (Probuse) without the import.
2. A compatibility package `decimal_precision` kept in its own addons folder (not in the vendor
   folder), added to `addons_path` of each server (environment change, needs approval; affects
   every database of that server; to be removed when the vendor build is fixed).
3. Not acceptable under A1/A2: editing the vendor file.

### Verification (2026-10-26)

Source DB: dump of `warranty_test` (182 installed modules, read-only `pg_dump`), restored twice.

| | `wt_p5_baseline` | `wt_p5_mrf` |
|---|---|---|
| Vendor MRF / bridge | not installed | installed (with the temporary shim) |
| Purchase | not installed | installed (+ Odoo auto-installs) |
| Existing tests (warranty 132, helpdesk 88, fsm 132, mrp 7, AMC 27) | **386 / 0 failed / 0 errors** | **386 / 0 failed / 0 errors** |
| Bridge tests T0.1 - T0.4 | - | **4 / 0 failed / 0 errors** (T0.4 test bug fixed and re-run) |
| Skipped tests | 0 | 0 |

Log notes (not failures): "failed sending mail … sender address" (no outgoing mail server on the
copies), `py.warnings` / duplicate-label warnings of Parts 1-4 (existing), and Odoo's test
framework "runbot" stack notes on class patching (at log level info).

## Phase 5.1 - Create / link Material Requests (2026-10-26, waiting for review)

Sources: SRS 2.10 b1, 9.6 step 5, 9.8 steps 1-2, 10.5 "Parts Required", 10.7 (MRF No., Warranty
Case, Requested Part, Quantity, Estimated Cost), 14 "Part requested", 16 Technician / Service
Coordinator, 18 `MRF/000001`; diagram "Click Create Material Request -> Create or link existing
MRF -> Link Warranty Case / Service Job / Field Service Task -> Auto-fill … -> Add material
request lines -> Determine estimated material cost".

The mapping's recommended options were implemented; **please confirm them at the review**
(they were not individually approved):

| ID | Implemented | Alternative |
|---|---|---|
| D4 | Requester = the user's employee in the case company; department from that employee; clear error when missing (the vendor requires both). | Company default department / service employee. |
| D5 | Warranty requests `MRF/000001` (new sequence `warranty.material.request`); standalone keep `EPR`. A linked standalone request keeps its `EPR` number. | One sequence for all. |
| D10 | Source: company setting, else the company's first warehouse stock. Destination: main technician's employee *Destination Location* (vendor field), else company *Technician Location*, else requester's employee / department location (vendor). Picking type: company setting, else the warehouse's internal transfers. | - |
| D19 | Optional Serial / Lot Numbers on the line (must belong to the product). | - |
| D20 | Estimated Unit Cost = product cost converted to the line UoM, editable; Estimated Cost = qty x unit cost; header total. | Vendor price for purchase lines (5.5). |
| D22 | Case: Approved, Job Created, In Progress, Chargeable. Job: Confirmed, Rescheduled, In Progress, Awaiting Parts, Workshop, Incomplete. Visit: warranty visit not Done / Cancelled, its job allowed. | - |

### Implementation

* `material.purchase.requisition` (inherit): Warranty Case / Service Job / Field Service Task
  (read-only, set only by the warranty actions; cannot be changed afterwards), stored
  *Warranty Material Request* flag, related Ticket / Customer (stored), Site, Card, Unit, Serial,
  Serviced Product; *Total Estimated Cost*. Constraints: job of the case, visit of the job, same
  company. The vendor `create` numbers the request; warranty requests are created with a context
  that makes its `next_by_code('purchase.requisition.seq')` use the MRF sequence (no gap in either
  sequence; mixed batches create one by one).
* Lines: Estimated Unit Cost, Estimated Cost, Serial / Lot Numbers.
* **Create Material Request** (case: with its open job and the job's only open visit; job: with
  its only open visit; visit task): checks the states and the requester, opens a new request
  form with the values as defaults (nothing saved until the user saves). The same checks run at
  creation (API / import).
* **Link Material Request** (case / job / visit, wizard; Helpdesk users): a New standalone
  request of the case company; already linked / not New refused.
* History: logged notes on the case and the job ("Material Request MRF/… created / linked by …")
  and on the request (links); field tracking of the links.
* Smart buttons **Material Requests** on case, job, visit task and Helpdesk ticket; menu
  **Warranty -> Material Requests** (warranty requests only, no *New*); vendor list / search:
  Warranty Case, Service Job, Customer, Total Estimated Cost; filters Warranty / Standalone
  Requests; group by Warranty Case / Service Job.
* Settings -> Warranty -> **Material Requests**: Source Location, Technician Location, Picking Type.
* Security (R1): Helpdesk users read / write / create all warranty requests (and lines);
  Field Service users read the warranty requests of jobs where they are main or support
  technician; vendor rules unchanged (own requests, Requisition / Purchase users, Department
  Managers); link wizard for Helpdesk and Field Service users.
* Not in 5.1: coverage (5.2), approvals (5.3), quotation (5.4), stock / purchase (5.5),
  consumption (5.6), cost accounting (5.7), claims (5.8), closing / reports (5.9). Repair Order
  link: Part 6 (D14).

## Phase 5.2 - Coverage classification and coverage decision (2026-10-26, waiting for review)

Sources: SRS 2.10 b2, 9.6 step 6, 10.7 "Covered Under Warranty?" / "Coverage Type", 12 "Partial
coverage and excluded item billing", 14 "Part requested -> coverage check", 16.1 goodwill row;
diagram "Classify each MRF line" / "Any Pending Coverage lines?".

Implemented as recommended in the mapping (**please confirm at the review**):

| ID | Implemented | Alternative |
|---|---|---|
| D7 | Default per line: chargeable case (status Chargeable or a chargeable case type) -> **Not Covered**; product of an **Excluded Item** of the card policy -> Not Covered; product of a **Covered Item** on an Eligible / Partial case -> **Covered**; otherwise **Pending Coverage Decision**. Policies: the case card's policy and the policies of its service cards (cross-card merge). Excluded wins when a product is both. Reviewers = **Warranty Case Approval Users** of the company; when *Warranty Case Approval Required* is off: Helpdesk users of the company (Part 3 S1 / S2). Goodwill = a reviewer decision "Covered (Goodwill)". | Own reviewer list. |
| G4 | One field *Coverage Type*; *Covered Under Warranty?* Yes / No is a computed label (empty while Pending). | - |
| T2.6 / D21 (part) | After Confirm the coverage, the products and the lines (add / delete) of a warranty request are locked; Reset to Draft (vendor, after rejection) reopens them. Quantity changes are left for 5.3 (D21). | Edit with re-approval. |

### Implementation

* Line fields: *Coverage Type* (Covered / Not Covered / Pending Coverage Decision), *Coverage
  Basis* (why the default applies), *Goodwill*, *Coverage Decided By / Date / Reason*, computed
  *Covered Under Warranty?*. A new product (or linking a standalone request to a case) resets the
  line to its default and clears an earlier decision. Coverage values sent on create are ignored;
  direct writes are refused.
* Header: stored *Coverage* (No Lines / Pending Decision / Covered / Not Covered / Mixed), counts,
  warning banner while lines are pending.
* **Request Coverage Decision** (draft, pending lines): one To-Do per reviewer, no duplicates
  while open; no reviewer configured -> error (approval required) or note (not required).
* **Decide Coverage** (wizard: lines, Covered / Covered (Goodwill) / Not Covered, reason
  required): reviewers only; never the request creator, the requester or the user who requested
  the decision (Q40 pattern). Reviewers may also override a default. Logged on the request, the
  case and the job; open To-Dos closed when no line is pending.
  Revised 2026-10-27 (manual test MRF/000004): the wizard lists all lines of the request
  (transient `warranty.mrf.coverage.wizard.line`: checkbox, Product, Quantity, Unit of Measure,
  Current Coverage Type, Coverage Basis), pending lines preselected; no *Add a line*, no line
  creation, no editing of products / quantities through the wizard; lines of another request are
  refused. Lines are shown as "MRF/…: Product (qty unit)". The decision logic is unchanged.
* **Confirm** (vendor) refused for warranty requests while a line is pending (message lists the
  products). Standalone requests unchanged.
* Lists / search: *Coverage* column, filter *Coverage Pending*, group by *Coverage*.
* Reviewers need access to the request: Helpdesk users (R1 Service Coordinator) or Requisition
  users / managers. A configured approver without these rights gets the To-Do but cannot open
  the request.
* Not in 5.2: approval routing (5.3; goodwill lines will force GM + Finance there), quotation for
  Not Covered lines (5.4), stock (5.5).

## Phase 5.3 - Material approval matrix (2026-10-26, waiting for review)

Design: `doc/part5_3_approval_design.md` revision 2 with the review decisions D-A - D-P,
Q1 - Q11 and the additional requirements 1 - 10 (approved 2026-10-26).

* `warranty.mrf.approval.rule` (Warranty -> Configuration -> Material Approval Rules, Settings
  users): company / branch, amount range, coverage, goodwill, products / categories, explicit
  *No Approval Required* or Manager / Finance / GM levels with named approvers. Rules used in an
  approval history cannot be deleted (archive).
* Company settings *Material Approval Matrix* (default on) and *Approval To-Do Deadline (days)*.
* Submit (vendor *Confirm*): routing amount = all lines at max(estimated, product cost); rules of
  the company and its parent companies, strictest combination; goodwill forces Finance + GM; no
  matching rule -> refused; approvers without requester / creator / submitter and users not
  allowed in the company; a distinct approver must exist for every level; snapshot of route,
  approvers and amounts in `warranty.mrf.approval` (round); To-Dos with deadline.
* Approve / Reject (named approvers of the pending level; Manager first, Finance and GM in any
  order; one person one level); vendor *Department Approve* / *Approve* / *Reject* executed by
  the bridge, vendor e-mails kept; Approved only when the round is complete; Approved By / Date /
  Amount, Department / Manager Approval By; requester and submitter notified; case / job notes.
* Withdraw (requester / creator, until final approval), Reset to Draft (requester / creator, from
  Rejected / Cancelled only), Cancel (requester / creator, New / Rejected), resubmission = new
  round; history kept; requests with a history cannot be deleted.
* Server-side guards (warranty requests only): status / approval / snapshot fields writable only
  by the workflow (superuser mode after its checks); header and lines locked after submission
  except Picking Details and the line action / vendors / description / serials for Requisition,
  Inventory and Purchase users until the picking exists; vendor methods check status, groups and
  separation of duties (matrix requests: vendor approval methods refused, also in superuser
  mode); *Create Picking and PO* only for complete rounds without Not Covered lines; pickings,
  moves, RFQs and PO lines can be linked to a warranty request only in that case (also in
  superuser mode); picking validation re-checks the request.
* Requests submitted before 5.3 (no round) are never approved or released (banner; withdraw and
  submit again).
* Matrix off: vendor 2-step workflow with separation of duties and the same guards.
* Named approvers read the requests routed to them, their lines and the approval history (record
  rules); no write right; the approval history is read-only for everybody.
* The 5.1 / 5.2 tests run with the matrix off (design T-9).

### Approval UI and validation improvements (approved 2026-10-27, after MRF/000004)

Root cause of the MRF/000004 message on `warranty_management_18_4` (read-only inspection): the
request was New; its only line (Bolt, Covered (Goodwill)) matched only *TEST Low Value*, whose
only Finance approver was `main_tech`. Submitted by `main_tech`, the submitter is excluded
(separation of duties, correct) and no Finance approver remained; submitted by another user, the
next blocker is GM (goodwill forces Finance + GM, no matching rule defined GM approvers). The old
message named only requester / creator / submitter and hid which approver was excluded and why.

* Submit messages name the level, the matching rules, every configured approver and the reason
  for each exclusion (requester, creator, submitter, archived user, portal user, not allowed in
  the request's company); goodwill without a matching GM / Finance rule names the goodwill lines
  and the matching rules; the distinct-approver error lists the eligible approvers per level.
  Rules and separation of duties unchanged.
* **Check Approval Route** (New warranty requests): read-only preview for the current user as
  submitter - applicable rules (condition, levels, company, matches), routing / covered / not
  covered / goodwill amounts, required levels with eligible and excluded approvers, skipped
  levels, and every reason that blocks Submit (no lines, pending coverage, route errors). Writes
  nothing on the request (no approval records, To-Dos, messages or status change); Submit still
  validates and saves the route.
* Matrix requests: Approve / Reject only for the named approvers of the current stage (unchanged,
  `can_warranty_approve` = server check). Matrix off: the vendor *Department Approve / Approve /
  Reject* buttons of **warranty** requests are shown only to users who pass the server checks
  (group, separation of duties, department approver not final approver); standalone requests keep
  the vendor group-based buttons. All server checks unchanged.

## Deployment - module upgrade required (2026-10-27)

Version 18.0.1.5.1 adds models / fields / views (`warranty.mrf.coverage.wizard.line`,
`warranty.mrf.route.preview.wizard`, the One2many coverage wizard, the vendor button flags). The
Python code and the database must always be upgraded together:

* After updating the source, run `-u warranty_management_mrf` on **every** database where the
  module is installed **before** the server serves requests with the new code. Restarting a server
  with the new code but without the upgrade loads Python models whose tables / views do not exist
  (errors in Decide Coverage, the request form and the coverage wizard).
* A running server keeps the code it loaded at start: after the upgrade, restart every Odoo
  process that uses the database (several workers / servers included).
* `warranty_management_18_4` (port 8018) still has 18.0.1.5.0 and has **not** been upgraded (needs
  the user's approval). `warranty_management_18_2` and `warranty_test` are not touched.
* No shim is needed (see the B1 correction below); the upgrade uses the database's own
  `odoo.conf`.

## Open manual-testing items

| Date | Phase | Item | Status |
|---|---|---|---|
| 2026-10-26 | 5.3 | Manual test blocker reported by the user: scheduling issue with **JOB/000002** and **WSE/00002** (existing Warranty scheduling validations of Parts 2 / 4). Recorded only; the scheduling validations are not changed or bypassed. | Open - 5.3 manual testing to be completed |
| 2026-10-26 | Part 3 | `test_13_serial_rules`: Check Eligibility reads the serial name as the user (`warranty_case.py:885 / 887`); Helpdesk users without Inventory rights get an AccessError on a serial mismatch. Reproduced without Phase 5 (`wt_p5_probe`). Fix (sudo read) needs approval of a Part 3 change. | Open - decision pending |

## Phase 5.4 - Commercial control of Not Covered lines (2026-10-26, waiting for review)

Sources: SRS 2.10 b5 ("Non-covered parts create customer quotation/invoice before issue
according to the configured commercial trigger"), 9.6 step 7, 9.8 step 5, 10.7 Customer
Quotation / Invoice, 14 "Excluded item added -> quotation", 16.1 non-covered row ("Customer
approval plus configured SO/payment trigger"); diagram lane "Commercial Coverage Control";
mapping 5.4, D8, D9.

Implemented with the mapping's recommended options - **please confirm at the review**:

| ID | Implemented | Alternative |
|---|---|---|
| D8 | The parts quotation's **own sales delivery** (standard `sale_stock`) issues the Not Covered material. Quoted / declined request lines get the line action **Customer Quotation** (bridge value of the vendor field), which the vendor *Create Picking and PO* skips - no internal picking, no RFQ, no double issue. Validation of the sales delivery is blocked until the line is released. | MRF internal picking + invoice-only quotation (would need suppressing the automatic delivery). |
| D9 | Company setting **Chargeable Parts Release**: *On Quotation Confirmation* (default) or *On Payment* (fully invoiced and every posted invoice settled - Part 3.3 rule: Paid, or In Payment covered by registered payments; partial payments and reversed invoices do not release). Stored on the quotation when it is created. **Chargeable Release Exception Users** (company) may release before payment with a reason, never the requester / creator / submitter. | Helpdesk team Chargeable Job Trigger. |
| C-1 | *Create Parts Quotation* needs Sales rights (Part 3 rule), only on approved requests (5.3 round complete), for every Not Covered line not yet quoted / declined; customer = case commercial customer, delivery address = case site, company = request company, standard pricelist prices; no e-mail - Send To-Do on the case (Part 4 C10). | - |
| C-2 | The quotation is linked to the warranty case after creation, so it never gets a Chargeable Purpose and never creates a Service Job (Part 4.10 untouched) while it is listed in the case Quotations. | Separate link only. |
| C-3 | Product, quantity and unit of a quotation line come from the approved request and cannot be changed; prices can. Lines are removed only with *Customer Declined*. One active quotation line per request line. | Editable quantities. |
| C-4 | *Customer Declined* (Helpdesk or Sales users, reason required): lines not yet quoted or waiting for the customer; removed from the open quotation (cancelled when nothing remains); never issued; not possible after the customer confirmed. A cancelled quotation puts its lines back to *To Quote*. | - |
| C-5 | *Create Picking and PO* (covered lines) requires every Not Covered line to be quoted or declined (replaces the 5.3 D-L block). | Allow covered issue while chargeable lines are undecided. |

### Implementation

* Request lines: *Chargeable Release* (To Quote / Waiting Customer / Waiting Payment / Released /
  Released (Exception) / Customer Declined), quotation lines, decline reason / by / date.
* Request: *Create Parts Quotation*, *Customer Declined*, *Approve Release Exception*; smart
  buttons Parts Quotations and Customer Deliveries; chatter + case / job notes.
* Quotation: Material Request, Parts Release Trigger, Parts Release, release exception by / date /
  reason (set by the workflow only).
* Guards: Customer Quotation line action only by the workflow and never removed; warranty fields
  of quotations / quotation lines only by the workflow; quotation line product / quantity locked;
  delivery validation only for released lines; covered release rule C-5.
* Covered / Not Covered classification, coverage decisions and the approval history are not
  changed by 5.4 (tests).

## Phase 5.5 - Availability, issue, purchasing, receipts and backorders (2026-10-26, waiting for review)

Sources: SRS 2.10 b4 - b6, 9.8 steps 3, 6, 7, 9.13 Partially Issued / Issued, 10.7 Stock
Availability / Stock Transfer, 16 Store User; diagram lane "Inventory and Purchasing"; mapping
5.5, D10, D15, D19, D-split.

New decisions, implemented as recommended - **please confirm at the review**:

| ID | Implemented | Alternative / conflict |
|---|---|---|
| F-1 | For warranty requests *Create Picking and PO* is **availability-driven**: the free quantity at the source location is issued by one internal picking, the shortage is bought by RFQs (line Vendors, else the product vendor); repeatable as **Issue / Purchase Remaining**. The vendor line action Internal / Purchase is not used for warranty lines (Customer Quotation lines are delivered by the quotation). Standalone requests keep the vendor behaviour. | Vendor per-line action (no partial issue). Conflict with 5.3 Q4 (line action editable by Store users): the action no longer matters for warranty lines. |
| F-2 | **No line splitting** (mapping D-split): approved lines stay unchanged (5.3 lock); issued / in picking / purchased / received / outstanding quantities are tracked per line. | Split lines (would change approved lines). |
| F-3 | Purchased material is received into the warehouse stock (standard receipt) and issued with *Issue / Purchase Remaining*; it is not reserved for the request in between. | Receipt directly to the technician location / MTO reservation. |
| F-4 | D15: job **Material Status** (Waiting Approval / To Issue / Shortage / Partially Issued / Issued) and an Awaiting Parts suggestion banner; no automatic hold. | Automatic hold / resume. |
| F-5 | Issue validation never exceeds the approved quantity per line (duplicate issue); *Received* only when every line (incl. quotation deliveries) is issued. | - |
| F-6 | Requested serial / lot numbers (D19, optional) are enforced at validation when set. | - |
| F-7 | Issue: Requisition or Inventory users; RFQs: Requisition or Purchase users; RFQ confirmation / receipts: standard Purchase / Inventory rights. Locations and picking type must belong to the request company. | - |

Implementation: line fields Free at Source, Stock Availability, Approved Qty, In Picking, Issued,
Outstanding, Purchased, Received, Issue Status (stored quantities from stock moves, purchase lines
and quotation deliveries; returns reduce Issued); request status Partially Issued / Issued,
Issue Progress; pickings (issue, backorders, receipts, quotation deliveries) and purchase orders
show the Warranty Material Request / Case / Service Job. Fix found by the tests: the requested
serial check of 5.1 now reads the lots in superuser mode (requesters cannot read lots).

## Phase 5.6 - Actual consumption and unused returns (2026-10-27, waiting for review)

Design `doc/part5_6_consumption_design.md` revision 2, E-1 - E-15 approved 2026-10-27 with the
user's safeguards (E-7 delivery is not installation, E-12 authorisation / reason / audit, E-13
Draft and Rejected requests block, E-13b coordinator cancel with reason). Version 18.0.1.6.0
(new dependency `industry_fsm_sale`, installed on all Warranty databases).

Implementation:

* `warranty.mrf.consumption` (*Material Usage*): one record per event - Used (validated move
  technician location -> Warranty Consumption), Installed / Customer Keeps (customer-paid parts, no
  stock move), Unused Return / Customer Return (transfer), Cancelled Remaining. Read-only for
  users, written by the workflow after its checks, never deleted; Used / Installed / Kept entries
  are reversed with a reason (Reverse Consumption: move back to the technician location).
* Request lines: Used / Installed, Customer Keeps, Returned, In Return, Cancelled, To Reconcile,
  Reconciliation (To Reconcile / Return Pending / Reconciled). Consumption and return moves do
  **not** carry the vendor line link, so the 5.5 *Issued* quantity is unchanged by them.
* Actions (request, job, visit): Record Used Parts, Confirm Full Consumption (confirmation tick +
  dialog, remaining serials, stock check), Return Unused (one transfer technician location ->
  request source, flagged *Warranty Unused Return*, validated by Inventory users only, never above
  the recorded quantity or with other serials), Customer Keeps / Customer Return (Helpdesk or Sales
  users, reason; customer return = standard return of the quotation delivery with *Update
  quantities on SO*, validated by the store, credit note by Sales), Cancel Remaining (requester,
  creator, Requisition Manager or Requisition + Inventory user; reason; not issued, not on an open
  transfer / purchase order). Request Cancel (New / Rejected) asks for a reason; requester, creator
  or Service Coordinator (Helpdesk + Requisition user).
* Limits: quantity <= to reconcile of the line; covered parts <= unreserved stock at the technician
  location (no negative stock); serials / lots only those issued (delivered) for the line and not
  yet used, kept or on a return; one serial per unit, one lot per entry.
* Statuses: **Returned** = everything reconciled, return transfers still open (store validation
  pending); **Closed** = everything reconciled, nothing open. Interpretation of SRS 9.13
  "Issued -> Returned -> Closed".
* Completion blocker (`_warranty_completion_blockers`, Part 4 hook): requests of the job that are
  New, Rejected, waiting for approval, legacy, have quantities to issue / on an open issue transfer,
  quantities to reconcile, or customer-paid lines not quoted / confirmed / paid / delivered /
  resolved. Return Pending, Cancelled, Closed, Customer Declined and case-only requests do not block.
  Incomplete / Reschedule (4.8) closes the visit without this hook (tested).
* Materials tab on the job (all lines, quantities, open items, usage history), Material Usage tab on
  warranty visits, Returns smart button and Material Usage tab on the request, setting *Warranty
  Consumption Location* (created on first use: Inventory Loss type under Virtual Locations).
* E-15: Products button hidden on warranty visits; `action_fsm_view_material` and the product
  quantity setters refused for warranty visits; ordinary Field Service tasks unchanged (tested).
* Valuation verified by the tests on this database (Standard Price, Manual valuation): the
  consumption move has one outgoing valuation layer (-qty x standard price), no journal entry; the
  reversal an incoming layer. No warranty expense entries in 5.6 (5.7 / Part 8).

Deviations / notes:

* Customer return serials: the standard return wizard reserves the return; the recorded serials
  are enforced when the store validates it.
* Not Covered lines not yet quoted are not cancelled with Cancel Remaining (use Customer Declined,
  5.4); after confirmation the quotation quantities belong to Sales (customer return).
* After the job is completed (or cancelled) no further usage, returns or reversals are recorded;
  return transfers created before can still be validated by the store.
* The mobile Field Service form has no Products button of its own; the server-side refusal covers it.
* Found by the Part 4 regression (`test_145_completion_mode`, Helpdesk user opening a job form):
  Helpdesk users without Inventory rights may not read stock moves, transfers or lots. Usage
  lists therefore show *Transfer* and *Serial / Lot* as text (computed in superuser mode); the
  raw stock fields of a usage record are shown to Inventory and Field Service users only. Selecting
  serials of customer-paid parts (Customer Keeps / Return) needs a user who can read lots (Sales
  or Inventory rights).

### Phase 5.6 backward compatibility - pre-matrix requests (approved 2026-10-27, 18.0.1.6.1)

Found by the trial upgrade of a copy of `warranty_management_18_4`: MRF/000003 (Received through
the Requisition workflow before the approval matrix, no approval round) blocked JOB/000001
permanently (legacy requests allowed no material action and cannot be withdrawn once Received).

* Pre-matrix warranty requests in Picking / PO Created or Received accept Record Used Parts,
  Return Unused and (authorised, reason) Reverse - only for the quantities of their **validated
  issue moves** (5.5 *Issued* from the move history; a Received request is not assumed to be fully
  issued). Same limits, serial rules, access rights and reasons as other requests.
* They are never approved or issued again (5.3 guards unchanged: no Create Picking and PO / Issue
  Remaining, vendor approvals refused, open transfers of the earlier workflow cannot be validated
  and are cancelled). Completion blocker for them: open transfers of the earlier workflow and
  quantities to reconcile only. Their status becomes Returned / Closed when reconciled; state,
  approval round (none), transfers and history are unchanged.
* Unused-return transfers are exempt from the 5.3 release guard (they issue nothing and have their
  own checks), so they can also be linked to pre-matrix requests.
* Pre-matrix requests still Approved (nothing issued) keep the withdraw / resubmit rule.
* Test `test_09_legacy_requests`; verified on the upgrade copy: MRF/000003 reconcilable, then only
  the legitimate blockers of JOB/000001 remain (MRF/000002 waiting for approval, MRF/000001 New).

### Correction - blocker B1 (2026-10-27)

Odoo 18 keeps a compatibility alias: `odoo/addons/base/models/decimal_precision.py` (lines 69-73)
registers `odoo.addons.decimal_precision` when `base` is loaded, i.e. before any addon. The vendor
import `import odoo.addons.decimal_precision as dp` therefore works in a normal server start (proven
on `warranty_management_18_4`, which runs with `odoo.conf` and no shim). The original B1 test
imported the vendor file without loading `base`. B1 is **not a blocker**; the shim in the
disposable environment was not needed (kept there unchanged until cleanup is approved).

## Phase 5.7 - Estimated, approved and actual material cost (2026-10-27, waiting for review)

Design `doc/part5_7_cost_design.md` revision 1, H-1 - H-12 approved 2026-10-27 with the user's
safeguards (verified vs unverified cost, separate buckets, snapshot preservation, Not Recorded
(Legacy), no journal entries, consistent access, company currency). Version 18.0.1.7.0; no new
dependency (Accounting / Stock Accounting already installed through Sales / Purchase Stock).

Implementation (`models/material_purchase_requisition_cost.py`, `views/warranty_mrf_cost_views.xml`):

* Line **Cost Bucket**: Covered / Goodwill / Customer Paid / Pending-Unclassified (from coverage
  and goodwill). **Warranty Material Cost = Covered + Goodwill verified actual cost.**
* **Approved snapshot** per line (*Approved Unit Cost*, *Approved Cost*) written when the request
  gets its approval date (matrix final approval and vendor 2-step); = the line routing cost, so
  the lines add up to the header *Approved Amount*. Users cannot write it (create / write guard,
  also on New requests); cancellations never change it. *Approved Cost Status*: Recorded / Not
  Recorded (approved before 5.7) / Not Recorded (Legacy) / Not Approved.
* **Actual cost** (stored, recomputed from the moves and layers, superuser): Used entries -> the
  consumption move's valuation layers (reversed entries are excluded and their value shown as
  *Reversed Cost*, so a reversal after a cost change can never make the cost negative or
  inflated); customer-paid lines -> sales delivery layers minus customer returns valued at the
  **unit cost of the returned delivery** (*Customer Returned Cost*); issue and unused-return
  transfers (internal) are never cost. Moves without a layer: move price, else product cost,
  in **Actual Cost (Unverified)** with *Cost Status* Unverified / Estimated, never in the verified
  amount; totals show a warning note and the report has an *Unverified Cost* filter.
* *Cancelled Cost* = cancelled qty x approved unit cost; *Approved (Net)* = approved - cancelled;
  *Variance* = actual (verified + unverified) - approved (net).
* Customer billing (separate, never warranty cost): *Customer Invoiced* (posted invoices),
  *Customer Credited* (posted credit notes), *Customer Billed (Net)*, company-currency balances of
  the quotation lines' invoice lines; an invoice line linked to several warranty quotation lines
  counts for one request line only.
* Totals (computed, read-only) on request, service job and warranty case: Estimated, Approved
  (Net), Warranty Material Cost, Unverified, Customer-Paid Parts Cost, Customer Billed, and a
  bucket x measure summary table (*Material Cost* tab). Job / case totals exclude the
  estimated / approved cost of Cancelled and Rejected requests; their actual cost always counts.
  Case = all its requests (job-linked and case-only); job = its requests.
* Report **Warranty Material Cost** (`warranty.mrf.cost.report`, SQL view over the stored line
  values; pivot / list / graph; filters Warranty Cost, Customer Paid, Unverified, Approved Cost
  Not Recorded, With Reversals, With Cancellations): menus **Warranty -> Reports -> Warranty
  Material Cost** (SRS section 6; new reusable Reports submenu, shown only to users who can open
  one of its reports; the earlier Warranty -> Material Cost entry was moved there) and
  Accounting -> Reporting -> Warranty Material Cost.
* **Access (H-11)**: every cost field has field-level groups (Helpdesk users, Requisition users,
  Accounting Billing / Read-only), so other users (technicians) get an AccessError on read,
  search_read, read_group and export and the fields are removed from their views; report read
  access for the same groups only, multi-company record rule. Accountants without Helpdesk rights
  use the report.
* **Accounting**: no journal entry, no account or valuation setting changed (tests assert both).
* **Currency / companies**: valuation layer and journal item balances are company-currency values
  of the request's company (moves and quotations are created in the request company); no PO /
  invoice foreign-currency price is used; report rows carry the request company's currency.
* Upgrade (`migrations/18.0.1.7.0/post-migrate.py`): requests approved before 5.7 get the snapshot
  only when the current line routing costs still equal the recorded *Approved Amount* (note on the
  request); otherwise Not Recorded with a note; legacy requests stay Not Recorded (Legacy). No
  approval record is created or changed.

Verification:

* Tests `test_mrf_cost.py` 01 - 08 (T7.1 - T7.10: FIFO, AVCO, missing layer, reversal after a cost
  change, unused / partial returns, customer return after a cost change, invoices and credit
  notes, recompute without duplication, Cancel Remaining, goodwill with matrix off, legacy and
  upgrade snapshot, permissions incl. read_group / search_read / views, multi-company and
  currency): 8 / 8. Bridge 82 / 82. Full regression 441 tests, 0 failed, 1 error (known Part 3
  `test_13_serial_rules`).
* Trial upgrade on `wm18_4_57_check` (new disposable copy of `warranty_management_18_4` taken
  read-only on 2026-10-27): 18.0.1.7.0, no errors; MRF/000004 and MRF/000005 snapshots recorded
  (+2 notes), MRF/000002 / 000003 Not Recorded (Legacy), MRF/000001 Not Approved; MRF/000005 actual
  700 + 1,200 (Covered, verified), 4,000 customer-paid gas (delivered, not invoiced), unused returns
  0; journal entries 29, valuation layers 46, stock moves 109, approvals 6 unchanged; views and
  report load for all five users (all are Helpdesk users there, so all see costs).

Open points:

* The 5.1 *Estimated Cost* and 5.3 submitted / approved amounts on requests stay visible to the
  technicians of the job (unchanged 5.1 / 5.3 behaviour). Restricting them like the 5.7 fields is
  possible; it is a separate decision.
* Products without valuation layers (consigned stock, imported moves) are only estimated
  (Unverified); vendor price differences of purchased parts are not part of the material cost
  (standard valuation; purchase price variance stays in accounting).

## Phase 5.8 - Vendor / manufacturer reimbursement claims (2026-10-27, waiting for review)

Design `doc/part5_8_vendor_claim_design.md` revision 2 (V-1 - V-18 with the approved corrections
C1 - C8). Version 18.0.1.8.0; no new dependency. Files: `models/warranty_vendor_claim.py`,
`wizard/warranty_vendor_claim_wizard.py`, `views/warranty_vendor_claim_views.xml`, sequence `VCL/`,
security rules / access, `tests/test_vendor_claim.py`.

* **Claim** `warranty.vendor.claim` (`VCL/00001`, chatter, activities): Draft -> Waiting Approval ->
  Approved -> Sent to Vendor -> Vendor Answered -> Closed / Cancelled; lines per MRF line (qty,
  serials, actual unit cost snapshot from 5.7, claimed, accepted, vendor reason, goodwill flag,
  supplier warranty info, over-claimed); allocations of vendor credit notes.
* **Eligibility (C1)**: company *Vendor Claims* on (default **off**: nothing changes until enabled),
  product *Vendor Claimable*, bucket Covered / Goodwill (customer-paid never), verified actual cost
  (no unverified part), consumed qty. Claimed qty <= consumed qty not on another active claim;
  claimed amount <= verified actual cost of the qty; serials = consumed ones, one active claim per
  serial; checks on create / write / submit / approve with a row lock on the MRF lines, so
  concurrent claims are serialised and re-checked. Cancelled claims and vendor-rejected lines
  release the qty (a re-claim references the earlier claim).
* **Partner (C2)**: proposal = supplying vendor (purchase order of the consumed lot, else of the MRF
  line), else product *Warranty Claim Partner*, else the product vendor list; another partner needs
  an override reason (tracked, basis *Manual Override*); one partner per claim; supplier warranty
  months, reference date and expiry warning shown on the lines and as a warning box.
* **Approval (C3)**: company *Vendor Claim Warranty Approvers*, *Finance Approvers*, *Finance
  Approval Threshold*; Finance also for every goodwill claim; responsible / creator / submitter
  never approve, one person one level, two distinct approvers when Finance is needed; To-Dos;
  reject / reset to Draft with a reason; named approvers who are not coordinators read only their
  claims. Separate from the 5.3 MRF matrix.
* **Evidence (C4)**: failure description and serials before submitting; at least one attachment
  before *Mark Sent* when *Claim Evidence Required* (default on; independent of the worksheet
  attachment setting).
* **Vendor response**: accepted amount per line (0 .. claimed) -> Accepted / Partially Accepted /
  Rejected; corrections only by Finance approvers with a reason; never below allocated credit notes.
* **Recovery (C5 / C6)**: *Create Draft Credit Note* (Billing users) = draft vendor credit note
  (`in_refund`) of the accepted, unallocated amount on the company **Recovery Account** (required,
  no fallback), no taxes added, never posted by the claim; *Allocate Credit Note* = posted credit
  note of the claim partner and company, amount <= its untaxed company-currency amount not allocated
  to other claims and <= the claim's accepted, not yet allocated amount. *Recovered* = allocations
  of posted, not reversed credit notes; *Settled* = the reconciled share (offset or refunded); a
  credit note is not treated as a cash receipt; cancelled credit notes count 0 automatically.
  Allocations are archived (never deleted) by Billing users with a reason; deleting a draft credit
  note is logged on the claim.
* **Over-claim (C7)**: a consumption reversal after claiming flags the claim *Over-claimed* (To-Do
  for the responsible person and Finance, notes); submit, approval, vendor response, allocation,
  credit note and closure are blocked until corrected. Posted credit notes are never changed by the
  bridge (accounting corrections only).
* **Close**: answered claims; no draft credit note pending; an outstanding amount needs a write-off
  reason (written-off amount, operational only, no posting). Cancel with a reason, not after
  allocations of non-cancelled credit notes. Submitted claims are never deleted.
* **Figures (V-17)** on case, job and request (cost groups): Vendor Claims smart button, Vendor
  Recovery status, Claimed / Accepted / Recovered / Settled / Outstanding, *Net Warranty Material
  Cost after Recovery* (5.7 values unchanged). Credit notes show a *Warranty Claims* smart button.
* **Menus (C8)**: Warranty -> Vendor Claims; Invoicing / Accounting -> Vendors -> Warranty Vendor
  Claims (accountants). The formal Vendor Claim Recovery report is 5.9 (Warranty -> Reports).
* **Security**: Helpdesk / Requisition users create and work on claims; Accounting Billing users
  create / allocate credit notes; Accounting Read-only users read; technicians have no menu, no
  records, and the claim figures on case / job / request are protected by field groups; company
  rules on claims, lines and allocations; workflow fields protected server-side.
* **Settings** (Warranty -> Vendor Claims block): Vendor Claims, approvers, threshold, evidence,
  Recovery Account. **Product** (Purchase tab): Vendor Claimable, Warranty Claim Partner, Vendor
  Warranty (months).

Verification: 5.8 tests 9 / 9 (`test_vendor_claim.py` 01 - 09). Bridge 92 / 92; full regression
451 tests, 0 failed, 1 error (known Part 3 `test_13_serial_rules`). Trial upgrade 18.0.1.7.0 ->
18.0.1.8.0 on `wm18_4_57_restore` (copy of `warranty_management_18_4`): no errors, all record
counts identical, vendor claims off by default, all views / wizards load for the five users.
Found and fixed by the tests: coordinators closing / cancelling a claim could not read the credit
note state (now read in superuser mode for the check only).

Remaining SRS scope (not in 5.8): claim-receivable / direct cash recovery accounting without a
vendor credit note (§17, Part 8); claims from complete-unit replacements (§11); labour / travel /
subcontract recovery (Part 8); Vendor Claim Recovery Report (§15, Phase 5.9); physical return of
defective parts to the vendor (Repair / Replacement).

### Phase 5.8 fix - serial / lot selection on claim lines (2026-10-27, 18.0.1.8.1)

Reported in manual testing of VCL/00001: the claim form offered serials / lots of unrelated
products. Root cause: the claim line field `lot_ids` had no domain and allowed creating lots (only
the Create Vendor Claim wizard filtered, and it did not exclude serials already claimed); the server
check did not refuse lots on untracked parts.

* Claim line `allowed_lot_ids` (computed, superuser) = serials / lots of the line's product consumed
  on its MRF line (5.6 Used entries, not reversed; unused / customer returns and issued-only lots
  excluded) minus, for serials, those on another active claim; `lot_ids` domain on it, no create /
  create-and-edit, read-only for untracked products; the wizard uses the same rule. Recomputed from
  the MRF line (the claim line product is the MRF line product).
* Server (also imports / API): lots must be in that set, one serial per unit, one active claim per
  serial; lots on untracked parts refused.
* Found by the new test: Return Unused of serial-tracked parts by a technician without Inventory
  rights failed (AccessError on the reserved move lines); the replacement of the move lines now runs
  in superuser mode like the rest of the return (5.6 code, one line).
* Tests: `test_10_serial_selection_limited_to_consumed_serials`; 5.8 10 / 10, bridge 93 / 93, FSM
  132 / 132, part 1 227 (1 known error `test_13`). Verified on `wm18_4_581_check` (copy of
  `warranty_management_18_4`): Fan Sensor of MRF/000005 offers only FS-001 (FS-002 returned unused;
  21 lots in the database); the Compressor Relay line (untracked) offers none.

## Phase 5.9 - Closure, audit trail and reporting (2026-10-28, waiting for review)

Design `doc/part5_9_closure_audit_reporting_design.md` revision 2 (review decisions of
2026-10-27). Version 18.0.1.9.0 (includes the not yet deployed 5.8 fix 18.0.1.8.1). Files:
`models/material_purchase_requisition_closure.py`, `models/warranty_mrf_reports.py`,
`wizard/warranty_mrf_closure_wizard.py`, `views/warranty_mrf_closure_report_views.xml`,
`migrations/18.0.1.9.0/post-migrate.py`, `tests/test_mrf_closure.py`; 5.8 model change for
explicit claim-line allocations.

* **Reconciled vs Closed (K-1 / K-7)**: the computed 5.6 end state is now *Reconciled*; *Closed*
  only by **Close Material Request** (Coordinators, Requisition / Store users) with Closed By / On
  (tracked) and notes on request, case, job. Upgrade: statuses recomputed only - requests computed
  Closed before (e.g. MRF/000005) become Reconciled; no closer or date invented, nothing reopened.
* **Close checks (K-2)**: 5.6 material problems (approval, release rules, issue, usage /
  installation / resolution), open return transfers, stock moves of the request not done (issues,
  backorders, receipts, quotation deliveries / returns), RFQs not confirmed, purchase lines not
  fully received. Customer invoicing is a separate **Customer Invoicing** status (No Customer
  Billing / Pending Invoicing / Invoiced: posted invoices net of posted credit notes vs delivered
  quantities); company option **Require Customer Invoice to Close** (default off). Closure never
  creates or posts invoices. Vendor claims / credit notes / recoveries never block (K-3).
* **Freeze (K-4)**: a closed request refuses usage / install / keep / returns / reversal / Cancel
  Remaining / Confirm Full Consumption, coverage requests and decisions, Create Picking and PO /
  Issue Remaining, quotations / declines / release exceptions, Cancel / Reset / Received, header and
  line edits (also API) and new stock / purchase links. Vendor claims, credit notes, allocations,
  payments, invoices of the quotation, audit and reports continue. Stock / accounting documents
  outside the request are not frozen.
* **Reopen (K-5)**: Requisition Managers with a reason, never the person who closed it;
  **administrator exception** (Settings users, reason, logged as such). Last reopened by / on /
  reason / exception flag tracked; notes on request, case, job.
* **Batch close / case guard (K-6)**: **Close Material Requests** on the job and the case lists
  every open request with its blockers; only selected eligible requests are closed after
  re-validation (confirmation notification). Setting a case to *Closed* (any path; Part 3 has no
  Close button today) is refused while a request (not cancelled) is not closed, listing open
  obligations and requests ready to close. Job completion rules unchanged.
* **K-8 Lost / Damaged**: deferred (separate controlled inventory enhancement); such parts keep the
  request un-reconciled.
* **Recovery per claim line (report B decision)**: allocations carry the claim line; draft credit
  notes from a claim create one line and one allocation per claim line; manual allocation selects
  the line (single-line claims: automatic); limits per line and per claim. Upgrade assigns existing
  allocations of single-line claims to their line (VCL/00001); multi-line claim-level allocations
  would stay *Unassigned (claim level)* - never distributed. Job / request recovery figures now
  come from their own claim lines (no double counting of claims over several jobs); case figures
  stay claim-level.
* **Audit**: tracking added on the request header (warranty status, approval round, submitted /
  approved by, approved amount, total estimated, coverage, requester, closure / reopen fields).
  **Material Audit Trail** (`warranty.mrf.audit.event`, SQL view, no copied data): request and
  claim chatter and field changes (before / after), approval decisions, usage records and reversals
  (reason), stock moves of the request and its customer deliveries (value), credit note allocations
  / removals, credit note field changes (state, payment state); Open Document with the user's own
  access rights.
* **Reports (Warranty -> Reports)**: **Material Approval and Cost** (one row per request: stage,
  approval round / approvers / dates, estimated / approved / actual per bucket, warranty cost,
  customer billing and invoicing status, quantities, vendor claimed / accepted / recovered / settled
  / outstanding, net warranty cost, closure), **Warranty Material Cost** (5.7 unchanged + vendor
  claimed / accepted / recovered / settled / net per line), **Vendor Claim Recovery** (one row per
  claim line + unassigned rows: claimed, accepted, not accepted, recovered, settled, outstanding,
  written off, statuses), **Material Audit Trail**. Accounting / Invoicing -> Reporting shortcuts for
  A, B, D with the same actions. List / pivot (/ graph) views, filters, export. Reports flush
  pending changes and never serve stale rows.
* **Access**: reports and audit trail for Helpdesk, Requisition and Accounting (Billing /
  Read-only) users; company rules; technicians none; Customer Invoicing status has cost groups.

Verification: 5.9 tests 8 / 8 (`test_mrf_closure.py`: close checks incl. issue / RFQ / open
picking / PO receipt / open return; customer invoicing policy; freeze of every entry point and
claims / credit notes after closure; reopen rules incl. administrator exception; batch close and
case guard; reports A / B / D totals, explicit line allocation, draft credit note not recovered,
settled separate, unassigned allocation row, job figures without double counting; audit trail
before / after values, reasons, credit note changes, Open Document; access, menus, upgrade
recompute). Bridge 101 / 101; FSM 132 / 132; core / Helpdesk / MRP / AMC 227 (1 known error
`test_13_serial_rules`) = 460 tests. Updated 5.6 tests: computed end state *Reconciled* instead of
*Closed* (K-7).

Validation on `wm18_4_581_check` (copy of `warranty_management_18_4`, upgraded 18.0.1.9.0):
MRF/000005 Reconciled (not closed, no closer), Pending Invoicing (S00041), no close blocker;
MRF/000003 / 000004 blocked (Bolt issued, not recorded), MRF/000002 waiting for approval,
MRF/000001 New. Report A for WCAS/000003: estimated 9,000.50 = case form, warranty material cost
1,900 = case form; MRF/000005 claimed / accepted 1,200, recovered 0 (draft credit note). Report B
VCL/00001: one Compressor Relay line, allocation of the draft credit note assigned by the upgrade;
claimed / accepted 1,200, recovered 0, outstanding 1,200 = claim form. Report D: Relay net 1,200,
Fan Sensor 700. Case close refused (MRF/000004 open; MRF/000005 ready to close). 48 audit events
for MRF/000005.

Known limitations: tracking of computed fields and of records created in the same transaction is
written by Odoo at commit (the tests simulate the transaction boundary); the upgrade itself writes
one tracking entry *Closed -> Reconciled* per relabelled request (author OdooBot), which documents
the K-7 change.
