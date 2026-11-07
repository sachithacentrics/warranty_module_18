# 18 – AMC Automated Test Results

**Executed:** 2026-11-06, database `amc_test` (disposable; Odoo 18 with Enterprise, all warranty
addons, `amc_management` 18.0.1.1.0, `amc_management_warranty` and `amc_management_service`
18.0.1.0.0, demo data), command:

```
MSYS_NO_PATHCONV=1 ../python/python.exe odoo-bin -c odoo.conf -d amc_test \
  -u amc_management,amc_management_warranty,amc_management_service \
  --test-tags /amc_management,/amc_management_warranty,/amc_management_service \
  --stop-after-init --no-http --log-level=warn --log-handler=odoo.tests.result:INFO
```

**Final result:** `0 failed, 0 error(s) of 63 tests` (log `test_final_2.log`). Re-run on 2026-11-07 (18.0.1.3.0, AMC Enabled switch): `0 failed, 0 error(s) of 68 tests` (65 functional + 3 documentation tests).

| Suite | File | Tests | Result |
|---|---|---|---|
| Lifecycle (functional, negative, scheduler) | `amc_management/tests/test_amc_lifecycle.py` | 28 | PASS |
| Pricing, governance, override (D01–D13) | `amc_management/tests/test_amc_pricing.py` | 9 | PASS |
| Security, multi-company, non-AMC regression | `amc_management/tests/test_amc_security.py` | 10 | PASS |
| Warranty link | `amc_management_warranty/tests/test_amc_warranty.py` | 10 | PASS |
| Service chain end-to-end | `amc_management_service/tests/test_amc_service_chain.py` | 8 | PASS |
| **Total** | | **63** | **63 PASS** |

| Test ID | Requirement | Scenario (see 17) | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-001 … TC-005 | D11, D07, B07, B02, E01 | defect regressions | refused / correct values | as expected | PASS |
| TC-010 … TC-013 | C03, E01, E02, B04–B06, E10 | entitlement generation | as specified | as expected | PASS |
| TC-020 … TC-024 | E03–E09 | visits, planning, alerts, missed | as specified | as expected | PASS |
| TC-030 … TC-034 | B09, G01–G04, A05 | billing, payment activation | as specified | as expected | PASS |
| TC-040 … TC-048 | C02, C04, C05, B07, B08, H01, H05 | lifecycle, report | as specified | as expected | PASS |
| TC-050 … TC-052 | H03, H05 | roles, RPC protection | refused outside role | as expected | PASS |
| TC-060 … TC-063 | NFR-01, E03, AMC Enabled | multi-company, AMC Enabled switch | isolated | as expected | PASS |
| TC-070 … TC-072 | REG-01, REG-02 | regular SO / invoice | standard | as expected | PASS |
| TC-080 … TC-089 | A03, A04, A06–A08, C07, E09, X01, NFR-03, AMC Enabled | warranty link | as specified | as expected | PASS |
| TC-090 … TC-097 | F01–F07, A08, C04, H02, H04, REG-04 | service chain | as specified | as expected | PASS |
| TC-100 … TC-108 | D01–D13, B03, C02, G06 | pricing, governance | as specified | as expected | PASS |
| TC-M01 … TC-M04 | A09, F08–F10, F12, F13, H01 | manual UAT | — | — | NOT RUN (UAT) |

## Defects found by the tests during development (fixed before the final run)

| Found by | Defect | Fix |
|---|---|---|
| TC-013, TC-020, TC-032 | `_()` reserves the keyword `source` (TypeError in the completion log) | placeholder renamed |
| TC-030, TC-033 | draft invoice has no `name` (TypeError in the invoice log) | `display_name` |
| TC-090 | Helpdesk / FSM users could not read AMC visits of their own cases | read ACL in the service bridge |
| static review | DEF-09 missing `_` import in rounding rules | import; TC-108 |

Test-only corrections (assertions that were wrong, not the code): TC-051 (record rule of the
salesman; refusal by the write guard), TC-096 (free services are pending too), TC-103 (approved
P1 auto-end rule), TC-020 (core manual completion isolated from the service bridge).
