# Warranty Management – Part 2 Design Decisions

**Free Service Entitlements – Free Service Due Monitoring**

| Item | Value |
|---|---|
| Module | `warranty_management` 18.0.1.3.0 |
| Primary source | Warranty Module SRS (Functional Solution and System Design Document) |
| Secondary source | Warranty Module Development Mapping – Part 2 workflow diagram |
| Scope | Mapping Part 2 after "Generate Free Service Schedule": Warranty Basis? → Monitor Service Due Date → Service Due? → Due Alert → Service Expired? → Extra Allowed Period / Expiry Rule → Keep Available / Mark Expired |
| Status | All decisions below were explicitly approved by the business owner before implementation |

The SRS remains the source of truth. This document records every point where the SRS is silent, ambiguous or in conflict, and the approved resolution.

---

## 1. Approved deviations and clarifications

| ID | Topic | SRS / Mapping position | Approved resolution |
|---|---|---|---|
| C1 | Draft status | SRS §10.3 lists 8 statuses without Draft; SRS §2.5, §7, §9.3 step 8, §19 and the Mapping require services to be created in Draft | Draft is kept as the initial status. The 8 SRS §10.3 statuses are kept unchanged. No migration of existing Draft records. |
| C2 | "Due" stage | SRS §9.13 lifecycle Draft → Due → …; SRS §10.3 has no Due status | No Due status. A separate **Due Indicator** (`due_status`: Upcoming / Due / Overdue) tracks due-date conditions. Reaching the alert date never changes the lifecycle status. |
| C3 | "Job Created" stage | SRS §9.13 only | Handled through the Service Job relationship in Part 3/4. Merge Status remains a separate field (SRS §10.3). |
| C4 | Missed vs Expired | SRS §12 scenario 6: "Scheduler marks expired or missed"; scenario 23: "expired after grace period"; rule not defined | **Missed**: due date passed without completion, while within the grace period (or when expiry does not apply). **Expired**: only after the grace period ended, Auto-expire on, Carry-forward off. |
| X1 / D1 / D2 | Free Services Balance | Mapping: Balance = Allowed − Used | **Balance = Allowed − Completed − Expired − Cancelled.** Used = Completed (SRS §9.4 step 8 – consumption). Missed stays in the balance. Separate counts: Used (Completed), Missed, Expired, Cancelled. |
| D2 | Job vs entitlement cancellation | SRS §9.4 step 9: cancelled jobs do not consume entitlement | Cancelling a Service Job (Part 3/4) must never cancel or consume its service entitlement. An entitlement becomes Cancelled only through an explicit entitlement-level action. **No such action exists in Part 2** (SRS defines no trigger); only the balance formula supports it. |
| D3 / Q7 | Deletion | SRS §2.13: critical values must not be overwritten silently | Completed, Missed, Expired and Cancelled entitlements cannot be deleted by anyone (including administrators). Deleting a warranty card holding such entitlements is blocked. Draft entitlements: administrators only (`base.group_system`). Nothing is deleted automatically. |
| Q4 | Carry-forward | SRS §12 scenarios 6 / 23: configurable, behaviour not defined | Configurable on the policy. When enabled, a Missed entitlement is **never expired automatically** and stays Missed pending the carry-forward rules. No automatic extension, transfer or rescheduling. |
| X4 | Expiry Reminder Days | Not in the SRS (only the due alert of §2.5 / §7 / §10.3) | Added as a separate configurable field at the business owner's request. |
| Q2 / X8 | Alert responsible users | SRS does not define who receives alerts | Configurable **Service Alert Responsible Users** (several users allowed, 18.0.1.3.0) on the policy, company-level fallback, snapshotted on the card at confirmation. **Each valid user receives their own activity.** |
| A4 | Notifications | — | Internal Odoo Activities. No customer Email / WhatsApp. Odoo's standard "activity assigned" notification to the internal user follows that user's notification preference and the outgoing mail configuration. **Added 2026-10-16 (D1–D5):** each **due alert** also queues one dedicated email (template *Warranty: Free Service Due Alert*) to every valid responsible user with an email address, whatever their notification preference – see section 6a. **Added 2026-10-16 (E1–E4):** each **expiry reminder** queues one dedicated email too, and each **automatic expiry** queues one *Service Expired* email per valid responsible user. |
| A8 | Timezone | — | Dates are evaluated in the company's **Warranty Timezone** → company contact timezone → UTC (with a server-log warning). |
| Q1 | Historical records | — | Only cards confirmed after this version (`service_monitoring_active` = True) are monitored. Existing cards and their entitlements are never changed automatically. |
| Q4a | Carry-forward on the policy form | — | **Carry-forward Allowed** is kept on the model but hidden on the policy form (always off) until the carry-forward rules are defined. The Q4 expiry rule stays in place. |
| P1–P5 | Warranty Policy architecture | SRS §2.2 resolution priority | **Approved 2026-10-16 (final design review):** strict policy priority – Product + Pricelist mapping line policy (replaced 2026-10-17 by the **Sales Order pricelist policy**, D1–D5) > product policy (per company) > category policy > Company Default Warranty Policy, then the own values (P5). No mixing of lower-level values; Company Warranty Settings fill an empty Basis / Start Criterion / Free Service Period / Schedule Method; an invalid selected policy is a configuration error; policies of other companies never apply; Applies To and the applicability mappings removed from the policy interface (data kept); new policy fields Free Service Frequency / Unit and Usage Limit. Brand, Model and Customer Type policy levels removed. Details: `doc/warranty_policy_resolution.md`. |

