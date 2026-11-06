# 28 – AMC Final Delivery Report (2026-11-06)

## A. Executive summary

* **Objective:** complete the Annual Maintenance Contract solution of the warranty SRS (AMC as a
  separate module) for Odoo 18 without changing non-AMC behaviour.
* **Original status:** `amc_management` 18.0.1.0.0 covered phases A1–A3 (plans, pricing engine,
  opportunities, contracts, overrides, quotation). No entitlements, billing, lifecycle after
  activation, report, warranty or service integration, no tests; 9 defects (DEF-01 … DEF-09), one of
  them critical (contracts on payment trigger could never become Active).
* **Final status:** `amc_management` 18.0.1.1.0 (phases A4–A6) + two new bridges
  `amc_management_warranty` and `amc_management_service` (18.0.1.0.0), migration, 63 automated tests,
  29 documents and a Word user manual with screenshots.
* **Architecture decisions (approved by the user):** standalone AMC core; integrations in bridges
  that only inherit the warranty models and act on AMC-linked records; AMC billing schedule on
  standard Sales Order lines (no Subscriptions); conservative documented defaults AS-01 … AS-08 for
  rules the SRS leaves open.

## B. Requirement coverage (80 baseline requirements, see 25)

| Category | Count |
|---|---|
| Already complete in 1.0.0 (retained, now tested) | B01, B03, B05, B10, B11, C01, C06, D01–D10, D12, D13, G06, H03 |
| Corrected (defects DEF-01 … DEF-09) | A05, B02, B07, D07, D11 |
| Newly implemented | all other implemented requirements (phases A4–A6, warranty and service bridges) |
| Implemented and tested (total) | 70 |
| Implemented, UI rendering to be confirmed in UAT | 2 (A09, F13) |
| Partially implemented (reuse of existing warranty processes not verified for AMC, or configuration-based) | 7 (E05, F08, F09, F10, F11, F12, G05) |
| Blocked | 0 |
| Superseded | 1 (A02, BA decision 2026-10-28) |
| Not applicable | 0 |

## C. Development summary

| Req. | Component | File | Method / XML ID | Change |
|---|---|---|---|---|
| E01–E10, B06, C03 | entitlements | `amc_management/models/amc_contract_visit.py` | `amc.contract.visit`, `_amc_consume`, `_cron_amc_visits` | new model |
| B09, G01–G04, A05 | billing | `models/amc_billing_line.py`, `models/account_move.py`, `models/amc_contract.py` | `amc.billing.line`, `_invoice_paid_hook`, `_amc_generate_billing`, `_amc_schedule_billing`, `action_create_invoice` | new |
| C02, C04, C05, B08 | lifecycle | `models/amc_contract.py` | `_amc_activate`, `_amc_hold`, `action_resume`, `_amc_check_expiring`, `action_renew`, `_amc_close`, `_amc_mark_renewed`, `_cron_amc_daily` | new |
| B07, D07, B02, D11 | defects | `models/amc_contract.py`, `models/amc_pricing_factor.py`, `models/amc_pricing_rounding.py`, `models/amc_pricing_formula.py` | `contract_months`, `expected_usage`, pricelist check, factor lock, `_` import, cleanup | fixed |
| H01, F13 | report / views | `views/amc_contract_visit_views.xml`, `report/amc_contract_reports.xml` | `amc_contract_visit_action_schedule_report`, `amc_contract_action_report_visit_schedule` | new |
| A09 | menus / actions | `views/amc_management_menus.xml`, `views/amc_contract_views.xml` | Quotations, Renewals, Services, Reporting; smart buttons | extended |
| — | data / security | `data/ir_cron_data.xml`, `data/ir_sequence_data.xml`, `security/*` | `ir_cron_amc_daily`, `seq_amc_contract_visit`, ACL, rules | new |
| — | migration | `migrations/18.0.1.1.0/post-migrate.py` (removed in 18.0.1.2.0) | `migrate` | removed |
| A03, A04, A06, A07, C07, X01 | warranty bridge | `amc_management_warranty/models/*` | `_amc_auto_create`, `action_convert_to_amc`, `warranty_unit_id`, `_warranty_apply_expiry` | new module |
| A08, F01–F07, F12, H02, H04 | service bridge | `amc_management_service/models/*`, `wizard/*` | `amc.service.request`, `_amc_run_checks`, job hooks, `amc_pending_visit_ids`, `helpdesk_tag_amc` | new module |
| — | meta module | `warranty_meta_dependencies/__manifest__.py` | depends | both bridges added |

