# Warranty Management – Part 4 (Service Job + Field Service) – Design Decisions

Sources: SRS (`Warranty_Module_SRS (1) (1).pdf`), Development Mapping, Part 4 diagram
(`part4.drawio.svg`). Every decision below was approved by the business owner.

| Status | Phases 4.0 and 4.1 done; Phase 4.2 implemented (2026-10-21); Phase 4.3 implemented on `warranty_test` (2026-10-22), waiting for approval. Phase 4.4 not started. |
|---|---|

## Basic decisions (approved 2026-10-20 / 21)

| ID | Topic | Approved resolution |
|---|---|---|
| P1 | Module | Separate module `warranty_management_fsm` (depends `warranty_management_helpdesk`, `industry_fsm`). |
| P2 | Field Service | Installed on `warranty_test` only. Odoo auto-installed bridge modules with it (see "Open points"). |
| P3 | Service Job | Custom model `warranty.service.job`; Field Service tasks are its visits (later phases). |
| P4 | Job sources | Approved warranty cases (+ Chargeable cases in 4.10). Jobs from free services (Part 2 "Draft Job from Service") = separate scope decision 4.11, not forgotten. |
| P5 | Technicians | `res.users`. |
| G1 | Free service status "Job Created" | Option B: new status, set at Service Job confirmation (4.3) with all identified Part 2 / 3 impacts handled then. |
| G2 | Claims without free service | Service Jobs allowed without free services. |
| G3 | Feasible Date Window | **Pending BA approval** – no date rule, no default restriction. |
| G4 | Conflicting status / entitlement | 3.1 availability rule + same card / customer / company + not on another open job / active case. |
| G5 | Helpdesk ticket | The case ticket is reused; confirmation blocked when the ticket is closed (4.3). |
| R2 | Jobs per case | One active (open) Service Job per case; rescheduling and follow-up visits continue under the same job (4.8). |
| 4.10 | Chargeable jobs / Job Trigger | Included as a phase. |

## Phase 4.0 – Setup

* Field Service (`industry_fsm`) installed on `warranty_test`; regression 195/195 after install.
* Module `warranty_management_fsm`; model `warranty.service.job` (sequence `JOB/000001`, status list
  of SRS 9.13: Draft, Planned, Confirmed, In Progress, Awaiting Parts, Workshop, Completed,
  Cancelled); access: internal users read, Helpdesk / Field Service users read-write-create,
  Helpdesk managers delete (Draft / Cancelled jobs only); multi-company record rule; menu
  Warranty → Service Jobs.

## Phase 4.1 – Service selection, merge and draft Service Job

Diagram: From Part 3 *Eligible / Approved* → Read Linked Service Entitlement(s) → Multiple Services
Selected? → Check Service Merge Compatibility → Compatible? → Merge / Show Merge Validation
Error → Set Entitlements Selected / Merged · Use Single Service Entitlement → Create / Prepare
Service Job.

* Case button **Prepare Service Job** (Helpdesk users): only Approved cases with result Eligible,
  only when no open job exists (R2). The job takes all free services linked to the case.
* 0 services → job for the claim (G2); 1 service → Merge Status **Selected**; several →
  compatibility check (only for several, as in the diagram) → **Merged**, otherwise a validation
  error listing every service and reason; nothing is created or changed.
* Compatibility (G4): same customer / company, same site (delivery address of the card's sales
  order, = case site when set), status still available (3.1 rule), same card as the case, not on
  another open job, not on another active case. G3 date window: not applied (pending BA).
* The free service **status is not changed** in 4.1 (Job Created comes with confirmation, 4.3).
* **Cancel** (Draft / Planned, Q42): job Cancelled, services back to Not Merged (not consumed),
  the case stays Approved, a new job can be prepared.
* Job: case, ticket, customer, site, product, serial, card, unit (from the case), free services,
  Free Services Type (No Free Service / Single / Merged); smart button Service Jobs on the case;
  Service Job on the free service form; chatter on job, case and services.

### Verified interactions (before 4.1)

| # | Interaction | Result |
|---|---|---|
| V1 | 3.1 availability rule ignores merge status / jobs | 4.1 checks "already on another open job" itself. |
| V2 | Merge Status only read by Part 2 | Set by 4.1 (Selected / Merged), reset on cancel. |
| V3 | Part 2 expiry protection | Selected / Merged services are not moved to Missed / Expired and get no due / expiry alerts – already for a **draft** job (approved Part 2 rule). Without G3 nothing limits how long a draft job keeps them protected. |
| V4 | Cancel | Not Merged again → the next daily monitoring applies the normal rules (tested). |
| V5 | Status unchanged in 4.1 | Case revalidation (Q41) at confirmation keeps working. |
| V6 | Part 2 Schedule wizard | Still usable on Selected / Merged services (G22, 4.2). |

## Open points

