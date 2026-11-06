# 26 – AMC Change Log

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
`/amc_management/user_manual` (`controllers/main.py`; kept out of `/static`, which is public); test
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
