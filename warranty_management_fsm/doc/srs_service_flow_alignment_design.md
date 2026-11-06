# SRS Service Flow Alignment + Optional Case Type / Site Inspection – Combined Design

| Item | Value |
|---|---|
| Status | **Approved 2026-10-29 (G1–G6); implemented and tested on `wt_p5_mrf`, trial-upgraded on a copy of 18_4; NOT deployed** (§8) |
| Scope | Part A: SRS service-origin route (job before ticket). Part B: undetermined Case Type with a controlled inspection visit. One coordinated development. |
| Decisions applied | D-A … D-F (user, 2026-10-29). Open decisions: §7. |
| Modules | `warranty_management_fsm` (main), `warranty_management_helpdesk`, `warranty_management` (buttons / alerts via views), `warranty_management_mrf` (guards only). **Not changed:** `amc_management`, `material_purchase_requisitions`. |
| SRS | §2.5, §2.7, §2.11, §9.4 (steps 1–9), §9.5, §10.3–10.5, §19, gap table #13 / #18 / #21; Part 4 diagram. |

**SRS compliance statement (D-D):** the warranty free-service route is aligned. **AMC entitlements
(SRS step 1 "AMC Entitlement") remain an open SRS requirement** – the AMC module is separate and
is not modified here. Full Warranty / AMC compliance is not claimed.

## 1. Current blockers (verified in code)

| Constraint | Location |
|---|---|
| `warranty.service.job.warranty_case_id` required, `ondelete='restrict'` | `fsm/models/warranty_service_job.py:109` |
| Job company / customer / site / ticket / product / serial / card / unit are `related` to the case | `warranty_service_job.py:111-122` |
| Jobs only from an Approved, Eligible case (`action_prepare_service_job`) | `fsm/models/warranty_case.py:79` |
| Merge compatibility only as a case method (`_warranty_job_merge_problems`) | `fsm/models/warranty_case.py:45` |
| Confirm requires case Approved + ticket = case ticket; revalidation runs on the case | `warranty_service_job.py:362`, `action_confirm_job` |
| `warranty.case.helpdesk_ticket_id` and `case_type` required | `helpdesk/models/warranty_case.py:119 / 132`, create wizard `case_type` required |
| Draft Job from Service = ticket → case → check → approval → Prepare | `fsm/models/warranty_draft_job.py` |
| 108 references to `job.warranty_case_id` (FSM 50, MRF bridge 58) | fsm / mrf models |

## 2. Workflows and status transitions

### 2.1 Route S – SRS service-origin route (new)

| SRS step | Implementation | Job | Free services | Case |
|---|---|---|---|---|
| 1–3 Confirmed card; auto-create check; Draft services (auto / manual) | unchanged (Part 1/2) | – | Draft | – |
| 4 Due-date / usage alert | due alert unchanged + **usage alert** (§3.6); the alert To-Do links to *Create Service Job* | – | unchanged | – |
| 5 Select compatible services | **Create Service Job** (services list multi-select, service form, card) – shared merge check §3.2 | – | – | – |
| 6 One Draft job + planned date | wizard creates **one Draft job, Origin = Service**, no ticket / case; or **adds** the services to an open Draft service-origin job of the same customer / company / site | Draft | Selected / Merged | – |
| 7 Create or Link Helpdesk Ticket | **Create or Link Helpdesk Ticket** on the job (D-C): the ticket only, no case (customer requirement 2026-10-29) | Draft / Planned | unchanged | – |
| 8 Eligibility + link case | manual: **Warranty Cases > New** (existing form) on the job's ticket, Case Type **Free Service** (B8), all the job's free services, Requested Items; on save the case is linked to the waiting job (`_warranty_link_waiting_job`; another ticket, part of the services or two jobs refused); **Check Eligibility** on the case | unchanged | unchanged | New → Eligibility Checked |
| 9 Technicians + Confirm | Plan Job (existing) → **Confirm Service Job**: ticket open, case **Eligible** (revalidated, Q41); **no general case approval (D-A)**; eligibility-driven approvals (payment *Approval Required* / Hold, repeated-failure escalation) still block | Planned → Confirmed | Job Created | Job Created |
| 10–11 FS task + worksheets | existing `_warranty_create_visit` / `_warranty_create_worksheets`, once | Confirmed | | |
| 12 Execute visit | existing timer / worksheets / usage / MRF / sign-off / Complete Visit | In Progress → Completed | In Progress → Completed | In Progress → Completed |

Cancel before Confirm: services back to Not Merged / previous status; a case created at step 8 goes
back to New (or is rejected by the user) – nothing is consumed.