---

## 2. Configuration

### 2.1 Warranty Policy – "Service Due Monitoring" group

| Field | Technical name | Rule |
|---|---|---|
| Grace Period (Days) | `grace_period_days` | ≥ 0. 0 = expiry rule evaluated from the day after the due date |
| Auto-expire | `auto_expire_services` | Off = never moved to Expired automatically |
| Carry-forward Allowed | `carry_forward_allowed` | On = never expired automatically (rules pending). **Hidden on the form – always off** |
| Service Due Alert Days | `service_due_alert_days` | ≥ 0. **0 = due alert disabled** |
| Expiry Reminder Days | `expiry_reminder_days` | ≥ 0. **0 = expiry reminder disabled** |
| Usage Alert % | `usage_alert_percentage` | 0–100. Display only (usage threshold); not monitored |
| Service Alert Responsible Users | `service_alert_user_ids` | Several users allowed. Each must be an active internal user allowed in the policy company when the policy has one |

### 2.2 Company – Warranty Settings → "Free Service Monitoring"

| Field | Technical name | Rule |
|---|---|---|
| Service Alert Responsible Users | `warranty_service_alert_user_ids` | Fallback users (several allowed); each an active internal user allowed in the company |
| Warranty Timezone | `warranty_timezone` | Timezone for "today" in due / expiry evaluation |

### 2.3 Warranty Card – snapshot at confirmation (read-only)

When the card includes free services, confirmation copies the seven policy values above to the card and sets `service_monitoring_active`. The responsible users are resolved as the valid policy users → (if none is valid) the valid company fallback users; only users valid for the card company are copied. Later policy changes do not affect confirmed cards.

At run time the responsible users are: the still-valid card snapshot users → (if none is valid) the valid **current** company fallback users (A1). Users who became invalid (archived, not internal, not allowed in the company) are skipped and logged. The snapshot itself is never overwritten. The user fields also show archived users, so a stale configuration stays visible.

---

## 3. Fields on `warranty.service.entitlement`

| Field | Type | Definition |
|---|---|---|
| `state` | Selection (unchanged) | Draft + SRS §10.3: Pending, Scheduled, In Progress, Completed, Missed, Expired, Cancelled, Rescheduled. Changes are tracked in the chatter. |
| `merge_status` | Selection (unchanged) | Not Merged, Selected, Merged, Completed |
| `grace_period_end_date` | Date, computed stored | `due_date` + grace days (monitored cards only) |
| `alert_date` | Date, computed stored | `due_date` − due alert days; empty when disabled |
| `expiry_reminder_date` | Date, computed stored | grace end − reminder days; empty when disabled, Auto-expire off or Carry-forward on |
| `usage_threshold` | Float, computed stored | `usage_due` × Usage Alert % ÷ 100 (display only) |
| `due_status` | Selection | Empty / Upcoming / Due / Overdue |
| `due_alert_sent`, `expiry_reminder_sent` | Boolean | Duplicate prevention |
| `due_alert_activity_ids`, `expiry_reminder_activity_ids` | Many2many `mail.activity` | The system-generated activities, one per responsible user (only these are ever closed automatically) |

