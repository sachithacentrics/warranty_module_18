# Phase 5.3 – MRF Approval Matrix Integration – Design (revision 2, for review)

| Status | Revision 2 **approved 2026-10-26** (Q1 – Q11 as proposed in section 14, additional requirements 1 – 10); implemented in `warranty_management_mrf` 18.0.1.3.0, waiting for review. |
|---|---|
| Prepared | 2026-10-26 (rev. 1), 2026-10-26 (rev. 2) |
| Module | `warranty_management_mrf` only (inheritance). `material_purchase_requisitions`, Warranty Parts 1–4 and AMC unchanged. |
| Scope | Warranty-linked requests only (`warranty_case_id` set). Standalone requests keep the vendor workflow. |
| Databases | Development and tests on disposable databases (`wt_p5_mrf` …) only; `warranty_test` / `warranty_management_18_2` untouched. |

## 0. Sources reviewed

| Source | Relevant content |
|---|---|
| SRS 2.10 | Approval "configurable by estimated amount, product/category, coverage type, goodwill, branch/company and whether customer approval/payment is required"; stages Draft → Submitted → Manager Approval → Finance/GM Approval → Approved → …; "If total expected cost exceeds approval thresholds, the job/material issue cannot proceed until the required approvers accept it." |
| SRS 9.13 | Material Request: Draft → Submitted → Manager Approval → Finance/GM Approval → Approved → Partially Issued/Issued → Returned → Closed/Rejected |
| SRS 10.7 | Approval Status: Draft, Submitted, Manager Approved, Finance Approved, GM Approved, Rejected |
| SRS settings table | **Material Approval Matrix – Yes / No** – "By coverage, amount, category, goodwill and company – determines manager/finance/GM approvals before issue or customer commitment" |
| SRS 12 (p. 74) | Material cost approval: "Block issue/quotation where configured approval threshold is not met" |
| SRS 14 | "Material request cost exceeds threshold → Route approval to manager/finance/GM" |
| SRS 16 | Material Approver: "Approve MRF based on configured threshold and coverage"; audit to chatter |
| **SRS 16.1** | Covered part within automatic threshold → *Service Manager or auto-approval*; above Level 1 → *Service Manager + Finance*; high-value / goodwill → *GM + Finance*; non-covered → customer approval + SO/payment trigger (5.4) |
| `part5.drawio.svg` lane "Existing MRF – Approval Workflow" | Submit → Calculate total estimated cost → Determine approval route → Department / Manager Approval → Finance / GM approval required? → Finance / GM Approval → MRF Approved / Rejected → Notify requester |
| `part5_integration architecture.drawio.svg` | Bridge box "Approval and Issue Status" between the installed MRF and Inventory / Purchase |
| Mapping 5.3, D3, D6, D21 | Rule model, route stored at Submit, vendor methods wrapped, Warranty MRF Status, To-Dos, reject + notify |
| Vendor 11.9.12 code | section 1 |

(The request mentions PlantUML diagrams; the repository contains only the two `.drawio.svg` Phase 5 diagrams, which were used.)

## 1. Existing vendor approval flow (unchanged for standalone requests)

```
New ──Confirm──► Waiting Department Approval ──Department Approve──► Waiting IR Approval ──Approve──► Approved
 (draft)         (dept_confirm)                 group: Department Mgr   (ir_approve)          group: Requisition User
                                                                                              ──Create Picking and PO──► Picking/Purchase Created ──Received──► Received
Reject (dept_confirm / ir_approve / approve) ──► Rejected ──Reset to Draft──► New      Cancel (New) ──► Cancelled
```

