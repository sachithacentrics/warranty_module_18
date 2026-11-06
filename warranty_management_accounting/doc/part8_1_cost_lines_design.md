# Part 8.1 Warranty Cost Lines: decision record

Module `warranty_management_accounting` 18.0.1.0.1. Approved 2026-11-04, from `Part8_Cost_Accounting_Mapping.md` revision 2, with the review corrections of the same day. Manual UAT is pending.

**No journal entries.** Part 8.1 only reads timesheet, purchase, vendor bill and stock records. Provision and reserve accounting are later stages.

## SRS coverage

| Requirement | SRS | As built |
| --- | --- | --- |
| Warranty Cost Lines | 5 | `warranty.cost.line`, sequence `WCL/` |
| Labour, travel, subcontract and approved other cost | 2.10 | Cost types Labour, Travel, Subcontract, Other |
| Estimated vs approved vs actual | 2.10, Figure 7 | Totals by type on case and job, including parts from the existing fields |
| Unplanned cost approval by amount | 16.1 | Manager always; Finance by the total expected cost |
| Total expected cost blocks job and material issue | 2.10, 13, 14 | Optional gate, off by default |
| Actual cost locked from purchase and subcontract records; manual cost needs an audit reason | 17 | Subcontract actual is read from the record; manual actual needs a reason |
| Cost allocated to case and job | 17 | Timesheet labour by visit; equal split on shared visits |
| Update cost on job completion and closure | 9.11, 14 | Totals are computed live |
| Audit trail | 2.13, 16 | Tracked fields, plus notes on line, case, and job or Repair Order |
| Accountant views cost; technicians do not | 16, H-11 | Record rules and field groups |

## Decisions

| Topic | Decision |
| --- | --- |
| Labour actual | Visit timesheets at their stored amount, company currency. Never written |
| Labour line on a visit | An estimate only. A manual actual is refused, so timesheets are not counted twice |
| Workshop labour | A Labour line linked to a Repair Order holds a manual actual |
| Line scope | Case required; one service job or one Repair Order, not both. No separate visit link: 16.1 adds cost to the job or case, and visit labour comes from timesheets |
| Shared visits | Equal split across jobs that are not cancelled. The last job takes the rounding, so shares add up to the visit total |
| Subcontract source | One posted vendor bill line, or one confirmed purchase order line. A purchase line shows its commitment, and its actual comes from posted bills |
| Refused sources | Stockable products and Material Request purchases, because parts cost already counts them; other companies; draft bills |
| Duplicates | Refused with a message before saving, including a bill of an already linked purchase line. Partial unique indexes remain as the backstop. A rejected or reversed line frees its link |
| Who links a source | Billing and Purchase users, who can read those records. They may change only the link fields |
| Approval | Named Cost Approvers and Finance Approvers per company. The requester and submitter cannot approve, and one person cannot approve both levels |
| Finance threshold 0 | Turns the additional Finance level off (user decision). The Manager approval stays mandatory, as do Material Request and Service Job approvals |
| Missing hourly cost | Timesheet hours with no cost show an Incomplete badge on Labour and Total, and a warning naming the employees. Timesheets and employees are never changed |
| Partial vendor refund | Posted credit notes of the linked bill reduce the actual, with a warning on the line. The approved figure is kept. Credit note lines are matched by product and account, and split by amount across matching bill lines. A purchase line link nets its refunds through the bill lines |
| Finance after submission | Rechecked at approval, in case the case total rose |
| Counting | Actual and approved count only once a line is Approved. A reversed bill stops counting and flags the line |
| Record Actual | On approved manual lines, within the approved amount, with a reason. A higher cost needs reversal and a new line |
| Reversal | Cost approvers only, with a reason. All figures stay on the line. Never deleted |

## Expected cost gate

- Off by default (`warranty_cost_gate_enabled`), until F7 is configured.
- **Total expected:** active Material Request lines (excluding customer-paid), the larger of labour estimates and timesheets, and other non-rejected lines.
- **When enabled and above the threshold:** job confirmation (`_warranty_confirm_problems`, which also covers shared visits), next-visit planning (`_warranty_plan_next_visit`) and material release (`_warranty_release_error`) are refused while a cost line or Material Request of the case is unapproved.
- **Threshold 0:** any expected cost is checked; it never bypasses the gate.
- **Not retroactive:** approved records never block, and confirmed jobs are not reversed.

## Known limits

| Limit | Effect |
| --- | --- |
| Timesheets directly on a ticket | Not counted; only visit timesheets are. UAT has none on warranty cases |
| Credit note entered without a link to the bill | Cannot be detected, so the actual is not reduced. Use the bill's Credit Note action |
| Credit note on another product or account than the bill line | Not matched to that line |
| Replacement cost | Added to totals in Part 8.2 |
| Accounting menu and Warranty Cost Report | Part 8.2 |
