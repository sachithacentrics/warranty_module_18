# Part 4 – Manual Testing Guide

Database **`warranty_test`** only (port 8199):

```
..\python\python.exe odoo-bin -c odoo.conf -d warranty_test --http-port=8199
```

Use the Part 3 data: Approver A (Warranty Case Approval User), admin (Helpdesk + Sales), P3 Policy
(Standard Service covered, Payment Check Required off, Repeated Failure Threshold 0), a confirmed
P3 AC card for ABC Hotel with pending free services, a ticket for Hotel Engineer.

An **Approved case**: admin creates the case (Requested Items = Standard Service, optionally
select free services) → Check Eligibility (Eligible) → Approver A → Approve Case.

## Phase 4.0 – Setup

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-001 | Open the apps menu. | **Field Service** app is available. | | |
| TC-P4-002 | Warranty → **Service Jobs**. | Empty list "No service job yet"; no *New* button. | | |
| TC-P4-003 | Spot check Parts 1–3: confirm a card, create a case, Check Eligibility, Approve. | Works as before. | | |

## Phase 4.1 – Service selection, merge and draft Service Job

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-004 | Approved **Warranty Complaint** case without free services → **Prepare Service Job**. | Draft job **JOB/…** opens: case, ticket, customer, site, product, card filled; *Free Services Type* = No Free Service; chatter "…prepared (Draft)… warranty claim only". Case stays **Approved**, smart button **Service Jobs (1)**. | | |
| TC-P4-005 | Approved **Free Service** case with **1** free service → Prepare Service Job. | Type **Single**; the service shows Merge Status **Selected**, its status unchanged, field *Service Job* = JOB/…. | | |
| TC-P4-006 | Approved case with **2** free services of the card → Prepare Service Job. | Type **Merged**; both services **Merged**; chatter "Free services merged: WSE/…, WSE/…". | | |
| TC-P4-007 | Approved case with 2 services; then make one of them unavailable (e.g. as admin a service of a past due date + grace expired by *Monitor Free Service Due Dates*) → Prepare Service Job. | Error "The free services cannot be merged…" naming the service and "conflicting status"; no job, merge status unchanged. | | |
| TC-P4-008 | On a case with an open job: look for Prepare Service Job. | Button hidden (one open job per case). | | |
| TC-P4-009 | Open the job → **Cancel** (confirm). Back on the case → Prepare Service Job again. | Job **Cancelled**; services Merge Status **Not Merged**, free services balance unchanged; case **Approved**; chatter on case and job "cancelled before confirmation"; a new job can be prepared. | | |
| TC-P4-010 | Case not Approved (e.g. Eligibility Checked); user without Helpdesk rights; user of another company. | No Prepare Service Job button / refused; jobs of another company not visible. | | |

## Phase 4.2 - Service Job planning

Setup: two users with **Field Service / User** rights in your company (e.g. *Tech Main*, *Tech
Support*); a Draft job from TC-P4-004 (Warranty Only, no free service).

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-011 | Open the Draft job -> **Plan Job** without date / technician. | Blocked: "Planned Date, Main Technician required". Status Draft. | | |
| TC-P4-012 | Planned Date = yesterday (D4 revised) on a Draft / Planned job; also in Plan Next Visit. | Accepted (no past-date error); change tracked in the chatter. Outside a free service window: accepted with a non-blocking Service date note (D3 revised). | | |
| TC-P4-012b | JOB/000006 case: free service due in 3 months, Plan Job today. | Accepted; Service date note "outside the service window ... not blocking"; due date unchanged. | | |
| TC-P4-013 | Main Technician list. | Only active Field Service users of the company; a normal user is not offered. | | |
| TC-P4-014 | Main = Tech Main, Support = Tech Main. | Refused: main cannot also be support. | | |
| TC-P4-015 | Planned Date tomorrow, Main = Tech Main, Support = Tech Support -> **Plan Job**. | Status **Planned**; chatter "Service job planned for ... ready for confirmation"; case still Approved; no Field Service task created. | | |
| TC-P4-016 | Change the Planned Date on the Planned job; then Cancel it. | Change allowed; Cancel -> Cancelled, case Approved. | | |
| TC-P4-017 | Job with 1 free service (TC-P4-005) -> plan -> Prepare. | Planned; the free service status and Merge Status (Selected) unchanged. | | |

## Phase 4.3 - Confirm Service Job

