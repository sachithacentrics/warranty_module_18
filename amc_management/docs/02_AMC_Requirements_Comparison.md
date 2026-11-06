# 02 – Requirements Comparison: Original SRS vs. Consolidated DOCX

**Consolidated document:** `AMC_Consolidated_Requirements_Odoo19.docx` ("Functional Requirements
Register – Annual Maintenance Contract", 75 requirements AMC-A01 … AMC-H06, derived from the same
81-page SRS). Every DOCX page reference was checked against the SRS text (`01_AMC_SRS_Analysis.md`).

Precedence applied (prompt §5.2): 1 SRS → 2 DOCX → 3 existing code (evidence only) → 4 Odoo 18
standard → 5 documented assumptions.

## 1. Summary

| Classification | Count | IDs |
|---|---|---|
| Fully aligned | 63 | all IDs not listed below |
| Partially aligned | 3 | A07 (SRS 14 also asks to *offer* AMC on expiry → added AMC-X01), D01 (Site-Based missing from the p. 15 dropdown sample), F13 (SRS also lists pivot / graph) |
| Missing from DOCX | 1 | AMC-X01 "Warranty expires → offer AMC conversion if configured" (SRS p. 75) |
| Additional requirement in DOCX | 0 | — (the DOCX §7 decisions are questions, not requirements) |
| Conflicting | 2 | C-01 menu placement (pp. 6 / 18–19), C-02 p. 51 diagram vs. p. 52 text |
| Ambiguous / under-specified | 8 | B07, B08, C04, C05, E08, G01/G03 (billing detail), coverage precedence (F09/G05), usage meter source (E10) |
| Odoo 18 compatibility concern | 2 | G01 (Subscriptions wording), NFR-04 (Odoo 19 references) |
| Superseded by a later approved decision | 1 | A02 – the warranty Scope Mode limitation was removed by the BA on 2026-10-28 (`warranty_management/doc/part2_design_decisions.md`) |
| Outside confirmed AMC scope | 0 | — |

## 2. Requirement-by-requirement comparison

