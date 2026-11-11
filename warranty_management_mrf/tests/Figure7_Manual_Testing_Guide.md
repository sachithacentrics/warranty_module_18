# SRS Figure 7: Material Request, Approval, Stock Issue, Cost, Invoice and Reimbursement (manual UAT guide)

| Item | Value |
|---|---|
| Updated | 2026-11-07, after the non-accounting Figure 7 changes (D1 to D5, D9), the accounting integration with standard Odoo (accounting 18.0.1.8.0) and the change request **Create Parts Quotation after full approval** (MRF/000013, D2a); **Check Approval Route** button hidden (Submit still validates the route) |
| Code versions | mrf **18.0.1.10.4**, repair **18.0.1.7.2**, accounting **18.0.1.8.0**. UAT (`warranty_management_18_4`) runs mrf 18.0.1.10.2 (read 2026-11-07). 18.0.1.10.3 fixes the Picking Details onchange error on approved requests ("'<' not supported between instances of 'NewId'", MRF/000013); it needs a server restart before resuming at TC-F7-09 / Picking Details |
| Other versions on UAT | fsm 18.0.1.4.4, helpdesk 18.0.1.2.4, core 18.0.1.2.3, mrp 18.0.1.0.3, vendor `material_purchase_requisitions` 18.0.11.9.12 |
| SRS | Figure 7 (page 31), 2.10, 9.8, 9.13, 10.7, 14 to 17, 16.1 |
| Decision records | `doc/figure7_workflow_decisions.md` (D1 to D5, D9); accounting: `warranty_management_accounting/doc/figure7_accounting_integration.md` (standard Odoo mapping, journal-entry examples, migration); `part5_*`, `part8_1`, `part8_6`, `part8_7` |

Fill **Actual** and **Status** (PASS / FAIL / BLOCKED) only from what you see in UAT. A scenario is PASS only after its final stock, accounting and closure checks are done.

**Accounting (N9):** covered spare parts use standard Odoo stock accounting (manual valuation on UAT: no journal entry at issue or use, actual cost on the case); provision and reserve utilization are standard journal entries controlled by Finance; Not Covered parts use customer invoices; vendor recovery uses vendor credit notes. Scenarios A to E are unchanged. Scenario F checks the integration without repeating them.

---

## 1. Figure 7 nodes, arrows and decisions

| # | Diagram element | Outgoing arrow(s) |
|---|---|---|
| N1 | Helpdesk / Job / Repair Order identifies spare parts | → N2 |
| N2 | Create separate Material Request (MRF) | → N3 |
| N3 | Classify each line: Covered / Not Covered / Pending Decision | **Not Covered** → N5; other lines → N4 |
| N4 | Estimated material, labour, subcontract and other cost | → D1 |
| N5 | Customer quotation for Not Covered lines; confirmation / payment requirement | → N7, **bypasses D1 and D2** |
| D1 | Approval required by amount, coverage, category or goodwill rule? | **Yes** → N6; **No** → D2 |
| N6 | Service Manager / Finance / GM approval | → D2 |
| D2 | Stock available? | **Yes** → N7; **No / Awaiting Stock** → back to the MRF (loop) |
| N7 | Serial / lot-aware stock issue and actual cost | → N8 |
| N8 | Return unused parts and reconcile quantities | → N9 |
| N9 | Warranty expense / provision; invoice non-covered parts; reimbursement claim | end |

Also required by the SRS text:
- Rejection (9.13, 10.7).
- Awaiting Parts on the job (9.8 step 6).
- The lifecycle (9.13).
- Estimated vs approved vs actual (2.10, 15).
- The audit trail (16).

## 2. Traceability matrix

Status:
- **Implemented**: built and covered by automated tests.
- **Partial**: built with a documented limit.
- **Pending**: waits for a decision.

