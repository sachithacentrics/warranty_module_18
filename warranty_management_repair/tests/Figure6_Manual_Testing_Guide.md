# SRS Figure 6 – Workshop Repair and Backup Machine – Manual UAT Guide

Versions: `warranty_management_repair` 18.0.1.7.1, `warranty_management_accounting` 18.0.1.6.4
(design: `doc/part6_1_repair_intake_design.md` sections 13–15). SRS: §2.9, §12 scenarios 17/18,
§13, §14, §17, status table page 59, Figure 6 page 30.

**Rules for the tester**

* Fill **Actual** with what you saw and the record numbers; **Status** = PASS / FAIL / BLOCKED.
* PASS only with your own evidence on screen. An automated test or a Done transfer alone is not
  a PASS.
* Note before each test: the Sales Order **Delivered** quantity, the card **Start / End** dates and
  the unit **Serial**. They must not change in any test.

## 0. Configuration (once, after the backup-first upgrade)

| ID | Menu | Set / check | Actual | Status |
|---|---|---|---|---|
| CFG-01 | Settings > Warranty | Warranty Repair Intake Location = Physical Locations/Warranty Repair Intake | | |
| CFG-02 | Settings > Warranty | Backup Issue / Backup Return operation types set; Backup Damage / Loss Approvers = `approval` | | |
| CFG-03 | Settings > Warranty | Backup Damage / Loss Charge Product (service product). Needed for TC-F6-31, 32, 35, 83 | | |
| CFG-04 | Helpdesk > Configuration > Teams > Customer Care | Returns and Repairs on; Inspection Required; Inspection Trigger On Sales Order Confirmation | | |
| CFG-05 | Inventory > Configuration > Locations > New | `Vendor Repair - PCB Vendor`: Parent **Physical Locations**, Type **Internal**, Company set, **Vendor Repair Custody** ticked, Repair Vendor = the vendor (e.g. a vendor contact) | | |
| CFG-06 | Inventory > Configuration > Locations > New | `Vendor Repair - Any Vendor`: as CFG-05, Repair Vendor empty | | |
| CFG-07 | Inventory > Configuration > Locations > New | `PCB Lab` (internal repair bench): Parent Physical Locations, Type Internal, **not** custody | | |
| CFG-08 | Inventory > Configuration > Operation Types | The warehouse's **Internal Transfers** is active | | |
| CFG-09 | Users | Tester: Helpdesk User + Inventory User + Sales User; approver `approval` (another user) | | |

Negative config check: **CFG-10** tick Vendor Repair Custody on `WH/Stock`. Expected: refused
("outside the warehouses").

## 1. Test data (UAT, read on 2026-11-06)

| Data | Value |
|---|---|
| Customer machines (no open case) | WC/00014 UAT-AC12-001 (UAT - Service Customer); WC/00016 UAT-AC12-002 (UAT - Service Customer); WC/00035 AC-0001 (ASD Customer); WC/00026 B10001 (Moda Manidu) |
| Backup machine | DEMO-AC-007 (free it with TC-F6-24 on BKU/00008 first); BK-001 / BK-102 in WH/Stock can be moved to Backup Stock with a standard internal transfer |
| Existing records | WCAS/000062 + JOB/000048 (trigger before intake, created before the fix); BKU/00009, BKU/00002 (Damaged, approved), BKU/00003 (Lost) |

## 2. Diagram coverage

| Diagram node | Test cases |
|---|---|
| Helpdesk Ticket / Service Job | all |
| On-site resolution possible? (Service Mode) | TC-F6-01 – 08 |
| YES: Continue Field Service | TC-F6-01, 02, 03 |
| NO: Return / repair intake Customer -> Warranty Repair Intake | TC-F6-10, 11 |
| Linked Repair Order with product and serial | TC-F6-11, 12, 13 |
| Backup machine required? YES / NO | TC-F6-20, 21 / TC-F6-10 |
| Repair | TC-F6-10 |
| Vendor repair | TC-F6-40 – 47 |
| Replacement | Part 7 guides (TC-F6-50 checks the link) |
| Return repaired / replacement unit | TC-F6-10, 44 |
| Receive backup, inspect, close | TC-F6-22 – 25 |
| Lost / damaged / chargeable cost? YES -> approval, quotation / invoice | TC-F6-30 – 32, 70 |
| Close Helpdesk, Job, Repair, stock history | TC-F6-60 – 62 |
| Damaged backup disposition and Close | TC-F6-33 – 37 |
| Lost backup disposition and Close | TC-F6-71 – 73 |
| Lost -> Found recovery | TC-F6-80 – 85 |

