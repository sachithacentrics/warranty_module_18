# Part 6.3 – Backup Damage / Loss Billing – Manual Testing Guide

Needs the Part 6.2 configuration (`Part6_2_Backup_Manual_Testing_Guide.md`) and a module upgrade.

## 1. Configuration

| # | Where | Set |
|---|---|---|
| 1 | Sales > Products | Service product `Backup Damage / Loss Charge`: Can be Sold, Invoicing Policy Ordered Quantities, Create on Order Nothing, Warranty Applicable off |
| 2 | Settings > Warranty | **Backup Damage / Loss Charge Product**: that product |
| 3 | Settings > Warranty | **Backup Damage / Loss Approvers**: user B (Helpdesk or Inventory User) |
| 4 | Users | User A: Inventory User and Helpdesk User, not an approver. A billing user with Sales and Invoicing rights |
| 5 | Stock | Serials `BK-101`, `BK-102`, `BK-103`, `BK-104` in Backup Stock |

## 2. Phase 2 unchanged

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-D-01 | Issue BK-101, return with Good, transfer to Backup Stock, Close. | Closed as in Part 6.2; Financial Recovery Not Assessed; no quotation | | |

## 3. Damage

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-D-10 | Issue BK-102, return with Damaged. | **Damaged**; Physical Asset In Returned - Inspection; To-Do "submit the damage assessment" | | |
| TC-D-11 | User A: Submit Assessment with no notes. | Refused | | |
| TC-D-12 | Enter notes, cost 5,000, charge 10,000. Submit. | Waiting Approval; fields read-only; B has a To-Do; note on record, ticket, case, card, job, repair | | |
| TC-D-13 | User A opens the record. | No Approve or Send Back | | |
| TC-D-14 | Add A to the approvers. A opens the record. | Still no Approve or Send Back (submitter). Remove A again | | |
| TC-D-15 | B: Send Back with no Decision Note. | Refused | | |
| TC-D-16 | B: enter a note, Send Back. | Not Submitted; A has a To-Do; status stays Damaged; values editable | | |
| TC-D-17 | A: Submit again. B: Approve Assessment. | Approved; one **draft** quotation for the commercial customer, one line, 10,000; Origin has BKU, case, Repair Order; To-Do "send the charge quotation" | | |
| TC-D-18 | Check the case, jobs, Field Service. | No job, task, or case link on the quotation; quotation not sent | | |
| TC-D-19 | Return Condition. | Still Damaged, read-only | | |

## 4. Billing

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-D-20 | On the quotation, change the price or quantity. | Refused | | |
| TC-D-21 | Duplicate the quotation. Delete it. | Both refused | | |
| TC-D-22 | Cancel the quotation. | Financial Recovery **Quotation Cancelled**; no Close; not No Charge | | |
| TC-D-23 | Set to Quotation. Send. Confirm. | Quotation, then **To Invoice** | | |
| TC-D-24 | Create Invoice, Regular. Create Invoice again. | One invoice; nothing left to invoice; not posted automatically | | |
| TC-D-25 | Post. | **Invoiced**; invoice shown to billing users | | |
| TC-D-26 | Register a partial payment, then the rest. | **Partially Paid**, then **Paid** | | |
| TC-D-27 | Physical Asset after payment. | Unchanged: In Returned - Inspection | | |
| TC-D-28 | Repair, or transfer to Backup Stock. | Physical Asset follows the stock; Financial Recovery unchanged | | |
| TC-D-29 | New record: BK-102 offered? Close offered on the damaged record? | Not offered; no Close (D3) | | |

## 5. Damage found during inspection

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-D-30 | Issue BK-103, return with Good. Enter notes and charge 0. Submit Assessment. | **Damaged**; Return Condition still Good; Close gone | | |
| TC-D-31 | B: Approve with no Decision Note. | Refused | | |
| TC-D-32 | B: enter a note, Approve. | **No Charge Approved**; no quotation; record stays Damaged, not Closed | | |

## 6. Loss

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-D-40 | Issue BK-104. Create Return Transfer. Report Lost with notes and charge. | Refused: cancel the open return transfer | | |
| TC-D-41 | Cancel it. Report Lost. | Status stays Issued; Waiting Approval; no Create Return Transfer | | |
| TC-D-42 | B: Send Back with a note. | Still Issued; return possible again | | |
| TC-D-43 | Report Lost again. B: Approve. | **Lost**; draft quotation; Physical Asset In Service / Loan With Customer; no stock move, no scrap | | |
| TC-D-44 | New record. | BK-104 not offered | | |
| TC-D-45 | Overdue scheduled action. | Lost record unchanged | | |
| TC-D-46 | Inventory > Scrap: BK-104 from Service-Loan, Validate. | Physical Asset **Scrapped**; Financial Recovery unchanged; still Lost; BK-104 not offered | | |

## 7. Deposit

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-D-50 | Enter a Deposit amount on any record. | Saved and tracked; no invoice or payment created | | |
| TC-D-51 | Billing user: select a customer invoice of this customer in Deposit Invoice. | Saved; another customer's invoice is not offered | | |
| TC-D-52 | Return and pay the charge on a unit with a deposit. | No refund, offset or forfeiture | | |

## 8. Existing behaviour

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-D-60 | Repair flow TC-R-01 to TC-R-15 and a Figure 4 chargeable case. | Unchanged; no backup quotation is used as a final repair quotation | | |
| TC-D-61 | Overdue charge invoice, then a new warranty claim of that customer. | Existing overdue-invoice check counts it (D7) | | |
