# Warranty Start Date Automation – Detailed Design

| Item | Value |
|---|---|
| Status | **Approved 2026-10-28 (rev 2: Q1–Q18 decided, Q7 / Q8 changed by the user)** – implementation on `wt_p5_mrf` |
| Modules | `warranty_management` (core), `warranty_management_fsm` (installation); minimal state-list change in `warranty_management_helpdesk` |
| Business decisions | D1–D11 final (user, 2026-10-28), §2 |
| Related | `PROJECT_HANDOFF.md` §5–§7 (analysis), `part2_design_decisions.md`, `warranty_policy_resolution.md` |

Implementation questions and their decisions are in **§16**.

---

## 1. Scope

In scope: how the warranty start date of a card is determined, shown, frozen, protected,
excepted and corrected for the three automated bases (**Delivery**, **Invoice**,
**Installation/Commissioning**), plus the posting-time capture on customer invoices.

Out of scope / unchanged:
* **Custom Date Range** basis (manual start / end in Draft, as today).
* **Usage** warranty basis (no end date; usage limit / unit), free-service usage due.
* Sales Order Warranty Grouping (grouping modes, keys, unit numbering, Per Delivery split).
* Part 4 Service Job / visit completion logic and its completion lock, AMC modules,
  `material_purchase_requisitions`, Part 5 MRF logic.
* Policy resolution (`warranty_policy_resolution.md`) – the card keeps its resolved
  `start_criterion`.
* Existing confirmed cards (WC/00001–00004 on 18_4) – values never changed by the upgrade.

## 2. Final business decisions (user, 2026-10-28)

| # | Decision |
|---|---|
| D1 | Invoice basis: the actual date/time the customer invoice transitions to Posted; never `invoice_date` or the accounting date. |
| D1a | Historical invoices: use a reliable historical posting event only if it can be verified; never guess, never `create_date` / `write_date`. Confirmed cards unchanged; authorized exception process for affected Draft cards. |
| D1b | Reset to Draft + repost: the latest valid posting event of an invoice that is currently Posted; earlier events preserved for audit. |
| D2 | Partial deliveries: actual validated delivery date recorded per unit; card start = latest relevant delivery date once all required units are delivered; never an unrelated delivery. |
| D3 | Multiple invoices: only posted, non-reversed customer invoices containing the warranted products / order lines; down payments and unrelated invoices excluded; units without the invoicing condition never activate. Matching / allocation / partial-invoice rules defined before implementation (§7.2). |
| D4 | Installation tasks identified by the "Warranty Installation Service" product flag and the "Create Installation Task" card button; only correctly linked installation tasks activate; repair / maintenance excluded. |
| D5 | A task may cover several cards of the same Sales Order and site where explicitly linked; each card waits for all its required installation tasks. |
| D6 | Installation cards confirm automatically when all installation tasks are complete and every other validation passed (incl. validated delivery). Delivery / Invoice cards keep manual confirmation; expected start / end shown before confirmation. |
| D7 | Activation event = actual Field Service task completion; if Customer Sign-off Required is enabled, the sign-off requirement must also be met. |
| D8 | Installation without task: only through an authorized, audited exception with mandatory reason. |
| D9 | Dedicated **Warranty: Date Correction** group and controlled correction wizard; confirmed dates protected against UI, import and API. |
| D10 | After an approved correction, recalculate only eligible Draft / Pending entitlements; finalized services kept. |
| D11 | Card chatter records activation, source changes, invoice reversals and authorized corrections with traceable references. |

Additional requirements: company Warranty Timezone everywhere; Installation Date only from
completed installation tasks; source Delivery / Invoice / Task visible on the card; no
automatic change of historical records during upgrades.

## 3. Current implementation (baseline, verified 2026-10-28)

`warranty_management/models/warranty_card.py`:
* `state` is a stored compute (`draft` ↔ `ready` from `_get_missing_requirements()`);
  `action_confirm_warranty()` computes start / end, writes the card and its units
  (`state='active'`), snapshots free-service values, generates entitlements and the PDF.
* Delivery: `max(delivery_ids.date_done)` of **all** done deliveries linked to the card, converted
  with the **confirming user's** timezone.
* Invoice: `min(invoice_date)` of posted `out_invoice` moves of the card's SO lines; reversed
  invoices not excluded.
* Installation: manual `installation_date` (editable in Draft / Ready for every criterion).
* No server-side protection of dates after confirmation; chatter only logs PDF downloads.

Verified facts used by this design:
* `account.move.state` is tracked (`tracking=True`) in Odoo 18 → each Draft → Posted transition
  made through the ORM leaves a `mail.tracking.value`. On 18_4, INV/2026/00005–00007 have such
  a record; **INV/2026/00001–00004 have none** (created in bulk 2026-10-26 06:39) → their posting
  time cannot be verified.
* Odoo has no posting-timestamp field on `account.move`.
* `industry_fsm_sale` is installed on 18_4 and `wt_p5_mrf`; tasks generated from SO lines get
  `sale_line_id` (`sale_project._timesheet_create_task_prepare_values`).
* `project.task` has no completion timestamp (`date_end` only follows folded stages); Mark as Done
  (`action_fsm_validate`) writes `fsm_done=True, state='1_done'`.
* `res.company.warranty_signoff_required` ("Customer Sign-off Required", FSM module, default on)
  and `warranty_fsm_project_id` ("Warranty Field Service Project") already exist.
