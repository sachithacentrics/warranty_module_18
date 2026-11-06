# Phase 5.3 - 5.5 Combined Manual Acceptance Guide

Disposable database **`wt_p5_mrf`** only, test server **http://localhost:8299** (started with the
temporary `decimal_precision` test shim - B1 is still open, see `doc/part5_design_decisions.md`).
Record numbers: see the table "Test data" (filled when the data is loaded).

## Test data

| Item | Value |
|---|---|
| Customer | ABC Hotel (MRF test) |
| **Case G** (main scenario) | **WCAS/017739** - Approved, Service Job **JOB/005430** Confirmed, technician **Technician T** (`tech_t`), visit *JOB/005430 - WCAS/017739 - MRF Split AC* |
| **Case H** (side scenarios) | **WCAS/017740** - Approved, no job |
| Earlier cases (still usable) | D `WCAS/016338`, E `WCAS/016339`, F `WCAS/016869` |
| Products | **Outdoor PCB** 18,500, Covered, 40 in stock · **Expansion Valve** 2,000, Covered, **2** in stock, vendor **Cool Parts Ltd** (1,800) · **Gas R410A** 3,000 / sales 4,000, **Not Covered**, 20 in stock · **Fan Motor** 1,000 / sales 1,500, Not Covered · **Copper Pipe** 10, not in the policy (**Pending**), 5 in stock |
| Locations | Source WH/Stock; destination **Van 1** (Technician T's employee location) or WH/Technician Stock |
| Settings (Warranty -> Material Requests) | Material Approval Matrix **on**, To-Do deadline 1 day, Chargeable Parts Release **On Payment**, Release Exception User **approver_w** |
| Approval rules | TEST Low value (< 25,000, No Approval) · TEST Level 1 (25,000 - 100,000: svc_manager -> finance_off) · TEST High value (>= 100,000: svc_manager -> finance_off + gm_user) · TEST Goodwill (goodwill: finance_off + gm_user) · TEST Chargeable only (only Not Covered < 25,000: svc_manager) |

| Login (password = login) | Role |
|---|---|
| `admin` | Requester / Service Coordinator (Helpdesk, Sales) |
| `approver_w` | Coverage reviewer (5.2), Release Exception User (5.4) |
| `svc_manager` / `finance_off` / `gm_user` | Manager / Finance / GM approvers (5.3) |
| `store_user` | Store: Requisitions + Inventory + Purchase user (5.5) |
| `helpdesk2` | Another Helpdesk user (no rights on admin's requests) |
| `tech_t` | Technician of job G |

Use a second browser / private window for the other users.

## A. Main scenario (Case G)

Warranty Case -> Material Request -> Coverage Decision -> Approval Matrix -> Customer Quotation /
Payment -> Stock Availability -> Issue / Purchase -> Receipt -> Remaining Issue.

| # | User | Steps | Expected | Pass/Fail |
|---|---|---|---|---|
| A1 | admin | Open job **JOB/005430** -> **Create Material Request** -> lines Outdoor PCB 2, Expansion Valve 3, Gas R410A 1, Copper Pipe 1 -> Save. | Request MRF/...: Case G, job, visit; destination Van 1. Coverage: PCB / Valve **Covered**, Gas **Not Covered**, Pipe **Pending**; yellow banner "1 line(s) pending". | |
| A2 | admin | **Confirm / Submit**. | Refused: coverage of Copper Pipe pending. | |
| A3 | admin | **Request Coverage Decision**. | To-Do for approver_w. | |
| A4 | approver_w | Request -> **Decide Coverage** -> Copper Pipe -> **Covered (Goodwill)**, reason "Goodwill for key customer". | Pipe Covered + Goodwill; notes on request, case, job; Coverage **Mixed**. | |
| A5 | admin | **Confirm / Submit**. | Routing Amount **46,010** (all lines). Approvals tab round 1: **Manager** (svc_manager), **Finance** (finance_off), **GM** (gm_user) pending - GM because of the goodwill line. Status **Manager Approval**; To-Do for svc_manager; vendor approval buttons hidden. | |
| A6 | finance_off | Open the request (filter *Waiting for My Approval*). | Visible, read only, **no Approve button** yet (Manager first). | |
| A7 | admin | Try to change the PCB quantity and the Reason. | Refused ("locked"). | |
| A8 | svc_manager | **Approve**. | Status **Finance/GM Approval**; To-Dos for finance_off and gm_user. | |
| A9 | gm_user, then finance_off | **Approve** (GM first, then Finance). | After the last approval: **Approved**, Approved Amount 46,010, admin notified; case / job notes. | |
| A10 | admin | **Create Parts Quotation**. | Quotation with **only Gas R410A x1** (4,000); Parts Release Trigger **On Payment**; Gas line **Waiting Customer**; To-Do "Send quotation" on the case; no Service Job. | |
| A11 | admin | Confirm the quotation. | Gas **Waiting Payment**; the quotation has a delivery for Gas; validating it is **refused** (not released). | |
| A12 | store_user | Request: check the line columns **Free at Source / Stock Availability**. | PCB **Available**; Valve 2 **Partially Available**; Pipe 5 **Available**; Gas (customer quotation) no availability. | |
| A13 | store_user | **Create Picking and PO**. | One internal picking WH/Stock -> Van 1 with **PCB 2, Valve 2, Pipe 1** (no Gas); one RFQ to **Cool Parts Ltd** for **Valve 1** at 1,800; status **Picking / PO Created**; chatter lists picking and RFQ; job Material Status **Shortage** with the Awaiting Parts suggestion banner (no automatic change). | |
| A14 | store_user | Validate the internal picking with the full quantities. | PCB / Pipe **Issued**, Valve Issued 2 / Outstanding 1 (on the open RFQ); request **Partially Issued**; *Received* refused (not completely issued); *Issue / Purchase Remaining* refused (nothing to issue or purchase now). | |
| A15 | store_user | Confirm the RFQ (Purchase) -> validate its receipt. | Receipt linked to the request / case / job (fields on the receipt); Valve Purchased 1 / Received 1. | |
| A16 | store_user | Request -> **Issue / Purchase Remaining**. | New internal picking with **Valve 1** only; no new RFQ. Validate it -> Valve **Issued** 3. | |
| A17 | admin | Quotation -> Create Invoice -> post -> register **half** the amount. | Gas still **Waiting Payment**; delivery still refused. | |
| A18 | admin | Register the rest. | Gas **Released**; validate the quotation delivery (Gas 1) -> Gas **Issued**; request status **Issued**; job Material Status **Issued**. | |
| A19 | store_user | **Received**. | Request **Received**. Approvals tab and coverage columns unchanged (history kept). | |
| A20 | any | Gas movements: Inventory -> Moves Analysis, product Gas R410A. | Only the quotation delivery moved the Gas (no internal picking / RFQ for it). | |

## B. Side scenarios (Case H unless stated)

Create each request from case **WCAS/017740** as admin (*Create Material Request*). Keep the
amounts in mind: PCB 18,500 each (< 25,000 = no approval; 2 = Level 1; 6 = High value).

| # | Phase | Steps | Expected | Pass/Fail |
|---|---|---|---|---|
| B1 | 5.3 | PCB x1 -> Submit. | Approved at once (TEST Low value, "No Approval Required" in the Approvals tab). | |
| B2 | 5.3 | Archive TEST Low value; PCB x1 -> Submit; unarchive the rule. | "No material approval rule matches"; stays New. | |
| B3 | 5.3 | PCB x6 (111,000) -> Submit -> svc_manager, gm_user, finance_off approve. | Manager first; GM / Finance any order; Approved after the last. | |
| B4 | 5.3 | PCB x2 -> Submit -> svc_manager **Reject** without, then with reason. | Reason required; **Rejected**; admin notified; Manager Rejected, Finance Superseded. | |
| B5 | 5.3 | helpdesk2: Reset to Draft on B4 -> refused. admin: Reset to Draft, quantity 1, Submit. | Round 2 (No Approval); round 1 kept in the Approvals tab. | |
| B6 | 5.3 | PCB x2 -> Submit -> svc_manager approves -> admin **Withdraw** (helpdesk2 has no Withdraw). | New again; Manager Approved, Finance Withdrawn. | |
| B7 | 5.3 | Add admin to the Manager approvers of TEST Level 1; admin submits PCB x2; remove admin again. | admin not an approver of his own request. | |
| B8 | 5.3 | PCB x2, Estimated Unit Cost 1,000 -> Submit. | Estimated Cost 2,000 kept, Routing Amount 37,000 -> Level 1. | |
| B9 | 5.3 | Delete a withdrawn request; Cancel it as admin. | Delete refused; Cancel allowed. | |
| B10 | 5.4 | Settings: Release **On Quotation Confirmation**. PCB x1 + Gas x1 + Fan Motor x1 -> Submit -> Create Parts Quotation. | Quotation Gas + Fan Motor; Waiting Customer. | |
| B11 | 5.4 | Quotation: change quantity / delete a line (refused); change a price (allowed). | | |
| B12 | 5.4 | Request -> **Customer Declined** -> Fan Motor, reason. | Fan Motor removed from the quotation, **Customer Declined**. | |
| B13 | 5.4 | store_user: Create Picking and PO. | Picking only PCB. | |
| B14 | 5.4 | Confirm the quotation. | Gas **Released** at once (On Quotation Confirmation); delivery can be validated. | |
| B15 | 5.4 | Settings: **On Payment**. PCB x1 + Gas x1 -> quotation -> confirm. As approver_w: **Approve Release Exception** (empty reason, then reason). admin: button not offered. | Released (Exception); delivery allowed. | |
| B16 | 5.4 | PCB x1 + Gas x1 -> quotation -> cancel the quotation. | Gas back to **To Quote**; new quotation possible. | |
| B17 | 5.4 | A user without Sales rights (approver_w): Create Parts Quotation. | Refused. | |
| B18 | 5.5 | PCB x1 + Gas x1 **before** quotation / decline: store_user Create Picking and PO. | Refused: quote or decline the Not Covered lines first. | |
| B19 | 5.5 | PCB x3 -> Submit -> Create Picking and PO -> validate the picking with **2** -> **Create Backorder**. | Backorder linked to the request; Issued 2, In Picking 1; Partially Issued; validate the backorder -> Issued. | |
| B20 | 5.5 | PCB x1 -> picking -> set quantity 2 -> Validate. | Refused: exceeds the approved quantity. | |
| B21 | 5.5 | Request **Copper Pipe x10** (4 left in stock after A13; no product vendor) -> approver_w decides coverage (Covered) -> Submit -> store_user Create Picking and PO. | Refused "No stock and no vendor"; store_user sets **Vendors** = Cool Parts Ltd on the line -> Create Picking and PO: picking for 4 + RFQ for 6. | |
| B22 | 5.5 | helpdesk2 (no stock rights): Create Picking and PO on an approved request. | Refused. | |
| B23 | all | Standalone request (Requisitions -> New, admin): Confirm -> Department Approve -> Approve -> Create Picking and PO -> Received. | Vendor workflow unchanged (full quantities by line action, no approval tab). | |
| B24 | all | Spot check Parts 1-4 / AMC screens. | Unchanged. | |

## C. Known open items (not failures of this test)

* B1 vendor compatibility blocker (shim only in the disposable environment).
* 5.3 manual test blocker: scheduling issue **JOB/000002 / WSE/00002** (scheduling validations
  unchanged).
* Part 3 `test_13_serial_rules`: serial-name AccessError for Helpdesk users without Inventory
  rights on a serial mismatch (Part 3 change awaiting approval).
* Serial-tracked issue (requested serial enforced at validation) is covered by the automated
  tests; the manual data has no serial-tracked spare part.