* **Auto-installed modules (P2):** installing `industry_fsm` automatically installed
  `helpdesk_fsm`, `helpdesk_fsm_report`, `industry_fsm_report`, `industry_fsm_sale`,
  `industry_fsm_sale_report`, `industry_fsm_stock`, `industry_fsm_sms` and timesheet modules
  (standard Odoo auto-install; the same happens on any database). `helpdesk_fsm` offers a ticket →
  task action that bypasses the Service Job (SRS #27): to be blocked for warranty tickets or the
  module uninstalled – decision before 4.3.
* G3 (BA), G6 (worksheets, before 4.4), G20 / G23 (before 4.10) and G7–G22 before their phases.

## Phase 4.2 - Service Job planning (approved D1-D13, 2026-10-21)

| ID | Decision |
|---|---|
| D1 | Planned Date mandatory before Planned. |
| D2 | Technicians: active Field Service users (group Field Service / User) allowed in the job's company (selection filtered + server check). |
| D3 | The Main Technician cannot also be a Support Technician. |
| D4 | ~~No past Planned Date when planning.~~ **Revised 2026-10-29 (user approval):** removed - not an SRS rule; past Planned Dates are allowed on Draft / Planned jobs and in Plan Next Visit (postponed / retrospective visits). Free service window (D3, non-blocking for planning since its 2026-10-29 revision), sequence, eligibility, approval and security checks unchanged; Planned Date stays tracked. |
| D5-D9, D13 | Phase 4.3 (project, revalidation, Plan Intervention block, task address, notifications). |
| D6 | No default visit duration: the task keeps only the planned start (limitation: no end time in the Gantt until set). |
| D10 | No date-window rule (G3 pending BA); limitation V3: open draft / planned jobs keep their free services protected from Missed / Expired. |
| D11 | Part 2 Scheduled Date not used in 4.2; review before 4.3 for jobs with free services. |
| D12 | Cancelling confirmed jobs: Phase 4.8. |

Implementation: job fields Planned Date, Main Technician, Support Technicians (tracked, editable in
Draft / Planned only); **Prepare for Confirmation** (Helpdesk users): Draft -> Planned, blocked
without Planned Date or Main Technician; Planned jobs stay cancellable (Q42). No Field Service task
in 4.2; free services unchanged; Warranty Only jobs (no free service) supported.

## Phase 4.3 - Confirm Service Job and Field Service task (2026-10-22)

Confirm Service Job (Helpdesk users, job Planned) in diagram order, one transaction:
1. checks: Planned, Planned Date + Main Technician, the case ticket exists and is not closed (G5),
   chain ticket -> Approved case -> job (same company);
2. **Q41 / D7** eligibility revalidation (same checks as Check Eligibility, no new approval
   requests); failure: not confirmed, no task, reasons logged on job and case, case status /
   result unchanged, warning notification;
3. Field Service task in the company's **Warranty Field Service Project** (new setting, D5; else
   the standard Field Service project): name JOB - WCAS - product, customer = case site else
   customer (D9), planned start = Planned Date (D6: no end), assignees = main + support
   technicians (standard internal assignment notifications, D13), ticket (helpdesk_fsm field),
   Service Job, Warranty Case, Free Services, Visit No. 1;
4. free services -> **Job Created** (G1, previous status kept in `job_previous_state`), Merge
   Status unchanged; job **Confirmed**; case **Approved -> Job Created**.

* SRS #27 / D8: helpdesk_fsm *Plan Intervention* refused for tickets with warranty cases;
  constraint: no Field Service task of such a ticket without Service Job; a job's task belongs
  to the job's ticket. Other tickets unchanged.
* Free services of an open job cannot be deleted.
* D11: the Part 2 Scheduled Date of free services is not read or changed.
* Security decision applied (to confirm): the task is created with sudo by the checked
  confirmation, because Helpdesk users may have no Field Service rights (alternative: require
  Field Service rights to confirm).
* Module now also depends on `helpdesk_fsm` (installed automatically with Field Service).
* Worksheet instances: Phase 4.4 (G6).

## Phase 4.4 - Worksheet instances (approved W1-W6, G9; 2026-10-22)

* W1 (G6): model `warranty.job.worksheet` (SRS 10.5 "Worksheet Instances"): job, task, case,
  free service, product, template, status, usage reading, attachments, notes. Several instances
  under one Field Service task. The checklist is the standard worksheet template record (Studio
  model), created on first opening (only the task link is required).
* Generated at Confirm Service Job (after the task, before Job Created / Confirmed), once per
  task (retry: no duplicates): one per linked free service; Warranty Only: one for the case
  product (W3). Template: free service snapshot -> product Worksheet Template -> Field Service
  project default; none: instance without checklist, confirmation not blocked (W2).
* W4: one instance -> the task's standard Worksheet template = its template, the standard
  Worksheet button opens the same record; several -> standard buttons hidden, task button
  "Worksheets" (list) + job tab "Worksheets".
* W5: Field Service users read / write instances (not create / delete); Helpdesk users create
  (through confirmation); company rule.
* W6 (G7): To Do (4.4) -> In Progress -> Completed (4.5 / 4.7).
* G9: usage-based warranty (card basis Usage) -> Usage Reading Required with the card unit;
  blocking at visit completion in 4.5; period-based: no reading.
