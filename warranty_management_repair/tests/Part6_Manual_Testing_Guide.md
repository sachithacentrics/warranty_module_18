# Part 6.1 – Repair Intake – Manual Testing Guide

Run on a test database first. The module is not installed anywhere yet.

## 1. Configuration

| # | Where | Set |
|---|---|---|
| 1 | Apps | Install **Warranty Management - Repair Intake** (`warranty_management_repair`) |
| 2 | Inventory > Configuration > Settings | **Storage Locations** and **Lots & Serial Numbers** on |
| 3 | Inventory > Configuration > Locations > New | Name `Warranty Repair Intake`, Parent **Physical Locations**, Type **Internal**, **Company set** (San Francisco). It must not be under `WH` |
| 4 | Settings > Warranty | **Warranty Repair Intake Location** = the location from step 3 |
| 5 | Helpdesk > Configuration > Teams (Customer Care) | **Returns** and **Repairs** on; **Job Trigger** as needed for the test |
| 6 | Settings > Warranty | Material locations and approval rules as in the Part 5 guide. The **Technician Location** is where workshop parts are issued |

**Users**

| Role | Groups |
|---|---|
| Coordinator | Helpdesk User, Inventory User (needed for the Return and Repair buttons), Requisition User, Sales User for chargeable tests, linked employee with a department (needed for MRFs) |
| Approver | As in the Part 5 guide |

**Test data:** a confirmed warranty card with a **serial-tracked** product that was **delivered in Odoo**, then a warranty ticket with **Is Warranty** on, and a warranty case on that ticket.

Before each test, note the **Delivered** quantity on the Sales Order line, the card's **Start / End Date**, and the unit's **Delivery / Serial**. They must not change.

## 2. Workshop-only warranty repair

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-R-01 | Ticket > **Return**. Select the delivery, enter quantity 1, keep **Warranty Repair Intake** ticked. | Draft return with destination Warranty Repair Intake | | |
| TC-R-02 | Enter the serial and validate the return. | Serial in Intake (not WH/Stock). Delivered qty unchanged. Card log says the dates are unchanged | | |
| TC-R-03 | Check Inventory on-hand for the warehouse. | The machine is not available to Sales | | |
| TC-R-04 | Ticket > **Repair**. | Case, product, serial and return prefilled. **No Sale Order link**. Intake Status = Received | | |
| TC-R-05 | Save, then try **Confirm** with a different serial. | Refused, naming the expected serial | | |
| TC-R-06 | Create the order on a case not yet Approved, Confirm and Start. | Start refused until the case is Approved, Eligible | | |
| TC-R-07 | On a linked order, add a part line of type Add, then try Catalog. | Refused: "request its parts with a Material Request" | | |
| TC-R-08 | Add a line of type Remove. | Allowed | | |
| TC-R-09 | Case > **Material Request**: add a covered part, approve, issue, record used. | MRF links to the Repair Order. Page **Material Requests** on the order shows the line. Cost appears once on the case | | |
| TC-R-10 | Approved case: Confirm, Start. | Under Repair; **Under Warranty** ticked automatically | | |
| TC-R-11 | **End Repair** with no Repair Result. | Refused | | |
| TC-R-12 | Set result Repaired and End Repair. | Repaired. Serial still in Intake. To-Do "return the machine". No stock or value change for the machine | | |
| TC-R-13 | On the validated return > **Return**, quantity 1, validate. | Machine at the customer. Intake Status = Returned. Delivered qty unchanged. Unit delivery and serial unchanged | | |
| TC-R-14 | Leave the MRF unreconciled, click **Complete Warranty Case**. | Refused, listing the MRF | | |
| TC-R-15 | Reconcile, click **Complete Warranty Case**. | Case Completed. Notes on the case and card. Ticket stays open | | |

## 3. Completion conditions

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-R-20 | Case with a pending free service: repair and return. Complete Warranty Case. | Refused: free service needs a service job | | |
| TC-R-21 | Case with an open service job: repair and return. | Complete Warranty Case refused: the job completes the case | | |
| TC-R-22 | Same job, before the machine is returned: **Complete Visit** and Batch Complete. | Refused, naming the Repair Order | | |
| TC-R-23 | Same job: visit > Not Completed, reason **Workshop Repair Required**. | Allowed; job stays open | | |
| TC-R-24 | After the return: complete the next visit. | Job and case Completed, as today | | |
| TC-R-25 | Result **Not Repairable**, machine returned. | Complete Warranty Case refused (BA-2) | | |

## 4. Chargeable repair

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-R-30 | Chargeable (Repair) case, intake done, Repair Order linked. **Create Quotation** on the order. | Quotation with Chargeable Purpose = Repair, linked to the case | | |
| TC-R-31 | Start Repair before confirming. | Refused: Job Trigger not met | | |
| TC-R-32 | Trigger On Sales Order Confirmation: confirm the quotation. | **No service job created**. Case note and To-Do "start the repair". Start works | | |
| TC-R-33 | Trigger On Payment: confirm only, then invoice and pay. | Start refused until fully paid, then allowed. No job | | |
| TC-R-34 | Case **Prepare Service Job** with a linked order. | Clear message; no job | | |
| TC-R-35 | Same case type with **no** Repair Order: confirm the quotation. | Draft Chargeable Repair job, as today | | |
| TC-R-36 | Finish, return, Complete Warranty Case. | Completed, outcome Repair Completed. Invoice not created automatically | | |
| TC-R-37 | Inspection job completed, repair required, order linked, **Customer Declined Repair**. | Case Repair Declined; Repair Order cancelled; To-Do to return the machine | | |
| TC-R-38 | Decline after Start Repair. | Refused | | |

## 5. Existing behaviour

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-R-40 | Ticket > Return, **untick** Warranty Repair Intake. | Standard return to WH/Stock; delivered qty decreases as standard | | |
| TC-R-41 | Non-warranty ticket > Repair. | Fully standard; parts allowed; ticket's Sales Order still linked | | |
| TC-R-42 | Repair Order with no ticket and no case. | Fully standard, including part lines | | |
| TC-R-43 | Figure 4: Approved case with Inspection Required: Prepare Service Job, send, confirm. | Quotation, trigger and job unchanged | | |
| TC-R-44 | Figure 4 with an open Repair Order: complete the inspection job. | The repair does not block the inspection job | | |
| TC-R-45 | MRF on a case with no Repair Order and a Part 5 job. | Unchanged | | |

## 6. Kit serials

| ID | Step | Expected | Result | Tester |
|---|---|---|---|---|
| TC-R-50 | Kit (Indoor / Outdoor): return the Outdoor component, repair, return. | Accepts that unit's serial. Indoor / Outdoor serials on the unit unchanged | | |
| TC-R-51 | A line with another undelivered unit: return and re-deliver one machine. | The undelivered unit gets no serial | | |
