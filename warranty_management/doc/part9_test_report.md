# Part 9 test report

Run 2026-11-05 on the disposable database `wt_p7_s2`, in the foreground. **Full regression is not a PASS: 11 tests fail.** None of the 11 is caused by Part 9.

## Final regression, on the finished code

Groups overlap, because the first and last groups both include Part 9 repair tests, so don't add them up.

| Group | Tests | Failed or error |
| --- | --- | --- |
| Part 9 (`warranty_part9` tag) | 60 | 0 |
| Core, kit, AMC and Part 9 | 216 | 2 |
| Helpdesk | 99 | 4 |
| Field Service | 171 | 3 |
| Material Requests | 107 | 2 |
| Repair and Accounting | 300 | 0 |

## The 11 failures

Each fails the same way when run with the saved pre-Part 9 code. That comparison used the same test database, which already has the Part 9 columns and stored views.

| Test | Result | Cause |
| --- | --- | --- |
| `TestWarrantyPart2.test_01_models_fields_and_sequence` | Fail | Environment: this test database's sequence has passed 99999 |
| `TestWarrantyPart2Monitoring.test_02_snapshot_and_monitoring_dates` | Fail | Hard-coded alert date of 1 Nov 2026 has passed |
| `TestWarrantySettingsHelp.test_01_every_visible_setting_has_help` | Fail | Hard-coded count of 39; was already above that before Part 9, and Part 9 adds 5 settings |
| `TestServiceJobChargeable.test_158_partial_case_approved_items_on_warranty_job` | Error | Test user lacks the Sales rights now required |
| `TestWarrantyCaseEligibility.test_13_serial_rules` | Error | Known since Part 3 |
| `TestSrsServiceFlow.test_b06_closure_and_chargeable_guards` | Fail | Expected refusal no longer raised; not root-caused |
| `TestDraftJobFromService.test_178_locked_and_concurrent_services` | Error | Not root-caused |
| `TestTicketWarrantyVisibility.test_10_site_address` | Fail | Not root-caused |
| `TestWarrantyCase.test_03_create_case_without_services` | Fail | Not root-caused |
| `TestWarrantyCasePayment.test_31_in_payment_partial_and_shared_payment` | Fail | Not root-caused |
| `TestWarrantyMrfCoverage.test_04_decision_logged` | Fail | Not root-caused |

## Defects found and fixed during Part 9

| Defect | Fix |
| --- | --- |
| Patch separated a decorator from `_compute_warranty_card_unit`; `test_07_customer_change` failed | Decorator restored; every inserted method audited |
| Duplicate check fired in the middle of a valid kit serial swap | Kit units use the K4 check on write, and the common check at confirmation |
| Evidence moved with `sudo` could have taken another user's attachment | Only the requester's fresh uploads are accepted |
| Open work could miss a job whose card link wasn't yet written | Search also reads the job's direct card link |

## Trial upgrade on a UAT copy

`wm18_4_p9_check`, from a read-only dump of UAT, using the server's upgrade list. Results: `D:\ODOO\odoo18\backups\wm18_4_p9_trial_20261105_075848`.

| Check | Result |
| --- | --- |
| Upgrade | 24 seconds, no errors, 0 pending |
| Versions | As in the design record |
| Fingerprints | 24 of 28 identical. Card, unit, case and company differ only by new empty columns: identical when those are excluded |
| Accounting | 39 documents, 471,984.57; 8 accounts match UAT |
| WCAS/000042, WCAS/000049, JOB/000036 | 1,520.50, 200.00, 1,520.00 |
| VCL/00006 | Answered; recovered 0, outstanding 200; note Draft |
| Warranty Cost Report | 28 rows, 5,521.00, recovered 0 |
| New data | 0 actions; 0 units with a current site; approvers empty |
| Direct customer edit by a user | Refused |
| Suspend and reactivate, rolled back | Worked; dates unchanged; 0 actions after rollback |
| Active UAT during the run | 0 changes; accounting 18.0.1.6.1, core 18.0.1.1.1 |

## Not tested

- **Browser:** nothing was clicked. Forms were exercised through Odoo's form test tool.
- **Not covered by a test:** cancellation from a credit note; paid extension from an invoice; an issued backup unit blocking correction or transfer; the database index under real concurrent requests; a case Closed by the real Close Case path followed by a repeat complaint (tests set the status directly); import of protected unit fields (card import is tested).