* Only `warranty_card.py` writes card / unit dates in the warranty modules (no other module).
* `warranty_management_helpdesk/models/warranty_case.py` (lines ~599, ~892) treats
  `('draft', 'ready')` as "not confirmed yet → manual review".

## 4. Common rules

### 4.1 Warranty Timezone conversion
New helper on `res.company` (core), sharing the timezone resolution of `_warranty_today()`:

```
_warranty_tz_name()            -> warranty_timezone or partner_id.tz or 'UTC'
_warranty_local_date(datetime) -> date of the UTC datetime in that timezone
```
`_warranty_today()` is refactored to use `_warranty_tz_name()` (no behaviour change). Every
timestamp → date conversion in this design uses the **card company's** helper, never the
user's timezone.

### 4.2 Terminology
* **Warranted unit** – a `warranty.unit` of the card (one per SO line quantity unit).
* **Goods unit** – unit whose product is `type == 'consu'` (needs a delivery, as today).
* **Relevant SO line** – the unit's `sale_order_line_id` (never other lines of the order).
* **Source event** – delivery validation / invoice posting / installation task completion, each
  with a UTC timestamp.
* **Expected dates** – start / end calculated live from the current source events (not stored).
* **Frozen dates** – the stored `warranty_start_date` / `warranty_end_date` written at
  confirmation; changed afterwards only through the correction wizard.

### 4.3 Card start / end
* Card start = **local date of the latest unit source timestamp** once every warranted unit has
  met its condition (D2, and §7.2 for invoices).
* End (Period basis) = start + duration − 1 day (unchanged). Usage basis: no end (unchanged).
* All units of a card receive the card start / end at confirmation (unchanged); each unit also
  keeps its own source reference / timestamp for traceability.

## 5. Status model

`CARD_STATES` gains **`pending_installation` ("Pending Installation")** between Draft and Ready.

| From | To | Trigger |
|---|---|---|
| (new) | Draft | Card created by grouping |
| Draft | Pending Installation | Installation basis; every requirement met **except** the installation completion (computed) |
| Draft / Pending Installation | Ready to Confirm | All requirements met, incl. source event (computed) |
| Pending Installation / Ready | Draft | A requirement is lost again (e.g. task reopened, invoice reset) (computed) |
| Ready | Confirmed | Delivery / Invoice / Custom: user clicks Confirm Warranty. Installation from tasks: **automatic** at the last task completion or at the last missing requirement (D6); Installation by exception: manual Confirm |
| Confirmed | Suspended / Expired / Cancelled | Unchanged (existing logic) |

Implementation:
* `_get_missing_requirements()` keeps its message list; a new internal
  `_get_missing_requirement_items()` returns `(code, message)` pairs so `_compute_state` can
  tell "only installation missing" (`code == 'installation'`) from other gaps.
* `_compute_state` / `_compute_missing_requirements` treat `pending_installation` like
  `draft` / `ready` (recomputed, not frozen).
* Every place that means "not confirmed yet" must include the new state: the card views
  (`readonly="state not in (...)"`, statusbar `draft,pending_installation,ready,confirmed`),
  and `warranty_management_helpdesk/models/warranty_case.py` (two tuples
  `('draft', 'ready')` → also `pending_installation`, same manual-review result). This is the
  only Part 3 code change (state list only, no logic change).

## 6. Data model

### 6.1 Core (`warranty_management`)

**`warranty.card`** (new fields; stored ones `copy=False`, readonly in views, protected §9):

| Field | Type | Stored | Meaning |
|---|---|---|---|
| `expected_start_date` | Date | no (compute) | Start from the current source events; empty when not determinable |
| `expected_end_date` | Date | no (compute) | End from the expected start |
| `expected_source_note` | Char | no (compute) | E.g. "Delivery WH/OUT/00013 validated 26/10/2026 19:52 (Asia/Colombo)"; or why it cannot be calculated |
| `start_date_source` | Selection | yes | `delivery`, `invoice`, `installation`, `custom`, `exception`; empty = confirmed before this feature ("Not recorded (before automation)" in the view) |
| `source_picking_id` | M2O stock.picking | yes | Delivery that set the card start (latest unit delivery) |
| `source_invoice_id` | M2O account.move | yes | Invoice that set the card start (latest unit invoice) |
| `source_datetime` | Datetime | yes | UTC timestamp of the deciding source event |
| `source_verification` | Selection | yes | `event` (captured live), `history` (verified from chatter tracking, §7.2.5), `exception` (authorized exception) |
| `date_log_ids` | O2M warranty.card.date.log | – | Audit history (§11) |

`installation_date` stays (data preserved) but becomes system-filled and read-only (§7.3, §9).

**`warranty.unit`** (new fields):

| Field | Type | Stored | Meaning |
|---|---|---|---|
| `delivery_picking_id` | M2O stock.picking | no (related `stock_move_line_id.picking_id`) | Validated delivery of the unit |
| `delivery_datetime` | Datetime | no (related `...picking_id.date_done`) | Actual validation time |
| `source_invoice_id` | M2O account.move | yes, at confirmation | Invoice covering the unit (§7.2) |
| `source_invoice_posted_at` | Datetime | yes, at confirmation | Its posting time |
| `expected_invoice_id` / `expected_invoice_posted_at` | M2O / Datetime | no (compute) | Live allocation before confirmation |

The related delivery fields need no migration (computed from existing allocation data).

**`account.move`** (new, core):