The model inherits `mail.thread` and `mail.activity.mixin`.

---

## 4. Status transitions (scheduled action only)

Evaluated only for entitlements where the card is Confirmed, period-based, `service_monitoring_active` is set and a due date exists, and `_is_expiry_blocked()` is False.

| # | From | To | Condition |
|---|---|---|---|
| T1 | Draft, Pending | Missed | today > due date and today ≤ grace end |
| T2 | Draft, Pending | Expired | today > grace end, Auto-expire on, Carry-forward off |
| T3 | Draft, Pending | Missed | today > grace end and (Auto-expire off or Carry-forward on) |
| T4 | Missed | Expired | today > grace end, Auto-expire on, Carry-forward off |

Not automated in Part 2: Draft → Pending (no SRS trigger); transitions into Scheduled / In Progress / Completed / Rescheduled (Part 3/4); any transition into Cancelled; any transition out of Missed or Expired.

Completed, Cancelled and Expired entitlements are never selected for change. Scheduled, In Progress and Rescheduled entitlements only receive the due indicator.

## 5. Due indicator

| Value | Condition |
|---|---|
| Empty | Not monitored, no due date, before the alert window, or Completed / Expired / Cancelled |
| Upcoming | alert date ≤ today < due date (only when due alert days > 0) |
| Due | today = due date |
| Overdue | today > due date and the entitlement is open (Draft, Pending, Scheduled, In Progress, Rescheduled, Missed) |

---

## 6. Automation – "Warranty: Monitor Free Service Due Dates" (daily)

Runs as the system user, per company, with "today" in the company warranty timezone. Order per run:

1. **Due alert** – one activity *Free Service Due Alert* per valid responsible user when: alert days > 0, state Draft/Pending, merge status Not Merged, alert date ≤ today ≤ due date, not yet sent, at least one valid responsible user. Deadline = due date.
2. **Expiry reminder** – one activity *Free Service Expiry Reminder* per valid responsible user when: reminder days > 0, Auto-expire on, Carry-forward off, not blocked, state Draft/Pending/Missed, reminder date ≤ today ≤ grace end, not yet sent, at least one valid responsible user. Deadline = grace end.
3. **Transitions** T1–T4.
4. **Closure** – when an entitlement becomes Expired, only its linked system activities are marked done with the note "Service expired". Both activity types have *Keep Done*, so closed activities remain as history; manual activities are never touched.
5. **Due indicator** refresh; stale indicators on closed / unmonitored entitlements are cleared.

**Late or delayed runs (A3):** reminders are evaluated before transitions. When the window has already passed, no reminder is created (no due alert after the due date – no overdue-reminder rule exists; no expiry reminder after the grace end). At most one set of activities of each kind (one per responsible user) per entitlement per due date.

**Missing responsible user (A2):** when no selected user is valid: no activity, nothing marked as sent (the alert is created on a later run if configured while the window is still open), a notice on the card's Free Services tab and on the policy form, and one warning line per company and run in the server log.

**Due date change (A3.4, Draft only):** the open system activities → their deadline / summary move to the new dates, no new activity; when **all** of them are closed or deleted → the sent flag is reset so one new set can be created for the new dates.

---

## 6a. Due alert email (approved 2026-10-16, D1–D5)

- Sent from the existing due alert step of the daily action, right after each user's activity
  (`_send_due_alert_email`), for the same valid responsible users. Activities, their standard
  notification, alert dates, user selection and expiry reminders are unchanged.
- Template `mail_template_free_service_due_alert` (noupdate): Warranty Card, Customer, Product (the
  card product, else the products of its order lines – D4), Service No., Due Date and a *View Free
  Service* link (`/mail/view`). Rendered in the recipient's language (D2).
- **Sender:** the card company's email, else the server default sender
  (`ir.mail_server._get_default_from_address()`), else Odoo's default; **Reply-To** = sender (D3).
- **One email per user and alert:** one `mail.mail` per user (single recipient), created in the
  same transaction as the activities and the Due Alert Sent mark, so later runs never send it again.
  A changed due date resets the alert and sends a new email for the new date (D5).
