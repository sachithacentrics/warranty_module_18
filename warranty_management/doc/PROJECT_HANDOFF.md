# Warranty Management – Project Handoff (2026-10-28)

Handoff from a long Claude Code session to a fresh one. Read this first, then the decision records
it links. Times are local (Asia/Colombo) unless marked UTC.

## 1. Environment

| Item | Value |
|---|---|
| OS / shells | Windows 11; Git Bash (run `export MSYS_NO_PATHCONV=1` first) and PowerShell 5.1 |
| Odoo 18 | `D:\ODOO\odoo18\server` (`odoo-bin`), Python `D:\ODOO\odoo18\python\python.exe` |
| Config | `D:\ODOO\odoo18\server\odoo.conf` – http_port 8018, data_dir `D:\ODOO\odoo18\sessions`, addons_path `odoo\addons,custom_addons\warranty`. **`db_password` is in odoo.conf – never print it**; read it into `PGPASSWORD` with grep/sed. |
| PostgreSQL tools | `D:\ODOO\odoo19\PostgreSQL\bin` (psql, pg_dump, pg_restore, createdb), user `odoo18`, localhost:5432 |
| Live / demo DB | **`warranty_management_18_4`** (user's UAT database) |
| User's server | PyCharm run config "odoo18" = `odoo-bin -d warranty_management_18_4 -u warranty_management,warranty_management_helpdesk,warranty_management_mrp,amc_management` (port 8018). Its `-u` cascades to all dependent warranty modules, so **restarting it upgrades the live DB**. |
| Project root | `D:\ODOO\odoo18\server\custom_addons\warranty` |
| SRS | `custom_addons\warranty\Warranty_Module_SRS (1) (1).pdf` (read with PyPDF2: `python -I script.py`), mapping `Warranty Module Development Mapping.pdf`, `Part5_MRF_Integration_Mapping.md` |
| Users (18_4) | admin, approval (Requisition + Requisition Manager), demo, main_tech, support_tech; tz Asia/Colombo. Companies: 1 San Francisco, 2 Chicago (no warranty data). |

### Modules (live versions on 18_4)

| Module | Version | Part |
|---|---|---|
| `warranty_management` | 18.0.1.0.4 | Parts 1–2 core (cards, policies, units, free services, monitoring, PDF download approval) |
| `warranty_management_helpdesk` | 18.0.1.0.1 | Part 3 (tickets, warranty cases, eligibility, approvals, chargeable) |
| `warranty_management_fsm` | 18.0.1.0.1 | Part 4 (service jobs, visits, worksheets, completion, Draft Job from Service) |
| `warranty_management_mrp` | 18.0.1.0.1 | Kit Indoor / Outdoor serials |
| `warranty_management_mrf` | 18.0.1.9.1 | Part 5 bridge to the vendor module `material_purchase_requisitions` |
| `amc_management` | 18.0.1.0.0 | AMC (separate, do not modify) |
| `material_purchase_requisitions` | 18.0.11.9.12 | **External vendor module – never modify** |

### Running tests

```
cd /d/ODOO/odoo18/server; export MSYS_NO_PATHCONV=1
../python/python.exe odoo-bin -c odoo.conf -d wt_p5_mrf --http-port=8399 --stop-after-init \
  --test-tags /warranty_management_mrf --log-level=warn --log-handler=odoo.tests.result:INFO > LOG 2>&1
```

* Upgrade the test DB first after code changes: `-u warranty_management` (cascades) without tests.
* Run in the foreground (max 10 min per call, the machine has little free RAM). Groups:
  core+helpdesk+mrp+amc (227 tests, ~4 min); FSM in two halves by class (61 + 72); MRF (104).
* Baseline: **464 tests, 0 failed, 1 known error** (`test_13_serial_rules`, see §9).
* Odoo's `assertRaisesRegex` has no savepoint – tests use an override with savepoint +
  `invalidate_all(flush=False)`; tracking is written at commit – tests call `env.cr.precommit.run()`.
* Write scripts to files (Write tool) instead of heredocs with backslash continuations.
* Browser checks: HttpCase `browser_js` with a throwaway probe module (example used:
  `zz_usage_probe`, see §10); console output logged under `odoo.addons.<module>`.

## 2. Implementation and deployment status

| Part | Status |
|---|---|
| Parts 1–4 | Implemented, deployed on 18_4. Decisions: `warranty_management/doc/part2_design_decisions.md`, `warranty_policy_resolution.md`, `warranty_management_helpdesk/doc/part3_design_decisions.md`, `warranty_management_fsm/doc/part4_design_decisions.md`. Manual guides: `*/tests/Part2..Part4_Manual_Testing_Guide.md`. |
| Part 5.0–5.6 | Deployed (MRF link, coverage, approval matrix, quotation / release, fulfilment, consumption). |
| 5.7 Cost | Deployed (1.7.0), `part5_7_cost_design.md`. |
| 5.8 Vendor claims | Deployed (1.8.0 + serial/lot fix 1.8.1), `part5_8_vendor_claim_design.md`. |
| 5.9 Closure / audit / reports | Deployed 2026-10-28 08:5x (1.9.0), `part5_9_closure_audit_reporting_design.md` rev 2. **Not accepted yet** – waiting for the user's UAT (§3). |
| Small Fix: Scope Mode removal + Settings help | Deployed on 18_4 at 15:00 by the user's PyCharm restart (versions above). See §4. |
| Warranty Start Date Automation | **Technical deployment completed on 18_4 (2026-10-28 22:12 local, by a PyCharm "odoo18" debug-session start; verified read-only afterwards); manual UAT TC-SD-01–11 / TC-IN-01–10 pending.** Backup (taken just after the upgrade): `backups/warranty_management_18_4_before_start_date_20261028_2218`; last pre-upgrade backup: `..._before_fix02_20261028_1434`; trial copy `wm18_4_sd_check`. Tests needing their own start criterion must clear the company Default Warranty Policy (San Francisco: Standed Policy, Delivery). – design / decisions / implementation notes: `start_date_design.md` (rev 2, §16 decisions, §18 notes). Versions after deployment: core 18.0.1.1.0, helpdesk 18.0.1.0.2, fsm 18.0.1.1.0. |

**2026-10-29 status:** Helpdesk Is Warranty (18.0.1.0.3) and Site Address (18.0.1.0.4) are on
18_4 (upgraded 04:00 UTC by a PyCharm start, not by the deployment procedure). SRS service flow
alignment + optional Case Type (fsm 18.0.1.2.0, helpdesk 18.0.1.1.0, mrf 18.0.1.9.2):
implemented and tested on `wt_p5_mrf` (515 tests, 1 known error), trial-upgraded on
`wm18_4_srs_check` with identical data – **not deployed**; design / notes:
`warranty_management_fsm/doc/srs_service_flow_alignment_design.md`. Backup:
`backups/warranty_management_18_4_before_srs_flow_20261029_1054`. Open SRS gap: AMC entitlements.
Update: fsm 18.0.1.2.1 (SRS flow + past Planned Date allowed) reached 18_4 at 07:16 UTC by a
PyCharm start. Since then on `wt_p5_mrf` only (not deployed): due date / window not blocking
planning (fsm 1.2.2), card Service Jobs smart button (1.2.3), cross-card merge without window
overlap (helpdesk 18.0.1.1.1, fsm 1.2.4), **shared Field Service visit for several jobs** (fsm
18.0.1.3.0, mrf 18.0.1.9.3; `warranty_management_fsm/doc/shared_visit_design.md`). Regression
523 tests: 1 known error + `test_01_models_fields_and_sequence` (test DB WSE sequence passed
99999, environmental). Next live upgrade needs a fresh backup + trial upgrade first.
Deployment package (helpdesk 18.0.1.1.2, fsm 18.0.1.3.2, mrf 18.0.1.9.3; also Check Eligibility
on the job and Helpdesk Ticket smart button): backup
`backups/warranty_management_18_4_before_deploy_pkg_20261029_0905` (dump + filestore + counts /
checksums / values), restored and trial-upgraded on `wm18_4_pkg_check` (data identical, 38 smoke
tests pass) - **GO, awaiting authorization**.
Since the package (wt_p5_mrf only, not trial-tested): fsm 18.0.1.3.3 - Create or Link Helpdesk Ticket
links the ticket only (field `origin_ticket_id`); the case is created manually (Warranty Cases >
New) on that ticket and linked to the job on save. Case Coverage Management: design only
(`warranty_management_helpdesk/doc/case_coverage_design.md`), DEV-1 pending BA approval.

All Part 5 decisions: `warranty_management_mrf/doc/part5_design_decisions.md`. K-8 (lost / damaged
parts) deferred.

**2026-11-02 status:** Part 6.1 Repair Intake: new module `warranty_management_repair`
(18.0.1.0.0), coded per `warranty_management_repair/doc/part6_1_repair_intake_design.md`. **Not
installed on any database and never run**; manual UAT pending
(`warranty_management_repair/tests/Part6_Manual_Testing_Guide.md`). Backup Unit and Damage / Loss
Billing wait for the user's approval of Phase 1. Figure 4 gap analysis: reported to the user, no change.
Update: the user installed the module on 18_4 (UAT) and approved Phase 2. Part 6.2 Backup Units coded in
the same module (18.0.1.1.0, `doc/part6_2_backup_unit_design.md`): **never run**, manual UAT pending
(`tests/Part6_2_Backup_Manual_Testing_Guide.md`). Damage / Loss Billing waits for approval of Phase 2.
Update: Part 6.3 Damage / Loss Billing coded after conditional approval (18.0.1.2.0,
`doc/part6_3_backup_billing_design.md`): **never run**, needs a module upgrade by the user, manual UAT
pending (`tests/Part6_3_Backup_Billing_Manual_Testing_Guide.md`). BA decisions D3, D4, D6, D9 stay open:
Damaged and Lost records cannot be closed until D3. Phase 4 Reporting not started.

**2026-11-05 status:** Part 9 developed and tested on `wt_p7_s2` only, not on UAT. See
`Part9_History_Exceptions_Mapping.md` (sections 9-10), `doc/part9_controlled_actions_design.md` and
`doc/part9_test_report.md`. Void and the extended warranty product wait for business decisions.

**2026-11-07 status:** SRS Figure 7, non-accounting part (decisions D1 to D5 and D9, approved by
the user).
- Versions: mrf 18.0.1.10.0, repair 18.0.1.7.2, accounting 18.0.1.6.5.
- Implemented and tested on `wt_p7_s2` only; **not on UAT** (UAT has mrf 18.0.1.9.14, repair
  18.0.1.7.1, accounting 18.0.1.6.4).
- Changes:
  - no matching approval rule = No Approval Required;
  - rule Amount Basis;
  - Not Covered quotation after submission, with Release Blocked;
  - Stock Status / Awaiting Stock loop;
  - MRF Case Cost Breakdown;
  - Repair Order Create Material Request.
- Records: `warranty_management_mrf/doc/figure7_workflow_decisions.md`; guide
  `warranty_management_mrf/tests/Figure7_Manual_Testing_Guide.md`.
- Pre-change copy: DB `wt_f7_base`; module sources in the session scratchpad `rollback_f7_src`.
- Full regression on `wt_p7_s2` (run in small batches): 961 tests, only the 3 known baseline
  failures. The user accepted the work for further verification; it is not deployed to UAT.
- The warranty expense / provision accounting is a design only
  (`warranty_management_accounting/doc/figure7_accounting_design.md`, rev. 2: B2 evaluated on
  UAT; 600000 is not a suitable Cost Recognition Account). It waits for Finance decisions F1 to
  F14. No accounting code until approved.
- B2 chosen by the user (625100 / 216100 / 450100; not 600000; no backfill). The Finance checklist,
  validation rules and the remaining decisions D-F1 to D-F13 are in
  `warranty_management_accounting/doc/figure7_b2_finance_checklist.md`.
- B2 implemented on `wt_p7_s2` only: accounting 18.0.1.7.0, **off by default**, tests
  `test_figure7_b2`.
  - Pre-B2 copies: DB `wt_f7b2_base`; sources `rollback_b2_src/pre_b2_accounting` (scratchpad).
  - Finance setup, security and the UAT upgrade steps:
    `warranty_management_accounting/doc/figure7_b2_setup_and_upgrade.md`.
  - B2 must not be activated in UAT before Finance approves D-F1 to D-F13.
- **Superseded 2026-11-07 (user, after SRS review):** B2 removed. Accounting 18.0.1.8.0 uses
  standard Odoo stock accounting for covered parts and keeps only Finance-controlled reserve
  utilization (`warranty_management_accounting/doc/figure7_accounting_integration.md`, tests
  `test_figure7_accounting`). Built on `wt_p7_s2`; trial upgrade of UAT copy `wt_f7_mrf13`
  identical data. Rollback: DB `wt_f7std_base`, sources `rollback_f7std/` (scratchpad).
  UAT found at mrf 18.0.1.10.2 / accounting 18.0.1.7.0; mrf on disk 18.0.1.10.4.

## 3. Manual UAT status

* **Phase 5.9 – UAT-901 … 915** (`warranty_management_mrf/tests/Part5_Manual_Testing_Guide.md`):
  the step-by-step guide was given to the user; **no results reported yet**. Live data shows
  MRF/000005 still *Reconciled* (not closed), so at least UAT-904 onwards is not done. Phase 5.9
  must not be marked complete until the user validates closure, audit and report totals.
* **Phase 5.8 – TC 810–815** (posting / settlement from the draft credit note of VCL/00001):
  outstanding.
* **Scope Mode fix – TC-P2-080 / 081 / 082** (Part 2 guide, section 5.18) and **TC-P2-001 / 004
  (revised)**: not yet executed in the UI on 18_4.

## 4. Scope Mode removal and Settings help (deployed)

* BA decision 2026-10-28 (deviation from SRS §1.2 item 12), recorded in
  `part2_design_decisions.md` ("Warranty Scope Mode limitation removed"). The earlier proposal to
  move Scope Mode to the policy is **superseded**.
* `res.company.warranty_scope_mode` is kept (data preserved) but unused and not in Settings. Free
  services follow the resolved count + Auto-create + existing rules in every company; the
  `warranty_free_services_enabled` display fields were removed; Draft Job from Service runs for
  every company.
* `warranty_management_helpdesk/migrations/18.0.1.0.1/pre-migrate.py` cleans one stored view arch
  (load order); no data changes.
* All **38** visible settings of Settings > Warranty have a plain-English description (`<setting
  help>`) and hover help (field `help`; `title` where the setting has no field label). Warranty Case
  Approval Required "off" = approval by any Helpdesk user (manual), never "automatic". Test:
  `warranty_management_mrf/tests/test_settings_help.py`.
* Verified before deployment: regression 464 / 1 known error; trial upgrade on a restored backup;
  after the live upgrade all business values identical to the 14:34 backup (only +4 chatter
  messages and module versions).

## 5. Warranty Start Date Automation – analysis (historical; now implemented, see `start_date_design.md`)

Current code (`warranty_management/models/warranty_card.py`):
* Start / end are computed **only at Confirm Warranty** (`action_confirm_warranty` →
  `_get_warranty_start_date` / `_get_warranty_end_date`); end = start + duration − 1 day; units
  get the card dates; free services are generated at confirmation.
* Delivery: latest done delivery of the card (`stock.picking.date_done`) converted with the
  **confirming user's** timezone (should be the company Warranty Timezone).
* Invoice: earliest posted `invoice_date` of the card's SO lines – **reversed invoices are not
  excluded** (bug).
* Installation: manual `installation_date`, editable in Draft for every criterion, no checks; no
  Pending Installation state; no installation-task link.
* Confirmed dates are read-only in the UI only (no server-side guard; all internal users have write
  access); no tracking / audit; no correction process.
* Policy `start_date_basis` has no Custom option (Custom only via product / category / company).
* WC/00001 (S00038, Delivery basis) start 26 Oct 2026 = WH/OUT/00013 done 14:22:29 UTC, end
  25 Oct 2027 – correct. Its Installation Date (and WC/00002's) was typed manually by admin and is
  not used.

## 6. Start Date requirements (user, 2026-10-28)

* **Delivery basis**: start = actual validation date of the linked completed delivery
  (`stock.picking.date_done`); never the SO date, commitment or scheduled date. End from duration.
* **Invoice basis – IMPORTANT CORRECTION**: start = the **actual posting date (timestamp)** of the
  linked posted customer invoice, **not** the (possibly backdated) `invoice_date` and not the
  accounting date. Odoo 18 has **no posting-timestamp field**: capture it when the invoice is posted
  (hook on `account.move._post`), store it (date source on the card and/or a field on the move),
  convert to a date with the Warranty Timezone. Draft invoices never count; reversed invoices are
  excluded. For already-posted invoices a posting time can only be derived from chatter tracking
  (state Draft → Posted) – decide how to treat them.
* **Installation basis**: start = completion of the linked **Installation** Field Service task (not a
  manual date). Repair / maintenance / Part 4 service-job tasks must never activate. Card stays
  **Pending Installation** until the installation is completed; then Installation Date is filled
  automatically, start / end calculated; no duplicate activation; original completion date
  preserved; corrections only through an authorized, auditable process.
* **General**: apply the resolved policy's basis consistently; never activate before the source
  event; Warranty Timezone for timestamp → date (helper: Warranty Timezone > company contact tz >
  UTC, like `res.company._warranty_today`); source traceable from the card (delivery / invoice /
  task + timestamp); confirmed dates protected against UI, import and API; existing confirmed cards
  and dates preserved; partial deliveries / multiple invoices / multiple units handled explicitly;
  **no change to Part 4 service-job completion logic**.

## 7. Design and decisions D1–D11 (all decided 2026-10-28; final text in `start_date_design.md` §2 / §16)

Proposed (awaiting approval): new card status **Pending Installation**; expected start / end shown
as soon as the source event exists, frozen at confirmation; source fields (Start Date Source,
Source Delivery, Source Invoice + posting timestamp, Installation Task, Source Timestamp);
server-side write guard on card and unit dates after confirmation; **Correct Warranty Dates**
wizard (authorized group, reason, before / after audit, recalculates end, unit dates and Draft
free-service due dates). Installation tasks are identified positively: task created by standard
`industry_fsm_sale` from an SO line whose service product is ticked "Warranty Installation
Service", or by a "Create Installation Task" button on the card (`warranty_task_purpose =
'installation'`); tasks with `warranty_service_job_id` can never be installation tasks.
Code placement: delivery / invoice / status / guard / wizard in `warranty_management`, installation
in `warranty_management_fsm`.

| # | Decision | Status / recommendation |
|---|---|---|
| D1 | Invoice date source | **Decided by the user: actual posting timestamp** (see §6); still decide how to date invoices posted before the change |
| D2 | Partial deliveries | Open – rec.: card start = date fully delivered (latest delivery); each unit also stores its own delivery date |
| D3 | Multiple invoices | Open – rec.: earliest posted, non-reversed invoice containing the card's products; down payments never count |
| D4 | Installation task identification | Open – rec.: product tick + card button |
| D5 | One SO, several cards / tasks | Open – rec.: task covers all Pending Installation cards of the SO and site; card waits for all its tasks |
| D6 | Activation on installation | Open – rec.: auto-confirm if all other requirements are met; Delivery / Invoice cards stay manual confirm |
| D7 | "Completed and validated" | Open – rec.: Mark as Done; optionally require customer signature |
| D8 | Installation without a task | Open – rec.: only via the authorized correction wizard with reason |
| D9 | Who may correct dates | Open – rec.: new group "Warranty: Date Correction" |
| D10 | Free services after correction | Open – rec.: recalculate only Draft / Pending entitlements |
| D11 | Card chatter (today logs only PDF downloads) | Open – rec.: allow activation / reversal / correction notes |

## 8. Live data that must be preserved (18_4)

* Cards: WC/00001 (Delivery, policy Standed Policy, 1 year), WC/00002 (Invoice, 6 months),
  WC/00003 (Invoice), WC/00004 (Delivery) – all confirmed, Period basis, San Francisco.
* Entitlements (8): WC/00001 1 Job Created; WC/00002 Missed + Draft; WC/00003 Completed + Draft;
  WC/00004 3 Draft.
* Cases: WCAS/000001 job_created, 000002 approved, 000003 completed, 000004 approved.
  Jobs: JOB/000001 confirmed, JOB/000002 cancelled, JOB/000003 completed.
* MRFs: 000001 draft, 000002 manager approval (legacy), 000003 issued, 000004 issued (Bolt issued,
  not recorded – blocks closing WCAS/000003), 000005 reconciled (ready to close, S00041 Gas not
  invoiced), 000006 draft.
* Vendor claim VCL/00001 answered, claimed / accepted 1,200, recovered 0, draft vendor credit note.
* Do not create or post credit notes or payments automatically; preserve approval histories,
  attachments and accounting records (30 account moves).
* Count / value queries for comparisons: in the fix02 backup folder (`counts_query.sql`,
  `values_query.sql`, §10).

## 9. Open bugs and items

* **Part 3 `test_13_serial_rules`** (helpdesk `TestWarrantyCaseEligibility`) – known error, fix
  needs approval of a Part 3 change. Track separately.
* **User edits not covered by a regression run**: 14:31 coverage-item change (`warranty_coverage_item.py`,
  `warranty_coverage_item_views.xml` in core, helpdesk `models/__init__.py`) and 15:00 card view edit
  (Free Services tab fields removed). Both are deployed on 18_4 (15:00 upgrade succeeded) but the
  full regression has not been rerun since – run it before the next deployment.
* Invoice-basis start used reversed invoices (§5) – fixed by the Start Date Automation (not deployed yet).
* Start Date Automation regression on `wt_p5_mrf` 2026-10-28: 492 tests, 0 failed, 1 known error
  (covers the user's 14:31 / 15:00 edits). Deployment to 18_4 still needs the backup / trial
  upgrade procedure and the user's authorization.
* Usage Due / Usage Unit columns in the card Free Services tab: code and DB are correct (verified in
  a browser on a copy); user's view was likely the standalone Services list or a stale tab – no
  change made; confirm with the user.
* Older pending items: paused Part 4 "service visit attachments optional" (setting Worksheet
  Attachment Required); technicians can see 5.1 / 5.3 estimated / approval amounts; decisions
  D8 / D9 / C-1..C-5 / F-1..F-7 (earlier phases); JOB/000002 / WSE/00002 scheduling item; K-8.
* No undeployed fixes in the code base.

## 10. Backups and disposable databases (keep – cleanup only with explicit approval)

Backups `D:\ODOO\odoo18\backups\` (dump + filestore + counts):
`warranty_management_18_4_before_5_6_20261027_1341`, `..._pre_upgrade_20261027_1351`,
`..._before_5_7_20261027_1913`, `..._before_5_8_20261027_2134`, `..._before_5_9_20261028_0847`,
**`..._before_fix02_20261028_1434`** (latest; also `values_before.txt`, `values_live_after_1500.txt`).

Dumps in the old session scratchpad
`C:\Users\Centrics\AppData\Local\Temp\claude\D--ODOO-odoo18-server\a578f0c3-be60-4427-b85d-376b18c4f674\scratchpad\`:
`wm18_4_now.dump`, `wm18_4_581.dump`, `wm18_4_fix02.dump`, `wm18_4_usage.dump`,
`warranty_management_18_2_*.dump`; probe module `probe_addons\zz_usage_probe`.

Disposable DBs: `wt_p5_baseline`, `wt_p5_mrf` (main test DB, has all modules + current code),
`wt_p5_probe`, `mpr_v18_test`, `wm18_2_fixtest`, `wm18_2_copy2`, `wm18_2_copy3`,
`wm18_4_upgrade_check`, `wm18_4_57_check`, `wm18_4_57_restore`, `wm18_4_58_check`,
`wm18_4_581_check`, `wm18_4_59_check`, `wm18_4_fix02_check`, `wm18_4_fix02_restore`
(zz_usage_probe installed), `wm18_4_usage_check` (copy of live after 15:00, zz_usage_probe
installed). Their filestores are under `D:\ODOO\odoo18\sessions\filestore\`. Other DBs on the
server (aiken_*, altek_*, tsl_*, warranty_test, warranty_management_18_2, …) are not ours.

## 11. Rules

* **Never upgrade `warranty_management_18_4` or stop / restart the PyCharm server without the
  user's explicit authorization** (the restart itself upgrades the DB). Coordinate timing; take a
  fresh backup (dump + filestore + counts + values), test-restore it, trial-upgrade the copy first.
* Design first, wait for approval, then implement on isolated test DBs; report blockers and
  unresolved items separately; never silently mark items as passed.
* Do not modify: `material_purchase_requisitions` (vendor), AMC modules, `warranty_test`,
  `warranty_management_18_2`, Parts 1–4 or unrelated parts unless the user asks for that change.
* Preserve records, MRF data, approval histories, attachments, accounting; never create / post
  credit notes or payments automatically.
* Keep all backups, dumps and disposable DBs until the user approves cleanup.
* Work efficiently: targeted test classes during development, full regression once at the end,
  filtered log output.

## 12. Next steps for the new session

**Update 2026-10-28 (later session):** steps 1–4 below are done for the Start Date Automation
(design approved, implemented on `wt_p5_mrf`, full regression passed). Remaining: step 5
(deployment preparation, only with the user's authorization), UAT TC-SD-01–11 (Part 2 guide
§5.19) and TC-IN-01–10 (Part 4 guide), and step 6.

1. Read this file, then `part2_design_decisions.md` (end sections) and the Part 5 decision record
   as needed.
2. Ask the user for the remaining Start Date decisions **D2–D11** and how to date invoices posted
   before the change (D1 follow-up). Do not code before approval.
3. With approval, write the design document (e.g. `warranty_management/doc/start_date_design.md`),
   then implement on `wt_p5_mrf` (upgrade with `-u warranty_management`), with new tests.
4. Run the full regression (also covers the user's 14:31 / 15:00 edits, §9).
5. Prepare deployment: fresh backup of 18_4, restore to a new disposable DB, trial upgrade,
   compare counts / values, then ask the user when to stop PyCharm.
6. In parallel, remind the user of outstanding UAT (5.9 UAT-901–915, 5.8 TC 810–815,
   TC-P2-080–082).
