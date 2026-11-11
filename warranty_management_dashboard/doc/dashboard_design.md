# Warranty Dashboard – design record (18.0.1.0.7, 2026-11-11)

History: first version 18.0.1.0.0 approved 2026-11-08 (KPI cards, charts, cost / recovery /
reserve). **SRS simplification approved 2026-11-11**: the dashboard shows exactly the five
areas of SRS 15 "Warranty Dashboard" with its filters; the expiry trend, Failure Patterns,
replacement / repeated-failure trend and the Cost / Recovery / Reserve section were removed
(not part of the SRS dashboard; the full reports stay under Warranty > Reports). The four
Warranty > Reports > Warranty & Entitlements menus were removed the same day (18.0.1.0.4).

Presentation layer only: no business model, calculation or workflow of its own; opening or
refreshing the dashboard writes nothing. No change to any warranty, MRF, accounting, repair,
Helpdesk, Field Service or AMC module.

## SRS 15 compliance

| SRS 15 "Warranty Dashboard" | Dashboard | Source (existing data) | Drill-down |
|---|---|---|---|
| Warranty status | Warranty Status: Active today (or In force in period), Expiring within 30 / 60 / 90 days (or Ending in period), cards by status | `warranty.card` state and warranty dates | Warranty Cards |
| Pending services | Pending Services: open services, overdue, by due indicator | `warranty.service.entitlement` in OPEN_STATES, existing Due Indicator | Service Entitlements |
| Approvals | Approvals: total waiting, one line per document type | the existing waiting states (see `APPROVALS`) | each document's list |
| Replacements | Replacements: open, awaiting approval | `warranty.replacement` Draft / Submitted / Approved; Submitted | Replacements |
| Escalations | Escalations: pending GM escalation, open repeated-failure cases | `warranty.case` `escalation_pending`; `repeated_failure_flag`, not closed / rejected | Warranty Cases |
| Filter Company | Company (shown when the user has several companies) | allowed companies of the switcher | – |
| Filter Branch | Branch (shown when the selected company has branches) | Odoo 18 child companies | – |
| Filter Product Category | Product Category (child_of) on every figure | the record's product category | – |
| Filter Status | **Warranty Card Status** – Warranty Status area only | `warranty.card.state` | – |
| Filter Date range | Date From / To on all five areas (rules below) | document dates below | – |

## Date range

No date range (default) = today's position. With a range (either bound may be open):

| Area | Date used | Meaning |
|---|---|---|
| Warranty Status – first figure | warranty start / end | **In force in period**: Confirmed or since-Expired card whose warranty period overlaps the range (usage cards without end date: start ≤ range end). Not "active today". |
| Warranty Status – second figure | warranty end date | **Ending in period**: Confirmed or Expired card ending in the range (replaces the 30 / 60 / 90-day window). |
| Warranty Status – status lines | card creation date | cards created in the period, by current status |
| Pending Services | due date | open services due in the period (services without due date are not counted) |
| Approvals | creation date of the waiting document | |
| Replacements | creation date (draft replacements have no submission date) | |
| Escalations | warranty case creation date | |

Known limit: only the current card status is stored, so a card suspended or cancelled after the
period is not counted as in force in that period.

## Verification (2026-11-11, copy of UAT `wt_dash_srs`)

54 dashboard figures (today, 2026-11-01..11, 2026-01-01..10-31) compared with independent SQL
counts: 0 differences. Tests `warranty_dashboard` tag: 20 / 20 (incl. a browser render test).

## Security

Counts with the user's rights (`search_count` / `_read_group`, record rules, allowed
companies); a model the user cannot read gives None ("—") and its drill-down is refused. No
`sudo` in any count; the only sudo reads the groups of the linked report actions.

## Report links

The dashboard links only the SRS 15 reports that have no Warranty > Reports menu any more:
Active / Expiring Warranty, Free Service Due, Draft Warranty Review (their actions and views are
kept). Unit Warranty Number stays under Cards > Warranty Unit Numbers.

## SRS 15 report coverage after the menu removal

| Report | Key filter | Status |
|---|---|---|
| Unit Warranty Number | card, number, product, delivery, serial, status | supported (Cards > Warranty Unit Numbers search) |
| Active / Expiring Warranty | customer, product | supported (card search) |
| | expiry date | custom filter / group by on Warranty End Date; Expiring figure on the dashboard |
| | model | **gap** – no model field (decision 2026-11-08) |
| Free Service Due | due date | supported (Upcoming / Due / Overdue filters, Service Calendar) |
| | branch | supported through the company switcher (branch = company) |
| | technician | custom filter on Service Jobs > Main Technician |
| | customer type | **not defined** – no "customer type" field; only custom filters on the customer (e.g. company type) |
| Draft Warranty Review | Sales Order | supported (card search, group by) |
| | pricelist, grouping mode, missing criteria | custom filter / group by on Pricelist, Card Grouping Mode, Missing Confirmation Requirements |

## Data gaps (not invented)

* Branch exists only as company branches; there is no branch field on warranty records.
* Brand / model are not implemented in the warranty modules (decision 2026-11-08).

## 18.0.1.0.7 – presentation redesign (2026-11-11)

Frontend only, after the user's reference screenshot; KPI logic, filters, date rules, access and
drill-downs unchanged (54 / 54 figures = SQL, 20 / 20 dashboard tests).

* Filter Dashboard: one bar with Company, Branch, Product Category, Card Status, Date From /
  To. Company is a fixed field when one company is selected in the switcher; Branch is a fixed
  "No branches" field when the selected company has none (both still filter when available).
* Row 1: Warranty Status, Pending Services, Approvals (equal cards). Row 2: Replacements,
  Escalations (coloured left border). All 7 approval types stay, paired on rows, each number
  opens its own documents.
* Row 3: Warranty Cards by Status – horizontal HTML / CSS bars (no chart library) over the
  existing `warranty.by_status` data (same counts, same filters; created-in-period with a date
  range); each bar opens its cards.
* Reports & Quick Access: Active / Expiring Warranty, Free Service Due, Draft Warranty Review,
  Warranty Unit Numbers (existing actions, shown only with access). "View All Reports" is not
  offered: there is no existing action for the Reports menu folder.
* Colours: primary #65446E; areas #785287, #138F83, #4473C4, #B87C26, #CC6574; page
  #F6F7FB; dark mode uses Odoo's dark background and lighter accents.
