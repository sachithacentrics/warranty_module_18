# Part 8.7 Vendor Recovery Accounting: decision record

`warranty_management_mrf` 18.0.1.9.10 and `warranty_management_accounting` 18.0.1.6.1. F6-A (recognise the posted amount) and F6-B (process control) were decided on 2026-11-04.

## SRS mapping

| SRS | Requirement | Status |
| --- | --- | --- |
| 2.10 | Reimbursement tracked through a claim linked to a vendor credit note or receivable entry; recovery visible on the case | Met for credit notes. Claim receivable is an approved deviation (D13) |
| 6 | Recover warranty cost from supplier or manufacturer | Met for Parts and Replacements (D14) |
| 11.1 step 8, 12 #15 | Vendor claim and recovery status | Met |
| 15 | Vendor Claim Recovery Report | Met |
| 17 | Vendor credit note or reimbursement tracked against the claim and case | Met for notes created from the claim. Notes entered directly are handled by the F6-B process rule |

## Accounting events

| Event | Accounting | Recovered | Outstanding |
| --- | --- | --- | --- |
| Claim approved or sent | None | 0 | 0 until answered |
| Vendor accepts | None | 0 | Accepted amount |
| Create Draft Credit Note | Draft Dr Payable, Cr Recovery Account; nothing posted | 0 | Accepted amount |
| Accounting posts it | Standard posting | The allocation, or its share of the note's actual untaxed amount if lower | Falls by it; the rest stays recoverable |
| Reconciled with a bill or refund | Standard, by Accounting | Unchanged; Settled rises | Unchanged |
| Note reset and cancelled | Standard | Back to 0 | Back |
| Note fully reversed | Standard | Back to 0 | Back; a new note is possible |
| Note partly reversed | Standard | In proportion | In proportion |
| Vendor document outside the claim | Standard | Not counted; Finance reviews it (F6-B) | Unchanged |
| Case closed | None | Unchanged | Claim continues |

## F6-A: recognise the posted amount (approved)

**Rule (`warranty.vendor.claim.recovery._warranty_recovery_eligible_amount`, and the same rule in `ALLOCATION_SQL`):**

- **Draft note:** holds its whole allocation, so the amount can't be claimed a second time.
- **Posted note:** the allocation, or its share of the note's actual untaxed amount if that is lower. Allocations on one note share a lowered amount in proportion.
- **A higher note:** stays capped at the allocation, so accepted-amount caps are unchanged.
- **Reversals:** apply to this eligible amount, as before.

| Accepted 100, draft 100, lowered to 60 | Before | After |
| --- | --- | --- |
| Note posted amount | 60 | 60 |
| Recovered | 100 | **60** |
| Outstanding | 0 | **40** |
| Allocated (net) | 100 | **60** |
| Status | Recovered | **Partial** |
| Next credit note | Refused | **Draft of 40** |
| Allocation record amount | 100 | 100 (history unchanged) |

Vendor Claim, Warranty Case, Vendor Recovery and Material reports, and the Warranty Cost Report all read this rule. No posted document or allocation record is changed.

**Multi-line claims:** a note's lines aren't matched to claim lines one by one. If a note covering several claim lines is lowered, every line shares the reduction in proportion, even if Accounting lowered only one line.

## F6-B: process control (approved)

**Vendor recovery credit notes must start from the Vendor Claim, with Create Draft Credit Note.**

- There is no Allocate Credit Note button, and no automatic linking of notes created in Accounting.
- A vendor credit note entered directly in Accounting doesn't count as recovery.
- If one was entered for a claim, Finance reviews it. Finance decides whether to reverse it in Accounting and create the recovery from the claim.
- Nothing reverses or relinks a note automatically.

**For Finance review on UAT:** `RBILL/2026/10/0001` (30.00) and `RBILL/2025/07/0001` (622.27) are posted vendor credit notes with no claim allocation. They haven't been changed.

**Not confirmed:** `RBILL/2026/11/0001` doesn't exist on UAT, and nothing was created to match it.

## Known gaps

- A claim closed before its note is reversed stays closed with outstanding 0. Recovered falls, and Accounting follows up.
- Claim receivable (example G) stays not built (D13). Labour, travel and subcontract recovery stays not built (D14).
- Customer notification (row 18, D15) stays open and is unrelated to this stage.
