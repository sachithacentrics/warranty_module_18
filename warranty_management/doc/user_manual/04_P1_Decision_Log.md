# P1 – Inspection and Chargeable Route: Decision Log

Package P1 = G-08 (customer declines the inspection quotation), G-30 (customer without a warranty card), G-09 (inspection fee on an eligible case). Status of every entry: **functional design decision by the user; pending formal BA sign-off where marked; not implemented.**

Package order agreed by the user on 11 Nov 2026: P1 → P2 → P3 sequential; P4 and P5 designed independently. This is planning approval only, not implementation approval.

## BD-14 – Inspection decline and eligible-case fee

### Q1 – How the case ends when the customer declines the inspection quotation

**Decision (11 Nov 2026):** Option B – the case is **Closed** with the outcome **"Inspection Declined"**.

| # | Requirement |
|---|---|
| R1 | When the customer **explicitly** declines the inspection quotation, the Warranty Case can be closed with the outcome "Inspection Declined" |
| R2 | "Rejected" stays reserved for company-side warranty claim rejections |
| R3 | The decline reason, responsible user and date / time are recorded in the chatter and in Warranty History |
| R4 | The draft / sent inspection quotation is cancelled with the standard Sales cancellation |
| R5 | The decline flow is refused when the inspection quotation is already confirmed or invoiced; such cases need a separate approved process |
| R6 | Reserved, unconsumed free services are released; historical records are preserved |
| R7 | Closing without a Case Type or a completed Service Job is allowed **only** for the "Inspection Declined" outcome |
| R8 | All existing validation rules for other outcomes stay unchanged |
| R9 | The linked Helpdesk ticket is **not** closed automatically (ticket closure is decided in P3) |
| R10 | No invoice, refund, credit note or inventory transaction is generated |

Clarifications:
- An explicit customer refusal and no customer response are different situations. Cases are **never** closed automatically because the customer has not responded.
- Any quotation expiry, reminder or non-response closure policy needs a separate business decision. It is logged as an open item: **BD-39 – non-response / quotation expiry policy (BA)**.
- Formal BA sign-off is pending.

### Q2 – Decline reason: free text or fixed list

**Decision (11 Nov 2026):** Option B – a fixed decline-reason list plus an additional note.

| # | Requirement |
|---|---|
| R11 | Recording "Inspection Declined" requires choosing a reason from a fixed list |
| R12 | The note is optional for standard reasons and **mandatory for "Other"** |
| R13 | The reason values must be reviewed and confirmed by the BA before implementation. The examples (Price not accepted, Customer will repair elsewhere, Problem no longer exists, Customer will replace the unit, Other) are **not approved** |
| R14 | The reason, note, responsible user and date / time are recorded in the case chatter and in Warranty History |
| R15 | The case stays Closed with outcome "Inspection Declined" (Q1) |
| R16 | No configuration model or menu for decline reasons |
| R17 | The three existing customer-declined workflows (excluded items, repair after inspection, Material Request parts) keep their free-text reasons; they are out of scope |
| R18 | "Customer did not respond" is **not** a decline reason (stays under BD-39) |
| R19 | No new dashboard KPI or unnecessary UI element |
| R20 | All existing access permissions and validation rules are preserved |

Open item: **BD-40 – final decline reason values (BA).** The decision itself is also subject to BA sign-off.

### Q3 – Who may record the decline

**Decision (11 Nov 2026):** Option A – Helpdesk User.

| # | Requirement |
|---|---|
| R21 | Authorised Helpdesk Users may record the decline without Warranty Manager / Approver approval |
| R22 | The user must have access to the case under the existing access rights and company / record rules |
| R23 | "Customer Declined Inspection" is shown only when the case is in the applicable inspection-quotation workflow and all conditions are met |
| R24 | Permissions and workflow conditions are validated on the **server**, not only by button visibility |
| R25 | Only that case's Draft / Sent inspection quotation is cancelled, through the existing controlled Sales cancellation (the same pattern as Customer Declined Repair) |
| R26 | No additional Sales rights for Helpdesk Users |
| R27 | Blocked when the inspection quotation is confirmed or invoiced, or when an active Service Job or another conflicting downstream transaction exists |
| R28 | Reason required (Q2); note required for "Other" |
| R29 | User, timestamp, reason and note go to the chatter and Warranty History |
| R30 | The case is Closed with outcome "Inspection Declined" (Q1) |
| R31 | Unused reserved free services are released; history and consumed services are preserved |
| R32 | The Helpdesk ticket is not closed automatically (P3) |
| R33 | No new security group, approval stage or unnecessary UI element |
| R34 | Company-side Reject Case approval rules are unchanged |

Pending formal BA sign-off.

### Q4 – Eligible (Fig 4) case: does the decline end the claim?

**Decision (11 Nov 2026, revised):** **Option B – continue the warranty service with a controlled inspection waiver.** Option A was only a recommendation and was never decided; it is replaced and is **not** a final decision.

