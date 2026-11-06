# 16 – AMC Test Strategy

## Levels

| Level | Tool | Location | Database |
|---|---|---|---|
| Unit / ORM integration (functional, negative, security, multi-company, scheduler) | `TransactionCase` (`AccountTestInvoicingCommon` base for accounting) | `amc_management/tests/` | `amc_test` (disposable) |
| Warranty integration | `TransactionCase` | `amc_management_warranty/tests/` | `amc_test` |
| End-to-end service chain (Helpdesk → Job → FSM visit → sign-off) | `TransactionCase` with the real FSM timer / worksheet / signature flow | `amc_management_service/tests/` | `amc_test` |
| Non-AMC regression | existing warranty suites, unchanged | `warranty_management*/tests/` | `amc_test` |
| Fresh install | `-i warranty_meta_dependencies` | — | `amc_test` (all modules) and `amc_upg` (AMC only) |
| Upgrade with historical data | 1.0.0 install + seed + `-u` | — | `amc_upg` |
| Migration re-run | direct call of `migrate()` + rollback | scratchpad script | `amc_upg` |

Tags: `post_install`, `-at_install`, `amc`. Command (Git Bash):

```
cd /e/odoo-env/odoo-v18-03022026/server
MSYS_NO_PATHCONV=1 ../python/python.exe odoo-bin -c odoo.conf -d amc_test \
  --test-tags /amc_management,/amc_management_warranty,/amc_management_service \
  --stop-after-init --no-http --log-level=warn --log-handler=odoo.tests.result:INFO
```

## Principles

* Every implementable baseline requirement has at least one traceable test (TC-ID in the
  docstring, requirement IDs alongside).
* Scheduler tests pass an explicit `today` and run twice (idempotency).
* Security tests use real users with only the role under test (`with_user`), never `sudo`.
* The user database `warranty_claim` is never used for testing.
* An unexecuted test is reported as NOT RUN, never as PASS.

## Out of automated scope (manual UAT)

Browser rendering of the new views, PDF via wkhtmltopdf (HTML rendering is tested), MRF / chargeable
/ cost processes on AMC jobs (reused, not AMC-specific), Helpdesk SLA configuration on the AMC tag.
