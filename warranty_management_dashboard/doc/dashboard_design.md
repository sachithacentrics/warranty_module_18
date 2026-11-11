# Warranty Dashboard – design record (18.0.1.0.0, 2026-11-08)

Approved 2026-11-08 with three corrections (Active by validity dates, accurate approval
breakdown, consistent filters / no misleading branch filter). Correction 2026-11-08: brand and
model removed from the dashboard (not implemented in the warranty modules); failure analysis by
product and the case's existing Failure Category only. Presentation and reporting layer
only: no business model, calculation or workflow of its own; no change to any warranty, MRF,
accounting, repair, Helpdesk, Field Service or AMC module.

## SRS mapping

| SRS | Dashboard element | Source (existing data) | Drill-down |
|---|---|---|---|
| 6 Dashboard menu | Warranty > Dashboard, first entry (opens with the app) | client action `warranty_management_dashboard.dashboard` | – |
| 15 Dashboard: status | KPI Active Warranties | card Confirmed, start ≤ today, end ≥ today (usage cards without end date) | Warranty Cards |
| 15 nearing expiry | KPI Expiring (30 / 60 / 90 days), Expiry Trend (12 months) | active cards by end date | Warranty Cards |
| 15 pending services | KPI Pending Warranty Services (+ overdue / due), Service Due chart | entitlements in OPEN_STATES, existing Due Indicator | Service Entitlements |
| 15 approvals / 16 roles | KPI Pending Approvals + table by type | case Eligibility Checked + Eligible (existing "Waiting Approval" filter); warranty MRF Manager / Finance-GM; replacement Submitted; vendor claim Waiting Approval; card action Waiting; download To Approve; service date exception group Requested | each type's own list |
| 15 replacements | KPI Open Replacements (+ awaiting approval), replacement trend | replacement Draft / Submitted / Approved; by requested month and type | Replacements |
| 15 escalations | KPI Repeated Failure Escalations (+ open repeated-failure cases), trend | case `escalation_pending`, `repeated_failure_flag` | Warranty Cases |
| 15 Failure Pattern | chart by product / failure category | failure case types (complaint, replacement, repeat complaint); case `product_id` and `failure_category` | Warranty Cases |
| 15 / 17 Warranty Cost | Actual / Recovered / Net, cost by type | rows of the existing Warranty Cost Report (`_warranty_report_rebuild`, same access check) | Warranty Cost Report |
| 15 / 17 Vendor recovery | Claims, recovered, outstanding; amounts chart | vendor claim stored amounts | Vendor Claims |
| 15 / 17 Provision / Reserve | reserve balance, actual cost, movements | rows of the existing Provision / Reserve report (its builder, Accounting groups only) | Provision / Reserve report |
| 15 report list | Reports panel + Warranty > Reports menus | existing reports linked; new list / pivot / graph actions on existing records for the reports without a menu | – |

## Filters

* Company: the companies selected in the switcher (a company outside them is ignored).
* Branch: Odoo 18 branches (child companies); shown only when the selected company has branches
  the user may use (correction 3).
* Product Category (child_of) on every figure through the record's product.
* Warranty Status: card figures only (status chart, Active, Expiring, expiry trend).
* Date range (default: 12 months to today) on dated figures only, each labelled with its date
  (case created, requested / created, cost date, claim created, entry date). Snapshot figures are
  labelled "Snapshot".

## Security

* Counts with the user's rights (`search_count` / `_read_group`, record rules, allowed
  companies); a model the user cannot read gives None ("—") and its drill-down is refused.
* Financial sections use the existing report access checks; the cost and reserve rows are
  built by the existing builders for the user (transient rows, own user only), refreshed at most
  every 10 minutes or with Refresh.
* No `sudo` in any count; the only sudo is the reading of action / menu groups for the report
  list.

## Data gaps (not invented)

* Branch exists only as company branches; there is no branch field on warranty records.
* Failure category is optional on cases ("Not Set").
* Brand / model analysis (SRS 15 Failure Pattern and Warranty Cost key filters) is **not
  provided**: brand and model are not implemented in the warranty modules (decision
  2026-11-08). The dashboard groups failures by product and failure category only, and no
  brand / model field is added to any module.
* Cost and provision figures are calculated by the reports, not stored: the financial section
  loads after the KPI cards.
