# Part 7 Stage 2: manual testing guide (Indoor Unit and Outdoor Unit Replacement)

Run on a test database, only after `warranty_management_repair` has been upgraded there with your approval. Version 18.0.1.4.2.

Indoor and Outdoor replacements need **Manager / GM approval** and no Finance approval (SRS 11.2, Figure 3; see `doc/part7_replacement_design.md`).

Keep the operation types, location and users from Stage 1 (Stage 1 guide, section A). Use two users: a **Coordinator** who submits, and an **Approver** in Replacement GM Approvers. Full Product: Finance Approval is not used here; section L checks that Full Product still needs it.

## A. Products and stock

1. **Components:** create two storable products, tracked By Unique Serial Number, for example **AC Indoor Unit** and **AC Outdoor Unit**.
2. **Kit:** create a product **AC Split Kit** (Warranty Applicable, with your warranty policy, tracking None). A kit delivery moves the components, so the kit itself needs no serial.
3. **Bill of Materials on the kit:** Type **Kit**, quantity 1. Lines: AC Indoor Unit quantity 1, Warranty Component Role **Indoor Unit**; AC Outdoor Unit quantity 1, Warranty Component Role **Outdoor Unit**.
4. **Stock in WH/Stock (Inventory > Physical Inventory, or a receipt):**
   - AC Indoor Unit: IN-001 (sold), IN-101, IN-102, IN-103
   - AC Outdoor Unit: OUT-001 (sold), OUT-101, OUT-102, OUT-103
   - Add more spare serials to repeat section F, one per policy.
5. **WH/Stock** must be the default source of the Replacement Delivery operation type, as in Stage 1.

## B. Settings

1. Settings > Warranty: Replacement GM Approvers holds the Approver. There is no Indoor / Outdoor Finance Approval setting.
2. Leave **Fixed Extension Added To** empty until section F.
3. Warranty Policy of the card: Replacement Date Policy empty, Replacement Return empty.

## C. Starting data

1. Sell 1 AC Split Kit, deliver IN-001 and OUT-001, then confirm the warranty card.
2. Write down the card number, unit number and dates. Check the unit: Indoor Serial IN-001, Outdoor Serial OUT-001, Serial(s) both.
3. Create a Helpdesk ticket with Is Warranty ticked, Product **AC Split Kit** and Serial No. **IN-001**. Warranty Card and Unit Warranty fill in by themselves. Create the warranty case from the ticket, Check Eligibility, then Approve Case.

In the later sections, "a case with serial X" always means this: the kit as Product and the Indoor or Outdoor serial as Serial No.

## C1. Kit serials on the ticket, wizard and case

Needs `warranty_management_helpdesk` 18.0.1.1.6.

| Step | Expected |
|---|---|
| Ticket: Product = the kit, open Serial No. | The Indoor and Outdoor serials of this customer's kit units are listed. Serials of the kit product itself also appear, if any exist. Spare component serials in stock and other customers' serials do not |
| Select the Indoor serial | Warranty Card and Unit Warranty fill in |
| Select the Outdoor serial instead | Same card and unit |
| Change Product to a non-kit product | Serial No. is cleared |
| Clear Product, select the Indoor serial, then set Product = the kit | Serial No. stays |
| Create Warranty Case: open Serial No. in the wizard, then on the case | The same list as the ticket |
| Single (non-kit) product on a ticket | Its serials are listed as before |
| A serial of the kit product itself (if you created one) | Warranty Card stays empty; Check Eligibility gives Manual Review |

## D. Validations

1. Case > **Request Replacement**. Expect Type = Indoor Unit, Old Serial IN-001, Product AC Indoor Unit, Other Serial (Not Changed) OUT-001.
2. **New Serial list:** only spare AC Indoor Unit serials in WH/Stock. No outdoor serial, no IN-001.
3. Select IN-101, Reason Compressor Failure, Save.
4. Change Type to **Outdoor Unit** and Submit. Refused: the case was checked on IN-001, not on the active outdoor serial. Change Type back to Indoor Unit and New Serial back to IN-101.
5. Change Type to **Full Product** and Submit. Refused: a kit uses the Indoor Unit or Outdoor Unit type. Change it back.
6. Reason Goodwill: refused. Change it back to Compressor Failure.
7. After each refusal: status stays Draft, and no transfer exists.

