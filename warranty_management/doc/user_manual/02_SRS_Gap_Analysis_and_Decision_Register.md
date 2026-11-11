# Warranty Management – SRS Gap Analysis and Implementation Decision Register

Version 0.2 – 11 November 2026 – for the user's decision. **Nothing in this register is approved for implementation yet.**

> **v0.2 corrections (after code research; details in `03_Gap_Review_Phase_I_Design.md`):**
> (1) G-18 and G-24 are **not** approved deviations: they are pending decisions BD-23 and BD-24 (user instruction).
> (2) G-20: an open Damaged / Lost backup unit does **not** block Close Case (only Issued / Overdue / open issue transfer / found-but-not-returned do).
> (3) G-22: a lost issued part already blocks **job completion** and every completion path, not only closure.
> (4) G-21(c): the component replacement PDF is already regenerated in code (user decision "Component as built"); only the R5 record needs confirming.
> (5) 16 further pending decisions were found in the decision records (BD-23 … BD-38).

Basis: `01_SRS_Coverage_Matrix.md` v0.2 (142 rows), the SRS (81 pages, 22 diagrams), current code (= UAT versions of 11 Nov 2026) and the decision records in each module's `doc/` folder. Read-only analysis: no code, database or AMC file was changed.

## 0. How the gaps are counted

The matrix has 45 rows that are not fully implemented: 40 Partial and 5 Gap. Row H04a moved from Doc to Partial after a new finding, G-30, so v0.1's 39 Partial rows are now 40. Many rows share one root cause; for example, customer notification affects five rows. The register therefore lists **unique gaps**, and section 9 maps each matrix row to its gap ID.

| Class | Unique items | IDs |
|---|---|---|
| A. Completely missing features | 5 | G-01, G-05, G-06, G-07, G-08 |
| B. Partially implemented features | 21 | G-02, G-03, G-04, G-09, G-10, G-11, G-12, G-13, G-14, G-15, G-16, G-17, G-19, G-20, G-21, G-22, G-23, G-25, G-26, G-27, G-30 |
| C. Approved deviations from the SRS | 17 | DV-01 … DV-17 (G-18 and G-24 reclassified here, see C) |
| D. Pending business decisions | 22 | BD-01 … BD-22 (includes G-28 and G-29, which are Finance set-up rather than development) |
| E. Excluded from scope | 4 | EX-01 … EX-04 |
| F. UI text defects (not SRS gaps) | 3 | TX-01 … TX-03 |

**Workflow blocker** = a branch of an SRS figure cannot reach its end in the system today. Blockers are marked **⛔**.

**Priority** (recommended):
- **Critical**: blocks an SRS workflow branch.
- **High**: an SRS 12.1 minimum must-have, or a financial or customer-facing correctness issue.
- **Medium**: an SRS feature with a workaround.
- **Low**: convenience or reporting.

**Status:** every gap is *Not started*. Verification of every gap is *Not verified*.

---

## A. Completely missing features

### Fig 4 / 9.7 – Chargeable inspection

#### G-08 ⛔ Customer declines the inspection quotation
| Field | Value |
|---|---|
| SRS reference | 9.7 diagram ("Customer Approves? No → Close Request"); Fig 4; 2.11 |
| Expected | When the customer does not accept the inspection quotation, the request is closed with a reason; no job is created |
| Current | No action exists. The case stays *Approved* (Fig 4 route) or *Chargeable* with a draft quotation. **Close Case** needs *Completed*, and **Reject Case** is only possible from *Eligibility Checked*, so the case cannot be closed |
| Missing | A "Customer Declined Inspection" action: cancel the draft inspection quotation, record a reason, close the case, and optionally close the ticket (see G-15) |
| Business impact | Cases stay open indefinitely; dashboards and approvals are overstated; no audit of the refusal |
| Modules | warranty_management_helpdesk, warranty_management_fsm, warranty_management_accounting (close guard) |
| Approach (standard first) | Reuse the existing "Record Customer Declined" wizard of the chargeable flow; cancel the quotation with the standard `sale.order` Cancel; reuse the existing case close / outcome fields ("Inspection Only …" outcomes already exist) |
| Priority | **Critical** |
| Business decision | Yes: the final case status (Closed vs Rejected) and whether a reason list is required (part4 "Fig 4 ambiguity") |
| Status | Not started / not verified |

### 2.4 / 12 #13 – Extended warranty