---

## A. Decision "On-site resolution possible?" – Service Mode

### TC-F6-01 – YES, On-site (Figure 4 / 5)
SRS: Figure 6 YES, §12 sc. 18. Data: WC/00014, UAT-AC12-001.

| # | Navigation / button | Expected | Actual |
|---|---|---|---|
| 1 | Helpdesk > Customer Care > New ticket, Is Warranty, customer, serial UAT-AC12-001; create the case; Check Eligibility; `approval` approves | Case Approved, Eligible | |
| 2 | Case > Service Mode = **On-site**, save | Saved; chatter shows the change | |
| 3 | Case > **Prepare Service Job** | Inspection quotation created; no job yet | |
| 4 | Quotation > **Confirm** | One Draft service job; case note "service job … prepared" | |
| 5 | Continue the job and visit (Figure 4 / 5) to Complete Visit | Job and case Completed by the job | |

Status: ____

### TC-F6-02 – On-site wins over a workshop Repair Order
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | New case (WC/00016, UAT-AC12-002), approved; ticket **Return** + validate; ticket **Repair** + Confirm | Repair Order Confirmed, Intake Status Received | |
| 2 | Service Mode = On-site; Prepare Service Job; Confirm quotation | **One job created** (explicit On-site) | |
| 3 | Cancel the job, Repair Order Cancel, ticket Return the machine (clean-up) | – | |

Status: ____

### TC-F6-03 – Prepare Service Job refused while a job is open
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Case of TC-F6-01 with its open job: **Prepare Service Job** | Refused: "already has the open service job" | |

Status: ____

### TC-F6-04 – Who may set the Service Mode
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | User with Inventory rights only opens the case | Service Mode not editable / save refused | |
| 2 | Case with an open job: change Service Mode to Workshop Repair | Refused: "the job keeps control" | |
| 3 | Completed or Rejected case | Field read-only | |

Status: ____

### TC-F6-05 – Prepare Service Job with Workshop / Vendor mode
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Approved case, Inspection Required, Service Mode Workshop Repair: **Prepare Service Job** | Inspection quotation created (no job) | |
| 2 | Confirm the quotation; **Prepare Service Job** again | Refused: "Service Mode Workshop Repair … no on-site Service Job" | |
| 3 | Case without Inspection Required, mode Vendor Repair: Prepare Service Job | Refused at once | |

Status: ____

### TC-F6-06 – Empty Service Mode keeps the earlier behaviour
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Case with Service Mode empty: run TC-F6-01 steps 3–4 | Job created as before | |

Status: ____

### TC-F6-07 – Job-led switch to the workshop
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Job of an On-site case In Progress: **Hold > Workshop Repair**, reason | Job state Workshop; case Service Mode = Workshop Repair; note "Service Mode set to Workshop Repair" | |
| 2 | Case: change Service Mode to On-site | Refused (job keeps control) | |
| 3 | Case: change to Vendor Repair | Allowed | |

Status: ____

### TC-F6-08 – Trigger before intake (the WCAS/000062 situation) with Workshop mode
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | New approved case, Service Mode Workshop Repair; Prepare Service Job; **Confirm** the quotation **before** any Return | **No job**; one case note "Service Mode Workshop Repair: no Field Service job is created" | |
| 2 | Ticket Return + validate; Repair + Confirm; **Start Repair** | Allowed (trigger met) | |

Status: ____

Recovery of the existing WCAS/000062 (Service Mode empty, job created before the fix): **TC-F6-09**
JOB/000048 > Cancel (your decision), then WH/RO/00012 > Complete Warranty Case. Expected: case
Completed, no free service consumed. Status: ____

## B. NO branch – workshop repair

### TC-F6-10 – Helpdesk-led workshop repair, no backup
SRS §2.9. Data: WC/00016, UAT-AC12-002, Service Mode Workshop Repair.

