# Phase 5.9 – Closure, Audit Trail and Reporting – Design (revision 2)

| Status | Revision 2 – approved 2026-10-27 with the decisions of section 0 (they override sections 4 – 13 where they differ); implemented (18.0.1.9.0) and tested on disposable databases – waiting for review before deployment. |
|---|---|
| Module | `warranty_management_mrf` only (one small hook on the case close, K-6, inside the bridge by inheritance); `material_purchase_requisitions`, Parts 1–4, AMC unchanged |
| Databases | development / regression on disposable databases; `warranty_management_18_4` untouched until approved |

## 0. Revision 2 – review decisions (2026-10-27)

| ID | Decision | Implementation |
|---|---|---|
| K-1 / K-7 | Approved with changes: **Reconciled** (computed: all quantities and returns resolved) vs **Closed** (formal, Closed By / On). Historical requests computed *Closed* (e.g. MRF/000005) become **Reconciled** – never open / incomplete, no invented closer or date. Batch closure from job / case validates each request and asks for confirmation. | Status value *Reconciled* + final *Closed*; upgrade recomputes the status only; batch wizard lists every request with its result and closes only the selected eligible ones after re-validation. |
| K-2 | Modified: no invoice requirement by default. Operational completion (approval, release rules, delivery, usage / installation / resolution, returns, stock moves, purchases) separate from financial completion: **Customer Invoicing** status (No Customer Billing / Pending Invoicing / Invoiced, posted invoices net of credit notes) shown separately. Optional company policy **Require Customer Invoice to Close**. No invoice created or posted by closure. | `warranty_mrf_close_requires_invoice` (default off). |
| K-3 | Approved: claims, draft credit notes and unsettled recoveries never block MRF, job or case closure; claims / recovery continue after closure. | – |
| K-4 | Approved with exceptions: closed requests refuse issues / fulfilment, usage, returns, reversals, coverage changes, operational cancellation / Cancel Remaining, quotations / declines / release exceptions, header and line edits, new stock / purchase links. Allowed: vendor claims, recovery, accounting reconciliation (invoices, credit notes, payments), audit, reporting. Stock / accounting documents outside the request are not frozen. Corrections via Reopen. | Guards in the existing entry points (material open check, coverage, fulfilment, quotation, release guard, write guards). |
| K-5 | Approved: Requisition Managers reopen with a reason, never the person who closed it; **administrator exception** (Settings users) with mandatory reason, logged as such. | Reopen wizard; closed / reopened by, date, reason, exception flag tracked. |
| K-6 | Modified: a warranty case cannot be set to *Closed* while a linked request (not cancelled) is not formally closed; the error lists the requests with open obligations and those ready to close; **Close Material Requests** on the case (and job) closes the selected eligible requests after validation and confirmation. No automatic closure. Job completion rules unchanged. Note: Part 3 has no Close action for cases today; the guard applies to every path that sets the state. | Bridge `write` hook on `warranty.case`. |
| K-8 | **Deferred** as a separate controlled inventory enhancement (manager approval, quantity / source stock validation, reason / audit, standard stock move, cost classification, no duplicate consumption / recovery). Until then lost / damaged parts keep the request un-reconciled (no manual status bypass). | Documented only. |
| Report B | Modified: explicit recovery allocation per **claim line**. Credit note allocations now carry the claim line (draft credit notes created from a claim: one allocation per line; manual allocation: the user selects the line). Existing claim-level allocations of single-line claims are assigned to that line by the upgrade; other claim-level allocations stay visible as *Unassigned (claim level)* rows – never distributed proportionally. | `claim_line_id` on allocations; report B rows per claim line + unassigned rows. |
| Audit | Approved: tracking of MRF header state / approval / cost / coverage / responsible / closure / reopen fields; audit trail view reuses chatter, tracking, approvals, usage records, stock moves, allocations and credit-note tracking. | `warranty.mrf.audit.event` SQL view. |
| Menus | Approved: Warranty → Reports (A, B, C, D) and Invoicing / Accounting → Reporting shortcuts (A, B, D) using the same actions and access rules. | – |

