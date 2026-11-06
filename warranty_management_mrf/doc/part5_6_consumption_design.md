# Phase 5.6 – Actual Consumption and Unused Returns – Design (revision 2, approved)

| Status | Revision 2 **approved 2026-10-27, implemented** (18.0.1.6.0) on the disposable database; see `part5_design_decisions.md` Phase 5.6 for the implementation notes. |
|---|---|
| Module | `warranty_management_mrf` only (inheritance); `material_purchase_requisitions`, Parts 1–4, AMC unchanged |
| Database | disposable `wt_p5_mrf` only |

User decisions of 2026-10-27 (revision 1 review): workflow accepted (Issue -> Record Actual
Consumption -> Return Unused -> Reconcile -> Complete Service Job -> Close MRF); E-1, E-3, E-8
accepted; E-12 accepted with authorization, mandatory reason and audit; E-13 accepted, Draft /
Rejected to be reviewed, Incomplete / Reschedule preserved; E-15 accepted for warranty visits only;
E-7 to be clarified (delivery is not installation).

## 1. Sources

SRS §2.5 (batch completion validates "worksheets, usage, materials, repair blockers"), §2.8
(Incomplete jobs and rescheduling), §2.10 b5 – b8 (quotation before issue; "Unused parts are
returned and actual consumption is reconciled. Serial/lot tracking is retained"; actual cost from
stock valuation), §2.13 (history and audit), §9.6 steps 5 – 9, §9.8 (Parts MRF flow), §9.13 (MRF
stages "… Partially Issued/Issued -> Returned -> Closed/Rejected"), §10.5 (*Parts Required* on the
job card), §10.7 (*Unused Return Picking*, *Actual Cost* "returns unused parts and reconciles actual
consumption"), §12 scenario 14 (customer returns) and 16 (parts out of stock), §13 validations
(batch completion "no open MRF/repair blockers"), §15 reports, §16 roles (Technician, Store User)
and audit trail, §17 accounting ("Warranty part consumption: capture inventory cost against
warranty case"). Mapping §5.6 and D10, D11, D16, D18.

## 2. Facts checked (read-only)

| Fact | Consequence |
|---|---|
| `_warranty_completion_blockers()` (Part 4) is used by Complete Visit (4.7), Batch Complete (4.9) and the visit-closure guard for `1_done`. | One extension point blocks every completion path. |
| Incomplete / Reschedule (4.8) closes the visit as `1_canceled` without that hook. | Incomplete / Reschedule is never blocked by material requests. |
| Issued parts sit in the request's destination (technician van / Technician Stock), shared by the technician's jobs. | Per-line limit **and** stock check at the location. |
| Not Covered lines leave the company by the quotation delivery (5.4 D8: WH/Stock -> Customer). | Delivery = change of ownership, not installation (E-7). |
| Product categories: costing **Standard Price**, valuation **Manual (periodic)** (company default on `wt_p5_mrf`; no category-specific setting on `warranty_management_18_4` either). `stock_account` installed. | See section 5. |
| Part 4 does not use the Field Service *Products* button; `industry_fsm_stock` / `industry_fsm_sale` installed. | E-15 only affects warranty visits. |

## 3. Workflow

```
Issued to technician location (5.5)
  -> Record Used Parts (visit / job / request)   technician location -> Warranty Consumption
  -> Return Unused (rest)                        technician location -> source, validated by Store
  -> line reconciled: issued = used + returned (+ on an open return)
  -> Not Covered lines: delivered = installed + resolved (customer keeps / customer return)
  -> job completion allowed (4.7 / 4.9)          Incomplete / Reschedule always allowed
  -> request Returned / Closed
```

## 4. Decision table

| ID | Proposed functionality | Recommended option | SRS reference | Impact on the existing workflow |
|---|---|---|---|---|
| **E-1** ✔ | Who records consumption / returns | Technicians **of the job** (main / support, Field Service users) on the visit or job; Service Coordinator (Helpdesk user of the company) and Store (Requisition / Inventory user) on the request. Checks in code, records written by the workflow after the check (no write access granted on requests); user, date and notes stored; notes on request, case, job. | §9.6 step 5, §16 roles, §16 audit trail, §2.13 | New buttons only; technicians keep read-only access to requests. |
| **E-2** | Record Used Parts | Wizard listing the issued, not yet used / returned lines of the job's warranty requests (one row per line: *Quantity Used*, serials, notes). One consumption record per line and entry (request line, request, job, visit, product, qty, UoM, serials, notes, user, date, stock move); the move technician location -> Warranty Consumption is validated at once. Mistakes: **Reverse Consumption** (coordinator / store, reason; reverse move), never deleted. | §2.10 b6, §9.13, §10.7 Actual Cost | New stock moves out of the technician location; 5.5 issue pickings unchanged. |
| **E-3** ✔ | Quantity limits | ≤ issued − used − returned − on open returns of the line, **and** ≤ stock available at the technician location (no negative stock). | §2.10 b6, §13 | If another job used the van stock, the store must transfer stock first. |
| **E-4** | Consumption location | One virtual location **Warranty Consumption** per company (type *Inventory Loss*), created at install / for new companies, selectable in Warranty settings. | §2.10 b7, §17 | New location; no existing location changed; shows in standard inventory reports. |
| **E-5** | Accounting (D11 a) | Keep manual valuation; the consumption creates a stock valuation layer (quantity and cost) per case / job; no journal entry. Automatic expense / provision posting only if the company switches spare-part categories to automated valuation (5.7 / Part 8). Details: section 5. | §2.10 b7 / b8, §17 | No accounting change; inventory value decreases at consumption. |
| **E-6** | Serial / lot | Used and returned serials / lots must be among those issued **for that line** and not yet used / returned; serial-tracked: one serial per unit. Kept on the consumption record and the moves. | §2.10 b6, §10.7 | Serial-tracked parts require the serial when used / returned. |
| **E-7** (revised) | Not Covered lines (customer-paid parts) | **Delivery and installation are tracked separately.** The quotation delivery (5.4) stays the stock movement / change of ownership; the technician additionally records **Installed** quantity and serials with Record Used Parts (no second stock move – the part already left the company). A delivered but not installed quantity needs a **resolution** with reason: *Customer keeps the part* or *Customer return* (standard sales return + credit note by Sales). Reconciled when delivered = installed + resolved. | §2.10 b5 / b6, §10.7 Customer Quotation / Invoice, §12 scenario 14 | 5.4 delivery and payment rules unchanged; new installation / resolution columns on Not Covered lines; such lines also take part in E-13. Alternative b: route chargeable parts through the technician location (changes approved 5.4 D8). Alternative c: delivery = consumption (rejected by the user). |
| **E-8** ✔ | Return Unused | Action on request / job: remaining quantity per line (default, editable), serials, reason -> **one internal transfer** technician location -> request source location, linked to request / case / job, flagged *Unused Return*; created by technicians of the job, coordinator or store; **validated by Inventory users (Store)** only. Several returns possible. | §2.10 b6, §9.13 Returned, §10.7 Unused Return Picking | New return transfers; stock back in the warehouse. |
| **E-9** | Confirm Full Consumption | Button (visit / request): records all remaining issued quantities as used (lot-tracked: the remaining issued lots), after confirmation. | §2.10 b6 | Optional shortcut. |
| **E-10** | Line reconciliation | Per issued line: Used, Returned (validated), In Return (open return), To Reconcile = issued − used − returned − in return; status Open / Return Pending / Reconciled (Not Covered lines: Installed / Resolved per E-7). | §2.10 b6, §10.7 | New read-only columns. |
| **E-11** | Request status | `warranty_mrf_status` adds **Returned** (a return validated, nothing left to reconcile) and **Closed** (all lines reconciled, no open issue / return transfer, no outstanding approved quantity). Computed. Vendor *Received* unchanged / optional. | §9.13 | Two statuses after Issued; filters / lists show them. |
| **E-12** ✔ (conditions) | Cancel Remaining | Cancels the approved quantity not yet issued (or not delivered for Not Covered lines not yet quoted). **Authorized:** requester, creator, Requisition Manager or Store (Requisition + Inventory user) of the company. **Reason mandatory.** Stored per line (cancelled qty, user, date, reason) and logged on request, case and job. Refused while the quantity is on an open issue transfer / RFQ (cancel those first) or invoiced / delivered to the customer (use the sales return). Approval history unchanged. | §9.13, §13, §16 audit trail | Lets a job finish without an unneeded part; nothing else changes. |
| **E-13** ✔ (revised) | Completion blocker | Extend `_warranty_completion_blockers()`: block while a request **linked to the job** is **Draft** or **Rejected** (materials asked for but never resolved – submit it or cancel it with a reason), waiting for approval, approved / picking created with outstanding quantity, partially issued, has lines to reconcile, or Not Covered lines waiting customer / payment / delivery / installation resolution. Not blocking: Cancelled, Returned, Closed, *Return Pending* (only the store validation is left), Customer Declined lines, requests linked only to the case. One message per request with its lines and what is missing. Incomplete / Reschedule never blocked. **Sub-decision E-13b:** to clear a Draft / Rejected request the coordinator (Helpdesk user) may also cancel it with a reason (today only requester / creator, 5.3 Q6); and Cancel of warranty requests always asks for a reason. | §2.5, §2.8, §9.6 step 9, §13 batch completion "no open MRF/repair blockers" | Complete Visit / Batch Complete show new reasons; Part 4 checks unchanged; Draft / Rejected requests must be submitted or cancelled before completion. |
| **E-14** | Material history | Job: tab **Materials** (all lines of its warranty requests: requested, approved, issued, used / installed, returned, cancelled, to reconcile, status) + consumption records; visit: its consumption records. Read-only; notes for every consumption, return, reversal and cancellation. | §2.13, §10.5 Parts Required, §15 | New read-only tab. |
| **E-15** ✔ | Field Service *Products* on warranty visits | On tasks with a warranty service job only: hide the *Products* button and refuse adding products from the task server-side, so the Material Request is the only parts path. Ordinary Field Service tasks unchanged (bridge depends on the installed `industry_fsm_stock`). | §9.6 step 5, §9.8 | Warranty visits lose the standard Products button (unused by Part 4); standalone tasks unchanged. |

✔ = accepted by the user (with the conditions shown).

## 5. Inventory and accounting with manual (periodic) valuation

Verified: costing **Standard Price**, valuation **Manual**. In Odoo 18 a stock move gets a stock
valuation layer (SVL) when it leaves or enters the company's valued (internal) locations; with
manual valuation no journal entry is posted for moves.

| Movement | Locations | Inventory effect | Valuation layer | Journal entry (manual) |
|---|---|---|---|---|
| Issue (5.5) | WH/Stock -> Van 1 (internal -> internal) | Quantity moves, total on hand unchanged | none | none |
| **Consumption (5.6)** | Van 1 -> **Warranty Consumption** (Inventory Loss) | On hand decreases | **out**: −qty × standard price, linked to the move (case / job via the consumption record) | none |
| Reverse consumption | Warranty Consumption -> Van 1 | On hand increases | **in**: +qty × standard price | none |
| Return unused | Van 1 -> WH/Stock | Quantity moves | none | none |
| Not Covered delivery (5.4) | WH/Stock -> Customers | On hand decreases | out (cost of goods sold value) | none for the move; the customer invoice posts revenue / receivable |
| Purchase receipt (5.5) | Vendors -> WH/Stock | On hand increases | in | none for the move; the vendor bill posts to the category's **expense** account |

Consequences:

* 5.6 records **exact quantities and cost values** of warranty consumption per case / job (data for
  the 5.7 cost reports), and the stock valuation report shows the decrease.
* With manual valuation the general ledger does **not** show a separate "warranty expense" for
  consumption: purchases are expensed when the vendor bill is posted, and the accountant adjusts
  inventory periodically. If warranty consumption must appear in the accounts automatically, the
  spare-part categories have to use **Automated** valuation; then the consumption move posts
  Dr Warranty Expense (or Provision) / Cr Stock Valuation, using the accounts set on the Warranty
  Consumption location. That is a company accounting decision for 5.7 / Part 8 (D11 b); 5.6 works
  the same way in both cases.
* A dedicated location keeps warranty consumption separate from inventory adjustments and scrap in
  the reports and allows the account mapping later without changing 5.6.
* Standard price: the layer uses the cost at the moment of consumption; later cost changes do not
  change recorded consumption.

## 6. Model outline

* `warranty.mrf.consumption` (new): request line, request, job, visit, product, qty, UoM, serials,
  notes, user, date, kind (Used / Installed / Customer keeps / Customer return), stock move, state
  Done / Reversed (+ reversal move, reason).
* Request line (+): used / installed, returned, in return, resolved, cancelled qty (+ by / date /
  reason), to reconcile, reconcile state. Request (+): statuses Returned / Closed, actions.
* Company (+): consumption location. Picking (+): *Unused Return* flag (existing request links).
* Job (+): Materials tab, blocker extension. Task (+): consumption list, buttons, Products hidden
  on warranty visits.

## 7. Tests (planned)

T6.1 limits (line and location stock); T6.2 serials; T6.3 Return Unused (links, store validation
only); T6.4 reconciliation states, Returned / Closed; T6.5 Complete Visit / Batch Complete blocked
(Draft, Rejected, open, unreconciled, Not Covered unresolved) and allowed after; Incomplete /
Reschedule not blocked; T6.6 Confirm Full Consumption; T6.7 Cancel Remaining (authorization,
reason, audit, refusals); T6.8 Reverse Consumption; T6.9 access; T6.10 Not Covered installation /
resolution; T6.11 Products hidden / refused on warranty visits only; T6.12 valuation layers of
consumption / reversal (no journal entry with manual valuation); T6.13 standalone requests and
standalone Field Service tasks unchanged; full regression.