| # | Navigation / button | Expected | Actual |
|---|---|---|---|
| 1 | Ticket > **Return**: quantity 1, Warranty Repair Intake ticked; Validate with serial UAT-AC12-002 | Serial in Warranty Repair Intake; Delivered qty unchanged | |
| 2 | Ticket > **Repair** | Case, product, serial and intake prefilled; Intake Status **Received** | |
| 3 | **Confirm**; **Start Repair** | Start refused: "requires an inspection quotation" | |
| 4 | Case > Prepare Service Job; Confirm the quotation | No job; note; Repair Order To-Do "start the repair" | |
| 5 | **Start Repair**; Repair Result Repaired; **End Repair** | Intake Status Under Repair, then Repaired; To-Do "return the machine" | |
| 6 | **Return Machine to Customer**; validate | Intake Status **Returned**; serial at the customer | |
| 7 | **Complete Warranty Case** | Case Completed; ticket stays open | |

Status: ____

### TC-F6-11 – Intake Status reflects the received serial
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Repair Order created before the intake is validated | Intake Status **Awaiting Receipt** | |
| 2 | Validate the intake; open the Repair Order | **Received** | |
| 3 | Intake validated with another serial | Validation refused (machine of the ticket only) | |

Status: ____

### TC-F6-12 – Confirm guard: wrong serial
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Repair Order: change the serial to another one; Confirm | Refused, naming the expected serial | |

Status: ____

### TC-F6-13 – Two active cases on one ticket (F1)
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Ticket with two active cases; open the job of the second case > **Create / Open Repair Order** | Repair form with that case, **its product and serial** | |
| 2 | Ticket > Repair | No case chosen automatically (choose it) | |

Status: ____

## C. Backup machine

### TC-F6-20 – Backup required YES: issue
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Repair Order > **Issue Backup Machine** | Backup form prefilled (ticket, case, Repair Order, customer) | |
| 2 | Serial list | Only free serials in Backup Stock (DEMO-AC-007), not BK-103 / UAT-AC12-009 | |
| 3 | Issue Condition Good, Expected Return; **Create Issue Transfer**; Validate | State Issued; serial in Service-Loan With Customer | |

Status: ____

### TC-F6-21 – Backup issue negative
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Change the serial on the issue transfer to another serial; Validate | Refused "must move exactly one …" | |

Status: ____

### TC-F6-22 – Receive backup, Good
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | After TC-F6-10 step 6: backup unit Return Condition **Good**; **Create Return Transfer**; Validate | State Returned; serial in Returned-Inspection | |
| 2 | **Return to Backup Stock**; Validate | Serial in Backup Stock; To-Do "close" | |
| 3 | **Close** | Closed; serial can be issued again | |

Status: ____

### TC-F6-23 – Receive backup, Minor Scratch (C3)
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Return Condition **Minor Scratch**: Create Return Transfer, Validate; **Return to Backup Stock** (button visible); Validate; Close | Closed; serial in Backup Stock | |

Status: ____

### TC-F6-24 – Free DEMO-AC-007 (BKU/00008)
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | BKU/00008 > Return to Backup Stock > Validate > Close | Closed; DEMO-AC-007 issuable | |

Status: ____

### TC-F6-25 – Backup Required NO
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | TC-F6-10 without Issue Backup Machine | No backup record, no backup transfer | |

Status: ____

## D. Damaged / Lost backup (C2, repair 18.0.1.7.1)

Rules: [PROPOSED] business decisions approved 2026-11-06, not explicit SRS text.
B1 a damaged unit returns to service only with Confirm Restored; B2 Close needs No Charge
Approved or Paid (fully invoiced, no draft); B3 Credit Note Issued / Quotation Cancelled not
closable (except B5c); B4 Lost: standard Scrap **or** Physical Inventory count 0 (missing),
verified; B5 Lost -> Found; B6 rejection = Send Back; B7 Damaged / Lost Close by Inventory users.
**Close never creates a scrap, adjustment, transfer, invoice, payment or journal entry.** Every
disposition below is a standard Inventory operation done by you.

Data: a new workshop case with a backup issued (TC-F6-20), one unit per test. BK-001 / BK-102 can
be added to Backup Stock with a standard internal transfer.

### TC-F6-30 – Damaged return
SRS: §2.9, Fig. 6 "Receive backup unit, inspect condition".

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Backup Unit > Return Condition **Damaged** > **Create Return Transfer** > Validate | State **Damaged**; serial in Returned-Inspection; To-Do "submit the damage assessment" | |
| 2 | Variant: unit returned Good, damage found later > **Submit Assessment** | Damaged; no stock move | |

Status: ____

