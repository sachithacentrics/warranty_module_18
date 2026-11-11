# Warranty UX cleanup (AMC-style next action) - 2026-11-08

Views first; no business workflow, approval, stock, accounting or AMC logic changed. Developed and
tested on the disposable `wt_ux` (copy of UAT backup 2026-11-08 22:58). Pending with the SRS 9.10
Warranty Card Output update (one coordinated upgrade).

## AMC patterns applied

One `btn-primary` per step (same method twice, primary / secondary, when the role changes with a
sub-state); explicit state `invisible` on every button; smart buttons hidden at 0; pages and
blocks hidden when empty; technical fields for `base.group_no_one`.

## Changes

| Screen | Problem | Change | Module / file |
|---|---|---|---|
| Warranty Case | Returns / repairs only from the job or ticket; Workshop / Vendor Repair cases (no job) had no entry point | Header: Workshop Intake, Repair Order, Issue Backup Unit (primary when Workshop / Vendor Repair and it is the next step; not for AMC / free service cases). Smart buttons: Ticket, Field Service, Returns. Actions reuse the job's Return wizard / Repair form logic (moved to case helpers, the job calls the same helpers after its own checks) and the Repair Order's Issue Backup | repair `models/warranty_case.py`, `models/warranty_service_job.py`, `views/warranty_case_views.xml` |
| Warranty Case | Buttons shown where they refuse | Prepare Service Job hidden in Workshop / Vendor Repair (S1 refusal); Create Material Request hidden without Case Type; Create Vendor Claim from Job Created; Close Material Requests on Completed | repair, mrf views |
| Warranty Case | Close Case not emphasized; Cost Lines 0; clutter | Close Case primary; Cost Lines hidden at 0; Payment block only with a payment result; Repeated Failure in a "Failure Analysis" tab; Merged Ad-hoc only when set or New; free-service tabs only when relevant; Service Jobs icon | helpdesk, accounting, fsm views |
| Service Job | No primary after confirmation; workshop actions on AMC visits; "No Free Service" label | Open Field Service primary (confirmed / rescheduled / in progress, opens the open visit); Workshop Intake / Repair Order hidden on draft, AMC and free service jobs (related `warranty_case_type`); Free Services Type only when set; Free Services tab when used; Vendor Claim not on cancelled; Cost Lines hidden at 0 | fsm, repair, mrf, accounting |
| Field Service visit | Complete Visit primary while the sign-off was pending | Started -> Complete Worksheet; worksheets ready + sign-off required + unsigned -> Sign Report; signed (or not required) -> Complete Visit primary. Complete Visit stays available as secondary; server checks unchanged. Non-stored `warranty_signoff_required` (related company) and `warranty_worksheets_ready` (existing worksheet completion checks + checklist record) | fsm `models/project_task.py`, `views/project_task_views.xml` |
| Warranty Card / Free Service | Next step not emphasized | Create Installation Task primary while Pending Installation without task; free service Create Service Job primary when Scheduled / Rescheduled; duplicated Used / Balance removed from the Policy tab; Date History tab only with entries; Installation icon; Pending in the status bar | warranty_management, fsm views |
| Unit / Replacement | Technical fields; last step not emphasized | Sale line, move line, invoice posted at: developer mode; Generate Updated Card primary | warranty_management, repair views |
| Menus | All Repair Orders under Warranty; exception menu names | Warranty > Repairs > Repair Orders: warranty Repair Orders only (stock users); Late Service Requests / Exceptions | repair, helpdesk views |

Kept by earlier approved decisions: Approve and Reject Case both primary (Option C, test_67).

## Final corrections (2026-11-09, after review)

| Screen | Change | Module / file |
|---|---|---|
| Service Job header | Buttons shown only when their own check passes: Request Late Service Exception follows the wizard's offer rule (non-stored `warranty_late_exception_available`); Create Vendor Claim needs a consumed claimable part (non-stored `can_warranty_vendor_claim`, same check as the action, also used on the case); Close Material Requests after Completed / Cancelled; Workshop Intake not again once the case's Repair Order is in the workshop (related `warranty_workshop_repair_count`). Open Field Service stays the only primary in progress; holds, Cancel Job, Repair Order, Create Material Request, Report Fault stay secondary | fsm `models/warranty_service_job.py`, `views/warranty_draft_job_views.xml`; mrf `models/warranty_vendor_claim.py`, `views/warranty_vendor_claim_views.xml`, `views/warranty_mrf_closure_report_views.xml`; repair `models/warranty_service_job.py`, `views/warranty_service_job_views.xml` |
| Material Request (warranty) | One primary per stage. Draft: Decide Coverage (reviewer) / Request Coverage Decision while coverage is pending (Submit, refused then by T2.3, is hidden), else Submit. Stock: Recheck Stock / Issue Remaining, else Confirm Material Usage, else Received. Received: Confirm Material Usage, else Create Parts Quotation. The demoted actions stay as secondary twins (same method). Standalone requests unchanged | mrf `views/material_purchase_requisition_views.xml`, `warranty_mrf_sale_views.xml`, `warranty_mrf_consumption_views.xml`, `warranty_mrf_closure_report_views.xml` |
| Warranty Card | Free Services tab hidden when the card has no free services (Free Services Allowed 0 and no entitlements); Policy tab frequency fields only with a count. Decided 2026-11-09: data-driven, not by the kept company Scope Mode (BA 2026-10-28 unchanged; generation unchanged). Smart button already hidden at 0 | warranty_management `views/warranty_card_views.xml` |
| Upgrade | `warranty_management` 18.0.1.2.7 end-migrate: the 18.0.1.2.6 multi-unit soft copy regeneration did not run on UAT (live upgrade 2026-11-08 17:38 UTC: WC/00011, WC/00026 unchanged, no note). Same step, skipping cards that already have the regeneration note | `migrations/18.0.1.2.7/end-migrate.py` |

Not changed (separate, lower priority): Reports menu reorganisation. Note: the Warranty Dashboard
report menus have no groups, so Technicians see Warranty > Reports (mrf closure test_08 fails on
UAT data with old and new views). Policy / Coverage Item permissions are not part of this task.