## D. Testing summary

| Area | Result |
|---|---|
| Automated AMC tests | **63 / 63 PASS** (46 core, 9 warranty link, 8 service chain) – 18 |
| Functional workflow coverage | full lifecycle Draft → Renewed / Closed / Cancelled, both activation triggers, all billing frequencies, visits incl. usage, alerts, missed, carry-forward – 17, 19 |
| End-to-end | 6 scenarios incl. Helpdesk → Service Job → FSM visit → sign-off → consumption – 19 |
| Security | role matrix, RPC protection, separation of duties – PASS |
| Multi-company | isolation and cross-company refusal – PASS |
| Installation | fresh install of the complete stack (`amc_demo`) and of the core alone (`amc_upg`) – PASS |
| Upgrade | genuine 1.0.0 → 1.1.0 with historical data, values identical, migration idempotent – PASS |
| Non-AMC regression | 866 warranty tests with AMC installed: 860 PASS, 6 failing tests **identical on a database without any AMC module** (pre-existing) – 20 |
| Manual UAT | TC-M01 … TC-M04 NOT RUN (UAT) |

## E. Non-AMC impact assessment

* **Shared models modified (by inheritance, scoped to AMC records):** `sale.order`,
  `sale.order.line` (1.0.0), `account.move`, `res.company`, `res.config.settings`, `warranty.card`,
  `warranty.unit`, `warranty.case`, `warranty.service.job`, `helpdesk.ticket`.
* **Related addons analysed:** warranty_management, _helpdesk, _fsm, _mrp, _mrf, _accounting,
  _repair, material_purchase_requisitions (read only).
* **Unrelated addon files changed:** none, except the depends list of `warranty_meta_dependencies`.
* **Regression-tested non-AMC workflows:** full warranty suites (866 tests) + TC-070, TC-072,
  TC-080, TC-083, TC-097.
* **Remaining risk:** low – the reused MRF / chargeable / cost processes on AMC jobs (K-10) and
  browser interaction (K-09) are left to UAT.

## F. Documentation inventory

`amc_management/docs/`: 00 – 28 (Markdown) and **`AMC_User_Manual.docx`** (30 pages, 37 screenshots,
table of contents). Index: `00_AMC_Documentation_Index.md`.

## G. Deployment recommendations

See 24: backup (dump + filestore) → trial upgrade on a restored copy → `-u amc_management -i
amc_management_warranty,amc_management_service` (or `-u warranty_meta_dependencies`) → configure
Settings > AMC (Activation Trigger, Auto-create Mode, Offer on Expiry), plan planning / grace /
renewal fields, AMC SLA policy, Draft Job Helpdesk Team, Warranty Worksheet templates → check the
daily scheduler → smoke tests (24 §3). Rollback: restore dump and filestore. Note: with the service
bridge, AMC visits are completed only through Service Jobs.

## H. Known issues and blockers

No known critical or high-severity defect. Open items (27): business confirmation of AS-01 … AS-08
(K-01); limitations K-02 … K-08, K-13; UAT gaps K-09 – K-11; mapping document unavailable (K-12);
read access of technicians to AMC contract values (K-14). Six pre-existing warranty test failures
(20) belong to the warranty modules.

**Not committed or pushed** (user instruction): all changes are in the working tree of
`warranty_module_18`. Disposable databases created: `amc_test`, `amc_upg`, `wm_base`, `amc_demo`
(keep or drop on request).

## I. Final readiness decision

**READY FOR UAT** – implementation complete for all unblocked baseline requirements, 63 / 63
automated tests, install / upgrade / migration verified, no AMC-caused regression. Business
acceptance of the assumptions AS-01 … AS-08 and the UAT cases TC-M01 … TC-M04 remain before a
production deployment review.