Use a **Planned** job (TC-P4-015). Optional: Settings -> Warranty -> General -> **Warranty Field
Service Project**.

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-018 | Planned Warranty Only job -> **Confirm Service Job**. | Job **Confirmed**; smart button **Visits (1)**; the task: project = the company's standard Field Service project, customer = case site / customer, planned start = Planned Date, assignees = main + support technicians, Ticket, Service Job, Warranty Case, Visit No. 1. Case status **Job Created**; chatter on job and case. Technicians get the standard internal assignment notification; no customer email. | | |
| TC-P4-019 | Job with 1 free service -> Confirm. | Free service status **Job Created**, Merge Status unchanged; free services balance unchanged; deleting the service is refused. | | |
| TC-P4-020 | Planned job; then on the case policy tick Payment Check Required + Hold (unpaid invoice) -> Confirm. | Warning "Service job not confirmed"; job stays Planned, no task; case stays Approved / Eligible; chatter on job and case "blocked by the eligibility revalidation". Undo the policy change afterwards. | | |
| TC-P4-021 | Move the case's Helpdesk ticket to a closed (folded) stage -> Confirm. | Refused: "Helpdesk ticket ... is closed: reopen it first". | | |
| TC-P4-022 | On the warranty ticket click **Plan Intervention** (Field Service). Create a Field Service task manually with that ticket. | Both refused (use the Service Job). On a ticket without warranty case, Plan Intervention works as standard. | | |

## Phase 4.4 - Worksheet instances

Setup: Field Service -> Configuration -> Worksheet Templates: e.g. **AC Checklist**; Product
**P3 AC** -> Warranty tab -> **Worksheet Template** = AC Checklist.

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-023 | Confirm a Warranty Only job. Open the job tab **Worksheets** and the task. | 1 instance (case product, AC Checklist, To Do); the task's standard **Worksheet** button opens the AC Checklist; **Open Worksheet** on the instance opens the same record. | | |
| TC-P4-024 | Job with 2 free services -> Confirm -> task. | 2 instances under one task; standard Worksheet buttons hidden, **Worksheets (2)** button; each instance opens its own checklist. | | |
| TC-P4-025 | Remove the product template (and project default) -> confirm a job. | Confirmed; instance without template; Open Worksheet not shown; usage / notes / attachments can be filled. | | |
| TC-P4-026 | Usage-based card -> confirm. | Instance: Usage Reading Required, unit of the card; technician enters Current Usage and attachments. | | |
| TC-P4-027 | Customer with an email; the Field Service project's first stage has an email template -> confirm a job. | No customer email / "Intervention Scheduled" message on the warranty task; a normal Field Service task still gets it. | | |

## Phase 4.5 - Visit start and usage readings

Setup: the technician needs an **Employee** in the task company (Employees -> New -> Related User,
Company) and an email address; a usage-based card for TC-P4-032 / 033.

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-028 | Confirmed Warranty Only job -> open the Field Service task as the technician -> **Start** (timer). | Job **In Progress**; Worksheets **In Progress**; case stays **Job Created**; chatter note "Visit ... started by ..." on job and case. | | |
| TC-P4-029 | Pause / resume / start again. | No further status change or note. | | |
| TC-P4-030 | Free Service job (2 services) -> Start. | Both free services **In Progress** with a note. | | |
| TC-P4-031 | Technician without an employee in the company -> Start on a warranty task. | Message "You need an active employee in <company> ..."; nothing started. A normal Field Service task starts as standard. | | |
| TC-P4-032 | Usage-based: worksheet -> Current Usage -5; unit KM; a value below the case reading; then a valid value. | Refused: "greater than zero", "usage unit ... must be ...", "lower than the latest reading ..."; valid value saved. | | |
| TC-P4-033 | Enter a value above the card's usage limit. | Saved; warning note "exceeds the usage limit" on job and case; nothing else changes. | | |

| # | Steps (completion lock) | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-034 | Warranty task (started) -> **Mark as done**; kanban: drag / set status **Done**; status widget **Cancelled** - as technician and as Helpdesk user. | Each refused: "... cannot be marked Done or Cancelled directly."; task, job and worksheets unchanged. | | |
| TC-P4-035 | Normal Field Service task -> Mark as done / Cancel. | Standard (closed). | | |
| TC-P4-036 | Warranty task -> **Send Report** (if shown). | Standard manual send kept. | | |

## Phase 4.6 - Parts / workshop blockers

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-037 | Started job (In Progress) -> **Awaiting Parts** -> reason "Compressor not in stock" -> Confirm (as technician). | Job **Awaiting Parts**; note with reason on job and case; case stays **Job Created**; task, timer, worksheets unchanged. | | |
| TC-P4-038 | **Resume Job** -> reason "Parts received". | Job **In Progress**; notes on job and case. | | |
| TC-P4-039 | Free Service job -> **Workshop Repair** (Helpdesk user). | Job **Workshop**; free services stay **In Progress**; balance unchanged. | | |
| TC-P4-040 | Try Confirm without a reason; check buttons on Draft / Confirmed / Awaiting Parts jobs. | Reason required; Awaiting Parts / Workshop only on In Progress; Resume only on hold. | | |

## Phase 4.7 - Service Job completion