- **Failures:** the email is only queued (`force_send=False`) and sent by the standard mail queue,
  so delivery errors never block activities. Emails are kept (`auto_delete` off): Settings →
  Technical → Email → Emails shows the status and failure reason; **Retry** resends only the
  failed email(s) of the selected users. A user without an email address gets the activity but no
  email (server log warning, D1); an error while preparing one email is logged and skips only that
  email (own savepoint).

### 6b. Expiry reminder and service expired emails (approved 2026-10-16, E1–E4)

- Same sending rules as 6a (shared `_send_service_email(user, template)`: company sender with
  fallback, Reply-To = sender, one email per user, recipient language, queued and kept, own
  savepoint, user without email skipped and logged).
- **Expiry Reminder email** (`mail_template_free_service_expiry_reminder`): queued right after each
  user's expiry reminder activity; Warranty Card, Customer, Product, Service No., Due Date, Grace
  Period End Date, link. Once per reminder (Expiry Reminder Sent).
- **Service Expired email** (`mail_template_free_service_expired`): queued by `_apply_expiry_rules`
  after the Expired transition and the closing of the system activities, to the valid responsible
  users (card snapshot, else company fallback); "EXPIRED" subject, Service Reference, Warranty
  Card, Customer, Product, Due Date, **Expiry Date (Grace Period End)** and **Expired On** (company
  date of the run – E1). One email per service and user (E2); Expired is final, so it is sent once.
  Also sent when Expiry Reminder Days = 0 (E3). Services expired before this version get no email.
- Expiry conditions, activities and their notifications are unchanged; an email problem never
  blocks the expiry (the state is written first, the email is only queued).

### 6c. Free service scheduling (approved S1–S7, S2 monitoring, R1)

- **Schedule / Reschedule** buttons on the free service open the *Schedule Free Service* wizard
  (monthly date picker, default the due date or today; services already scheduled in that month
  are listed for information – no capacity restriction, S6). Allowed any time (S7) on a confirmed
  card for Draft / Pending, Missed within the grace period (Schedule, or Reschedule when it
  already has a scheduled date) and Scheduled / Rescheduled (Reschedule).
- Confirm saves the **Scheduled Service Date** (`scheduled_date`) and sets **Scheduled** (first
  schedule) or **Rescheduled** (S1); the Due Date, Fixed Offsets / Equal Interval dates and the
  policy resolution are unchanged; never Completed.
- Validations: not in the past (company warranty timezone); not after the Grace Period End Date
  (S3); a reschedule needs a reason and another date; the date is only written by the wizard
  (direct writes and the calendar drag-and-drop are refused, S5).
- **Schedule History** (`warranty.service.entitlement.schedule.log`): action, user, date/time,
  previous / new scheduled date, reason; multi-company rule; Reschedule Count = number of
  reschedules.
- On scheduling, open **due alert** activities are marked Done "Service scheduled" (S4); no new
  due alert / due alert email afterwards (Draft / Pending only, unchanged).
- **Free Service Calendar** (menu Warranty → Free Service Calendar, and the calendar view of the
  Service Entitlements action): the free service records themselves on their Scheduled Service
  Date (one entry per service, moved by a reschedule – no duplicates), coloured by status.
- **S2 monitoring** (daily job): Scheduled / Rescheduled stay while the scheduled date is today or
  later or the due date has not passed; when both have passed → **Missed**, or **Expired** directly
  when the Grace Period End has passed with Auto-expire on and Carry-forward off (late run);
  merged services are never changed. Missed services then follow the existing rules (expiry
  reminder once per service, Expired + email). **R1:** rescheduling a Missed service leaves its
  open expiry reminder unchanged; no duplicate reminder activity / email. Automatic changes are in
  the chatter, not in the Schedule History; the scheduled date is kept.

### 6d. Kit products – Indoor / Outdoor serial numbers (approved K1–K4)

- **K1:** separate bridge module `warranty_management_mrp` (depends on `warranty_management` +
  `sale_mrp`, auto-installed when both are installed); Manufacturing stays optional.
- **K2:** *Warranty Component Role* (None / Indoor Unit / Outdoor Unit) on Kit BoM lines; at most
  one Indoor and one Outdoor line per kit, Kit BoMs only, serial-tracked component, 1 per kit unit.
