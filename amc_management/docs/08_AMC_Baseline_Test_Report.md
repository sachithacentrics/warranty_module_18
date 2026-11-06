# 08 – AMC Baseline Test Report (before development, 2026-11-06)

| Item | Baseline |
|---|---|
| Git | repository `warranty_module_18`, branch `main`, HEAD `b9f7c8a` (`staging_release_11062026_#2`); working tree: only untracked `__pycache__/` folders (no uncommitted user changes) |
| Odoo | `E:\odoo-env\odoo-v18-03022026\server\odoo-bin`, Python `E:\odoo-env\odoo-v18-03022026\python\python.exe`, config `server\odoo.conf` (addons: Odoo 18 incl. Enterprise + `warranty_module_18`) |
| Databases | `warranty_claim` (user's database: all warranty addons + AMC 1.0.0, **0 AMC records**, 0 warranty cards, 2 companies) – not used for testing. Created for this work: `amc_test` (all addons, disposable), `amc_upg` (AMC only, upgrade test) |
| Installed AMC version | 18.0.1.0.0 |
| AMC tests | **none present** in the repository (an earlier handoff mentions AMC tests in another environment; they are not in this repository) → AMC baseline tests: NOT AVAILABLE |
| Fresh install 1.0.0 | `amc_upg`: `-i amc_management` (original zip copy) – success |
| Functional baseline (manual run of 1.0.0 code on `amc_upg`) | Draft / Quotation / Active (SO confirmation) / Awaiting Payment contracts created successfully; Awaiting Payment cannot progress (DEF-05); no visits / billing (phases A4–A6 missing) |
| Warranty regression baseline | Not run on this machine before the change (the user database could not be used and no pre-change copy with the full warranty stack existed). The earlier handoff reports 464 tests / 1 known error (`test_13_serial_rules`) in another environment. The regression on `amc_test` (doc 20) is therefore analysed failure by failure for AMC relation. |

Workflows that must remain unchanged: warranty card creation / confirmation / expiry, warranty cases
and eligibility, service jobs (case- and service-origin), FSM visits / worksheets / completion /
reschedule / cancel, MRF, repair, accounting provisions, regular Sales Orders and invoices.