| Field | Type | Meaning |
|---|---|---|
| `warranty_posted_at` | Datetime, stored, readonly, `copy=False` | Time of the **current** posting (latest Draft → Posted) while the move is Posted; cleared on reset to draft / cancel |
| `warranty_posting_event_ids` | O2M | History |

**New model `warranty.invoice.posting.event`** (core; append-only, no edit / delete for anyone):
`move_id` (`ondelete='cascade'`: posted moves cannot be deleted anyway; a draft move deleted by
Odoo takes its events with it), `event` (`posted`, `reset_to_draft`,
`cancelled`), `event_datetime` (UTC), `user_id`, `company_id` (related, stored, record rule).
Only customer invoices / credit notes (`out_invoice`, `out_refund`) are recorded.

**New model `warranty.card.date.log`** (core; append-only): `card_id`, `event` (`activation`,
`exception`, `correction`, `source_change`, `invoice_reversal`, `delivery_return`,
`task_reopened`, `task_cancelled`), `old_start`, `old_end`, `old_installation`, `new_start`,
`new_end`, `new_installation`, `start_date_source`, `picking_id`, `invoice_id`, `task_ref`
(Reference/char so the core does not depend on `project`), `source_datetime`, `reason` (Text),
`attachment_ids`, `user_id`, `log_datetime`, `company_id`. Each log also posts a chatter note.

### 6.2 Installation (`warranty_management_fsm`)

**`product.template`**: `warranty_installation_service` Boolean "Warranty Installation Service"
(help: completing the Field Service task created from this service starts the warranty of
Installation-basis cards) and `warranty_installation_product_ids` M2M product.template
"Installs Products" (the warranted products whose cards the task is linked to, Q8). Constraint:
only for service products that create a task in a Field
Service project (`service_tracking == 'task_global_project'` and project `is_fsm`), else
validation error on save.

**`project.task`**:

| Field | Type | Meaning |
|---|---|---|
| `warranty_task_purpose` | Selection `[('installation', 'Installation')]`, readonly, `copy=False` | Set only by system (SO line with flagged product, or card button) |
| `warranty_installation_card_ids` | M2M warranty.card | Explicitly linked cards (D5) |
| `warranty_installation_done_at` | Datetime, readonly, `copy=False` | Time of the latest valid completion (§7.3) |

Constraint: `warranty_task_purpose == 'installation'` and `warranty_service_job_id` are mutually
exclusive; linked cards must belong to the task's Sales Order (`sale_order_id`), same company and
same customer; only Installation-basis cards can be linked.

**`warranty.card`** (FSM extension): `installation_task_ids` (inverse M2M),
`installation_task_count`, button **Create Installation Task**; the Installation requirement and
expected date of the core are extended here (core without FSM: installation only via exception).

**Manifest**: `warranty_management_fsm` adds `industry_fsm_sale` to `depends` (already installed on
both DBs).

## 7. Source-selection rules

### 7.1 Delivery basis
1. A unit's delivery = the picking of its allocated `stock_move_line_id` (allocation unchanged:
   `stock.picking._warranty_allocate_delivery`, in unit order). This is the only link used, so
   deliveries of other lines / orders can never count ("never an unrelated delivery").
2. Unit timestamp = `picking.date_done` (UTC) of that picking (outgoing, state done).
3. Requirement: every goods unit has a done delivery (already required today for every basis).
   Card start = local date of `max(unit delivery_datetime)` (D2). `source_picking_id` = picking of
   that maximum.
4. Non-goods units (service / combo products) have no delivery; they do not influence the date.
   A Delivery-basis card with **no** goods unit has no source event → requirement "Validated
   delivery" stays missing → exception process (§10).
5. Per Delivery grouping keeps its split (undelivered units move to a new Draft card); each card
   then dates from its own units.
6. Returns: a validated return of a delivered unit does not de-allocate the unit (unchanged
   behaviour). It writes a `delivery_return` log + chatter note on the affected cards (Draft or
   confirmed); dates are not changed automatically (Q13).
7. Change vs today: `card.delivery_ids` (all linked pickings) is no longer used for the date; the
   unit allocation is. For cards where every unit was allocated, the result is the same.

### 7.2 Invoice basis

#### 7.2.1 Posting-time capture (D1, D1b)
* Override `account.move._post(soft=True)`: after `super()`, for the returned moves that are now
  `posted` and of type `out_invoice` / `out_refund`: set `warranty_posted_at = now()` and create a
  `posted` event. Scheduled posting (`auto_post`) is recorded at the cron run time (actual
  posting).
* Override `button_draft()` / `button_cancel()`: create `reset_to_draft` / `cancelled` events and
  clear `warranty_posted_at` (D1b: the earlier posting is no longer valid; its event stays).
* `warranty_posted_at` is written only by these hooks (field protected, §9).

#### 7.2.2 Relevant invoice lines (matching, D3)
For a unit with SO line *L*, the relevant lines are `account.move.line` records with
`display_type == 'product'`, `L in sale_line_ids`, move `state == 'posted'`:
* `out_invoice` lines → **+quantity**, `out_refund` lines → **−quantity** (credit note).
* Quantity converted to the product UoM (`product_uom_id._compute_quantity`).
* Down payments are never relevant: they are invoiced on the separate down-payment SO line
  (`is_downpayment`), never on *L*; the deduction line of a final invoice is also on that line.
  An invoice containing only down payments / other products has no relevant line → ignored.
