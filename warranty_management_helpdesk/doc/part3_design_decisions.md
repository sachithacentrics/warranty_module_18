# Warranty Management – Part 3 Design Decisions (Helpdesk + Warranty Case + Eligibility)

| Item | Value |
|---|---|
| Module | `warranty_management_helpdesk` 18.0.1.0.0 (depends `warranty_management`, `helpdesk`) |
| Primary sources | Warranty Module SRS (§2.6, §9.4–9.5, §10.4, Helpdesk Warranty Panel), Part 3 Development Mapping diagram (`warranty part3Diagram.drawio.svg`) |
| Status | Stage 3.1 implemented on `warranty_test` and **approved by the business owner after manual testing (2026-10-19)**. Stage 3.2 implemented and **approved by the business owner after manual testing (2026-10-19)**. Stage 3.3 implemented and **approved by the business owner after manual testing (2026-10-19)**. Stage 3.4 **approved** (2026-10-20). Stage 3.5 **approved** (2026-10-20). Stage 3.6a (case approval) **approved** (2026-10-20). Stage 3.6b (claim rejection) **approved** (2026-10-20). Stage 3.6c (chargeable conversion / partial coverage) **approved** (2026-10-20). **Part 3 complete.** |

## Stage breakdown (approved plan)

| Stage | Diagram scope |
|---|---|
| 3.1 Helpdesk Ticket and Warranty Case | Complaint → Helpdesk ticket → customer / site / product / serial → pending services → link selected service / create case |
| 3.2 Card, serial and validity | Find card → serial match → warranty active / draft → period / usage validity |
| 3.3 Payment and overdue handling | Payment check, overdue claim handling (Warning / Hold / Approval / Block) |
| 3.4 Coverage and entitlement | Requested service / item coverage, free service entitlement availability |
| 3.5 Repeated failure and final eligibility | Threshold, escalation, Eligible, ready for Service Job |
| 3.6 Claim rejection and chargeable conversion | Chargeable inspection / service / excluded-item quotations, rejection |

## Stage 3.1 decisions

| ID | Topic | Approved resolution |
|---|---|---|
| Q1 | Module | Separate module `warranty_management_helpdesk`; Helpdesk installed on `warranty_test` only. |
| Q2 | Site | The customer's delivery address (child contact). The card's site is the delivery address of its Sales Order (no new card field). |
| Q3 | Case status | The 9 SRS §10.4 statuses (New, Eligibility Checked, Approved, Rejected, Chargeable, Job Created, In Progress, Completed, Closed). Hold / Pending Approval will be separate indicators (stage 3.3). Stage 3.1 only creates **New** cases. |
| Q4 | Cases per ticket | Several warranty cases per Helpdesk ticket. |
| Q5 | Pending services | Draft, Pending, Scheduled, Rescheduled, and Missed up to the Grace Period End Date; card Confirmed; Free Services Balance > 0 (parts of Part 2 rule A9 checked at this stage); optional filters site / product / serial (unit serials incl. kit Indoor / Outdoor). The same rule is checked when a service is linked. |
| Q6 | Skill / technician | Required Skill and Assigned Technician (§10.4) are not implemented in Part 3 (§2.5 / Part 4). |
| Q7 | AMC case | Case Type AMC kept; handled as Manual Review in stage 3.2; no AMC functionality. |
| A | Create / Link | The wizard creates a case and links the selected pending services; no linking to an existing case from the wizard; services are managed on the case while it is New. |
| B | Part 2 behaviour | Linking does not change the service merge status, lifecycle status, schedule or monitoring. Merging is Part 4. |
| C | **Additional rule (not in the SRS)** | A free service can be linked to only one **active** warranty case (not Rejected / Closed); after Rejected / Closed it may be linked to a new case if it is still pending. |
| D | Product / serial on the ticket | Own fields on the Helpdesk ticket (`warranty_product_id`, `warranty_serial_id`, `warranty_site_id`); `helpdesk_stock` is not installed. |
| E | Priority | Case priority defaults from the ticket priority (0 Low, 1 Normal, 2 High, 3 Urgent), editable. |

## Implementation (stage 3.1)

- `warranty.case` (WCAS/000001, mail thread): ticket (required), customer / company from the
  ticket, site, case type (7 SRS values), customer complaint (default: ticket description, else
  subject), product, serial, warranty card (from the linked services; found in 3.2), priority,
  status, eligibility result (empty until 3.2), pending customer services (computed), linked
  free services, merged ad-hoc request + description.
- `helpdesk.ticket`: Warranty tab (site, product, serial, pending services), *Create Warranty
  Case* button, *Warranty Cases* smart button.
- `warranty.service.entitlement`: `helpdesk_ticket_id` (Development Mapping field) = ticket of
  its active case; `warranty_case_ids`.
- Wizard `warranty.case.create.wizard`.
- Security: internal users read cases; Helpdesk users create / edit; Helpdesk managers also
  delete (New cases only); multi-company record rule; no new groups.
