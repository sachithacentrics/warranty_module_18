# Part 8.6 Warranty Provision Entries: manual testing guide

Run after `warranty_management_accounting` 18.0.1.6.0 is upgraded, with your approval. Use **test customers, products and invoices**. WCAS/000042, WCAS/000049 and existing accounting documents stay untouched.

**Before upgrading:** Company 1 on UAT has provision **on** at 5%, with journal MISC and accounts 625100 and 216100. After the upgrade, every warranty sale invoice posted creates a draft entry. Turn it off in Warranty Settings if you don't want that yet.

## A. Basic entry

| # | Step | Expected |
|---|---|---|
| 1 | Provision off, post an invoice for a warranty product | No provision entry |
| 2 | Provision on, company 5%, post an invoice of 10,000 untaxed plus tax | Invoice posted. Warranty Provision button shows 1 |
| 3 | Open the entry | **Draft**. Dr Warranty Expense 500, Cr Warranty Provision 500, on the invoice date, in the configured journal. Other Info shows method, rate, level and source |
| 4 | Source Invoice button | Opens the invoice |
| 5 | Post the entry as an Accounting user | Posted. The invoice is unchanged |
| 6 | Invoice for a non-warranty product | No entry |
| 7 | Inspection or repair invoice of a warranty case | No entry |

## B. Rule levels (test product, category and policy)

| # | Setting | Expected entry on a 1,000 invoice |
|---|---|---|
| 1 | Company 5% | 50, level Company Default |
| 2 | Policy 4% | 40, level Warranty Policy |
| 3 | Category 2% | 20, level Product Category |
| 4 | Product Fixed 7, quantity 3 | 21, level Product |
| 5 | Product Use Next Level | 20 |
| 6 | Product No Provision | No entry |
| 7 | Change a rate after posting an invoice | The earlier entry keeps its amount |

## C. Source changes

| # | Step | Expected |
|---|---|---|
| 1 | Draft invoice, or cancelled invoice | No entry |
| 2 | Reset a posted invoice whose provision is draft | Draft provision removed, note on the invoice |
| 3 | Post it again | One new draft, not two |
| 4 | Post the provision, reset the invoice, post it again | Posted provision unchanged, note for Finance, no second entry |
| 5 | Provision posted, credit note for the full invoice | One **draft** reversal: Dr Provision, Cr Expense, linked to the entry, invoice and credit note. Original unchanged |
| 6 | Invoice of 2,000, provision 100, credit note 500 | Draft reversal 25 |
| 7 | Post it, second credit note 500 | A new draft reversal 25, not 50 |
| 8 | Credit notes beyond the invoice | Reversals stop at 100 |
| 9 | Raise a draft reversal above what remains, post | Refused |
| 10 | Credit note of another invoice, or not linked to any invoice | No reversal |
| 11 | Reset the credit note | Its draft reversal goes; a posted one stays, with a note |
| 12 | Cancel an invoice with a posted provision | Draft reversal of what remains |

## D. Locks and access

| # | Step | Expected |
|---|---|---|
| 1 | Fiscal lock date after the draft's date, post it | Refused; stays draft |
| 2 | Change its date to an open date, post it | Posted |
| 3 | Try a hard lock with a draft in the period | Standard Odoo refuses and lists it |
| 4 | Invoice in a foreign currency | Entry in company currency |
| 5 | Company 2 with provision off | No entry |

## E. Warranty Provision / Reserve report (Warranty > Reports; Accounting > Reporting)

| # | Step | Expected |
|---|---|---|
| 1 | After sections A and C | Provisions and Reversals show from posted entries; drafts only under Draft |
| 2 | Compare Outstanding Reserve, no filters, with the General Ledger for that account | Same amount |
| 3 | Check Utilization and Releases | 0, until Finance labels a manual entry |
| 4 | Manual entry debiting the account, labelled Reserve Release, posted | Shows under Releases |
| 5 | Same entry with no label | Shows under Other Manual |
| 6 | Label on an entry that does not debit the account, post | Refused |
| 7 | Actual Warranty Cost filter | Same total as the Warranty Cost Report; never in Outstanding Reserve |
| 8 | Filter by Warranty Policy, Product Category, Period | Only matching rows |
| 9 | User with no Accounting rights | No menu |
| 10 | Edit or delete a row | Not offered |

## F. No effect on cost

Warranty Cost tab, Warranty Cost Report and Net Warranty Cost don't change when a provision is created or posted. No stock valuation changes.
