# 04 – AMC Final Requirements Baseline

Baseline for development and acceptance (2026-11-06). Full text of each requirement:
`01_AMC_SRS_Analysis.md` §2; assumptions AS-01 … AS-08: `03_AMC_Gap_and_Conflict_Register.md`.

**Scope decisions by the user (2026-11-06):**

1. Service execution through a bridge module `amc_management_service` (Helpdesk → Service Job →
   Field Service of the warranty solution), no edits to the warranty modules' files.
2. Warranty integration through a bridge module `amc_management_warranty`.
3. Open rules → conservative documented defaults (AS-01 … AS-08).
4. Billing → AMC billing schedule on the standard Sales Order lines (no Subscriptions).
5. No commit / push until the user confirms.

| Req. | Baseline decision | Module | Assumptions |
|---|---|---|---|
| A01 | In scope – retain separate module | amc_management | — |
| A02 | **Superseded** (BA decision 2026-10-28, C-03) | — | — |
| A03, A04, A06 (units), A07, C07, X01 | In scope | amc_management_warranty | AS-01 |
| A05, C01–C06, B01–B09, B11 | In scope | amc_management | AS-01 … AS-07 |
| A08, F01–F07, F11, H02, H04 | In scope | amc_management_service | — |
| A09 | In scope | all three | C-01 |
| B10 | In scope – reuse the existing *AMC Visit* service type / *AMC* case type | warranty modules (unchanged) + service bridge | — |
| D01–D13, G06 | In scope – retain existing engine, fix DEF-01 / DEF-02 | amc_management | — |
| E01–E10 | In scope | amc_management (+ service bridge for E07) | AS-08, G-10 |
| F08, F09, F10 | In scope – **reuse** existing MRF / chargeable / cost processes on the AMC Service Job (no AMC-specific change) | warranty modules | G-09 |
| F12 | In scope – Helpdesk SLA via "AMC" ticket tag | amc_management_service | — |
| F13, H01 | In scope | amc_management | G-11 |
| G01–G05 | In scope – billing schedule; G05 via the existing chargeable flow | amc_management | G-07 |
| H03, H05, H06 | In scope | all | — |
| NFR-01 … NFR-04 | In scope | all | — |

Out of scope (documented, not implemented): Subscriptions-based billing, automatic draft jobs for AMC
(G-12), cross-contract merge (G-13), AMC revenue / forecast KPIs (G-11), meter integration (G-10),
proration (G-07), automatic carry-forward (G-08).
