# Part 7 Stage 3 Phase 2: manual testing guide (Goodwill Replacement)

Run on a test database, only after `warranty_management_repair` has been upgraded there with your approval. Version 18.0.1.4.4.

Goodwill Replacement is for one serialized product, on a case that is Not Eligible or Out of Warranty. It needs Manager / GM approval and no Finance approval. The approver decides the warranty end date. The case keeps its eligibility result.

## A. Users and settings

1. Use two users: a **Coordinator** with Helpdesk and Inventory rights, and an **Approver** in Settings > Warranty > Replacement GM Approvers. There is no new setting.
2. Keep the Replacement Return and Delivery Operation Types from Stage 1.
3. **Stock:** a serial-tracked, warranty-applicable product with a sold serial (`GW-OLD`) on a Confirmed card, and a spare serial (`GW-NEW`) in WH/Stock.

## B. Out of Warranty case

1. Make the warranty out of date on a test card: use **Correct Warranty Dates** with a start date older than the warranty duration. Test database only.
2. Create a Helpdesk ticket with Is Warranty, the Product and Serial `GW-OLD`. Create the case with a Case Type, add a requested item, and use Check Eligibility.
3. Expect the case to show Eligibility Checked with result **Out of Warranty**, and a **Request Goodwill Replacement** button. There is no Request Replacement button.

## C. Main flow

| # | Step | Expected |
|---|---|---|
| 1 | Coordinator: Request Goodwill Replacement | Type Goodwill, Reason Goodwill, Date Policy Manual Approval-Based Date (all three cannot be changed to another value), Old Serial `GW-OLD`, Case Eligibility Result Out of Warranty |
| 2 | Select New Serial `GW-NEW`, leave Reason Details empty, Save | Reason Details is required |
| 3 | Enter Reason Details, Save, Submit | Status **Submitted**, no transfers, Serial still `GW-OLD` |
| 4 | Chatter of the replacement, ticket, case and card | Says the Goodwill exception, the result Out of Warranty stays as checked, and the exception reason |
| 5 | Coordinator on the form | No Approve or Reject button |
| 6 | A Finance approver who is not a GM approver | No Approve or Reject button |
| 7 | Approver: To-Do | "approval needed (Manager / GM)" |
| 8 | Approver: Approve with no Manual End Date | Refused: enter the date and reason |
| 9 | Approver: enter Manual End Date and Manual Date Reason, Approve | Status **Approved**, GM Approved By and On filled, Finance fields empty, one Return and one Delivery. Chatter shows decision Approved, the approver and the date |
| 10 | Validate the Delivery first | Refused: the return comes first |
| 11 | Validate the Return, then the Delivery | Status **Done**, Updated Card Generated = Yes |

## D. Results to check after Done

| Check | Expected |
|---|---|
| Card and unit numbers | Unchanged |
| Serial of the unit | `GW-NEW` |
| Unit End Date | The manual date; Start unchanged |
| Card header dates | Unchanged |
| Warranty Date History | One Replacement row with old and new dates and the manual reason |
| PDF | Updated Copy, `GW-NEW`, unit dates as above |
| Case | Still Eligibility Checked, result still **Out of Warranty** |
| Sales Order | Delivered and invoiced quantities unchanged |
| Inventory | `GW-OLD` in the Old Unit Location, `GW-NEW` at the customer |

## E. Case completion

1. On the case, the **Complete Warranty Case** button now shows, and Request Goodwill Replacement does not.
2. Use it. Expect status **Completed**, result still **Out of Warranty**, and a chatter note.
3. Create a new ticket and case with `GW-NEW` on a Confirmed card and use Check Eligibility. Expect the validity step to pass, using the manual date.

## F. Case stays as checked

Use a new case with a Submitted Goodwill replacement. Repeat after Approve and after Done.

1. Check Eligibility: refused.
2. Reject the case, Convert to Chargeable: refused.
3. Change Serial No. or Warranty Card: refused.

Then reject a Submitted replacement as the Approver, with a reason: status Rejected, no serial change, and Check Eligibility works again on the case. Complete Warranty Case does not show.

## G. Not Eligible and blocked cards

| Card status when checking | Case result | Goodwill Submit |
|---|---|---|
| Expired | Not Eligible | Allowed; after Done with a future date the card is Confirmed again, with a past date it stays Expired |
| Suspended | Not Eligible | **Refused**: stays blocked |
| Cancelled | Not Eligible | **Refused**: stays blocked |

Also try excluded items: a request with only excluded items gives Not Eligible on a Confirmed card, and Goodwill is allowed.

## H. Refusals

1. **Eligible case:** on a Request Replacement form, choose Type Goodwill and Submit: refused.
2. **Kit:** Out of Warranty case on an Indoor or Outdoor serial, Goodwill: refused, it must hold one product with one serial.
3. **Empty approver list:** remove the Approver from Replacement GM Approvers and Submit: refused. Restore the list.
4. **Other type:** a Full Product request with Reason Goodwill: refused.
5. **Usage-based warranty:** refused, it can only use Continue Original Warranty.
6. **Case without Case Type:** refused, it could not be completed.

## I. Regression

1. **Full Product:** still refused while Full Product: Finance Approval is empty; GM and Finance approval as before; Continue Original as the default date.
2. **Indoor / Outdoor:** Manager / GM only, as before.
3. **Vendor and Component:** still refused at Submit, "not available yet".
4. **Correct Warranty Dates** on a card with a Done Goodwill replacement: the unit keeps its replacement dates.