## 1. Sources reviewed

* SRS §2.10 (MRF stages … Issued, Returned, **Closed**; "Unused parts are returned and actual consumption
  is reconciled"; estimated vs approved vs actual reportable; recovery status on the case), §2.13 /
  §2.14 row 34 (immutable card / unit / service / job / **material / accounting** history), §6 menus
  (Warranty Management → Material Requests "… reimbursement and actual-cost status", Vendor Claims,
  **Reports**, Warranty History), §9.13 MRF stages, §11.1 step 8 ("Case is closed and cost/reporting
  updated"), **§13** validations (batch completion: "no open MRF/repair blockers"; material cost
  approval), **§14** triggers ("Service job completed → consume entitlement and update cost", "Warranty
  cost incurred → update warranty cost/provision reports", "Material request cost exceeds threshold"),
  **§15** reports (Warranty Cost, Vendor Claim Recovery, **Material Approval and Cost**, Warranty
  History …), **§16** roles and audit trail ("All critical actions should be posted to chatter … and
  closure"; "Critical before/after values should be stored"), §17 accounting.
* Mapping §5.9 (Close MRF, tracked fields, history notes on case / job / card – D17, reports, T9.1 –
  T9.5, M9.1 – M9.3), D16 (completion blocker), D17 (central Warranty History model = **Part 9**).
* Implementation 5.1 – 5.8 (18.0.1.8.1 in development, 18.0.1.8.0 on `warranty_management_18_4`).

## 2. Existing functionality vs missing

| Area | Existing (keep) | Missing for 5.9 |
|---|---|---|
| MRF status | Computed *Warranty MRF Status* incl. **Returned / Closed** (5.6): Closed = no material problem (approved, issued, used / returned / cancelled, customer-paid quoted / confirmed / paid / delivered / installed or resolved) and no open return transfer. Vendor *Received* (F-5: only when fully issued). | Closed is only a computed state: no closing user / date, no freeze (a case-only request can still be reversed later), no reopen control, no check of pending stock moves of the request (issue / receipt), RFQs or the customer invoice. |
| Job completion | `_warranty_completion_blockers` (5.6 E-13) blocks Complete Visit / Batch Complete for open material items; Incomplete / Reschedule never blocked; vendor claims never block. | Nothing (keep). |
| Case closure | Part 3 / 4 case states Completed / Closed; no material check. | SRS §11.1 / §2.10: material reconciliation before the case is closed (K-6). |
| Audit | Chatter notes on request, case, job for every material / approval / claim event; approval history `warranty.mrf.approval` (round, level, user, date, reason, amounts); usage records (user, date, note, reversal user / date / reason, moves); claim tracking (state, partner, amounts, references, approvers) + allocations (user, date, removal reason); stock moves / valuation layers (date, user); credit notes (standard chatter / tracking). | One chronological view across these sources; before / after values for MRF header fields (only links are tracked); explicit close / reopen events; claim-side record of credit-note posting / cancellation (only on the credit note today). |
| Reports | 5.7 *Warranty Material Cost* (line level, buckets, estimated / approved / actual / variance / billed); Vendor Claims list / pivot (5.8). Parts 1–4: **no** report views (lists only). | §15 *Material Approval and Cost Report*, *Vendor Claim Recovery Report*, material part of *Warranty History Report*; recovery columns in the cost report. |
| Other §15 reports | – | Not MRF-bridge scope: Warranty Dashboard, Active / Expiring, Free Service Due, Failure Pattern, Repeated Failure, Replacement, Chargeable Service Revenue, Provision / Reserve Utilization, Draft Warranty Review, Unit Warranty Number, Service Merge / Job Planning, Helpdesk Pending Service, Repair / Backup, AMC Visit (owners in §9). |

## 3. Functional workflow

```
Material events (5.1 – 5.6)          -> computed status Returned / Closed (unchanged)
Close Material Request (new, K-1)    -> checks K-2 / K-3 -> Closed (Final): user, date, frozen (K-4)
  exceptional Reopen (K-5)           -> Requisition Manager + reason -> back to computed status
Service Job completion (unchanged)   -> 5.6 blockers only; open vendor claims never block
Warranty Case close (K-6)            -> refused while a linked request has unresolved material items
Vendor claims (5.8, independent)     -> recovery / settlement continue after MRF / job / case closure
Reports & audit (new, read-only)     -> Material Approval and Cost, Vendor Claim Recovery,
                                        Material Audit Trail, Warranty Material Cost (+ recovery)
```

## 4. Closure validation – decision table

| ID | Topic | Recommended (safest) option | Alternatives | SRS |
|---|---|---|---|---|
| **K-1** | Closing an MRF | New explicit **Close Material Request** (request form, and *Close Completed Requests* on the job / case for all closable ones) by Service Coordinators, Store or Requisition users. Records Closed By / On, posts a note on request, case, job. The computed *Closed* status stays as "ready to close" (renamed **Reconciled**, see K-7). | Automatic final close when the computed status becomes Closed | §2.10, §9.13, §16 closure in chatter, mapping 5.9 |
| **K-2** | Close checks (all must pass) | (a) 5.6 `_warranty_material_problems()` empty (approved, issued, consumed / returned / cancelled, customer-paid resolved); (b) no open return transfer (status Reconciled, not Returned); (c) no stock move linked to the request **not done / cancelled** (issue pickings, backorders, purchase receipts, quotation deliveries / returns); (d) no RFQ / PO of the request in draft / sent / to approve, and no confirmed PO line with qty not received (unless cancelled); (e) customer-paid lines: their quotation lines **fully invoiced with posted invoices** (net of credit notes) or declined – payment is *not* required (receivable is Accounting's); (f) no pending approval round, coverage decision or release exception. Each failure is listed with the document. | (e) require payment; (e) not required | §2.10 b5 / b6, §13, mapping 5.9 "quotations settled" |
| **K-3** | Vendor claims and recovery | **Never block** closure of MRF, job or case (open, sent, answered claims, draft credit notes, unsettled recoveries). Claims stay creatable after closure (they only read the closed request). | Block while a claim is open | user requirement |
| **K-4** | Freeze after closure | A closed request refuses: usage / install / keep / return / reversal / cancel-remaining, coverage decisions, Create Picking / PO, quotation creation, line or header changes (server side, also superuser workflow entry points). Accounting / stock documents themselves are not locked. | No freeze | §2.13 immutability |
| **K-5** | Exceptional reopen | **Reopen Material Request**: Requisition Managers only, reason required, not the person who closed it; logged (who, when, reason) on request, case, job; back to the computed status; re-closing follows K-2. Not possible while the job is completed **and** the reopen would add new issues (only corrections). | No reopen; any coordinator | §16 audit |
| **K-6** | Warranty case close (Part 3 state *Closed*) | Bridge hook: refuse closing a case while any of its warranty requests has unresolved material items (K-2 a–d); requests only *Reconciled* (not formally closed) are closed automatically with the case close (logged). Vendor claims never block. | Warning only; no hook | §11.1 step 8, §2.10 |
| **K-7** | Status names | Computed status *Closed* (5.6) renamed **Reconciled**; new final status **Closed** set by K-1. Existing data: requests currently computed *Closed* become *Reconciled* (no data loss). | Keep name *Closed* for both | §9.13 |
| **K-8** | Lost / damaged parts (issued, neither used nor returned) | Controlled exception **Record Lost / Damaged** (Store users, reason): scrap move technician location → company scrap location (standard valuation layer), usage kind *Lost / Damaged*; reported separately (not warranty material cost, not claimable). Otherwise such a request can never close. | Defer (request stays open; manual stock adjustment) | §2.10 b6 reconciliation |
| **K-9** | Pre-matrix (legacy) requests | Same Close / checks (5.6 legacy rules); approved cost stays *Not Recorded (Legacy)*. | – | – |

## 5. Audit design

**Principle:** reuse the existing records; add only what is missing; no copy of data.

| Event | Existing source (user, date, before / after, reason, document) | 5.9 addition |
|---|---|---|
| MRF created / modified | chatter (create note); links tracked | `tracking=True` on header fields (state via bridge status, warranty MRF status, approval status, total estimated, approved amount, locations, closed by / on) → before / after in tracking values |
| Approval submitted / approved / rejected / withdrawn / reset | `warranty.mrf.approval` (round, level, user, date, reason, amounts) + notes | – |
| Coverage decision | line fields decided by / date / reason + notes | – |
| Picking / issue / receipt | stock moves (create user, date done, qty, from / to), notes | – |
| Consumption / unused return / reversal / cancel remaining | `warranty.mrf.consumption` (user, date, note, moves, reversed by / date / reason) | – |
| Estimated / approved / actual cost | estimated (tracked header total), approved snapshot (5.7, recorded at approval), actual = valuation layers (date, value, move) | header tracking; actual-cost events come from the layers in the audit view |
| Vendor claim lifecycle / corrections / responses | claim tracking + notes, response user / date, Finance correction reason | – |
| Credit note created / posted / cancelled / settled | allocation (user, date, removal reason) + credit note chatter | audit view reads the credit note state changes (tracking of `state` / `payment_state` on account.move is standard) |
| MRF close / reopen | – | K-1 / K-5 fields + notes + tracking |

**Material Audit Trail** (`warranty.mrf.audit.event`, read-only SQL view, UNION of the sources
above): date, event type (Request, Approval, Coverage, Stock, Usage, Cost, Claim, Recovery, Closure),
event (e.g. "Approved – Finance", "Used", "Reversed", "Credit note posted"), company, warranty case,
service job, material request, claim, product, user, old value, new value, amount, reason / note,
source document (model + id + display name) with an **Open Document** button. Filters: case, job,
request, claim, event type, user, date; group by case / request / type. This is the material part of
the §15 *Warranty History Report*; the central history over cards / units / services (§2.15) is
Part 9 (D17) and can include this view.

## 6. Reports (Warranty → Reports)

| Report | Grain / source | Columns (sample) | Notes |
|---|---|---|---|
| **A. Material Approval and Cost** (new, §15) | one row per **warranty request** (SQL view over request + stored line costs) | Request, case, job, customer, company, request date, warranty MRF status, approval status, approval mode / round, submitted by / on, approvers (Manager / Finance / GM), approved by / on, routing amount, approved amount; estimated, approved (net), actual verified, actual unverified, per bucket Covered / Goodwill / Customer Paid; customer invoiced / credited / billed; qty requested / issued / used / returned / cancelled / lost; vendor claimed / accepted / recovered / settled / outstanding (claims of the request's lines); closed by / on | Filters: MRF stage, approver, job, coverage (has goodwill / customer-paid lines), amount ranges, unverified, not recorded, open recovery. List / pivot / graph / export. |
| **B. Vendor Claim Recovery** (new, §15) | one row per **claim line** (SQL view over claim lines + claim) | Claim, state, vendor result, recovery status, vendor / manufacturer, claim type, case, job, request, product, serials, sent / response dates, claimed, accepted, not accepted, recovered, settled, outstanding, written off, goodwill, over-claimed | Claim-level recovered / settled / written-off allocated to lines in proportion to the accepted amount (exact sum per claim; rounding difference on the last line). Draft credit notes never count; settled ≠ recovered. Filters: vendor, claim status, recovery status, amount, period. |
| **C. Material Audit Trail** (new, §15 Warranty History – material part) | one row per event (section 5) | as section 5 | Open Document button; chronological list; export. |
| **D. Warranty Material Cost** (5.7, kept) | one row per request line (unchanged) | + Vendor Claimed qty / amount, Accepted, Recovered, Net Warranty Cost after Recovery (line share, same allocation as B) | No change of 5.7 calculations. |

*No double counting:* every report has one grain; header totals are sums of lines; claim amounts
are allocated, not repeated per request / job / case; job / case figures on forms keep the 5.7 / 5.8
rules (case = all its requests, job = its requests; a claim counted once per case).

## 7. Accounting accuracy

Manual valuation kept; closure, reopen and reports create **no journal entry**; K-8 lost parts create
a standard scrap move (valuation layer, no journal entry with manual valuation); recovered = posted,
not reversed, allocated credit notes only (5.8); settled separate; company currency (layers, journal
item balances); multi-company record rules on every report; 5.7 costs unchanged.

## 8. Technical design

* `material.purchase.requisition`: `warranty_closed` (bool), `warranty_closed_by_id`, `warranty_closed_date`,
  `warranty_reopen_reason` (last), status selection: *Reconciled* (computed) + *Closed* (final); methods
  `_warranty_close_problems()`, `action_warranty_close()`, `action_warranty_reopen()` (wizard with reason);
  freeze guard in the existing material / coverage / fulfilment / sale entry points (`_warranty_check_material_open` and the 5.3 write guard); tracking on header fields.
* `warranty.service.job` / `warranty.case`: *Close Completed Requests* button; case close hook (K-6).
* `warranty.mrf.consumption`: kind *Lost / Damaged* (K-8) + wizard.
* New SQL views: `warranty.mrf.approval.cost.report` (A), `warranty.vendor.claim.recovery.report` (B),
  `warranty.mrf.audit.event` (C); extra columns on `warranty.mrf.cost.report` (D).
* Menus: **Warranty → Reports** → Material Approval and Cost, Warranty Material Cost, Vendor Claim
  Recovery, Material Audit Trail; accounting shortcut Invoicing → Reporting (A, B, D).
* Access: reports and audit view = cost groups (Helpdesk, Requisition, Accounting Billing /
  Read-only); company rules; technicians / plain users none; Close = Coordinators / Store /
  Requisition users; Reopen = Requisition Managers; Lost / Damaged = Inventory + Requisition users.

## 9. Ownership of other §15 reports (not in the bridge)

| Report | Owner |
|---|---|
| Warranty Dashboard, Active / Expiring, Draft Warranty Review, Unit Warranty Number | Part 1 / 2 (`warranty_management`) |
| Free Service Due, Service Merge / Job Planning, Helpdesk Pending Service | Parts 2 – 4 (`warranty_management_helpdesk` / `_fsm`) |
| Warranty Cost Report (labour / travel / provision), Provision / Reserve Utilization | Part 8 (accounting) – material part = report D |
| Failure Pattern, Repeated Failure Escalation | Part 3 / 9 (failure data on cases) |
| Replacement Report | Replacement Part |
| Repair and Backup Unit Report | Part 6 |
| Chargeable Service Revenue | Part 3 / 4 (inspection / chargeable jobs) + Part 5 billed amounts |
| AMC Visit Schedule | AMC module |
| Warranty History Report (complete) | Part 9 (D17); report C is its material / claim part |

## 10. Automated tests (planned)

T9.1 close refused for each K-2 item (material problem, open return, open move, open RFQ / PO line,
customer-paid not invoiced, pending approval) with clear messages; T9.2 close succeeds, logged, status
Closed, freeze of every material / coverage / fulfilment / quotation action (also API); T9.3 open
vendor claim / draft credit note do not block MRF, job or case closure; claim creatable after close;
T9.4 reopen: Requisition Manager only, reason, not the closer, logged; T9.5 case close hook K-6 and
automatic close of reconciled requests; T9.6 Lost / Damaged (scrap move, layer, no journal entry,
not warranty cost, not claimable); T9.7 report A totals = form totals, per-bucket values, approval
data; T9.8 report B allocation sums = claim figures, draft credit note not recovered, settled ≠
recovered, cancelled credit note excluded; T9.9 report D recovery columns, no double count across
request / job / case; T9.10 audit trail contains every event type with user, date, old / new values,
reason and opens the source document; T9.11 access (technician / plain user refused, accountant
reads, company isolation); T9.12 end-to-end scenario (mixed request, partial stock + purchase,
quotation, consumption, return, reversal, claim, credit note, close); full regression.

## 11. Manual UAT (on `warranty_management_18_4` after an approved upgrade)

| ID | Steps with your records | Expected |
|---|---|---|
| UAT-901 | MRF/000005 (status today Closed → shown **Reconciled**) → *Close Material Request* | Refused while S00041 (Gas R410A, customer-paid) is not invoiced (K-2 e); message names S00041. |
| UAT-902 | Invoice S00041 (Sales) and post → Close MRF/000005 | Closed, Closed By / On, notes on WCAS/000003 and JOB/000003; VCL/00001 (draft credit note) does not block. |
| UAT-903 | On closed MRF/000005: try Record Used Parts / Return / Reverse / Cancel Remaining | All refused ("closed"). |
| UAT-904 | Reopen MRF/000005 as admin (Requisition Manager) without / with reason; close again | Reason required; logged; closes again. |
| UAT-905 | VCL/00001 after closure: post the draft credit note (optional), register payment (optional) | Recovered / Settled update; MRF stays Closed. |
| UAT-906 | Warranty → Reports → **Material Approval and Cost**: filter WCAS/000003 | MRF/000004 and /000005 rows: estimated 0.50 / 9,000, approved, actual 0 / 1,900 (+4,000 customer paid), approval data, claimed 1,200 / accepted 1,200 / recovered 0 (draft). |
| UAT-907 | **Vendor Claim Recovery**: VCL/00001 | Claimed 1,200, Accepted 1,200, Not accepted 0, Recovered 0 (draft credit note), Settled 0, Outstanding 1,200 (after posting: recovered 1,200). |
| UAT-908 | **Material Audit Trail**: filter MRF/000005 | Chronological creation, approval, issue, usage, returns, quotation / delivery, cost, claim, response, credit note, close / reopen events with user, date, before / after, reason; Open Document works. |
| UAT-909 | **Warranty Material Cost**: recovery columns for MRF/000005 Relay line | Claimed 1,200, Recovered 0 (1,200 after posting), Net after Recovery 1,200 → 0. |
| UAT-910 | WCAS/000003 close (if the case flow allows) with a non-reconciled request on another case for comparison | Refused only for unresolved material items, never for VCL/00001. |
| UAT-911 | Technician-only user / Billing user | Technician: no reports; Billing: A, B, D readable, no write. |

## 12. Tracked items (not part of 5.9, status as of 2026-10-27)

| Item | Status |
|---|---|
| 5.8 serial / lot selection fix (18.0.1.8.1) | Developed and tested (5.8 10/10, bridge 93/93, FSM 132/132, part 1 227 with 1 known error); verified on `wm18_4_581_check`; **not deployed** – awaiting your approval. Includes the Return Unused (serial, technician) access fix. |
| Part 3 `test_13_serial_rules` | **Open** – pre-existing Part 3 error (serial name read without Inventory rights, `warranty_case.py:885`); fix needs approval of a Part 3 change. Not counted as passed. |
| 5.8 manual tests posting / settlement / close / rejection / over-claim (TC 810 – 815) | **Open** – your testing stopped at the draft credit note of VCL/00001. |
| Part 4 "visit attachments optional" | Paused (company setting *Worksheet Attachment Required*). |
| Technicians still see 5.1 estimated / 5.3 approval amounts on requests | Open decision. |

## 13. Open business decisions

1. **K-1 / K-7** – explicit *Close Material Request* with the computed status renamed *Reconciled*?
2. **K-2 (e)** – customer-paid lines: posted invoice required to close (payment not required)?
3. **K-3** – vendor claims / recoveries never block closure (confirmed by you – recorded)?
4. **K-4** – freeze closed requests completely (all material, coverage, fulfilment, quotation actions)?
5. **K-5** – reopen by Requisition Managers only, with reason, not by the closer?
6. **K-6** – case close refused for unresolved material items, reconciled requests closed with the case?
7. **K-8** – include *Record Lost / Damaged* (scrap) now, or defer?
8. **Report B** – proportional allocation of claim recovered / settled / written-off to claim lines?
9. **Audit** – add field tracking on MRF header fields (before / after values) as listed?
10. Reports also under Invoicing → Reporting for accountants?
