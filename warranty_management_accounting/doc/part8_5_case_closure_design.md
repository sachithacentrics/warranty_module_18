# Part 8.5 Warranty Case Closure: decision record

Module `warranty_management_accounting` 18.0.1.4.0. SRS 2.11, 9.7 steps 8-9, 9.11, 10.4, Figure 3, 13, 14, 16; mapping rows 21, 22 and D11. No new state, model, menu or wizard, and no new approval level.

## Reused

| Existing | Use |
| --- | --- |
| Case state Closed, Completed | The action moves Completed to Closed |
| `open_service_job_id`, job and visit states | Pending jobs and visits |
| `_warranty_check_requests_closed` (K-6) | Material Requests, with its open obligations and "ready to close" list |
| `_warranty_active_repairs`, `_warranty_replacement_covers` | Repair Orders |
| `_warranty_replacement_problems` | Replacements |
| `_warranty_inspection_effective`, `_warranty_inspection_adjustment_plan` (8.4) | The inspection fee adjustment, with its refusal reasons |
| `qty_invoiced_posted` (standard Sales) | Billing |

## Closure validation matrix

Every blocker is listed at once.

| Check | Warranty repair or free service | Declined repair | Inspection only | Chargeable repair completed |
| --- | --- | --- | --- | --- |
| Case is Completed, with a Case Type | Required | Required | Required | Required |
| Service jobs and visits finished | Required | Required | Required | Required |
| Linked free services finished | Required | Required | Required | Required |
| Material Requests closed (K-6) | Required | Required | Required | Required |
| Repair Orders done, machine returned or replaced | Required | Required | Required | Required |
| Replacements finished | Required | Required | Required | Required |
| Cost lines not draft or waiting approval | Required | Required | Required | Required |
| Inspection fee invoiced and posted | Not applicable | **Required** | **Required** | Required, unless credited |
| Repair invoiced and posted | Not applicable | **Not required** | Not applicable | **Required** |
| Inspection fee adjustment applied, credit note posted | Not applicable | **Refused, fee stays** | **Refused, fee stays** | **Required** |
| Customer payment | Not required | Not required | Not required | Not required |
| Vendor claims | **Never block** | **Never block** | **Never block** | **Never block** |

**Billing means:** a confirmed order with a chargeable purpose, or an excluded-item line, is invoiced and posted for its full quantity. Zero-priced lines and down payment lines don't count. A chargeable quotation still draft or sent must be confirmed or cancelled. Customer-paid parts follow the existing Material Request setting, and backup charges follow their own record, so neither blocks twice.

**Fee above the repair total:** closure is blocked with the 8.4 message, and the case stays pending Finance (F5).

## Audit and security

- **Who:** Helpdesk users, the same role that completes cases. No new approval level. The SRS names no closure role, so this follows the existing completion rule.
- **Recorded:** Closed By, Closed On and a chatter note. No reason is required, because neither the SRS nor an approved decision asks for one.
- **Server side:** `state = closed` and the closure fields can be written only through Close Case, also through sudo and RPC. Only the system itself is exempt.
- **Duplicates:** the case row is locked during the action. A closed case is refused with no second event.
- **No reopen:** a closed case can't change status. Controlled reopening belongs to Part 9.

## Conflict found and resolved by keeping the implemented rule

| Source | Says |
| --- | --- |
| `part5_9_closure_audit_reporting_design.md`, K-6 row | Reconciled requests close automatically with the case |
| `part5_design_decisions.md`, later, and the code and its tests | Closure is refused, listing requests ready to close; the user runs Close Material Requests |

The later rule is kept: no request is closed automatically.

## Known limits and SRS gaps

- **Customer notification (row 18, D15):** mandatory in the SRS and still not implemented. Close Case doesn't check for it, and the SRS isn't fully closed until it is built.
- **Helpdesk ticket:** it stays open when the case closes. No approved decision closes it.
- **Backup units:** a backup still with the customer doesn't block closure. It has its own lifecycle, and Part 6.3 decisions D3 and D9 are open.
- **After closure:** a posted credit note or invoice can still be reversed in Accounting, and a vendor claim continues. The closed case isn't reopened.
- **SRS 9.11:** the section is a process diagram with no text; the checks follow the diagrams, the SRS 2.11 and 9.7 text and D11.
- **Existing data:** cases completed before this stage go through the same checks, so some stay blocked until their billing is finished.
