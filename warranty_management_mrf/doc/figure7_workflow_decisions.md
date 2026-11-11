# SRS Figure 7: workflow decisions (non-accounting)

Modules: `warranty_management_mrf` 18.0.1.10.0, `warranty_management_repair` 18.0.1.7.2, `warranty_management_accounting` 18.0.1.6.5.
SRS sections: 2.10, 9.8, 10.7, 16.1, 17, and the Figure 7 diagram (page 31).
Decisions D1 to D5 and D9 were approved by the user on 2026-11-07. The accounting decisions (D6 to D8) are still open; see `warranty_management_accounting/doc/figure7_accounting_design.md`.

Built and tested on the isolated database `wt_p7_s2` only. UAT and production are unchanged.

## D1. Approval required?

| Situation | Result |
| --- | --- |
| No rule matches | **No Approval Required**. The request is approved at submission. The approval history line reads "No Approval Required: no material approval rule matches." |
| Every matching rule is No Approval Required | Approved at submission. The history line names the rules |
| At least one matching rule requires approval | The levels of all matching rules are combined (strictest). It can't be bypassed |
| Goodwill lines | Finance and GM are always required (SRS 16.1). Without Finance or GM approvers, Submit is refused with a configuration error, also when no rule matches |
| Automatic approval vs a person | The Approval Status field is **Approved - No Approval Required** (no approving person, no To-Do) or **Approved** (Approved By set) |
| Rule order | The result never depends on order: Sequence only sorts the list. Rules of the request's company and its parent companies apply |
| Boundaries | Minimum is inclusive, maximum is exclusive, and 0 means no maximum |
| Changes | Lines are locked after submission. Withdraw or Reset to New, change, then Submit starts a new round. Earlier rounds stay in the history |

**Approval levels.** The three checkboxes (Manager, Finance, GM) allow every combination. Manager always approves first; Finance and GM follow in any order. Each level needs a different person. The requester, creator and submitter never approve.

Changed code:
- `_warranty_route_analysis`: no matching rule is no longer an error.
- `_warranty_submit`: records the reason for an automatic approval.
- `_compute_approval_status`: adds the value `not_required`.
- Check Approval Route preview: shows the no-rule case.

## D3. Amount Basis (rule field)

| Value | Amount compared with Minimum and Maximum |
| --- | --- |
| All Lines (default) | Routing amount of every line. This is the earlier behaviour, so existing rules are unchanged |
| Covered Lines Only | Routing amount of the Covered lines, including goodwill lines |

Each line counts at the higher of its estimated cost and its product cost.

Method: `warranty.mrf.approval.rule._basis_amount`.

## D2. Not Covered: customer quotation

**When Create Parts Quotation is available** (changed 2026-11-07, see D2a):
- Every required approval level is completed: the request is **Approved**, or **Approved - No Approval Required** at submission. Pending lines block Submit, so a Pending line never reaches a customer charge.
- Its lines are unchanged since submission.
- It has at least one Not Covered line that is not quoted yet (To Quote).

### D2a. Change request 2026-11-07: quotation after full approval

Found in manual UAT of MRF/000013. **Approved business rule:** the quotation waits for all required approval levels.

**Previous rule (diagram branch order):** the quotation was available right after submission, while Manager / Finance / GM approval was still pending. It waited only for a rule that explicitly approves Not Covered materials, or for the Requisition workflow.

**Difference from the SRS Figure 7 diagram:** the diagram branches to "Not Covered → customer quotation" before the approval decision. The approved rule moves that branch after "Approval required? → Approved" (or "No → approved automatically"). Covered lines are unaffected.

- Hidden: `can_create_parts_quotation` uses `_warranty_quotation_error`.
- Server: `action_create_parts_quotation` and the creation of any quotation line linked to a request line (`sale.order.line.create`, sudo included) refuse it with "waiting for approval" or "need a submitted request".
- Unchanged: release of existing orders (`_warranty_chargeable_request_error`), release triggers (confirmation / payment / exception), mixed lines, quantity locking, Release Blocked, cancellation of unconfirmed quotations on reject / withdraw, duplicate prevention.
- Historical quotations created before the change, while the request was waiting, are not changed. They keep their release and cancellation behaviour (tests 08, 09).
- Tests: `test_mrf_figure7` 06, 13, 14 (08 and 09 now cover historical early quotations).

**Release:** a Not Covered line is released only by the customer trigger: quotation confirmation, payment, or an approved release exception. It is delivered only by the quotation's own delivery. A guard refuses any transfer move or purchase line of the request that points to a Not Covered line.

