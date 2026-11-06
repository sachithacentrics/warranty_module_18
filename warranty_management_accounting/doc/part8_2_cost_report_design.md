# Part 8.2 Cost Consolidation and Reporting: decision record

Module `warranty_management_accounting` 18.0.1.1.1, with `warranty_management_mrf` 18.0.1.9.9 for the recovery rule. Mapping rows 4, 33, 37, 40, 42, 43, in `Part8_Cost_Accounting_Mapping.md` revision 2. Part 8.2 posts no journal entry.

## Figures

| Figure | Source | Rule |
| --- | --- | --- |
| Parts | Material Request lines, `_cost_totals` | Unchanged from 8.1. Covered and Goodwill actual; customer-paid stays out |
| Labour | Visit timesheets, shared visits split (D7), approved workshop lines | Unchanged from 8.1. Manual labour is shown separately |
| Travel, Other | Approved cost lines | Unchanged from 8.1 |
| Subcontract | Linked purchase or bill line | Unchanged from 8.1 |
| Replacement | `replacement_cost` of Done replacements of the case | Counted once. Component type is never read: its part counts as Parts |
| Vendor Recovered | Existing `vendor_recovered_amount` | See the recovery rule below |
| Net Warranty Cost | Total Actual Cost minus Vendor Recovered | New field `warranty_net_cost` |
| Net Warranty Material Cost | Existing field | Unchanged, except that a reversed credit note no longer counts |

## Recovery rule (approved correction)

A credit note counts as recovered when it is posted. Each posted reversal linked to it through `reversed_entry_id` reduces its recovery in proportion:

`Recovered = allocated amount x (1 - reversed amount / credit note total)`

| Situation | Recovered |
| --- | --- |
| Draft or cancelled credit note | 0 |
| Posted credit note | The allocated amount |
| Fully reversed | 0 |
| Reversed for 30 of 100 | 70 |
| Draft reversal | Not counted yet |
| Reversal that is itself reversed | Restored |
| Vendor bill or refund reconciled against the note | Unchanged: this is settlement, not reversal |
| Payment state Reversed with no linked reversal (existing rule) | 0 |

**Why not the payment state:** Odoo's standard Reverse on a vendor credit note creates a vendor bill and leaves the note Paid, the same state as a real settlement.

**Where it lives:** `warranty_management_mrf`, in `warranty.vendor.claim.recovery._compute_effect` and `ALLOCATION_SQL`, because every recovery figure and the Part 5 reports read from there.

**Follow-on effects:**

- Settled excludes the reversed share.
- Allocated becomes net of reversals, so Create Draft Credit Note can recover the amount again. Without this the claim would show an outstanding amount it could not recover.
- Nothing is posted, cancelled, reversed or reconciled. Allocations and credit notes are not changed.

## Effective date of each cost

Actual cost is dated by when it was incurred. A reversal never edits the earlier period: it shows as a negative on its own date.

| Cost | Actual is dated by | Reversal or adjustment | Estimated and Approved are dated by |
| --- | --- | --- | --- |
| Parts | Date of the done stock move, company local date | Usage reversal: negative on its Reversed On date. Customer return: negative on the return move date | Material Request date |
| Labour, visit | Timesheet date | Editing a timesheet changes its own date | Date of the Labour cost line |
| Labour, workshop | Cost Incurred Date of the cost line | Line reversal: negative on its Reversed On date | Same date |
| Travel, Other | Cost Incurred Date of the cost line | Line reversal: negative on its Reversed On date | Same date |
| Subcontract, bill link | Accounting date of the bill | Credit note: negative on its accounting date. Line reversal: negative on its Reversed On date | Date of the cost line |
| Subcontract, purchase link | Accounting date of each posted bill | Credit notes linked to the purchase line: negative on their dates | Date of the cost line |
| Replacement | Replacement Date (delivery) | None exists in Part 7 | Same date |
| Vendor Recovered | Accounting date of the credit note | Reversal: negative on its accounting date, in proportion | Not applicable |