| Node | Model / method | Screen / button | Prerequisite | State change | Stock / accounting impact | Status | Automated test | UAT |
|---|---|---|---|---|---|---|---|---|
| N1 case / job / visit | `action_create_material_request` (case, job, visit) | **Create Material Request**, **Link Material Request** | Requester employee **with a department** (on UAT only `admin`, `demo`) | – | none | Implemented | `test_mrf_create_link` | TC-F7-01 |
| N1 Repair Order | `repair.order.action_warranty_create_material_request`; create keeps that RO; auto-link only with one open RO | Repair Order > **Create Material Request**; RO tab Material Requests; MRF field Repair Order | Warranty RO not done / cancelled, machine not returned | – | none | Implemented | repair `test_figure7_repair_mrf` | TC-F7-40 |
| N2 | vendor requisition, `MRF/` sequence | Warranty > Material Requests | Settings: Source, Technician Location, Internal Transfers | Draft | none | Implemented | `test_mrf_foundation` | TC-F7-01, 02 |
| N3 | `_warranty_default_coverage`, Request / **Decide Coverage** | Lines: Coverage Type; header Coverage (Mixed) | Policy items; reviewers = Warranty Case Approval Users | Pending / Covered / Not Covered | none | Implemented; Pending blocks Submit | `test_mrf_coverage`, `test_mrf_figure7` 10 | TC-F7-03, 20, 50 |
| N4 material | `routing_cost` = max(estimated, product cost) | Material Cost tab | Product cost | – | none | Implemented | `test_mrf_cost` | TC-F7-04 |
| N4 labour / subcontract / other | `warranty.cost.line` (Part 8.1, own approval); **Case Cost Breakdown** tab; Expected Cost Approval Gate | Case > Cost Lines; MRF > **Case Cost Breakdown** | Cost approvers; gate off by default | Draft → Approved | none | Implemented (separate approval by design D5) | accounting `test_figure7_cost`, `test_warranty_cost_lines` | TC-F7-05, 05b, 05c |
| N5 | `_warranty_quotation_error` (new quotations), `_warranty_chargeable_request_error` (release), `action_create_parts_quotation`, release trigger, Customer Declined, release exception, delivery guard, Release Blocked | MRF > **Create Parts Quotation**, **Customer Declined**, **Approve Release Exception** | Release trigger; exception users | Line: To Quote → Waiting Customer → Waiting Payment → Released / Released (Exception) / **Release Blocked** / Declined | Quotation delivery only; standard invoice | Implemented: quotation **only after every required approval level** (change request 2026-11-07, D2a; the diagram branches before approval) | `test_mrf_quotation`, `test_mrf_figure7` 06–10, 13, 14 | TC-F7-06b, 08c2, 08f–i, 50–56, E, CR1–CR7 |
| D1 | `_warranty_route_analysis` (no rule = No Approval Required; strictest; goodwill Finance + GM), rule **Amount Basis** | **Confirm / Submit** (Check Approval Route hidden); Approval Status | Material Approval Rules (you configure, section 4) | → Manager Approval / Finance/GM Approval, or **Approved - No Approval Required** | none | Implemented | `test_mrf_approval`, `test_mrf_figure7` 01–04 | TC-F7-06, 21, 41, 51, E1 |
| N6 | Approve / Reject / Withdraw / Reset to New; rounds | **Approve**, **Reject**, **Withdraw** | Named approvers | → Approved / Rejected; new round | none | Implemented | `test_mrf_approval`, `test_mrf_figure7` 03, 05 | TC-F7-07–08, 22–25 |
| D2 | `warranty_stock_status`, line `availability`, **Awaiting Stock** reason | MRF header **Stock Status**; line *Awaiting Stock*; filter Awaiting Stock | Source location stock | Ready to Issue / Partially Available / Awaiting Stock / Issued | none | Implemented | `test_mrf_figure7` 11 | TC-F7-09, 26 |
| D2 No loop | `_warranty_fulfil` (non-blocking), `_warranty_await_stock` (note, To-Do, notification), **Recheck Stock / Issue Remaining**; **Put Job on Awaiting Parts** | MRF buttons; Job Material Status *Awaiting Stock* | Vendor on line / product, or none | Same MRF | RFQ when a vendor exists; nothing otherwise | Implemented | `test_mrf_figure7` 11, 12; `test_mrf_fulfilment` | TC-F7-13, 26–29 |
| N7 | `_warranty_create_issue_picking`, transfer validation (no over-issue, requested serial / lot) | Create Picking and PO / Recheck Stock; transfer Validate | Internal Transfers | Partially Issued / Issued | Internal move, no valuation change | Implemented | `test_mrf_fulfilment`, `test_mrf_figure7` 11 | TC-F7-10–13, 27 |
| N7 actual cost | valuation layers of consumption | Material Cost tab; Case Cost Breakdown | Standard / Manual valuation on UAT | – | valuation layer, **no journal entry** | Implemented | `test_mrf_cost` | TC-F7-15 |
| N8 | `warranty.mrf.consumption` (Used / Installed / Customer Keeps / Return Unused / Cancel Remaining / Reverse) | **Confirm Material Usage**, **Return Unused**, … | Warranty Consumption location | To Reconcile → Return Pending → Reconciled | consumption / return transfers | Implemented | `test_mrf_consumption` | TC-F7-14, 16 |
| N8 close | Close / reopen; case guard | **Close Material Request** | Require Customer Invoice to Close (on) | → Closed | none | Implemented | `test_mrf_closure` | TC-F7-19 |
| N9 expense / provision | provision on warranty sales (8.6); covered parts: standard stock accounting (`stock.valuation.layer`, Odoo stock entry with automated valuation on the Warranty Consumption location accounts); `warranty_reserve_utilization.py`: Finance reserve utilization | Settings > Warranty Accounting > Warranty Reserve Utilization; Accounting > Accounting > Warranty > Warranty Reserve Utilization; case > **Warranty Accounting** > Create Reserve Utilization Draft | Journal and accounts (8.3); Bookkeeper to post | Draft → Posted by Finance | standard stock entry (automated only); draft Dr 216100 / Cr 625100 | Implemented (18.0.1.8.0) | `test_warranty_provision_entry`, `test_figure7_accounting` | TC-F7-17, TC-F7-AC1–AC8 |
| N9 invoice | standard invoice of the parts quotation | Quotation > Create Invoice | Sales / Invoicing rights | Invoiced | customer invoice; no provision on parts | Implemented | `test_mrf_quotation`, `test_mrf_closure` | TC-F7-18, 53 |
| N9 reimbursement | `warranty.vendor.claim`, draft credit note | **Create Vendor Claim**, Warranty > Vendor Claims | Claims on; approvers; Recovery 450100 | Draft → … → Closed | draft vendor credit note (never posted by the claim) | Implemented | `test_vendor_claim` | TC-F7-60–64 |
| Audit / reports | audit events, reports | Warranty > Reports | – | – | – | Implemented | `test_mrf_closure` | TC-F7-70, 71 |