* Draft / cancelled moves never count.

#### 7.2.3 Reversals (credit notes)
* A credit note quantity is first applied to the invoice it reverses (`reversed_entry_id`) for the
  same SO line; a credit note without `reversed_entry_id` (or exceeding it) is applied to the
  most recently posted invoice lines of *L* that still have quantity (LIFO) (Q2).
* An invoice whose relevant quantity is fully credited is **reversed** for that line and covers no
  unit. Fully reversed invoices (`payment_state == 'reversed'`) are therefore excluded
  automatically.

#### 7.2.4 Quantity allocation to units (D3)
Per SO line *L*:
1. Order the net invoice quantities by posting time (`warranty_posted_at` / verified history,
   §7.2.5), ties by move id.
2. Walk the units of *L* in `unit_number` order (same order as delivery allocation). Unit *k* is
   covered by the first invoice whose **cumulative net quantity ≥ k** (whole units; a fractional
   remainder covers nothing until the cumulative quantity reaches the next whole number – Q3).
3. Units beyond the cumulative net quantity are **not invoiced** → missing requirement
   "Invoice for unit WN/…" → the card cannot be confirmed (D3: units without the invoicing
   condition never activate).
4. Unit timestamp = posting time of its covering invoice. Card start = local date of the **latest**
   unit timestamp (consistent with D2; Q1). `source_invoice_id` = that invoice.

Example: SO line qty 3 (units 1–3). INV-A posted 01/11 qty 2, INV-B posted 05/11 qty 1 →
units 1–2 by INV-A, unit 3 by INV-B → card start 05/11. If only INV-A exists, unit 3 is missing
and the card stays Draft. If RINV credits INV-A qty 1 → INV-A net 1, units 1 by INV-A, 2 by INV-B,
3 missing.

#### 7.2.5 Historical posting time (D1a)
An invoice without `warranty_posted_at` (posted before the module upgrade) is resolved **on the
fly, without writing** anything at upgrade time:
* Verified history = the latest `mail.tracking.value` on `account.move.state` of that move whose
  new value is Posted, with no later tracking value leaving Posted; timestamp = the tracking
  message `date` (UTC, written in the posting transaction). Values are matched on the field and
  the selection label of every installed language (tracking stores labels) (Q4).
* Found → usable, `source_verification = 'history'` (frozen on the card at confirmation; the
  log records the tracking message id).
* Not found (e.g. 18_4 INV/2026/00001–00004) → the unit is "Invoice posting time cannot be
  verified (INV/…)" → missing requirement; only the exception process (§10) can set the start.
  `create_date`, `write_date`, `invoice_date` and `date` are never used.

#### 7.2.6 Other rules
* The existing Payment Check (policy `payment_check_required`) is unchanged.
* Credit notes posted **after** confirmation: `invoice_reversal` log + chatter note on the
  confirmed cards whose SO lines are credited (with invoice / credit-note references and
  quantity) and an activity to the card's service alert responsible users (Q16). Dates and card
  state are not changed automatically.

### 7.3 Installation basis
1. **Identification (D4)** – a task is an installation task only if
   `warranty_task_purpose == 'installation'`, it is a Field Service task (`is_fsm`) and has no
   `warranty_service_job_id`. Purpose is set (a) by `sale.order.line._timesheet_create_task_prepare_values`
   when the line product has `warranty_installation_service`, or (b) by **Create Installation
   Task** on the card. Part 4 visits, repair / maintenance and any other task can never qualify.
2. **Linking (D5)** – explicit M2M:
   * **Relevance (Q8, user decision)** – the installation service product lists the products it
     installs (`warranty_installation_product_ids`, "Installs Products"). A task created from an
     SO line is linked only to the Installation-basis cards of the same SO (Draft / Pending
     Installation / Ready) that contain a unit of one of these products. Empty list → no automatic
     link (unrelated cards of the same SO are never linked).
   * Cards created **after** the task (Warranty Grouping runs after SO confirmation, when
     `industry_fsm_sale` already created the task): the same relevance rule is applied at card
     creation to the SO's non-cancelled installation tasks.
   * Per Delivery split: the same relevance rule is applied to the new card.
   * Create Installation Task button: creates one task in the company's Warranty Field Service
     Project (`warranty_fsm_project_id`, else the standard FSM project), customer = SO customer,
     address = SO delivery address, linked to this card only.
   * Manual link / unlink: only Date Correction group, only while the task is not done and the
     card is not confirmed; logged (`source_change`).
   * "Same site" = the Sales Order delivery address; a task can only link cards of its own SO.
3. **Completion event (D7)** – `project.task.write` override (FSM module, additive; Part 4 lock
   untouched): when an installation task enters `state == '1_done'` (Mark as Done or any closing
   path), set `warranty_installation_done_at = now()`.
   * Customer Sign-off Required (company setting, existing): Mark as Done of an installation task
     is refused without the customer signature (`worksheet_signature`), same rule as warranty
     visits (Q6).
   * **Original completion preserved (Q7, user decision)**: `warranty_installation_done_at` is
     set only by the **first** valid completion and never changed by reopening or completing
     again. Reopened before confirmation: the card waits (installation requirement missing again,
     `task_reopened` log); completed again: the card uses the **original** timestamp (the log
     shows both). After confirmation: card unchanged, log + note only; never a second
     activation (only Ready cards are confirmed). Changes only through the correction wizard.
   * Task cancelled: no longer a required task; `task_cancelled` log. A card whose linked tasks are
     all cancelled has no installation source → stays Pending Installation (new task or
     exception).