| # | Finding in the vendor code | Risk |
|---|---|---|
| V1 | Approval is **group-based**: any Department Manager / Requisition User approves any request, including his own. | No named approvers, no separation of duties. |
| V2 | Methods do **not check the state**: `manager_approve`, `user_approve`, `request_stock`, `action_received`, `reset_draft`, `action_cancel`, `requisition_reject` work from any state when called directly (RPC / server action). | Approval steps can be skipped. |
| V3 | Every internal user has full CRUD on **his own** requests (record rule + ACL); `state` and the approval fields are normal writable fields. | Requester can write `state = 'approve'`. |
| V4 | Lines stay editable until Cancelled / Received. 5.2 locks product / coverage / add / delete after Confirm; **quantity, UoM and estimated unit cost are still editable**; the estimated unit cost is freely editable in Draft. | Approved amount ≠ requested amount; a lowered estimate dodges thresholds. |
| V5 | `request_stock` creates the picking **and** the RFQs in one action (RFQ lines with `sudo()`); stock / purchase users can link any picking / RFQ to a request through `custom_requisition_id`. | Material linked to an unapproved request; no partial release. |
| V6 | `send_mail(self.id)` in Confirm / Department Approve fails for multi-record calls (G9); the vendor e-mails go to the employee's manager / Requisition users (group-based). | Bridge acts record by record. |

## 2. Warranty approval flow (warranty requests, matrix enabled)

```
Draft ──Submit (vendor Confirm)──────────────────────────────────────────────────────────────────┐
  │  checks: lines, no Pending coverage (5.2), matching rule(s), approvers available             │
  │  computes and snapshots: routing amount, levels, named approvers, round number               │
  ▼                                                                                              │
 only explicit "No Approval Required" rules match ──► Approved (recorded as rule-based no-approval)
 Manager required ──► Waiting Department Approval = "Manager Approval"                            │
        named Manager approver: Approve ──► Finance and/or GM required? ── no ──► Approved          │
                                                            └─ yes ─► Waiting IR Approval = "Finance/GM Approval"
 Manager not required, Finance/GM required ──► Waiting IR Approval directly                       │
        Finance approver: Approve ┐ any order (D-N)                                               │
        GM approver: Approve      ┘──► every required level approved ──► vendor Approve (bridge) ──► Approved
 Approver of the pending level: Reject (reason) ──► Rejected ──Reset to Draft (requester / creator)──► Draft
 Requester / creator: Withdraw (while waiting, D-J) ──► Draft                                      │
 Draft ──Submit again──► new round, route recomputed, all required levels approve again (D-K) ───┘
 Approved ──Create Picking and PO (vendor, Requisition User)──► only when no Not Covered line (D-L)
```

* Vendor states are reused (D3): `dept_confirm` = Manager Approval, `ir_approve` = Finance/GM
  Approval, `approve` = Approved. A level that is not required is skipped by the bridge and
  recorded as *Skipped – not required*; the vendor never records the wrong person as approver.
* Manager approval always comes first when required; Finance and GM follow in any order (D-N).
* The vendor state Approved is set **only** when every required level of the current round is
  approved (D-O), by the bridge calling the vendor `user_approve` (vendor approval date /
  approver employee filled with the last approver).
* For warranty requests the vendor buttons *Department Approve*, *Approve* and *Reject* are hidden
  and replaced by **Approve** / **Reject** shown to the approvers of the pending level. Hiding is
  cosmetic only – every transition is enforced server-side (section 6).
* Computed **Warranty MRF Status** (D3): Draft, Manager Approval, Finance/GM Approval, Approved,
  Rejected, Cancelled (Partially Issued / Issued / Returned / Closed added in 5.5 / 5.6 / 5.9).
  Computed **Approval Status** (SRS 10.7): Draft, Submitted, Manager Approved, Finance Approved,
  GM Approved, Approved, Rejected.

## 3. Approval rules, thresholds and route

### 3.1 Configuration

* Company setting **Material Approval Matrix** – **enabled by default** (D-E) for every company
  (new field default True; the install sets it on existing companies).
* Company setting **Approval To-Do Deadline (days)** – default 1 (D-M).
* Menu **Warranty → Configuration → Material Approval Rules** (Warranty administrators).

`warranty.mrf.approval.rule`

