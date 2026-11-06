# Part 8.2 Cost Consolidation and Reporting: manual testing guide

Run after `warranty_management_mrf` 18.0.1.9.9 and `warranty_management_accounting` 18.0.1.1.1 are upgraded, with your approval.

**View only, change nothing:** WCAS/000042, WCAS/000049, JOB/000036, WR/000006, VCL/00006 and its draft vendor credit note. Use **new test records** for every other step.

## A. Setup

1. **Users:** Coordinator, a Cost Approver with no other cost role, Accountant (billing) from the Part 8.1 guide.
2. **A new Field Service-only user:** on UAT `main_tech` and `support_tech` also hold a cost role, so they can read cost. They are not valid for the technician steps.
3. **Test product:** Warranty Configuration tab, Brand `GREE`, Model `9000 BTU`.
4. **A second test product** with Brand and Model empty.

## B. Protected records, view only

| # | Step | Expected |
|---|---|---|
| 1 | WCAS/000049, Warranty Cost tab | Replacement actual 200.00, once. Vendor Recovered 0.00, Net Warranty Cost 200.00 |
| 2 | Same tab, Vendor Recovery | Claimed 200.00, Recovered 0.00, Outstanding 200.00 |
| 3 | VCL/00006 and its credit note | Vendor Responded; credit note still Draft |
| 4 | WCAS/000042 and JOB/000036 | Totals show; nothing changed |

## C. Vendor recovery, on a new test case with a Done Vendor replacement of 100

| # | Step | Expected |
|---|---|---|
| 1 | Create Vendor Claim, submit | Recovered 0.00: an unapproved claim is not recovery |
| 2 | Approve, send, record vendor response 100, Create Draft Credit Note | Recovered 0.00, Net Warranty Cost 100.00: a draft is not recovery |
| 3 | Accounting: post the credit note | Claim Recovered 100.00, Outstanding 0.00; Net Warranty Cost 0.00 |
| 4 | Accounting: Reverse, then enter a reversal of 30 and post it | Recovered 70.00, Outstanding 30.00; Net Warranty Cost 30.00 |
| 5 | Warranty > Reports > Vendor Claim Recovery | The claim shows Recovered 70.00, Outstanding 30.00 |
| 6 | On a second test claim, post the credit note, then use the full Reverse | Recovered 0.00, Settled 0.00, Outstanding 100.00; credit note and allocation still listed |
| 7 | On that claim, Create Draft Credit Note again | A new draft of 100.00; Recovered stays 0.00 until posted |
| 8 | On a third test claim, reconcile the posted credit note against a vendor bill | Recovered stays 100.00, Settled 100.00: an offset is not a reversal |

For a parts claim, also check Net Warranty Material Cost rises again after step 6. A replacement claim doesn't change it.

## D. No double counting

| # | Step | Expected |
|---|---|---|
| 1 | New Component replacement with a consumed Material Request part | The part shows once under Parts; no Replacement row |
| 2 | Case with a part, timesheet, travel line and replacement | Each shows once; Total is their sum |
| 3 | Workshop labour line on a Repair Order | Summary says how much labour is manual; the report row is marked Manual Cost |
| 4 | Timesheet for an employee with no Hourly Cost | Incomplete badge on the case; the report row is marked Incomplete Labour |

## E. Cost periods (Warranty > Reports > Warranty Cost; also Accounting > Reporting)

On one new test case, use different months where you can. Backdate only your own test records.

| # | Step | Expected in the report |
|---|---|---|
| 1 | Timesheets on two different dates | Labour on each timesheet date |
| 2 | Travel and Other lines with different Cost Incurred Dates | Each on its own date |
| 3 | Subcontract line linked to a posted test bill | On the bill's accounting date |
| 4 | Credit note on that bill for part of it, in a later month | A negative on the credit note's date; total is net |
| 5 | Consume a part | On the stock move date |
| 6 | Reverse that usage on a later date | A negative on the reversal date; the first date stays |
| 7 | Done replacement | On its Replacement Date |
| 8 | Reverse a travel line | A negative on the reversal date; the original date stays |
| 9 | Group by Cost Incurred Month | Costs split across months |
| 10 | Group by Case Creation Month | All of the case in one month, same total |
| 11 | Remove all filters, filter on the case | Actual, Estimated, Approved and Net equal the case's Warranty Cost tab |
| 12 | Filter by Service Job | Totals equal the job's Warranty Cost tab |
| 13 | Update Actual Cost with a new date and a reason | The line moves to that date; the note shows the reason and date; a future date is refused |

## F. Brand and Model

**Skip this section:** by later decision, Brand and Model are hidden on the product form and in the report. The fields and data are kept.

| # | Step | Expected |
|---|---|---|
| 1 | Search the report for Brand `GREE` and Model `9000 BTU` | Only cases of the test product |
| 2 | Search for Model `12000 BTU` | No rows |
| 3 | Case of the product with empty Brand and Model | Rows show blank, no error |
| 4 | Product form of a non-warranty product | Both fields show and can stay empty |

## G. Report behaviour

| # | Step | Expected |
|---|---|---|
| 1 | Try to edit, create or delete a row | Not offered |
| 2 | Change a cost, press Refresh | New figure shows |
| 3 | Click a row | Opens the warranty case |
| 4 | Filter by Product, Main Technician, Failure Category | Only matching rows |

## H. Access and companies

| # | Step | Expected |
|---|---|---|
| 1 | New Field Service-only user | No report menu, and no cost tab on cases or jobs |
| 2 | Accountant login | Report opens; read only |
| 3 | Cost Approver login | Report opens, only for the company they approve for |
| 4 | Remove that user from Cost Approvers, log in again | Menu gone |
| 5 | User with Company 2 selected only | No Company 1 cost or recovery rows |

## I. Regression

| # | Step | Expected |
|---|---|---|
| 1 | Part 8.1 guide, section C, steps 1-7 | Same results, with Update Actual Cost also asking for the date |
| 2 | Journal entry and stock valuation counts before and after opening the report | Opening the report adds nothing |
