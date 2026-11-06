# 03 – AMC Gap and Conflict Register

Severity: Critical / High / Medium / Low. "Proceed" = implementation can proceed safely with the
recorded resolution. Business assumptions (AS-nn) were approved by the user on 2026-11-06 as
"conservative documented defaults"; they remain open for BA confirmation in UAT.

## 1. Conflicts

| ID | Conflict | Evidence | Severity | Resolution | Proceed |
|---|---|---|---|---|---|
| C-01 | Menu placement: "AMC Contracts" under Warranty Management (p. 18) vs. AMC transactions only in the separate module (pp. 6, 18–19) | SRS pp. 6, 18, 19 | Low | AMC transactions only in the AMC app; warranty side gets smart buttons / Convert to AMC (no AMC menu in Warranty) | Yes |
| C-02 | p. 51 diagram creates FSM tasks directly; p. 52 text and pp. 6, 8 require Helpdesk → Service Job → FSM | SRS pp. 6, 8, 51, 52 | High | The mandatory textual chain is implemented (`amc_management_service`); manual completion is disabled when the chain is installed | Yes |
| C-03 | Scope Mode (SRS 2.1 / 7) vs. BA decision 2026-10-28 removing the Scope Mode limitation | SRS pp. 6, 20; `warranty_management/doc/part2_design_decisions.md` | Medium | Later approved decision wins; AMC integration is controlled by the AMC Auto-create Mode and its own settings | Yes |

## 2. Gaps (missing / unclear in the sources)

| ID | Area | Gap | Source | Severity | Resolution / assumption | Proceed |
|---|---|---|---|---|---|---|
| G-01 | Start / end criteria | Choices, anchor dates, retroactive starts not defined | p. 10; DOCX §7 | High | **AS-01**: plan Start Criteria = Activation Date (start = activation day) or Manual Start Date (entered before quotation); end = start + duration − 1 day; renewal start = predecessor end + 1; conversion start = warranty end + 1 when still ahead, else activation | Yes |
| G-02 | Hold effects | Effects of On Hold on visits, free services, invoices | pp. 10, 52, 59; DOCX §7 | High | **AS-03**: On Hold blocks new visit planning, service requests and visit alerts; entitlements, dates and the billing schedule are unchanged (period not extended); Resume returns to Active (or Expiring) | Yes |
| G-03 | Transition restrictions | Exact allowed transitions not stated | DOCX C04 | High | **AS-02**: running contracts (Active / Expiring / On Hold) are never Cancelled, only Closed; Cancel only before activation | Yes |
| G-04 | Renewal mechanics | Reminder lead time, renewal quotation, proration, price carry-forward | pp. 6, 10, 19, 52; DOCX §7 | High | **AS-04**: Renew creates a linked Draft contract (same customer, site, plan, equipment) priced again with the formula in force, sold with its own quotation / trigger; no proration, no automatic price carry-forward. **AS-07**: renewal notice = plan *Renewal Notice (Days)* (default 30); Auto Offer prepares the renewal at that moment | Yes |
| G-05 | Renewed vs Closed | When the predecessor becomes Renewed | — | Medium | **AS-06**: predecessor becomes Renewed when its renewal is activated after its end date, or at its end date if the renewal is already Active; otherwise Closed at the end date | Yes |
| G-06 | Closure effects | Effect on open visits / unbilled periods | pp. 10, 52, 59 | High | **AS-05**: open entitlements Expire (not consumed); billing periods not yet released are Cancelled; released / invoiced periods are left to Accounting (no credit notes created) | Yes |
| G-07 | Billing detail | Periodicity, advance / arrears, proration, failed collection | pp. 10, 15, 80–81 | High | Billing Plan frequency (upfront / monthly / quarterly / half-yearly / annual / per preventive visit) and timing (advance / arrears) from 1.0.0; no proration; failed collection = standard Accounting follow-up; Subscriptions not used (user decision) | Yes |
| G-08 | Missed / carry-forward | Grace, auto-expiry, carry-forward rules | pp. 63, 70, 72, 75 | Medium | **AS-08**: plan Grace Period (days) and *Mark Missed After Grace Period*; a Missed visit can be reopened by an AMC Manager while the contract runs (manual carry-forward); no automatic carry-forward | Yes |
| G-09 | Coverage precedence | AMC vs. warranty coverage when both are active | pp. 5, 9, 42, 52 | Medium | AMC cases (Case Type AMC with a contract) use the AMC eligibility only; warranty cases keep warranty eligibility. Line-level item coverage for AMC is not defined → excluded items follow the existing chargeable / MRF decisions on the job (documented limitation K-03) | Yes |
| G-10 | Usage meter source | AMC meter source / reading reset | pp. 10, 63, 74, 77 | Medium | Usage reading entered on the job worksheet (or manual completion); must be > 0 and not lower than the last AMC reading of the same unit; no meter integration | Yes |
| G-11 | Reporting scope | Revenue / renewal forecast / utilization KPIs | p. 75; DOCX §7 | Low | Only the AMC Visit Schedule report (SRS 15) + standard pivot / graph analysis | Yes |
| G-12 | Draft job mode for AMC | SRS "Draft Job from Service" for AMC | pp. 8, 21 | Medium | AMC plans offer Alert-Driven or Manual planning; automatic draft jobs for AMC are not implemented (documented limitation K-02) | Yes |
| G-13 | Multi-contract merge | Merge of visits across contracts of one customer | pp. 8, 13 | Low | One service request per contract and site (documented limitation K-04) | Yes |
| G-14 | Development mapping decisions | 1.0.0 code cites approved decisions B2–B9, C1–C5, P1–P6 from "Warranty Module Development Mapping.pdf", which is not available here | code comments | Medium | Decisions are taken as implemented in 1.0.0 and preserved; not re-verified against the mapping document | Yes (risk noted) |

