# Part 9 manual testing guide

**Use only after you approve and carry out the upgrade.**

**Don't use:** WCAS/000042, WCAS/000049, VCL/00006 or its draft credit note, or JOB/000036. Use **new test sales, cards and cases**. Don't post real accounting documents for these tests beyond your normal test records.

## Setup

1. Settings > Warranty > Controlled Warranty Actions: add two test users as **Warranty Exception Approvers**.
2. You need a **requester** who isn't an approver for the first tests, and an approver.
3. Create and confirm two test warranty cards: one with one unit and one with two units.

**Every action:** Warranty Card > **Controlled Action**, choose the action, fill in the form, **Request Approval**. Then, as the approver, open the action and **Approve and Apply**.

## Tests

| # | Test | Expected |
| --- | --- | --- |
| 1 | Warranty Card list, import or API: change a confirmed card's customer | Refused; form field is read-only |
| 2 | Request with no approver configured | Refused with a message |
| 3 | Requester who is also an approver opens their own request | No Approve button |
| 4 | Request a second action while one is waiting | Refused |
| 5 | Reject a request with a reason | Nothing changes; reason in the chatter |
| 6 | **Suspend** the one-unit card, without evidence | Refused |
| 7 | Suspend with reason and evidence, then approve | Card and unit Suspended; dates unchanged |
| 8 | New case on that serial, Check Eligibility | Not Eligible |
| 9 | **Reactivate** and check again | Confirmed; Eligible |
| 10 | Suspend one unit of the two-unit card | Card Confirmed; that unit Not Eligible, the other Eligible |
| 11 | Suspend a card with an open case and job | Both listed; both unchanged |
| 12 | Return a delivered serial, without requesting anything | Card unchanged; note in the chatter and Warranty Date History |
| 13 | **Return / Refund Cancellation** with that return | Unit Cancelled; sale, delivery and invoices unchanged |
| 14 | Cancellation without a return or credit note | Refused |
| 15 | **Correct Serial** with a serial already on another live unit | Refused |
| 16 | Correct Serial with a free serial of the same product | Serial changed; PDF updated; old and new shown |
| 17 | **Correct Customer** while a case is open | Refused |
| 18 | **Relocate Unit** to another address of the customer | Current Site changed; dates unchanged; new case uses the site |
| 19 | **Transfer Ownership** without a document | Refused |
| 20 | Transfer with date and document | New owner Eligible; old owner not; sale and invoices keep the old customer |
| 21 | **Extend Warranty**, free, 3 months | End dates moved; Original End Date shown; PDF updated |
| 22 | Extend as Paid with no quotation or invoice | Refused |
| 23 | On a Completed or Closed case, **Repeat Complaint** | New case form linked to the old case; old case unchanged; no free service used |
| 24 | Second repeat while the first is open | Refused |
| 25 | **History** button on Card, Unit, Sales Order, Ticket, Case and Job | Events listed with entity, user and date; can't be edited |
| 26 | Warranty > Warranty Cards > Warranty History, as a user of the other company | No San Francisco rows |
| 27 | After the tests, compare accounting totals | No new or changed documents from these actions |

## Not available yet

Void, Extended Warranty Product, reopening a closed case, repeat window, single-unit transfer and "free services don't transfer" wait for business decisions. Don't report these as failures.
