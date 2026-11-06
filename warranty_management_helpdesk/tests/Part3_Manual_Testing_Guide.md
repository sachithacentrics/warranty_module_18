# Warranty Management – Part 3 Manual Testing Guide

## Stage 3.1 – Helpdesk Ticket and Warranty Case Creation

Database: **warranty_test** (Helpdesk and `warranty_management_helpdesk` installed).

### Test data setup

| # | Where | What |
|---|---|---|
| D1 | Warranty → Configuration → Settings | Default Start Criterion Installation; Default Warranty Duration 12 Months (the Warranty Scope Mode is not shown any more and does not limit free services – BA decision 2026-10-28) |
| D2 | Warranty → Configuration → Warranty Policies | **P3 Policy**: 12 Months, Free Service Count 3, Free Service Period 12 Months, Equal Interval, Auto-create ✔, Grace Period 30 days, Auto-expire ✔ |
| D3 | Inventory → Configuration → Product Categories | **P3 ACs** with Default Warranty Policy P3 Policy |
| D4 | Sales → Products | **P3 AC** (Service, category P3 ACs, Warranty Applicable ✔); **P3 Fan** (same, second product) |
| D5 | Contacts | Company **ABC Hotel** with child addresses **ABC Hotel – Weligama** and **ABC Hotel – Galle** (type Delivery Address) and contact **Hotel Engineer**; a second customer **Other Customer** |
| D6 | Sales | SO for ABC Hotel, Delivery Address *Weligama*, 1 × P3 AC → Confirm → Warranty Grouping (Per Sales Order) → card: Installation Date today → **Confirm Warranty** (3 Draft free services). Repeat with Delivery Address *Galle* and **P3 Fan**. One more confirmed card for **Other Customer**. |
| D7 | Helpdesk → Configuration → Helpdesk Teams | A team, e.g. **Warranty Service** |

### Test cases