## E. Indoor Unit replacement: main flow (Continue Original)

1. Submit as Coordinator. Status **Submitted**, no Approve button for the Coordinator, **no transfers**, and the Approver has a To-Do "approval needed (Manager / GM)". The unit still shows IN-001 and OUT-001.
2. As a user outside Replacement GM Approvers (a Finance approver too): no Approve or Reject button. As the Approver, Approve: status **Approved**, GM Approved By and On filled, Finance fields empty, one Return Picking and one Replacement Delivery exist. The chatter shows decision Approved, the approver and the date.
3. **Second request:** create another Indoor Unit request on this case with IN-102 and Submit. Refused: the unit already has an open replacement. Delete that draft.
4. Open both transfers. Return: **AC Indoor Unit**, IN-001, customer to Warranty Return. Delivery: **AC Indoor Unit**, IN-101.
5. **Order:** validate the delivery first: refused, the return comes first.
6. **Before any stock validation:** the unit still shows IN-001 and OUT-001.
7. Validate the return, then the delivery. Status Done; Updated Card Generated = Yes.

Check afterwards:

| Check | Expected |
|---|---|
| Card and unit numbers | Same as section C |
| Indoor Serial / Outdoor Serial | IN-101 / **OUT-001** |
| Serial(s) of the unit | IN-101 and OUT-001 |
| Card Indoor / Outdoor Serial No. (single-unit card) | IN-101 / OUT-001 |
| Unit Start and End dates, card header dates | Unchanged |
| Indoor Start / End Date on the unit form | Not shown: Continue Original changes nothing |
| Warranty Date History | One Replacement row, naming Indoor Unit, IN-001 and IN-101 |
| Replacements tab of the card | Type Indoor Unit, IN-001 to IN-101 |
| Chatter of the replacement | Says OUT-001 and its dates did not change |
| PDF | Updated Copy, serials IN-101 and OUT-001 |
| Sales Order | Delivered and invoiced quantities and the original delivery unchanged |
| Inventory | IN-001 in Warranty Return, IN-101 at the customer, OUT-001 still at the customer |
| Replacement Cost | The valuation of IN-101 |

## F. Serial-specific dates

Use a new sale, card and case for each row, or the same unit with the next spare serial. Set the policy on the draft request. Use a role not yet given its own dates, unless the row says otherwise.

| Policy on an Outdoor Unit request | Outdoor dates on the unit form | Indoor serial | Unit and header dates |
|---|---|---|---|
| Continue Original | Not shown | Unchanged | Unchanged |
| Restart from Replacement Date | Start = replacement date; End = replacement date + duration - 1 day | Unchanged | Unchanged |
| Remaining Period Only | Not shown; Remaining Days filled on the request | Unchanged | Unchanged |
| Add Fixed Extension | First refused while **Fixed Extension Added To** is empty; then End = base + extension | Unchanged | Unchanged |
| Manual Approval-Based Date | End = the date the Approver enters before approving; Approve refused without date and reason; both read-only for the Coordinator and after approval | Unchanged | Unchanged |

For each row with new dates, also check:

1. The PDF shows a second table with both serials, each with its own dates, and the header dates are labelled Original.
2. Warranty Date History shows the old and new dates of that serial.

## G. Eligibility by serial

The check uses the ticket creation date, so the unit dates are moved into the past instead of waiting.

1. Take a card where the outdoor serial got **Restart** (section F), so its dates start today.
2. Before moving any dates, open a new ticket and case with the **indoor** serial and Check Eligibility. It passes the validity step, as before.
3. On the card, use **Correct Warranty Dates** (group Warranty: Date Correction) with a start date older than the warranty duration, so the unit end date is before today. Test database only.
4. Open a new ticket and case for each row below and use Check Eligibility.

