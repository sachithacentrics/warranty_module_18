# Part 6.1 – Repair Intake + Standard Repair Order Integration – Detailed Design

| Item | Value |
|---|---|
| Status | **Implemented 2026-11-02 (18.0.1.0.0). Not installed on any database and never run; only static syntax checks.** Manual UAT by the user is pending. See §12. |
| Scope | Phase 1 only. Backup Unit, Damage / Loss Billing, reporting and unit-level history are later phases. |
| Module | New `warranty_management_repair` (Part 6). `material_purchase_requisitions`, AMC modules and standard Odoo files are not changed. |
| Decisions applied | User 2026-11-02: D1 parts through the MRF, D2 narrow workshop-only completion, D3 trigger authorizes the repair. |
| Verification | Code reading and read-only queries only. Nothing was run: see §9. |

## 1. Sources: SRS versus implementation decision

| Topic | SRS states | SRS is silent on | Implementation decision |
|---|---|---|---|
| Intake | §2.9: "Helpdesk/Service Job initiates a reverse transfer from Customer to Warranty Repair Intake and creates a serial-aware Repair Order" | Which screen | Standard ticket Return and Repair buttons (§3) |
| Repair Order content | §2.9: product, serial, under-warranty status, parts, notes, responsible, scheduled date, result | Result values | Standard fields + `warranty_repair_result` (BA-2) |
| Repair status | §9.13: Draft → Confirmed → Under Repair → Repaired → Returned / Cancelled | How Returned is held | Computed; no new standard state |
| Parts | §2.10: MRF linked to Helpdesk, Job, Task and/or Repair Order; §13 threshold approval | How MRF and Repair Order parts avoid double counting | D1 (§4) |
| Field Service | §2.9: optional for pickup / delivery | – | Existing job and visit flows only |
| Blockers | §2.5, §13: no open MRF / repair blockers at completion | – | `_warranty_completion_blockers` (§7) |
| Blocked visit | §2.8: the next visit can stay unscheduled until the blocking record is ready | – | Existing Incomplete reason "Workshop Repair Required" + a To-Do |
| Completion | §9.7 step 9: "Completed repair is invoiced and closed" | Completion without a job | D2 (§5). K6 is a project rule, not SRS |
| Chargeable trigger | §2.6, §2.11: team trigger, SO Confirmation or Payment; §9.7 step 4 creates the inspection job | Any repair job; workshop behaviour | D3 (§6). C12 is a project rule, not SRS |

## 2. Verification required by Decision 1

**Question:** does blocking Repair Order part lines break standard completion or stock accounting?
**Answer from code reading: no, for `add` lines. `recycle` must also be blocked.** A runtime check is still required (§9, V1).

| Check | Evidence | Result |
|---|---|---|
| Confirm with no parts | `_action_repair_confirm` acts on an empty `move_ids` | Works |
| Parts status | `_compute_parts_availability`: no moves stays Available | Works |
| End Repair button | `has_uncomplete_moves` False: the normal button shows | Works |
| Done with no parts | `action_repair_done`: `all()` on no moves is True; `consume_line_ids` is empty; only the product move is created | Works; serial still required |
| Product move value | Standard default has source = destination (`_compute_default_product_location_id`). Internal → internal is neither in nor out (`stock_account/stock_move.py:129`) | No valuation entry |
| `add` line value | Would consume from stock to Production: this is the duplicate to prevent | Blocked by D1 |
| `recycle` line | Production → stock: counts as stock **in**, adding value and saleable stock | Must be blocked |
| `remove` line | Production → Scrap: neither valued location | No value; allowed (BA-5) |
| Quotation lines | `_create_repair_sale_order_line` only uses `add` moves | Nothing created |
| Traceability | `consume_line_ids` empty: parts are not on the Repair Order's lot trace | Known limit: the MRF moves carry the part trace |
| Standard test coverage | `repair/tests/test_repair.py` scenarios read all use parts | Not confirmed by a standard test: V1 needed |

**MRF without a job (case-only):**

