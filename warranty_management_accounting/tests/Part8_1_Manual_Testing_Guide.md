# Part 8.1 Warranty Cost Lines: manual testing guide

Run after `warranty_management_accounting` is installed, with your approval. Version 18.0.1.0.1.

Use **new test records**. WCAS/000049, WR/000006, VCL/00006 and its draft vendor credit note stay untouched.

## A. Setup

1. **Users:** a Coordinator with Helpdesk rights, a Cost Approver, a Finance Approver and a Billing user. A Technician with Field Service rights only.
2. **Settings > Warranty > Warranty Cost:** set Cost Approvers, Finance Approvers, and Finance Threshold 1,000. Leave the Expected Cost Approval Gate **off**.
3. **Employee:** give the technician's employee an Hourly Cost of 50.

## B. Labour

| # | Step | Expected |
|---|---|---|
| 1 | Log 2 hours on a job's visit | Job and case, Warranty Cost tab: Labour actual 100.00, hours 2:00 |
| 2 | Change the timesheet to 8 hours | Labour actual 400.00 |
| 3 | Cost Lines button > New, Labour, Service Job, Actual 50 | Refused: read from its timesheets |
| 4 | Same line with Estimated 300 only | Saves; total expected is the larger of 300 and the timesheets, not both |
| 5 | Shared visit of 3 jobs, log 3 hours | Each job 50.00; total 150.00 |
| 6 | Cancel Job on one of them, with a reason | That job 0.00; the other two 75.00 each; total unchanged |
| 7 | Log hours for an employee with no Hourly Cost | Warning names the employee; Labour and Total show **Incomplete**; the timesheet is unchanged |

## C. Travel and approval

| # | Step | Expected |
|---|---|---|
| 1 | Coordinator: Warranty > Warranty Costs > New, Travel, Estimated 500, a Reason, Save | Draft, number `WCL/...`, note on the case |
| 2 | Submit for Approval | Submitted; To-Do for the Cost Approver |
| 3 | Coordinator on the form | No Approve button |
| 4 | Cost Approver: Approve | Approved 500.00, with name and date |
| 5 | Coordinator: change Estimated | Fields are read-only |
| 6 | Record Actual 600 | Refused: above approved |
| 7 | Record Actual 400 with a reason | Case actual Travel 400.00; note shows old and new values and the reason |
| 8 | Coordinator on the form | No Reverse button |
| 9 | Cost Approver: Reverse with a reason | Reversed; figures stay on the line; case actual falls by 400.00 |
| 10 | New line, Submit, Cost Approver: Reject with a reason | Rejected; not counted |

## D. Finance level

| # | Step | Expected |
|---|---|---|
| 1 | New case, line Estimated 1,200, Submit | Finance Approval Required |
| 2 | Cost Approver: Approve | Still Submitted |
| 3 | Finance Approver: Approve | Approved |
| 4 | Settings: Finance Threshold 0. New case, line Estimated 1,200, Submit | No Finance level; the Cost Approver must still approve. Set the threshold back to 1,000 |

## E. Workshop labour

1. Open a Repair Order linked to a test case, then the Cost Lines button > New.
2. Labour, Estimated 300, Actual 250, a Reason. Submit and approve.
3. Expect the case actual Labour to rise by 250.00, and the note to show on the Repair Order.

## F. Subcontract

| # | Step | Expected |
|---|---|---|
| 1 | Accounting: post a test vendor bill of 1,000 for a service product | Standard |
| 2 | Coordinator: new Subcontract line with a Reason, Save | Draft; no source fields for a Helpdesk-only user |
| 3 | Billing user: select the Vendor Bill Line | Source Document and Actual 1,000.00 show |
| 4 | Submit and approve | Case actual Subcontract 1,000.00. The bill is unchanged |
| 5 | Second line, on another case, same bill line | Refused: already allocated |
| 6 | Bill line of a stockable product | Refused |
| 7 | On the test bill, Credit Note for 300, then post it | Warning on the line; actual 700.00; Approved stays 1,000.00 |
| 8 | Reverse the rest of the test bill in Accounting | Warning on the line; case actual falls to 0.00 |

## G. Expected cost gate

| # | Step | Expected |
|---|---|---|
| 1 | Gate off: Draft line of 1,500 on a test case, then Confirm its job | Job confirms as before |
| 2 | Settings: gate on, threshold 1,000. New test case with a Planned job and a Draft line of 1,500. Confirm the job | Refused; names the pending line |
| 3 | Approve the line, then Confirm | Confirms |
| 4 | Add a Draft line, then release an approved Material Request of that case | Refused; names the line |
| 5 | Same line pending, Plan Next Visit on an Incomplete job | Refused |
| 6 | Already confirmed jobs | Stay as they are |
| 7 | Settings: turn the gate **off** again | Back to normal |

## H. Security and accounting

| # | Step | Expected |
|---|---|---|
| 1 | Technician | No Warranty Costs menu; no Warranty Cost tab on the job |
| 2 | Accounting read-only user | Can read the lines; cannot change them |
| 3 | User of the other company | Cannot see these lines |
| 4 | Accounting > Journal Entries, before and after these tests | No new entry from cost lines. Only the test bill and its reversal |
| 5 | View WCAS/000049, WR/000006, VCL/00006 | Unchanged |