| New case with | Expected |
|---|---|
| New outdoor serial | **Passes** the validity step; the chatter note shows the outdoor dates |
| Indoor serial (not replaced) | **Out of warranty**: the unit dates apply; it was not extended |
| Old outdoor serial | The serial is no longer found on the card |

## H. Later replacements on the same unit

1. Indoor already replaced (IN-101). Open a new case with **OUT-001**. Request Replacement: Type Outdoor Unit. Complete it with OUT-101.
2. Expect IN-101 and OUT-101 on the unit, both replacement serials accepted on save, and one more history row.
3. Open a new case with IN-101 and replace it with IN-102. The Old Serial is IN-101; Previous dates are the dates in force for IN-101.
4. Open requests for the Indoor and the Outdoor serial at the same time, on two cases: both may be submitted. Each moves only its own serial.

## I. Refusals

1. **Serial on another warranty:** a serial already on another card is not offered in New Serial.
2. **Stock:** select a spare serial, then move it out of WH/Stock before Submit: refused.
3. **Same New Serial on two open requests:** second Submit refused.
4. **Direct edit:** on a Confirmed card the Indoor / Outdoor serials cannot be edited.
5. **Wrong serial on a transfer:** on the Return, change IN-001 to another serial and Validate: refused. On the Delivery, change the serial and Validate: refused.
6. **Unit without a role:** kit whose BoM has no Warranty Component Role: refused. Non-kit product with type Indoor Unit: refused.
7. **Repair open:** Repair Order on the old indoor serial still in progress: refused. A Repair Order on the outdoor serial does not block an indoor replacement.

## J. Recovery (Stage 1 K, on a role)

Only a user in Replacement GM Approvers, other than the submitter, sees Reject and Change New Serial, each with a required reason.

0. **Reject while Submitted:** status Rejected with the approver and reason in the chatter, no transfers, serials unchanged.
1. **Change New Serial** after the return: old delivery Cancelled, one new delivery of the same component.
2. **Reject** after the return: delivery Cancelled, return stays Done, the unit keeps both serials and all dates, and a To-Do asks to resolve the old unit. Case completion is refused until it is resolved.
3. **Create Missing Transfers:** only when a transfer is missing; a second click creates nothing.

## J1. A request approved under the earlier version (WR/000002)

WR/000002 reached Approved under 18.0.1.4.1, with no GM signature. After the upgrade:

1. Its form shows a warning that the Manager / GM approval is missing. Its status and transfers have not changed.
2. Validating RPL/IN/00002 or RPL/OUT/00002 is refused. There is no Change New Serial button.
3. To close it, the Approver enters a Rejection Reason and uses Reject. Both open transfers become Cancelled, IND-003 and OUT-003 stay on the unit, and IND-004 is free again.

## K. Correct Warranty Dates on a kit

Use a card where the outdoor serial has its own dates.

1. Use Correct Warranty Dates to change the card dates.
2. Unit Start / End and the card header change as usual.
3. **Outdoor dates stay** as set by the replacement, and the indoor serial follows the corrected unit dates.

## L. Regression

1. **Stage 1:** a Full Product replacement of a non-kit product behaves as before: refused while Full Product: Finance Approval or the GM Approvers are empty, then GM and Finance Approve, and Correct Warranty Dates keeps its unit dates.
2. **New kit sale:** delivery allocates indoor and outdoor serials to units as before, including a backorder on 3 units, and the serial correction on a Draft card.
3. **Eligibility of a kit without any replacement:** unchanged.
4. **Other workflows:** Repair (Part 6.1), Backup (Part 6.2), and Material Request claims (Part 5.8) behave as before.
5. **Free services on a kit with serial dates:** the due dates and the service eligibility follow the unit and card dates, unchanged.