| Field | Meaning |
|---|---|
| Name, Sequence, Active, Note | |
| Company | Company or branch the rule is defined for (required). Applies to that company and its branches (D-B, 3.3). |
| Minimum / Maximum Amount | Range of the **routing amount** (3.2) in company currency; minimum inclusive, maximum exclusive, Maximum 0 = no upper limit |
| Coverage Condition | Any / Covered lines present / Not Covered lines present / Only Not Covered lines |
| Goodwill Condition | Any / Goodwill lines present |
| Product Categories, Products | at least one line product in these categories (child categories included) / products; empty = all |
| **No Approval Required** | explicit flag (additional control 1): the rule authorizes approval without approvers; mutually exclusive with the level flags |
| Manager Required + Manager Approvers | users |
| Finance Required + Finance Approvers | users |
| GM Required + GM Approvers | users |

Constraints: a rule either has **No Approval Required** or at least one required level; every
required level needs at least one approver; approvers must be internal users allowed in the rule
company; Maximum > Minimum when set.

### 3.2 Routing amount (D-A, D-F)

* Per line: **routing cost = max(entered estimated cost, product cost in the line UoM × qty)**.
  The entered *Estimated Unit Cost / Estimated Cost* stay unchanged on the line (information,
  later estimated vs approved vs actual in 5.7); the routing cost is a separate stored field
  (D-F).
* **Routing amount = Σ routing cost of all lines** – Covered, Not Covered and goodwill (D-A).
* Covered / Not Covered / Goodwill sub-totals are stored for information and for the coverage
  conditions of the rules.

### 3.3 Route determination at Submit

1. **Applicable rules** (D-B): active rules whose Company is the request company **or one of its
   parent companies** (Odoo 18 branches = child companies). See open question Q1 for the case
   where a branch has its own rules.
2. **Matching rules**: applicable rules whose amount range, coverage, goodwill and product /
   category conditions match.