### 2.2 Route H – Helpdesk-first complaint / repair route (unchanged, plus Part B)

Ticket (Is Warranty, confirmed card) → Create Warranty Case → Check Eligibility → Approve Case
(Part 3 approvers, unchanged) → Prepare Service Job (Origin = **Case**) → Plan → Confirm → visit →
completion. All existing rules and statuses unchanged.

### 2.3 Route H with undetermined Case Type (Part B, new)

| Step | Case | Job / visit |
|---|---|---|
| Create Warranty Case **without Case Type** (`case_type` empty = "To be determined") | New, Inspection = **Required** | – |
| **Preliminary Check** (Check Eligibility in preliminary mode: card, serial, validity, payment only) | Eligibility Checked, result **Preliminary Passed** (or the normal failure results → existing Manual Review / chargeable / reject routes) | – |
| **Prepare Inspection Job** (only Preliminary Passed; payment Hold / Block / pending approval refuses) | Job Created | job Origin Case, **Job Type = Warranty Inspection**, no free services |
| Plan → Confirm (existing; revalidation in preliminary mode) | Job Created | 1 inspection visit + 1 inspection worksheet (§3.4) |
| Technician starts / works the visit | In Progress | In Progress |
| **Complete Inspection** (technician on the visit): findings, failure category, requested items, **final Case Type** (mandatory) | back to **New**, Inspection = **Done**, Case Type set, eligibility result reset | visit Done (outcome *Inspection Completed*), job **Completed**; nothing consumed, no stock, no quotation |
| Full Check Eligibility (normal mode, new type) → Approve / Convert to Chargeable / Excluded Items quotation / Reject (existing rules for that type) | existing | – |
| Prepare Service Job (Origin Case, normal job) → … completion | existing | next job (R2: only one open job per case – the inspection job is closed first) |

Rules: an undetermined case cannot be approved, converted to chargeable, closed, or get a
non-inspection job; cannot link free services (B8, §7 G3); is not counted as a repeated failure
until typed. Scheduled Free Service cases (Route S, Pending Services, Draft Job automation) are
always created with Case Type Free Service.

## 3. Changes – fields, models, methods, views

### 3.1 `warranty.service.job` (fsm)

| Change | Detail |
|---|---|
| `job_origin` Selection Case / Service | required, readonly, default Case; migration sets Case on all existing jobs |
| `warranty_case_id` | `required` removed; constraint: required when Origin = Case, or when state ∉ {Draft, Planned, Cancelled} |
| `company_id`, `partner_id`, `commercial_partner_id`, `site_id`, `warranty_card_id`, `helpdesk_ticket_id` | `related` → stored compute: from the case when linked, else from the job's services (company / customer of the cards, site = shared delivery address); product / serial / unit stay from the case (empty before) |
| `job_type` | + `warranty_inspection` (Warranty Inspection) |
| `inspection_case_type`, reuse `inspection_diagnosis` | findings of the inspection (readonly, set by Complete Inspection) |
| `_warranty_create_from_services(services, planned_date, technicians)` | new; shared merge check, row lock (`FOR UPDATE SKIP LOCKED` as 4.11), merge status |
| `action_link_helpdesk_ticket` + wizard `warranty.job.ticket.wizard` | Link (open Is Warranty ticket, same commercial customer / company / site) or Create (team = Draft Job Helpdesk Team, Is Warranty, site, address); creates the Free Service case, runs Check Eligibility, links it; refuses when the job already has a case |
| `_warranty_confirm_problems` | Origin Service branch: ticket + case + case Eligible (+ revalidation), no Approved state required (D-A); inspection jobs: preliminary revalidation |
| `action_cancel` / `_warranty_cancel` | case-less jobs: release services only |
| `_warranty_complete_visit` | inspection jobs: Complete Inspection path (no consumption, case back to New with type) |
| guards | case-less jobs: no hold, MRF, visit, completion actions (they already need Confirmed) |

### 3.2 Merge check (fsm)

`_warranty_job_merge_problems` moves to `warranty.service.entitlement._warranty_merge_problems(
partner, company, site)` – same rules (same customer / company / site, availability, not on
another open job or active case, card Confirmed, windows overlap, sequence); the case method calls
it (no behaviour change for Route H).

### 3.3 `warranty.case` (helpdesk + fsm)