- Menus: Warranty → Warranty Cases; Helpdesk → Tickets → Warranty Cases.

## Known limitations of stage 3.1

- No eligibility check yet: Eligibility Result stays empty and the status stays New until
  stage 3.2.
- Cases are created from a ticket only (the Warranty Cases menu has no Create button).

## Stage 3.2 decisions (approved 2026-10-19)

| ID | Topic | Approved resolution |
|---|---|---|
| Q8 | Card Draft / Ready to Confirm | **Manual Review** with the message "confirm the warranty (Confirm Warranty) and check again"; the existing warranty confirmation is reused, no new approval. *(SRS §9.5: "block service entitlement activation / job confirmation"; the diagram: "Require Authorized Warranty Confirmation".)* |
| Q9 | Usage basis | New case field **Current Usage** (entered by the user, usage unit of the card shown); valid when <= the unit's usage limit (else the card's); empty (0) -> Manual Review; above -> Out of Warranty. No worksheet integration (Part 4). *(Not explicitly specified by the SRS: "Check Usage Limit / Current Usage".)* |
| Q10 | Validity date | **Helpdesk ticket creation date** (user timezone): Warranty Start <= date <= Warranty End (unit dates, else card dates); not today's date. *(Not specified by the SRS.)* |
| Q11 | Missing serial | Units with serial numbers (serial-tracked product, or kit Indoor / Outdoor serials) require the case Serial No. -> Manual Review "serial number is required"; units without serials skip the serial check. |
| Q12 | Several cards | Several cards / units for customer + product (or serial on several units) -> Manual Review; the user selects the Warranty Card / Unit Warranty and checks again; never an arbitrary card. |
| Q13 | Checked case types | Warranty Complaint, Free Service, Replacement, Reopen/Repeat Complaint; AMC -> Manual Review; Chargeable Inspection / Repair are not checked (chargeable workflow, stage 3.6). |
| Q14 | Suspended / Expired / Cancelled card | **Not Eligible**. |

### Implementation (stage 3.2)

- *Check Eligibility* button on the case (Helpdesk users, status New / Eligibility Checked, not for
  chargeable types): Find Warranty Card / Unit (selected unit > selected / linked card > unit with
  the serial > customer cards of the product; customer and company always respected) -> serial ->
  card status -> period / usage validity; stops at the first failure.
- Result: status **Eligibility Checked**; Eligibility Result Manual Review / Not Eligible / Out of
  Warranty on a failure; **empty when all 3.2 checks pass** (payment, coverage and repeated failure
  follow in 3.3-3.5; final Eligible in 3.5). The found card / unit are written on the case.
- Each run is logged on the case as an internal chatter note with every step and its reason.
- New case fields: Unit Warranty (SRS Helpdesk Warranty Panel), Current Usage (Q9). Ticket Warranty
  tab: Warranty Card / Unit Warranty found from the ticket customer, product and serial (read-only).
- Product, Serial No., Warranty Card, Unit Warranty and Current Usage stay editable while the case
  is New / Eligibility Checked so a correction can be checked again.
- Part 1 / Part 2 records are only read.

### Known limitations of stage 3.2

- The "Create Chargeable Inspection / Manual Review", "Serial Mismatch / Possible Rejection" and
  "Move to Chargeable Service" actions of the diagram are only results / messages until stage 3.6.
- A Current Usage of 0 is treated as "not provided".

## Stage 3.3 decisions (approved 2026-10-19)

| ID | Topic | Approved resolution |
|---|---|---|
| Q15 | Payment / settlement conditions | *Revised 2026-10-20 (Option B), see below.* (1) **Every posted customer invoice of the warranty sale is Paid** (Odoo 18 `payment_state = paid`); none posted, In Payment (registered, not reconciled), Partially Paid, Not Paid, Blocked, Reversed (refunded) fail. (2) **No overdue receivables**: posted customer invoices of the same commercial customer and company, due before today (company warranty timezone), not Paid / Reversed (In Payment counts as not settled). Passed = (1) and (2). Part 1 confirmation (Paid or In Payment) unchanged. |
| Q16 | Overdue Warning | Always computed and shown on the case and the Helpdesk ticket ("Customer has N overdue invoice(s) (amount due X)"; the In Payment note was removed by Q15 rev. B); informational only when Payment Check Required is off. |
| Q17 | Handling not configured | Warning Only. |
| Q18 | Approvers | New company setting **Overdue Claim Approval Users** (Warranty Settings, internal users allowed in the company); one To-Do activity per approver except the requester; no duplicates while open; requester never approves. |
| Q19 | Waiver | Approval sets Payment Eligibility **Waived** and stores approver, date and the failed conditions on the case; Check Eligibility must be run again; later checks of the same case use the waiver when the payment still fails; other cases are not covered. |
| Q20 | Release | No Release button: the next Check Eligibility after payment gives Passed and removes On Hold / Blocked / Pending Approval (open approval activities are closed). |
| Q21 | Free services | Payment Eligibility stays on the case; linked free services are not changed (Service Job stage). |