#### G-01 ⛔ Extended warranty product line
| Field | Value |
|---|---|
| SRS reference | 2.4 (all bullets), 2.14 #9, 12 #13, 14 "Extended warranty product line confirmed / paid" |
| Expected | A service product on the Sales Order extends identified unit warranties. It has an extension period, included free services, a start rule (after the original warranty or a commercial trigger) and an overlap warning / approval, and it stays linked to the SO line and invoice |
| Current | Not implemented. Only the controlled action **Request Warranty Change > Extend Warranty** exists (manual, approval, links a quotation or invoice) |
| Missing | Product flag + configuration, allocation of the SO line to card / unit lines, a trigger on confirmation or payment, an extension record, draft free services, an overlap check |
| Business impact | Paid extensions are entered manually by an approver; no automatic link to revenue; risk of unallocated extension lines |
| Modules | warranty_management (product, card, units), warranty_management_accounting (if provision / revenue treatment is needed) |
| Approach | Standard service product + SO line. Reuse the existing Extend Warranty controlled action as the engine (it already writes the history and before / after dates). Reuse the existing free-service generator for the included services |
| Priority | High (SRS 2.4 / 14; not in the 12.1 must-have list) |
| Business decision | **Yes**: Q21 (build now or defer) and **Finance Q23** (revenue and provision treatment) before design |
| Dependencies | Finance Q23; uses G-25 extension rules (Q22 maximum) |
| Status | Not started |

### 12 #11 – Project warranty

#### G-05 Project warranty (parent / child cards, bulk visits)
| Field | Value |
|---|---|
| SRS reference | 12 #11 |
| Expected | A parent project warranty / contract with child unit cards, bulk visit scheduling and failure tracking per unit |
| Current | Not implemented as a parent / child structure. Existing substitutes: one card per Sales Order with many unit warranty numbers; merged Service Jobs across cards; shared Field Service visit for several jobs; repeated failure per unit |
| Missing | A parent record grouping cards of one project / site, and a bulk-visit action |
| Business impact | Project customers (e.g. 100 A/C units in a hotel) are handled as one large card or several cards without a project view |
| Modules | warranty_management, warranty_management_fsm |
| Approach | Least custom: use the standard **Project** or an analytic tag / partner site as the grouping key with a filter and group-by, plus the existing merge / shared-visit wizard. Only build a parent model if reporting needs it |
| Priority | Low (not a 12.1 must-have; substitutes exist) |
| Business decision | Yes: accept the existing multi-unit card + merged jobs as the project solution, or build a parent grouping |
| Status | Not started |

### 6 / 12 #20–21 – SLA and escalation