| Check | Evidence | Result |
|---|---|---|
| Create on Approved / Chargeable case | `_warranty_mrf_check_allowed`, `MRF_CASE_STATES`; job and task optional; 2 such MRFs on live | Supported |
| Record usage | `_warranty_open(mrf, mode)` takes the job from the MRF, which may be empty | Supported by reading |
| Access | `_warranty_has_material_access('record')`: coordinator or store | Supported |
| Open check | `_warranty_material_open_error`: an empty job is not "closed" | Supported |
| Reconcile check | `_warranty_material_problems()` is per MRF | Reusable for D2 |
| Cost | `_compute_actual_cost` reads MRF consumption only | One cost source |
| Parts quotation | `action_create_parts_quotation` links the case **after** create, so it gets no purpose (T4.6) | Cannot trigger a job |

## 3. Workflow with standard screens

1. **Return (ticket Return button, standard wizard).** New checkbox **Warranty Repair Intake**, on by default for warranty tickets. The return goes to the company Intake location with `to_refund` off.
2. **Receive (standard receipt).** The user enters the serial. The existing `_warranty_log_returns` logs it on the card; warranty dates do not change.
3. **Repair Order (ticket Repair button, standard form).** Prefilled with case, product, serial and return.
4. **Parts:** existing Create Material Request on the case or job. The new MRF links itself to the open Repair Order. Approval, issue, usage and returns are unchanged.
5. **Repair:** standard Confirm → Start → End, with the guards in §7.
6. **Return to customer (standard Return button on the receipt).** `to_refund` stays off. Validation marks the Repair Order Returned.
7. **Completion:** job-controlled when a job is open; otherwise **Complete Warranty Case** on the Repair Order (§5).

Only one new button is added to a workflow: Complete Warranty Case. No wizard is added.

## 4. Decision 1 – parts

* A Repair Order linked to a warranty case takes parts only through the MRF. This applies to warranty and chargeable cases.
* `stock.move` constraint: `add` and `recycle` lines are refused when `repair_id.warranty_case_id` is set. `remove` is allowed (BA-5).
* A Repair Order cannot be linked to a case while it holds active `add` or `recycle` lines.
* The Repair Order shows linked MRF lines read-only, using the same columns as the job's Materials list. Nothing is issued or consumed from this list.
* Repair Orders with no case behave exactly as standard.
* An MRF created before the Repair Order stays unlinked and is not displayed, but D2 still counts it.

## 5. Decision 2 – workshop-only completion

`repair.order.action_warranty_complete_case()` lists every problem at once and completes the case only when:

1. the Repair Order is Repaired and the equipment has been returned;
2. every other non-cancelled Repair Order of the case is also returned;
3. the case has **no open Service Job**;
4. no linked free service is pending: all are Completed, Cancelled or Expired;
5. `_warranty_material_problems()` is empty for **every** MRF of the case;
6. the case is Approved or Chargeable (type Repair) and has a Case Type;
7. the result is not Not Repairable (BA-2).

The write follows `_warranty_decline_repair`: `sudo()` with `warranty_completion_marker=_COMPLETION_MARKER`. Chargeable cases get outcome `repair_completed`. The K6 guard is not changed. The case stops at Completed; Closed stays in Part 8.

When a job is open, completion stays with that job and the button is refused. An open repair blocks completion through `_warranty_completion_blockers`.

## 6. Decision 3 – chargeable trigger

* **Linked Repair Order:** the existing trigger rule (`_warranty_trigger_orders`) authorizes **Start Repair**. No repair job is created.
* **No linked Repair Order:** the existing Chargeable Repair job is created, unchanged.
* The change applies only to `warranty_chargeable_purpose == 'repair'`. Inspection and excluded-items jobs are unchanged.
* **Figure 4 is unchanged:** `_warranty_check_chargeable_trigger`, `_warranty_inspection_gate`, `_warranty_trigger_case_job` and the inspection quotation are not overridden.
* The order must be linked before the quotation meets the trigger. If a job already exists, it stays in control and the repair is a blocker on it.
* Invoices stay manual. The inspection-fee adjustment stays in Part 8.

## 7. Exact changes

### 7.1 Module

