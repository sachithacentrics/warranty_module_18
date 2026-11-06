# Part 8.6 Warranty Provision Entries: decision record

Module `warranty_management_accounting` 18.0.1.6.0. SRS 1.1, 15, 17; mapping rows 11, 12, 14, D1, D3, D5, D17, decision P1, and your decisions R1, F1, F2, F4, F8 of 2026-11-04.

## Built

When a customer invoice posts, for a company with provision on: one **draft** journal entry per warranty sale line, for Finance to post.

| Item | Rule | Source |
| --- | --- | --- |
| Event | Customer invoice posted | D1 |
| Debit | Warranty Expense Account | SRS 17 |
| Credit | Warranty Provision / Reserve Account | SRS 17, P2 |
| Journal | Warranty Accounting Journal | Part 8.3 |
| Date | The invoice's accounting date | D1 |
| State | Draft; never posted automatically | D3 |
| Fixed | Quantity in the product's unit x amount | P1 |
| Percentage | Line's untaxed value, in company currency | D1 |
| Rule | Product, category, warranty policy, company | D17 |
| Policy level | The sale line's selected policy, the same one its warranty card uses; otherwise the product's applied policy | Existing Part 1 resolution |

**A warranty sale line is:** a product line of a Warranty Applicable product. **Not a warranty sale:** down payments, work billed on a warranty case (inspection, repair, excluded items), Material Request parts, backup charges, AMC orders, a credit note, or a reversal of a credit note.

**No new model:** the planned `warranty.provision.entry` wasn't needed. The entry's own fields hold its invoice, invoice line, method, rate or amount, level and source, so a later rule change never alters it. Warranty cards show through the sales order.

## Controls

| Risk | Control |
| --- | --- |
| Duplicate | One active entry per invoice line, enforced by a database unique index |
| Invoice reset to draft or cancelled | Its **draft** provision is removed, and created again if the invoice posts again |
| Invoice reset after its provision was posted | The posted entry is unchanged and noted for Finance; posting again creates no second one |
| Credit note | A linked draft reversal, see below |
| Locked period | Posting a provision into a fiscal or hard locked period is refused, and it stays draft. Finance changes its date. Standard Odoo posting would not recheck this |
| Hard lock | Standard Odoo refuses a hard lock while drafts exist in the period |
| Company and currency | Accounts and journal of the invoice's company; amounts in its currency |
| Provision off, or No Provision | Nothing created |
| A problem creating the entry | The invoice still posts, and a note goes on it for Finance |
| Link fields | Server-side guard; can't be changed through RPC |
| Permissions | Standard: created as the checked result of posting an invoice; posted by users with Accounting rights |
| Operational cost | No cost line, report row or cost total is touched. Warranty Cost remains the operational view |

## Accounting event matrix

| Event | Entry | Status |
| --- | --- | --- |
| Customer invoice posted | Draft: Dr Warranty Expense, Cr Warranty Provision | **Built** |
| Invoice reset, provision still draft | Draft removed | **Built** (D5 table) |
| Invoice reset, provision posted | None; note for Finance | **Built** |
| Credit note linked to the invoice posted | Draft reversal, proportional and capped | **Built** (R1) |
| Invoice cancelled | Draft reversal of what remains | **Built** (R1) |
| Credit note reset, its reversal draft | Draft removed | **Built** |
| Credit note reset, its reversal posted | None; note for Finance | **Built** |
| Parts consumed | None | F1: B1, operational only |
| Reserve utilization (C, D) | None | F4: pending confirmation of the expense recognition |
| Unused reserve release | None automatic | F8: manual journal by Finance |

## Example

Invoice 10,000 untaxed plus tax, rule 5%, on the invoice date:

| Account | Debit | Credit |
| --- | --- | --- |
| Warranty Expense | 500 | |
| Warranty Provision / Reserve | | 500 |

Fixed amount 20 per unit, quantity 3: Dr 60, Cr 60.

## Provision reversal (R1)

| Rule | Implementation |
| --- | --- |
| Event | A posted credit note linked to the invoice (`reversed_entry_id`), or the invoice cancelled |
| Entry | Draft: Dr Warranty Provision, Cr Warranty Expense, on the original entry's accounts and journal, linked to it |
| Date | The credit note's accounting date; today for a cancellation |
| Amount | Share of the product's invoiced value refunded, cumulative, minus reversals already made |
| Several credit notes | Each creates only the difference |
| Cap | Never above the provision, also when Finance edits a draft: posting above what remains is refused |
| Still-draft provision | No reversal until Finance posts it, then it catches up |
| Unrelated credit note | Ignored: not linked to the invoice, or another product |
| Original entry | Never modified or reversed automatically |
| Locks | Same check as the provision: refused in a locked period, stays draft |

**Example:** provision 100 on an invoice of 2,000. Credit note 500 gives a draft reversal of 25. A second credit note of 500 gives another 25. Refunding more than was invoiced stops at 100.

## Warranty Provision / Reserve report (SRS 15, row 14)

Warranty > Reports and Accounting > Reporting, for Accounting users. Read-only, rebuilt when opened, filtered by policy, product category and period.

| Column | Comes from |
| --- | --- |
| Provisions | Posted provision entries |
| Reversals | Posted reversals, including a standard Odoo reversal of a provision |
| Utilization, Releases | Posted manual entries debiting the reserve that **Finance labelled**. Nothing is inferred |
| Other Manual | Any other posted item on the account, unclassified |
| Outstanding Reserve | Credits minus debits of posted items; the total equals the account's posted balance |
| Draft | Unposted entries, shown and not counted |
| Actual Warranty Cost | Operational figures from the Warranty Cost Report, as separate rows, never netted into the reserve |

**The label:** Warranty Reserve Movement on a manual journal entry, set before posting. Posting refuses it unless the entry debits the provision account.

**Filters and manual entries:** a manual entry has no product or policy, so filtering by policy or category shows only the provision side. Outstanding Reserve is complete only without those filters.

## Finance decisions

| # | Decision | Status |
| --- | --- | --- |
| R1 | Draft reversal on credit note or cancellation | **Approved, built** |
| F1 | Parts route | **B1 for UAT.** No stock valuation change, no reclassification |
| F4 | Reserve utilization | **Not automatic.** Pending confirmation of expense recognition |
| F8 | Reserve release | **Manual, by Finance** |
| F2 | Accounts | **UAT accounts kept for testing.** Production mapping needs Finance sign-off |
| F7 | Thresholds and approvers | Configuration only |

## Known limits

- **Direct invoices:** a warranty product invoiced with no sales order also creates a provision, because D1 says posted customer invoice.
- **Old invoices:** existing invoices get nothing. If one is reset and posted again with provision on, it counts as a new event and creates a provision (D1 says nothing retroactive, so Accounting should avoid this).
- **Draft entries are per line:** an invoice with many warranty lines gives Finance many entries, as row 11 specifies.
- **Finding drafts:** use the report's Draft Entries filter, or the invoice's Warranty Provision button.
- **Credit notes entered without the invoice link** can't be detected, so they give no reversal.
- **Different prices on one credit note:** lines of the same product share a refund by value, because a credit note line has no link to one invoice line.
- **Reset invoices:** resetting alone gives no reversal, because it may be a correction. Cancelling it does.
- **Report snapshot:** use Refresh for the latest figures. Actual cost rows use cost dates and the case's card policy.
- **SRS gaps:** customer notification (row 18, D15) stays open. Part 8 isn't fully closed.
