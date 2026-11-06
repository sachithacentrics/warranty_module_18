# Part 7 Stage 1: manual testing guide (Full Product Replacement)

Run on a test database, only after the module has been upgraded there with your approval.

## A. Configuration

1. Inventory > Configuration > Locations: create **Warranty Return** (Internal, parent Physical Locations, so outside every warehouse).
2. Inventory > Configuration > Operations Types: create **Replacement Return**: Type Receipt, default destination Warranty Return.
3. Create **Replacement Delivery**: Type Delivery, default source WH/Stock, default destination Partners/Customers.
4. Prepare 4 users: Coordinator (Helpdesk user, Inventory user), GM, Finance, Warehouse (Inventory user).
5. Settings > Warranty: set Replacement Return Operation Type, Replacement Delivery Operation Type, Replacement GM Approvers = GM, Replacement Finance Approvers = Finance.
6. Leave **Full Product: Finance Approval** and **Fixed Extension Added To** empty for now.
7. Warranty Policy of the test card: Replacement Date Policy empty, Replacement Return empty.
8. Create a serial product with serials NEW-001 and NEW-002 in WH/Stock.

## B. Starting data

1. Sell, deliver (serial OLD-001), and confirm the warranty card. Note the card number, unit number and dates.
2. Create a Helpdesk ticket and warranty case with serial OLD-001. Check Eligibility, then Approve Case.

## C. Pending decision blocks

1. Case > **Request Replacement**: type Full Product, New Serial NEW-001, Reason Compressor Failure. Save.
2. Submit. Expect a refusal naming the pending decision BA B1.
3. Change Type to Goodwill and Submit: refused, not available yet. Repeat for Component and Vendor. Indoor Unit and Outdoor Unit are refused here because this product is not a kit (Stage 2 guide).
4. Type Full Product, Reason Goodwill, Submit: refused.
5. As the test choice for B1, set **Full Product: Finance Approval = Required**. Set Reason back to Compressor Failure.

## D. Approval and separation of duties

1. Submit as Coordinator. Expect Submitted, and To-Dos for GM and Finance.
2. As Coordinator: Approve is not shown.
3. As GM: Approve. Status stays Submitted; GM name and date recorded; the To-Do now names Finance.
4. As Finance: Approve. Status Approved; one Return Picking and one Replacement Delivery exist.
5. Chatter of the replacement, case and card shows each step.

## E. Stock order (Figure 3)

1. As Warehouse, open the Replacement Delivery and Validate: **refused**, the return comes first.
2. Check the card: the unit still shows OLD-001.
3. Open the Return Picking: serial OLD-001 from customer to Warranty Return. Change the serial to another one and Validate: refused. Restore OLD-001 and Validate.
4. Validate the Replacement Delivery with serial NEW-001.
5. Expect: status Done, Replacement Date set, Updated Card Generated = Yes.

## F. After the swap

1. Same card number and unit number. The unit shows NEW-001.
2. Warranty Date History has a **Replacement** row with old and new dates.
3. Replacements tab of the card shows OLD-001 to NEW-001. Replacement Count = 1.
4. Download PDF: shows **Updated Copy after replacement** and NEW-001; the existing download rule applies.
5. Sales Order: delivered and invoiced quantities and the original delivery are unchanged.
6. Free services of the card are unchanged.
7. A new warranty case with OLD-001 no longer finds the card. One with NEW-001 finds it.

## G. Date policies (repeat B to E with a new serial each time)

Use a warranty of 10 Aug 2026 to 9 Aug 2027 as the reading aid; compare with your own dates.

| Policy | Expected unit end | Expected unit start |
|---|---|---|
| Continue Original Warranty | Unchanged | Unchanged |
| Restart from Replacement Date | Replacement date + duration - 1 day | Replacement date |
| Remaining Period Only | Unchanged; Remaining Days filled | Unchanged |
| Add Fixed Extension | First refused while Fixed Extension Added To is empty; then base + extension | Unchanged |
| Manual Approval-Based Date | The date entered by the first approver; refused without date and reason | Unchanged |

The card header dates stay unchanged and are labelled Original on the PDF when the unit dates changed.

## H. Existing validated return

1. New card and case. Ticket > Return: receive the machine into Warranty Repair Intake and validate.
2. Create a Repair Order, start it, end it as Not Repairable.
3. Request Replacement, Submit, approve at both levels.
4. Expect: no new return; Return Picking is the validated intake; Existing Return Reused = Yes.
5. Standard Return of that intake: refused.
6. Validate the delivery: status Done, and the "return the machine" To-Do of the Repair Order closes.

## I. Completion

1. On H: Repair Order shows Complete Warranty Case. Use it; the case becomes **Completed**, never Closed.
2. Repeat H with an open Material Request not reconciled: Complete is refused for that reason.
3. While a replacement is Draft, Submitted or Approved: job completion and Repair completion are refused, naming it.
4. Case with a service job: after Done, complete the job as usual.
5. Check that a Repair Order with Not Repairable and **no** Done replacement is still blocked.

## J. Other refusals

1. A serial already on another warranty card is not offered in New Serial.
2. A serial not in WH/Stock is not offered in New Serial. Select a valid serial, move it out of WH/Stock before Submit: Submit refused.
3. Same New Serial on a second open request: the first is Submitted, then Submit of the second is refused.
4. Second open request on the same unit: Submit refused.
5. Kit product, or a unit with no serial: Submit refused.
6. Reject without a reason: refused. With a reason: Rejected, transfers cancelled, serial unchanged.
7. Approved with no transfer validated: Reject works and cancels the transfers.
8. Policy Replacement Return = Not Required, machine at the customer: no return is created; delivery validates; the note says not returned.
9. Backup unit with the customer on this case: after Done, a To-Do asks to receive it.

## K. Recovery after the return is validated

Start each with a new request, approved, return validated, delivery not validated.

1. **Change New Serial:** as an approver, select another serial and validate without a reason: refused. Add the reason: the old delivery is Cancelled, one new delivery exists, the approvals remain, and the chatter shows both serials. The return is not touched.
2. Try to validate the cancelled delivery: not possible. Validate the new one: status Done.
3. **Reject:** as an approver, reject with a reason. The delivery is Cancelled, the validated return stays Done, the unit keeps the old serial and dates, and a To-Do asks to resolve the old unit.
4. Complete the case now: refused, naming the old serial's location.
5. Use the standard Return of the validated return and validate it: the old serial is at the customer, the To-Do closes, and completion is no longer refused for this reason.
6. Repeat 3, then instead create a new request on the same unit: after approval it reuses the same return, with no second return.
7. As the submitter or a user outside the approver lists: Reject and Change New Serial are not shown.

## L. Recovery buttons

1. Create Missing Transfers shows only when a transfer is missing. Cancel the delivery: the button shows; click it: one new delivery; the button disappears. Check Inventory for duplicates.
2. Same with the return cancelled before validation: one new return; the open delivery is kept.
3. Generate Updated Card shows only when Updated Card Generated is No. To test it, stop PDF generation on the test server only, if you can do so safely; otherwise this is checked by reading the code.

## M. Replacement cost

1. After Done: Replacement Cost equals the valuation of the delivered serial (Inventory > Reporting > Valuation), and Cost From Stock Valuation is ticked.
2. No journal entry is created by the replacement, other than what your stock valuation setting posts for any transfer.
3. Case and card cost totals did not change.

## N. Regression checks

Backup issue and return (Part 6.2), repair without replacement (Part 6.1), Material Request claims (Part 5.8), and Correct Warranty Dates on a card without a replacement all behave as before.