| File | Content |
|---|---|
| `__manifest__.py` | depends: `warranty_management_mrf`, `warranty_management_mrp`, `helpdesk_repair`. The `mrp` dependency makes the allocation filter run before the kit logic |
| `models/res_company.py`, `res_config_settings.py` | Intake location setting |
| `models/repair_order.py` | §7.3 |
| `models/stock_move.py`, `stock_picking.py` | §7.2, §7.4 |
| `wizard/stock_picking_return.py` | §7.2 |
| `models/warranty_case.py`, `warranty_service_job.py` | §7.5 |
| `models/material_purchase_requisition.py` | §7.6 |
| `models/sale_order.py` | §7.5 |
| `models/helpdesk_ticket.py` | §7.3 |
| `views/*.xml` | §7.7 |
| `tests/Part6_Manual_Testing_Guide.md` | Manual guide |

No new model and no ACL file. No data records: the user creates the Intake location in standard Inventory.

### 7.2 Intake and customer return

| Object | Method / field | Change | Protects |
|---|---|---|---|
| `res.company` | `warranty_repair_intake_location_id` | Internal, same company, `warehouse_id` empty (constraint), so outside the WH view | Saleable stock (`product.py:292`) |
| `stock.return.picking` | `warranty_repair_intake` Boolean | Default from `ticket_id.is_warranty`; can be unticked for a genuine customer return | Scope |
| `stock.return.picking` | `_prepare_picking_default_values()` | When ticked: destination = Intake; sets the picking flag; error if no location is set | Location |
| `stock.return.picking.line` | `_prepare_move_default_values()` | `to_refund = False` when the wizard is ticked **or** the move being returned belongs to an intake picking | Delivered qty, both directions (`sale_order_line.py:354-356`) |
| `stock.picking` | `warranty_repair_intake` Boolean | Readonly, `copy=False` | Identification |
| `stock.picking` | `_warranty_allocate_sale_line()` | Removes moves whose `origin_returned_move_id.picking_id` is an intake picking, then `super()` | Unit allocation |
| `stock.picking` | `_action_done()` | After `super()`: history notes; To-Dos when equipment is received or returned | History |

The customer-return wizard needs no other change: the standard code already sends a return of a receipt from Intake to the customer location.

### 7.3 `repair.order` and ticket

| Method / field | Change |
|---|---|
| `warranty_case_id` | Many2one, tracked, `check_company`; ticket's cases only; refused on Rejected / Closed / Completed cases |
| `warranty_service_job_id` | Stored compute: the case's latest non-cancelled job, excluding both inspection types |
| `warranty_card_id`, `warranty_unit_id` | Related from the case |
| `warranty_repair_result` | Selection Repaired / No Fault Found / Not Repairable (BA-2) |
| `warranty_equipment_returned` | Stored compute: a done move from `picking_id.move_ids.returned_move_ids` to a customer location with the same serial |
| `warranty_intake_state` | Stored compute: Awaiting Receipt, Received, Under Repair, Repaired, Returned, Cancelled. Returned takes priority |
| `warranty_mrf_ids` | One2many to the MRF link |
| `warranty_mrf_line_ids` | Many2many compute, `sudo` read of lines, like `_compute_warranty_materials` |
| `_compute_product_location_src_id`, `_compute_product_location_dest_id` | `super()`; intake return: use its destination. Otherwise a repaired unit would move to WH/Stock |
| `_warranty_repair_serial_problems()` | Serial must equal the case serial or a serial of the case unit |
| `_warranty_repair_start_problems()` | See below |
| `action_validate()` | Linked order: return done, serial correct. Also refuses when the ticket has an active case and none is chosen |
| `action_repair_start()` | Calls `_warranty_repair_start_problems()`; syncs `under_warranty` from the case. Refused after the equipment is returned |
| `action_repair_done()` | Linked order: result required. Then `super()`, history note, To-Do on the job |
| `action_create_sale_order()` | Linked order: only Chargeable (Repair) cases; adds `default_warranty_case_id` so the existing create hook sets the purpose |
| `create()`, `write()` | History note on case link; links an open Final Repair Quotation |
| `action_warranty_complete_case()` | §5 |
| `helpdesk.ticket._prepare_repairs_default_value()` | `super()`; warranty ticket: **removes `default_sale_order_id`**; falls back to warranty product and serial; defaults the single active case; prefers the latest done intake return |