#### TC-P3-001 – Pending services on a new ticket
| | |
|---|---|
| **Steps** | Helpdesk → Tickets → New: Subject "AC not cooling", Team Warranty Service, Customer **Hotel Engineer** (contact of ABC Hotel), Description "Cooling not effective". Open tab **Warranty**. |
| **Expected** | Pending Services lists the 6 Draft services of both ABC Hotel cards (not Other Customer's). Columns: reference, card, service no., due date, scheduled date, grace end, due indicator, status. The list is read-only. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-002 – Site / product / serial filters
| | |
|---|---|
| **Steps** | On the ticket set Site **Weligama**; clear it and set Product **P3 Fan**; clear it, set Product P3 AC and a Serial No. of that card's unit (if the unit has a serial). Try Site = an address of Other Customer. |
| **Expected** | Site Weligama: only the P3 AC card services. Product P3 Fan: only the Galle / Fan card. Serial: only the card whose unit has that serial (kit Indoor / Outdoor serials also match). Another customer's address is refused. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-003 – Services that are not pending
| | |
|---|---|
| **Steps** | On a card: schedule service 1 (Scheduled), reschedule service 2 (Rescheduled); then let a service become Expired (or use a card whose services are Expired / Completed / Cancelled). |
| **Expected** | Scheduled and Rescheduled services are listed; Expired, Completed, Cancelled services and Missed services after their Grace Period End are not; a card with Free Services Balance 0 shows nothing. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-004 – Create a case without services
| | |
|---|---|
| **Steps** | Ticket priority **High** (2 stars), Site Weligama, Product P3 AC → **Create Warranty Case** → Case Type **Warranty Complaint**, no pending service selected → Create. |
| **Expected** | Case **WCAS/000001…** opens: Status New, Eligibility Result empty, Customer Hotel Engineer, Site Weligama, Product P3 AC, Priority High, Customer Complaint "Cooling not effective". The ticket shows the **Warranty Cases (1)** smart button. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-005 – Create a case linking pending services
| | |
|---|---|
| **Steps** | Create Warranty Case → Case Type **Free Service**, select Service 2 in *Link Pending Services*, tick **Merged Ad-hoc Request**, Ad-hoc Request "Gas leak complaint" → Create. Open the linked free service. |
| **Expected** | Case Linked Free Services = Service 2; Warranty Card = its card; on the free service: Helpdesk Ticket = the ticket, Warranty Cases = the case. The service status, due date, scheduled date and merge status are **unchanged**. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-006 – Several cases on one ticket, all case types
| | |
|---|---|
| **Steps** | Create cases on the same ticket with each Case Type: Warranty Complaint, Free Service, AMC, Chargeable Inspection, Chargeable Repair, Replacement, Reopen/Repeat Complaint. |
| **Expected** | All are created in New; the smart button shows the count and opens the list of this ticket's cases. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-007 – Link rules on the case (approved rule C)
| | |
|---|---|
| **Steps** | On a New case tab *Linked Free Services* → Add: try a service of Other Customer, an Expired service, and Service 2 already linked to another active case. Remove a linked service. |
| **Expected** | Only pending services of the customer are offered; the others are refused ("not a pending free service" / "already linked to the active warranty case WCAS/…"). A removed service has no Helpdesk Ticket any more. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-008 – Part 2 behaviour unchanged
| | |
|---|---|
| **Steps** | With a service linked to a case: open Warranty → Free Service Calendar, Schedule / Reschedule it, and let the daily monitoring run (Settings → Technical → Scheduled Actions → *Warranty: Monitor Free Service Due Dates* → Run Manually). |
| **Expected** | Scheduling, due alerts, Missed / Expired transitions and emails work as before; linking changes nothing. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-009 – Access rights and companies
| | |
|---|---|
| **Steps** | Log in as an internal user without Helpdesk rights, as a Helpdesk User, as a Helpdesk Manager, and as a user of another company. |
| **Expected** | Internal user: sees cases (Warranty → Warranty Cases), cannot create / edit. Helpdesk User: creates and edits cases, cannot delete. Helpdesk Manager: deletes New cases only (others refused). Other company: does not see the cases. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-010 – Menus and validations
| | |
|---|---|
| **Steps** | Open Warranty → Warranty Cases and Helpdesk → Tickets → Warranty Cases; filter / group by type, status, ticket. Create a ticket without customer and look for Create Warranty Case. |
| **Expected** | Both menus list the cases (no Create button: cases come from tickets). Without customer the button is hidden. |
| **Actual Result** | |
| **Status** | |

## Stage 3.2 – Warranty Card, Serial Number and Validity Check

Use the 3.1 data. In addition:

| # | What |
|---|---|
| D8 | Product **P3 AC Serial**: Goods, Track Inventory ✔ **By Unique Serial Number**, category P3 ACs, Warranty Applicable ✔. Update Quantity: WH/Stock, serial **SN-P3-001**, qty 1. Sell 1 to ABC Hotel (Delivery Address Weligama) → Confirm → Warranty Grouping → validate the delivery (SN-P3-001) → card: Installation Date today → Confirm Warranty. Also create an unused serial **SN-P3-999** for this product. |
| D9 | A usage-based policy **P3 Usage** (12 Months, Warranty Basis Usage, Usage Limit **2000**, Usage Unit Operating Hours) on product **P3 Usage AC**; sell it to ABC Hotel and confirm its card. |
| D10 | A Sales Order for ABC Hotel with P3 AC confirmed and grouped, **card not confirmed** (Draft / Ready). |

After every **Check Eligibility** click: status **Eligibility Checked**, the Eligibility Result as
below, and a chatter note "Eligibility check (warranty card, serial, validity): …" listing each step.

#### TC-P3-011 – Card found and all checks passed
| | |
|---|---|
| **Steps** | Ticket for Hotel Engineer, Product P3 AC Serial, Serial SN-P3-001 (Warranty tab shows Warranty Card / Unit Warranty). Create Warranty Case (Warranty Complaint) → **Check Eligibility**. |
| **Expected** | Eligibility Result **empty** (passed – not yet Eligible), Warranty Card and Unit Warranty filled; chatter: card found, serial matches, card Confirmed, ticket date within the warranty period, "the payment check follows". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-012 – No warranty card
| | |
|---|---|
| **Steps** | Case for a product the customer has no card for (or Other Customer's product) → Check Eligibility. |
| **Expected** | **Manual Review**, "No warranty card found … chargeable inspection / manual review". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-013 – Several cards
| | |
|---|---|
| **Steps** | ABC Hotel has two confirmed cards for P3 AC (data D6 + one more Sales Order); case with Product P3 AC, no serial, no linked service → Check Eligibility; then select the Unit Warranty of one card → Check Eligibility. |
| **Expected** | First: **Manual Review** "Several warranty cards / units match …", no card selected automatically. After selecting the unit: passed, that card set. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-014 – Serial mismatch
| | |
|---|---|
| **Steps** | Case with Product P3 AC Serial and Serial **SN-P3-999** (not delivered on the card), select the P3 AC Serial card → Check Eligibility. |
| **Expected** | **Manual Review**, "Serial number SN-P3-999 does not match … possible rejection". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-015 – Serial missing / not tracked
| | |
|---|---|
| **Steps** | Case with Product P3 AC Serial without Serial No. → Check; then a case on a card whose unit has no serial (Product P3 Fan). |
| **Expected** | First: **Manual Review** "The serial number is required …". Second: serial check skipped, passed. Kit cards: the Indoor / Outdoor serial of the unit must be entered. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-016 – Warranty card not confirmed
| | |
|---|---|
| **Steps** | Case on the D10 card (Draft / Ready) → Check; confirm the card (Confirm Warranty) → Check again. |
| **Expected** | First: **Manual Review** "… is not confirmed yet: confirm the warranty …". After confirmation: passed. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-017 – Suspended / Expired / Cancelled card
| | |
|---|---|
| **Steps** | (Test data only) set a card status to Suspended, Expired or Cancelled (developer mode / technical access) → Check. |
| **Expected** | **Not Eligible**, "Warranty card … is Suspended / Expired / Cancelled". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-018 – Period validity by ticket date
| | |
|---|---|
| **Steps** | Case on a card whose period does not contain the ticket creation date (e.g. a card with Custom Date Range in the past, or a ticket created before the warranty start). |
| **Expected** | **Out of Warranty**, "Ticket date … is outside the warranty period …". Today's date is not used. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-019 – Usage-based warranty
| | |
|---|---|
| **Steps** | Case for P3 Usage AC → Check (no Current Usage); enter Current Usage **1500** → Check; enter **2500** → Check. |
| **Expected** | Current Usage and Usage Unit (Operating Hours) shown on the case. Empty: **Manual Review** "enter the Current Usage reading". 1500: passed. 2500: **Out of Warranty** "exceeds the usage limit 2000". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-020 – Case types, re-check and access
| | |
|---|---|
| **Steps** | Case Type AMC → Check; Chargeable Inspection / Repair case → look for Check Eligibility; correct a failed case and check again; log in as an internal user without Helpdesk rights. |
| **Expected** | AMC: **Manual Review** (AMC handled outside the warranty module). Chargeable: no Check Eligibility button (chargeable workflow, 3.6). Re-check replaces the result and adds a new chatter note. Internal user: cannot run the check. Warranty card, units and free services are unchanged by the check. |
| **Actual Result** | |
| **Status** | |

## Stage 3.3 – Payment Eligibility and Overdue Claim Handling

Use the 3.1 / 3.2 data (ABC Hotel, P3 Policy, a confirmed P3 AC card with no due problems).

| # | What |
|---|---|
| D11 | Warranty → Configuration → Settings → block **Warranty Case Payment Exceptions** → Overdue Claim Approval Users = **Approver A** and **Approver B** (internal users of the company, other than the user who runs the checks). |
| D12 | P3 Policy → **Payment Check Required** ✔ (only after the card is confirmed, or pay the invoice first: Part 1 requires a paid invoice to confirm). |
| D13 | Invoice of the card's Sales Order: Sales Order → Create Invoice → Confirm. To get **Paid**: Register Payment, then reconcile it with a bank transaction (Accounting → Bank → transaction → match the payment). Registered but not reconciled = **In Payment**: it passes when the registered payments cover the whole invoice (Q15 rev. B); register a smaller amount for a **partially covered** In Payment invoice. |
| D14 | An **overdue** invoice: Accounting → Customers → Invoices → New, Customer ABC Hotel (or one of its addresses), Invoice Date and Due Date in the past (e.g. 2026-09-01) → Confirm, not paid. |

Run each test on a Warranty Case of the P3 AC card (ticket for Hotel Engineer, Product P3 AC)
with **Check Eligibility**. The 3.2 checks must pass first. The chatter note "Eligibility check
(warranty card, serial, validity, payment): …" lists every payment step.

#### TC-P3-021 – Payment Check Required off
| | |
|---|---|
| **Steps** | P3 Policy: Payment Check Required unticked; D14 overdue invoice exists. Open the ticket's Warranty tab and the case; Check Eligibility. |
| **Expected** | Yellow **Overdue Warning** "Customer has 1 overdue invoice(s) (amount due …)" on ticket and case. Payment Eligibility **Not Required**, Eligibility Result empty (continues); chatter "Overdue Warning (information only)". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-022 – Payment passed
| | |
|---|---|
| **Steps** | Payment Check Required ✔; card invoice **Paid** (D13, reconciled); no overdue invoice (pay or cancel D14). Check Eligibility. |
| **Expected** | Payment Eligibility **Passed**, no indicator, Eligibility Result empty, chatter "… the coverage check follows". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-023 – Not settled statuses (Warning Only)
| | |
|---|---|
| **Steps** | Overdue Claim Handling **Warning Only**. Check with: no invoice posted; invoice **In Payment, partially covered** (Register Payment for half of the amount, not reconciled); Partially Paid; Not Paid; refunded (credit note). Then register the rest (still not reconciled) and check again. |
| **Expected** | Each time Payment Eligibility **Failed**, the check continues (Result empty), chatter shows the reason ("No posted invoice", "In Payment, not fully covered by the registered payments (uncovered …)", "Partially Paid", "Not Paid", "Reversed (warranty sale refunded)") and "Warning Only". After the rest is registered: **Passed** although the invoice is still In Payment. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-023a – In Payment fully covered (Q15 rev. B)
| | |
|---|---|
| **Steps** | Overdue Claim Handling **Approval Required**. Two invoices of ABC Hotel with a past due date, each with **Register Payment** for the full amount and no bank reconciliation (status In Payment); card invoice Paid or In Payment fully covered. Open the ticket / case → Check Eligibility. Then register only half of a third overdue invoice → Check. |
| **Expected** | No Overdue Warning (0 invoices, 0 amount), Payment Eligibility **Passed**, no approval activity. With the half-paid third invoice: Overdue Warning "1 overdue invoice(s) (amount due = the uncovered half)", **Pending Approval**. The invoices and payments are unchanged. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-024 – Hold
| | |
|---|---|
| **Steps** | Overdue Claim Handling **Hold**, invoice Not Paid → Check Eligibility. Pay and reconcile the invoice → Check Eligibility again. |
| **Expected** | First: Eligibility Result **Pending Payment**, red banner Payment **On Hold**, Payment Eligibility Failed, status not Rejected. After payment: **Passed**, banner gone. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-025 – Block
| | |
|---|---|
| **Steps** | Same as TC-P3-024 with Overdue Claim Handling **Block**. |
| **Expected** | Pending Payment + **Blocked**; after payment Passed, Blocked removed. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-026 – Approval Required: request
| | |
|---|---|
| **Steps** | Overdue Claim Handling **Approval Required**, invoice In Payment. As a Helpdesk user (not an approver) → Check Eligibility; click it again. |
| **Expected** | Pending Payment, **Pending Approval**, Payment Eligibility Pending, "Payment Exception Requested By" = you; one To-Do activity for Approver A and one for Approver B; the second check creates no new activities. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-027 – Approval: who may approve
| | |
|---|---|
| **Steps** | Try **Approve Payment Exception** as the requester (add yourself to the approvers first), as a user who is not an approver, as a user of another company. |
| **Expected** | The button is not shown / the action is refused for all three. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-028 – Approval and waiver
| | |
|---|---|
| **Steps** | As Approver A open the activity (or the case) → **Approve Payment Exception**. Back as the requester → Check Eligibility. |
| **Expected** | After approval: Payment Eligibility **Waived**, indicator removed, Payment Waiver Approved By / Date / Waived Payment Conditions filled, activities done, chatter "Payment exception approved by …", Eligibility Result still Pending Payment (no automatic continuation). After the new check: Waived, Result empty (continues), chatter "Payment exception approved by … for this case". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-029 – Waiver only for that case
| | |
|---|---|
| **Steps** | Create a second case on the same ticket → Check Eligibility. Then pay and reconcile the invoice and check both cases again. |
| **Expected** | The second case asks for its own approval (Pending Approval). After payment both are **Passed**; the open approval activities of the second case are closed; the waiver stays visible on the first case. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-030 – Defaults and scope
| | |
|---|---|
| **Steps** | Clear Overdue Claim Handling on the policy → Check; check the Overdue Warning with overdue invoices of another customer / company; check a free service linked to a held case. |
| **Expected** | Empty handling behaves as **Warning Only**. Only the same commercial customer and company count. The linked free service's Payment Eligibility is unchanged. Card, units and free services are not modified. |
| **Actual Result** | |
| **Status** | |

## Stage 3.4 – Service Coverage and Free Service Entitlement

| # | What |
|---|---|
| D15 | Warranty → Configuration → **Coverage Items**: create **Standard Service**, **PCB**, **Gas Refill**, **Installation Kit** (if not existing). |
| D16 | **P3 Policy** → Covered Items = Standard Service, PCB; Excluded Items = Gas Refill. Installation Kit in neither list. |
| D17 | So that payment does not stop the check: P3 Policy Payment Check Required unticked (or the card invoice Paid, no overdue invoices). |

Use a ticket for Hotel Engineer, Product P3 AC (a confirmed P3 AC card with pending free
services). Set **Requested Items** on the case, then **Check Eligibility**. The chatter note is
now "Eligibility check (warranty card, serial, validity, payment, coverage, free service): …".

#### TC-P3-031 – All covered
| | |
|---|---|
| **Steps** | Warranty Complaint case, Requested Items = Standard Service, PCB → Check Eligibility. |
| **Expected** | Eligibility Result empty, status Eligibility Checked (not Eligible). Chatter: "All requested items are covered", "Not a free service request …", "… the repeated failure check follows". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-032 – Partial coverage
| | |
|---|---|
| **Steps** | Requested Items = Standard Service, Gas Refill → Check. |
| **Expected** | Eligibility Result **Partial**; chatter lists "Covered: Standard Service" and "Excluded (chargeable quotation …): Gas Refill"; no free service / repeated failure step. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-033 – Only excluded
| | |
|---|---|
| **Steps** | Requested Items = Gas Refill → Check. Then change to Standard Service → Check. |
| **Expected** | First **Not Eligible**; after the change the result is reset (empty). |
| **Actual Result** | |
| **Status** | |

#### TC-P3-034 – Undefined item / both lists
| | |
|---|---|
| **Steps** | Requested Items = Standard Service, Installation Kit → Check. Then add PCB to Excluded Items too, Requested Items = PCB → Check. |
| **Expected** | **Manual Review** "Coverage not defined in policy P3 Policy for: Installation Kit"; then **Manual Review** "PCB is both a Covered and an Excluded Item". (Remove PCB from Excluded Items afterwards.) |
| **Actual Result** | |
| **Status** | |

#### TC-P3-035 – No Requested Items
| | |
|---|---|
| **Steps** | Case without Requested Items (also a Free Service case with a linked service) → Check. |
| **Expected** | **Manual Review** "No Requested Items: select the requested services / items and check again". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-036 – Card without policy (P5)
| | |
|---|---|
| **Steps** | Ticket for a product whose confirmed card has no Warranty Policy (own values, e.g. a card with Policy Source Product / Category / Company) → case with Requested Items → Check. |
| **Expected** | **Manual Review** "Warranty card … has no warranty policy: the coverage cannot be resolved"; the card is not changed. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-037 – Free service available
| | |
|---|---|
| **Steps** | Create Warranty Case with case type **Free Service**, select an available pending free service, Requested Items = Standard Service → Check. Repeat with a Warranty Complaint case linked to another pending service. |
| **Expected** | Result empty; chatter "Free service entitlement available: WSE/…". Service status, scheduled date and due date unchanged. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-038 – Free Service without linked service
| | |
|---|---|
| **Steps** | Free Service case with no service selected, Requested Items = Standard Service → Check. |
| **Expected** | **Manual Review** "select the available free service on the case and check again"; no service is linked automatically. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-039 – Linked service no longer available
| | |
|---|---|
| **Steps** | Free Service case linked to a service that later becomes Expired or Missed after its grace period (e.g. a service whose due date + grace has passed and the expiry scheduled action has run) → Check. |
| **Expected** | **Not Eligible** "Free service WSE/… is no longer available (status, grace period or balance) - convert to chargeable service or reject". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-040 – Rules kept
| | |
|---|---|
| **Steps** | (a) Link the same free service on a second case. (b) Free Service case linked to a service of another card of the customer together with one of the case card. (c) P3 Policy Payment Check Required + Hold with an unpaid invoice → Check a case with Requested Items = Gas Refill. |
| **Expected** | (a) Refused (one active case per service). (b) **Manual Review** "belongs to another warranty card". (c) **Pending Payment** / On Hold; the coverage step is not run. |
| **Actual Result** | |
| **Status** | |

## Stage 3.5 – Repeated Failure Check and Final Eligibility

| # | What |
|---|---|
| D18 | Users **GM** and **Service Manager** (internal). Warranty → Configuration → Settings → block *Warranty Case Payment Exceptions and Escalations* → **Repeated Failure Escalation Users** = GM, Service Manager (not admin, who runs the checks). |
| D19 | **P3 Policy** → Controls: **Repeated Failure Threshold = 2**, **Repeated Failure Period (days) = 90**. Keep D15–D17 (covered items, payment not stopping). |
| D20 | A **new** confirmed P3 AC card with quantity 1 for ABC Hotel (so earlier test cases do not count), and a ticket for Hotel Engineer, Product P3 AC, with the card selected on the case. |

Every case needs Requested Items = Standard Service. The chatter title is now "Eligibility check
(…, repeated failure): …" and shows the physical unit, the failure count and the counted cases.

#### TC-P3-041 – No escalation rule
| | |
|---|---|
| **Steps** | P3 Policy threshold 0 → Warranty Complaint case → Check Eligibility. |
| **Expected** | Eligibility Result **Eligible**, status Eligibility Checked (not Approved), chatter "No repeated failure escalation rule … check not needed" and "Eligible - warranty case ready for the Service Job". Then set threshold 2 again. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-042 – Below threshold
| | |
|---|---|
| **Steps** | Case 1 and case 2 (Warranty Complaint / Replacement) of the D20 card → Check each. |
| **Expected** | Both **Eligible**; Failures in Period 1 then 2; Repeated Failure unticked. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-043 – Threshold exceeded
| | |
|---|---|
| **Steps** | Case 3 (Reopen/Repeat Complaint) → Check; click Check again. |
| **Expected** | **Manual Review**, Repeated Failure ✔, Failures in Period 3, red banner "Escalated - repeated failure", Escalation Requested By = admin; one To-Do for GM and one for Service Manager; the second check creates no new activities. Status not Approved. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-044 – Who may confirm
| | |
|---|---|
| **Steps** | Add admin to the escalation users; on case 3 try **Confirm Warranty (Repeated Failure)** as admin (requester), as a user who is not an escalation user, as a user of another company. Remove admin again. |
| **Expected** | Button not shown / action refused in all three cases. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-045 – Confirmation
| | |
|---|---|
| **Steps** | Log in as GM → activity / case 3 → **Confirm Warranty (Repeated Failure)**. As admin → Check Eligibility. |
| **Expected** | After confirming: banner gone, Warranty Confirmed By = GM + date, activities done, chatter "Warranty confirmed despite repeated failure by GM", result still Manual Review. After the new check: **Eligible**, Repeated Failure stays ✔, chatter "Warranty confirmed by GM … for this case". A 4th case escalates again (confirmation only for case 3). |
| **Actual Result** | |
| **Status** | |

#### TC-P3-046 – Not counted
| | |
|---|---|
| **Steps** | On the D20 unit create: a Free Service case (with a free service), an AMC case, a Chargeable Inspection case; reject one complaint (if a Reject action is not available yet, skip the rejected part). On a new card: two complaints with a ticket date older than 90 days (not possible from the UI: skip or use an older ticket). |
| **Expected** | They do not raise Failures in Period. A Free Service case checked after 3 failures escalates ("this case not a failure", count = earlier failures). |
| **Actual Result** | |
| **Status** | |

#### TC-P3-047 – Kit / serial (one system)
| | |
|---|---|
| **Steps** | Kit card (warranty_test with MRP): complaint 1 with the **Indoor** serial, complaint 2 and 3 with the **Outdoor** serial of the same unit → Check case 3. |
| **Expected** | Physical unit line shows the unit with both serials; Failures in Period 3 → escalation. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-048 – Several units (Q37)
| | |
|---|---|
| **Steps** | Card with quantity 3 of a product, a case without serial / Unit Warranty → Check. Then select Unit Warranty …-01 → Check. |
| **Expected** | First **Manual Review** "Physical unit not identified (warranty card … has 3 units …): select the Unit Warranty or serial number". After selecting the unit: only the failures of unit -01 are counted; earlier cases without unit on that card are listed "Not attributable to a physical unit, not counted". |
| **Actual Result** | |
| **Status** | |

#### TC-P3-049 – Other units / customers
| | |
|---|---|
| **Steps** | Complaints of another customer, of another unit of the customer, of another company. |
| **Expected** | Not counted. A Unit Warranty of another product selected on the case gives Manual Review. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-050 – Earlier stop / cleared
| | |
|---|---|
| **Steps** | On an escalated case set Requested Items = Gas Refill → Check; back to Standard Service; remove / reject an earlier failure so that the count is 2 → Check. |
| **Expected** | With Gas Refill: Not Eligible, escalation banner removed, open escalation activities closed (repeated failure step not run). With count 2: **Eligible**, Repeated Failure unticked. |
| **Actual Result** | |
| **Status** | |

## Stage 3.6a – Warranty Case Approval

| # | What |
|---|---|
| D21 | Users **Approver A**, **Approver B** (internal; Helpdesk User to open the cases from the Warranty Cases menu). Warranty → Configuration → Settings → block *Warranty Case Approvals and Exceptions* → **Warranty Case Approval Users** = Approver A, Approver B, **admin** → Save. |
| D22 | A case that becomes **Eligible**: created and checked by **admin** (Requested Items = Standard Service, payment not stopping, no repeated failure escalation). |

#### TC-P3-051 – Approval activities
| | |
|---|---|
| **Steps** | Admin creates the case and runs Check Eligibility → Eligible. Click Check Eligibility again. |
| **Expected** | One To-Do "Approve warranty case WCAS/…" for Approver A and one for Approver B, **none for admin** (creator and checker). Chatter "Case approval requested from …". The second check creates no new activities ("already requested"). |
| **Actual Result** | |
| **Status** | |

#### TC-P3-052 – Button visibility
| | |
|---|---|
| **Steps** | Open the case as admin, as a user who is not an approval user, as Approver A. Then set Requested Items = Gas Refill → Check. |
| **Expected** | Only Approver A / B see **Approve Case**. After Gas Refill (Not Eligible): button gone for everybody, approval activities closed ("no longer Eligible"). |
| **Actual Result** | |
| **Status** | |

#### TC-P3-053 – No self-approval
| | |
|---|---|
| **Steps** | Back to Standard Service → Check as admin. Let Approver B (with Helpdesk User) run Check Eligibility, then try to approve as Approver B. |
| **Expected** | Admin never sees the button (creator). After Approver B ran the check: B has no button / is refused; activities now for Approver A and **admin is still excluded as creator**. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-054 – Approve
| | |
|---|---|
| **Steps** | Admin checks again → Eligible. Approver A → open the activity / case → **Approve Case**. |
| **Expected** | Status **Approved**, Eligibility Result Eligible, Approved By = Approver A, Approval Date set, activities done, chatter "Warranty case approved by Approver A - revalidation passed" with the list of checks. Card, units and linked free services unchanged; no Service Job. Check Eligibility is no longer shown. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-055 – Revalidation fails
| | |
|---|---|
| **Steps** | New Eligible case. Before approving: P3 Policy Payment Check Required ✔ + Approval Required with an unpaid invoice (or Hold). Approver A → Approve Case. |
| **Expected** | Yellow notification "Warranty case not approved…"; status stays Eligibility Checked, result **Pending Payment**; **no** payment approval activity created; approval activities closed; chatter "Approval refused by revalidation" with "not requested during the approval revalidation - run Check Eligibility". Restore the policy afterwards. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-056 – Waiver / confirmation kept
| | |
|---|---|
| **Steps** | A case with an approved payment exception (3.3) or a repeated failure confirmation (3.5) that is now Eligible → Approver A → Approve Case. |
| **Expected** | Revalidation passes (Payment Waived / Warranty confirmed for this case) → **Approved**. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-057 – Approver list changes
| | |
|---|---|
| **Steps** | Eligible case with activities for A and B. Remove Approver B from the setting → B tries Approve Case. Add a new user Approver C → admin runs Check Eligibility. |
| **Expected** | B: no button / refused. After the check: the activity of B closed ("no longer an authorized approver"), the activity of A kept (no duplicate), new activity for Approver C; chatter lists closed / kept / requested. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-058 – Settings / company
| | |
|---|---|
| **Steps** | Try to add a portal user or a user of another company to Warranty Case Approval Users; as a user of another company try to open / approve the case. |
| **Expected** | Refused ("must be active internal users allowed in that company"); the case is not visible / not approvable for the other company. |
| **Actual Result** | |
| **Status** | |

## Stage 3.6b – Claim Rejection

Use the 3.6a setup (D21: Warranty Case Approval Users = Approver A, Approver B, admin). Admin
creates the cases and runs Check Eligibility; Approver A rejects.

#### TC-P3-059 – Who may reject
| | |
|---|---|
| **Steps** | Admin: case with Requested Items = **Gas Refill** → Check (Not Eligible). Look for **Reject Case** as admin, as a non-approver, as Approver A. |
| **Expected** | Only Approver A / B see **Reject Case**; admin (creator / checker) and non-approvers do not. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-060 – Which results
| | |
|---|---|
| **Steps** | Cases with result Eligible, Partial (Standard Service + Gas Refill), Pending Payment and New (not checked); a case with Manual Review (e.g. Installation Kit) and one Out of Warranty. |
| **Expected** | Reject Case only for **Not Eligible, Out of Warranty, Manual Review**; not shown for Eligible, Partial, Pending Payment or New. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-061 – Reason and note
| | |
|---|---|
| **Steps** | Approver A → Reject Case → reason **Other** without note → Reject. Then add a note → Reject. |
| **Expected** | Without note: refused ("Enter a note for the rejection reason Other"), case unchanged. With note: status **Rejected**, Rejection Reason / Note / Rejected By / Rejection Date shown, chatter "Warranty case rejected by Approver A: Other" with the note. The Helpdesk ticket stage is unchanged. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-062 – Free services released
| | |
|---|---|
| **Steps** | Free Service case linked to a free service that is no longer available (Not Eligible) → Approver A rejects (No Free Service Available). Open the free service; create a new case and select it. |
| **Expected** | Chatter "Free services released for another case (status unchanged): WSE/…"; the service status is unchanged, its Helpdesk Ticket is cleared, and it can be linked to a new case (if still pending). |
| **Actual Result** | |
| **Status** | |

#### TC-P3-063 – Open escalation closed
| | |
|---|---|
| **Steps** | Case escalated for repeated failure (3.5, Manual Review + banner, GM activity) → Approver A rejects (Duplicate Complaint). |
| **Expected** | Rejected; GM activity closed; escalation banner gone. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-064 – Final
| | |
|---|---|
| **Steps** | On the Rejected case try to edit fields, Check Eligibility, Approve / Reject again, delete it; post a chatter message. |
| **Expected** | Fields read-only / change refused, no Check / Approve / Reject buttons, deletion refused; chatter messages still possible. The case is not counted as a repeated failure. |
| **Actual Result** | |
| **Status** | |

## Stage 3.6c – Chargeable Conversion and Partial Coverage

| # | What |
|---|---|
| D23 | Products (Sales → Products): **Gas Refill Service** (service, price 2,500) and **Inspection Fee** (service). Warranty → Configuration → Coverage Items → **Gas Refill**: Product = Gas Refill Service. |
| D24 | Helpdesk → Configuration → Teams → your team → After-Sales → **Warranty Inspection**: Inspection Required ✔, Inspection Product = Inspection Fee, Inspection Amount = 850 (used in TC-P3-072). |
| D25 | Users: **admin** (Helpdesk + Sales) creates / checks cases and quotations; **Approver A** approves; a Helpdesk user **without Sales** rights for TC-P3-073. |

#### TC-P3-065 – Partial → Excluded Items
| | |
|---|---|
| **Steps** | Case with Requested Items = Standard Service + Gas Refill → Check Eligibility. |
| **Expected** | Result **Partial**; tab **Excluded Items**: Gas Refill, decision **Quotation Required**; yellow banner "Excluded items: waiting for the customer decision…"; button **Create Excluded Items Quotation**; no Convert to Chargeable for Partial. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-066 – Create excluded items quotation
| | |
|---|---|
| **Steps** | Click **Create Excluded Items Quotation**. |
| **Expected** | A **Draft** quotation opens: customer ABC Hotel, Warranty Case = WCAS/…, one line Gas Refill Service. Case status still Eligibility Checked / Partial; decision **Waiting Customer Approval**, Quoted Qty 1; **Quotations** smart button (1). No email is sent; no Service Job. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-067 – Customer approves
| | |
|---|---|
| **Steps** | On the quotation set the quantity (e.g. 2) → **Confirm**. Back on the case → Check Eligibility. Then Approver A → **Approve Case**. |
| **Expected** | Decision **Customer Approved (Chargeable)**, Confirmed Qty 2; result **Eligible** (chatter: confirmed qty, "the excluded items stay chargeable"); banner gone; Approver A can approve → Approved. Gas Refill is still an Excluded Item of the policy. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-068 – Customer declines
| | |
|---|---|
| **Steps** | New Partial case → quotation → on the case Excluded Items line click **Customer Declined** (or on the quotation **Customer Declined (Warranty)**) → empty reason, then a reason. |
| **Expected** | Empty reason refused. With reason: decision **Customer Declined**, Declined By / On / reason shown; the line is removed and the quotation **cancelled** (no other line); chatter "Customer declined Gas Refill…". Check Eligibility → **Eligible**. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-069 – Undo decline
| | |
|---|---|
| **Steps** | On the declined item → **Undo Decline** → Check. Decline again → Check → Approve Case → try Undo Decline. |
| **Expected** | After undo: **Quotation Required**, result Partial. After approval: Undo Decline not available / refused. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-070 – Internal cancel / replace
| | |
|---|---|
| **Steps** | New Partial case → quotation → **Cancel** the quotation (internal). Check Eligibility. Create Excluded Items Quotation again. Set its line quantity to 0. |
| **Expected** | After cancel: decision **Quotation Required** (not Declined), result Partial; the new quotation links the item again (Waiting); Quotations count 2. Quantity 0 → Quotation Required. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-071 – Confirmed order protected
| | |
|---|---|
| **Steps** | Confirmed excluded items quotation → try Customer Declined on that item. Remove the product from the Gas Refill coverage item and try Create Excluded Items Quotation on a new Partial case. |
| **Expected** | Decline refused ("…on the confirmed order … already approved"). Without product: error "Set a Product on the coverage item(s) Gas Refill … or record Customer Declined". (Restore the product.) |
| **Actual Result** | |
| **Status** | |

#### TC-P3-072 – Convert to Chargeable
| | |
|---|---|
| **Steps** | Case with Requested Items = Gas Refill only → Check (Not Eligible) → **Convert to Chargeable** (wizard default Chargeable Type = Excluded Items) → Convert. |
| **Expected** | Status **Chargeable**, Chargeable Type Excluded Items, Converted By / Date; Case Type unchanged; Draft quotation with **Inspection Fee 850** + **Gas Refill Service**; chatter "Converted to chargeable (Excluded Items)… (no Service Job)"; Check Eligibility no longer available. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-073 – Chargeable case types / rights
| | |
|---|---|
| **Steps** | New case type **Chargeable Repair** (team Inspection Required off) → Convert to Chargeable. Then team Inspection Required on, a new **Chargeable Inspection** case → Convert as a Helpdesk user **without Sales** rights. |
| **Expected** | Repair: Chargeable, no quotation (chatter: create it from the Quotations button). Inspection without Sales rights: refused ("Creating quotations requires Sales rights"), case stays New. |
| **Actual Result** | |
| **Status** | |

#### TC-P3-074 – Other company / users
| | |
|---|---|
| **Steps** | A user of another company opens the case; a user without Helpdesk rights tries Customer Declined / Convert. |
| **Expected** | Not visible / refused. |
| **Actual Result** | |
| **Status** | |

## Warranty Card selection fix

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-CS-01 | New case with product *Company AC*: open the **Warranty Card** dropdown. The customer has a Confirmed, a Draft and an Expired card, plus a card of another product. | Only the Confirmed card of that product, customer and company. | | |
| TC-CS-02 | Customer with a multi-product card (e.g. AC + Fan on one SO). Case product = Fan. | The multi-product card is offered; **Unit Warranty** only shows the Fan unit. | | |
| TC-CS-03 | Set the **Serial Number** (or a kit Outdoor serial). | Only the card / unit holding that serial. | | |
| TC-CS-04 | Select a card + unit, then change **Product** to another product. | Card and unit are cleared. | | |
| TC-CS-05 | Case with no card, the customer has only a Draft card -> **Check Eligibility**. | Manual Review "not confirmed yet" and the Draft card shown on the case (Q8 unchanged); Expired card -> Not Eligible (Q14). | | |

### Automated tests

`warranty_management_helpdesk/tests/test_warranty_case.py` (9 tests, stage 3.1) and
`test_warranty_case_eligibility.py` (9 tests, stage 3.2: find card, not found / several, serial
rules, card status, period by ticket date, usage, case types, re-check / log, access) and
`test_warranty_case_payment.py` (9 tests, stage 3.3: not required, passed, not settled statuses,
hold / block cleared, approval and waiver, missing handling, overdue scope, settings, multi-company, plus 3 tests for
Q15 rev. B: fully covered In Payment, partial / shared payment, currency and cancelled payments) and
`test_warranty_case_coverage.py` (10 tests, stage 3.4: covered, partial / not eligible, undefined / no items,
card without policy, free service available / missing / unavailable / another card, rule C, payment stop) and
`test_warranty_case_repeated_failure.py` (10 tests, stage 3.5: no rule, threshold / escalation, period, failure types,
confirmation, kit unit, multi-unit card, other customers / units, earlier stop, settings / multi-company) and
`test_warranty_case_approval.py` (8 tests, stage 3.6a: activities, button / refused results, no self-approval,
approval, revalidation failure, waiver / confirmation kept, approver changes, settings / multi-company) and
`test_warranty_case_rejection.py` (6 tests, stage 3.6b: who / which results, reason / history, activities closed,
free services released, final status, multi-company, button visibility) and
`test_warranty_case_chargeable.py` (9 tests, stage 3.6c: excluded items quotation, approval, decline / undo,
internal cancel, decline rules, conversion, conversion rules, revalidation, multi-company). Run together with the Part 1/2 suites:

```
odoo-bin -c odoo.conf -d warranty_test -u warranty_management_helpdesk \
  --test-tags /warranty_management,/warranty_management_mrp,/warranty_management_helpdesk \
  --stop-after-init
```
`tests/test_warranty_case_card_selection.py` (6 tests: card choices, multi-product card / units,
serial + kit serials, server validation, Q8 / Q14 lookup, on-change clearing).

## Is Warranty on Helpdesk tickets (18.0.1.0.3, 2026-10-29)

| # | Steps | Expected | Actual | Status |
|---|---|---|---|---|
| TC-IW-01 | New ticket, Is Warranty unticked. | No Warranty tab, no Create Warranty Case button. | | |
| TC-IW-02 | Tick Is Warranty, no customer. | Warranty tab shown; no Create Warranty Case button. | | |
| TC-IW-03 | Customer without any warranty card (or only Draft / Pending Installation cards). | Info "no confirmed warranty card"; Available Warranty Cards empty; no button. | | |
| TC-IW-04 | Customer with a confirmed card. | Available Warranty Cards lists only that customer's confirmed cards of the ticket company; Product offers only their products; button shown; case created as before (eligibility / approval unchanged). | | |
| TC-IW-05 | Select a product, then change the customer to one without cards. | Product / serial cleared, Warranty Card empty, button hidden. | | |
| TC-IW-06 | Existing ticket with a warranty case after the update; untick Is Warranty. | Ticket ticked by the update; after unticking the tab is hidden but the Warranty Cases smart button / cases remain. | | |
| TC-IW-07 | Warranty ticket: type a free-text **Site Address**, save; change the customer and back. | Address saved; no Site (contact) field on the ticket; no error; pending services and Create Warranty Case unchanged (address not used for matching). | | |