| # | Requirement |
|---|---|
| R35 | On an Approved, Eligible case with inspection required, an authorised user may request an **inspection waiver** when the customer declines the inspection quotation |
| R36 | The waiver is reviewed and approved by an authorised Warranty Approver, using the existing approval controls wherever possible |
| R37 | The waiver applies to that case only; the team's inspection setting and the warranty policy are unchanged |
| R38 | The customer response, waiver reason, requester, approver, approval date / time and decision are recorded in the chatter and Warranty History |
| R39 | Only after approval is the Draft / Sent inspection quotation cancelled (controlled standard Sales cancellation) |
| R40 | After approval, Prepare Service Job is enabled and the existing warranty workflow continues |
| R41 | Eligibility, coverage, serial validation, security rules and all other validations are preserved |
| R42 | No automatic invoice, refund, credit note or inventory transaction |
| R43 | A rejected waiver does **not** close the case automatically; the rejection handling is proposed for BA approval (Q4a) |
| R44 | The Helpdesk ticket is not closed automatically (P3) |
| R45 | Cases actually closed with outcome "Inspection Declined" are excluded from repeated-failure counts; cases continuing through an approved waiver are counted normally |
| R46 | The inspection fee treatment on the waiver route is confirmed under Q6 (Finance where required) |
| R47 | Q1–Q3 stay as recorded, except for the explicit adjustments in Q4-ADJ below |

### Q4-ADJ – Proposed adjustments to Q1–Q3 for consistency (pending the user's confirmation)

| ID | Earlier decision | Conflict with Q4-B | Proposed consistent rule |
|---|---|---|---|
| ADJ-1 | Q1 R1: an explicit decline closes the case | On an eligible case the customer may refuse the inspection but still want the warranty service | Two customer answers, one wizard. **Chargeable route** (9.7): only "Close – Inspection Declined". **Eligible route** (Fig 4): the user chooses "Customer withdraws the request" → Close – Inspection Declined (Q1 unchanged), or "Customer wants the warranty service without inspection" → Request Inspection Waiver |
| ADJ-2 | Q1 R4 / Q3 R25: the quotation is cancelled when the decline is recorded | Q4 R39: cancel only after waiver approval | Close route: cancel at once (unchanged). Waiver route: the quotation stays Draft / Sent until the decision. Approval is refused if the quotation was confirmed or invoiced in the meantime |
| ADJ-3 | Q3 R21 / R33: no approval, no new approval stage | Q4 R36 requires approval for the waiver | The decline itself still needs no approval. The **waiver** is the only approval step, using the existing Warranty Case Approval Users and the existing segregation rule (requester cannot approve); no new group |
| ADJ-4 | Q2 R11: reason list for the decline | Q4 R38 needs the customer response **and** a waiver reason | The customer's reason uses the same Q2 list (BD-40 values); the waiver justification is a required text |
| ADJ-5 | Q1 R6 / Q3 R31: free services released | Under the waiver the case continues | Free services stay reserved on the waiver route; released only on the close route |
| ADJ-6 | Q3 R23: button visibility | A pending waiver must stop parallel actions | While a waiver is pending: Create Inspection Quotation / Prepare Service Job hidden and refused on the server; one pending waiver per case |

**ADJ-1 … ADJ-6 confirmed by the user (11 Nov 2026).**

| ID | Earlier decision | Conflict | Confirmed rule |
|---|---|---|---|
| ADJ-7 | Existing approval rule: with "Warranty Case Approval Required" off, any Helpdesk user (including the requester) may approve | Q4 R36 requires an authorised approver | **Confirmed:** the inspection waiver always requires a Warranty Case Approval User who is not the requester, whatever the setting. This applies **only to the waiver approval**; the general Warranty Case approval rules are unchanged |

### Q4a – Handling of a rejected waiver

**Decision (11 Nov 2026):** Option R-A – back to "inspection quotation pending".

| # | Requirement |
|---|---|
| R48 | A rejected waiver leaves the case **Approved**, with the inspection quotation open; the rejection reason, approver and date / time are recorded in the chatter and Warranty History |
| R49 | The customer can then accept the quotation (normal path) or withdraw (Close – Inspection Declined, Q1–Q3); the Helpdesk user may file a new waiver request with a new justification. Every request and decision stays in history |
| R50 | No automatic closure; non-response follows BD-39 |
| R51 | Keep the flow simple and follow the SRS. No approval levels, statuses, buttons or functions beyond what the agreed flow needs |

### Q5 – Helpdesk ticket handling

**Decision (11 Nov 2026):** Option A – no Helpdesk ticket change in P1.

| # | Requirement |
|---|---|
| R52 | Inspection Decline and Waiver actions are allowed whatever the linked ticket's stage, subject to the existing case permissions and validations |
| R53 | The ticket is never opened, closed or changed automatically |
| R54 | The existing rule stays: the ticket must be open before Prepare Service Job |
| R55 | No duplicate chatter messages on the ticket; no extra functionality |
| R56 | Ticket closure is handled in P3 |

### Q6 – Customer notification
Pending.

## BD-15 – Cardless chargeable cases
Q1–Q5 pending.