`_warranty_repair_start_problems()`:

* no Case Type: refused;
* Chargeable: type must be Repair and `case._warranty_trigger_orders()` must not be empty;
* otherwise: same rule as Prepare Service Job (Approved / Job Created / In Progress, Eligible);
* `_warranty_inspection_gate()` true and trigger not met: refused (BA-6).

Ticket 62 / WH/RO/00005 (draft, warranty ticket, SO 36, no case) has no case, so the guards do not apply. Its link to SO 36 is existing data and is not changed.

### 7.4 `stock.move`

`_check_warranty_repair_parts` (`@api.constrains('repair_id', 'repair_line_type')`): §4. It also covers the catalog, which creates moves.

### 7.5 Existing workflow overrides

Each override checks for a linked Repair Order first. With none, it only calls `super()`.

| Method | Change |
|---|---|
| `warranty.case.warranty_repair_ids`, count | New; stat button on the case |
| `warranty.case._warranty_active_repairs()` | New: non-cancelled linked orders |
| `warranty.case._warranty_create_chargeable_job(order, origin)` | Purpose Repair + active repair + no existing job: log and return an empty recordset. `_warranty_check_chargeable_trigger` already handles empty |
| `warranty.case._warranty_prepare_chargeable_job()` | Same condition: clear message. Otherwise the fallback would open an empty job |
| `warranty.case._warranty_check_decline_repair()` | `super()`; refuses when a repair is Under Repair or Repaired |
| `warranty.case._warranty_decline_repair(reason)` | `super()`; cancels open repairs; To-Do to return the equipment |
| `warranty.service.job._warranty_completion_blockers()` | `super()` + repairs not returned; **not** for `chargeable_inspection` / `warranty_inspection` jobs |
| `sale.order.create()` | `super()`; Purpose Repair: links to an open repair without an order. No change to purpose rules |

Not overridden: `action_prepare_service_job`, `_warranty_create_case_job`, `_warranty_set_hold`, `_warranty_complete_visit`, `_warranty_complete_case`, `_warranty_create_repair_quotation`, `_warranty_trigger_met`, `warranty.case.write`.

### 7.6 MRF (bridge only)

| Method / field | Change |
|---|---|
| `material.purchase.requisition.warranty_repair_id` | Many2one, readonly, `copy=False`; SRS §2.10, D14 |
| `create()` | `super()`; when the case has exactly one open repair, links it |
| `_check_warranty_repair_link` | Repair Order must belong to the same case |

No change to approval, issue, consumption, cost, claims or closure.

### 7.7 Views

| View | Change |
|---|---|
| `stock.view_stock_return_picking_form` | Checkbox, visible when `ticket_id` is set |
| `repair.view_repair_order_form` | Case, job, card, unit, result, intake status; page Material Requests (read-only); Complete Warranty Case button; catalog button hidden when linked |
| Warranty case form | Repairs stat button |
| Warranty Settings | Intake location with plain-English help |

## 8. BA-dependent rules

Phase 1 uses the default until the BA decides. Each default is the most conservative option.

| # | Question | Phase 1 default |
|---|---|---|
| BA-1 | Machine with no Odoo delivery (no return possible) | Not supported on linked Repair Orders: Confirm refused |
| BA-2 | Result values; what follows Not Repairable | Three values; Not Repairable can't complete the case. Replacement out of scope |
| BA-3 | Customer machine ownership and inventory value | No owner, like a standard return. While in Intake it counts in stock valuation (`_get_in_move_lines`); valuation is Manual, so no journal entry. Accounting to confirm |
| BA-4 | Chargeable parts through the MRF | Existing Part 5.4: separate parts quotation, delivered to the customer location, then recorded as installed. The delivery doesn't match the part physically going to the workshop, and the customer gets two quotations |
| BA-5 | Old / defective part recovery | Standard `remove` allowed, no value. No vendor-return logistics |
| BA-6 | Workshop repair on a case with Inspection Required | Start waits for the existing trigger; the trigger then creates the existing job, which controls completion |
| BA-7 | Inspection done in the workshop | Not supported: §9.7 step 4 and Figure 4 keep the Field Service inspection |
| BA-8 | Intake start point | SRS names Helpdesk / Service Job; design uses the ticket's buttons, reached from the case or job. Confirm this is acceptable |