### Q15 revision B (approved 2026-10-20)

Bank reconciliation pending must not block a case on its own:

* **Paid** passes; **In Payment** passes when the invoice is **fully covered by the registered
  payments** linked to it.
* *Uncovered amount* (invoice currency) = `amount_residual` minus the linked payments
  (`matched_payment_ids`) **without journal entry** in state In Process / Paid, inbound customer
  payments only. Payments with a journal entry are already in the residual once reconciled (not
  counted twice); cancelled / rejected / draft payments are not counted. A payment linked to
  several invoices is allocated once, to the earliest due invoice first. Payment amounts are
  converted to the invoice currency at the payment date.
* Odoo 18 shows In Payment both for a reconciled payment awaiting the bank statement (residual 0)
  and for a payment without journal entry (residual unchanged, also when the payment is only
  partial); both are handled by the rule above.
* Overdue receivables / Overdue Warning count only invoices with an uncovered amount and show the
  uncovered amount (company currency). A partially covered In Payment invoice stays subject to
  Warning / Hold / Approval / Block; the warranty sale invoice problem shows "In Payment, not fully
  covered by the registered payments (uncovered X)".
* Recomputed at every Check Eligibility; no invoice or payment is modified; Part 1 confirmation
  unchanged. Verified read-only on the working database: INV/2026/00009 and INV/2026/00010 (In
  Payment, residual 1.15 each, payments without journal entry) = uncovered 0, not overdue.

### Implementation (stage 3.3)

Check Eligibility continues after the 3.2 checks (card's policy; cards without policy = Not
Required):

| Situation | Payment Eligibility | Result / indicator |
|---|---|---|
| Payment Check Required off | Not Required | continue (3.4) |
| Conditions passed | Passed | continue |
| Failed + waiver of this case | Waived | continue |
| Failed + Warning Only (or empty) | Failed | warning logged, continue |
| Failed + Hold | Failed | Pending Payment, **On Hold** |
| Failed + Approval Required | Pending | Pending Payment, **Pending Approval**, activities to the approvers |
| Failed + Block | Failed | Pending Payment, **Blocked** |

Never Rejected (SRS 9.5 "do not silently reject"). Every check / approval is logged as an internal
chatter note. Accounting data is read with `sudo` (only counts, amounts and references shown).
When the requester has no email address the approval activities are assigned without the
assignment email.

## Stage 3.4 decisions (approved 2026-10-19)

| ID | Topic | Approved resolution |
|---|---|---|
| Q22 | Requested service / items | New case field **Requested Items** (Many2many `warranty.coverage.item`), selected manually (editable while New / Eligibility Checked). |
| Q23 | Item not in Covered / Excluded Items | Manual Review (never assumed covered or excluded). An item in both lists is also Manual Review. |
| Q24 | No Requested Items | Manual Review, also for Free Service cases (stricter reading of SRS 9.5, accepted). |
| Q25 | Free Service Request | Case Type Free Service, or any case with linked free services. |
| Q26 | Free Service case without linked service | Manual Review; nothing linked automatically. |
| Q27 | Card without policy (P5 own values) | Manual Review: coverage exists only on the Warranty Policy (SRS 10.1); P5 rules unchanged. **Accepted limitation:** P5 cards never pass coverage automatically; existing cards / snapshots are not modified. |
| Q28 | Partial coverage | Eligibility Result **Partial**, the check stops; the excluded items are listed for the chargeable quotation (stage 3.6). |

### Implementation (stage 3.4)

After the payment step (3.3), in diagram order:

1. **Coverage:** no policy / no items / undefined item / item in both lists -> Manual Review;
   covered + excluded -> Partial; only excluded -> Not Eligible; all covered -> continue.
