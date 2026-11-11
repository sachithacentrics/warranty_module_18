# Part 6.2 – Backup Unit Issue / Return – Manual Testing Guide

## 1. Configuration

| # | Where | Set |
|---|---|---|
| 1 | Inventory > Configuration > Locations | Create three locations, parent **Physical Locations** (not under `WH`), Type Internal, Company set: `Backup Stock`, `Service-Loan With Customer`, `Returned-Inspection` |
| 2 | Inventory > Configuration > Operation Types | **Backup Issue**: Type Internal Transfer, sequence prefix `BKU/OUT/`, Default Source `Backup Stock`, Default Destination `Service-Loan With Customer` |
| 3 | Same | **Backup Return**: Type Internal Transfer, sequence prefix `BKU/IN/`, Default Source `Service-Loan With Customer`, Default Destination `Returned-Inspection` |
| 4 | Settings > Warranty | **Backup Issue Operation Type** and **Backup Return Operation Type** |
| 5 | Product | A storable backup product tracked **By Unique Serial Number** |
| 6 | Inventory > Physical Inventory, or a Receipt | Put serial e.g. `BK-001` and `BK-002` into `Backup Stock` |

User: Inventory User and Helpdesk User. Test data: a warranty ticket (ideally with a case and a Repair Order).

## 2. Issue

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-B-01 | Warranty > Backup Units > New: select the ticket. | Customer and site fill; case and Repair Order fill when only one is active | | |
| TC-B-02 | Open the Backup Product and Backup Serial lists. | Only products and serials in Backup Stock with no open record | | |
| TC-B-03 | Check Sales: product forecast / availability of the serial. | Backup stock not counted as available in the warehouse | | |
| TC-B-04 | Save with BK-001, Expected Return in 7 days, no Issue Condition. Create Issue Transfer. | Refused: set the Issue Condition | | |
| TC-B-05 | Set Issue Condition Good. Create Issue Transfer. | Standard transfer opens, BK-001 reserved, Backup Stock → Service-Loan. Record stays Draft | | |
| TC-B-06 | Another record with BK-001. | Serial not offered; forced value refused: already on an open record | | |
| TC-B-07 | On the transfer, change the serial to BK-002 and validate. | Refused; no stock move | | |
| TC-B-08 | Restore BK-001 and validate. | Record **Issued**; Issue Date = validation time; notes on ticket, case, card, job, repair | | |
| TC-B-09 | Original Sales Order of the customer's machine. | Delivered quantity unchanged | | |
| TC-B-10 | **Return** button on the validated issue transfer. | Refused: use Create Return Transfer | | |

## 3. Customer use and overdue

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-B-20 | Set Expected Return to yesterday. Settings > Technical > Scheduled Actions > **Warranty: Backup Units Overdue** > Run Manually. | Record **Overdue**; one To-Do; note. Running again adds no second To-Do | | |
| TC-B-21 | Move Expected Return to next week and run again. | Back to **Issued**; To-Do closed | | |
| TC-B-22 | With a linked Repair Order: return the repaired machine to the customer. | To-Do "receive the backup unit" | | |

## 4. Return

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-B-30 | Create Return Transfer. | Standard transfer, BK-001 reserved, Service-Loan → Returned-Inspection | | |
| TC-B-31 | Click Create Return Transfer again. | Opens the same transfer, no second one | | |
| TC-B-32 | Validate with no Return Condition. | Refused; no stock move | | |
| TC-B-33 | Return Condition Good, validate. | **Returned**; Actual Return = validation time; serial in Returned-Inspection; To-Do "inspect and close"; notes | | |
| TC-B-34 | Close. | Refused: not back in Backup Stock | | |
| TC-B-35 | **Return to Backup Stock** (18.0.1.6.2). | Standard Internal Transfer opens: Returned-Inspection → Backup Stock, BK-001 reserved, quantity 1; shown as Return to Stock Transfer; record stays Returned | | |
| TC-B-35a | Back to the record, Return to Backup Stock again. Close. | Same transfer opened, no second one; Close refused (not back in Backup Stock) | | |
| TC-B-35b | Validate the transfer. Close. | Record stays Returned until Close (no automatic close); To-Do "close"; then **Closed**; BK-001 selectable again | | |
| TC-B-35c | Minor Scratch return: no Return to Backup Stock button; Inventory > Internal Transfer by hand, then Close. | **Closed** (existing path) | | |
| TC-B-36 | New record, issue, Return Condition **Damaged**, validate. | **Damaged**; serial in Returned-Inspection; no Close button (Phase 3) | | |
| TC-B-37 | Cancel an issue transfer before validating, then Create Issue Transfer. | Record stays Draft; a new transfer is created | | |

## 5. Existing behaviour

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-B-40 | Repair Order flow TC-R-01 to TC-R-15 with a backup unit open. | Unchanged; completion is not blocked by the backup unit | | |
| TC-B-41 | MRF cost on the case after a backup cycle. | Unchanged | | |
| TC-B-42 | No job or Field Service task appears from any backup action. | None created | | |