## 9. Checks not yet run (each needs approval)

| # | Check on `wt_p5_mrf` |
|---|---|
| V1 | Repair Order with no parts: Confirm, Start, End; stock and valuation records unchanged except the serial's location |
| V2 | MRF on a case with no job: approve, issue, record usage, reconcile, cost |
| V3 | Kit (Indoor / Outdoor) serial: return, repair and re-delivery of one component |
| V4 | Delivered qty, invoice status, warranty dates and unit allocation identical before and after return + re-delivery, including a line with undelivered units |
| V5 | Intake location outside the WH view on Receipts: validation and on-hand figures |

## 10. Acceptance tests (not to be run without approval)

| ID | Scenario |
|---|---|
| R-01 | Warranty ticket: return to Intake; SO delivered qty unchanged; card log written; dates unchanged |
| R-02 | Checkbox unticked: standard return, `to_refund` on, standard destination |
| R-03 | Repair Order prefilled; no link to the ticket's original Sales Order |
| R-04 | Confirm refused before receipt; wrong serial; case not chosen |
| R-05 | `add` / `recycle` refused (form and catalog); `remove` allowed |
| R-06 | MRF links itself and displays; no second consumption; cost counted once |
| R-07 | Done without parts; result required; serial stays in Intake, never WH/Stock |
| R-08 | Return to customer: delivered qty unchanged; no unit re-allocated; Returned shown |
| R-09 | Completion: each of the §5 conditions fails separately, then passes |
| R-10 | Job linked: repair blocks Complete Visit and batch; Incomplete still works; job completes after return |
| R-11 | Inspection jobs not blocked by a repair |
| R-12 | Chargeable + repair: trigger (both modes) allows Start, no job; without repair: job as today |
| R-13 | Decline: repair cancelled; refused when Under Repair |
| R-14 | Figure 4 route: quotation, trigger and job unchanged |
| R-15 | Repair Order with no case: fully standard |
| R-16 | Regression of Part 3–5 chargeable, completion and MRF classes |

`warranty_management_mrf/tests/test_settings_help.py:20` expects 39 settings. The new setting makes it 40, so that assertion must be updated when the module is installed.

## 11. Deployment

The module is new, so it needs an explicit install. The PyCharm `-u` list will not install it. Normal procedure: fresh backup, test-restore, trial on a copy, compare, then coordinate with the user.

## 12. Implementation notes (2026-11-02)

Differences from §7, found while coding:

| Topic | As built | Why |
|---|---|---|
| Catalog button | **Not hidden**; pressing it and adding a product is refused by the constraint, and an alert on the Parts page explains the rule | Odoo 18 `list_renderer.xml` renders `<control>` buttons with no `invisible` support |
| Material Requests page | Limited to Helpdesk and Requisition users | The vendor record rule shows other users only their own requests, so the list would raise an access error |
| Repair To-Dos | All on the Repair Order, closing the previous step | One mechanism; nothing added to the job's To-Dos |
| Sales Order on a linked order | New constraint: it must be a quotation of the same case | Stops an order already linked to the customer's original Sales Order from being linked to a case (for example WH/RO/00005) |
| Replace / Exchange on the return wizard | Refused when Warranty Repair Intake is ticked | Added; an exchange would create a new outgoing move |
| Intake return source | Must be a delivery to a customer location | Added |
| Manifest | No security file | No new model |

Not done, as decided: the MRF form does not show `warranty_repair_id`; a chargeable workshop repair has no pickup / delivery job path, because the Job Trigger creates none and Prepare Service Job is refused (raise with the BA).

Not changed: `warranty_management_mrf/tests/test_settings_help.py:20` still expects 39 settings, so it fails on any database where this module is installed until it reads 40.
