# 10 – AMC Technical Design Specification (as implemented)

## 8.1 Architecture

* **Retained:** all 1.0.0 models, the Python-object *marker* pattern (`_CONTRACT_MARKER`,
  `_FORMULA_MARKER`, `_OVERRIDE_MARKER`) that lets only server code write protected fields, the
  pricing engine and the quotation flow.
* **Added to `amc_management`:** `amc.contract.visit`, `amc.billing.line`, contract lifecycle
  methods, `account.move._invoice_paid_hook`, daily cron, report, wizards, migration.
* **Bridges:** `amc_management_warranty` (warranty card / unit / opportunity links),
  `amc_management_service` (warranty case / service job / worksheet / ticket hooks).
* **Data flow:** Contract → (SO confirmation) billing lines → (activation) visits + billing dates →
  (cron) release → SO line `qty_delivered` → standard invoice. Visits → (service request) ticket +
  case → job → FSM task + worksheets → completion → `_amc_consume`.
* **Transactions:** activation, completion and renewal take a row lock on the contract
  (`SELECT … FOR UPDATE`, parameterized); consumption runs inside the warranty completion
  savepoint; the cron processes each contract in its own savepoint and logs failures.
* **Errors:** `UserError` for business rules (all problems listed at once where useful),
  `ValidationError` for constraints, `AccessError` for role checks – all translatable.

## 8.3 Main methods

| Method | Model | Purpose | Side effects | Req. |
|---|---|---|---|---|
| `_amc_on_order_confirmed(order)` | amc.contract | price frozen, billing generated, activation or Awaiting Payment | billing lines; release period 1 (payment trigger) | A05, G04 |
| `_amc_on_invoice_paid(invoice)` | amc.contract | Awaiting Payment → Active | `_amc_activate` | G03 |
| `_amc_activate(reason)` | amc.contract | Active, start date, visits, billing dates, renewal of predecessor, expiring check | visits, billing release | C02, E01 |
| `_amc_generate_visits()` | amc.contract | idempotent entitlement generation | visits | E01, E02, B06 |
| `_amc_generate_billing()` / `_amc_schedule_billing(release=True)` / `_amc_release_due_billing(today)` | amc.contract | billing schedule, dates, due releases | `qty_delivered` on SO lines | B09, G01 |
| `action_create_invoice()` | amc.contract | draft invoice of released periods (`sale.order._create_invoices`) | draft `account.move` | G01 |
| `_amc_hold(reason)` / `action_resume()` | amc.contract | On Hold / back | — | C04 |
| `_amc_check_expiring(today)` | amc.contract | Expiring + activity + auto offer | renewal draft | C05, B08 |
| `action_renew()` / `_amc_create_renewal()` | amc.contract | linked Draft renewal | contract copy | B08 |
| `_amc_close(reason, automatic)` / `_amc_end_entitlements()` / `_amc_mark_renewed()` | amc.contract | Closed / Renewed | visits Expired, billing Cancelled | C04, C05 |
| `_cron_amc_daily(today)` | amc.contract | scheduler | all of the above | E04, E08, C05 |
| `_amc_consume(date, usage, note, source)` | amc.contract.visit | single consumption with validations | billing release (per visit) | E06, E07, E09, E10 |
| `_cron_amc_visits(today)` | amc.contract.visit | due indicator, alerts, Missed | activities | E04, E08 |
| `_amc_release(date)` | amc.billing.line | +1 delivered on the SO line | — | G03 |
| `_invoice_paid_hook()` | account.move | scoped activation | — | A05 |
| `_amc_auto_create()`, `action_convert_to_amc()` | warranty.card (bridge) | draft AMC from warranty | contract / opportunity | A03, A07 |
| `_warranty_run_checks()` → `_amc_run_checks()` | warranty.case (bridge) | AMC eligibility | — | A08 |
| `action_confirm_job`, `_warranty_worksheet_lines`, `_warranty_create_worksheets`, `_warranty_visit_completion_problems`, `_warranty_complete_case`, `_warranty_cancel` | warranty.service.job (bridge) | AMC execution | visit states | F01–F07 |

Extension points: `amc.contract.visit._amc_manual_completion_allowed()` and
`_amc_check_not_in_service()` (overridden by the service bridge), `_amc_renewal_values()`.

## 8.5 Automation

| Job | Model / method | Frequency | Duplicate prevention | Failure handling |
|---|---|---|---|---|
| AMC: Daily Contract and Visit Scheduler (`ir_cron_amc_daily`) | `amc.contract._cron_amc_daily` | daily | releases only `planned` lines; state checks; `alert_sent`; renewal only if none open | per-contract savepoint + `_logger.exception`; visit monitoring idempotent |

Processing limit: all running contracts / open visits in one run (expected volume: hundreds to low
thousands of visits per company). Retry: the next daily run repeats idempotently.

## 8.6 Security (summary – details in 13)

ACL for every new model, multi-company record rules on `company_id`, server-side group checks in
every action, protected fields enforced in `write` (UI, import and RPC).

## 8.7 Migration (summary – details in 14)

`migrations/18.0.1.1.0/post-migrate.py`: billing schedule for Awaiting Payment / Active contracts,
entitlements for Active contracts; re-runnable; no deletion, no state / price change.