**Covered lines** are released by their own approval. They are no longer held back by Not Covered lines that are still to be quoted.

**Rejected, withdrawn or cancelled requests:**
- Draft or sent quotations are cancelled and logged.
- A confirmed order is never cancelled automatically. Its lines show **Release Blocked (Request Not Valid)** and its delivery is refused until the request is submitted again.
- Request lines on a confirmed order keep their product, quantity, unit and coverage, and can't be deleted.
- The request can't be cancelled while it has a confirmed order.

**Duplicates:** one active quotation line per request line (existing constraint). Quotation lines stay locked.

Where:
- `material_purchase_requisition_sale.py`: `_warranty_quotation_error`, `_warranty_chargeable_request_error`, `_warranty_cancel_open_parts_quotations`, `_warranty_check_not_sold`, `_warranty_check_open_customer_orders`.
- `stock_purchase_guard.py`: `_check_requisition_lines`.
- `material_purchase_requisition_fulfilment.py`: `_warranty_fulfil_lines` (Not Covered lines excluded).

**Known limit:** usage of a part delivered early can be recorded only once the request is approved. Until then the request shows "waiting for approval".

## D4. Stock available? and the Awaiting Stock loop

| Item | Behaviour |
| --- | --- |
| Request Stock Status | **Ready to Issue**, **Partially Available**, **Awaiting Stock** or **Issued**. It covers the approved lines the request issues itself (Covered). Search filter: Awaiting Stock |
| Line Awaiting Stock reason | "Purchase P0xxxx open", "Shortage: Recheck Stock / Issue Remaining creates the purchase order", or "No stock and no vendor: waiting for stock" |
| Create Picking and PO, or Recheck Stock / Issue Remaining | Free stock is issued by one internal transfer. A shortage with a vendor gets an RFQ. A shortage without a vendor is no longer a blocking error: the other lines are processed and the line stays Awaiting Stock |
| Lines without a vendor | A chatter note on the request, case and job. One To-Do for the Requisition Responsible (existing vendor field), else the requester, while none is open. A warning notification. Nothing is created in Inventory or Purchase |
| Recheck | The same button on the same request. Quantities already in open transfers and RFQs are deducted, so no duplicate transfer, RFQ or To-Do. Approvals and payment release stay valid while the lines are unchanged |
| Job | Material Status "Shortage" is now labelled **Awaiting Stock**. The **Put Job on Awaiting Parts** button on the request opens the existing hold wizard; only In Progress jobs, Helpdesk and Field Service users. Resume Job stays on the job. Nothing is put on hold automatically, and no new case status |
| Partial availability | Free quantity is issued, the rest waits (existing F-1). Serial and lot checks and the over-issue block are unchanged |

## D5. Labour, subcontract and other cost

- The request's material approval stays material-only.
- Labour, travel, subcontract and other costs are cost lines and timesheets of the case and job, with their own approval (Part 8.1).
- The total expected cost is checked by the existing **Expected Cost Approval Gate** (company setting, off by default). When on and above its threshold, while a cost line or request of the case is unapproved, it blocks:
  - job confirmation;
  - the next visit;
  - Create Picking and PO / Recheck Stock.
- New **Case Cost Breakdown** tab on the request (read-only, cost groups only) showing estimated, approved, actual and variance:
  - this request's warranty-borne materials;
  - then the case's parts (all requests), labour, travel, subcontract, other and replacement, and the total.
  - Each source is counted once.
  - The gate message is shown when it blocks.

## D9. Repair Order: Material Request

- New **Create Material Request** button on a warranty Repair Order (Helpdesk and Requisition users). It is shown while the order is not done or cancelled and the machine has not been returned.
- It opens the existing request form, linked to that Repair Order, also when the case has several open Repair Orders.
- The service job is linked only when the case has exactly one job that accepts requests.
- Customer, product and serial follow the case.
- A request created from the case is still linked automatically only when the case has exactly one open Repair Order.
- A cancelled Repair Order takes no request.
- The Repair Order is shown on the request form.

## Regression notes

- Existing tests updated for the approved behaviour changes:
  - no rule now approves automatically (approval test 03);
  - automatic approval status (01);
  - Not Covered guard on moves and RFQ lines (13);
  - no stock and no vendor is now Awaiting Stock (fulfilment 03);
  - covered lines are no longer held back (fulfilment 08, quotation 02).
- No change to:
  - inspection quotations, repair quotations or backup charges: parts quotations are identified by `warranty_mrf_id`;
  - case states;
  - the Part 8 closure checks;
  - Figure 6 flows.