4. **Card date** – all linked, non-cancelled tasks done → `installation_date` = local date of the
   latest `warranty_installation_done_at` (written by the system), card start = that date.
5. **Activation (D6)** – after a task completion (and after a delivery validation or an invoice
   posting, for Installation cards whose installation comes from tasks): cards that are now Ready are confirmed automatically
   (`_warranty_auto_confirm`), exactly once (state guard: only Ready cards). The confirmation runs
   with `sudo()` (technicians may lack card rights) and the log / chatter author is the completing
   user. A `UserError` raised by the confirmation is caught **specifically** in a savepoint: the
   task completion still succeeds, the card stays Ready, the error is logged on the card and an
   activity goes to the responsible users. No broad exception swallowing.

### 7.4 Custom Date Range
Unchanged: manual start / end in Draft / Ready; `start_date_source = 'custom'` at confirmation.

## 8. Event hooks (summary)

| Event | Hook (module) | Effect |
|---|---|---|
| Delivery validated | `stock.picking._action_done` (core, existing) | Allocation as today; then `_warranty_auto_confirm` for Installation cards concerned |
| Return validated | `stock.picking._action_done` (core) | `delivery_return` log on cards of returned units |
| Invoice posted | `account.move._post` (core, new) | `warranty_posted_at`, event; state recompute of cards; `_warranty_auto_confirm` (Installation cards); credit note → reversal log on confirmed cards |
| Invoice reset / cancelled | `account.move.button_draft` / `button_cancel` (core, new) | Event; `warranty_posted_at` cleared; confirmed cards: `source_change` log if the card's source invoice |
| Task created from SO line | `sale.order.line._timesheet_create_task_prepare_values` (FSM, new) | Purpose + card links |
| Cards created by grouping | `sale.order._warranty_create_draft_cards` (FSM extension of the card creation, `super()` first) | Link existing installation tasks |
| Task done / reopened / cancelled | `project.task.write` (FSM, additive) | done_at, logs, `_warranty_auto_confirm` |
| Confirm Warranty | `warranty.card.action_confirm_warranty` (core) | Freeze dates + source fields + unit sources; `activation` log |

Card state recompute: invoice posting state, task done_at and posting fields are added to the
`@api.depends` of `_compute_state` (`REQUIREMENT_DEPENDS`) where they are stored fields; otherwise
the hook calls an explicit recompute (`_warranty_recompute_requirements`).

## 9. Protection of dates (D9)

* Internal marker object `_DATE_WRITE_MARKER` (same pattern as Part 4's `_WARRANTY_CLOSE_MARKER`:
  a Python object no client can send; `sudo()` alone does not pass).
* `warranty.card.write` refuses, without the marker:
  * `warranty_start_date`, `warranty_end_date` – unless the card is Draft / Pending / Ready **and**
    `start_criterion == 'custom'`;
  * `installation_date`, `start_date_source`, `source_*`, `start_criterion` – always (system only);
  * card `create` with these values (except Custom start / end) – refused.
* `warranty.unit.write` refuses `start_date`, `end_date`, `source_invoice_*` without the marker.
* `account.move.write` refuses `warranty_posted_at`; `project.task.write` refuses
  `warranty_installation_done_at`, `warranty_task_purpose` without the marker.
* Applies to UI, import (`load` → `create` / `write`) and JSON-RPC. Direct SQL is not covered
  (outside the ORM).
* Views: these fields readonly; `installation_date` readonly in every state.
* Writers with the marker: confirmation, exception / correction wizard, grouping split
  (resets dates of the new Draft card), hooks of §8.

## 10. Exception and correction (D1a, D8, D9, D10)

One wizard **`warranty.card.date.wizard`** (transient), opened from the card by users of
**Warranty: Date Correction**; two modes:

**Exception (before confirmation)** – card in Draft / Pending Installation / Ready with
Delivery / Invoice / Installation basis whose source event is missing or not verifiable
(no delivery source, unverifiable historical invoice, installation without task):
* Fields: start date (Installation basis: Installation Date), mandatory reason, optional evidence
  attachments; shows the expected end and the current missing requirements.
* Effect: stores the date as the card's exception source (`start_date_source = 'exception'`,
  `source_verification = 'exception'`), `exception` log + chatter; the source requirement is
  satisfied, **all other requirements still apply**. The card is then confirmed **manually**
  (for every basis: an exception is an explicit authorized act, no automatic activation).
* The exception date is never later overwritten by an event; if the real event arrives later, a
  `source_change` note shows both values (no automatic change).

**Correction (after confirmation)** – card Confirmed or Suspended (Q11):
* Fields: new start date (Custom basis: new start and end), mandatory reason, attachments;
  shows old / new start, end and the entitlements that will be recalculated.
* Effect (one transaction, marker): card and all its units get the new start / end (end recalculated
  from the frozen duration); `correction` log (before / after, reason, user) + chatter;
  eligible entitlements recalculated (below); PDF soft copy regenerated (download count
  unchanged) (Q11).
* **D10 – entitlements**: only `draft` / `pending` entitlements not selected / merged for a job
  (`_is_expiry_blocked()` false) and whose current due date equals the value calculated from the
  **old** start (i.e. not manually re-dated, Q12) get the due date / alert date from
  `_get_free_service_due_values()` with the new start; the existing due-date change rules apply
  (alert reset, date log). Scheduled, in progress, completed, missed, expired, cancelled and
  manually re-dated entitlements are kept; the wizard lists them as "not changed".

