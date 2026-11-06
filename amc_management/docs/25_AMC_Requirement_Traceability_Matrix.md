# 25 – AMC Requirement Traceability Matrix

Modules: **core** = amc_management, **W** = amc_management_warranty, **S** = amc_management_service.
Status values per prompt §15.

| Req. | SRS | DOCX | Implementation | Test | Status |
|---|---|---|---|---|---|
| A01 | 6, 10, 16–17, 80 | 3.1 | separate core module; bridges | install of core alone (`amc_upg`), 21 | Implemented and tested |
| A02 | 6, 11, 20 | 3.1 | — (BA decision 2026-10-28, C-03) | — | Superseded by documented approved requirement |
| A03 | 6, 10, 21, 52, 75 | 3.1 | W `warranty.card.action_confirm_warranty`, `_amc_auto_create` | TC-081, TC-082, TC-083 | Implemented and tested |
| A04 | 21, 52 | 3.1 | W `res.company.amc_auto_create_mode` | TC-080 – TC-082 | Implemented and tested |
| A05 | 6, 10, 52 | 3.1 | core `sale_order.action_confirm`, `account.move._invoice_paid_hook`, `_amc_activate` | TC-010, TC-033, TC-081 | Implemented and tested |
| A06 | 10, 15, 52 | 3.1 | core `amc.contract.line`; W `warranty_unit_id` | TC-081, TC-086 | Implemented and tested |
| A07 | 71–72, 75 | 3.1 | W `action_convert_to_amc` | TC-084, TC-085 | Implemented and tested |
| A08 | 42, 71 | 3.1 | S `warranty.case._amc_run_checks` | TC-090, TC-094, TC-097 | Implemented and tested |
| A09 | 18–19 | 3.1 | core menus / smart buttons; W card button; S ticket tab | TC-081 (count); views load at install | Implemented; UI rendering in UAT (TC-M01) |
| B01 | 10, 15, 20, 52 | 3.2 | core `amc.plan` | all suites | Implemented and tested |
| B02 | 10, 15, 19–20, 52 | 3.2 | core `_amc_pricing_problems` (pricelist applicability) | TC-004 | Implemented and tested |
| B03 | 10, 15, 52 | 3.2 | core `_amc_line_problems` | TC-106 | Implemented and tested |
| B04 | 5, 10, 15, 20, 52 | 3.2 | plan visit count / frequency; `_amc_visit_interval_months` | TC-011, TC-012 | Implemented and tested |
| B05 | 5, 20, 51–52, 79 | 3.2 | configurable plans | TC-011, TC-012 | Implemented and tested |
| B06 | 10, 15, 19, 52 | 3.2 | `included_free_services`, free-service entitlements | TC-011 | Implemented and tested |
| B07 | 10 | 3.2 | start rule, `contract_months`, AS-01 | TC-003, TC-033, TC-048 | Implemented and tested |
| B08 | 6, 10, 19, 52 | 3.2 | renewal rule / notice, `action_renew`, auto offer | TC-041, TC-042, TC-045 | Implemented and tested |
| B09 | 10, 15 | 3.2 | `amc.billing.plan`, `amc.billing.line` | TC-030 – TC-032 | Implemented and tested |
| B10 | 19, 62–63 | 3.2 | existing service type / case type AMC (reused) | TC-090 | Implemented and tested |
| B11 | 10, 42, 52, 75 | 3.2 | contract / line / visit site, site pricing | TC-100 (site), TC-093 | Implemented and tested |
| C01 | 10, 19, 32, 52 | 3.3 | `action_create_quotation` | TC-010 | Implemented and tested |
| C02 | 10, 15, 52, 59 | 3.3 | 9 states + transitions | TC-010, 033, 034, 040–045, 107 | Implemented and tested |
| C03 | 6, 10, 40, 52 | 3.3 | generation only in `_amc_activate` | TC-010, TC-033 | Implemented and tested |
| C04 | 10, 15, 52, 59 | 3.3 | hold / resume / close, AS-02/03/05 | TC-040, 043, 044, 094 | Implemented and tested |
| C05 | 6, 10, 19, 52 | 3.3 | expiring / renewed, AS-04/06/07 | TC-041, 042, 045 | Implemented and tested |
| C06 | 32, 52 | 3.3 | manual contract | all suites | Implemented and tested |
| C07 | 6, 15, 71 | 3.3 | W `source_warranty_card_id`, start continuity | TC-081, TC-085 | Implemented and tested |
| D01–D08 | 10, 15, 21, 77 | 3.4 | core formula engine | TC-100, TC-002, TC-032 | Implemented and tested |
| D09 | 10, 21, 74 | 3.4 | `amc_safe_expression` | TC-102 | Implemented and tested |
| D10 | 10 | 3.4 | `HYBRID_VARIABLES` | TC-102 | Implemented and tested |
| D11 | 10, 15, 21 | 3.4 | versions, lock (DEF-01), rounding rules (DEF-09) | TC-001, 101, 103, 108 | Implemented and tested |
| D12 | 10, 21, 74 | 3.4 | `amc.pricing.preview`, formula sample | TC-104 | Implemented and tested |
| D13 | 10 | 3.4 | `amc.price.override` | TC-105 | Implemented and tested |
| E01 | 6, 10, 40, 51–52 | 3.5 | `_amc_generate_visits` | TC-011 | Implemented and tested |
| E02 | 10, 20, 51–52 | 3.5 | plan-driven counts | TC-011, TC-012 | Implemented and tested |
| E03 | 17–18, 52, 62–63 | 3.5 | `amc.contract.visit` | TC-011, TC-022, TC-062 | Implemented and tested |
| E04 | 8, 42, 52, 63, 75 | 3.5 | `_cron_amc_visits` alerts | TC-024 | Implemented and tested |
| E05 | 8, 21, 41–42, 52, 79 | 3.5 | planning mode Alert / Manual (draft-job mode not for AMC, K-02) | TC-024 | Partially implemented |
| E06 | 51–52 | 3.5 | `next_visit_date` | TC-020 | Implemented and tested |
| E07 | 8–9, 41–42, 52 | 3.5 | `_amc_consume`; S `_warranty_complete_case` | TC-020, TC-090 – TC-092 | Implemented and tested |
| E08 | 63, 70, 72, 75 | 3.5 | due status, grace, Missed, reopen (AS-08) | TC-024 | Implemented and tested |
| E09 | 63, 74 | 3.5 | state checks, unique constraint, compatibility | TC-020, TC-086, TC-090, TC-093 | Implemented and tested |
| E10 | 7–8, 14, 63, 74 | 3.5 | usage reading validation; S worksheet usage | TC-013 | Implemented and tested |
| F01 | 6, 8, 10, 27, 52, 74 | 3.6 | S wizard + case / job hooks; manual completion disabled | TC-090, TC-095 | Implemented and tested |
| F02 | 8, 14, 19, 63, 75 | 3.6 | S `helpdesk.ticket.amc_pending_visit_ids` | TC-096 | Implemented and tested |
| F03 | 8, 13–14, 19, 27, 74 | 3.6 | S `_amc_service_problems` | TC-090, TC-093 | Implemented and tested (one contract per request, K-04) |
| F04 | 8, 13, 44, 74 | 3.6 | existing job rule (reused) | TC-090 | Implemented and tested |
| F05 | 8, 14, 27, 44 | 3.6 | S `_warranty_worksheet_lines` | TC-090 | Implemented and tested |
| F06 | 8, 14, 44, 52, 74 | 3.6 | existing completion checks + AMC checks | TC-090, TC-091 | Implemented and tested |
| F07 | 8–9, 29, 75 | 3.6 | S `_warranty_cancel`, case release | TC-092 | Implemented and tested |
| F08 | 9, 31, 44, 49 | 3.6 | existing MRF on the Service Job (reused) | — | Partially implemented (reuse not verified, TC-M02) |
| F09 | 5, 9, 19–20, 42, 44, 49 | 3.6 | existing chargeable flow (reused) | — | Partially implemented (TC-M02) |
| F10 | 9, 31, 76–78 | 3.6 | existing cost lines (reused) | — | Partially implemented (TC-M02) |
| F11 | 8, 23, 74 | 3.6 | batch completion uses the same hooks | — | Partially implemented (not executed for AMC) |
| F12 | 19, 72 | 3.6 | S AMC ticket tag + standard SLA | TC-090 (tag) | Partially implemented (SLA policy configuration, TC-M03) |
| F13 | 8, 19, 75–76 | 3.6 | visit list / kanban / calendar / pivot / graph / filters | views load at install | Implemented; UI rendering in UAT (TC-M01) |
| G01 | 10, 16–17, 19, 80–81 | 3.7 | billing schedule + Create Invoice | TC-030, TC-031 | Implemented and tested |
| G02 | 6, 10, 16–17, 80–81 | 3.7 | design (no Subscriptions) | — | Implemented and tested (by design, suites) |
| G03 | 10, 15, 52 | 3.7 | activation trigger, paid hook | TC-033 | Implemented and tested |
| G04 | 6, 10, 32, 52 | 3.7 | quotation / SO / payment | TC-010, TC-033 | Implemented and tested |
| G05 | 5, 9, 42, 49, 71, 78 | 3.7 | existing chargeable flow (reused) | — | Partially implemented (TC-M02) |
| G06 | 10, 15, 21 | 3.7 | engine controls | TC-101, TC-105 | Implemented and tested |
| H01 | 75 | 3.8 | visit schedule views + PDF | TC-047 | Implemented and tested (PDF via wkhtmltopdf in UAT TC-M04) |
| H02 | 18–19, 52, 62–63 | 3.8 | S case / job / ticket tabs, visit links | TC-090 | Implemented and tested |
| H03 | 77 | 3.8 | groups, ACL, server checks | TC-050, TC-051 | Implemented and tested |
| H04 | 6, 8, 17, 52, 63–65 | 3.8 | visit ↔ case / ticket / job / task / worksheet | TC-090 | Implemented and tested |
| H05 | 10, 15, 19, 77 | 3.8 | chatter logs, protected fields | TC-021, 046, 052, 088 | Implemented and tested |
| H06 | 9–10, 74, 77 | 3.8 | override approval audit | TC-105 | Implemented and tested |
| X01 | 75 | — | W expiry offer | TC-087 | Implemented and tested |
| NFR-01 | — | — | record rules, company checks | TC-060, TC-061 | Implemented and tested |
| NFR-02 | 16–17 | — | standard Sales / invoicing / Helpdesk / FSM reused | suites | Implemented and tested |
| NFR-03 | 10, 77 | — | protected fields | TC-021, 046, 088 | Implemented and tested |
| NFR-04 | 1 | — | Odoo 18 APIs / views | install + 63 tests on Odoo 18 | Implemented and tested |

**Totals (80 baseline requirements: 75 DOCX + X01 + 4 NFR):** Implemented and tested 70 ·
Implemented, UI rendering to be confirmed in UAT 2 (A09, F13) · Partially implemented 7 (E05, F08,
F09, F10, F11, F12, G05) · Superseded 1 (A02) · Blocked 0 · Not applicable 0.