2. **Free service entitlement** (only for Free Service cases or cases with linked services):
   none linked -> Manual Review; a linked service of another warranty card -> Manual Review; a
   linked service no longer available (3.1 / Part 2 A9 rule: card confirmed, Draft / Pending /
   Scheduled / Rescheduled or Missed within grace, balance > 0) -> Not Eligible ("convert to
   chargeable service or reject", 3.6); otherwise continue ("the repeated failure check
   follows", 3.5).

Rule C (one active case per free service) unchanged; linking never changes the service status,
schedule, merge status or monitoring; the case is never marked Eligible in this stage.

## Stage 3.5 decisions (approved 2026-10-20)

| ID | Topic | Approved resolution |
|---|---|---|
| Q29 | Failures | Warranty cases of type Warranty Complaint, Replacement, Reopen/Repeat Complaint; not Rejected. Free Service, AMC, Chargeable Inspection / Repair not counted. |
| Q30 | Threshold | Failures within the period **including this case** > threshold → escalation (threshold 2: the 3rd failure escalates). |
| Q31 | Physical unit (unit first) | 1. Unit Warranty (all its serials; kit Indoor + Outdoor = one system); 2. serial number; 3. card + product only when the card has exactly one unit of the product. Different physical units are never combined. |
| Q32 | No Escalation Rule | Threshold or period 0 / empty → check skipped, Eligible. |
| Q33 | Free Service cases | Checked against the earlier failures, not counted themselves. |
| Q34 | Final result | Status Eligibility Checked, Eligibility Result **Eligible** ("ready for the Service Job"); never Approved automatically, no Service Job. |
| Q35 | Failure Category | Optional (reporting). |
| Q36 | Repeated Failure Flag | Updated by every check that reaches 3.5; escalation activities, confirmation and chatter history kept. |
| Q37 | Unit not identified | Manual Review "Physical unit not identified …: select the Unit Warranty or serial number". |

### Implementation (stage 3.5)

* Policy (`_inherit` in this module, Controls group): **Repeated Failure Threshold**, **Repeated
  Failure Period (days)** (SRS 10.1 Escalation Rule).
* Company setting **Repeated Failure Escalation Users** (Manager / GM; internal users of the
  company), Warranty Settings block "Warranty Case Payment Exceptions and Escalations".
* Case: Failure Category, Repeated Failure (flag), Failures in Period, Escalated - Pending
  Confirmation, Escalation Requested By, Warranty Confirmed By (Repeated Failure) / date; button
  **Confirm Warranty (Repeated Failure)**; filters Repeated Failure / Escalated.
* Period = ticket dates from (this ticket date - N days) to this ticket date (company / user
  timezone, as 3.2); later tickets are not counted.
* Earlier cases: same company and commercial customer, failure type, not Rejected. Their unit is
  the stored Unit Warranty or, for cases never checked, resolved like the 3.2 check (serial →
  unit, single card / unit of the product). Cases that could belong to several units of the
  product (no unit / serial) are **not counted** and listed as "not attributable" in the chatter.
* The selected Unit Warranty must belong to the case card, company, customer and product, else
  Manual Review.
* Exceeded: Repeated Failure flag, Eligibility Result Manual Review, red banner, one To-Do per
  escalation user except the requester (no duplicates while open). An escalation user (never the
  requester) confirms → stored on this case only; Check Eligibility again → Eligible (flag kept).
  Another case of the same unit escalates again.
* When an earlier stage stops the check, the escalation indicator is removed and open escalation
  activities are closed; flag / count keep the value of the last check that reached 3.5.

## Stage 3.6a decisions - Warranty Case approval (approved 2026-10-20)

| ID | Topic | Approved resolution |
|---|---|---|
| Q38 | Eligibility Checked → Approved | Separate **Approve Case** action, only for result Eligible; eligibility revalidated first; then Status Approved, Result Eligible. |
| Q39 | Approvers | **Additional business decision (SRS silent):** company setting **Warranty Case Approval Users** (Warranty Settings), active internal users of the company. |
| Q40 | Self-approval | **Additional business decision (SRS silent):** the case creator and the user who ran the latest eligibility check cannot approve. |
| Q41 | Revalidation at Service Job confirmation | Part 4. |
| Q42 | Draft Service Job cancelled | Part 4: case stays Approved, services not consumed. |
| Q43 | Approval activities | **Additional business decision (SRS silent):** one To-Do per allowed approver when a check gives Eligible; synchronised on every Eligible check (obsolete / now excluded closed, new approvers added, valid kept, no duplicates); closed on approval, when the result is no longer Eligible or the revalidation fails; history in the chatter. |

### Implementation (stage 3.6a)

* Case fields: Eligibility Checked By (latest checker), Approved By, Approval Date, case approval
  activities; button **Approve Case**; filters Waiting for Approval / Approved.
* Approve Case checks the **current** approver list of the case company and Q40 server-side,
  then reruns the checks of 3.2-3.5 (`_warranty_run_checks`, sudo, context
  `warranty_revalidation`): the payment waiver and repeated failure confirmation of the case
  stay valid; payment approval / escalation requests are **not** created ("run Check
  Eligibility"). Failed: not approved, Eligibility Result updated (indicators, flag and count are
  only updated by Check Eligibility), approval activities closed, chatter, warning
  notification. Passed: Status Approved, Approved By / Date, activities closed, chatter.
* Approved cases: Check Eligibility, linked free service changes and deletion are refused (as
  for every status after Eligibility Checked). No Service Job / Field Service task; cards,
  units and free services unchanged.

## Stage 3.6b decisions - Claim rejection (approved 2026-10-20)

| ID | Topic | Approved resolution |
|---|---|---|
| Q44 | Who rejects | Current **Warranty Case Approval Users** of the case company, not the case creator nor the latest eligibility checker (same rule as Q40). |
| Q45 | Rejectable results | Status Eligibility Checked with result **Not Eligible, Out of Warranty, Manual Review** (not Eligible, Partial, Pending Payment). |
| Q46 | Reasons | Fixed list: Serial Mismatch, Out of Warranty, Not Covered / Excluded, No Free Service Available, Customer / Site Mismatch, Duplicate Complaint, Other; note required for Other. |
| Q47 | Helpdesk ticket | Unchanged (closed by the team's own process). |
| Q48 | Linked free services | Released: no active case any more (rule C), Helpdesk Ticket of the service re-synchronised, status unchanged, not consumed; the case link is kept as history. |

### Implementation (stage 3.6b)

* **Reject Case** button → wizard (reason, note) → status **Rejected**; Rejection Reason / Note,
  Rejected By / Date; open case approval, payment approval and escalation activities closed;
  chatter "Warranty case rejected by X: reason" with the note and the released services.
* A Rejected case is **final**: no field can be changed (chatter / activities only), no check,
  approval, second rejection or deletion. Not counted as a repeated failure (3.5).
* Filter **Rejected**. No customer notification.
* 3.6c (approved design, not implemented yet): Convert to Chargeable (status Chargeable, Q49
  Chargeable Type, original case type kept), inspection configuration on the Helpdesk team (Q50),
  product on coverage items (Q51), no automatic customer email (Q52), partial coverage in one case
  with item-level excluded items and explicit customer decisions (Q53a-d, Q55-Q57), several
  quotations per case (Q54), quantities only on the quotation (Q58 A); no Service Job from
  quotations (Part 4 Job Trigger).

## Stage 3.6c decisions - Chargeable conversion and partial coverage (approved 2026-10-20)

| ID | Topic | Approved resolution |
|---|---|---|
| Q49 | Conversion | Status **Chargeable** + **Chargeable Type** (Inspection / Repair / Excluded Items); original case type kept. |
| Q50 | Inspection configuration | Helpdesk team: Inspection Required, Inspection Product, Inspection Amount (SRS Helpdesk interface). Job Trigger: Part 4. |
| Q51 | Excluded item products | Product on the Coverage Item. |
| Q52 | Customer notification | None automatic; the user sends the quotation with the standard Send button. |
| Q53a | Partial coverage | One case, item-level: Excluded Items list with a customer decision per item; Partial is never converted to Chargeable. |
| Q53b | Covered work | Continues only after the customer decided on **all** excluded items (SRS scenario 19). |
| Q53c | Declined | Explicit **Customer Declined** only; declined items are never in a Service Job. |
| Q53d | Changes after approval | No automatic status change; revalidation at Service Job confirmation (Part 4). |
| Q54 | Quotations | Several per case (Quotations smart button). |
| Q55 | Customer Declined | Helpdesk users, reason required, user / date / reason in the history. |
| Q56 | Undo Decline | Before the case is Approved; back to Quotation Required; never added to an existing order automatically. |
| Q57 | Confirmed quantity reduced (> 0) | Still Customer Approved, for the confirmed quantity. |
| Q58 | Quantities | Option A: only on the quotation (Quoted / Confirmed Qty shown on the case); nothing beyond the confirmed quantity is approved. |

### Implementation (stage 3.6c)

* Model `warranty.case.excluded.item` (case, coverage item, product, quotation lines, Customer
  Decision, Quoted / Confirmed Qty, declined / reason / by / date). Decision: Declined (stored,
  explicit) > Approved (linked line on a confirmed order, qty > 0) > Waiting (Draft / Sent line)
  > Quotation Required (no line, line deleted, qty 0, quotation cancelled internally).
* `sale.order.warranty_case_id`, `sale.order.line.warranty_case_id` /
  `warranty_excluded_item_id`: set only by the case actions, read-only; constraint: same case,
  at most one active (not cancelled) line per excluded item.
* Coverage check (3.4) for Partial: syncs the Excluded Items list; any item Quotation Required /
  Waiting → Partial ("proceed only after approval", banner on the case); all Approved /
  Declined → covered items continue (free service, repeated failure, Eligible, 3.6a approval);
  the excluded items stay chargeable (policy unchanged). Only excluded → Not Eligible (unchanged).
* **Create Excluded Items Quotation** (Partial, Helpdesk user with Sales rights): Draft quotation
  for the commercial customer (delivery = case site), lines for the items still Quotation
  Required; items without product → error (set the coverage item product or decline).
* **Customer Declined** (case Excluded Items list or quotation header "Customer Declined
  (Warranty)"): reason required; removes the item's lines from Draft / Sent quotations (sudo,
  only these lines) and cancels a quotation left without lines; refused on a confirmed order.
  **Undo Decline** while Eligibility Checked / Chargeable.
* **Convert to Chargeable** (Helpdesk users; results Not Eligible / Out of Warranty / Manual
  Review, or New Chargeable Inspection / Repair cases): wizard with Chargeable Type (default from
  the case type, excluded items or team inspection); Draft quotation with the inspection line
  (team product, amount) and, for Excluded Items, the excluded requested items; Sales rights
  needed only when a quotation is created; approval / payment / escalation activities closed.
* No Service Job / Field Service task from quotations (creation or confirmation).
* Accepted with the 3.6c approval: Convert to Chargeable by Helpdesk users (quotations need
  Sales rights); free services stay linked to Chargeable cases (rule C).
* Clarification during implementation (accepted): quotation lines need a product in Odoo 18 and manual
  lines are never linked (clarification 2), so excluded items without a product cannot be
  quoted automatically: the user sets the product on the coverage item or records Customer
  Declined.

## Warranty Card selection fix (approved 2026-10-22)

* Manual selection on the Warranty Case form: Warranty Card = Confirmed, case company, customer
  (commercial, child_of), product (card product or a unit product: multi-product cards), serial
  (a unit holding it: unit / kit Indoor / Outdoor serials). Unit Warranty = units of the
  selected card (else of the customer's confirmed cards), product and serial. Choices refresh
  with customer / product / serial / company; on-change clears a no longer matching card / unit.
* Server-side `_check_manual_card_unit` on card / unit writes (UI and API). Not applied in
  superuser mode only (server code; no context flag, clients can send any context): the Part
  3.2 automatic lookup records the found card that way, including Draft / Expired cards for the
  Q8 / Q14 results.
* Create Warranty Case wizard: no card field (approved). Existing cards / cases not changed; the
  rule runs only when card / unit is set or changed.

## Cross-Warranty-Card Service Merge (approved Option A, D1-D8, UI 1-4; 2026-10-23)

Business case: a corporate customer with 8 AC units at one site, each with its own warranty card
and free service, serviced together: one ticket, one case, one job, one visit, 8 worksheets,
each service consumed once on its own card. Cards and worksheet answers are never merged.

* Option A: one warranty case links free services of several cards of the same customer
  (company, site). The case's Warranty Card stays the primary card (D5); new searchable
  **Service Cards** (case) and **Warranty Cards** (job).
* D1: every participating card is checked (customer / company, confirmed, warranty period of the
  selected units, site, units selected); any failure blocks the case and is named as
  "card (services): reason"; nothing is excluded silently. Payment: each card's sale invoices
  with its own policy's Payment Check Required; strictest Overdue Claim Handling of the
  policies; the case waiver covers the case.
* D2: linked free services and Units to Service can be changed in New and Eligibility Checked;
  a change in Eligibility Checked resets the case to New (approval and payment approval To-Dos
  closed, logged); after Approved: refused.
* D3 (BA-approved interpretation of SRS 2.5 "feasible date window" / G3, not an SRS formula):
  window = earliest Alert Date (due date - the card's Service Due Alert Days), else the Due
  Date; latest = Grace Period End (due date + the card's Grace Period Days), else the Due Date
  (from the card values, also when monitoring is off); services without due date (usage-based)
  have no window. The windows of the selected services must overlap and not end before today
  (eligibility and Prepare Service Job); the planned visit date (company warranty timezone)
  must be inside every window (Plan Job, Confirm Service Job, Plan Next Visit). **Revised 2026-10-29 (user approval):** the due date / window is a target, not a planning restriction - a planned date outside a window is accepted at Plan Job, Confirm Service Job and Plan Next Visit (also service-origin jobs) and logged as a non-blocking Service date note; the overlap / not-ended rule for case eligibility and service selection, sequence, status, balance, validity, eligibility, payment and approval checks are unchanged; due dates unchanged. Service-level
  reasons; nothing removed silently. No Early Service Days setting.
  **Revised 2026-10-29 (cross-card merge clarification, user approval):** the windows need NOT overlap - compatible free services of different cards (same customer, company, site, eligibility) are merged into one job and one visit whatever their due dates; a service whose permitted service dates ended before today is still refused; Enforce Service Sequence (same card) unchanged; Draft Job from Service joins with the same rules (dates + sequence).
* D4: free services stay card-level (Part 2 unchanged). **Units to Service** on the case:
  single-unit cards automatically, multi-unit cards all units by default, the Helpdesk user
  removes the units that do not need maintenance. One worksheet per (free service x selected
  unit) with its service, card, unit, product and serial; unselected units get none. Each
  card-level free service is consumed **once** at completion, whatever the number of its units;
  every worksheet is validated (4.7). **Per-unit allowance / consumption needs a separate Part 2
  business approval and design.**
* D6: same site = same address record, or same commercial customer with the identical
  normalized address (street, street 2, ZIP, city - case / spaces ignored - state, country);
  otherwise **Confirm Same Site** by a Helpdesk manager (backend check), reason required, this
  case only, never another customer / company; user, date, addresses and reason stored and
  logged; it resets a checked case.
* D7: duplicate selection refused (one active case per free service, one open job); company /
  customer access unchanged.
* D8: requested items checked against the policy of every participating card; a card without
  policy or an item classified differently -> Manual Review naming the items and cards; the
  Partial / Excluded Items flow is unchanged.
* UI: ticket **Pending Services** button (list of the site's pending services with units and
  window, multi-select -> **Create Warranty Case**); Create Warranty Case window **Add All
  Pending** + units column; case Service Cards, Units to Service, linked services with units and
  window, Confirm Same Site; job Warranty Cards, worksheets with service / card / unit / serial.
* Limitation: a usage-based card that is not the case's primary card needs a case of its own
  (Manual Review), because the case holds one usage reading.
* Tests: earlier test classes run with the D3 date checks switched off
  (check_service_windows = False) because they merge services of different due dates; the D3
  rules are tested in test_service_job_multicard.

## Part 4.11 interaction (2026-10-24)

* Q24 unchanged for manual cases. Automatic cases of Draft Job from Service get the Requested
  Items of the policy field **Automatic Case Requested Items** (approved resolution); empty ->
  Manual Review "No Requested Items".
* Extension point `_warranty_after_eligibility_check(result, steps)` called after each Check
  Eligibility (no behaviour change in Part 3).


## Confirm Same Site - nothing to confirm (approved fix, 2026-10-24)

* Confirm Same Site opens only when a linked card's delivery address does not match the case
  site yet; otherwise: "All service addresses of <case> already match the case site <site>: no
  same-site confirmation is needed." (message only, D6 rules unchanged).

## Flexible Service Dates (BA-approved enhancement F1-F10 / K1-K8, 2026-10-24)

**Status:** BA-approved enhancement of the original SRS. The early-service rules are a BA
interpretation of SRS 2.5 "feasible date window"; the Late Service Exception after the Grace
Period End is **not an original SRS requirement** (SRS p.62: Grace Period End = "last acceptable
date"; SRS scenario 23: expiry after the grace period). SRS validation table "Service due within
grace period - Warn/block based on policy" is implemented as Late Service Handling.

* Policy (copied to the card at warranty confirmation, `_snapshot_free_service_values`):
  **Early Service Rule** (From Alert Date / Days Before Due / Any Date; empty = standard rules),
  **Early Service Days**, **Late Service Handling** (Block / Manager Approval after Grace Period
  End), **Enforce Service Sequence** (default on). Cards confirmed before: empty rule -> standard
  D3 (planning from the Alert Date) and Part 2 (scheduling from today) unchanged; sequence off.
* Permitted service dates (`warranty.service.entitlement._warranty_allowed_range`): earliest =
  Alert Date / due - days / warranty start (never before the warranty start); latest = Grace
  Period End, or the later approved Late Service Exception date. Used by Part 2 Schedule /
  Reschedule (K2), Check Eligibility and Prepare Service Job (common permitted date; also for a
  single service), Plan Job / Confirm / Plan Next Visit, Complete Visit and batch completion
  (F9 / K4: the actual completion date must be permitted; earlier is blocked, later needs an
  approved exception before the consumption). Due Dates are never changed.
* F4: after the due date within the grace period: allowed, "Service date note" on the job at Plan
  Job and at completion.
* F3 / K7 (Enforce Service Sequence): free services of one card are never in one case / job;
  service N needs the previous services of the card Completed / Expired / Cancelled - at Check
  Eligibility and Prepare Service Job unless the previous service is on another open job, at
  Complete Visit (single and batch) always.
* Late Service Exception (`warranty.service.date.exception`, menu Warranty > Late Service
  Exceptions): Request Late Service Exception (Helpdesk users; free service, case or job):
  requested latest date after the current latest permitted date, from today, never after the
  card's Warranty End Date (F6), mandatory reason, one open request per service; To-Dos to the
  approvers due on the Grace Period End (K6, no duplicates). Approvers: company setting **Late
  Service Exception Approvers** (Helpdesk managers of the company), empty = all Helpdesk managers
  of the company; never the requester or the Draft Job Automation User (K5, server-side).
  Approve / Reject (reason) / Cancel; records cannot be edited or deleted (Python marker);
  notes on the request, free service, card and case; multi-company record rule.
* F7 / F8 / K3 / K6: an approved exception keeps the service available (Pending Services,
  eligibility, Prepare, planning, completion) and protects it from the Part 2 expiry until its
  date; a request alone grants nothing and does not stop the expiry - when the service expires
  first, the request is closed "Not Approved before Expiry" and logged; Expired stays final.
* K8: the Part 4.11 automatic draft job keeps the Alert Date trigger (`_warranty_alert_window`).
* Requirement 4: Job Creation Date (create date), Planned Date, **Actual Completion Date** (new,
  job and visit, set at Complete Visit; empty on historical records), Free Service Due Date.
* Limitations: no early-date exception (re-plan instead); an exception date of a multi-unit card
  is limited by the card's Warranty End Date; usage-based services have no date rules; a request
  does not stop the expiry (managers must decide before the Grace Period End).
* Tests: `warranty_management_fsm/tests/test_flexible_service_dates.py` (10 tests); earlier test
  fixtures keep Enforce Service Sequence off (helpdesk TestWarrantyCase policy).

## Late Service Exception request groups (approved G1-G7, H5-A, 2026-10-24)

* Request Late Service Exception selects **several free services** (Many2many): from a service
  job or warranty case all eligible services are preselected (Manager Approval policy, open, no
  open request) and can be deselected; from a free service only that service. One common
  requested latest date and mandatory reason.
* `warranty.service.date.exception.group` (menu Warranty > Service Date Exceptions > Exception Requests): one request,
  one `warranty.service.date.exception` per service (per-service audit, expiry protection, date
  and completion checks unchanged). All-or-nothing: every service checked on its own (policy,
  status, its own latest date / Grace Period End, its card's Warranty End Date, open requests),
  one company and customer; any problem -> nothing created, every failing service named.
* One To-Do per approver on the request (due on the earliest Grace Period End), none on the
  service records. Approve All / Reject (reason) / Cancel on the request: authorized Helpdesk
  managers of the company, never the requester or the Draft Job Automation User; every record
  re-checked at approval (status, service open, date not passed, warranty end, policy) - any
  failure -> nothing decided; decisions in one savepoint. Grouped records cannot be decided one
  by one (a request of one service is decided through its record too).
* H5-A: a member expiring before approval -> it is Not Approved before Expiry, the request
  becomes Partly Expired, cannot be approved; the approvers get one To-Do "Reject or cancel";
  rejecting / cancelling keeps the expired member and closes the others, which can then be
  requested again. Request status derived from its records (Requested / Partly Expired /
  Expired before Approval / Approved / Rejected / Cancelled).
* Records created before the request groups (no request) keep their own Approve / Reject /
  Cancel. Requests and records cannot be created, edited or deleted directly (Python marker);
  multi-company record rules on both.
* Tests: test_flexible_service_dates 211-216.


## Is Warranty on Helpdesk tickets (user request 2026-10-29, 18.0.1.0.3)

* `helpdesk.ticket.is_warranty` (default off, tracked) after the customer; the existing Warranty
  tab is shown only when ticked; unticking never deletes cases or links (Warranty Cases smart
  button stays).
* Available Warranty Cards: Confirmed cards of the customer (commercial entity) in the ticket
  company, searched with the user's record rules; Product choices limited to their products when
  ticked; customer / company change clears the previous product / serial / site.
* Create Warranty Case (same button / wizard / workflow): shown and accepted on the server
  (button method and wizard) only with Is Warranty, a customer and at least one confirmed card.
  Eligibility, approval, duplicate and permission rules unchanged. Creating any warranty case
  (also from Pending Services) ticks Is Warranty on its ticket.
* Migration: tickets with a warranty case or Warranty tab data (site / product / serial) are
  ticked (18_4: 4 of 30 tickets); others stay unticked.
* Consequence: a warranty case can no longer be opened for a customer without any confirmed card
  (the "no card" / "draft card" Manual Review outcomes now need another confirmed card of the
  customer). Tests adapted accordingly (`_unrelated_card`).

## Site Address on Helpdesk tickets (user request 2026-10-29, 18.0.1.0.4)

* `helpdesk.ticket.warranty_site_address` (Char "Site Address", typed freely) in the Warranty tab;
  informational only – never used for free service matching, eligibility or case data.
* `warranty_site_id` unchanged in model / database and logic (pending-service site filter,
  site constraint, customer-change reset, case / wizard default site, Draft Job from Service
  sets it automatically); only hidden on the ticket form (kept there as an invisible field). The
  case keeps its own editable Site for the same-site rules.

## Automatic warranty expiry (approved 2026-11-04, 18.0.1.1.7)

* SRS 9.13, 13, 14: the daily job moves ended cards and units to Expired. Q14 is unchanged: an Expired
  card gives **Not Eligible**.
* **Effect on Q10:** Q14 is checked before the ticket date. A ticket created while the warranty was
  valid but first checked after the card expired gets Not Eligible, approved as decision A. A stored
  result is not rewritten; only a new Check Eligibility run changes it, and that run is logged.
* A ticket created after the end date, before the job has run, gets Out of Warranty; after the job
  it gets Not Eligible. Both allow rejection, chargeable conversion and Goodwill.
* Decision B: tickets and the manual card and unit lists also offer Expired cards, so a customer with
  only expired cards reaches Q14, SRS 12 #9 and Goodwill. Eligibility is not bypassed.

## Kit serials in the serial lists (Part 7 Stage 2 UAT fix, approved 2026-11-03, 18.0.1.1.6)

* A kit delivery moves the components, so the Indoor / Outdoor serials belong to the component
  products. The Serial No. lists of the ticket, Create Warranty Case wizard and case offered only
  serials of the selected product: with the kit as product, no kit serial could be chosen.
* The three lists also offer `_warranty_unit_serials`: the serials on the customer's units of that
  product in the company, same search as `_warranty_find_card` (any card state: the eligibility
  check gives the Draft / Expired result). The serials of the product itself stay offered.
* The ticket product change clears the serial only when the list no longer offers it; an empty
  product still clears it. `_warranty_find_card` and the eligibility checks did not change.
* Tests: `warranty_management_repair/tests/test_kit_serial_link.py` (a real kit delivery needs
  `warranty_management_mrp`, which this module does not depend on).
* Known, not changed: `_onchange_warranty_partner` clears the product and serial on every customer
  change, even when the new customer has that product (real id compared with the new-record ids
  of the x2many in an onchange). It clears too much, never too little.