Setup: Settings -> Warranty: Customer Sign-off Required (on), Worksheet Checklist Required (on),
Worksheet Attachment Required (off). A started job (TC-P4-028).

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-041 | Warranty task (timer running) -> **Complete Visit**. | Refused, listing every problem: stop the timer, customer sign-off, checklist not filled in. Nothing changes. **Mark as done** is not shown on warranty tasks. | | |
| TC-P4-042 | Stop the timer (save the time), open the worksheet, fill it in, save; **Sign Report** -> customer signs; **Complete Visit** (Warranty Only job). | Task **Done**, Visit Outcome **Completed**; worksheets, job and case **Completed**; ticket unchanged; notes on job, case and card. | | |
| TC-P4-043 | Free Service job (2 services), Helpdesk user -> Complete Visit (after TC-042 steps). | Both services **Completed** (Merge Status Completed); card Free Services Used +2, Balance -2; note on each service and on the card. | | |
| TC-P4-044 | Job **Awaiting Parts** -> Complete Visit. | Refused: "... resume it first." | | |
| TC-P4-045 | Usage-based card: Complete Visit without a reading; then a valid reading. | Refused "current usage reading and its unit are required"; then completed; reading in the notes; card / unit reading not changed. | | |
| TC-P4-046 | Settings: Attachment Required on -> Complete Visit without attachment; Sign-off Required off -> no signature. | Refused "at least one attachment"; after adding one, completes without signature (note "not required"). | | |
| TC-P4-047 | Studio: make a checklist answer Required; leave it empty (worksheet saved by API / not opened) -> Complete Visit. | Refused "required checklist answers missing: <field>". | | |
| TC-P4-048 | Completed job: click Complete Visit again (other browser tab) / normal Field Service task. | Refused "already closed", nothing consumed again / standard Mark as done unchanged. | | |

## Warranty Worksheet templates (per-instance checklists)

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-049 | Warranty > Configuration > Warranty Worksheet Templates -> New "AC Service (per service)" -> Studio: add questions, one Required. Set it on the product. | Template created; Studio works. | | |
| TC-P4-050 | Case with 2 free services of that product -> job -> Confirm -> task -> Worksheets: fill each one differently. | One task, two worksheets, each with its own answers; standard Worksheet button hidden. | | |
| TC-P4-051 | Complete Visit with one required answer missing. | Refused, naming only that worksheet. | | |
| TC-P4-052 | Sign Report (customer preview). | Both checklists are on the report. | | |
| TC-P4-053 | Product with a Field Service (task) template, 2 merged services -> Confirm Service Job. | Blocked: "... would be used by several worksheet instances ... Set a Warranty Worksheet template". One service: works as before. | | |
| TC-P4-053a | Free services saved with a Field Service template (e.g. Default Worksheet), product now has a Warranty Worksheet template, 2 merged services -> Confirm Service Job. | Confirmed; one worksheet per service with the product's Warranty Worksheet template; the free services' saved template is unchanged. One service: keeps its Field Service template. | | |

## Phase 4.8 - Visit not completed / reschedule / cancel

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-054 | Started visit (timer stopped) -> **Visit Not Completed** as technician: Customer Unavailable, Reschedule, notes. | Task Cancelled (not Done), Visit Outcome **Rescheduled**, reason + notes; job **Incomplete**; services still In Progress, Used unchanged; ticket open; To-Do "Plan the next visit" for the Helpdesk user; notes on job / case / card / services. The technician sees no date fields. | | |
| TC-P4-055 | Helpdesk user: job -> **Plan Next Visit** (date, technicians). | New task "... - Visit 2", High priority (star), new worksheets (To Do); job **Rescheduled**, Reschedule Count 1; the previous visit keeps its date / technicians / outcome; To-Do "Inform the customer ...". | | |
| TC-P4-056 | Start visit 2 -> complete it (4.7). | Job In Progress -> Completed; services consumed once; the free service Reschedule Count includes the visit. | | |
| TC-P4-057 | Visit Not Completed: Awaiting Parts + Follow-up. | Outcome **Part Pending**; job Incomplete; nothing consumed; Complete Visit refused on that task. | | |
| TC-P4-058 | Job Awaiting Parts -> Visit Not Completed (Reschedule). | Job Incomplete; the hold note stays in the chatter. | | |
| TC-P4-059 | Visit Not Completed -> **Cancel** (or job **Cancel Job** as Helpdesk user with a reason). | Job **Cancelled** with the reason; open visits Cancelled; services back to their previous status, Not Merged, not consumed; case **Approved**. | | |
| TC-P4-060 | Closed visit: change its planned date / assignees / status, edit its timesheet, edit its worksheet reading. | Each refused: "kept as visit history". | | |

## Product Worksheet Template (SRS 2.7 fix)

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-061 | Product with a Warranty Policy (product or category) -> Warranty tab -> Worksheet Template: select a Warranty Worksheet template -> Save; new SO / card -> Free Services; new job. | Field editable and saved; policy values (basis, period, free service count / frequency) still read-only; new free services show the template; the job creates one worksheet instance per service with it. | | |

