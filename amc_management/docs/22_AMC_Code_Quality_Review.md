# 22 – AMC Code Quality Review

Reviewed: all added / modified files of `amc_management` 1.1.0, `amc_management_warranty`,
`amc_management_service` against the Odoo 18 coding guidelines.

## Checks executed

| Check | Tool | Result |
|---|---|---|
| Python compilation | `py_compile` over all files | pass |
| XML well-formedness | `lxml` over all XML | pass |
| View validation, external IDs, ACL / rule loading | Odoo install / upgrade (`-i` / `-u`) | pass, no errors / warnings from the AMC modules |
| Unused imports / missing `_` import | custom AST check (pyflakes / flake8 not installed) | found **DEF-09** (`_` missing in `amc_pricing_rounding.py`, 1.0.0) and 3 unused imports – fixed |
| Automated tests | Odoo test runner | see 18 / 20 |

## Python

* Imports ordered stdlib → odoo → odoo.addons → relative; no wildcard imports.
* Models named `amc.<object>` with `_description`; fields with `string` / `help`; Many2one
  `ondelete` chosen explicitly (cascade for children, restrict for history links).
* Batch-safe `create` (`@api.model_create_multi`), loops over recordsets, `ensure_one()` only where
  the method is a single-record action.
* Stored computes declare complete `@api.depends`; snapshots (`contract_months`) intentionally
  depend on `plan_id` only (documented).
* Business invariants in `write` guards / `@api.constrains`, never in onchange.
* `UserError` / `ValidationError` / `AccessError` with translated, named-placeholder messages
  (one bug found and fixed: `_()` reserves the keyword `source`).
* `sudo()` only after an explicit group check or for system side effects of an authorized event,
  each with a comment.
* SQL: one parameterized `SELECT … FOR UPDATE` row lock (`_amc_lock`); no other SQL.

## XML

* Odoo 18 syntax: `<list>`, `invisible` / `readonly` / `required` expressions, `<chatter/>`,
  `<setting>`, kanban `t-name="card"`.
* Inherited views use XPath on stable anchors (`button_box`, `header`, `notebook`, named fields /
  pages); no full view replacement; inherited view ids follow `<model>.view.<type>.inherit.<module>`.
* Existing external IDs preserved; new data in `noupdate` where user-editable (sequences, cron, tag).

## Security

* ACL for each new model; record rules on `company_id`; protected fields refuse UI, import and RPC
  writes (Python marker objects cannot be sent by clients).
* The Hybrid expression engine never uses `eval` / `safe_eval` (AST whitelist, length limit).

## Performance

* Daily cron: searches with stored, indexed fields (`state`, `contract_state`, `due_date`,
  `alert_date`, `grace_end_date`); writes only on change (`_amc_refresh_due_status`).
* No search inside large loops except serial / unit conflict checks per line (bounded by contract
  size) and the ticket pending-visit compute (one search per ticket).
* Stored statistics on the contract avoid recomputation in list views.

## Architecture

* AMC core stays standalone; integrations isolated in two bridges that only extend the warranty
  modules through inheritance and act only on AMC-linked records.
* Extension points (`_amc_manual_completion_allowed`, `_amc_check_not_in_service`,
  `_amc_renewal_values`) keep the bridges thin.
* No unrelated addon file was changed except `warranty_meta_dependencies/__manifest__.py`
  (depends list).
