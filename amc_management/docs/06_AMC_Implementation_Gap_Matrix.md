# 06 – Implementation Gap Matrix (state of 1.0.0 → action taken in 1.1.0)

| Req. | Existing implementation (1.0.0) | Location | 1.0.0 status | Action (1.1.0) |
|---|---|---|---|---|
| A01 | Separate module | `amc_management` | Complete | Retain |
| A02 | Warranty `warranty_scope_mode` (unused after BA decision) | `warranty_management/models/res_company.py` | Superseded | None |
| A03 / A04 | — | — | Missing | Develop (`amc_management_warranty`: `amc_auto_create_mode`, `action_confirm_warranty` hook) |
| A05 | SO confirmation activation; payment → stuck | `sale_order.py`, `amc_contract._amc_on_order_confirmed` | Partial / defective (DEF-05) | Extend (billing schedule, `account.move._invoice_paid_hook`) |
| A06 | Lines with product / serial; no warranty unit | `amc.contract.line` | Partial | Extend (`warranty_unit_id`) |
| A07 / C07 / X01 | — | — | Missing | Develop (Convert to AMC, source card, expiry offer) |
| A08 | Case type AMC → always manual review | `warranty_management_helpdesk/.../warranty_case.py:1109` | Partial | Extend in bridge (`_warranty_run_checks` for AMC cases) |
| A09 | Opportunities, Contracts, Overrides, Configuration menus | `views/amc_management_menus.xml` | Partial | Extend (Quotations, Renewals, Services, Reporting menus; smart buttons) |
| B01, B04, B05, B06 (config), B07 | Plan fields, constraints | `amc_plan.py` | Complete (untested) | Retain + tests; snapshot fix DEF-03 |
| B02 | `pricelist_ids` stored only | `amc_plan.py` | Partial (DEF-04) | Fix |
| B03 | `_amc_line_problems` | `amc_contract.py` | Complete (untested) | Retain + test TC-106 |
| B06 (entitlements) | summary text only | `amc_contract.py` | Missing | Develop (`amc.contract.visit`) |
| B08 | `renewal_rule` selection only | `amc_plan.py` | Partial | Extend (notice days, Renew, auto offer) |
| B09 | Billing plan, quotation lines per period | `amc_billing_plan.py`, `_amc_quotation_lines` | Partial | Extend (`amc.billing.line`) |
| B10 | `amc_visit` service type, `amc` case type | warranty modules | Complete | Reuse |
| B11 | Contract / line site, site pricing | `amc_contract.py`, formula `site` | Complete | Retain; visit site |
| C01 | Create / reissue quotation | `amc_contract.py` | Complete | Retain |
| C02 | 9 states defined; 4 unreachable | `CONTRACT_STATES` | Partial | Develop transitions |
| C03 | No entitlements at all | — | n/a | Develop (generation only at activation) |
| C04 / C05 | — | — | Missing | Develop (hold / resume / close / expiring / renewed) |
| C06 | Manual contract | `amc.contract` | Complete | Retain |
| D01–D10, D12 | Engine, safe expression, preview | `amc_pricing_formula.py`, `amc_safe_expression.py`, `wizard/amc_pricing_preview.py` | Complete (untested) | Retain + tests TC-100 … TC-104 |
| D07 | Contract usage ignored | `action_compute_price` | Defective (DEF-02) | Fix |
| D11 | Versioning / lock; factors unlocked | `amc_pricing_formula.py`, `amc_pricing_factor.py` | Defective (DEF-01) | Fix |
| D13 / H06 | Override approval | `amc_price_override.py` | Complete (untested) | Retain + test TC-105 |
| E01–E10 | — | — | Missing | Develop |
| F01–F07, F11 | Warranty chain exists (cases, jobs, FSM, worksheets, sign-off) | warranty modules | Reusable, no AMC link | Develop bridge `amc_management_service` |
| F08–F10 | MRF / chargeable / cost processes on Service Jobs | warranty modules | Reusable | Reuse |
| F12 | Helpdesk SLA | Odoo | Reusable | AMC ticket tag |
| F13 / H01 | — | — | Missing | Develop visit views + report |
| G01–G04 | Quotation + trigger only | `amc_contract.py` | Partial | Develop billing schedule + invoicing button |
| G05 | Warranty chargeable flow | warranty modules | Reusable | Reuse |
| G06 | Engine controls | formula | Complete | Retain |
| H02 / H04 | — | — | Missing | Develop links (case, ticket, job, task, worksheet) |
| H03 | Groups + ACL | `security/` | Complete | Extend ACL for new models |
| H05 | Chatter + protected fields | all models | Complete | Extend to new models |
| NFR-01 | Record rules | `security/<model>_security.xml` | Complete | Extend to new models |