3. **No matching rule → Submit refused** with a configuration error ("No material approval rule
   matches … – contact the Warranty administrator"). There is no implicit auto-approval
   (additional control 1).
4. **Strictest combination** (D-C): a level is required when any matching rule requires it; its
   approvers = union of the approvers of the matching rules for that level. A *No Approval
   Required* rule has effect only when **every** matching rule is a *No Approval Required* rule.
5. **Goodwill** (D-G): a request with a goodwill line always requires **Finance and GM**, added
   to the matched levels (Manager only when a matching rule requires it – see Q9).
6. **Approver availability** (D-B "access restrictions", D-D): approvers who are inactive, not
   allowed in the request company, or excluded by separation of duties (section 4) are removed.
   A required level left without approvers → Submit refused naming the level.
7. **Snapshot** (D-H): routing amount, sub-totals, levels, rules and the remaining approvers are
   stored as the approval lines of a new round. Later rule or cost changes do not affect a
   submitted request; they apply on resubmission.

### 3.4 Illustrative test configuration (D-I – manual / automated test data only, nothing seeded)

| Seq | Rule | Condition | Levels |
|---|---|---|---|
| 10 | Low value | routing amount < 25,000, no goodwill | **No Approval Required** (or Manager, to test the other SRS option) |
| 20 | Level 1 | 25,000 ≤ amount < 100,000 | Manager + Finance |
| 30 | High value | amount ≥ 100,000 | **Manager + Finance + GM** (D-I) |
| 40 | Goodwill | goodwill lines present | Finance + GM (also forced by D-G) |
| 50 | Chargeable only | only Not Covered lines, < 25,000 | Manager |

Example: 12,000 covered + 15,000 not covered = 27,000 → rule 20 (Manager + Finance), because
D-A counts all lines.

### 3.5 Deadlines and escalation (D-M)

One To-Do per approver of the pending level (Manager first; Finance and GM together when the
manager level is done or not required), deadline = today + company *Approval To-Do Deadline*.
Open To-Dos of a level are closed when the level is decided, on rejection and on withdrawal.
No automatic escalation or re-assignment.

## 4. Roles and separation of duties (D-D, D-J)

| Role (SRS 16) | Odoo | 5.3 rights on warranty requests |
|---|---|---|
| Technician | Field Service User | create (5.1); submit, withdraw, reset, cancel **own** requests (requester or creator) |
| Service Coordinator | Helpdesk User (+ Requisition User) | create, submit; withdraw / reset / cancel **only** requests he requested or created (D-J – no general Helpdesk right) |
| Material Approver – Manager / Finance / GM | **named users on the rules** (any internal user of the company) | approve / reject the pending level of requests routed to them; read access to those requests (new record rule) |
| Store User | Inventory User + Requisition User | *Create Picking and PO* only on fully approved requests without Not Covered lines (D-L); issue itself: 5.5 |
| Purchasing | Purchase User | unchanged; RFQs only from approved requests |
| Warranty administrator | Settings / Administration | rules and settings |

Separation of duties (server-side):

* The **requester** (employee's user), the **creator** and the **submitter** of the round cannot
  approve any level (D-D).
* **One person approves at most one level** of the same request round (D-D). A user listed for
  Finance and GM can approve either, then the other level needs another person.
* Excluded users are removed from the snapshot; a level left empty blocks the submission (3.3.6).
* 5.2 coverage reviewers may also approve (different control) – unchanged unless you decide
  otherwise (Q8).

## 5. Approval history (additional control 7)

`warranty.mrf.approval` – one line per required level per round; no create / write / unlink
rights for users (written by the bridge only), kept for ever:

| Field | |
|---|---|
| Request, Round (1, 2, …), Level (Manager / Finance / GM / No Approval) | |
| Rules | rules that required the level |
| Allowed Approvers | snapshot (3.3.7) |
| Status | Pending / Approved / Rejected / Skipped / Withdrawn / Superseded |
| Decided By, Decision Date, Reason / Comment | reason required for Reject, optional for Approve |
| Routing amount, Covered / Not Covered / Goodwill sub-totals | snapshot of the round |

* **Approvals** tab on the request (all rounds); header: Submitted By / On, Round, Routing Amount,
  Approved By / On (last level), **Approved Amount** (snapshot for 5.7).
* Chatter on the request for submission, every approval / rejection / skip / withdrawal /
  no-approval rule; notes on the case and the job (D17).
* Notifications (D-P): requester and submitter receive a message (chatter notification, e-mail
  when an outgoing mail server is configured) on final approval and on rejection.

## 6. Server-side enforcement and bypass protection (additional controls 2–5)

Privileged writes are done by bridge methods in superuser mode (`sudo()`) after their own checks.
A context key alone is not used for authorization: a client can pass any context through RPC,
but cannot obtain superuser mode.

| Vector | Protection (warranty requests only) |
|---|---|
| Direct write of `state`, vendor approval fields (`approve_manager_id`, `approve_employee_id`, `managerapp_date`, `userrapp_date`, `employee_confirm_id`, `confirm_date`, `reject_*`), approval snapshot / amount / round fields (V3) | refused unless superuser mode |
| Header changes after Submit: employee, department, company, warranty links, request / deadline dates, reason | refused until Draft again (allow-list of fields still editable after Submit: see Q4) |
| Create a warranty request in a state other than Draft | refused |
| `requisition_confirm` | = Submit with the checks of 3.3; Draft only |
| `manager_approve`, `user_approve` called directly (V2) | refused unless called by the bridge Approve after the level / approver / separation checks |
| `requisition_reject` called directly | refused; bridge Reject (reason required, pending-level approver only) |
| `request_stock` | only state Approved, round complete (every level Approved / Skipped), line snapshot unchanged, **no Not Covered line** (D-L) |
| `action_received` | only from Picking / Purchase Created |
| `reset_draft` | only from Rejected / Cancelled, requester or creator (Q2, Q7) |
| `action_cancel` | only from Draft / Rejected, requester or creator (Q6) |
| Line changes after Submit (V4, control 3) | product, quantity, UoM, estimated unit cost, coverage, add / delete refused while not Draft; changes only via Withdraw / Reset to Draft + new round |
| Lowered estimated unit cost (V4) | routing cost = max(entered, product cost) (D-F) |
| Picking / move / RFQ / PO line linked to a warranty request (V5) | `custom_requisition_id` / `custom_requisition_line_id` on `stock.picking`, `stock.move`, `purchase.order`, `purchase.order.line` may point to a warranty request only when it is Approved or later **and** has no Not Covered line (until 5.4); checked on create and write, also in superuser mode (the vendor creates RFQ lines with `sudo()`) |
| Validation of such a picking when the request is no longer approved | refused (defensive) |
| Approval history | read-only, no unlink right; deleting a warranty request that has an approval history is refused (Q10) |
| Matrix switched off while requests wait | submitted requests keep their snapshot route |
| Standalone requests (control 5) | none of the above; vendor workflow, buttons and groups unchanged (regression tests) |

## 7. Rejection, withdrawal and resubmission

* **Reject** (approver of the pending level): wizard, reason required → vendor state Rejected
  (vendor reject employee / date set by the bridge), pending lines Rejected / Superseded, To-Dos
  closed, requester + submitter notified, note on case / job.
* **Withdraw** (requester or creator, while Manager Approval or Finance/GM Approval – Q2): back to
  Draft, round lines Withdrawn, To-Dos closed. Ordinary Helpdesk users cannot withdraw other
  users' requests (D-J).
* **Reset to Draft** (vendor button, Rejected / Cancelled, requester or creator): lines editable
  again; 5.2 coverage decisions kept unless the product changes.
* **Resubmit** = Submit → new round, route recomputed with the current rules / costs, every
  required level approves again (D-K); earlier rounds stay in the history.
* After **Approved** nothing can be changed; additional parts = new request (D21).

## 8. Protection against stock issue / procurement before authorization (D-L)

* Picking / RFQ creation only through *Create Picking and PO* on a fully approved request.
* **Until 5.4**, *Create Picking and PO* and any picking / RFQ link are refused for warranty
  requests with a Not Covered line (message: "… contains Not Covered lines – released by the
  commercial control (Phase 5.4)"). The vendor action creates the picking and the RFQs for the
  whole request at once, so a mixed request is blocked completely (see T-3).
* Approval itself is not blocked by Not Covered lines (D-A counts them).

## 9. Matrix switched off

Warranty requests follow the vendor 2-step flow (group-based approvers), still with: 5.2 coverage
rules, separation of duties (requester / creator / submitter cannot approve), state / field / line
protection, D-L release block and the picking / RFQ guards. No rule routing.

## 10. Phase 5.2 status before integration (additional control 8)

| Item | Status |
|---|---|
| 5.2 automated tests | 7 / 7 passed; bridge 28 / 28; regression 381 tests, 0 failed, 1 error = Part 3 `test_13_serial_rules` (existing Part 3 permission issue, reproduced without Phase 5) |
| 5.2 manual tests | main workflow tested by you; TC-P5-201 – 213 results not yet recorded in the guide |
| D7 default coverage rules / reviewers = Warranty Case Approval Users | implemented as recommended – **confirmation outstanding** |
| G4 (Covered Under Warranty? = computed label) | **confirmation outstanding** |
| Lock after Confirm (5.2: product / coverage / add / delete) | 5.3 extends it to quantity, UoM, estimated cost and header (D21) – consistent |
| Reviewers need access to the request | **confirmation outstanding** |
| Part 3 serial-name AccessError for Helpdesk users without Inventory rights | **your decision outstanding** (Part 3 change) |

5.3 relies on 5.2 as follows: Submit refuses Pending lines (5.2); goodwill comes only from a 5.2
reviewer decision; coverage is frozen from Submit on.

## 11. Technical conflicts identified

| # | Conflict | Proposed handling |
|---|---|---|
| T-1 | Vendor e-mails (Confirm → employee's manager; Department Approve → Requisition users) are group-based and would announce approvals to people who are not the named approvers. | Keep them unchanged (vendor behaviour) in addition to the named To-Dos – Q5. |
| T-2 | A skipped Manager level must not go through vendor `manager_approve` (it would record the submitter as department approver). | Bridge moves the state directly (superuser) and records "Skipped". Vendor manager fields stay empty. |
| T-3 | D-L + vendor `request_stock` handles the whole request: a mixed request (covered + not covered) cannot release its covered lines before 5.4. | Accept until 5.4 (workaround: separate requests for covered and chargeable parts) – Q3. 5.4 / 5.5 will release per line. |
| T-4 | Requesters have full CRUD on their own requests through vendor rules (needed for Draft editing); the protection must therefore be field-based on `write`, which a later vendor version could circumvent with new fields. | Allow-list of fields editable after Submit (Q4) instead of a deny-list. |
| T-5 | D-B "subject to explicit company/branch rules": with strictest combination a branch rule cannot relax a parent rule. | Q1. |
| T-6 | Approvers need to read the request; vendor / bridge rules give that only to own requests, Helpdesk, Requisition and Department users. | New read rule: users allowed on an approval line of the request (any round) read it and its lines; decisions run in superuser mode after checks. |
| T-7 | Rules store users per level; an approver without an employee leaves the vendor approver-employee fields empty. | History keeps the user; acceptable. |
| T-8 | D-A includes Not Covered lines; if the customer later declines them (5.4), the approved amount is higher than needed. | No re-approval for decreases; increases are impossible after Submit (lock). |
| T-9 | Existing 5.1 / 5.2 tests confirm warranty requests through the vendor `requisition_confirm` without rules. | Tests updated to configure a rule (or the matrix off); standalone tests unchanged. |
| T-10 | `wt_p5_mrf` contains manually created warranty requests in Confirmed states from the 5.1 / 5.2 tests, without approval rounds. | Existing submitted requests without a round are treated as "legacy": no new approvals possible, Reset to Draft required (disposable DB only; no production data exists). |

## 12. Automated tests (planned, `tests/test_mrf_approval.py`)

| # | Scenario |
|---|---|
| T3.1 | Rule matching: amount boundaries (25,000 / 100,000), coverage and goodwill conditions, category (child), product, inactive rule ignored |
| T3.2 | Routing amount = all lines, max(entered, product cost) per line, entered values preserved (D-A, D-F) |
| T3.3 | Company / branch: parent rule applies to a branch request; branch rule does not apply to the parent (D-B) |
| T3.4 | Strictest combination of several matching rules (levels and approvers union) (D-C) |
| T3.5 | No matching rule → submit refused; explicit No Approval Required rule → Approved with history; No-Approval rule + a Manager rule → Manager required |
| T3.6 | Manager only → named manager → Approved; Finance/GM skipped |
| T3.7 | Manager + Finance (Level 1) → Approved only after both; Finance before Manager refused |
| T3.8 | High value → Manager, then Finance and GM in both orders (D-I, D-N) |
| T3.9 | Goodwill → Finance + GM forced (D-G) |
| T3.10 | Separation of duties: requester / creator / submitter refused; one user one level; empty level → submit refused; approver not allowed in the company removed |
| T3.11 | Non-approvers (incl. vendor Department Manager / Requisition User groups) refused; direct calls of `manager_approve`, `user_approve`, `requisition_reject`, `request_stock`, `action_received`, `reset_draft`, `action_cancel` from wrong states / by wrong users refused |
| T3.12 | Direct writes of `state`, vendor approval fields, snapshot fields, header fields after Submit refused (requester own rule); create in non-Draft refused |
| T3.13 | Line lock after Submit: product / qty / UoM / estimated cost / coverage / add / delete refused (control 3) |
| T3.14 | Reject → reason required, Rejected, To-Dos closed, requester + submitter notified, case / job note |
| T3.15 | Withdraw by requester / creator; refused for another Helpdesk user (D-J) |
| T3.16 | Reset to Draft + resubmit → round 2, all levels again, round 1 kept (D-K, control 7) |
| T3.17 | Rule / cost change after submission does not change the snapshot (D-H) |
| T3.18 | `request_stock` before Approved / incomplete round refused; with a Not Covered line refused (D-L); covered-only approved request creates picking / RFQ |
| T3.19 | Manual picking / move / RFQ / PO line linked to an unapproved or Not Covered request refused (also in superuser mode) |
| T3.20 | To-Do deadline from the company setting; no escalation (D-M) |
| T3.21 | Matrix off → vendor 2-step flow with protections (D-E) |
| T3.22 | Standalone request: vendor flow, buttons, groups, picking / RFQ unchanged (control 5) |
| T3.23 | Approver record rule; views render for requester, approver, Store user, technician |
| – | Full regression (Parts 1–4, MRP, AMC if its tests exist again, bridge) |

## 13. Manual tests (planned, TC-P5-301 …)

Users *Service Manager*, *Finance Officer*, *GM*, a second Helpdesk user; rules of 3.4.
Scenarios: low value (No Approval Required); no matching rule (e.g. rule 10 archived → error);
Level 1 mixed coverage 27,000 (Manager + Finance); high value (Manager, then Finance / GM in both
orders); goodwill line; chargeable-only; requester / creator / other user tries to approve; one
user on two levels; vendor buttons absent; reject with / without reason, reset, resubmit (round
2); withdraw by requester and refused for another Helpdesk user; quantity / cost change after
Submit refused; lowered unit cost routes on product cost; *Create Picking and PO* before / after
approval and with a Not Covered line; manual picking linked to an unapproved request; approval
history tab and chatter on request, case, job; notifications to requester / submitter; To-Do
deadline; matrix off; standalone request through the vendor flow; branch company (if a branch is
configured in the test DB).

## 14. Decisions (review 2026-10-26) and open questions

Confirmed in the review: D-A all lines · D-B parent rules apply to branches · D-C strictest ·
D-D requester / creator / submitter excluded, one person one level · D-E enabled by default ·
D-F max(entered, product cost), entered value kept · D-G Finance + GM · D-H snapshot · D-I
25,000 / 100,000 test data only, high value incl. Manager · D-J requester / creator only · D-K new
round · D-L block release with Not Covered lines until 5.4 · D-M configurable deadline, no
escalation · D-N Finance / GM any order after Manager · D-O vendor Approved only when complete ·
D-P requester and submitter · additional controls 1–8.

Still to confirm:

| # | Question | Proposal |
|---|---|---|
| **Q1** | D-B: when a branch has its own rules, do the parent-company rules still apply (combined, strictest – a branch cannot relax the parent) or do the branch rules replace the parent rules for that branch? | Combine (consistent with D-C, safer). |
| **Q2** | D-J "subject to request status": withdrawal allowed during Manager Approval only, or also during Finance/GM Approval after the manager approved? | Both waiting states, until final approval; earlier approvals of the round become Withdrawn. |
| **Q3** | D-L / T-3: mixed requests (covered + not covered) are blocked completely until 5.4. Acceptable, with separate requests as workaround? | Yes. |
| **Q4** | Header fields still editable after Submit (allow-list). | Only *Picking Details* (source / destination location, picking type) for Requisition / Inventory users until the picking exists; nothing else. |
| **Q5** | Keep the vendor group-based e-mails (T-1)? | Keep (vendor unchanged); named To-Dos are the authoritative approval requests. |
| **Q6** | Cancel of a warranty request: who / when? | Requester or creator, in Draft or Rejected. |
| **Q7** | Vendor *Reset to Draft* also from Received: block for warranty requests? | Block (Received is final for warranty requests). |
| **Q8** | May a 5.2 coverage reviewer who decided coverage on the request also approve it? | Yes (separate control); alternative: exclude. |
| **Q9** | Goodwill: Manager only when a matching rule requires it (D-G literally Finance + GM)? | Yes – with the D-I rule set a high-value goodwill request gets Manager + Finance + GM anyway. |
| **Q10** | A Draft request that was submitted and withdrawn / rejected can be deleted by the vendor unlink – delete its approval history with it, or forbid deleting requests that have a history? | Forbid deleting warranty requests with an approval history (Cancel instead). |
| **Q11** | Outstanding 5.2 confirmations (section 10) and the Part 3 serial-name fix. | Confirm before 5.3 integration. |
