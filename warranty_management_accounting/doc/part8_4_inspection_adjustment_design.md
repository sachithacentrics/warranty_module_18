# Part 8.4 Inspection Fee Adjustment: decision record

Module `warranty_management_accounting` 18.0.1.3.1. SRS 2.11, 9.7 steps 7-8, 13, 17, 19; mapping rows 26-28 and D10. Nothing is posted, paid, reconciled or refunded by this feature, and no posted document is changed.

## Reused

| Existing | Use |
| --- | --- |
| Inspection order, `warranty_chargeable_purpose` | Finding the inspection and repair quotations |
| `warranty.service.job` completed inspection | Proof the inspection was done, for the quotation route |
| Team Inspection Product and Amount, Part 8.3 Deduction Product | Fee line; deduction line |
| `account.move._reverse_moves` | The credit note, with `reversed_entry_id` to the invoice |
| `sale.order`, `sale.order.line` | The deduction, invoiced by the standard flow |
| `_warranty_check_decline_repair` | Extended with one check |
| `account.move._warranty_reversed_ratio` (Part 8.2) | A fully reversed note is no longer effective |

**New, no new model, menu or wizard:** `warranty_inspection_case_id` and `warranty_inspection_credit_limit` on `account.move`, `warranty_inspection_deduction_case_id` on `sale.order.line`, computed status fields and one action on the case.

## Routes

| Inspection invoice | Repair quotation | Result |
| --- | --- | --- |
| Posted: unpaid, part-paid or paid | Confirmed | **One draft credit note** for the fee line, with its tax, from the standard reversal |
| Posted | Not confirmed | Refused: the customer hasn't proceeded |
| None or draft | Draft or Sent | **One deduction line** on the quotation, at the fee's untaxed amount with the fee line's tax |
| None or draft | Confirmed | Refused: post the inspection invoice, so the credit note route applies |
| Any | Customer declined, or no repair needed | Refused: the fee stays charged |

## What is refused, with the reason shown

- **Duplicate:** an effective adjustment already exists. The row is locked during the action, so two users can't both create one.
- **Not charged:** no confirmed inspection order, or no completed inspection job for the quotation route.
- **Already credited:** the invoice has a credit note or reversal that isn't cancelled.
- **Not a clean case, for Accounting to review:** several posted inspection invoices, a down payment on the inspection order, several fee lines, or several active repair quotations.
- **Different company, currency or fiscal position:** the tax of a deduction can't be decided safely across fiscal positions.
- **Fee above the repair total:** see F5 below. An unpriced repair also falls here.
- **Deduction product missing or not invoiced on ordered quantities:** it wouldn't reach the invoice.

## Duplicate benefit

- A credit note that is cancelled, or a deduction line removed or on a cancelled quotation, is no longer effective, so the action can run again.
- An inspection invoice posted **after** a deduction stays valid. The fee is billed and deducted once, and a credit note is refused.
- A deduction line can't be edited, only deleted and applied again.
- A credit note can't post above its stored fee. Accounting may lower it.
- A declined repair is refused while a draft or posted credit note is effective. A deduction goes with its cancelled quotation.

## Authorization

Billing users (`account.group_account_invoice`) or the company's named Cost and Finance Approvers from Part 8.1. Technicians can't read the status. Case access rules apply first, so another company's case is refused. An approver with no Sales or Accounting rights gets the adjustment and sees the status on the case, without opening the document.

## Duplicate billing safeguard

Standard Odoo lowers the invoiced quantity for a credit note, even in draft, so the fee line would show To Invoice again and could be charged a second time.

| Check | Rule |
| --- | --- |
| `qty_to_invoice` of the inspection fee line | 0 while an effective credit note covers its invoice, so the standard invoicing flow skips it. `qty_invoiced` stays standard |
| Posting a customer invoice | Refused if it holds that fee line, unless it is the original invoice or a reversal |
| Other lines of the order | Invoice normally |
| A cancelled note, or a standard reversal of a posted note | Not blocked. Net, the fee is charged once |

## F5: approved decision

| Scenario | Behaviour |
| --- | --- |
| Fee above the repair total | **Refused with a clear message, nothing created.** The case stays pending Finance decision; no refund or excess credit is created |
| Inspection order never invoiced after a deduction | Allowed by the SRS path; the status shows on the case. Part 8.5 Close Case is designed to block it (D10) |

## Server-side rights

Apply and Open both check access to the case first, then the rights, on the server. Link fields on the credit note and the case, and the deduction line's amounts, can't be changed through RPC. Internal `_warranty_*` methods aren't callable through RPC.

## Open SRS gap: customer notification

**Mandatory and not implemented (SRS 2.11, 7, 17, Figure 4; mapping row 18, D15).** Inspection quotations still rely on the staff To-Do and the manual Send button, and UAT has no active mail server. Part 8.4 doesn't close this, so the SRS isn't fully met until it is built.

## Known limits

- **Fully reversed credit note:** it stops being effective and the status returns to No Adjustment, but the documents then need a person's review, so a new note is refused.
- **Duplicating a repair quotation:** the deduction isn't copied. If the case then has two active repair quotations, a new adjustment is refused until one is cancelled.
- **Sent quotations:** a deduction on a Sent quotation changes its total. Send it again to the customer.
- **Accounting period:** the draft uses today's date; standard lock dates apply when Accounting posts.
- **UAT roles:** all five UAT users hold Billing access, including `demo`, `main_tech` and `support_tech`, so all can apply this adjustment. This is a role configuration matter; no groups were changed.