## 11. Audit and chatter (D11)

* `warranty.card.date.log` (append-only; read for internal users of the card company; no
  write / unlink for anyone) is the structured audit; each record also posts an internal note on
  the card (`_message_log`, no email, no followers) with links to the delivery / invoice / task.
* Card notes: activation (basis, source document, timestamp in Warranty Timezone, verification),
  exception, correction (before / after, reason), source change (invoice reset / reposted,
  task reopened / cancelled, link changes, later real event after an exception), invoice
  reversal after confirmation, delivery return.
* The card's chatter description ("only logs PDF downloads") is extended accordingly; the
  creation note stays disabled.
* `warranty.invoice.posting.event` keeps all posting / reset / cancel events of customer invoices.

## 12. Permissions

| Item | Rule |
|---|---|
| Group `warranty_management.group_warranty_date_correction` "Warranty: Date Correction" | New, no implied groups, not assigned automatically (admin assigns it) |
| Exception / correction wizard, manual task links | Group only (button `groups=` + server check) |
| `warranty.card.date.log`, `warranty.invoice.posting.event` | Read: `base.group_user`; create only by system code (sudo); no write / unlink (ACL + `ondelete` / `unlink` guard); multi-company record rules |
| Create Installation Task | Users who may create Field Service tasks (`industry_fsm.group_fsm_user`) and write the card |
| Auto-confirm | System (sudo) on behalf of the completing user |

## 13. Existing data and upgrade

* No data migration: new columns are empty, the new state is only a selection value, related
  unit delivery fields are computed. Confirmed cards (WC/00001–00004) keep every value; their
  `start_date_source` is empty → "Not recorded (before automation)". Manually typed
  Installation Dates on WC/00001 / WC/00002 stay (unused, read-only).
* No posting events are created for already-posted invoices at upgrade (D1a: verified on the fly,
  §7.2.5).
* Draft cards existing at upgrade (none on 18_4) are recomputed with the new rules (state may
  change Draft ↔ Pending ↔ Ready – computed, not data loss). Installation dates typed in Draft
  cards before the upgrade are **not** used as installation source (they need a task or an
  exception); listed in the upgrade log.
* Versions: `warranty_management` 18.0.1.1.0, `warranty_management_fsm` 18.0.1.1.0,
  `warranty_management_helpdesk` 18.0.1.0.2 (state list).

## 14. Affected files

**`warranty_management`** (core):
| File | Change |
|---|---|
| `models/res_company.py` | `_warranty_tz_name`, `_warranty_local_date`; `_warranty_today` reuses it |
| `models/warranty_card.py` | New state, requirement items, source rules (delivery / invoice), expected fields, source fields, confirmation freezing, write guard, auto-confirm entry point, logs |
| `models/warranty_unit.py` | Delivery related fields, invoice source fields, write guard |
| `models/account_move.py` (new) | Posting capture, reset / cancel events, field guard, reversal notes, invoice allocation helpers |
| `models/warranty_invoice_posting_event.py` (new) | Event model |
| `models/warranty_card_date_log.py` (new) | Audit model |
| `models/stock_picking.py` | Return log; auto-confirm call after allocation |
| `models/warranty_service_entitlement.py` | Recalculation helper for corrections |
| `models/__init__.py`, `wizard/__init__.py` | Imports |
| `wizard/warranty_card_date_wizard.py` + `_views.xml` (new) | Exception / correction wizard |
| `views/warranty_card_views.xml` | Statusbar, readonly rules, expected / source fields, Date History tab, wizard buttons |
| `views/warranty_unit_views.xml` | Unit source columns |
| `views/account_move_views.xml` (new) | Posting time + events on the customer invoice (read-only, inherited view) |
| `security/warranty_security.xml`, `security/ir.model.access.csv` | Group, ACL, record rules |
| `__manifest__.py` | Version, data files |
| `tests/common.py` | Test helper to set a test start / installation source through the marker |
| `tests/test_warranty_start_date.py` (new) | §15 |
| Existing tests setting `card.installation_date` (≈10 places: part1, part2, part2_monitoring, policy_product, scope_visibility, download, free_service_scheduling) | Replace the manual write with the helper (no assertion change) |
| `tests/Part2_Manual_Testing_Guide.md` | New section "Start Date Automation" (TC-SD-xxx) |
| `doc/part2_design_decisions.md`, `doc/PROJECT_HANDOFF.md` | Decision entry / status |

**`warranty_management_fsm`**:
| File | Change |
|---|---|
| `models/product_template.py` | `warranty_installation_service` + constraint |
| `models/project_task.py` | Purpose, card links, done_at, completion / reopen / cancel hook, sign-off check for installation tasks (additive; Part 4 methods unchanged) |
| `models/sale_order.py` | SO line task preparation (purpose + links); link tasks after card creation |
| `models/warranty_card.py` (new) | Task links, Create Installation Task, installation requirement / expected date |
| `views/product_template_views.xml`, `views/project_task_views.xml`, `views/warranty_card_views.xml` (new) | Fields, button, smart button |
| `__manifest__.py` | `industry_fsm_sale` dependency, version, data |
| `tests/test_installation_start_date.py` (new) | §15 |
| Existing tests setting `installation_date` (draft_job_from_service, flexible_service_dates, service_job_multicard) and writing a confirmed card's `warranty_end_date` (flexible_service_dates ≈ lines 457–550) | Use the test helper (marker) |
| `tests/Part4_Manual_Testing_Guide.md` | Installation task section |