## Phase 4.9 - Batch Job Completion

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-062 | Job form: Completion Mode. | New jobs: Batch Eligible; can be set to Single while open; read-only when completed. | | |
| TC-P4-063 | Service Jobs list: select 1 ready job + 1 with timer running + 1 not signed + 1 Single + 1 Awaiting Parts -> Complete Selected Jobs. | Preview: 1 Ready, 4 Not Ready with reasons; nothing changed yet. | | |
| TC-P4-064 | Complete Ready Jobs. | Ready job Completed (visit Done, case Completed, services consumed, ticket open, note "batch completion"); others Skipped, unchanged. | | |
| TC-P4-065 | Select Draft / Confirmed / Incomplete / Rescheduled / Cancelled / Completed jobs -> Check. | All Not Ready with their reason; Complete Ready Jobs not offered. | | |
| TC-P4-066 | Rescheduled job, visit 2 started, stopped, signed -> batch. | Only visit 2 completed; visit 1 stays Cancelled / Rescheduled. | | |
| TC-P4-067 | Run the batch again on the same jobs. | Skipped "Already closed"; Used / Balance unchanged. | | |
| TC-P4-068 | Log in as technician: Service Jobs list. | No Complete Selected Jobs button. | | |

## Phase 4.10 - Chargeable jobs / Job Trigger

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-069 | Helpdesk team: Warranty Inspection on (product, amount); Chargeable Job Trigger = On Sales Order Confirmation. | Settings saved. | | |
| TC-P4-070 | Chargeable Inspection case -> Convert to Chargeable. | Draft quotation, Chargeable Purpose Inspection; case To-Do "Send quotation ..."; no job; Prepare Service Job refused (trigger not met). | | |
| TC-P4-071 | Send the quotation; confirm it. | To-Do closed when sent; at confirmation a Draft job "Chargeable Inspection" (no free services); Prepare again: refused (open job). | | |
| TC-P4-072 | Trigger On Payment: confirm; invoice a 50 % down payment and pay it; then invoice the rest and pay. | No job after confirmation or the down payment; one job after full payment. | | |
| TC-P4-073 | Plan / confirm / start the inspection job; Complete Visit. | Inspection Result window: diagnosis, repair required, repair details (when Yes). | | |
| TC-P4-074 | Repair required = Yes. | Job Completed with diagnosis; case Chargeable, type Repair; draft repair quotation with the diagnosis note (no price); To-Do to send it. | | |
| TC-P4-075 | Price the repair quotation, confirm. | Draft "Chargeable Repair" job; complete it -> case Completed (Repair Completed); both jobs on the case. | | |
| TC-P4-076 | Instead: case -> Customer Declined Repair (reason). | Case Completed (Repair Declined); repair quotation cancelled; inspection job kept. | | |
| TC-P4-077 | Repair required = No. | Case Completed (Inspection Only), not Closed. | | |
| TC-P4-078 | Partial case with confirmed gas quotation -> approve -> job. | Warranty job, tab "Approved Excluded Items" shows the gas item. | | |

## Phase 4.11 - Draft Job from Service

Setup (beginner steps):
1. Warranty > Configuration > Settings: **Draft Job Helpdesk Team** = your warranty team,
   **Draft Job Automation User** = a Helpdesk user used only for the automation (not an
   approver). Save. Keep **Warranty Case Approval Users** set (other users).
2. Warranty Policy (e.g. FS Standard Warranty - 12 Months): tick **Draft Job from Service**, set
   **Automatic Case Requested Items** (e.g. Standard Service, must be a Covered Item), **Service
   Due Alert Days** 7, **Grace Period Days** 30 and the Service Alert Responsible Users. Save.
3. New sales orders / cards confirmed after step 2 (older cards keep Draft Job from Service off),
   with an Installation Date so that service 1 is due within the next 7 days.
