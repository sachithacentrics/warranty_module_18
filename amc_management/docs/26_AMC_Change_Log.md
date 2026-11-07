# 26 – AMC Change Log

## Upgrade fix (2026-11-07) – XML id migration

Odoo.sh staging databases already contain an AMC version from before the coding standards
(18.0.1.0.0 / 18.0.1.1.0). The renamed XML ids made the upgrade create the AMC groups a second
time (`res_groups_name_uniq`: "User" of the AMC category). Pre-migration scripts now rename the
old XML ids, so the records are kept and updated in place (users keep their AMC groups):
* `amc_management/migrations/18.0.1.3.0/pre-migrate.py`: 63 ids (groups, record rules, actions,
  menus, views, access rights of the transient models); removes the inheriting view
  `amc_plan_view_form_pricing` (merged into the plan form).
* `amc_management_service/migrations/18.0.1.1.0/pre-migrate.py`: 3 ids.
* Verified: upgrade from 18.0.1.1.0 (#8, all three modules) – 68 / 68 AMC tests pass during the
  upgrade; upgrade from 18.0.1.0.0 (#1) – 50 / 50 core tests pass. Idempotent (renames only when
  the old id exists and the new one does not).

## 18.0.1.3.0 / amc_management_warranty 18.0.1.2.0 (2026-11-07) – AMC Enabled switch

The company setting **AMC Enabled** (until now stored only, K-08) works as an on / off switch:
* Off: the AMC Management application (all its menus) is hidden in that company
  (`ir.ui.menu.load_menus`, active company of the company switcher).
* Off: no new AMC opportunity or contract can be created in that company
  (`res.company._amc_check_enabled`); renewals of existing contracts are still allowed.
* Off (warranty bridge): no AMC auto-create after warranty confirmation, no "offer an AMC"
  to-do on warranty expiry, **Convert to AMC** hidden on the warranty card and refused.
* Existing contracts are not touched: visits, billing, renewals, service requests and the
  scheduler continue. Tests TC-063, TC-089.

## 18.0.1.2.0 / bridges 18.0.1.1.0 (2026-11-06) – coding standards

Structure only, no functional change (all AMC tests unchanged and passing):
* License OPL-1 (all three modules); migration script removed (not in production).
* One class per Python file, named after the model: `amc_contract_line.py`,
  `amc_contract_visit.py` (was `amc_visit.py`), `amc_pricing_tier.py`, `sale_order_line.py`;
  bridges `amc_contract_line.py`, `res_config_settings.py`, `warranty_unit.py`.
* Transient models in `wizard/` without "wizard" in names: `amc.opportunity.lost`,
  `amc.contract.cancel`, `amc.contract.reason`, `amc.contract.visit.action`,
  `amc.price.override.reject`, `amc.service.request`; each with `<transient>_views.xml`.
* Security: `amc_management_groups.xml` (groups `amc_management_group_user / _coordinator /
  _manager / _approver`) and one `<model>_security.xml` per model (`<model>_rule_company`).
* Views per model (`amc_price_override_views.xml`, `amc_contract_visit_views.xml`, bridge
  `amc_opportunity_views.xml`, `warranty_service_job_views.xml`); model menus inside the model
  views file, root / section / document menus in `amc_management_menus.xml`; price-formula page
  of the plan form merged into `amc_plan_view_form`.
* XML ids: actions `<model>_action[_detail]`, menus `<model>_menu[_detail]`, inheriting views use
  the inherited id (`view_order_form`, `res_config_settings_view_form`,
  `helpdesk_ticket_view_form_warranty`) with name `<model>.view.<type>.inherit.<module>`.
* Data split: `ir_sequence_data.xml`, `product_product_data.xml`, `ir_cron_data.xml`; report
  split: `report/amc_contract_reports.xml` + `amc_contract_templates.xml`; controller
  `controllers/amc_management.py`.

## amc_management 18.0.1.1.0 (2026-11-06) – phases A4–A6

**Added**
* `amc.contract.visit`: AMC entitlements (preventive visits per covered unit, included free
  services), due / overdue / missed monitoring, alerts, manual planning / completion with usage,
  cancel / reopen, visit views (list, kanban, calendar, pivot, graph), AMC Visit Schedule report
  (menu + PDF).
* `amc.billing.line`: billing schedule from the Billing Plan, release to SO delivered quantities,
  Create Invoice; activation on payment (`account.move._invoice_paid_hook`).
* Contract lifecycle: On Hold / Resume, Expiring (renewal notice, Auto Offer), Renew (linked
  renewal), Close, Renewed; daily scheduler `ir_cron_amc_daily`.
* Plan fields: Visit Planning, Grace Period, Mark Missed After Grace Period, Renewal Notice.
* Contract fields: Expected Usage, Duration snapshot, entitlement balances, next visit, lifecycle
  reasons / dates, renewals; smart buttons Invoices / AMC Visits / Renewals; menus Quotations,
  Renewals, Services, Reporting.
* Migration `18.0.1.1.0/post-migrate.py`; automated tests (`tests/`, 46 tests); documentation
  `docs/`.

**Fixed**
* DEF-01 factor lock of Active formula versions; DEF-02 usage-based contract price; DEF-03 end date
  moved by plan edits; DEF-04 plan pricelist applicability; DEF-05 Awaiting Payment never activated;
  DEF-06 blank-line bloat; DEF-07 NOWAIT lock; DEF-08 activation with the confirming user's rights;
  DEF-09 missing `_` import in target-currency rounding rules (NameError instead of the message).

**In-app User Manual:** menu *Configuration > Documents > User Manual* (AMC users) opens the HTML
manual (`manual/amc_user_manual.html`, screenshots embedded, sidebar navigation with active section,
topic search, chapter pager, image zoom, responsive / print layout) through the login-protected route
`/amc_management/user_manual` (`controllers/amc_management.py`; kept out of `/static`, which is public); test
TC-110.

**In-app Technical Architecture:** menu *Configuration > Documents > Technical Architecture* opens
the HTML version of `AMC_Technical_Architecture.docx` (`manual/amc_technical_architecture.html`,
diagrams embedded, same navigation as the manual) through `/amc_management/technical_architecture`
(AMC users only); test TC-112.

**Process recording:** menu *Configuration > Documents > Process Recording (Video)* opens a player
page (`manual/amc_process_video.html`) for the screen recording of the complete AMC process
(`manual/amc_process.mp4`, H.264 1440x900, 4:28, 12 chapters: configuration, contract, quotation
and activation, billing, AMC visits and service request, Helpdesk case and Service Job, Field
Service completion, hold / expiry / renewal, warranty to AMC, reports). Routes
`/amc_management/process_video`, `/file` (private, seekable HTTP range stream) and `/poster`, AMC
users only; test TC-111.

**UI fixes after the screenshot review:** readable name of covered equipment lines (was
`amc.contract.line,<id>`); user manual `docs/AMC_User_Manual.docx`.

## amc_management_warranty 18.0.1.0.0 (new)
AMC Auto-create Mode, Convert to AMC, Offer AMC on Warranty Expiry, warranty units on covered
equipment, source warranty card, smart buttons; 9 tests.

## amc_management_service 18.0.1.0.0 (new)
Create Service Request (ticket + AMC case), AMC eligibility, Service Job / worksheet / completion /
cancellation hooks, Pending AMC Services on tickets, AMC ticket tag, read access for Helpdesk / FSM
users; 8 tests. Wizard label "Customer"; ticket title "3 x Preventive Visit 1 of 3".

## warranty_meta_dependencies
Depends on the two bridges as well.