**Cost line date:** new optional field Cost Incurred Date on manual lines. A new line starts with today; it can be changed in Draft or through Update Actual Cost, and a future date is refused there. Lines from before this field stay empty and use the final approval date, so no existing record is written.

**Why dates cannot change totals:** each source is split by date, then fitted to the figure the case and job already show. A rounding difference goes to the latest date. Period rows always add up to the case and job totals.

The Case Creation Date stays available as a separate filter and group.

## Brand and Model

Inspected the product master, product attributes and the fields on UAT: nothing equivalent exists, and the product `brand` attribute is unused. Two optional text fields, `warranty_brand` and `warranty_model`, are on the product's Warranty Configuration tab, for all products. Existing products stay empty, and the report reads the current product values each time it opens.

## Other decisions

| # | Decision | Reason |
| --- | --- | --- |
| R1 | A replacement has no estimate or approved amount of its own. Once Done, Estimated and Approved show its cost; before that it adds 0 and the summary names it as not delivered | Inventing an estimate from the product cost would add a figure no one approved |
| R2 | A Done replacement without a stock valuation shows as Unverified and stays out of Total Actual | Same rule as parts (H-3): an estimate is not a verified actual |
| R3 | Replacement cost is on the case only, not on a job | A replacement record has no job link |
| R4 | The D9 expected cost gate does not include replacement cost | D9 defines the total as Material Requests plus cost lines. Replacements have their own approval |
| R5 | The report rows are rebuilt from Python when the report opens, not an SQL view | Labour shares, rounding and bill refunds are calculated in Python. Repeating them in SQL could disagree with the case |
| R8 | Technician is the job's main technician | One row has one technician. Support technicians are not filterable |
| R9 | Named approvers without another cost role reach the report through a hidden group kept in step with the company settings | Approvers are a setting, not a group, and menus need a group. The companies are checked again each time the report opens |

## Access

| User | Report | Companies |
| --- | --- | --- |
| Coordinator, requisition user, accountant (read-only or billing) | Read | Their selected companies |
| Named Cost or Finance Approver with no other cost role | Read | Only the selected companies they approve for |
| Technician (Field Service only), other internal users | Refused | None |

Nobody can create, edit or delete a row through the interface or RPC; only the rebuild does, in sudo, and it removes the user's own earlier rows only. Rows are visible only to the user they were built for. They are removed by the standard transient cleanup after 24 hours.

## Known limits

- **Update Actual Cost:** the line holds one actual and one date, so an update moves the whole actual to the date entered. The old value and date stay in the audit notes.
- **Editing old sources:** editing a timesheet or changing a Cost Incurred Date restates that period. Locked accounting periods don't apply to these operational figures.
- **Report snapshot:** use Refresh or reopen for the latest figures. On a very large database, opening takes longer because each case is calculated.
- **Recovery on jobs:** job totals can be below the case's, because a replacement claim and any pre-5.9 claim-level allocation belong to the case only.
- **Closed claims:** a claim closed before its credit note is reversed stays closed with outstanding 0. Recovered falls, and Accounting must follow up, because closed claims have no reopen action.
- **Allocated amount versus credit note:** F6 stays open. Recovery counts the allocated amount, not the note's amount if a draft was edited before posting.
- **Credit notes outside the claim:** a reversal is only recognised through the link Odoo sets. A manual entry with no link and no reconciliation is not detected.
- **Rounding:** when one credit note covers several claim lines, a partial reversal rounds per line, so totals can differ by the smallest currency unit from the note's share.
- **Brand and Model are free text:** `GREE` and `Gree` group separately, though filtering ignores case.
- **Blank data:** failure category is mostly empty on existing UAT cases, and 9 cases have no product or serial, so those rows show no product, brand or model.
- **Replacement cost:** the value of the returned unit is not deducted (existing Part 7 rule).