## 3. Gaps and limits

| # | Item | Status |
|---|---|---|
| G1 | Awaiting Stock loop | **Fixed** (D4): Stock Status, Awaiting Stock reason, non-blocking issue, To-Do, Recheck Stock / Issue Remaining, Put Job on Awaiting Parts. No new case status (approved) |
| G2 | Not Covered quotation before approval | **Changed** (D2a, 2026-11-07): quotation only after every required approval level, or right after submission when no approval is required. Differs from the diagram's branch order (approved business rule) |
| G3 | Warranty expense / provision for parts | **Pending**: Finance design A1 to A9, Phase 3 |
| G4 | Labour / subcontract / other in the approval | **By design** (D5): separate cost-line approval plus Expected Cost Approval Gate; read-only breakdown on the MRF |
| G5 | Create Material Request on the Repair Order | **Fixed** (D9) |
| G6 | Lost / damaged spare parts (K-8) | Deferred, not tested |
| G7 | UAT rules contradict SRS 16.1 | **You configure** the rules (section 4) before Scenario A |
| G8 | Release Exception Users empty | You add `approval` before Scenario D |
| G9 | Only `admin` / `demo` employees have a department | `admin` is the requester |
| G10 | No lot-tracked spare part | Use Cable Management Box FURN_5555 (lots CM-BOX-00001 = 50, CM-BOX-00002 = 40) |
| G11 | Fan Sensor 3 and DEMO Compressor 1 units without serial in WH/Stock | Pick FS-002 by hand on the transfer |
| G12 | Status names Picking / PO Created, Received, Reconciled | Accepted design |
| G13 | A Not Covered part delivered early (request still waiting approval): its usage is recorded after the request is approved | Documented limit (D2); no longer possible for new requests (D2a), historical quotations only |

## 4. Material Approval Rules: frontend configuration guide (you apply it)

**The amounts are UAT test values, not SRS amounts.** Rules affect only requests submitted afterwards; approved requests keep their approval round.

**Navigation:**
1. As `admin`: **Warranty > Configuration > Settings > Material Requests**. Check **Material Approval Matrix** is on, then click **Material Approval Rules**.
2. Or go to **Warranty > Configuration > Material Approval Rules**, then **New**.

**Fields:**

| Field | Meaning |
|---|---|
| Name | Free text |
| Company | The rule applies to this company and its branches |
| Minimum Amount | From, inclusive |
| Maximum Amount | Up to, exclusive; 0 = no upper limit |
| **Amount Basis** | *All Lines* (default) or *Covered Lines Only* (goodwill lines included). Each line counts at the higher of its estimated cost and its product cost |
| Coverage Condition | *Any*; *Covered Lines Present*; *Not Covered Lines Present*; *Only Not Covered Lines* |
| Goodwill Condition | *Any* or *Goodwill Lines Present* |
| Product Categories / Products | At least one line in them (child categories included) |
| Sequence | Display order only: the result never depends on it |
| **No Approval Required** | Explicit automatic approval |
| Manager Approval + Manager Approvers | |
| Finance Approval + Finance Approvers | |
| GM Approval + GM Approvers | |

**How rules combine:**
- All matching rules are combined (strictest).
- *No Approval Required* applies only when every matching rule is a No Approval rule.
- **No matching rule = No Approval Required.**
- Goodwill always needs Finance and GM approvers. Without them, Submit is refused with a configuration error.
- The parts quotation always waits for the final approval when any level is required (D2a, 2026-11-07). A rule with coverage condition *Not Covered Lines Present* or *Only Not Covered Lines* **and** approval levels additionally routes the request for approval because of its Not Covered lines.

**Approval sequence:**
- Manager first, then Finance and GM in any order.
- Each level needs a different person.
- The requester, creator and submitter never approve.
- Approvers must be internal users of the company.

**Statuses:**
- Submit → **Manager Approval** (if a Manager level is required), else **Finance/GM Approval**.
- After the last level → **Approved**; *Approval Status* = **Approved** (person).
- No level required → approved at Submit; *Approval Status* = **Approved - No Approval Required**.
- Reject (reason) → **Rejected**. The requester uses Reset to New, changes, and Submits: a new round; the history is kept.
- **Withdraw** (requester, while waiting) → New. A quotation the customer has not confirmed is cancelled.

**Recommended UAT rules** (all: Company = My Company (San Francisco), Goodwill Condition = Any unless stated):

| # | Name | Min | Max | Amount Basis | Coverage Condition | Approval |
|---|---|---|---|---|---|---|
| R1 | F7 Covered < 1,000 | 0 | 1,000 | Covered Lines Only | Covered Lines Present | **No Approval Required** |
| R2 | F7 Covered 1,000–3,000 | 1,000 | 3,000 | Covered Lines Only | Covered Lines Present | Manager: `approval` |
| R3 | F7 Covered ≥ 3,000 | 3,000 | 0 | Covered Lines Only | Covered Lines Present | Manager: `approval`; Finance: `main_tech` |
| R4 | F7 Goodwill | 0 | 0 | All Lines | Any; Goodwill Condition = **Goodwill Lines Present** | Finance: `main_tech`; GM: `support_tech` |
| – | TEST Low Value, rule 1 | | | | | **Archive** (Action > Archive). Used in history: archive, don't delete |