- Delivery validation (main module hook `stock.picking._warranty_allocate_sale_line`): for kit
  lines the serials of done outgoing Indoor / Outdoor component move lines are written on the
  warranty units (`indoor_serial_id`, `outdoor_serial_id`, also in Serial(s)) – **K3:** the k-th
  delivered serial of a role goes to the next unit without one (delivery order); a serial is used
  once; backorders fill the remaining units; nothing is created. Kits without roles are allocated
  once from their first component; non-kit lines are unchanged.
- **K4:** the pairing can be corrected on the card's Unit Warranty Numbers tab while the card is
  Draft / Ready to Confirm – only serials delivered for the same Sales Order line and role, no
  serial on two units (a swap of several units is checked after the save); corrected units are
  flagged *Serial Pairing Corrected* and never changed by later deliveries.
- The card's Indoor / Outdoor Serial No. are filled only for single-unit cards (unless the user
  entered another value on the card).
- Warranty confirmation requires the Indoor / Outdoor serial of every kit unit whose Kit BoM has
  these roles.
- 2026-10-19: the warranty card's own Brand / Model text fields were removed by the business
  owner (form, report).

### 6e. Warranty card PDF download approval (approved D1–D5)

- Warranty confirmation still generates the PDF (unchanged report) – stored in the protected
  field attachment `warranty.card.pdf_file` (administrators only, not listed with the normal
  attachments); **not** a download (Download Count stays 0).
- Settings per company (Warranty Settings → *Warranty Card PDF Download Approval*): Require PDF
  Download Approval, Free Download Count (default 1, at least 1), Download Approval Responsible
  Users (internal users allowed in the company).
- **Download PDF** (confirmed card): within the free count (or approval not required) a
  single-use ticket of the user and card, valid 10 minutes (D3), opens
  `/warranty/card/pdf/<ticket>`, which sends the stored PDF and records the download (Download
  History: card, user, date / time, download no., request). After the free count: the user's
  approved unused request is used; otherwise a *Download Approval Request* (WDR/xxxxx, reason
  required, one pending per user and card – D2) is created and the approvers get an activity.
- Approve / Reject only by the company's approvers, never the requester; one approval = one
  download; the request becomes **Used** when the file is sent (D4); rejected → no download.
- Checks are repeated when the file is sent (free count used meanwhile, request still approved,
  ticket unused / not expired / same user); the card row is locked and a ticket can only be
  counted once (no duplicate counting).
- Protection (D5): `ir.binary._record_to_stream` refuses the protected PDF on every standard
  web file / preview / image link (also for administrators); `ir.actions.report._render_qweb_html`
  refuses the warranty card report outside the system generation (internal marker that cannot
  be sent by a client), so `/report/pdf|html` cannot bypass the approval. Limitation accepted:
  system administrators can still read the raw data through the API. Other attachments are
  unchanged.
- Warranty card UI (2026-10-19): one **Download History** tab only – read-only view `warranty.card.download.history` (SQL view over the download log and the requests): each download with its request (status, requested by, approved / rejected by, dates, reason) and the requests without download yet. No requests section / buttons on the card; approvers decide from their activity (request form) or Warranty Cards → Download Approval Requests. All records kept.
- Existing cards: Download Count 0 (no history created). One-time (D1): the existing PDF soft
  copies (attachment of *PDF Soft Copy*) are moved into the protected storage – same records and
  content; other attachments unchanged.

## 7. Expiry block – temporary Part 2 limitation (A7)

`_is_expiry_blocked()` returns True when Merge Status is Selected or Merged. While blocked the scheduled action does **not** move the entitlement to Missed or Expired, creates no expiry reminder and never consumes or cancels it; only the due indicator is updated.

Part 2 has no Service Job, so nothing sets Selected / Merged yet. **Part 3/4 must extend `_is_expiry_blocked()`** with the actual Service Job state; when a job is cancelled the block is lifted and decision D2 applies (job cancellation never cancels or consumes the entitlement).

## 8. Eligibility – rule for Part 3 (A9)

A free service entitlement may be used only when all of the following hold:

1. Lifecycle status is Draft, Pending or Missed (Missed only within the grace period, or while Carry-forward is pending).
2. Free Services Balance > 0 (SRS §13).
3. The warranty is valid (SRS §9.5 – period / usage, status not suspended / voided / expired).
4. Applicable policy rules (payment, coverage, overdue handling).