4. Run the automation: activate the developer mode, Settings > Technical > Scheduled Actions >
   "Warranty: Monitor Free Service Due Dates" > Run Manually.

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-P4-079 | Card of a policy without Draft Job from Service; run. | Nothing created; the card shows Draft Job from Service off. | | |
| TC-P4-080 | Clear Draft Job Helpdesk Team; run. | Free service: Automatic Draft Job = Blocked with "not configured"; To-Do to the service alert users; run again: no second To-Do. Set the team; run: case created, To-Do done. | | |
| TC-P4-081 | **8 AC**: 8 sales orders of the same customer, delivery address Main Building (some with the same street written differently), service 1 due in 3-5 days; run. | ONE ticket (team above), ONE case "Created by Draft Job from Service": 8 Linked Free Services, 8 Service Cards, 8 Units to Service, Requested Items from the policy, created by the automation user; Eligibility Checked / Eligible; approval To-Dos to the approvers; no service job. | | |
| TC-P4-082 | Run again (twice). | No new ticket, case or job. | | |
| TC-P4-083 | Approver: Approve Case. | ONE Draft service job with the 8 services / 8 cards; no Field Service visit; services Draft Job Created; due alert To-Dos done; To-Do "Plan draft service job" for the planners. | | |
| TC-P4-084 | Planner: Planned Date (inside the windows), Main Technician -> Plan Job -> Confirm; complete the visit. | Plan To-Do done; one visit with 8 worksheets; each card Used +1 (consumed once on its own card). | | |
| TC-P4-085 | One of the 8 cards has another policy on which the item is not covered; run. | Whole case Manual Review; the To-Do names the card and the reason. Remove that service -> Check Eligibility -> Approve -> draft job. | | |
| TC-P4-086 | Card 9 (same site) due one week later while the case still waits for approval; run on its Alert Date. | Card 9's service added to the same case; chatter "Eligibility reset"; checked again; still one ticket. | | |
| TC-P4-087 | As 086, but the case is approved / has a job / was edited manually / card 9 has another address. | Card 9 gets its own new ticket and case; the approved case and its job unchanged. | | |
| TC-P4-088 | Cancel the automatic draft job; run. | Not recreated. | | |
| TC-P4-089 | Warranty Case Approval Required off. | Case stays Eligibility Checked; To-Do "Approve automatic warranty case"; job only after a Helpdesk user's Approve Case. | | |
| TC-P4-090 | Second company without these settings, with its own due card; run. | Its service Blocked (company named), To-Do to its Helpdesk managers; the first company processed. | | |
| TC-P4-091 | Archive the automation user, then approve an automatic case. | Case Approved, no job; To-Do "Prepare the service job" with the reason; reactivate the user, Prepare Service Job -> job. | | |
| TC-P4-092 | Usage-based card with the setting. | Nothing created (pending SRS requirement). | | |
| TC-P4-093 | Customer emails. | No email / WhatsApp to the customer from the automatic ticket or case. | | |

## Cross-Warranty-Card Service Merge (8 AC units)

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-MC-01 | Ticket (customer + site) -> Pending Services -> select service 1 of the 8 cards -> Create Warranty Case. | One case: 8 linked services, Service Cards = 8 cards, Units to Service = 8 units. | | |
| TC-MC-02 | Requested Items -> Check Eligibility -> Approve (approver). | Eligible; one approval. | | |
| TC-MC-03 | Prepare Service Job -> Plan Job (date inside the windows) -> Confirm. | One job (Warranty Cards = 8), one task, 8 worksheets (service / card / unit each). | | |
| TC-MC-04 | Start / Stop -> Complete Visit. | 8 services Completed; each card Used +1, Balance -1; notes on all 8 cards. | | |
| TC-MC-05 | One card suspended -> Check. | Not Eligible: "card (service): warranty card is Suspended"; remove that service -> New -> check / approve again. | | |
| TC-MC-06 | Card with another address (same street spelled differently / other street). | Same street: accepted; other street: Manual Review; Helpdesk manager Confirm Same Site (only the non-matching address is offered, reason) -> accepted. On a case whose addresses all match: message "already match the case site" (no empty wizard). | | |
| TC-MC-07 | Services due far apart / planned date outside a window. | Cards due far apart (same customer / site): merged into one case / job / visit (D3 revised, no overlap needed); planned date outside a window: accepted with a "Service date note ... outside the service window of WSE/.. (not blocking)" (D3 revised). | | |
| TC-MC-08 | Multi-unit card: remove one unit from Units to Service. | Worksheets only for the selected units; the card's service consumed once. | | |

## Flexible Service Dates (early / late service, Late Service Exception)

Setup (beginner steps):
1. Warranty > Configuration > Policies > your policy > **Service Date Rules**: Early Service Rule
   (e.g. Days Before Due, Early Service Days 60), Late Service Handling (Manager Approval after
   Grace Period End), Enforce Service Sequence (ticked). Also Service Due Alert Days 7 and Grace
   Period Days 30. Save.
2. Settings > Warranty > **Late Service Exception Approvers**: two Helpdesk managers (e.g.
   Manager A, Manager B).
