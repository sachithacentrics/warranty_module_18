# 21 – AMC Installation and Upgrade Test Report

Executed 2026-11-06 with `E:\odoo-env\odoo-v18-03022026\server\odoo-bin` (Odoo 18) and
`server\odoo.conf`. User database `warranty_claim` was **not** used.

| # | Check | Database / command | Result |
|---|---|---|---|
| 1 | Python import integrity | `py_compile` all files; module loading | PASS |
| 2 | XML parsing | `lxml` all XML; view validation at install | PASS |
| 3 | External ID resolution | install / upgrade (views, actions, menus, report, cron, ACL) | PASS |
| 4 | Security files loading | install / upgrade | PASS |
| 5 | Manifest dependencies | `amc_management` alone on `amc_upg` (no warranty modules) | PASS |
| 6 | Fresh installation – AMC core only | `amc_upg`: original 1.0.0 → see 7; core 1.1.0 standalone via upgrade | PASS |
| 6b | Fresh installation – complete stack (final code) | `amc_demo`: `-i warranty_meta_dependencies` (installs AMC 1.1.0 + both bridges + all warranty addons) | see §1 |
| 7 | **Upgrade 1.0.0 → 1.1.0 with historical data** | `amc_upg`: 1.0.0 installed from the original zip copy, seeded with the 1.0.0 code (Draft, Quotation, Active 10 units quarterly, Awaiting Payment), `-u amc_management` | PASS (details in 14 §5) |
| 8 | Existing-data preservation | contract values diff before / after | PASS – identical |
| 9 | Migration re-run | `migrate()` called again, counts compared, rolled back | PASS – idempotent |
| 10 | Scheduled action registration | `ir_cron_amc_daily` present and active after install / upgrade | PASS |
| 11 | Bridge installation on an existing database | `amc_test`: `-i amc_management_warranty`, `-i amc_management_service` | PASS |
| 12 | View rendering | form / list / search views validated by Odoo at load; browser rendering = UAT (TC-M01); screenshots of all screens taken on `amc_demo` for the user manual | PASS (load) |
| 13 | Report generation | QWeb HTML rendering (TC-047); PDF through wkhtmltopdf = UAT (TC-M04) | PASS (HTML) |
| 14 | Automated tests | 63 AMC tests (18) | PASS |

## 1. Fresh installation of the complete stack (`amc_demo`)

`odoo-bin -c odoo.conf -d amc_demo -i warranty_meta_dependencies --stop-after-init` on a new
database: **return code 0, 0 ERROR / CRITICAL log lines**; installed `amc_management` 18.0.1.1.0,
`amc_management_warranty` 18.0.1.0.0, `amc_management_service` 18.0.1.0.0,
`warranty_meta_dependencies` 18.0.1.0.0. The database was then filled with demonstration data
(plans, formulas, opportunity, Draft / Quotation / Awaiting Payment / Active / Expiring / On Hold
contracts, override request, AMC service request → approved case → confirmed Service Job, warranty
card) and served on a temporary port; all 37 screens of the user manual were opened in headless
Chrome without error (doc `AMC_User_Manual.docx`). This also covers check 12 (view rendering) for
the screens shown in the manual. A later `-u amc_management,amc_management_service` on the same
database (UI fixes) also succeeded.
