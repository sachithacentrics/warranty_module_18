# 27 – AMC Known Issues and Limitations

| ID | Item | Type | Impact | Workaround / next step |
|---|---|---|---|---|
| K-01 | Business assumptions AS-01 … AS-08 (start / hold / renewal / closure / missed rules) implemented as conservative defaults, not yet confirmed by the BA | Open decision | Behaviour may need adjustment after UAT | Confirm in UAT; rules are isolated in `amc.contract` lifecycle methods |
| K-02 | No automatic *Draft Job from Service* for AMC visits (only Alert-Driven / Manual planning) | Limitation (G-12) | Coordinators create service requests manually | Use alerts + Create Service Request |
| K-03 | Line-level AMC coverage (covered vs. excluded items) is not modelled; excluded items on AMC jobs follow the existing chargeable / MRF coverage decisions | Limitation (G-09) | Manual coverage decisions on AMC jobs | MRF coverage type per line; chargeable quotation |
| K-04 | One service request per contract and site (no merge across contracts of the same customer) | Limitation (G-13) | Two jobs for two contracts | Shared Field Service visit of the FSM module can serve several jobs |
| K-05 | AMC visits and an ad-hoc warranty complaint on the same ticket become two cases / jobs (one case type per case) | Limitation | Two jobs | Shared Field Service visit |
| K-06 | No proration, no automatic price carry-forward on renewal, no Subscriptions | By decision (G-07, AS-04) | Renewal is priced with the formula in force | — |
| K-07 | Closing a contract early does not credit already released / invoiced periods | By design (AS-05) | Accounting handles refunds | Credit note in Accounting |
| K-08 | `res.company.amc_enabled` (1.0.0) is not used by any logic | Obsolete field | None | Kept for data compatibility |
| K-09 | The PDF through wkhtmltopdf was not executed (HTML rendering is tested); the new screens were rendered in headless Chrome for the manual, but clicking through every filter / button in a browser remains UAT | Test gap | Low | UAT TC-M01 / TC-M04 |
| K-10 | MRF, excluded-item billing, cost lines and batch completion were not executed on an AMC job (reused unchanged) | Test gap | Low–Medium | UAT TC-M02 |
| K-11 | Helpdesk SLA "by AMC" relies on an SLA policy configured for the *AMC* ticket tag | Configuration | — | Create the SLA policy (UAT TC-M03) |
| K-12 | The Development Mapping decisions cited in the 1.0.0 code (B2–B9, C1–C5, P1–P6) could not be re-checked (document not available) | Traceability gap (G-14) | Low | Provide the mapping document for review |
| K-13 | Usage readings are entered on the worksheet / completion; no meter integration, no reading reset | Limitation (G-10) | — | Controlled correction through the warranty usage-correction process if needed |
| K-14 | Helpdesk and Field Service users get read access to AMC contracts (incl. contract value) | Security trade-off | Technicians can read AMC contract values | Restrict field visibility with groups if the BA requires it |
