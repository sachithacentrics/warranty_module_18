# Part 8.4 Inspection Fee Adjustment: manual testing guide

Run after `warranty_management_accounting` 18.0.1.3.1 is upgraded, with your approval.

**View only, change nothing:** WCAS/000042, WCAS/000049, JOB/000036, WR/000006, VCL/00006 and its draft credit note. Use **new test cases** for every step.

## Setup

1. **Helpdesk team:** Inspection Product and Amount as now. Set an **Inspection Deduction Product**: a service, invoiced on ordered quantities.
2. **Users:** a Billing user, a named Cost Approver, a Helpdesk user with neither role, and a new Field Service-only user.
3. **Each test case:** run a chargeable inspection through to Repair Required. That gives a confirmed inspection order, a completed inspection job and a draft repair quotation. Price the repair above the fee.

The action is **Apply Inspection Fee Adjustment** on the warranty case. The status is on the **Warranty Cost** tab.

## A. Inspection invoice posted

| # | Step | Expected |
|---|---|---|
| 1 | Post the inspection invoice, leave the repair unconfirmed, apply | Refused: confirm the repair first |
| 2 | Confirm the repair, apply as Billing user | Opens one **Draft** credit note: same customer and tax, fee amount, reference to the invoice and case. Status Draft Credit Note |
| 3 | Apply again | Button gone; through any other route, refused |
| 4 | Check Accounting | Credit note not posted, no payment, nothing reconciled, invoice unchanged |
| 5 | Raise the credit note above the fee, post | Refused |
| 6 | Restore the amount, post | Status Posted Credit Note. Accounting reconciles it by company policy |
| 7 | Repeat on new cases with the invoice unpaid, part-paid and paid | One draft each time; nothing reconciled |
| 8 | Open the inspection order after step 6, Create Invoice | Not offered as To Invoice; refused if forced, so the fee isn't charged again |
| 9 | Add a different product to that order, invoice it | Only the new line is invoiced |

## B. No posted inspection invoice

| # | Step | Expected |
|---|---|---|
| 1 | Leave no invoice or a draft one, apply as Cost Approver | No credit note. One negative line on the repair quotation with the fee's tax. Status Repair Quotation Adjustment |
| 2 | Check the total, 5,000 repair and 1,500 fee, both 15% tax | Untaxed 3,500, tax 525, total 4,025 |
| 3 | Apply again | Refused |
| 4 | Edit the deduction line's price as a Sales user | Refused |
| 5 | Delete the line, apply again | One line again |
| 6 | Post the inspection invoice, apply again | Refused: no second benefit |
| 7 | Confirm the repair and create its invoice | Invoice total 4,025; it stays draft |
| 8 | New case: no Deduction Product on the team | Refused, naming the team |
| 9 | Duplicate a repair quotation that has a deduction | The copy has the other lines, no negative line; applying again is refused |

## C. Customer declines

| # | Step | Expected |
|---|---|---|
| 1 | Customer Declined Repair on a case with a posted inspection invoice | Button gone; the invoice is unchanged and the fee stays |
| 2 | Same, on a case with a quotation deduction | Quotation cancelled, deduction gone |
| 3 | Decline after a draft credit note exists (only possible if the repair order was cancelled) | Refused until Accounting removes the note |

## D. Limits

| # | Step | Expected |
|---|---|---|
| 1 | Repair priced below the fee, either route | Refused with the amounts, mentioning F5. Nothing created |
| 2 | Repair not priced | Same refusal |
| 3 | Inspection invoice already has a credit note | Refused |

## E. Rights and companies

| # | Step | Expected |
|---|---|---|
| 1 | Helpdesk user with no Billing or approver role | No button |
| 2 | Field Service-only user | No button, no status |
| 3 | Case of another company | Not reachable |

## F. Regression

Inspection quotation, send To-Do, job on confirmation or payment, inspection result, repair quotation, Warranty Cost Report and Warranty Settings all behave as before.