For Scenario E only, create and later archive:

| # | Name | Min | Max | Amount Basis | Coverage Condition | Approval |
|---|---|---|---|---|---|---|
| R5 | F7 Chargeable needs Manager | 0 | 0 | All Lines | **Not Covered Lines Present** | Manager: `approval` |

**Other combinations** (all supported by the same form; not needed for these scenarios):

| Combination | Tick |
|---|---|
| Service Manager only | Manager |
| Finance only | Finance |
| GM only | GM |
| Manager + Finance | Manager, Finance |
| Finance + GM | Finance, GM |
| Manager + Finance + GM | all three |

**Authorized and unauthorized users:**
- Authorized: the named approvers of the pending level (To-Do, Approve / Reject buttons).
- Unauthorized: `demo`, the requester `admin`, and approvers of a later level. They see no buttons and the server refuses.

**Other configuration:**
- **CFG-F7-02** (Scenario D only): Settings > Material Requests > *Chargeable Parts Release* = **On Payment**, and *Chargeable Release Exception Users* = `approval`. Restore *On Quotation Confirmation* after D.
- **CFG-F7-03 roles:**

| Role | User |
|---|---|
| Requester / store | `admin` |
| Coverage reviewer, Manager, claim approver | `approval` |
| Finance, technician | `main_tech` |
| GM | `support_tech` |
| Unauthorized | `demo` |

## 5. UAT test data (read from UAT, 2026-11-07; recheck the stock before each scenario)