### TC-F6-31 – Assessment, approval, rejection
SRS: §2.9 "approved quotation/invoice", §17.

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Notes, Repair / Scrap Cost, Customer Charge 2,500 > **Submit Assessment** | Waiting Approval; approver To-Do | |
| 2 | Submitter tries to approve | Not offered / refused | |
| 3 | As `approval`: Decision Note > **Send Back** (B6) | Not Submitted; still Damaged; submitter To-Do | |
| 4 | Submit again > `approval` > **Approve Assessment** | One draft quotation; Financial Recovery **Quotation**; To-Do "send the charge quotation" | |

Status: ____

### TC-F6-32 – Charge settled; Close refusals (B2, B7)

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | **Close** (not invoiced, not disposed) | Refused, listing **both**: Financial Recovery Quotation; scrap or Confirm Restored | |
| 2 | Quotation > Confirm > Create Invoice > Post | Financial Recovery **Invoiced**; Close still refused | |
| 3 | Register Payment | Financial Recovery **Paid** | |
| 4 | Helpdesk-only user > Close | Refused (Inventory users only) | |

Status: ____

### TC-F6-33 – Damaged, Scrap disposition

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Inventory > Operations > **Scrap** > New: product, serial, Source **Returned-Inspection** > Validate | SP/… done; Physical Asset **Scrapped** | |
| 2 | Backup Unit > **Close** | Closed; Disposition **Scrapped**; Disposition Move = the scrap; note with financial status, scrap reference, user, date | |
| 3 | Compare Inventory / Accounting before and after Close | Close created no scrap, transfer, invoice or journal entry | |
| 4 | New Backup Unit > Backup Serial list | The scrapped serial is never offered | |

Status: ____

### TC-F6-34 – Damaged, Restore disposition (B1)

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Damaged, approved: **Confirm Restored** without condition / note | Refused | |
| 2 | Restored Condition Good + Restoration Note > **Confirm Restored** (Inventory user) | Restored By / On set; fields locked | |
| 3 | **Return to Backup Stock**; Close before validating | Close refused (transfer not validated) | |
| 4 | Validate the transfer > **Close** | Closed; Disposition **Restored to Backup Stock**; serial issuable again | |

Status: ____

### TC-F6-35 – Credit note / cancelled quotation (B3)

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Damaged with charge: invoice posted, then a Credit Note; unit scrapped > Close | Refused: "Credit Note Issued: closing needs a write-off rule" | |
| 2 | Other unit: charge quotation **Cancelled**; unit scrapped > Close | Refused: Quotation Cancelled | |

Status: ____ (the refusal is the expected result)

### TC-F6-36 – Scrap from the wrong location

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Damaged unit moved by hand out of Returned-Inspection and scrapped there > Close | Refused (not the verified disposition) | |

Status: ____

### TC-F6-37 – Completion and Close Case not blocked by a Damaged unit

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Damaged unit open: Complete Warranty Case, later Close Case | Both allowed (C4 blocks custody only) | |

Status: ____

### TC-F6-70 – Report Lost
SRS: §2.9 "Lost … approved quotation/invoice"; lifecycle page 59.

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Issued unit > Assessment Notes > **Report Lost** | Still **Issued**, Waiting Approval; **no return transfer** | |
| 2 | **Create Return Transfer** | Refused (loss waiting approval) | |
| 3 | Its Completed case > **Close Case** | Refused: backup still with the customer (C4) | |
| 4 | `approval` > **Send Back** | Issued, not Lost | |
| 5 | Report Lost again > `approval` > **Approve Assessment** | **Lost**; quotation if charged | |
| 6 | Close Case | Allowed (an approved Lost unit does not block) | |

Status: ____

### TC-F6-71 – Lost, Scrap

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | **Close** before any disposition | Refused: Scrap or count it missing | |
| 2 | Inventory > **Scrap**: serial, Source **Service-Loan With Customer** > Validate; charge settled (B2) | Physical Asset Scrapped | |
| 3 | **Close** | Closed; Disposition **Scrapped** | |

Status: ____

### TC-F6-72 – Lost, Missing (Inventory Adjustment)

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Inventory > Operations > **Physical Inventory**: the serial in Service-Loan, Counted Quantity **0** > **Apply** (Inventory Administrator) | Physical Asset **Removed by Inventory Adjustment** | |
| 2 | **Close** | Closed; Disposition **Missing (Inventory Adjustment)**; reference to the adjustment | |
| 3 | An Inventory user without Administrator rights tries step 1 | Refused by standard Odoo | |

Status: ____

