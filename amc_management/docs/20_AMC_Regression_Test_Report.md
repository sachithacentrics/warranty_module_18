# 20 – AMC Regression Test Report (non-AMC workflows)

## 1. Full warranty regression with the AMC modules installed

**Executed:** 2026-11-06, database `amc_test` (all warranty addons + `amc_management` 1.1.0 +
both bridges), tags `/warranty_management, /warranty_management_helpdesk, /warranty_management_mrp,
/warranty_management_accounting, /warranty_management_repair, /warranty_management_mrf,
/warranty_management_fsm` (log `regression_1.log`).

**Result:** `5 failed, 1 error(s) of 866 tests` → **860 PASS**. All Field Service suites (service
jobs: confirm, worksheets, completion, batch, reschedule, cancel, shared visits, draft jobs), which
are extended by `amc_management_service`, passed completely.

| Test | Module | Symptom |
|---|---|---|
| TestWarrantyCardDownloadHttp.test_12_urls | warranty_management | report URL returns 200 where 403/redirect expected |
| TestWarrantyPart2Monitoring.test_02_snapshot_and_monitoring_dates | warranty_management | due status `upcoming` instead of empty (date-dependent) |
| TestWarrantyPart2Monitoring.test_30_due_alert_email | warranty_management | mail subject contains unrendered `{{ … }}` |
| TestWarrantyPart2Monitoring.test_33_expiry_reminder_and_expired_emails | warranty_management | mail subject contains unrendered `{{ … }}` |
| TestWarrantyCasePayment.test_31_in_payment_partial_and_shared_payment | warranty_management_helpdesk | overdue invoice set differs (date-dependent) |
| TestWarrantyMrfCost.test_02_fifo_and_avco_layer_values | warranty_management_mrf | AccessError on `mrp.bom` |

## 2. Baseline comparison without any AMC module

To separate pre-existing failures, a new database `wm_base` was installed with the warranty modules
only (`warranty_management_mrf, _accounting, _repair, _mrp` and their dependencies; **0 AMC modules
installed**, verified in `ir_module_module`) and the six tests were run there:

`5 failed, 1 error(s) of 6 tests` – **identical failures**.

**Conclusion:** the six failures are pre-existing in the warranty modules on this environment
(template rendering, date-dependent fixtures, MRP access) and are **not caused by the AMC
implementation**. They are reported to the warranty maintainers; no AMC change is needed.
No regression was introduced by the AMC modules.

## 3. AMC-side regression tests

TC-070 (regular Sales Order end-to-end), TC-072 (regular invoice payment), TC-080 / TC-083
(warranty confirmation unchanged / never blocked), TC-097 (non-AMC eligibility unchanged): PASS
(see 18).
