# Part 8.5 Warranty Case Closure: manual testing guide

Run after `warranty_management_accounting` 18.0.1.4.0 is upgraded, with your approval. Nothing here should post, pay, reconcile or close a vendor claim.

**Don't close:** WCAS/000042 or WCAS/000049. Use **new test cases**. Closing can't be undone until Part 9.

The action is **Close Case** on a Completed warranty case, for Helpdesk users.

## A. Warranty repair

| # | Step | Expected |
|---|---|---|
| 1 | Approved case, no job finished | No Close Case button |
| 2 | Complete the job, Close Case | Closed. Closed by and on show; a chatter note is added |
| 3 | Refresh | No button; status can't change |

## B. Blockers, on a test case with each item open

| # | Open item | Expected message |
|---|---|---|
| 1 | Material Request not closed | Names the request, its obligations, or "ready to close" |
| 2 | Run Close Material Requests, retry | Closes |
| 3 | Repair Order not done or machine not returned | Names the Repair Order |
| 4 | Replacement draft or submitted | Names the replacement |
| 5 | Cost line draft or submitted | Names the line |
| 6 | Several at once | All listed together |

## C. Customer declines

| # | Step | Expected |
|---|---|---|
| 1 | Customer Declined Repair, inspection not invoiced, Close Case | Refused: order not invoiced and posted |
| 2 | Draft inspection invoice, Close Case | Refused |
| 3 | Post the invoice, Close Case | Closed. No credit note, no deduction, fee unchanged |

## D. Chargeable repair

| # | Step | Expected |
|---|---|---|
| 1 | Repair job done, repair not invoiced, Close Case | Refused: repair order not invoiced |
| 2 | Post the repair invoice, Close Case | Refused: apply the inspection fee adjustment |
| 3 | Apply: draft credit note, Close Case | Refused: Accounting must post it |
| 4 | Post the credit note, Close Case | Closed. Invoice can stay unpaid |
| 5 | New case with quotation deduction, inspection order not invoiced | Refused until the inspection invoice is posted |
| 6 | New case with fee above repair total | Refused, mentions F5 |

## E. Vendor claims

| # | Step | Expected |
|---|---|---|
| 1 | Completed case with an open claim, Close Case | Closed; the claim stays open and can continue |

## F. Rights

| # | Step | Expected |
|---|---|---|
| 1 | User without Helpdesk rights | No button |
| 2 | Case of another company | Not reachable |

## G. Regression

Warranty Cost tab and report figures, credit note and deduction workflows, and vendor recovery figures don't change when a case closes.