### TC-F6-73 – Written-off serial never issuable again (B5e)

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | After TC-F6-71 / 72: the Inventory Administrator puts the serial into Backup Stock by hand | Stock shows it | |
| 2 | New Backup Unit > Backup Serial | **Not offered**; forcing it is refused ("written off") | |
| 3 | The Closed Lost unit > Record Found | Not offered / refused (recovery of a closed record: Part 9) | |

Status: ____

### TC-F6-80 – Lost -> Found before write-off (B5)

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Lost unit (serial still in Service-Loan) > Create Return Transfer | Refused: Record Found first | |
| 2 | A non-approver > **Record Found** | Refused | |
| 3 | Found Note > `approval` > **Record Found** | Found By / On; note "loss assessment and charge unchanged"; To-Do "receive the backup unit"; still Lost | |
| 4 | Record Found again | Refused | |
| 5 | Its case > Close Case | Refused: found unit not received yet (B5f) | |
| 6 | Backup unit > Close | Refused: receive it first | |
| 7 | Return Condition **Good** > **Create Return Transfer** (twice: same transfer) > Validate | **Returned**; loss assessment unchanged | |
| 8 | Return to Backup Stock > Validate > **Close** (financial per B5c) | Closed; Disposition Back in Backup Stock; serial issuable | |

Status: ____

### TC-F6-81 – Found, condition Damaged (B5d)

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | TC-F6-80 steps 1–3, Return Condition **Damaged** > Validate | **Damaged**; To-Do "scrap or Confirm Restored" | |
| 2 | **Submit Assessment** | Not offered / refused: no second assessment, no new charge | |
| 3 | Scrap from Returned-Inspection, or Confirm Restored + Return to Backup Stock | as TC-F6-33 / 34 | |
| 4 | **Close** | Closed | |

Status: ____

### TC-F6-82 – Found after write-off: stock correction first

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Lost unit already scrapped or counted 0 > Found Note > Record Found | Refused: "written off … an Inventory Administrator must first correct the stock" | |
| 2 | Counted missing: Inventory Administrator counts 1 in Service-Loan > Apply | Serial back in Service-Loan | |
| 3 | Scrapped: Inventory Administrator **internal transfer from the Scrap location back to Service-Loan** (a count alone is not enough: still refused) | Serial back in Service-Loan; none left in Scrap | |
| 4 | Record Found > continue as TC-F6-80 / 81 | Allowed | |

Status: ____

### TC-F6-83 – Recovered loss: financial correction (B5c)

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Lost with charge invoiced; found; returned Good; back in Backup Stock | – | |
| 2 | Accounting: partial Credit Note posted; invoice remainder unpaid > Close | Refused: "Credit note correction not settled" | |
| 3 | Remainder paid (or a full credit note) > Close | Closed | |

Status: ____

### TC-F6-84 – Wrong serial on the recovery return

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | Change the serial on the found unit's return transfer > Validate | Refused "must move exactly one …" | |

Status: ____

### TC-F6-85 – Good path unchanged (regression)

| # | Screen > action | Expected | Actual |
|---|---|---|---|
| 1 | TC-F6-22 again (Good > Return to Backup Stock > Close) | As before; Disposition Back in Backup Stock | |

Status: ____

### TC-F6-86 – Existing UAT records (optional, your decision)

| Record | Path |
|---|---|
| BKU/00009 (Damaged, no charge, Returned-Inspection) | TC-F6-33 (Scrap) or TC-F6-34 (Restore) |
| BKU/00003 (Lost, quotation S00071 Draft, BK-104 scrapped SP/00001) | Settle S00071 (B2), then Close; a cancelled quotation is not closable (B3) |
| BKU/00002 (Damaged, charge invoiced, BK-103 already in Backup Stock by hand) | **Limitation:** Confirm Restored needs the serial in Returned-Inspection: move it back first, or decide otherwise |

## E. Vendor repair (Service Mode Vendor Repair)

Data: WC/00035 AC-0001 (ASD Customer); CFG-05 – CFG-07.