3. New sales orders / cards confirmed after step 1 (older cards keep the standard rules); open
   the card: Service Due Monitoring shows the copied rules; a free service shows Earliest /
   Latest Service Date.

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-DF-01 | Older card (confirmed before step 1). | Card shows no Early Service Rule; Schedule and job planning work as before. | | |
| TC-DF-02 | Free service due in 40 days (Days Before Due 60) -> Schedule tomorrow -> ticket / case -> approve -> Prepare -> Plan Job tomorrow -> Confirm -> complete. | All allowed; Due Date unchanged; Used +1; job and visit show Actual Completion Date. | | |
| TC-DF-03 | Free service due in 100 days: Schedule tomorrow; Plan Job tomorrow. | Schedule refused: "within its permitted service dates ..." (Part 2, unchanged); Plan Job accepted with a non-blocking "outside the service window" note (D3 revised). | | |
| TC-DF-04 | Card with services 1 and 2: case with both; case with service 2 only. | Manual Review: "cannot be serviced together" / "previous free service ... must be Completed". | | |
| TC-DF-05 | Service 1 on an open job, service 2 on a second job; complete service 2 first (and batch). | Refused: previous free service; after service 1 is completed, service 2 completes. | | |
| TC-DF-06 | Service past its due date (within grace) -> Plan Job. | Allowed; job chatter "Service date note ... after its due date". | | |
| TC-DF-07 | Policy Block: plan after the Grace Period End. | Refused, no exception offered; Request Late Service Exception refused. | | |
| TC-DF-08 | Policy Manager Approval: plan after the Grace Period End. | Refused with "Request Late Service Exception". | | |
| TC-DF-09 | Helpdesk user: Request Late Service Exception (free service / case / job): date after the grace end, reason. | Request "Requested"; To-Dos to Manager A and B (due on the Grace Period End); second request refused; date after the warranty end refused; empty reason refused. | | |
| TC-DF-10 | Manager A requests one for another service. | To-Do only to Manager B; Manager A cannot approve (separation of duties). Draft Job Automation User cannot approve. | | |
| TC-DF-11 | Manager B: Approve. | Approved; Latest Service Date = requested date; planning / scheduling / completion up to it allowed; notes on service, card, case. | | |
| TC-DF-12 | Reject (reason required). | Rejected; dates unchanged. | | |
| TC-DF-13 | Try to edit / delete an exception. | Not possible (kept for audit). | | |
| TC-DF-14 | Requested (not approved) exception; run Monitor Free Service Due Dates after the Grace Period End (or wait). | Service Expired; request "Not Approved before Expiry", To-Dos done, note on the service. | | |
| TC-DF-15 | Approved exception; after the grace end. | Service Missed (not Expired), still in Pending Services and usable until the approved date; Expired after it. | | |
| TC-DF-16 | Visit completed (Complete Visit) before the earliest date / after the latest date (e.g. JOB/000009 today). | Completed (revised F9): warning "Visit completed outside the permitted service dates", job note "completed on ..., earlier / later than ...", Actual Completion Date set, each service consumed once. Same note in batch completion. | | |
| TC-DF-17 | 2 cards, due dates 40 days apart (Days Before Due 60) -> one case / job. | Eligible; one job, both services consumed on their own cards. | | |
| TC-DF-18 | Cards with no common date. | Manual Review naming each service and window; an approved exception gives the common date. | | |
| TC-DF-19 | Draft Job from Service card with Any Date. | Automatic case only from the Alert Date (unchanged). | | |
| TC-DF-20 | User of another company. | Exceptions of this company not visible. | | |
| TC-DF-21 | Job with free services of 2 cards (policy Manager Approval) -> **Request Late Service Exception**. | Both services preselected; remove one -> request for the other only (Warranty > Service Date Exceptions > Exception Requests). Cancel it. | | |
| TC-DF-22 | Request again with both services, one date, reason. | One request, 2 service records; one To-Do per approver (not one per service); opening the wizard again: "already requested". | | |
| TC-DF-23 | One card with Block policy / a date after one card's warranty end / one service already requested. | Refused, the failing service named; nothing created. | | |
| TC-DF-24 | Approver: request -> **Approve All**. Requester / automation user / other-company manager. | Approved: both records Approved, notes on both services and cards; both permit planning / completion up to the date. Others refused. | | |
| TC-DF-25 | Before approving, shorten one card's warranty end (or complete one service) -> Approve All. | Refused naming that service; nothing approved. | | |
| TC-DF-26 | **Reject** (reason required). | Both Rejected; dates unchanged. | | |
| TC-DF-27 | One service of a pending request expires (Monitor Free Service Due Dates after its Grace Period End). | That service: Not Approved before Expiry; request Partly Expired (warning), Approve All hidden; To-Do "Reject or cancel"; Reject -> expired service unchanged, the other rejected; a new request for the remaining service works. | | |
| TC-DF-28 | Request from a free service form. | Request of one service; Approve on the service record or the request. | | |
| TC-DF-29 | Merged job of 2 cards completed early. | Completed; the warning names both services; each card Used +1. | | |
| TC-DF-30 | A linked free service Expired or Cancelled (e.g. after a data correction) -> Complete Visit. | Refused "is Expired and cannot be completed"; nothing consumed. | | |

### Automated tests