| Req. | SRS | DOCX | Comparison | Development decision |
|---|---|---|---|---|
| A01 Separate module | pp. 6, 10, 16–17, 80 | §3.1 | Match | Implement (exists; kept + bridges) |
| A02 Scope modes | pp. 6, 11, 20 | §3.1 | Match, but superseded by BA decision 2026-10-28 | Superseded – AMC uses its own Auto-create Mode / AMC Enabled |
| A03 Draft AMC from warranty | pp. 6, 10, 21, 52, 75 | §3.1 | Match | Implement (bridge `amc_management_warranty`) |
| A04 Auto-create mode | pp. 21, 52 | §3.1 | Match | Implement |
| A05 Own activation trigger | pp. 6, 10, 52 | §3.1 | Match | Implement (exists + payment activation) |
| A06 Equipment / warranty units | pp. 10, 15, 52 | §3.1 | Match | Implement (warranty unit on covered lines) |
| A07 Convert to AMC | pp. 71–72, 75 | §3.1 | Partial (offer on expiry → X01) | Implement + X01 |
| A08 Post-warranty eligibility | pp. 42, 71 | §3.1 | Match | Implement (AMC eligibility for AMC cases) |
| A09 Navigation | pp. 18–19 | §3.1 | Match; conflict C-01 | Implement separate app + smart buttons |
| B01–B06, B09–B11 | pp. 5, 10, 15, 19–20, 42, 51–52, 62–63, 75, 79 | §3.2 | Match | Implement / retain |
| B07 Start / end criteria | p. 10 | §3.2 | Match – both say not fully specified | Implement existing Activation Date / Manual Start + assumption AS-01 |
| B08 Renewal rules | pp. 6, 10, 19, 52 | §3.2 | Match – details missing | Implement with assumptions AS-04, AS-07 |
| C01–C03, C06, C07 | pp. 6, 10, 15, 19, 32, 40, 52, 71 | §3.3 | Match | Implement / retain |
| C04 Hold / inactive | pp. 10, 15, 52, 59 | §3.3 | Match – "exact transition restrictions require confirmation" | Implement with AS-02, AS-03, AS-05 |
| C05 Expiring / Renewed | pp. 6, 10, 19, 52 | §3.3 | Match – details missing | Implement with AS-04, AS-06 |
| D01 Pricing methods | pp. 10, 15, 21, 77 | §3.4 | Partial (p. 15 dropdown abbreviated) | Retain all 8 methods incl. Site-Based (p. 10 explicit) |
| D02–D13 | pp. 10, 15, 21, 74, 77 | §3.4 | Match | Retain (existing engine) + add tests; fix factor lock / usage defects |
| E01–E10 | pp. 5–9, 14, 17–18, 21, 40–42, 51–52, 62–63, 70–75, 79 | §3.5 | Match; E08 / E10 detail missing | Implement (phase A4) |
| F01 Mandatory chain | pp. 6, 8, 10, 27, 52, 74 | §3.6 | Match; conflict C-02 (p. 51 diagram) | Implement text version (bridge `amc_management_service`) |
| F02–F07, F11 | pp. 8–9, 13–14, 19, 23, 27, 29, 44, 52, 74–75 | §3.6 | Match | Implement via the existing warranty chain |
| F08–F10 | pp. 9, 31, 44, 49, 76–78 | §3.6 | Match (shared services) | Reuse the existing MRF / chargeable / cost processes of the Service Job (no AMC-specific code) |
| F12 SLA | pp. 19, 72 | §3.6 | Match | Reuse Helpdesk SLA with an "AMC" ticket tag |
| F13 Views | pp. 8, 19, 75–76 | §3.6 | Partial (pivot / graph in SRS) | Implement list, kanban, calendar, pivot, graph |
| G01 Recurring invoicing | pp. 10, 16–17, 19, 80–81 | §3.7 | Match; Odoo 18 note | Implement AMC billing schedule (user decision; Subscriptions optional per SRS) |
| G02–G06 | pp. 5–6, 9–10, 15–17, 21, 32, 42, 49, 52, 71, 78, 80–81 | §3.7 | Match | Implement / retain |
| H01–H06 | pp. 6, 8–10, 15, 17–19, 52, 62–65, 74–75, 77 | §3.8 | Match | Implement |
| X01 Offer AMC on expiry | p. 75 | — (only implied in A07) | Missing from DOCX | Implement (configurable activity) |

## 3. DOCX §4 field list vs. implementation names

| DOCX / SRS p. 15 field | Odoo 18 field |
|---|---|
| AMC Plan | `amc.plan.name` |
| Pricelist | `amc.plan.pricelist_ids` (applicability), `amc.contract.pricelist_id` |
| Equipment / Warranty Units (M2M) | `amc.contract.line_ids` (product, serial, qty) + `warranty_unit_id` (bridge) |
| Frequency / Visit Count | `visit_count`, `frequency_value`, `frequency_unit` (or `usage_interval` / `usage_unit`) |
| Included Free Services | `included_free_services` |
| Pricing Method / Formula / Variables | `pricing_method`, `amc.pricing.formula` (method, hybrid_expression, factors, tiers) |
| Min / Max / Rounding | `min_price`, `max_price`, `rounding_step`, `rounding_method`, `rounding_rule_ids` |
| Stage | `amc.contract.state` (9 values) |
| Recurring Plan / Invoice Trigger | `billing_plan_id` (`amc.billing.plan`), `activation_trigger` |
| Start / End Criteria | `start_rule`, `duration_value/unit`, `contract_months`, `start_date`, `end_date` |
| Renewal Rules | `renewal_rule`, `renewal_notice_days` |
| Effective dates / version / currency | `effective_from/to`, `version`, `currency_id` on the formula version |
| Preview / override approval | `amc.pricing.preview`, `amc.price.override` |