## 3. Defects found in the existing implementation (1.0.0)

| ID | Defect | Location | Severity | Fix |
|---|---|---|---|---|
| DEF-01 | Pricing factors of Active / Archived formula versions could be created / changed / deleted (the lock hooks were defined twice on `amc.pricing.tier` and missing on `amc.pricing.factor`) | `models/amc_pricing_formula.py`, `models/amc_pricing_factor.py` | High (price history integrity, AMC-D11) | Hooks moved to the factor model; duplicate removed; test TC-001 |
| DEF-02 | Contract pricing ignored the expected usage: Usage-Based contracts always priced at the base amount | `amc.contract.action_compute_price` | High (AMC-D07) | `expected_usage` field passed to the engine; test TC-002 |
| DEF-03 | `end_date` recomputed from the plan duration: editing a plan moved the end date of sold contracts | `amc.contract._compute_end_date` | High (data integrity) | `contract_months` snapshot; test TC-003 |
| DEF-04 | Plan pricelist applicability (`pricelist_ids`) was never checked | `_amc_pricing_problems` | Medium (AMC-B02) | Check added; test TC-004 |
| DEF-05 | Awaiting Payment contracts could never become Active (no payment hook, no billing) | phase A5 missing | Critical (AMC-A05 / G03) | Billing schedule + invoice-paid hook; test TC-033 |
| DEF-06 | 3,060 blank lines inside `amc_pricing_formula.py` | file | Low | Removed (no logic change) |
| DEF-07 | `action_create_quotation` used `FOR UPDATE NOWAIT` (unhandled lock error for a concurrent click) | `amc_contract.py` | Low | Shared `_amc_lock()` with a waiting `FOR UPDATE` |
| DEF-08 | Activation from SO confirmation ran with the confirming user's rights (contract write by a salesman without AMC role) | `sale_order.action_confirm` | Medium | The contract side-effect runs with sudo, scoped to the AMC order |
| DEF-09 | `amc.pricing.rounding._check_rule` used `_()` without importing it: every rounding-rule validation raised `NameError` instead of the business message | `models/amc_pricing_rounding.py` | Medium | Import added (found by the static review, 22); test TC-108 |