**`warranty_management_helpdesk`** (Part 3 – needs the user's approval): `models/warranty_case.py`
two state tuples; tests setting `installation_date` (warranty_case, card_selection,
coverage, eligibility, repeated_failure) → helper; version bump.

**Not changed**: `warranty_management_mrp` (allocation extension keeps working),
`warranty_management_mrf` (to be confirmed by the regression), AMC, vendor module.

## 15. Test plan (automated, new)

Core – `test_warranty_start_date.py`:
| ID | Case |
|---|---|
| SD-01 | Timezone: delivery done 2026-10-26 20:00 UTC, Warranty Timezone Asia/Colombo → start 2026-10-27 (not the user's tz) |
| SD-02 | Delivery: partial deliveries (2 + 1 units) → Draft until all delivered, start = latest, `source_picking_id` = 2nd picking; unit delivery fields per unit |
| SD-03 | Delivery: a done delivery of another SO line / order never sets the date |
| SD-04 | Delivery: SO date / commitment / scheduled date ignored (backdated scheduled date) |
| SD-05 | Invoice: `invoice_date` backdated → start = posting time (local date) |
| SD-06 | Invoice: draft invoice never counts; cancelled never counts |
| SD-07 | Invoice: reset to draft + repost → latest posting; events keep both postings |
| SD-08 | Invoice: down-payment invoice only → missing; final invoice → covered |
| SD-09 | Invoice: allocation 2 + 1 (example §7.2.4); partial invoice leaves unit 3 missing |
| SD-10 | Invoice: full reversal (credit note with `reversed_entry_id`) → not covered; partial credit note re-allocation |
| SD-11 | Invoice: invoice of unrelated products only → ignored |
| SD-12 | Invoice: historical posting with tracking → `history` verification; without tracking → missing, no fallback to create/write/invoice date |
| SD-13 | Invoice: credit note after confirmation → reversal log + note + activity, dates unchanged |
| SD-14 | Expected start / end shown in Draft / Ready, equal to the frozen values after Confirm |
| SD-15 | Protection: write of start / end / installation / source fields on a confirmed card refused (user, sudo, `load` import); unit dates refused; `warranty_posted_at` refused |
| SD-16 | Custom Date Range unchanged (manual start / end in Draft, confirm) |
| SD-17 | Usage basis unchanged (no end date) |
| SD-18 | Exception wizard: group required; reason mandatory; Invoice card with unverifiable invoice → exception → Ready → manual confirm; log + chatter |
| SD-19 | Correction wizard: new start, end recalculated, units updated, eligible Draft entitlements recalculated, scheduled / completed / missed / manually re-dated kept, log before / after |
| SD-20 | Correction refused without group / without reason / on Draft card |
| SD-21 | Grouping unchanged: Per SO / Per Product / Per Delivery / Per Unit produce the same cards and units as before |
| SD-22 | Existing confirmed card (no source fields) unchanged by recompute; shows "Not recorded" |
| SD-23 | Audit models: no write / unlink by users (incl. administrators via ORM) |

FSM – `test_installation_start_date.py`:
| ID | Case |
|---|---|
| IN-01 | SO with flagged installation service → task purpose installation, linked to the SO's Installation cards created later by grouping |
| IN-02 | Card stays Pending Installation until the task is done; then installation date = completion date (Warranty Timezone), auto-confirmed once |
| IN-03 | Two tasks linked → waits for both; start = latest completion |
| IN-04 | One task covering two cards of the same SO → both activate; card of another SO cannot be linked |
| IN-05 | Part 4 service-job visit, repair task, unflagged FSM task → never activate (and Part 4 completion tests unchanged) |
| IN-06 | Sign-off required: Mark as Done refused without signature; with signature allowed; setting off → no signature needed |
| IN-07 | Delivery not validated at completion → card Draft (not Pending/Ready), no activation; delivery validated later → auto-confirm |
| IN-08 | Task reopened before confirmation → back to Pending, re-completion uses new time; after confirmation → note only |
| IN-09 | All tasks cancelled → Pending; exception wizard → Ready → auto-confirm |
| IN-10 | Create Installation Task button → task in the Warranty FSM project, linked, purpose set |
| IN-11 | Installation date not writable manually (UI / API) |
| IN-12 | Auto-confirm failure (e.g. missing serial raised at confirm) → task done, card stays Ready, note + activity |
| IN-13 | Product flag constraint (non-FSM service product refused) |

Regression: full suite (baseline 464 / 1 known error) after updating the fixtures; manual UAT
cases TC-SD-01… in the Part 2 / Part 4 guides.

## 16. Implementation questions – all approved by the user 2026-10-28 (Q7, Q8 changed)

| # | Question | Recommendation |
|---|---|---|
| Q1 | Invoice basis card start when units are covered by different invoices | **Latest covering invoice** (consistent with D2: the card activates when its last unit meets the condition). Alternative: earliest. |
| Q2 | Credit note allocation | **Reversed invoice first (`reversed_entry_id`), else LIFO on the SO line**; a partial credit note after confirmation only logs. |
| Q3 | Fractional / UoM quantities | **Convert to product UoM; only whole cumulative units are covered** (0.5 covers nothing). |
| Q4 | Historical posting time | **Verify on the fly from `account.move.state` tracking (latest Draft→Posted, not left afterwards), no backfill at upgrade; unverifiable → exception.** On 18_4 this affects only INV/2026/00001–00004 (no Draft card uses them today). Accept the tracking message time (seconds, posting transaction) as "verified"? |
| Q5 | Should historical verification be frozen into posting events when first used? | **No** – freeze only on the card at confirmation (`source_verification = 'history'`, log keeps the tracking message id). |
| Q6 | Sign-off for installation tasks | **Reuse the existing company setting "Customer Sign-off Required" (default on) and refuse Mark as Done of an installation task without signature** (activation time = completion time). Alternative: allow completion and activate only when signed (activation time then = ? – not recommended). Note: the setting currently describes warranty visits; its help text would be extended. |
| Q7 | Task reopened and re-completed | **Decided (changed): the original valid completion timestamp is kept**; no silent change, no second activation; corrections only through the wizard. |
| Q8 | Automatic links of a task created from an SO line | **Decided (changed): only the relevant Installation-basis cards** (cards with a unit of a product listed in the installation service's “Installs Products”); explicit edits by the Date Correction group only. |
| Q9 | Project of Create Installation Task | **Existing "Warranty Field Service Project" setting, else the company's standard FSM project.** |
| Q10 | Same group for exceptions and corrections | **Yes – one group "Warranty: Date Correction".** |
| Q11 | Correction allowed on | **Confirmed and Suspended cards; Expired / Cancelled refused in this phase.** PDF soft copy regenerated after a correction (download count unchanged). |
| Q12 | Draft entitlements whose due date was changed manually (due-date wizard) | **Kept (not recalculated)**, listed in the wizard as not changed. Missed excluded (D10). |
| Q13 | Delivery return before / after confirmation | **Log + note only, no de-allocation, no date change.** |
| Q14 | Delivery basis without goods units | **No automatic source → exception process.** |
| Q15 | Partially delivered / invoiced cards | **Card waits (no automatic split)**; Per Delivery grouping split behaviour unchanged. |
| Q16 | Credit note after confirmation | **Note + activity to the card's service alert responsible users**; no state / date change. |
| Q17 | Invoice basis and goods units | **Keep today's rule: goods units also need their delivery for every basis** (existing requirement, unchanged). |
| Q18 | Part 3 file change | `warranty_management_helpdesk/models/warranty_case.py`: add `pending_installation` to the two "not confirmed yet" tuples + test fixture updates – **approval needed** (Part 3 is otherwise untouched). |

## 17. Risks

* Tests across helpdesk / FSM / MRF create confirmed cards through manual `installation_date`;
  the protection forces fixture updates (≈20 places) – mechanical, through one shared helper.
* Other code paths that check `('draft', 'ready')` must know the new state – grep done (§3);
  rechecked during implementation.
* Tracking labels are language-dependent (§7.2.5) – matched against all installed languages.
* `_post` / `button_draft` overrides run for every customer invoice: kept light (one event row,
  card lookup through the SO lines of the posted moves only, batched).
* Auto-confirm generates the PDF inside the technician's Mark as Done transaction (a few seconds).

## 18. Implementation notes (2026-10-28, `wt_p5_mrf`)

Implemented as designed (rev 2), with these implementation details:

* **Exceptions are confirmed manually for every basis** (also Installation): an exception is an
  explicit authorized act; only installation-task completion activates automatically (§5, §10).
* **Correction PDF**: the protected PDF soft copy is regenerated **in the same attachment record**
  (no second protected attachment, Download Count unchanged). The previous PDF content is not
  kept as a file; the previous dates, reason and user are kept in the Warranty Date History.
* **Historical posting verification** (§7.2.5): Odoo writes the Draft → Posted status tracking
  only for invoices created and posted in different requests (verified: a probe invoice created
  and posted in one transaction has no tracking). On 18_4 INV/2026/00005 – 00007 have it;
  INV/2026/00001 – 00004 do not (exception required if a new card ever depends on them).
* **Group** "Warranty: Date Correction" is in the *Extra Rights* category of the user form.
* **Installation links (Q8)**: product field *Installs Products* (`warranty_installation_product_ids`)
  on the installation service; the installation code lives in
  `warranty_management_fsm/models/warranty_installation.py` (Part 4 files unchanged except the
  Customer Sign-off Required help text, which now mentions installation tasks).
* **Card activities**: `warranty.card` now inherits `mail.activity.mixin` (credit note review,
  failed automatic activation).
* **Part 3** (Q18): the two state tuples in `warranty_case.py` and the matching assertion of
  `test_warranty_case_eligibility.test_14_card_status`.
* **Existing tests** (no assertion weakened): manual `installation_date` writes replaced by the
  helper `tests/common.py:set_installation` (authorized exception); writes of a confirmed card's
  end date in `test_flexible_service_dates` use the system writer; Part 1 tests updated for the
  new state, the posting-time start and the refused manual write; the download chatter test
  ignores the new activation / exception notes.

Test results (`wt_p5_mrf`, 2026-10-28): new `TestWarrantyStartDate` 17 / 17 and
`TestInstallationStartDate` 11 / 11 passed; full regression **492 tests, 0 failed, 1 error** (the
known `test_13_serial_rules`, unchanged) – core + helpdesk + mrp + amc 244, FSM 73 + 71, MRF 104.