`tests/test_service_job_setup.py` (4 tests, 4.0) and `tests/test_service_job_merge.py`
(9 tests, 4.1: no service, single, merged, validation error, compatibility details, rules / one
open job, cancel, expiry protection, multi-company).
`tests/test_service_job_planning.py` (6 tests, 4.2: plan Warranty Only job, blocks, technician
rules, past date allowed / service window, edit until confirmation / permissions, job with free services).
`tests/test_service_job_confirm.py` (7 tests, 4.3: Warranty Only confirm, free services Job Created, site
address, blocks, revalidation failure, project setting, no standalone warranty task).
`tests/test_service_job_worksheets.py` (5 tests, 4.4: single instance + standard button, several
instances, no template / no duplicates, usage + access, no customer stage email).
`tests/test_service_job_visit.py` (5 tests, 4.5: timer start, free services, employee check,
reading rules, usage limit warning).
`tests/test_service_job_completion_lock.py` (5 tests: Field Service user, Helpdesk user, import /
context / sudo, reserved close path + closed tasks, other tasks).
`tests/test_service_job_hold.py` (5 tests, 4.6: hold / resume, workshop + free services, invalid
transitions and reason, access, completion block).
`tests/test_service_job_completion.py` (8 tests, 4.7: Warranty Only completion, free services
consumed once + retry, all problems listed + hold, checklist answers / settings, usage reading +
sign-off setting, no bypass, atomic, access + buttons).
`tests/test_service_job_worksheet_host.py` (6 tests: independent answers with one template,
duplicate task template blocked, required answers per instance, report, access / company,
single task template). `tests/test_service_job_reschedule.py` (9 tests, 4.8: technician
reschedule request, plan next visit + completion, follow-up outcomes, hold history, cancel from
the visit, Cancel Job, history locks / no bypass, atomic, access / buttons).
`tests/test_product_worksheet_template.py` (4 tests: editable with policy / others read-only, new free services inherit and existing unchanged, Warranty Only and free-service job instances).
`tests/test_service_job_batch.py` (7 tests, 4.9: mixed selection, job states skipped, multiple
visits, retry / no double consumption, completion mode, access / companies, technical-error
rollback).
`tests/test_service_job_chargeable.py` (8 tests, 4.10: confirmation trigger + To-Do + no
duplicate, payment trigger (down payment / full payment), inspection -> repair -> repair job,
inspection only, customer declines repair, no bypass + trigger revalidation, cancel back to
Chargeable, Partial approved items).
`tests/test_service_job_multicard.py` (8 tests: 8-AC acceptance, ineligible card + remove +
reapproval, equivalent / different sites + manager override, date windows, duplicates /
security, multi-unit worksheets + per-worksheet validation, cancel + reschedule, usage-based /
single card).
`tests/test_draft_job_from_service.py` (10 tests, 4.11: setting off / snapshot / usage-based,
missing configuration blocked + retried, 8-AC one ticket / case / job after approval + reruns +
consumption, failed card blocks the case, later services join rules, cancelled job not recreated,
approval off still manual, locked / concurrently linked services, companies separated, protected
fields + failed Prepare + window ended).
`tests/test_flexible_service_dates.py` (10 tests: snapshot / legacy cards, Days Before Due,
sequence and same card, grace note / block, exception request / approval / separation of duties /
audit, expiry protection, completion date (single / batch), cross-card different due dates, 4.11
trigger unchanged, reschedule rules).
`test_flexible_service_dates.py` 211-216 (request groups: cross-card job preselection /
deselection, one To-Do per approver, group approval security, every service validated with
nothing partial, approval revalidation, Partly Expired (H5-A), protected records, single service
and records without request).
`test_flexible_service_dates.py` 207 / 217 / 218 (revised F9: early / late completion with warning, single / batch, cross-card, closed services blocked).

## Warranty Start Date Automation – Installation basis (start_date_design.md §7.3)

Setup (beginner steps):
1. Sales > Products > create the service **AC Installation**: Product Type Service, Create on
   Order *Task*, Project = the company's standard Field Service project, tick **Warranty Installation
   Service**, **Installs Products** = the split AC product(s). Save.
2. The AC product (or its policy) uses Start Criterion *Installation/Commissioning*.
3. Settings > Warranty: Customer Sign-off Required as needed (default on); Warranty Timezone set.

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-IN-01 | SO: 1 AC + 1 AC Installation + 1 water heater (installation basis, not in Installs Products). Confirm, Warranty Grouping *Per Product*. | One Field Service task with tab *Warranty Installation* (Purpose Installation) linked only to the AC card; the water heater card has no installation task ("no installation Field Service task is linked"). | | |
| TC-IN-02 | Validate the delivery; open the AC card. | Status **Pending Installation**; missing "waiting for installation task(s) …". | | |
| TC-IN-03 | Sign-off on: Mark as Done without signature, then Sign Report and Mark as Done. | First refused ("needs the customer sign-off"); then the card is **Confirmed automatically**: Installation Date = completion date (Warranty Timezone), start / end calculated, Source Installation Task, chatter *Warranty activated … Installation task … completed on …*. | | |
| TC-IN-04 | Reopen the task and mark it done again. | Card dates unchanged; history *Installation Task Reopened* and a note that the original completion is kept; no second activation. | | |
| TC-IN-05 | New SO with an AC and two installation services (indoor / outdoor). Deliver, complete one task. | Card waits (Pending Installation) until both are done; start = the later completion. | | |
| TC-IN-06 | Installation task completed **before** the delivery is validated. | Card Draft (delivery missing), Installation Date filled; validating the delivery confirms the card automatically with the original installation date. | | |
| TC-IN-07 | Card without an installation service on the SO: **Create Installation Task** on the card. | Task created in the company's standard Field Service project, linked to this card only; completing it confirms the card. | | |
| TC-IN-08 | Cancel the only installation task. Then (Date Correction user) **Record Start Date Exception** with a reason. | Card back to Pending Installation; after the exception Ready, confirm manually; Start Date Source = Authorized Exception. | | |
| TC-IN-09 | Repair / ordinary Field Service task and a Part 4 service-job visit completed. | Never change any warranty card's start date. Part 4 visit completion behaves exactly as before. | | |
| TC-IN-10 | As a technician (no Date Correction group) edit the cards of an installation task; try to type an Installation Date on a card. | Refused / read-only. As the Date Correction user the task's cards can be changed while the task is open (history *Source Change*). | | |