#### G-06 Warranty SLA rules
| Field | Value |
|---|---|
| SRS reference | 6 (SLA and Escalation Rules menu), 12 #20, 2.6 ("Helpdesk SLA … reused") |
| Expected | Response / resolution times by customer type, policy, priority and AMC; breach tracking and escalation |
| Current | No warranty SLA. Standard Helpdesk SLA Policies exist but are not configured for warranty teams and are not shown on the case or job. The case has a Priority field copied from the ticket |
| Missing | SLA configuration for warranty teams; SLA deadline / status visible on the case; breach escalation |
| Business impact | No measurable service commitment (SRS 12 #20) |
| Modules | Configuration of standard `helpdesk` SLA; small view change in warranty_management_helpdesk |
| Approach | **Standard first**: configure Helpdesk > Configuration > SLA Policies per warranty team / priority / tag (customer type = pricelist tag). Show the ticket's SLA deadline and status as related fields on the case. Breach escalation uses standard SLA failure + activities |
| Priority | Medium |
| Business decision | Yes: SLA targets per customer type / priority |
| Dependencies | Related to G-07 (same escalation recipients) |
| Status | Not started |

#### G-07 Escalation of unresolved jobs
| Field | Value |
|---|---|
| SRS reference | 12 #21, 6 ("unresolved job escalation") |
| Expected | A scheduled action finds jobs open more than N days (example 5) and creates a manager / GM activity |
| Current | Not implemented (only repeated-failure escalation exists) |
| Missing | Company setting "Unresolved Job Escalation Days" + escalation users; daily scheduled action; activity |
| Business impact | Stuck jobs are not visible to management |
| Modules | warranty_management_fsm |
| Approach | Standard `ir.cron` + `mail.activity`, reusing the existing escalation-user pattern (Repeated Failure Escalation Users); optional dashboard Escalations line |
| Priority | Medium |
| Business decision | Yes: threshold days, recipients, which job states count |
| Status | Not started |

---

## B. Partially implemented features

### B1. Fig 1 / Fig 2 / 9.3 – Sales Order and warranty card

#### G-16 Sales Order smart buttons
| Field | Value |
|---|---|
| SRS | 2.3 last bullet, 6 "Sales – Warranty Smart Buttons", 2.14 #8 |
| Expected | From the SO: Warranty Cards, Unit Warranty Numbers, Services, Helpdesk Tickets, Service Jobs |
| Current | Warranty Cards, Unit Warranties, Warranty History |
| Missing | Services, Helpdesk Tickets, Service Jobs buttons |
| Impact | Extra navigation; low |
| Modules | warranty_management (services), warranty_management_helpdesk (tickets), warranty_management_fsm (jobs) |
| Approach | Standard `oe_stat_button`s with counts through the existing card links |
| Priority | Low · Decision: No · Status: Not started |

#### G-03 Pending Payment status and activation on payment
| Field | Value |
|---|---|
| SRS | 12 #2, 14 "Invoice paid → Active", 10.2 status list, 9.3 last step |
| Expected | The card can be created and marked Pending Payment; it moves to Active when the invoice is paid |
| Current | Policy "Payment Check Required": the card stays Draft with "Invoice payment" missing, and the user clicks Confirm Warranty after payment. No Pending Payment status, no automatic activation. Case eligibility also has a payment check (H06) |
| Missing | Pending Payment status (or label) and automatic activation on payment |
| Impact | Revenue protection works; status naming and automation differ from the SRS (12.1 must-have "activation based on … payment" is met functionally) |
| Modules | warranty_management (card), standard `account` payment state |
| Approach | Use the standard invoice `payment_state`; add a computed status / filter, or auto-confirm when it reaches paid (like the installation auto-confirm) |
| Priority | Medium · Decision: **Yes, Q26** (A keep check / B add status) · Status: Not started |

#### G-27 Card statuses and filters
| Field | Value |
|---|---|
| SRS | 9.13, 10.2 |
| Expected | Card statuses include Pending Payment and Voided; status filters |
| Current | Draft, Pending Installation, Ready to Confirm, Confirmed, Suspended, Expired, Cancelled; the card search has no Suspended / Cancelled filter |
| Missing | Statuses depend on G-02 / G-03; two search filters |
| Priority | Low · Decision: through G-02 / G-03 · Dependencies: G-02, G-03 · Status: Not started |

### B2. 9.10 – Warranty card output

#### G-04 Card sharing by WhatsApp and portal
| Field | Value |
|---|---|
| SRS | 9.3 step 11, 9.10 step 3, 10.8 "Shared With Customer", 11 #7, 1.2 |
| Expected | Soft copy shared by email, WhatsApp link or portal; updated copy shared after replacement |
| Current | **Send to Customer** (email) and **Download PDF** (with download approval, duplicate / updated copy marks). No portal page, no WhatsApp. **Generate Updated Card** on the replacement regenerates but does not send |
| Missing | Portal access; WhatsApp channel; send after replacement |
| Impact | Customers cannot fetch their card themselves; the SRS default channel set is incomplete |
| Modules | warranty_management, warranty_management_repair |
| Approach | Standard **portal.mixin** + the standard **Share** wizard (portal link); WhatsApp only through Odoo's **WhatsApp** app (Enterprise, licence to check) using a template on the card; reuse Send to Customer after Generate Updated Card |
| Priority | Medium · Decision: Yes (which channels; WhatsApp licence) · Status: Not started |

### B3. Fig 3 / 9.4 – Free services

#### G-11 Task creation method and usage-based draft jobs
| Field | Value |
|---|---|
| SRS | 7 "Task Creation Method", 9.4 diagram (Immediate / X days / Manual), 2.2 usage |
| Expected | Choose Immediate, X days before due, or Manual; usage services also produce jobs / alerts |
| Current | "X days before" = Draft Job from Service at the alert date; Manual = Create Service Job. **Immediate is not offered** (decision E1: no jobs at confirmation; SRS 19 also recommends not creating all future tasks). **Usage-based services never get a draft job** (E9, recorded as pending) |
| Missing | Usage-based draft job; (Immediate only if the business wants it) |
| Impact | Usage warranties rely on the usage alert To-Do only |
| Modules | warranty_management_fsm |
| Approach | Reuse the existing draft-job generator, triggered by the existing usage alert |
| Priority | Medium (usage); Low (Immediate) · Decision: Yes (keep Immediate excluded per E1?) · Status: Not started |

#### G-12 Carry-forward of missed services
| Field | Value |
|---|---|
| SRS | 12 #6, #23 |
| Expected | Configurable carry-forward of a missed / expired free service |
| Current | Grace period, Missed, auto-expire implemented; carry-forward field hidden ("rules not implemented"). **Late Service Exception** (BA enhancement) lets an approver allow a late service |
| Missing | A carry-forward rule |
| Impact | Low: the Late Service Exception gives a controlled substitute |
| Approach | Either accept the Late Service Exception as the carry-forward mechanism (recommended) or add a policy option that moves the remaining service to the next period |
| Priority | Low · Decision: **Yes** (accept substitute?) · Status: Not started |

#### G-17 Kanban view for services
| Field | Value |
|---|---|
| SRS | 2.5 "list, kanban, calendar, pivot / graph" |
| Current | List, form, calendar; pivot / graph in reports |
| Missing | Kanban by status |
| Approach | Standard kanban view on `warranty.service.entitlement` grouped by state |
| Priority | Low · Decision: No · Status: Not started |

### B4. Fig 4 / 9.5 / Suppl. Fig 2 – Helpdesk, case and eligibility

#### G-30 ⛔ "Warranty card not found" branch for customers without any card (new finding)
| Field | Value |
|---|---|
| SRS | 9.5 row 1 ("Warranty card found? No → create chargeable inspection or manual review"), Suppl. Fig 2, Suppl. Fig 1 (not eligible → chargeable inspection) |
| Expected | A request from a customer with no warranty card can still go through Helpdesk to a chargeable inspection or manual review |
| Current | **Create Warranty Case** is refused when the customer has no Confirmed (or Expired) card (`warranty_management_helpdesk/models/helpdesk_ticket.py:167`). "Card not found → Manual Review" is reachable only when the customer has another card |
| Missing | A case without a card, of type Chargeable Inspection / Chargeable Repair, using the existing inspection quotation route |
| Impact | Non-warranty customers cannot use the warranty chargeable-inspection process; the Rs. 850 inspection flow (SRS 1.1, 9.7) is unavailable to them |
| Modules | warranty_management_helpdesk, warranty_management_fsm |
| Approach | Allow case creation without a card only for chargeable case types; reuse the existing inspection quotation, job trigger and fee adjustment |
| Priority | **Critical** · Decision: Yes (allow cardless chargeable cases?) · Verification: confirm in the UI on `wt_manual` · Status: Not started |

#### G-26 Detection of an existing ticket / case for the same unit
| Field | Value |
|---|---|
| SRS | 9.5 last row, 13 (duplicate prevention spirit), 2.6 |
| Expected | The ticket / case shows when the same serial already has an open ticket / case |
| Current | Only one open case per free service (rule C) and the "Duplicate Complaint" rejection reason |
| Missing | A warning banner / smart button with open cases and tickets for the same serial |
| Approach | Computed field + banner on ticket and case (no new model) |
| Priority | Medium · Decision: No · Status: Not started |

#### G-09 Inspection fee when an eligible case proceeds after an inspection quotation
| Field | Value |
|---|---|
| SRS | Fig 4 ("Customer proceeds with final repair? Yes → credit note against posted inspection invoice, or discount if not posted"), 2.11, 17 |
| Expected | The inspection fee is credited or deducted whenever the customer proceeds |
| Current | **Apply Inspection Fee Adjustment** works for the chargeable inspection → repair route. For an **eligible** warranty case (Fig 4 route: Inspection Required on the team) there is no rule; the demo case WCAS/000050 was charged 1,500 |
| Missing | The fee rule on the eligible-case route |
| Impact | Possible overcharge / customer dispute (financial correctness) |
| Modules | warranty_management_accounting, warranty_management_fsm |
| Approach | Extend the existing adjustment conditions (no new accounting flow; draft credit note or deduction line as today) |
| Priority | High · Decision: **Yes** (is a covered repair after inspection free, and is the fee refunded?) · Dependencies: decide together with G-08 / G-30 · Status: Not started |

#### G-13 Repeat complaint window and reopen
| Field | Value |
|---|---|
| SRS | 12 #22, 12.1 ("Reopen / repeat complaint handling") |
| Expected | Reopen Case or Repeat Complaint linked to the previous job; configurable repeat window; no extra free service for the same issue |
| Current | **Repeat Complaint** creates a new linked case (one open repeat per case, counts toward repeated failure). No reopen of a closed case (Q25 A chosen); no repeat window (Q24) |
| Missing | Repeat window setting and its warning |
| Modules | warranty_management_helpdesk |
| Approach | Company setting "Repeat Complaint Window (days)" + warning / flag; keep "new linked case" as the only reopen method |
| Priority | Medium · Decision: **Yes, Q24** (window value, "same issue" definition); Q25 recommended A (keep) · Status: Not started |

### B5. Fig 5 / 9.6 / 9.11 – Field Service, closure and notification

#### G-10 Customer notifications
| Field | Value |
|---|---|
| SRS | 2.8 (reschedule notification), 2.11 (notify customer of the inspection quotation), 12 #16, #19, 9.8 step 5, Fig 5 "Notify customer and internal team" |
| Expected | The customer is notified of the inspection quotation, parts quotation, reschedule / next visit and parts backorder |
| Current | Internal To-Do activities only; quotations can be sent manually with the standard Send button (decisions D15 / L4: "outstanding gap") |
| Missing | Customer e-mail templates and send points |
| Impact | Manual communication; SRS Fig 5 branch "notify customer" not met |
| Modules | warranty_management_helpdesk, warranty_management_fsm, warranty_management_mrf |
| Approach | **Standard first**: `mail.template` + standard composer; Helpdesk stage e-mail templates (standard); the Sales quotation **Send by Email** (standard). One small shared helper; no new model |
| Priority | High · Decision: Yes (which events, automatic vs confirm-then-send) · Dependencies: used by G-08, G-04 · Status: Not started |

#### G-14 Closure steps: repeated-failure check and next service
| Field | Value |
|---|---|
| SRS | 9.11 diagram ("Check Repeated Failure Rule", "Calculate Next Service"), 9.6 #9, 4 stage 8 |
| Current | Repeated failure runs at eligibility; the next free service already exists as an entitlement but is not highlighted at closure |
| Missing | Optional re-check at closure; show the next due service in the closure message / card |
| Priority | Low · Decision: No · Status: Not started |

#### G-15 Helpdesk ticket closure
| Field | Value |
|---|---|
| SRS | Fig 6 last step ("Close Helpdesk, Job, Repair and stock history"), 9.11 |
| Current | **Close Case** closes the case; the ticket stays open and is closed manually in Helpdesk (part8_5 known limit) |
| Missing | Ticket moved to a closed (folded) stage when its last case closes |
| Approach | Standard folded Helpdesk stage; optional company setting |
| Priority | Medium · Decision: Yes (automatic, or prompt) · Dependencies: shares the Close Case change with G-14 / G-20 / G-21 / G-22 · Status: Not started |

### B6. Fig 6 – Workshop repair and backup unit

#### G-20 ⛔ (exception branches) Backup damage / loss closure and charges
| Field | Value |
|---|---|
| SRS | Fig 6 ("Backup lost / damaged or chargeable cost? → approval and customer quotation / invoice → close"), 2.9, 17 |
| Current | Report Lost, assessment, approval, draft quotation, Found / Restored / Scrap and Close are implemented (B1–B7, 2026-11-06) |
| Missing | Closing a unit whose charge ended as **Credit Note Issued** or **Quotation Cancelled** (write-off rule) ⛔; recovery of a Lost unit that is already Closed; second damage charge on a recovered unit (B5d); deposit handling (D4); repair / scrap cost link (D9); loan rules (BB-5) |
| Impact | Some backup records can never be closed (no write-off path). *v0.2 correction:* this does **not** block Close Case of the warranty case (only Issued / Overdue units do) |
| Modules | warranty_management_repair, warranty_management_accounting |
| Approach | Standard stock scrap / inventory adjustment (already used); write-off = documented decision + close guard change |
| Priority | High · Decision: **Yes** (D3 remainder, D4, D9, BB-5) · Status: Not started |

### B7. Fig 7 / 9.8 – Material Requests

#### G-22 ⛔ (exception) Lost or damaged spare parts
| Field | Value |
|---|---|
| SRS | 2.10 (unused parts returned, consumption reconciled), Fig 7 |
| Current | Deferred (K-8). An issued part that is lost or damaged cannot be recorded, so the MRF stays not reconciled and blocks case closure |
| Approach | Standard `stock.scrap` from the MRF usage wizard with a reason; cost stays on the case |
| Priority | Medium · Decision: Yes (who bears the cost; approval) · Status: Not started |

### B8. SRS 11 / Suppl. Fig 3 – Replacement

#### G-21 Replacement approvals and completion
| Field | Value |
|---|---|
| SRS | 11, 11.2, 16.1 ("high-value replacement / goodwill = GM + Finance"), Suppl. Fig 3 "Close Case + Report Cost" |
| Current | Six types, approval, transfers, serial checks, five date policies, card update and Generate Updated Card are implemented; case completion for Full / Vendor / Indoor / Outdoor replacement is implemented |
| Missing | (a) ⛔ **Component replacement case completion** (R2, under review): a component-only case has no completion path. (b) "High value" Finance threshold undefined (B1); an empty setting refuses Full Product Submit. (c) Updated PDF for Component replacement (R5). (d) Generate Updated Card has no automated test |
| Priority | (a) **Critical**; (b) Medium; (c) Low · Decision: Yes (R2, B1, R5) · Status: Not started |

### B9. SRS 12 / Suppl. Fig 4 – Controlled actions

#### G-02 Void warranty
| Field | Value |
|---|---|
| SRS | 12 #5, 12.1 ("suspension and voiding with reason and approval"), 10.2 status Voided, Suppl. Fig 4 reasons |
| Current | **Suspend / Reactivate** through Request Warranty Change, with reason list, evidence and approval |
| Missing | Void (permanent invalidation) |
| Impact | 12.1 must-have only half met; a permanent void must be simulated by a suspension |
| Modules | warranty_management (controlled action), helpdesk eligibility (Not Eligible) |
| Approach | Add Void to the existing controlled-action wizard; status per Q7 (A: Voided / B: Cancelled + void reason) |
| Priority | High · Decision: **Yes, Q7 and Q10** · Dependencies: G-27; roles G-19 · Status: Not started |

#### G-25 Controlled-action options still open
| Field | Value |
|---|---|
| SRS | 12 #3, #4, #10, #14, #24 |
| Current | Transfer Ownership (whole card), Relocate Unit (site), Correct Serial / Customer / Usage, Correct Warranty Dates, Return / Refund Cancellation, Extend Warranty |
| Missing | Single-unit transfer (Q18); "free services do not transfer" option (Q19); branch / territory / technician rules on relocation (Q16); policy / product correction (Q13); kit serial correction after confirmation (Q30); free services on cancellation (Q11) |
| Priority | Medium (Q11, Q19, Q30); Low (Q13, Q16, Q18) · Decision: **Yes** for each Q · Status: Not started |

### B10. SRS 16 – Roles

#### G-19 Warranty role groups
| Field | Value |
|---|---|
| SRS | 16 (Warranty User, Coordinator, Technician, Store, Warranty Manager, GM, Accountant, Admin, Warranty Approver, Job Planner, Material Approver, Repair / Backup Coordinator) |
| Current | Standard Odoo groups (Helpdesk, Field Service, Inventory, Accounting, Requisition) + per-company approver lists; one warranty group "Warranty: Date Correction". Warranty Policies / Coverage Items menus have no group restriction. Unconfirmed UAT finding: technicians hold Accounting Manager |
| Missing | Named warranty groups (at least Warranty User / Manager) and menu restrictions |
| Approach | Two or three `res.groups` implying the standard groups; keep approver lists for approvals (Q1) |
| Priority | Medium · Decision: **Yes, Q1** · Status: Not started |

### B11. SRS 15 / 2.13 – Reports and history

#### G-23 Report and history completeness
| Field | Value |
|---|---|
| SRS | 15 key filters, 2.13 history scope |
| Missing | (a) Free Service Due: "customer type" filter. The SRS says pricelists are customer types, so this means a Pricelist filter. (b) Repair and Backup Unit report has no Repair Orders / intake. (c) Helpdesk Pending Service lacks ad-hoc tickets. (d) Warranty History lacks automatic expiry rows, kit-serial correction values, and visit / worksheet events. Brand / model filters are **not** a gap (DV-06 approved exclusion) |
| Approach | Filters / group-bys and one extra report action on standard `repair.order`; for history, track the card status change in the chatter (standard tracking) so the existing SQL history view picks it up |
| Priority | Low (a, c), Medium (b, d) · Decision: No (Q4 history scope is provisional) · Status: Not started |

---

## C. Approved deviations from the SRS (document as built; no development)

| ID | SRS | Approved behaviour | Record |
|---|---|---|---|
| DV-01 | 2.1, 7 scope modes | No scope mode | BA 2026-10-28 |
| DV-02 | 2.3, 14 cards at SO confirmation | **Warranty Grouping** button after confirmation | part2 §8a |
| DV-03 | 2.2, 2.15, 10.1 product + pricelist lines; customer / SO type levels | One policy per pricelist; Pricelist > Product > Category > Company | warranty_policy_resolution D1–D5 |
| DV-04 | 10.1 Calendar Month schedule | Not offered | part2 2026-10-19 |
| DV-05 | 9.5 draft warranty blocks | Manual Review "confirm the warranty" | part3 Q8 |
| DV-06 | 10.1, 10.2, 15 brand / model | **Approved exclusion (user + BA)**: no brand / model policy mapping, eligibility rule or report filter; existing free-text Brand / Model product fields used by the Warranty Cost report stay unchanged and are not policy mapping | user + BA (Q6, 11 Nov 2026) |
| DV-07 | Fig 7 quotation before approval | Quotation after full approval | figure7 D2a |
| DV-08 | 9.8 #6 case Awaiting Parts | Job hold by the user; no automatic case status | figure7 D4 |
| DV-09 | 17 custom warranty cost posting | Standard stock accounting + Finance reserve utilization | user 2026-11-07 |
| DV-10 | 16.1 goodwill GM + Finance; kits | Goodwill without Finance; goodwill / vendor single-serial only | part7 (BA) |
| DV-11 | 15 report menus | Four reports from the dashboard; Unit Warranty Number under Cards | user 2026-11-11 |
| DV-12 | 7 Immediate task creation | No jobs at card confirmation | part4 E1 |
| DV-13 | 2.10 labour etc. in material approval | Warranty Cost lines with their own approval | figure7 D5 |
| DV-14 | 9.4 #9 "unless configured otherwise" | Cancel / reschedule never consume; not configurable | part4 L5 |
| ~~DV-15~~ | 6 configurable Service Types | **Not approved – moved to pending decision BD-23 (G-18)** | – |
| ~~DV-16~~ | 10.3 payment eligibility per service | **Not approved – moved to pending decision BD-24 (G-24)** | part3 Q21 |
| DV-17 | 2.2 Custom Date Range on the policy | Custom range from product / category / company only | start_date_design |

## D. Pending business decisions (implemented behaviour or prerequisites awaiting confirmation)

| ID | Decision | Current behaviour | Linked |
|---|---|---|---|
| BD-01 | Part 4 M3: case status while a job is on hold | Case status unchanged | DV-08 |
| BD-02 | Part 4 C2: "On Payment" = full payment | Full payment required | H07 |
| BD-03 | Part 4 4.9: batch completion completes only passing jobs | Passing jobs completed, others skipped with reasons | J06 |
| BD-04 | DEV-1 Case Coverage Management (frozen coverage per case) | Design only; blocked pending BA | H04e |
| BD-05 | Part 5.1 options D4 / D5 / D10 / D19 / D20 / D22 marked "confirm at review" | Built as proposed | M01 |
| BD-06 | Equal Interval boundary: a service can be due one day after the warranty end | Unchanged | F02 |
| BD-07 | Project-default worksheet fallback (not in SRS 2.7) | Fallback active | C11 |
| BD-08 | Part 9 provisional rules Q1, Q2, Q4, Q5, Q6, Q9, Q15, Q17, Q20, Q22, Q29, Q31 | Built with the provisional rule | S00–S25 |
| BD-09 | Q7 / Q10 void | – | G-02 |
| BD-10 | Q26 pending payment | – | G-03 |
| BD-11 | Q21 / Finance Q23 extended warranty | – | G-01 |
| BD-12 | Q24 / Q25 repeat complaint | – | G-13 |
| BD-13 | Q11, Q13, Q16, Q18, Q19, Q30 controlled actions | – | G-25 |
| BD-14 | Inspection decline and eligible-case fee (Fig 4 ambiguity) | – | G-08, G-09 |
| BD-15 | Cardless chargeable cases | – | G-30 |
| BD-16 | Backup D3 remainder, D4, D9, BB-5 | – | G-20 |
| BD-17 | Replacement R2, B1, R5 | – | G-21 |
| BD-18 | Notification events (D15, L4) | – | G-10 |
| BD-19 | SLA targets; job escalation threshold | – | G-06, G-07 |
| BD-20 | Roles (Q1) | – | G-19 |
| BD-21 | **Finance (former G-28)**: automated stock valuation + Warranty Consumption location accounts so covered parts post warranty cost; UAT uses manual valuation | Configuration, no code | A02 |
| BD-22 | **Finance (former G-29)**: production accounts for provision (F2) and reserve release (F8) | Draft entries only | A01, A03 |

## E. Excluded from scope

| ID | Item | Basis |
|---|---|---|
| EX-01 | Skill / availability based AI technician assignment, Required Skill / Skill Category fields | SRS 1, 2.5, 6, 8 (Phase 2) |
| EX-02 | AMC lifecycle internals (plans, formulas, stages, billing, visit generation, renewals) | SRS 2.1, 2.12 – separate AMC module and AMC User Manual |
| EX-03 | Brand / model warranty functionality | Approved exclusion (DV-06) |
| EX-04 | Odoo Rental for backup units; standard Subscriptions for AMC billing | Optional alternatives in SRS 2.9 / 2.12 |

## F. UI text defects found during the analysis (not SRS gaps; need approval to fix)

| ID | Defect |
|---|---|
| TX-01 | Policy help for **Usage Alert %** still says "Not monitored yet" (usage alerts are implemented) |
| TX-02 | Help for **Draft Job Helpdesk Team** still describes automatic tickets (superseded by decision D-B) |
| TX-03 | `test_13_serial_rules` status is inconsistent across documents (known error vs fixed); re-run on `wt_manual` |

---

## 7. Dependencies between gaps

| Gap | Depends on / shares a change with |
|---|---|
| G-08, G-09, G-30 | One design for the inspection / chargeable route (Fig 4, 9.7, 9.5 row 1); G-10 for the quotation notification |
| G-15, G-14, G-20, G-21a, G-22 | All change the **Close Case** guard / closure step; implement and test together |
| G-02, G-03 → G-27 | New statuses must exist before filters / dashboard |
| G-01 | Finance Q23; reuses the Extend Warranty action (G-25 / Q22) |
| G-10 → G-04 | Notification helper reused to send the updated card |
| G-19 | Approver for Void (G-02), controlled actions (G-25), replacement Finance level (G-21b) |
| G-06, G-07 | Same escalation recipients / SLA configuration |
| G-13 | Affects repeated-failure counting (H13) |
| BD-21, BD-22 | Finance set-up before the accounting chapter (7.20) can be finalised |

## 8. Recommended implementation order

| Phase | Gaps | Why |
|---|---|---|
| I – Workflow blockers | G-08, G-30, G-09 (inspection / chargeable route); G-21a; G-20 write-off; G-22; G-15 (+ G-14) | Every SRS figure branch can reach its end |
| II – SRS 12.1 must-haves and customer communication | G-02 (+ G-27), G-10, G-04, G-13, G-25 (Q11, Q19, Q30) | Minimum must-have controls and the "notify customer" branches |
| III – Operational completeness | G-06, G-07, G-26, G-11 (usage), G-03, G-19 | SLA / escalation, duplicates, roles |
| IV – Convenience and reports | G-16, G-17, G-23, G-12, G-21b/c | Low risk |
| Decision only / defer | G-01 (Finance Q23), G-05 | Business decides whether to build |

Each phase follows the project rules: design first → your approval → build on an isolated test DB → tests → your UAT. No UAT / AMC change and no deployment without separate approval.

## 9. Traceability: matrix row → gap

| Matrix rows | Gap |
|---|---|
| W08, S13 | G-01 |
| S05 | G-02 |
| W09 | G-03 |
| W10, X07 | G-04 (+ G-21 for X07) |
| S11 | G-05 |
| H10, C07 | G-06 (C07 also G-07) |
| J08 | G-07 |
| H08 | G-08 |
| H09 | G-09 |
| F03, H07, J05 (+ M04 note) | G-10 |
| C17, F04 | G-11 (+ DV-12) |
| F06 | G-12 |
| H11 | G-13 |
| J09 | G-14 |
| R08 | G-15 |
| W07 | G-16 |
| F05 | G-17 |
| C06 | DV-15 (former G-18) |
| C15 | G-19 |
| A07, R07 | G-20 |
| X02, X08 (+ X07) | G-21 |
| M07 | G-22 |
| Y01, RP06, RP08, RP15, RP16, RP18 | G-23 |
| F08 | DV-16 (former G-24) |
| S03, S04, S10, S14, S24 | G-25 |
| H04i | G-26 |
| W11 | G-27 |
| H04a | G-30 |

Total: 45 matrix rows (40 Partial + 5 Gap) → 26 unique open gaps (5 missing + 21 partial) + 2 reclassified as approved deviations.
