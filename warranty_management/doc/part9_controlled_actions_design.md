# Part 9 Controlled Actions and Warranty History: technical design record

Developed 2026-11-05 on disposable databases. **Not on UAT.** Scope and decisions: `Part9_History_Exceptions_Mapping.md`. Test results: `part9_test_report.md`.

| Module | Version |
| --- | --- |
| `warranty_management` | 18.0.1.2.0 |
| `warranty_management_helpdesk` | 18.0.1.2.0 |
| `warranty_management_fsm` | 18.0.1.4.0 |
| `warranty_management_mrp` | 18.0.1.0.2 |
| `warranty_management_mrf` | 18.0.1.9.11 |
| `warranty_management_repair` | 18.0.1.5.0 |
| `warranty_management_accounting`, `amc_management` | Unchanged |

No migration script is needed: changes add empty columns, new tables and one view. New settings take their defaults.

## 1. Field protection (SRS 13)

`warranty.card.write` and `warranty.unit.write` refuse protected fields after confirmation. Status can't be set directly at any stage.

- **Covers:** forms, import and RPC, which never run as superuser.
- **Card fields:** customer, product, serials, policy and its source, pricelist, company, sale order, basis, duration, usage values, free services allowed, original end date, status.
- **Unit fields:** card, sale line, product, number, move line, serials, usage values, current site, original end date, usage correction, status.
- **Unchanged values:** allowed, so a re-import of the same value isn't refused.
- **Open cards and Draft units:** stay editable, apart from status.
- **System code:** `sudo()` and `_warranty_system_write` still pass. Expiry and restore now use the protected path, so they work for normal users during a date correction.

Direct writes from server code running under `sudo()` are not blocked. This is deliberate, to preserve Parts 1-8 workflows, and no method passes client values into such a write.

## 2. Controlled action (SRS 12)

`warranty.card.action` (`WCA/00001`) holds one exception. All types share one record and one wizard.

```
Controlled Action button -> wizard -> Waiting for Approval -> Approve and Apply -> Approved and Applied
                                                           -> Reject (reason)   -> Rejected
```

- **Request:** `warranty.card._warranty_request_action`. Validates, creates the record, sends an activity to approvers and logs a chatter note.
- **Approval:** `action_approve` checks the approver, runs validations again, executes, and stores previous and new values.
- **Separation of duties:** requesters can't decide their own requests.
- **Approvers:** company setting Warranty Exception Approvers. It's empty by default, so no request can be made until it's set (provisional, Q1).
- **Duplicates:** one waiting action per card, also enforced by the partial unique index `warranty_card_action_one_pending`.
- **Protection:** no write, create or delete rights for users; decided records can't change; nothing can be deleted.
- **Evidence:** only attachments uploaded by the requester for this request are accepted.
- **Isolation:** company rule on actions and history.

## 3. Action types

| Type | Allowed on | Effect | Never changes |
| --- | --- | --- | --- |
| Suspend | Confirmed card, Active units | Units Suspended; card Suspended when no unit is Active | Dates, cases, jobs, services, stock, accounting |
| Reactivate | Suspended units | Units Active; card follows | As above |
| Cancel | Confirmed, Suspended or Expired card, with a validated return or posted credit note of those units | Units Cancelled; card Cancelled when none remain | Sale, delivery, invoice, credit note, provision, services |
| Correct Serial | One non-kit unit, no open work, serial of the same product and not on another live unit | Serial replaced; PDF regenerated | Delivery move lines |
| Correct Customer | No open work | Card customer and unit site changed; PDF regenerated | Sale, invoices, old tickets |
| Correct Usage | One unit of a usage-based card | New baseline for the usage check | Case readings |
| Relocate | Live units, site of the same customer | Current site changed | Dates, old cases |
| Transfer | Confirmed card, whole card, no open work, date and document required | Same as customer change | Dates, sale, invoices, old tickets; free services stay on the card |
| Extend | Period-based Confirmed or Expired card; new end after the current end; paid needs its quotation or invoice | End dates moved, originals kept, date log written, Expired restored, PDF regenerated | Free services, accounting |

**Open work** is open cases, open jobs, draft to approved replacements, and backup units at the customer. It's shown when requesting. It blocks correction and transfer. Suspension doesn't block or change it.

## 4. Status effects at existing gates

- Eligibility reads unit status: a Suspended or Cancelled unit gives Not Eligible, on both complaint and free service paths.
- Job confirmation revalidates through the same check (existing Q41).
- Pending services, draft jobs and alerts already need a Confirmed card.
- Replacement already blocks Suspended and Cancelled.
- Expiry reads Confirmed cards and Active units only, so suspension doesn't extend or expire anything. After reactivation, the next daily run expires units past their end date.

## 5. Duplicate prevention (SRS 12 #25)

A serial can't be on two units in Draft, Active or Suspended status. Only serial-tracked products are checked; lot-tracked products may share a lot. It runs on client writes and at confirmation. Kit units use the existing K4 check on write, which allows a swap in one save, and the common check at confirmation.

Note: Expired units don't hold a serial (Q5).

## 6. Site (SRS 12 #4)

`warranty.unit.current_site_id` is read by `_warranty_service_address`. Empty means the delivery address of the sale, so behaviour is unchanged for existing data. Case site checks, free service site matching and draft jobs read it. For a card with several units at different sites, free service paths read the first unit, because services belong to the card.

## 7. Repeat complaint (SRS 12 #22)

Repeat Complaint on a Completed or Closed case opens a new case form with the type, card, unit, serial, items and links filled in. `repeat_of_case_id` and `repeat_of_job_id` record the links. The original stays untouched. Only one open repeat per case is allowed. The previous case must be on the same card. No free service is consumed, because only Free Service cases use one. The existing repeated failure count includes these cases.

## 8. History (SRS 2.13, 15)

`warranty.history` is a read-only database view over existing records; nothing is copied. Each module adds its records through `_warranty_history_queries`.

**Included:** card creation, controlled actions, date log, service due date and schedule logs, PDF downloads, invoices and credit notes of the card's sale lines, cases, jobs, material requests, repairs, replacements, backup units, vendor claims and their credit notes.

**Smart buttons:** Card (with count), Unit, Sales Order, Helpdesk Ticket, Case, Job. **Menu:** Warranty > Warranty Cards > Warranty History.

**Limit:** cases, jobs and similar rows show their creation and current status, not each status change; those stay in each record's chatter. Worksheets and journal entries other than invoices, credit notes and vendor credit notes aren't listed (Q4).

## 9. Not built

Void (Q7), extended warranty product (Q21, Q23), reopening closed cases (Q25), repeat window (Q24), single-unit transfer (Q18), "free services don't transfer" (Q19), branch, territory and technician rules (Q16), policy and product correction (Q13), kit serial correction (Q30), customer notification (D15).