| Change | Detail |
|---|---|
| `case_type` | `required` removed; selection unchanged; empty shown as "To be determined"; tracked |
| `inspection_state` Selection – / Required / Done; `inspection_findings` Text; `inspected_by_id`, `inspection_date` | audit of the inspection |
| `eligibility_result` | + `preliminary_passed` |
| `_warranty_run_checks(preliminary=False)` | preliminary: card, serial, validity, payment only |
| guards (server) | Approve Case, Convert to Chargeable, Excluded Items quotation, Prepare Service Job (non-inspection), Close, Complete Visit of a normal job, MRF request: **Case Type required** |
| Part 3 duplicate check | accepts the services of the case's own service-origin job |
| create wizard | `case_type` optional |
| `action_prepare_inspection_job` (fsm) | Preliminary Passed, no open job, payment not on hold |

### 3.4 Inspection visit / worksheet

Company setting **Inspection Worksheet Template** (Field Service worksheet); one worksheet per
inspection visit. Complete Inspection wizard on the task (assigned technician / Helpdesk user):
findings (mandatory), failure category, requested items, Case Type (mandatory, not Free Service
unless free services are added later), optional current usage; customer sign-off per the existing
Customer Sign-off Required setting.

### 3.5 Draft Job from Service (D-B)

`_cron_monitor_free_services` groups as today (customer / site, windows) and creates **Draft
service-origin jobs** (`_warranty_create_from_services`) instead of ticket + case; To-Do "Plan
draft service job" unchanged; later services join an open Draft service-origin job of the same
group. Existing automatic cases / jobs are kept (18_4: 1 card with the option, 0 services
processed).

### 3.6 Usage alert (D-E)

Reliable reading = `current_usage` of **completed** worksheets of the card (signed-off visits),
latest per card / unit. When it reaches `usage_threshold` (= usage due × Usage Alert %) of the next
open usage-basis service: one To-Do (same recipients as due alerts) linking to Create Service Job;
no duplicate while open; evaluated at visit completion and by the daily monitoring.

### 3.7 Views / buttons

| Where | Change |
|---|---|
| Service Entitlements list / form, Warranty Card | **Create Service Job** (Helpdesk users, D-F) |
| Service Job form | Origin; **Create or Link Helpdesk Ticket** (Origin Service, no ticket, Draft / Planned); Confirm hidden without case (case created manually on the ticket, linked automatically) |
| Warranty Case form / create wizard | Case Type optional ("To be determined"); Inspection tab; **Preliminary Check** (= Check Eligibility label when undetermined); **Prepare Inspection Job** |
| Field Service task | **Complete Inspection** for inspection jobs (instead of Complete Visit) |
| Helpdesk ticket | Service Jobs smart button; Is Warranty / Create Warranty Case rules unchanged |
| Card | Jobs / Tickets smart buttons |

## 4. Security and inspection-only rules

* Create Service Job / Link Ticket: `helpdesk.group_helpdesk_user` (D-F); planning, confirmation,
  technician execution, batch completion: unchanged groups and record rules (company rules on the
  stored `company_id`).
* Inspection jobs: no free services, no MRF / stock issue, no chargeable order, no excluded-items
  quotation, no consumption; Complete Visit / batch completion refused; only Complete Inspection.
* No repair, replacement, material issue or chargeable work before the approvals of the final
  Case Type (existing Part 3 / 4.10 / Part 5 rules).
* Duplicates: one open job per case (R2); one case per service-origin job; services on one open
  job / active case only; visits only from Confirm (Planned only); row locks in the wizard and the
  automation.
* Audit: every origin / link / preliminary check / inspection / type change is logged on job,
  case and ticket; tracking on `case_type`, `inspection_state`, `job_origin`.

## 5. Migration / backward compatibility

* Post-migrate (fsm): `job_origin = 'case'` for all jobs; the converted stored fields are
  recomputed from the case → identical values (verified on a trial copy by a value comparison of
  all jobs before / after).
* `case_type` / `warranty_case_id` NOT NULL dropped by the ORM; no values changed.
* Existing cases, jobs, visits, worksheets, MRFs, costs, vendor claims: unchanged; confirmed jobs
  keep the case route.
* Draft Job from Service: only new runs use the new route.
* Is Warranty / Site Address (helpdesk 18.0.1.0.3 / 1.0.4, not deployed yet): unchanged;
  `warranty_site_address` informational only; matching uses `warranty_site_id` / case site.
* Versions: fsm 18.0.1.2.0, helpdesk 18.0.1.1.0, mrf bridge patch version, core only if views.

## 6. Acceptance and regression tests

