# Part 7 Stage 3 Phase 3: manual testing guide (Vendor / Manufacturer Replacement)

Run on a test database, only after `warranty_management_repair` has been upgraded there with your approval. Version 18.0.1.4.5.

Vendor Replacement is a Full Product replacement of one serialized product on an Eligible, Approved case. It needs Manager / GM approval and no Finance approval. A Vendor Claim is optional.

## A. Setup

1. **Users:** a **Coordinator** with Helpdesk and Inventory rights, an **Approver** in Replacement GM Approvers, and a **Claim Approver** in Vendor Claim Approvers. Settings > Warranty: Vendor Claims Enabled.
2. **Product:** serial tracked, warranty applicable, **with a Cost above 0**, Vendor Claimable, and a Warranty Claim Partner. Set the cost before the replacement delivery. With no cost, the replacement still completes, but its claim is refused.
3. **Stock:** a sold serial (`VN-OLD`) on a Confirmed card and a spare serial (`VN-NEW`) in WH/Stock.
4. **Case:** create a ticket and case for `VN-OLD`, Check Eligibility (Eligible), Approve Case.

## B. Replacement without a claim

| # | Step | Expected |
|---|---|---|
| 1 | Coordinator: Request Replacement, Type **Vendor Replacement**, New Serial `VN-NEW`, a Reason, a Date Policy, Save, Submit | Status **Submitted**, no transfers, serial still `VN-OLD` |
| 2 | Coordinator on the form | No Approve button |
| 3 | A Finance approver who is not a GM approver | No Approve or Reject button |
| 4 | Approver: Approve | Status **Approved**, GM Approved By and On filled, Finance empty, one Return and one Delivery. Chatter shows decision Approved, approver and date |
| 5 | Validate the Delivery first | Refused: the return comes first |
| 6 | Validate the Return | Serial still `VN-OLD` |
| 7 | Validate the Delivery | Status **Done**, serial `VN-NEW`, Updated Card Generated = Yes, Replacement Cost filled |

Check afterwards: card and unit numbers unchanged; Warranty Date History has one Replacement row; the PDF shows Updated Copy and `VN-NEW`; the Sales Order is unchanged; `VN-OLD` is in the Old Unit Location.

Complete the case through its usual job or repair path: **no claim is required**.

## C. Optional Vendor Claim

Use a second replacement, or the one above before the case is completed.

| # | Step | Expected |
|---|---|---|
| 1 | On the Done replacement, **Create Vendor Claim** | A Draft claim: partner proposed, the replacement on the line, serial `VN-OLD`, amount = Replacement Cost |
| 2 | Create Vendor Claim again | Refused: already on a claim |
| 3 | Replacement form | A Vendor Claims button opens the claim |
| 4 | Enter an amount above the cost | Refused |
| 5 | Submit for Approval, then Claim Approver: Approve | Same claim steps as a Material Request claim |
| 6 | Mark Sent, record the vendor response, Create Draft Credit Note | The credit note stays **Draft**; nothing is posted automatically |
| 7 | Replacement and case | Replacement stays Done. The case shows the claim; Net Warranty Material Cost does not change |

### Claim from the New button (version 18.0.1.4.9)

Warranty > Vendor Claims > **New**: select the Warranty Case, add a line with the Replacement or the Material Line, and save. The same rules apply as above. A user with read access only sees no New button.

## D. Refusals

1. **Kit:** Vendor Replacement on an Indoor or Outdoor serial: refused, it must hold one product with one serial.
2. **Out of Warranty or Not Eligible case:** refused, the case must be Eligible.
3. **Reason Goodwill:** refused.
4. **Claim before Done, or on a Full Product type:** refused.
5. **Product not Vendor Claimable, Vendor Claims disabled, or no partner to propose:** the claim is refused, and the replacement stays Done.

## E. Regression

1. **Material Request claim:** create one from a case with a consumed part: same as before.
2. **Full Product, Indoor / Outdoor, Goodwill:** one quick flow each, same as before.
3. **Component:** still refused at Submit, "not available yet".