* Customer-email fix (a): warranty tasks never send stage email templates (e.g. "Intervention
  Scheduled") nor stage rating requests to the customer; other tasks standard; internal
  technician notifications unchanged.
* Task-creation security (a) confirmed: sudo only for the task / worksheet instance creation of
  the checked confirmation.


## UI label (approved 2026-10-22)

* Service Job button "Prepare for Confirmation" renamed **Plan Job** (label only; method
  `action_prepare_for_confirmation`, Draft -> Planned, validations, groups and visibility
  unchanged).

## Phase 4.5 - Visit start and usage readings (approved V1-V5; 2026-10-22)

* V1: the standard Field Service timer starts the warranty visit (no new button). Warranty tasks:
  the user needs an active employee in the task company before the timer starts (the timesheet
  is created on it at stop); other tasks standard.
* V2: first start of a visit of a Confirmed job -> job In Progress, the visit's free services
  Job Created -> In Progress, worksheets To Do -> In Progress; case stays Job Created; notes on
  job, case and services. Later starts / resume: nothing. Warranty Only jobs: no services.
* V3: checklist, notes and attachments as in 4.4; no extra mandatory rule.
* V4: worksheet reading (usage-based): > 0, unit = the card's usage unit, not lower than the
  latest earlier reading of the same warranty unit (worksheets of other visits planned up to
  this job, not cancelled jobs; eligibility readings of the unit's cases; never itself, the
  other worksheets of the same visit or another unit). New stored field Unit Warranty on the
  worksheet (job unit, else the only card unit of the product). Mandatory before completion:
  with the completion (V6 / 4.7).
* V5: reading above the usage limit -> warning note on job and case, no block / decision.
* V6 / V7 completion lock (approved C1-C3, 2026-10-22): on tasks of a Service Job, Done,
  Cancelled and Task Done are refused from every route (form, kanban, status widget, Mark as done
  incl. the stop-timers path, API, import; also for sudo writes). Only
  `project.task._warranty_close_visits()` (private; reserved for the Part 4.7 completion and
  Part 4.8 cancellation) closes them, with a Python marker object no client can send. Already
  closed tasks keep their status (editable, reopen allowed); other tasks standard; worksheets
  never Completed in 4.5. C3: standard Send Report kept (manual action, not the suppressed
  automatic stage emails).

## Phase 4.6 - Parts / workshop blockers (approved M1-M8; 2026-10-22)

* M1: job buttons **Awaiting Parts**, **Workshop Repair** (In Progress only) and **Resume Job**
  (Awaiting Parts / Workshop only), each with a required reason (wizard); notes on job and case.
  The hold statuses can be entered / left only through `_warranty_set_hold()` (Python marker; a
  direct status write from UI / API / import / sudo is refused); no double hold.
* M2: free services stay In Progress, not consumed. M8: the visit (task), its timer and
  timesheets are not changed; no cancel / reschedule (4.8).
* M3 option B: the case status is not changed (stays Job Created); a note on the case when the
  job enters or leaves a hold. **SRS deviation (BA approval required):** SRS 9.8 step 6 says the
  case moves to Awaiting Parts.
* M4 / M5: no Material Request / MRF (Part 5, existing module) and no Repair Order / intake
  (Part 6); none created, no temporary fields.
* M6: `_warranty_completion_blockers()` (used by 4.7) reports a job on hold; the reserved close
  path refuses completion (Done) while the job is Awaiting Parts / Workshop. The direct task lock
  is unchanged.
* M7: Field Service and Helpdesk users; company by the record rule.

## Phase 4.7 - Service Job completion (approved K1-K10; 2026-10-22)

### Verification of the standard features (before implementation)

* **Customer signature (K2):** the standard Sign Report stores `worksheet_signature` /
  `worksheet_signed_by` on the task (portal controller, written with sudo). It is offered only
  when the project allows worksheets, the timer is stopped and the report has content (timesheet
  hours or a worksheet of the task's template). It is one signature per visit. The standard
  `action_fsm_validate` does **not** check it, so Complete Visit checks it. Hardening: on warranty
  visits, the signature fields can only be written by the standard Sign Report (sudo); a direct
  UI / API write by a user is refused.
  *Limitation (not changed):* the standard report shows only the worksheet of the task's own
  template; with merged services using different templates, the other checklists are not on the
  signed report.
* **Required answers (K3):** a Studio "Required" answer is a **view attribute**. It is enforced
  only by the worksheet form in the browser, not on API writes, and not at all when the worksheet
  is never opened (no record). Only model-level required fields are enforced by the ORM, and only
  when a record is saved. So the standard validation is not reliable on its own. Complete Visit
  re-checks server-side, on the saved worksheet record:
  * model-level required fields;
  * the top-level fields of the worksheet form whose `required` expression is true and which are
    not invisible (expressions are evaluated on the record values; an expression that cannot be
    evaluated counts as required);
  * "filled in" also needs the record to exist (the check never creates it), and a checklist
    without required answers needs at least one answer (a non-empty text / HTML, a checked box,
    a non-zero number, a selected value).
  * As in the web form, a required checkbox or number is always considered answered.
  No change to the approved design was needed.
* **One checklist record per task and template (found in 4.7):** the standard worksheet model has
  a unique constraint on the task. The temporary 4.7 workaround (shared record) was **not
  approved** and is replaced by the Warranty Worksheet templates below.

### Decisions

* K1: **Complete Visit** button on warranty Field Service tasks (Field Service and Helpdesk
  users; confirmation dialog). The standard **Mark as done** is hidden on warranty tasks (and
  still refused by the completion lock); other tasks are unchanged.
* K2: company setting **Customer Sign-off Required** (default on): the standard Sign Report
  signature must exist.
* K3: company settings **Worksheet Checklist Required** (default on: every worksheet with a
  template has its checklist filled in, see above) and **Worksheet Attachment Required**
  (default off: at least one attachment on every worksheet instance).
* K4: checks, all problems listed at once: visit started (job In Progress), not Awaiting Parts /
  Workshop (M6), no running or paused timer of any user on the visit or its timesheets (the
  technician stops it; timesheets are never changed), sign-off, checklist, attachments, and a
  valid usage reading (V4 rules re-checked) on usage-based worksheets.
* K5: in one savepoint (all or nothing): task Done + Task Done through the reserved close path
  (`_warranty_close_visits`), worksheets Completed, job Completed, the visit's free services
  Completed with Merge Status Completed (consumed: Part 2 counts Completed services for Used /
  Balance). Already completed services are skipped and a completed job / closed visit is refused,
  so a retry consumes nothing. Warranty Only jobs complete without free services. No Sales Order
  is created (the standard `action_fsm_validate` is not called).
* K6: case Job Created -> **Completed**; the Helpdesk ticket is not changed.
* K7: task field **Visit Outcome** = Completed (other outcomes: Part 4.8).
* K8: history notes on the job, case, card(s) and consumed free services (no history model).
* K9: the usage reading stays on the worksheet and is written in the notes; card, unit and case
  readings are not changed.
* K10: Field Service and Helpdesk users; the job's company by its record rule (write access).
* No bypass: Completed statuses of the job, worksheets, free services of a service job, and the
  case, and the Visit Outcome, are set only by the completion (Python marker object; UI, API,
  import, a context flag or a plain sudo write are refused).

### Open points

* Editing a completed worksheet (reading, notes, attachments) and reopening a completed visit are
  not blocked (no approved rule).
* Worksheet "Rejected" status: no SRS rule (open).

## Warranty Worksheet templates - per-instance checklists (approved 2026-10-22)

* SRS 10.5 "Worksheet Instances: one worksheet per merged service/product template", with
  independent answers per instance. The standard worksheet framework supports other host
  models (Maintenance / Quality worksheets): templates with **Host = Warranty Worksheet**
  (`res_model = warranty.job.worksheet`) generate a checklist model with one record per
  worksheet instance (`x_warranty_job_worksheet_id`, unique per instance). Studio designs them
  like any worksheet template. Menu: Warranty > Configuration > Warranty Worksheet Templates
  (Helpdesk managers).
* Template access (security fix approved 2026-10-23): the standard rule "Worksheet Template:
  Project Only" limits Project users / managers to task-hosted templates, so Warranty Worksheet
  templates got their own rules (as Maintenance / Quality): **read** for Project / Field Service
  and Helpdesk users; **edit** for Helpdesk managers only (Project managers keep managing the
  task templates and only read the warranty ones). ACL: Helpdesk users read, Helpdesk managers
  full. Standard rules and the worksheet multi-company rule unchanged. **Standard limitation:**
  creating or deleting any worksheet template (also Field Service ones) generates / removes a
  model, which Odoo reserves for Administration / Access Rights; designing it needs Studio
  (administrators). So templates are created / designed by administrators (e.g. Mitchell Admin);
  Helpdesk managers edit their settings.
* Access: the framework's generated rules (Field Service and Helpdesk users: all; other internal
  users: own records) plus a **company rule** on the instance's company.
* The product / free service Worksheet Template accepts both kinds. One task per visit and one
  instance per service / product are unchanged.
* Task (Field Service) templates keep working for a single instance (standard task Worksheet
  button, W4). **Newly confirmed jobs** (and next visits) are **blocked** when one task template
  would serve several instances of a visit (including the project's default template), with a
  message to set a Warranty Worksheet template. Existing worksheet records and completed jobs
  are unchanged.
* With Warranty Worksheet templates (or several instances), the standard task Worksheet buttons
  are replaced by the visit's Worksheets list.
* Complete Visit checks every instance's own checklist (required answers server-side, 4.7).
* The Field Service report and its portal page (Sign Report) show every instance checklist, so
  the customer signs all of them.

## Phase 4.8 - Visit not completed, reschedule, follow-up, cancellation (approved 2026-10-22)

Sources: SRS 2.8, 9.4(9), 9.13, 10.5 (Field Service visit Job Outcome, Service Job), scenarios
7 / 16, automation table (p. 75), Part 4 diagram "Visit Completed? No".

* L1: task button **Visit Not Completed** (Field Service / Helpdesk users): reason (SRS 2.8:
  Customer Unavailable, Awaiting Parts, Technical Escalation, Workshop Repair Required, Access
  Issue, Other), required notes, next action **Reschedule / Follow-up / Cancel**. The timer must
  be stopped (timesheets are never changed).
* L2 option B: Visit Outcome keeps the six SRS values and is set automatically: Reschedule ->
  Rescheduled; Cancel -> Cancelled; Follow-up -> Customer Not Available (reason Customer
  Unavailable), Part Pending (Awaiting Parts), else Follow-up Required. Outcome and reason are
  separate from the Odoo task status.
* L3: the visit is closed through the reserved close path with Odoo status **Cancelled** (never
  Done / Task Done; SRS "Incomplete" = outcome + reason). Job -> **Incomplete** (new status).
  Free services stay open (In Progress / Job Created, Merge Status kept) and are **not
  consumed**; the case stays Job Created; the ticket stays open.
* L9 / L6 / L3: **Plan Next Visit** (Helpdesk users only; also directly in the wizard when a
  Helpdesk user reschedules): new planned date (past dates allowed - D4 revised) and technicians (4.2 rules), new
  linked visit (next number, **High priority** - R5, same free services, **new worksheet
  instances**), job -> **Rescheduled** -> In Progress at the next timer start -> Complete Visit
  (4.7) consumes the services once.
* L6 follow-up: same as reschedule without a planned visit (SRS 2.8 "the new visit can remain
  unscheduled"); never completed, nothing consumed.
* L8: allowed from Awaiting Parts / Workshop; the hold notes stay; the note records the status
  change.
* L5 / L7: **Cancel** (in the wizard) or **Cancel Job** (job, Helpdesk users, required reason):
  open visits closed Cancelled (outcome Cancelled), job **Cancelled** with its reason, free
  services back to their status before the job (stored at confirmation) and Not Merged, **not
  consumed**, case back to **Approved** (Q42); ticket unchanged. Draft / Planned jobs keep Cancel.
* L10: history notes (reason, notes, outcome, planned date, technicians, status change, new
  visit, previous date) on the job, case, card(s) and free services; job Reschedule Count
  (visits after the first) and Visits tab. **Locks** on closed warranty visits: planned date /
  deadline, technicians, status (no reopening), visit number, free services, outcome, reason,
  notes; their timesheets (hours, date, employee, task, description; create / delete) and
  worksheet instances (reading, unit, attachments, notes). This also closes the 4.7 open point
  (editing / reopening completed visits).
* Found during 4.8: standard Odoo (project_enterprise) unschedules a task cancelled before its
  planned date (clears the start date and deadline). For cancelled **warranty visits** this is
  skipped, so the attempt keeps its planned date (L3 / L10); other tasks are unchanged.
* R6: free service Reschedule Count = Part 2 schedule reschedules + next visits of the service
  (computed, display only; no stored record changed).
* No bypass: Incomplete / Rescheduled / Cancelled (after confirmation) and re-planning are set
  only by these flows (Python marker); outcome / reason / notes only through the close path.

### SRS deviations (BA approval required)

* **Customer notification (SRS 2.8, diagram "Notify Customer", scenario 16):** no automatic
  customer email / WhatsApp; a Helpdesk To-Do ("Plan the next visit" / "Inform the customer of
  visit ...") and internal notes instead (approved L4). **Not SRS-compliant until BA approval.**
* **Configurable consumption (SRS 9.4(9) / scenario 7 "unless configured", diagram "Keep
  Entitlement Unconsumed unless configured otherwise"):** cancelled and rescheduled visits never
  consume; the optional consume setting is not implemented (approved L5).
* Case status while a job is on hold (M3, SRS 9.8): unchanged (pending BA, see 4.6).

### Not in 4.8

Batch completion (4.9), chargeable jobs (4.10), automatic reschedule when parts arrive (Part 5
MRF), worksheet "Rejected" status (no SRS rule).

## Product Worksheet Template editable with a policy (SRS 2.7 fix, approved 2026-10-23)

* SRS 2.7 / 10.1 / 10.3: the worksheet template is always defined on the product master and
  inherited by the free service (snapshot at creation) and the worksheet instance. The product
  form made the field read-only while a Warranty Policy applied (it is not a policy value): the
  read-only condition is removed (warranty_management product form). Other policy-controlled
  product values stay read-only; no policy field; policy resolution unchanged.
* Resolution unchanged: free service snapshot -> product template -> Field Service project
  default. Existing free service snapshots are not refreshed (set the product template before
  the services are created).

## Phase 4.9 - Batch Job Completion (approved B1-B10, T1; 2026-10-23)

Sources: SRS scenario 15 (p. 11), feature classification (p. 23), Service Job field
"Completion Mode" (p. 65), validation table (p. 74), Job Planner role (p. 77). No batch steps in
the Part 4 diagram.

* B1 / B2: **Complete Selected Jobs** on the Service Jobs list (multi-select), Helpdesk users
  only (Job Planner); technicians keep Complete Visit. Company record rules apply; a job the user
  cannot write is skipped ("No access").
* B3: job field **Completion Mode** Single / Batch Eligible; new jobs Batch Eligible. No column
  default: existing jobs are not rewritten, an empty value counts as Batch Eligible. Editable
  while the job is open. Single jobs are skipped by the batch.
* B4 / B5: each selected job is validated independently with the 4.7 backend
  (`_warranty_visit_completion_problems` on its only open visit) plus Batch Eligible and access.
  Jobs with a business validation problem are skipped **before any write** (status, visits,
  worksheets, case, free services unchanged).
* B6: two-step wizard: Check / Preview (Ready / Not Ready with every reason, nothing changed)
  -> Complete Ready Jobs (each job revalidated just before completion) -> Completed / Skipped per
  job with reasons.
* B7 / B8: completion = the secure 4.7 `_warranty_complete_visit` (reserved close path,
  completion lock, savepoint per job, free services consumed once); no status shortcut.
* B9: the 4.7 history notes on job, case, card(s) and free services, marked "batch completion".
* T1: business validation failures skip the job; an unexpected technical error is not caught:
  the whole batch transaction (completions, pending changes and audit records) is rolled back.
* Job situations: Completed / Cancelled -> "Already closed"; Draft / Planned -> "not
  confirmed"; Confirmed / Rescheduled -> "has not been started"; Incomplete -> "No open visit";
  Awaiting Parts / Workshop -> "resume it first"; several open visits -> skipped. Only the
  current open visit is completed; closed earlier attempts are never reopened. The Helpdesk
  ticket stays open.

### SRS clarification (BA confirmation pending)

* p. 23 "completes only records that pass" and p. 74 "All selected jobs must have completed
  worksheets, required usage, no open MRF/repair blockers and required sign-off - avoids invalid
  mass closure" are read together as: every job closed by the batch must pass these checks;
  failing jobs are skipped, the batch is not aborted. "Completed worksheets" before completion =
  the K3 checklist / required answers (worksheets become Completed by the completion).
* **Not implemented yet:** Material Request (Part 5) and Repair Order (Part 6) blockers. Until
  then only Awaiting Parts / Workshop block completion; the check is the shared 4.7 / 4.9 method
  for Parts 5 / 6 to extend.

## Phase 4.10 - Chargeable Jobs / Job Trigger (approved C1-C12; 2026-10-23)

Sources: SRS 2.6 (p. 8), 2.11 (p. 10), 9.7 (p. 46), Helpdesk interface (p. 14), configuration
(p. 21); Development Mapping Part 8 (inspection billing, credit note).

* C1: Helpdesk team **Chargeable Job Trigger**: On Sales Order Confirmation (default) / On
  Payment.
* Quotation field **Chargeable Purpose** (Inspection / Repair / Excluded Items), set when a
  quotation is created from a Chargeable case (Convert to Chargeable, Quotations button, repair
  quotation), read-only. Only these orders trigger a job; other customer orders never do.
* C2: On Sales Order Confirmation = the chargeable order of the case's current step is
  confirmed (at least one product line); no invoice / payment needed. On Payment = that order is
  **fully invoiced** and every posted customer invoice **settled** (Part 3.3 rule: Paid, or In
  Payment fully covered by registered payments); a paid down payment with an unpaid remainder
  does not trigger. Checked at order confirmation, invoice paid (reconciliation), payment
  posting and by Prepare Service Job. Part 3.3 Payment Eligibility (warranty card's original
  order) is unrelated and unchanged.
* C3: one **Draft Chargeable Service Job** per triggering order, created automatically (sudo:
  the trigger may come from a salesperson / accountant; company, ticket, case from the case);
  never while the case has another open job; repeated events and **Prepare Service Job**
  (fallback on Chargeable cases, only when the trigger is met) never create a second active job
  (a cancelled job does not count).
* C4: planning and confirmation as 4.2 / 4.3, without the warranty eligibility revalidation;
  confirmation checks the case is Chargeable and **revalidates the trigger** (cancelled order /
  reversed payment -> blocked).
* C5: job field **Job Type** (Warranty / Chargeable Inspection / Chargeable Repair / Chargeable
  Excluded Items); worksheets, timer, hold, reschedule, completion and batch reused.
* C6: chargeable jobs take no free service and consume none (linked free services unchanged).
* C7: Complete Visit on an inspection job asks for the **Inspection Result**: Diagnosis
  (required), Repair Required Yes / No (required), Repair Details (required with Yes); stored on
  the job (set by this step only). Batch completion skips inspection jobs (result needed).
  Yes -> draft **repair quotation** (diagnosis / details as a note line, no price, never sent or
  confirmed automatically) + send To-Do; the repair job comes with the Job Trigger of that order.
  **Customer Declined Repair** (case, Helpdesk users, reason): inspection-only closure, open
  repair quotations cancelled, inspection history kept.
* C9: Partial cases keep the Part 3 flow (an excluded item is approved by a confirmed order =
  the confirmation trigger already); no extra trigger; the warranty job shows the customer-
  approved excluded items (read-only, for the technician).
* C10: no automatic customer notification; a Helpdesk To-Do "Send quotation ... to the
  customer" (ticket's assigned user, else the case creator) when a chargeable quotation is
  created, closed only when the quotation is sent (Send / Mark as Sent).
* Cancel Job (4.8) on a chargeable job returns the case to **Chargeable** (not Approved).

### Case lifecycle (C12)

| # | Step | Case | Chargeable Type | Job | Order |
|---|---|---|---|---|---|
| 1 | Convert to Chargeable | Chargeable | Inspection | - | Draft inspection quotation + send To-Do |
| 2 | Sent, customer approves | Chargeable | Inspection | - | Sent -> Confirmed |
| 3 | Trigger met | Chargeable | Inspection | Draft Chargeable Inspection job (automatic) | Confirmed (paid for On Payment) |
| 4 | Plan / Confirm / start | Job Created | Inspection | Confirmed -> In Progress | - |
| 5a | Inspection - no repair | Completed (outcome Inspection Only) | Inspection | Completed + diagnosis | - |
| 5b | Inspection - repair required | Chargeable | Repair | Inspection job Completed + diagnosis (kept) | Draft repair quotation + send To-Do |
| 6a | Customer approves repair | Chargeable | Repair | Draft Chargeable Repair job at the trigger | Priced, Confirmed (paid for On Payment) |
| 6b | Customer rejects repair | Completed (outcome Repair Declined) | Repair | Inspection job kept | Repair quotation cancelled |
| 7 | Repair job completed | Completed (outcome Repair Completed) | Repair | Completed | Invoiced (standard Sales) |
| 8 | Accounting completed, case closed | **Closed - Part 8 (pending)** | | | |

Inspection and repair jobs stay separately on the case (Service Jobs); the Chargeable Type
change is tracked.

### SRS deviations / pending (BA)

* **C2 On Payment = full payment** of the chargeable order: business decision; the SRS does not
  define the payment threshold (BA confirmation pending).
* **C10:** the customer is notified manually (Send + To-Do), not automatically as SRS 2.11
  says - **not SRS-compliant until BA approval**.
* **C8 / Part 8 (pending, not implemented):** inspection fee deduction (deduction product or
  discount), credit note against the posted inspection invoice, discount fallback, case
  **Closed** after the accounting steps. **The end-to-end chargeable repair workflow is not
  complete until Part 8.**
* C9: no payment trigger for Partial (warranty) jobs - interpretation, BA confirmation pending.

## Cross-Warranty-Card Service Merge (approved Option A, D1-D8, UI 1-4; 2026-10-23)

Business case: a corporate customer with 8 AC units at one site, each with its own warranty card
and free service, serviced together: one ticket, one case, one job, one visit, 8 worksheets,
each service consumed once on its own card. Cards and worksheet answers are never merged.

* Option A: one warranty case links free services of several cards of the same customer
  (company, site). The case's Warranty Card stays the primary card (D5); new searchable
  **Service Cards** (case) and **Warranty Cards** (job).
* D1: every participating card is checked (customer / company, confirmed, warranty period of the
  selected units, site, units selected); any failure blocks the case and is named as
  "card (services): reason"; nothing is excluded silently. Payment: each card's sale invoices
  with its own policy's Payment Check Required; strictest Overdue Claim Handling of the
  policies; the case waiver covers the case.
* D2: linked free services and Units to Service can be changed in New and Eligibility Checked;
  a change in Eligibility Checked resets the case to New (approval and payment approval To-Dos
  closed, logged); after Approved: refused.
* D3 (BA-approved interpretation of SRS 2.5 "feasible date window" / G3, not an SRS formula):
  window = earliest Alert Date (due date - the card's Service Due Alert Days), else the Due
  Date; latest = Grace Period End (due date + the card's Grace Period Days), else the Due Date
  (from the card values, also when monitoring is off); services without due date (usage-based)
  have no window. The windows of the selected services must overlap and not end before today
  (eligibility and Prepare Service Job); the planned visit date (company warranty timezone)
  must be inside every window (Plan Job, Confirm Service Job, Plan Next Visit). **Revised 2026-10-29 (user approval):** the due date / window is a target, not a planning restriction - a planned date outside a window is accepted at Plan Job, Confirm Service Job and Plan Next Visit (also service-origin jobs) and logged as a non-blocking Service date note; the overlap / not-ended rule for case eligibility and service selection, sequence, status, balance, validity, eligibility, payment and approval checks are unchanged; due dates unchanged. Service-level
  reasons; nothing removed silently. No Early Service Days setting.
  **Revised 2026-10-29 (cross-card merge clarification, user approval):** the windows need NOT overlap - compatible free services of different cards (same customer, company, site, eligibility) are merged into one job and one visit whatever their due dates; a service whose permitted service dates ended before today is still refused; Enforce Service Sequence (same card) unchanged; Draft Job from Service joins with the same rules (dates + sequence).
* D4: free services stay card-level (Part 2 unchanged). **Units to Service** on the case:
  single-unit cards automatically, multi-unit cards all units by default, the Helpdesk user
  removes the units that do not need maintenance. One worksheet per (free service x selected
  unit) with its service, card, unit, product and serial; unselected units get none. Each
  card-level free service is consumed **once** at completion, whatever the number of its units;
  every worksheet is validated (4.7). **Per-unit allowance / consumption needs a separate Part 2
  business approval and design.**
* D6: same site = same address record, or same commercial customer with the identical
  normalized address (street, street 2, ZIP, city - case / spaces ignored - state, country);
  otherwise **Confirm Same Site** by a Helpdesk manager (backend check), reason required, this
  case only, never another customer / company; user, date, addresses and reason stored and
  logged; it resets a checked case.
* D7: duplicate selection refused (one active case per free service, one open job); company /
  customer access unchanged.
* D8: requested items checked against the policy of every participating card; a card without
  policy or an item classified differently -> Manual Review naming the items and cards; the
  Partial / Excluded Items flow is unchanged.
* UI: ticket **Pending Services** button (list of the site's pending services with units and
  window, multi-select -> **Create Warranty Case**); Create Warranty Case window **Add All
  Pending** + units column; case Service Cards, Units to Service, linked services with units and
  window, Confirm Same Site; job Warranty Cards, worksheets with service / card / unit / serial.
* Limitation: a usage-based card that is not the case's primary card needs a case of its own
  (Manual Review), because the case holds one usage reading.
* Tests: earlier test classes run with the D3 date checks switched off
  (check_service_windows = False) because they merge services of different due dates; the D3
  rules are tested in test_service_job_multicard.

## Phase 4.11 - Draft Job from Service (approved E1-E10, A1-A7; 2026-10-24)

SRS: 2.5 ("Job creation from service is configurable ... Draft Service Job or wait for user
action"), 9.3 step 9 (mandatory Helpdesk Ticket > Service Job > Field Service chain), 9.4 steps 5-7
(draft jobs when enabled; validation before each service), gap #18, policy table p.47.

* E1: processed by the daily free service monitoring (`_cron_monitor_free_services`, after the
  Part 2 steps) from the start of the D3 window: Alert Date (due date - card Service Due Alert
  Days), else the Due Date. No jobs at card confirmation.
* E2: policy **Draft Job from Service** snapshotted on the card at warranty confirmation
  (`warranty.card.draft_job_from_service`); existing cards unchanged (no migration). The hidden
  company field stays unused.
* Q24 resolution (approved 2026-10-24): policy **Automatic Case Requested Items** (Covered Items
  of the policy only) = Requested Items of the automatic case (union of the participating cards'
  policies, D8 applies). Empty: Manual Review "No Requested Items" (Q24 unchanged).
* E3 / A1: ticket (Draft Job Helpdesk Team, no stage template email - `mail_notrack`) -> Free
  Service case (services, Units to Service D4, items) -> Check Eligibility (unchanged) ->
  approval To-Dos (Part 3) -> **manual** Approve Case (also when Warranty Case Approval Required
  is off: To-Do "Approve automatic warranty case") -> Prepare Service Job run automatically after
  the approval -> **Draft** job (no Field Service task before confirmation). A failed Prepare
  keeps the approval; To-Do with the reason; Prepare Service Job can then be used manually.
* E4: company settings **Draft Job Helpdesk Team** (team of the company) and **Draft Job
  Automation User** (active internal Helpdesk user allowed in the company), checked on save and
  at run time; missing / invalid -> services **Blocked** with the reason + To-Do, retried daily.
* E5 / A2 / A3 / A6: per run and company, one group per commercial customer and site (D6 rules
  1 / 2 only; Confirm Same Site never assumed); the windows of started services all contain
  today (D3). One new ticket + case per group. A later service joins an automatic case only when
  it is New / Eligibility Checked, has no service job, no manual change (services, units, items,
  card, site, ...) and no human decision (approval, rejection, payment waiver, escalation
  confirmation, same-site confirmation, chargeable conversion), same customer / company / site,
  overlapping windows; the case is then reset (D2), logged and checked again. Otherwise a new
  ticket / case. A failing card blocks the whole case (D1), the To-Do lists every failed reason.
* E6: service status **Automatic Draft Job** (Case Created / Draft Job Created / Blocked / Window
  Ended) + reason + automatic case; only empty / Blocked services are processed; the automatic
  Prepare runs once per case (never after a job, also a cancelled one).
* E7 / E8 / A4: due alerts unchanged until the Draft job exists; then the services' system due
  alert activities are closed and one To-Do "Plan draft service job" is created on the job (done
  when the job leaves Draft). Blocked / ineligible: due alert kept + To-Do with the exact reason.
  Expiry reminders unchanged. Recipients: ticket user, else the cards' service alert users, else
  the company's Helpdesk managers; nobody -> chatter + server log. No customer email / WhatsApp.
* E9: usage-based services are not processed: Part 2 has no usage threshold event
  (`usage_threshold` is display only). **Pending SRS requirement** (2.5 / 9.4 step 6).
* E10: the OdooBot cron only searches the candidates; tickets, cases, checks and Prepare Service
  Job run as the Draft Job Automation User with the card company (access rights and record rules
  apply). The automation user created and checked the case, so Part 3 excludes it from approving.
  Automation fields protected by a Python marker (not sendable by clients). Only sudo: the
  delivery address read (existing pattern) and the configuration-problem notifications.
* Concurrency (A5): candidate rows locked `FOR UPDATE SKIP LOCKED` and revalidated (status,
  active case, open job, availability); each group in a savepoint (failure -> Blocked, the other
  groups continue). **Remaining risk:** the manual Part 3 case creation keeps its
  application-level D7 check without a row lock; a manual case committed at the same instant as
  an automatic one could link the same service twice (the automation skips services linked in
  uncommitted transactions through the key share lock of the link row).
* Part 3 change: extension point `_warranty_after_eligibility_check(result, steps)` called after
  each Check Eligibility (no behaviour change).
* Tests: `tests/test_draft_job_from_service.py` (10 tests).

## Flexible Service Dates (BA-approved enhancement F1-F10 / K1-K8, 2026-10-24)

**Status:** BA-approved enhancement of the original SRS. The early-service rules are a BA
interpretation of SRS 2.5 "feasible date window"; the Late Service Exception after the Grace
Period End is **not an original SRS requirement** (SRS p.62: Grace Period End = "last acceptable
date"; SRS scenario 23: expiry after the grace period). SRS validation table "Service due within
grace period - Warn/block based on policy" is implemented as Late Service Handling.

* Policy (copied to the card at warranty confirmation, `_snapshot_free_service_values`):
  **Early Service Rule** (From Alert Date / Days Before Due / Any Date; empty = standard rules),
  **Early Service Days**, **Late Service Handling** (Block / Manager Approval after Grace Period
  End), **Enforce Service Sequence** (default on). Cards confirmed before: empty rule -> standard
  D3 (planning from the Alert Date) and Part 2 (scheduling from today) unchanged; sequence off.
* Permitted service dates (`warranty.service.entitlement._warranty_allowed_range`): earliest =
  Alert Date / due - days / warranty start (never before the warranty start); latest = Grace
  Period End, or the later approved Late Service Exception date. Used by Part 2 Schedule /
  Reschedule (K2), Check Eligibility and Prepare Service Job (common permitted date; also for a
  single service), Plan Job / Confirm / Plan Next Visit, Complete Visit and batch completion
  (F9 / K4: the actual completion date must be permitted; earlier is blocked, later needs an
  approved exception before the consumption). Due Dates are never changed.
* F4: after the due date within the grace period: allowed, "Service date note" on the job at Plan
  Job and at completion.
* F3 / K7 (Enforce Service Sequence): free services of one card are never in one case / job;
  service N needs the previous services of the card Completed / Expired / Cancelled - at Check
  Eligibility and Prepare Service Job unless the previous service is on another open job, at
  Complete Visit (single and batch) always.
* Late Service Exception (`warranty.service.date.exception`, menu Warranty > Late Service
  Exceptions): Request Late Service Exception (Helpdesk users; free service, case or job):
  requested latest date after the current latest permitted date, from today, never after the
  card's Warranty End Date (F6), mandatory reason, one open request per service; To-Dos to the
  approvers due on the Grace Period End (K6, no duplicates). Approvers: company setting **Late
  Service Exception Approvers** (Helpdesk managers of the company), empty = all Helpdesk managers
  of the company; never the requester or the Draft Job Automation User (K5, server-side).
  Approve / Reject (reason) / Cancel; records cannot be edited or deleted (Python marker);
  notes on the request, free service, card and case; multi-company record rule.
* F7 / F8 / K3 / K6: an approved exception keeps the service available (Pending Services,
  eligibility, Prepare, planning, completion) and protects it from the Part 2 expiry until its
  date; a request alone grants nothing and does not stop the expiry - when the service expires
  first, the request is closed "Not Approved before Expiry" and logged; Expired stays final.
* K8: the Part 4.11 automatic draft job keeps the Alert Date trigger (`_warranty_alert_window`).
* Requirement 4: Job Creation Date (create date), Planned Date, **Actual Completion Date** (new,
  job and visit, set at Complete Visit; empty on historical records), Free Service Due Date.
* Limitations: no early-date exception (re-plan instead); an exception date of a multi-unit card
  is limited by the card's Warranty End Date; usage-based services have no date rules; a request
  does not stop the expiry (managers must decide before the Grace Period End).
* Tests: `warranty_management_fsm/tests/test_flexible_service_dates.py` (10 tests); earlier test
  fixtures keep Enforce Service Sequence off (helpdesk TestWarrantyCase policy).

## Late Service Exception request groups (approved G1-G7, H5-A, 2026-10-24)

* Request Late Service Exception selects **several free services** (Many2many): from a service
  job or warranty case all eligible services are preselected (Manager Approval policy, open, no
  open request) and can be deselected; from a free service only that service. One common
  requested latest date and mandatory reason.
* `warranty.service.date.exception.group` (menu Warranty > Service Date Exceptions > Exception Requests): one request,
  one `warranty.service.date.exception` per service (per-service audit, expiry protection, date
  and completion checks unchanged). All-or-nothing: every service checked on its own (policy,
  status, its own latest date / Grace Period End, its card's Warranty End Date, open requests),
  one company and customer; any problem -> nothing created, every failing service named.
* One To-Do per approver on the request (due on the earliest Grace Period End), none on the
  service records. Approve All / Reject (reason) / Cancel on the request: authorized Helpdesk
  managers of the company, never the requester or the Draft Job Automation User; every record
  re-checked at approval (status, service open, date not passed, warranty end, policy) - any
  failure -> nothing decided; decisions in one savepoint. Grouped records cannot be decided one
  by one (a request of one service is decided through its record too).
* H5-A: a member expiring before approval -> it is Not Approved before Expiry, the request
  becomes Partly Expired, cannot be approved; the approvers get one To-Do "Reject or cancel";
  rejecting / cancelling keeps the expired member and closes the others, which can then be
  requested again. Request status derived from its records (Requested / Partly Expired /
  Expired before Approval / Approved / Rejected / Cancelled).
* Records created before the request groups (no request) keep their own Approve / Reject /
  Cancel. Requests and records cannot be created, edited or deleted directly (Python marker);
  multi-company record rules on both.
* Tests: test_flexible_service_dates 211-216.

## Revised F9 - completion outside the permitted dates (approved 2026-10-24)

* The SRS has no date-range block at Complete Visit: the actual completion date no longer
  blocks. Completed earlier or later than the permitted service dates (cards with flexible
  service dates): the completion goes through, the user gets a warning ("Visit completed outside
  the permitted service dates") and the job gets an audit note per service ("completed on ...,
  earlier than its earliest / later than its latest permitted service date ..."). Batch
  completion: the same note, no warning dialog.
* Kept: Actual Completion Date (job and visit); planning rules (Plan Job, Confirm, Plan Next
  Visit) and Part 2 scheduling with the Late Service Exceptions; expiry protection; all other
  completion checks (timer, sign-off, worksheets / required answers, attachments, holds, usage
  reading, Enforce Service Sequence). New safeguard: an Expired or Cancelled linked free service
  blocks the completion; Completed services are skipped (consumed once).
* Interaction: services on an open job are protected from the Part 2 expiry (Merge Status) and
  are In Progress once started, so they cannot expire meanwhile; a Late Service Exception is no
  longer needed to complete, only to plan / schedule after the Grace Period End.
* Tests: test_flexible_service_dates 207 (early + late, single + batch), 217 (cross-card early
  completion), 218 (Expired service blocks).

## SRS service flow alignment + optional Case Type (approved 2026-10-29, D-A..D-F, G1-G6)

Design and implementation notes: `doc/srs_service_flow_alignment_design.md`. Service-origin
jobs (Origin = Service Entitlements) are created from compatible free services before any ticket
(SRS 9.4); Create or Link Helpdesk Ticket links the ticket only; the Free Service case is created manually on that ticket (Warranty Cases > New, 2026-10-29), linked to the job on save and checked with Check Eligibility; Confirm
needs an Eligible case (no general approval, D-A). Draft Job from Service creates Draft
service-origin jobs (D-B, replaces E3's ticket-first route for new runs). Warranty cases may be
created without Case Type: preliminary check -> Warranty Inspection job (or the chargeable
inspection when the team requires it, G1) -> Complete Inspection with the final Case Type (G2)
-> full eligibility / approval. Faults found during free-service visits create a separate
complaint case (G5). AMC entitlements remain an open SRS requirement (D-D).


## SRS Figure 4 – Inspection quotation decision on the case (2026-10-30, approved)

SRS page 28 Figure 4, §2.11, §10.4, §9.7.

* Case fields **Inspection Required** (helpdesk, Boolean) and **Inspection Trigger** (fsm, On Sales
  Order Confirmation / On Payment), set at creation from the ticket's Helpdesk team (Inspection
  Required / Chargeable Job Trigger); Chargeable Inspection cases always, Free Service cases never
  require it. Editable while New / Eligibility Checked. Product / amount stay on the team.
* Existing data: no migration, no backfill – every existing case keeps Inspection Required off and
  the trigger empty (team value used); only new cases get the values.
* "No": unchanged (approval → Prepare Service Job).
* "Yes", Not Eligible / Out of Warranty / Manual Review / undetermined: existing Convert to
  Chargeable (Inspection) – the inspection line now follows the case flag, the trigger the case.
* "Yes", Approved + Eligible: Prepare Service Job creates the draft inspection quotation (purpose
  Inspection, send To-Do; case stays Approved / Eligible); further clicks show an information message (no error) and open the quotation until the trigger
  is met; on SO confirmation / payment the normal warranty service job is prepared automatically
  (all Prepare Service Job checks, savepoint, failure logged on the case); Prepare Service Job is
  the fallback. No duplicate quotation or job.
* Credit adjustment (§2.11) is not automated: standard Credit Note / reconciliation or a manual
  discount line (C8 / Part 8 pending; no automatic credit notes).
* Open SRS ambiguities (BA): fee treatment when an eligible warranty repair proceeds (nothing to
  discount); "customer does not proceed" on an eligible case (§9.7 step 8 is written for chargeable
  cases); a per-"warranty service type" inspection rule (no such setting exists).