### TC-F6-40 – External vendor round trip
| # | Navigation / button | Expected | Actual |
|---|---|---|---|
| 1 | Case Service Mode **Vendor Repair**; Return + validate; Repair + Confirm; quotation confirmed; **Start Repair** | Under Repair; **Send for Repair** button visible | |
| 2 | **Send for Repair** | Wizard: From = Warranty Repair Intake (actual location) | |
| 3 | Transfer Type **External Vendor**; Vendor = PCB Vendor | To offers `Vendor Repair - PCB Vendor` and `- Any Vendor` only | |
| 4 | Choose `Vendor Repair - PCB Vendor`; **Create Transfer** | Internal Transfer, exact serial, qty 1, partner = vendor, origin = RO / case; Vendor Repair tab lists it | |
| 5 | Validate | Intake Status **Away for Repair**; Vendor Repair = Sent for Repair; notes on RO / case / card | |
| 6 | Inventory valuation report / journal entries | **No** new valuation entry, no purchase order, no sale | |
| 7 | **Receive from Repair** | Transfer `Vendor Repair - PCB Vendor` -> Warranty Repair Intake, same serial | |
| 8 | Validate | Vendor Repair = Received Back; Intake Status Under Repair | |
| 9 | Repair Result; End Repair; Return Machine to Customer; Complete Warranty Case | Case Completed | |

Status: ____

### TC-F6-41 – Internal transfer round trip
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Send for Repair > **Internal Transfer** | To offers `PCB Lab`, not custody / intake / backup / WH locations; no vendor field | |
| 2 | Create, validate; Receive from Repair, validate | Machine back in Intake | |

Status: ____

### TC-F6-42 – While away, refused
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Machine away: End Repair; Cancel; Return Machine to Customer; ticket Return of the intake; Send for Repair | All refused ("away for repair") / Send hidden | |

Status: ____

### TC-F6-43 – Duplicates
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Send for Repair twice before validating | Second click opens the same transfer | |
| 2 | Receive from Repair twice | Same receive transfer opened | |

Status: ____

### TC-F6-44 – Wrong serial / location on the transfer
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | On the send transfer change the serial or the destination; Validate | Refused "must move exactly one …" | |

Status: ____

### TC-F6-45 – Mode and state checks
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Service Mode Workshop Repair | No Send for Repair button; action refused | |
| 2 | Repair Order only Confirmed | Refused "Start the repair first" | |
| 3 | Machine away: change Service Mode away from Vendor Repair | Refused | |

Status: ____

### TC-F6-46 – Permissions and company
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Helpdesk user without Inventory rights: Send for Repair | Refused (Inventory users only) | |
| 2 | A custody location of another company | Never offered | |

Status: ____

### TC-F6-47 – Vendor's charge / recovery (existing tools, no automation)
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | If the vendor bills: standard Purchase / vendor bill; cost line on the case (Part 8); recovery: Vendor Claim | Nothing created automatically by Send / Receive | |

Status: ____

## F. Replacement link

### TC-F6-50 – Not Repairable, replaced (Part 7)
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Repair Result Not Repairable; Part 7 replacement Done; Complete Warranty Case | Completed without returning the old machine; backup To-Do "receive the backup unit" after the replacement delivery | |

Status: ____

## G. Closure

### TC-F6-60 – Close Case waits for the backup machine (C4)
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Case Completed while its backup unit is Issued: **Close Case** | Refused: "Backup unit … is still with the customer" | |
| 2 | Receive the backup (Return Transfer validated); Close Case | Allowed (other Part 8 checks as before) | |
| 3 | Backup returned Damaged, assessment open or approved | Close Case **not** blocked by it | |

Status: ____

### TC-F6-61 – Completion not blocked by the backup
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Backup still Issued: Complete Warranty Case (Repair Order) / Complete Visit (job) | Allowed (SRS: backup comes back after the machine) | |

Status: ____

### TC-F6-62 – Helpdesk ticket
| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | After Close Case: move the ticket to its closed stage (standard, manual) | Allowed; history on ticket, case, card, Repair Order, transfers | |

Status: ____

## H. Summary

| Branch | Test cases | Result |
|---|---|---|
| YES On-site | 01–03, 06 | |
| Service Mode rules | 04, 05, 07, 08, 09 | |
| NO Workshop | 10–13 | |
| Backup YES / NO / Good / Minor Scratch | 20–25 | |
| Damaged return, assessment, billing | 30–32 | |
| Damaged Close (Scrap / Restore / refusals) | 33–37 | |
| Lost report, approval, Close (Scrap / Missing) | 70–73 | |
| Lost -> Found recovery | 80–85 | |
| Vendor repair | 40–47 | |
| Replacement link | 50 | |
| Closure | 60–62 | |

Figure 6 is complete only when every row is PASS with UAT evidence. Not covered (documented
limits): recovery of an already Closed Lost unit (Part 9); a second damage charge on a
recovered unit; a write-off rule for credit notes / cancelled quotations of non-recovered units.