**Missed status alone never guarantees eligibility.** Carry-forward never overrides warranty validity.

## 8a. Manual warranty card grouping (Part 1 flow change, approved 2026-10-16)

Approved decisions Q1–Q4:

- **Sales Order confirmation** validates the warranty configuration of every eligible line
  (Warranty Applicable product, quantity > 0, no Unit Warranty Number yet) with the existing
  resolution – "Configuration Required" still blocks the confirmation – but **no warranty card or
  unit warranty number is created**. Card Grouping Mode is no longer a required value (Q4).
- A **Warranty Grouping** header button is shown while the confirmed order has such pending
  lines (`sale.order.warranty_grouping_pending`, computed, not stored).
- **Wizard** `warranty.grouping.wizard` (transient): Sales Order (readonly), **Card Grouping Mode**
  (required, no default; Per Sales Order / Per Product / Per Delivery / Per Unit/Serial) and the
  pending products (`warranty.grouping.wizard.line`: product, quantity, Warranty Policy, Policy
  Source, Warranty Duration). **One mode for the whole Sales Order** (Q1).
- **Confirm:** the order must still be confirmed and have pending lines (otherwise "Warranty cards
  were already created" – no duplicates); **Per Delivery** is refused when an eligible product has
  no outgoing delivery, naming the products (Q3). The rule of each pending line is resolved again,
  the selected mode replaces the configured one, the existing grouping key still splits lines with
  different warranty values, and the Draft cards and unit warranty numbers are created as before.
  Deliveries already validated are then allocated with the existing delivery / serial allocation
  (including the Per Delivery split). The rest of Part 1 is unchanged.
- **Existing grouping fields** (Company Default Card Grouping Mode, policy and category Card
  Grouping Mode) are kept with their data but hidden and no longer used (Q2 a). The card's own
  Card Grouping Mode stores the selected mode.
- Policy, duration and free service resolution, existing cards and multi-company behaviour are
  unchanged (the order company is used).

## 9. Out of scope / not implemented

- Usage-based monitoring (no approved source of current usage readings; SRS §2.7 captures usage on worksheets in Part 4). Usage cards get no indicator, alert or transition.
- Carry-forward behaviour (extension / transfer / rescheduling).
- Overdue reminders after the due date.
- Entitlement cancellation action.
- Warranty card expiry at warranty end date (SRS §14).
- Customer-facing notifications.
- Warranty-specific security groups (Phase 10); administrator = `base.group_system`.

---

## 10. Change log

| Version | Change |
|---|---|
| 18.0.1.2.0 | Free service due monitoring (this document). |
| 2026-10-19 (manifest 18.0.1.0.0) | Warranty card PDF download approval (section 6e): protected PDF storage, Download PDF with single-use tickets, Download History, Download Approval Requests, settings per company, report / file link protection, one-time protection of the existing PDFs. |
| 2026-10-19 | Bridge module `warranty_management_mrp` 18.0.1.0.0: Kit Indoor / Outdoor serials (section 6d). Main module: per Sales Order line delivery allocation hook; warranty card Brand / Model text fields removed (business owner). |
| 2026-10-19 (manifest 18.0.1.0.0) | Free service Schedule / Reschedule, Schedule History, Free Service Calendar and S2 monitoring of Scheduled / Rescheduled services (section 6c). |
| 2026-10-19 (manifest 18.0.1.0.0) | Removed by the business owner: Schedule Method **Calendar Month** (and its pending notice); **Product Brand / Product Model** (models, views, access rights, product fields, policy legacy links – data dropped on upgrade, accepted). Warranty card Brand / Model text fields unchanged. |
| 2026-10-17 (manifest 18.0.1.0.0) | Pricelist Warranty Policy (D1–D5): Warranty tab on the standard pricelist (Warranty Applicable + required Warranty Policy, policy values readonly; company pricelist: own / shared policies, shared pricelist: shared policies); priority Pricelist > Product > Category > Company Default > own values; Product + Pricelist Warranty Mapping removed from the product form and from the resolution (records kept, logged once); Policy Source "Pricelist Warranty Policy". |
| 2026-10-16 (manifest 18.0.1.0.0) | Strict Warranty Policy architecture (decision P1–P5, `doc/warranty_policy_resolution.md`): policy selected on mapping line / product (company-dependent) / category / company; Applies To and mappings hidden (data kept); one-time copy of the legacy direct product assignments (`data/warranty_policy_migration_data.xml`); new Policy Sources; policy Free Service Frequency / Usage Limit. Due alert and expiry notifications unchanged. |
| 18.0.1.3.0 (2026-10-16) | Manual warranty card grouping: Warranty Grouping wizard after Sales Order confirmation (section 8a); grouping fields hidden. No migration. |
| 18.0.1.3.0 | Service Alert Responsible User → **Service Alert Responsible Users** (several users) on company settings, policy and card snapshot; one activity per valid user; invalid users skipped and logged. Migration `migrations/18.0.1.3.0/post-migrate.py` copies the previous single values (users and activity links); the old columns are left unused in the database. Carry-forward Allowed hidden on the policy form (Q4a). |

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


## Warranty Scope Mode limitation removed (BA decision, 2026-10-28)

**Deviation from the original SRS** (section 1.2 item 12 "General scope modes" and the
Configuration table "Warranty Scope Mode - controls which capability blocks are enabled"): after
review with the BA, the company Warranty Scope Mode no longer limits any warranty functionality.
The earlier proposal to move the Scope Mode to the Warranty Policy is superseded and was not
implemented.

* Removed limitations: L1 free services are included when the card's resolved Free Services
  Allowed > 0 (`warranty.card._free_services_included`); L2 the entitlement constraint follows L1
  (confirmed card, AMC Plan method, count and service-number limits are kept); L3 the free service
  tabs / sections on card, product, category, pricelist, Helpdesk ticket, Create Warranty Case
  wizard, warranty case, ticket Pending Services button and service job are always shown (the
  computed display fields `warranty_free_services_enabled` are removed); L4 Draft Job from Service
  runs for every company; L5 the Free Service Settings / Free Service Monitoring blocks are always
  shown in Settings; L6 the Scope Mode is no longer shown in Settings.
* Kept: the company field `res.company.warranty_scope_mode` and its values (backward
  compatibility, not used); free service generation by the resolved count, Auto-create Services
  and the existing rules; "Default Warranty Duration required without a Default Warranty Policy"
  (only its Scope Mode wording was removed); all approval, payment, security and validation rules.
  AMC uses its own AMC Enabled setting and was not changed.
* Data: no migration of records. Existing cards and entitlements are not changed, nothing is
  generated again (entitlements are generated only at confirmation, cards with entitlements are
  skipped). Only cards confirmed after the change can get free services in a company whose Scope
  Mode was Warranty Only / AMC (18_4: Chicago, no cards).
* Upgrade: `warranty_management_helpdesk` 18.0.1.0.1 pre-migrate removes the obsolete condition
  from the stored arch of the ticket Pending Services button view (load order); no data change.
* Settings help (same change): every visible setting of Settings > Warranty (38) has a plain
  English description and hover help (field help; settings without a field label: `title`).
  Warranty Case Approval Required off is described as approval by any Helpdesk user (manual step),
  not as automatic approval.
* Tests: warranty_management test_warranty_scope_visibility (rewritten), test_warranty_part1
  test_17 / test_18, test_warranty_part2 test_02 / settings view / test_23,
  test_warranty_settings_fallback test_06; helpdesk test_warranty_case_scope_visibility 91 / 92
  (rewritten); fsm test_service_job_setup test_05 (rewritten), test_draft_job_from_service 171b
  (new); mrf test_settings_help (new).

## Warranty Start Date Automation (approved 2026-10-28)

Full design, decisions D1–D11 / Q1–Q18 and implementation notes: `doc/start_date_design.md`.
Summary: Delivery basis = latest actual validation of the card's own unit deliveries; Invoice
basis = actual posting time of the posted, non-reversed customer invoices covering every unit
(whole quantities, credit notes deducted, down payments excluded; invoices posted before the
automation only through a verified posting tracking, else an authorized exception);
Installation basis = original completion time of the linked installation Field Service task(s)
(new status Pending Installation, automatic confirmation). Warranty Timezone for every date;
expected dates and source references on the card; confirmed dates protected (UI / import /
API); exceptions and corrections only by the group Warranty: Date Correction, with the Warranty
Date History; Custom Date Range and Usage unchanged; existing confirmed cards unchanged.