| ID | Scenario |
|---|---|
| A-01 | 3 services of 2 cards (same customer / site) → 1 Draft service-origin job, no ticket / case, planned date |
| A-02 | Incompatible selections refused (other customer / company / site, on another job / case, card not Confirmed, windows, sequence) |
| A-03 | Second Create Service Job for the same services refused; "add to open Draft job" works |
| A-04 | Link an open warranty ticket; Create a new ticket (Is Warranty, site); one case, Free Service type, services linked once |
| A-05 | Confirm refused without ticket / case, with closed ticket, Not Eligible, payment Hold / pending approval; passes without general approval (D-A) |
| A-06 | Confirm creates exactly 1 visit + worksheets per service / template; second Confirm refused |
| A-07 | Visit completion consumes the services once; cancel before Confirm releases them |
| A-08 | Draft Job from Service creates a Draft service-origin job (no ticket / case); later service joins it |
| A-09 | Usage alert from a completed worksheet reading ≥ threshold; no alert from case / draft readings; no duplicate |
| A-10 | Route H unchanged (existing Part 3 / 4 tests) |
| B-01 | Ticket and case created without Case Type; Is Warranty / confirmed-card rules apply |
| B-02 | Preliminary Check: card / serial / validity / payment only; failures use the existing routes |
| B-03 | Prepare Inspection Job → inspection visit; MRF, quotation, free services, Complete Visit refused |
| B-04 | Complete Inspection requires findings + Case Type; case back to New with type; job completed; nothing consumed |
| B-05 | Full eligibility + approval / chargeable / excluded items for the new type; then normal job |
| B-06 | Approve / Close / Prepare normal job / MRF refused while undetermined |
| B-07 | Free Service cases (Route S, Pending Services, automation) always typed Free Service |
| B-08 | Repeated failure not counted while undetermined; counted after typing |
| R | Full regression (≈ 510 tests), trial upgrade on a 18_4 copy with job / case / MRF value comparison |

## 7. Remaining business decisions

| ID | Question | Recommendation |
|---|---|---|
| G1 | Fee for the inspection visit of an undetermined case | Helpdesk team **Inspection Required** (existing SRS §2.11 setting) → existing Chargeable Inspection route; otherwise a free Warranty Inspection visit |
| G2 | Who sets the final Case Type | The technician in Complete Inspection; Helpdesk users may change it while the case is New (logged) |
| G3 | Free services on an undetermined case | Not allowed (a free service request is typed Free Service) |
| G4 | Approval before the inspection visit | None beyond Preliminary Passed and the payment rules (Hold / Block / Approval Required); the existing case approval applies after typing |
| G5 | Fault found during a scheduled free-service visit | New complaint case on the same ticket (no type change of the Free Service case) |
| G6 | Ticket team for Create in step 7 | Draft Job Helpdesk Team of the company (existing setting) |

## 8. Implementation notes (2026-10-29)

* Files: fsm `models/warranty_service_job.py` (origin, optional case, stored values, guards,
  confirm rules, inspection completion), `models/warranty_service_origin.py` (merge check,
  Create Service Job, Create or Link Helpdesk Ticket, Report Fault, usage alerts, D-A approval
  skip), `models/warranty_case.py` (Prepare Inspection Job, open-job duplicate guard),
  `models/warranty_draft_job.py` (D-B), `models/project_task.py` (Complete Inspection routing),
  `wizard/warranty_service_origin_wizards.py`, `wizard/warranty_chargeable_wizards.py` (final Case
  Type), `views/warranty_service_origin_views.xml`, settings (Inspection Worksheet Template),
  migration 18.0.1.2.0; helpdesk `models/warranty_case.py` (optional type, preliminary check,
  inspection fields, guards, G1 conversion), `models/warranty_service_entitlement.py` (window
  rule shared), create wizard / case view; mrf `warranty_case.py`, `warranty_service_job.py`
  (guards only).
* Behaviour details: the Free Service case of a service-origin job gets the policy's Automatic
  Case Requested Items (Q24: none -> Manual Review); Confirm also requires the job's and the
  case's free services to be identical (a service removed on the case -> cancel / recreate);
  linking a ticket without site fills its Site; the inspection job type is excluded from hold,
  batch completion and MRF; a paid inspection (G1) of an undetermined case returns to New when a
  warranty Case Type is found (the inspection fee credit follows the existing accounting rules,
  not automated here).
* Not implemented (by decision): AMC entitlements (D-D, open SRS requirement); ticket smart
  button for service jobs (the case smart button is used).
* Tests: `tests/test_srs_service_flow.py` (13), `tests/test_draft_job_from_service.py` rewritten
  for D-B (11), Settings count 39. Full regression 515 tests, 0 failed, 1 known error
  (`test_13_serial_rules`). Trial upgrade on `wm18_4_srs_check` (copy of 18_4, backup
  `backups/warranty_management_18_4_before_srs_flow_20261029_1054`): no error; jobs, cases,
  free services, MRFs, tickets, cards and account moves identical.