| Need | Record |
|---|---|
| Card A (Policy 4) | ASD Customer, WC/00035 |
| Card B (DEMO policy, workshop) | Azure Interior, WC/00021 |
| Card C (Policy 4) | Abigail Peterson, WC/00003 |
| Card D (DEMO policy) | Acme Corporation, WC/00005 |
| Card E | Any card with no open case (e.g. WC/00005 after D is completed) |
| Policy 4 | Covered: Bolt, Fan Sensor, Compressor Relay. Excluded: Gas R410A |
| DEMO policy | Covered: DEMO Compressor, DEMO Fan Motor. Excluded: DEMO AC Gas |
| Fan Sensor | Serial, cost 700, claimable: FS-002, FS-003 (+3 without serial) |
| Compressor Relay | Cost 1,200, claimable, vendor Cool Parts Ltd: **1** in stock |
| DEMO Fan Motor | Cost 300, vendor Demo Parts Supplier: 2 in stock |
| Gas R410A | Price 4,000, cost 2,000: 7 in stock |
| DEMO AC Gas | Cost 100, vendor Demo Parts Supplier: **0** |
| Outdoor PCB (spare part) | 0, **no vendor** |
| Cable Management Box FURN_5555 | Lot, cost 70 |
| Locations | WH/Stock → WH/Technician Stock; Virtual Locations/Warranty Consumption |
| Valuation | Standard, Manual (periodic): no stock journal entries |
| Do not use | WCAS/000059, 000062, 000064–000068, BKU/*, WH/RO/00010–00018, WCAS/000004, WCAS/000001, MRF/000001–000012, VCL/00001, 00006, 00007 |

## 6. Scenarios and order

| Order | Scenario | Branches |
|---|---|---|
| 0 | Phase 6 UAT upgrade (only after your permission); configuration section 4 | – |
| 1 | **A**: mixed, Manager + Finance, early quotation, partial stock, serial, Field Service job | D1 Yes, N5 before approval, D2 partial / RFQ, serial, over-issue, return, invoice, claim, close |
| 2 | **C**: Pending, goodwill (Finance + GM), rejection, revalidation, no stock / no vendor, lot | Pending, D1 Yes (goodwill), Reject / resubmit, **Awaiting Stock**, Awaiting Parts hold, loop, lot |
| 3 | **B**: Repair Order, No Approval rule | N1 RO button, D1 No (rule), D2 Yes, full use |
| 4 | **D**: fully Not Covered, no matching rule, payment trigger | D1 No (no rule), N5 On Payment, decline, partial / full payment |
| 5 | **E**: Manager only, withdraw, Release Blocked, explicit Not Covered rule | N6 Manager only, quotation cancelled on withdraw, confirmed order blocked after rejection |
| 5b | **F**: warranty accounting on standard Odoo (after the 18.0.1.8.0 upgrade) | settings, status, rights, no custom parts entry, utilization refusal / draft, menus, vendor credit note |
| 6 | Final reconciliation and regression | – |

Use one fresh case per scenario.

---

## 7. Test cases

Menus:
- *Warranty > Material Requests*
- *Warranty > Configuration > Material Approval Rules*
- *Inventory > Operations > Transfers*
- *Purchase > Orders*
- *Sales > Orders > Quotations*
- *Invoicing > Customers > Invoices*
- *Warranty > Vendor Claims*
- *Warranty > Reports*

### Scenario A: mixed request, Manager + Finance (new case on WC/00035)

Prerequisite (Figures 3 / 4, already tested):
1. A ticket for ASD Customer, then a case on WC/00035: Eligible, approved by `approval`.
2. A service job: main technician `main_tech`, confirmed, visit open.

Record: case WCAS/____, job JOB/____.

| ID | SRS | Step (user) | Data / values | Expected | Actual | Status |
|---|---|---|---|---|---|---|
| TC-F7-01 | N1, N2 | `admin`: Job > **Create Material Request** > Save | – | New MRF, Draft; case, job, visit, customer filled; WH/Stock → WH/Technician Stock; note on case and job | | |
| TC-F7-02 | N2 | Add lines > Save | Fan Sensor 1 (Serial / Lot Numbers **FS-002**); Compressor Relay 2; Gas R410A 1 | Estimated 700 / 2,400 / 2,000; total 5,100 | | |
| TC-F7-03 | N3 | Coverage columns | – | Fan Sensor, Relay **Covered**; Gas **Not Covered**; header **Mixed** | | |
| TC-F7-04 | N4 | Material Cost tab | – | Estimated 5,100; Covered 3,100, Customer Paid 2,000 | | |
| TC-F7-05 | N4 | Case > Cost Lines > New: Labour, estimate 1,500 > Submit; approve as `approval`, then `main_tech` | Labour 1,500 | Approved after Manager + Finance; the MRF routing amount is unchanged (material only) | | |
| TC-F7-05b | N4 (D5) | MRF > **Case Cost Breakdown** | – | Row "This request": estimated 3,100 (warranty-borne); case rows Parts 3,100, Labour 1,500, total 4,600; variance column; Customer-paid note | | |
| TC-F7-06 | D1 | MRF header buttons (Draft) | – | **Check Approval Route** not shown (hidden 2026-11-07); the route is checked at Submit | | |
| TC-F7-07 | D1 Yes | **Confirm / Submit** | – | **Manager Approval**; Approval Status Submitted; To-Do for `approval`; approval history: R3 (Covered basis 3,100 ≥ 3,000), Manager `approval`, Finance `main_tech` | | |
| TC-F7-06b | N5 (D2a) | Header at Manager Approval | – | **Create Parts Quotation not shown**; Gas *To Quote*; no quotation | | |
| TC-F7-08a | N6 refusal | Open the MRF as `demo`, then as `admin` | – | No Approve / Reject | | |
| TC-F7-08b | N6 | `main_tech` tries to approve before the Manager | – | No button (Manager first) | | |
| TC-F7-08c | N6 | `approval` **Approve** | – | **Finance/GM Approval**; To-Do for `main_tech` | | |
| TC-F7-08c2 | N5 (D2a) | Header at Finance/GM Approval | – | **Create Parts Quotation still not shown** | | |
| TC-F7-08d | N6 | `main_tech` **Approve** | – | **Approved**; Approval Status **Approved**; Approved By `main_tech`; approved amount 5,100 | | |
| TC-F7-08f | N5 (D2a) | `admin` **Create Parts Quotation** (now shown) | – | Draft quotation, customer ASD Customer, 1 line Gas R410A 1; Gas *Waiting Customer* | | |
| TC-F7-08g | N5 duplicate | Create Parts Quotation again | – | Button hidden (no Not Covered line to quote) | | |
| TC-F7-08h | N5 | Quotation: Gas quantity 2 | – | Refused (product / quantity from the MRF) | | |
| TC-F7-08i | N5 | Quotation > **Confirm** | – | Gas **Released**; delivery WH/OUT created (do not validate yet) | | |
| TC-F7-08e | revalidation | `admin`: Relay quantity 3 | – | Refused (locked after submission) | | |
| TC-F7-09 | D2 | MRF header / lines | – | **Stock Status: Partially Available**; Fan Sensor Available; Relay Partially Available (free 1) | | |
| TC-F7-10 | N7, D2 partial | **Create Picking and PO** (`admin`) | – | Transfer: Fan Sensor 1, Relay 1 (**no Gas**); RFQ to Cool Parts Ltd: Relay 1; Relay *Awaiting Stock*: "Purchase P… open"; Stock Status **Awaiting Stock** | | |
| TC-F7-11 | N7 serial | Transfer: serial **FS-003** > Validate | – | Refused: only FS-002 | | |
| TC-F7-12 | N7 | FS-002, Relay 1 > Validate | – | Done; **Partially Issued** | | |
| TC-F7-13a | D2 loop | **Recheck Stock / Issue Remaining** | – | Refused: "Nothing to issue or purchase … open pickings or purchase orders" (no duplicate) | | |
| TC-F7-13b | D2 loop | Purchase: Confirm the RFQ, Receive 1 > Validate; MRF **Recheck Stock / Issue Remaining** | – | Second transfer Relay 1; no new RFQ | | |
| TC-F7-13c | over-issue | Second transfer quantity **2** > Validate | – | Refused: exceeds the approved quantity | | |
| TC-F7-13d | N7 | Quantity 1 > Validate; Sales delivery of Gas > Validate | – | MRF **Issued**; Stock Status **Issued**; Gas Issued 1 | | |
| TC-F7-14 | N8 | Job / Visit > **Confirm Material Usage**: Fan Sensor 1 (FS-002) Used; Relay 1 Used; Gas 1 Installed | – | Usage entries; Relay To Reconcile 1 | | |
| TC-F7-15 | N7 cost | Material Cost tab | – | Actual Fan Sensor 700, Relay 1,200 (verified); Customer-Paid 2,000 | | |
| TC-F7-16a | N8 | **Return Unused**: Relay 1; `admin` validates the return | – | Returned 1; **Reconciled** | | |
| TC-F7-16b | duplicate | Return Unused again | – | Refused | | |
| TC-F7-17 | N9 expense | Accounting > Journal Entries (today) | – | **No** warranty or stock journal entry from issue, usage or return (manual valuation: standard Odoo). Actual cost shown on the Material Cost tab | | |
| TC-F7-18 | N9 invoice | Quotation > Create Invoice > Confirm | – | Invoice 4,000 + tax posted; no provision entry for it; MRF Customer Invoicing **Invoiced** | | |
| TC-F7-60 | claim | **Create Vendor Claim**: Relay 1 | – | VCL Draft, Cool Parts Ltd, 1,200 | | |
| TC-F7-61 | claim limit | Claim quantity 2 | – | Refused | | |
| TC-F7-62 | claim approval | Submit (`admin`), `approval` Approve | 1,200 < 1,500 | Approved without Finance | | |
| TC-F7-63 | claim send | Mark Sent without attachment → refused; attach > Mark Sent > Accept All | – | Answered, 1,200 | | |
| TC-F7-64 | reimbursement | **Create Draft Credit Note** | – | Draft vendor credit note 1,200 on 450100, **not posted** | | |
| TC-F7-19 | N8 close | **Close Material Request** | – | Closed; notes on case and job | | |
| TC-F7-19b | freeze | Closed MRF: Return Unused / edit | – | Refused | | |

### Scenario C: Pending, goodwill, rejection, no stock (new case on WC/00003)

Prerequisite: a case on WC/00003, approved; service job confirmed; visit open.

| ID | SRS | Step | Data / values | Expected | Actual | Status |
|---|---|---|---|---|---|---|
| TC-F7-20a | N3 | Create Material Request; lines | DEMO AC Gas 2; Cable Management Box 2 (lot **CM-BOX-00001**); Outdoor PCB 1 | All **Pending** | | |
| TC-F7-20b | N3 | **Confirm / Submit** | – | Refused: pending lines listed (no quotation possible) | | |
| TC-F7-20c | N3 | **Request Coverage Decision** | – | To-Do for `approval` | | |
| TC-F7-20d | refusal | `admin` Decide Coverage | – | Refused | | |
| TC-F7-20e | N3 | `approval` Decide Coverage, two runs: (1) DEMO AC Gas → **Free of Charge** (goodwill); (2) Cable Box + Outdoor PCB → **Covered**; reason each | – | Covered; goodwill on DEMO AC Gas; logged | | |
| TC-F7-21 | D1 goodwill | Confirm / Submit; open the approval history | covered 340 | R1 (No Approval) + R4 → **Finance + GM** (strictest); **Finance/GM Approval** | | |
| TC-F7-22 | N6 reject | `support_tech` **Reject** with reason | – | **Rejected**; requester notified | | |
| TC-F7-23 | revalidation | `admin` Reset to New; DEMO AC Gas quantity 1; Submit | 240 | Round 2; round 1 kept | | |
| TC-F7-24 | N6 | `main_tech`, then `support_tech` Approve | – | **Approved** | | |
| TC-F7-25 | duplicate | `main_tech` Approve again | – | No button | | |
| TC-F7-26 | D2 No | **Create Picking and PO** | – | Transfer Cable Box 2 (lot); RFQ to Demo Parts Supplier: DEMO AC Gas 1; **warning "Awaiting Stock"** for Outdoor PCB; To-Do *Awaiting stock: MRF/…* for `admin`; Outdoor PCB *No stock and no vendor: waiting for stock*; Stock Status **Awaiting Stock** | | |
| TC-F7-26a | Awaiting Stock list | Material Requests > filter **Awaiting Stock** | – | This MRF listed | | |
| TC-F7-26b | Awaiting Parts | Start the visit (job In Progress); MRF **Put Job on Awaiting Parts**, reason | – | Job **Awaiting Parts**; Job Material Status **Awaiting Stock**; case status unchanged | | |
| TC-F7-26c | no duplicate | **Recheck Stock / Issue Remaining** again | – | Same warning; no new transfer, RFQ or To-Do | | |
| TC-F7-27 | D2 loop | Outdoor PCB line: Vendors = Demo Parts Supplier; **Recheck Stock / Issue Remaining** | – | RFQ to Demo Parts Supplier for Outdoor PCB 1 (a second RFQ, only for the new line); reason "Purchase … open" | | |
| TC-F7-27b | N7 lot | Validate the transfer with lot CM-BOX-00001 (try CM-BOX-00002 first) | – | CM-BOX-00002 refused; CM-BOX-00001 done; **Partially Issued** | | |
| TC-F7-28 | recheck | Recheck Stock / Issue Remaining | – | Refused: everything on open orders | | |
| TC-F7-29 | replenish | Confirm both RFQs (unit prices), receive both > Recheck Stock / Issue Remaining > validate; Job **Resume Job** | – | **Issued**; Stock Status Issued; job In Progress | | |
| TC-F7-29b | N8 | Usage: Cable Box 1 Used, DEMO AC Gas 1 Used, Outdoor PCB 1 Used; Return Unused Cable Box 1 > validate | – | Reconciled; Goodwill bucket DEMO AC Gas | | |
| TC-F7-29c | close | Close Material Request | – | Closed | | |

### Scenario B: Repair Order, No Approval rule (new workshop case on WC/00021)

Prerequisite (Figure 6): Service Mode Workshop; Repair Order created and machine received.

| ID | SRS | Step | Data / values | Expected | Actual | Status |
|---|---|---|---|---|---|---|
| TC-F7-40 | N1 RO (D9) | Repair Order > **Create Material Request** > DEMO Fan Motor 1 > Save | – | MRF field **Repair Order** = this RO; case / customer / product / serial of the case; RO tab Material Requests lists the line | | |
| TC-F7-41 | D1 No (rule) | Confirm / Submit | 300 | R1 → **Approved**; Approval Status **Approved - No Approval Required**; approval history "No Approval Required: F7 Covered < 1,000"; no To-Do | | |
| TC-F7-42 | D2 Yes | Stock Status **Ready to Issue**; Create Picking and PO > validate | – | One transfer, no RFQ; Issued | | |
| TC-F7-43 | N8 | Confirm Material Usage: all used | – | Reconciled | | |
| TC-F7-44 | close | Close Material Request | – | Closed; RO unchanged | | |

### Scenario D: fully Not Covered, no matching rule, On Payment (new case on WC/00005)

Prerequisite: CFG-F7-02 applied; a case on WC/00005 approved.

| ID | SRS | Step | Data / values | Expected | Actual | Status |
|---|---|---|---|---|---|---|
| TC-F7-50 | N3 | Create Material Request: DEMO AC Gas 1; Gas R410A 1 | – | DEMO AC Gas Not Covered; Gas R410A Pending → `approval` decides **Not Covered** | | |
| TC-F7-51 | D1 No (no rule) | Confirm / Submit | – | **Approved - No Approval Required**; **Create Parts Quotation shown right away** (D2a); history reason "no material approval rule matches" | | |
| TC-F7-51b | N5 only | Create Picking and PO | – | Refused: no Covered material to issue (Not Covered lines go through the quotation only) | | |
| TC-F7-52 | N5 | Create Parts Quotation | – | One quotation, 2 lines, trigger **On Payment** | | |
| TC-F7-52b | decline | **Customer Declined**: DEMO AC Gas, reason | – | Removed from the quotation; Customer Declined | | |
| TC-F7-53a | payment | Confirm; validate the delivery | – | **Waiting Payment**; delivery refused | | |
| TC-F7-53b | partial | Invoice, post; partial payment 1,000 | – | Still Waiting Payment | | |
| TC-F7-53c | paid | Pay the rest; validate the delivery | – | **Released**; Issued | | |
| TC-F7-54 | exception (fresh MRF, optional) | Before payment: `approval` **Approve Release Exception** with reason; `admin` refused | – | Released (Exception) | | |
| TC-F7-55 | N8 | Usage: Gas R410A Installed | – | Reconciled | | |
| TC-F7-56 | close | Close; restore CFG-F7-02 | – | Closed; Invoiced | | |

### Scenario E: Manager only, withdraw, rejected after confirmation, explicit Not Covered rule (new case)

Prerequisite: a case on a DEMO-policy card without an open case, approved.

| ID | SRS | Step | Data / values | Expected | Actual | Status |
|---|---|---|---|---|---|---|
| TC-F7-E1 | D1 Manager only | MRF: DEMO Fan Motor 4 (covered 1,200); DEMO AC Gas 1 (Not Covered); Submit | – | R2 → **Manager Approval** only (Finance / GM skipped) | | |
| TC-F7-E2 | N5 (D2a) | Header at Manager Approval | – | **Create Parts Quotation not shown**; no quotation | | |
| TC-F7-E3 | withdraw | `admin` **Withdraw** | – | MRF New; Create Parts Quotation not shown | | |
| TC-F7-E4 | resubmit | Submit; `approval` **Approve**; Create Parts Quotation; Confirm (do **not** validate the delivery) | – | Approved; DEMO AC Gas **Released** | | |
| TC-F7-E5–E7 | historical | *Rejected / withdrawn after a quotation* (cancel of the open quotation, Release Blocked, line locks, revalidation) can no longer happen on new requests: a quotation exists only after full approval. Covered by automated tests `test_mrf_figure7` 08 and 09 for quotations created before 2026-11-07. Check one historical UAT request instead if any exists (read only) | – | N/A for new requests | | |
| TC-F7-E8 | explicit rule | Create **R5**; new MRF (same case): DEMO AC Gas 1; Submit | – | Manager Approval; **Create Parts Quotation** hidden / refused "require the approval of Not Covered materials" | | |
| TC-F7-E9 | | `approval` Approve; Create Parts Quotation | – | Quotation created; then archive R5; Customer Declined (reason) to finish | | |
| TC-F7-E10 | stock / close | First MRF: Create Picking and PO, usage, close; second MRF: close | – | Closed | | |

### Change request D2a: Create Parts Quotation after full approval (2026-11-07, from MRF/000013)

Run after the UAT upgrade to mrf 18.0.1.10.2. Rules R2 / R3 as in section 4.

| ID | Rule | Step | Data / values | Expected | Actual | Status |
|---|---|---|---|---|---|---|
| TC-F7-CR1 | Manager pending | Mixed MRF (covered + Not Covered), Submit → Manager Approval | – | Create Parts Quotation **not shown** | | |
| TC-F7-CR2 | Finance / GM pending | `approval` Approve → Finance/GM Approval | – | Still **not shown** | | |
| TC-F7-CR3 | fully approved | Finance (and GM if required) Approve → Approved | – | **Shown**; creates one draft quotation with the Not Covered lines only | | |
| TC-F7-CR4 | duplicate | After CR3 | – | Button hidden; no second quotation | | |
| TC-F7-CR5 | no approval required | MRF matching only a No Approval rule (or none), with a Not Covered line; Submit | – | Approved - No Approval Required; button **shown** at once | | |
| TC-F7-CR6 | rejected / withdrawn | One mixed MRF rejected, another withdrawn | – | Button **not shown** on both; no quotation | | |
| TC-F7-CR7 | fully covered | Approved MRF with Covered lines only | – | Button **not shown** | | |
| TC-F7-CR8 | historical | Open MRF/000013 (and any request quoted before the upgrade) | – | Existing quotations unchanged (state, lines, release status) | | |

### Scenario F: warranty accounting on standard Odoo (after the upgrade to accounting 18.0.1.8.0)

Scenarios A to E are **not repeated**: no operational step changed. Design: `warranty_management_accounting/doc/figure7_accounting_integration.md`.

Preconditions: one Accounting Bookkeeper (`finance`), one Settings + Accounting Administrator (`admin`), one Invoicing-only user (`billing`). UAT keeps manual valuation unless Finance decides otherwise.

| ID | Branch | Steps | User | Expected | Actual | Status |
|---|---|---|---|---|---|---|
| TC-F7-AC1 | settings | Settings > Warranty Management > Warranty Accounting | admin | Blocks **Journal and Accounts** (no Cost Recognition) and **Warranty Reserve Utilization** (Subcontract / Goodwill Uses the Reserve, off; Accounting Configuration Status). No switch, effective date, opening stock or confirmation fields | | |
| TC-F7-AC2 | status | Read Accounting Configuration Status | admin | "Reserve utilization: ready"; "Manual valuation (…)": no journal entry at issue, cost recorded on the case | | |
| TC-F7-AC3 | rights | Open the same settings as `finance`; try to tick a policy box | finance | Read-only; refused "Settings and Accounting Manager" | | |
| TC-F7-AC4 | standard stock (manual) | MRF/000013 / WCAS/000070: Accounting > Journal Entries filtered on today; case > **Warranty Accounting** tab; MRF > Material Cost tab | finance | No warranty or stock journal entry from its usage; Covered Parts Posted to Warranty Expense 0; actual cost still shown on Material Cost / Case Cost Breakdown (unchanged) | | |
| TC-F7-AC5 | utilization (manual) | A completed case with used covered parts: **Create Reserve Utilization Draft** | finance | Refused "Nothing to utilize … Only cost posted to Warranty Expense counts"; no entry | | |
| TC-F7-AC6 | menus | Accounting > Accounting > Warranty | finance | Only **Warranty Reserve Utilization** (no parts review menu) | | |
| TC-F7-AC7 | vendor recovery | TC-F7-64 credit note: Accounting posts it, registers / reconciles as usual | billing | Standard vendor credit note on 450100; claim shows the recovery | | |
| TC-F7-AC8 | optional, only if Finance adopts automated valuation (test on a copy first) | Category Automated + stock accounts; Warranty Consumption location Stock Valuation Account (Incoming / Outgoing) = 625100; use a covered part; complete the case; Create Reserve Utilization Draft; post as `billing`, then as `finance` | finance | Odoo's stock entry Dr 625100 / Cr Stock Valuation (one, no warranty duplicate); draft Dr 216100 / Cr 625100 = min(eligible, available); `billing` refused, `finance` posts; Reports > Warranty Provision / Reserve shows it | | |

### Final checks

| ID | Check | Expected | Actual | Status |
|---|---|---|---|---|
| TC-F7-70 | Reports > Material Approval and Cost for A–E | Figures = MRF forms; Approval Status per MRF | | |
| TC-F7-71 | Material Audit Trail, MRF A and E | Approvals, automatic approvals, coverage decisions, quotation cancellation, moves, usage, return, closure | | |
| TC-F7-72 | Jobs: Complete; cases: Complete / Close Case | Allowed only after the MRFs are closed; ticket closure stays manual | | |
| TC-F7-73 | Figure 6 regression: WCAS/000066, 000068, BKU/00009, WH/RO/00016, 00018 | Unchanged | | |

### Reconciliation (fill from UAT)

| MRF | Product | Requested | Approved | Issued | Used / Installed | Returned | Cancelled / Declined | Actual cost | Customer charge | Vendor recovery |
|---|---|---|---|---|---|---|---|---|---|---|
| A | Fan Sensor | 1 | | | | | | | – | – |
| A | Compressor Relay | 2 | | | | | | | – | |
| A | Gas R410A | 1 | | | | | | | | – |
| C | DEMO AC Gas | 1 (after revision) | | | | | | | – | – |
| C | Cable Mgmt Box | 2 | | | | | | | – | – |
| C | Outdoor PCB | 1 | | | | | | | – | – |
| B | DEMO Fan Motor | 1 | | | | | | | – | – |
| D | DEMO AC Gas | 1 | | | | | | | – | – |
| D | Gas R410A | 1 | | | | | | | | – |
| E | DEMO Fan Motor | 3 | | | | | | | – | – |
| E | DEMO AC Gas | 1 | | | | | | | | – |

Rules for every line:
- Issued = Used / Installed + Returned + still open.
- Approved − Issued = Cancelled / Declined.

No quantity is changed to force this.
