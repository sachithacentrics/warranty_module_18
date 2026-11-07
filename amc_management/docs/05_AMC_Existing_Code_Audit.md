# 05 – Existing Code Audit (amc_management 18.0.1.0.0)

Audited 2026-11-06: repository `warranty_module_18` (branch `main`, HEAD `b9f7c8a`), module
`amc_management` 18.0.1.0.0, compared with `C:\Users\Sacitha\Downloads\amc_management 1.zip`
(identical code; the repository copy only adds 3,060 blank lines to `amc_pricing_formula.py` and
differs in line endings).

## 1. Inventory

| Component | Content | Assessment |
|---|---|---|
| `__manifest__.py` | depends mail, product, sale_management, stock; phases A1–A3 | Valid; dependencies minimal and real |
| `amc.plan` | identity, applicability (pricelists, products, categories), period / usage basis, visit count + frequency, free services, pricing method, billing plan, start rule, duration, renewal rule, activation trigger, alert days | Complete for A1; `pricelist_ids` not enforced (DEF-04) |
| `amc.billing.plan` (+ 4 data records) | frequency, timing, interval | Complete; not used by any billing logic (A5 missing) |
| `amc.pricing.formula` / tier / factor / rounding | 8 methods, controlled Hybrid (`amc_safe_expression`), versions, effective dates, lock, activation with overlap handling, currency conversion, min / max, rounding, preview | Complete and well designed; DEF-01 (factor lock), DEF-06 (blank lines); duplicate tier methods |
| `amc_safe_expression` | AST whitelist (numbers, approved names, + − * /, unary ±, min / max / round / abs), 500-char limit, no eval | Secure; no attribute / subscript / power / call of other names |
| `amc.opportunity` | New / Offer Sent / Won / Lost, Create Contract | Complete |
| `amc.contract` / line | customer, site, plan, equipment (product, serial, qty, site, value + currency), pricing snapshot, override, quotation, activation trigger; protected fields via Python marker | Complete for A3; DEF-02, DEF-03, DEF-05, DEF-07, DEF-08; states On Hold / Expiring / Renewed / Closed unreachable |
| `amc.price.override` | price / pricelist override, approver ≠ requester, audit-protected | Complete |
| `sale.order` / line | AMC quotation lock (no edit / copy / extra lines), confirm / cancel hooks | Correct and scoped by `amc_contract_id` |
| `res.company` / settings | AMC defaults, activation trigger, AMC product | Valid; `amc_enabled` not used anywhere (made functional in 18.0.1.3.0, see 26) |
| Wizards | price preview, cancel reason | Valid |
| Security | groups User → Coordinator → Manager, Approver; ACL; multi-company record rules for all models | Valid |
| Views / menus | plans, formulas, billing plans, opportunities, contracts, overrides, settings | Valid Odoo 18 syntax (`<list>`, `invisible=`, `<chatter/>`) |
| Sequences | AMCO/, AMC/, AMCR/ | Valid |
| Tests | **none** in the repository (earlier session reports mention AMC tests that are not present) | Gap |

## 2. Classification

| Item | Status |
|---|---|
| Plans, billing plans, settings, opportunities, overrides, pricing engine, safe expression, quotation flow | Fully implemented but untested (now covered by `test_amc_pricing.py`, `test_amc_lifecycle.py`) |
| Factor lock | Implemented incorrectly (DEF-01) |
| Usage-based contract price | Implemented incorrectly (DEF-02) |
| End date | Implemented incorrectly (DEF-03) |
| Pricelist applicability | Partially implemented (DEF-04) |
| Activation On Payment | Missing (DEF-05) |
| Entitlements / visits, alerts, missed, next visit | Missing (phase A4) |
| Billing schedule, invoicing | Missing (phase A5) |
| Hold, Expiring, Renew, Close, scheduler | Missing (phase A6); states unreachable |
| Visit Schedule report | Missing |
| Warranty / service-chain integration | Missing (planned bridges) |
| Duplicate tier create/write/unlink | Duplicate |
| `amc_enabled` | Unused in 1.0.0; on / off switch since 18.0.1.3.0 |

## 3. Security / quality observations

* No `sudo()` misuse; the only SQL (`SELECT … FOR UPDATE NOWAIT`) is parameterized.
* Protected-field markers are Python objects that cannot be sent through RPC – a sound pattern,
  reused in 1.1.0.
* All user-facing messages translated with `_()` and named placeholders.
* No onchange used for invariants; constraints at ORM level.