## SRS service flow + optional Case Type (2026-10-29)

Setup: Settings > Warranty: Draft Job Helpdesk Team set; policy Automatic Case Requested Items set (else Manual Review "No Requested Items"); optional Inspection Worksheet Template.

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-SRS-01 | Service Entitlements: select free services of 2 cards (same customer / site) > Action > Create Service Job (planned date, technicians). | One Draft job, Origin Service Entitlements, no ticket / case; services Merged. | | |
| TC-SRS-02 | Try Create Service Job again with the same services; with services of another customer / site. | Refused with the reason. | | |
| TC-SRS-03 | Job > Plan Job > (Confirm hidden) > Create or Link Helpdesk Ticket: link an open warranty ticket, or create one; then Warranty > Warranty Cases > New: that ticket, Case Type Free Service, all the job's free services, Requested Items; Save; Check Eligibility. | After the ticket: no warranty case, Confirm refused ("no warranty case yet"). A case on another ticket, or with only part of the job's services, is refused. After Save: case linked to the job (chatter on both), cards / units filled; after Check Eligibility: Eligible, no approval To-Do; Confirm Service Job available. | | |
| TC-SRS-04 | Confirm > timer > Complete Visit. | One visit, one worksheet per service; services Completed once; case Completed. | | |
| TC-SRS-05 | Draft Job from Service card at its alert date (daily monitoring). | Draft service-origin job (no ticket), planning To-Do. | | |
| TC-SRS-06 | During a free-service visit: Report Fault (unit, description); report it again. | Separate Warranty Complaint case on the same ticket; duplicate refused. | | |
| TC-SRS-07 | Usage-based card: complete a visit with a reading above the Usage Alert %. | "Usage alert" To-Do on the next free service, once. | | |
| TC-SRS-09 | Card A Service 1 (due in 10 days) + Card B Service 1 (due in 100 days), same customer / site: Create Service Job, link ticket, confirm, complete. | One Draft job before the ticket, ONE visit with 2 worksheets; each service consumed on its own card; due dates unchanged. Same card Service 1 + 2 with Enforce Service Sequence ON: refused. | | |
| TC-SV-01 | Service Jobs list: select JOB A (card A) + JOB B (card B), same customer / site -> Action > Create Merged Field Service Visit -> date, technicians. | ONE visit with tab "Service Jobs on this Visit" (2 lines); both jobs Confirmed, no new job; each job's worksheets on the visit; Field Service smart button on each job. | | |
| TC-SV-02 | Start the timer, Complete job A on its line. | Job A Completed, only its free service consumed; job B unchanged; visit stays open. | | |
| TC-SV-03 | Not Completed for job B (reschedule). | Job B Incomplete, its service not consumed; visit closes; Plan Next Visit gives job B its own visit 2. | | |
| TC-SV-04 | Jobs of different customers / sites, one job only, a confirmed job, a Kandy site job. | Refused with the reason; nothing created. | | |
| TC-SV-05 | Material Request from job A while on the shared visit; Create Material Request on the visit. | MRF on job A (+ visit); the visit button refuses ("use the Service Job"); job A cannot complete until the MRF is resolved, job B can. | | |
| TC-SV-06 | Timesheets of the shared visit. | Kept on the visit, not split per job (v1 limitation). | | |
| TC-SRS-10 | Service-origin job: Create or Link Helpdesk Ticket (new ticket, then on another job an existing one). | "Helpdesk Ticket 1" smart button appears; it opens exactly the linked ticket in form view; hidden before linking. | | |
| TC-SRS-08 | Warranty Card WC/00006 (JOB/000006) and a card with a case job + a cross-card job: smart button **Service Jobs**. | Count includes case, service-origin, cross-card, completed and cancelled jobs; 1 job opens its form, several the filtered list (no New button); hidden when 0; a user of another company sees no jobs. | | |
| TC-INS-01 | Ticket > Create Warranty Case without Case Type > Check Eligibility. | Result Preliminary Passed; no approval; Prepare Inspection Job shown. | | |
| TC-INS-02 | Prepare Inspection Job > Plan > Confirm > timer > Complete Visit. | Inspection Result wizard: findings + final Case Type required; case back to New with the type, Inspection tab filled; nothing consumed, no parts possible. | | |
| TC-INS-03 | Check Eligibility > Approve > Prepare Service Job. | Normal job for the decided type. | | |
| TC-INS-04 | Team with Inspection Required: undetermined case after the preliminary check. | Prepare Inspection Job refused; Convert to Chargeable offers Inspection only. | | |
