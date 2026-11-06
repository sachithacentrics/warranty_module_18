# Part 7 Replacement + Serial Swap: decisions (Stages 1 and 2)

Status (2026-11-03):

- Stage 1: main Full Product workflow passed manual UAT (WR/000001). Recovery scenarios, the other date
  policies and full regression are still unverified.
- Stage 2 (18.0.1.4.2): Manager / GM approval is mandatory on Indoor and Outdoor, see "Approval on Indoor /
  Outdoor" below. **The approval correction and its updated tests have not been run (not authorized yet).
  Manual UAT, a browser run and a real PDF file are not done.** Stage 3 waits for the user's review of the
  Stage 2 manual test.
- Bug found by those tests and fixed, also in Stage 1: Submit, and a change of type in Draft, reset the
  date policy chosen on the draft to the Warranty Policy value.
- Kit serial linkage fix (`warranty_management_helpdesk` 18.0.1.1.6), found in manual UAT: see "Kit serials on
  the ticket" below. Automated tests pass on `wt_p7_s2`; **manual UAT is not done**.

## Stage 1 scope

Full Product replacement of one serialized product, following SRS 10.6, 11, 11.1-11.3, 16, 16.1 and
§9.12 Figure 3. Component, Goodwill and Vendor types are listed (SRS 10.6) but refused at Submit.

## Stage 2 scope

Indoor Unit and Outdoor Unit replacement of a kit (SRS 11.1), on the same `warranty.replacement` model,
approvals, transfers, date policy engine, history and PDF. Only one serial and its own dates change.

| Topic | Decision | Reason |
|---|---|---|
| Component product | The BoM line of the role on the kit the unit was delivered with (`_warranty_kit_bom`, `_warranty_role_lines`). `product_id` of the request is that component, and the transfers move it. | Correct product and role, no kit explosion, Sales Order untouched. |
| Serial swap | Written through the existing kit write path (`warranty_kit_allocation`, `_sync_kit_serials`). | `serial_ids` and the serials of a single-unit card stay in sync, as for a delivery. |
| Kit serial rule (K4) | `_warranty_delivered_role_lots` also accepts the serial delivered by a validated replacement of that unit and role. | Otherwise `_check_kit_serials` refuses every replacement serial, now and on later saves. |
| Serial dates | `indoor_/outdoor_start_date` and `_end_date` on the unit, empty until a policy changes the dates. Empty: the unit dates apply. Written only with the replacement marker. | SRS 11.1, 11.3. The unit dates and card header never move, so the other serial is never extended. |
| Eligibility | Hook `_warranty_validity_period` in `warranty_management_helpdesk` (no behaviour change there); the repair module returns the dates of the case serial. | SRS 13. |
| Free services | Unchanged: they keep using the unit and card dates. | SRS 11 step 9. A serial's own dates are not a new service entitlement. |
| Correct Warranty Dates | Writes the unit dates as before. A serial with its own dates keeps them; a serial without follows the correction. The Stage 1 "keep the unit dates" rule applies to Full Product only. | Otherwise one replacement would freeze the other serial. |

### Kit serials on the ticket (fix approved 2026-11-03)

A kit delivery moves the components, so the Indoor / Outdoor serials belong to the component products. The serial lists of the ticket, the Create Warranty Case wizard and the case offered only serials of the selected product, so with the kit as product no real kit serial could be chosen (UAT: ticket #66, WC/00031).

The three lists now also offer the serials on the customer's units of that product in the company (`_warranty_unit_serials`, `warranty_management_helpdesk`). The Product of the ticket and case stays the kit. The lookup, eligibility and replacement code did not change. A product change clears the serial only when it no longer fits the product. The SRS does not define these lists (10, 9.5, 10.6, 11.2 define the unit serials and their checks), so the list rule is a proposal approved by the user. No separate cards for components.

### Approval on Indoor / Outdoor (user decision, replaces the no-approval clarification)

The user first asked for no approval on these two types (18.0.1.4.1). That conflicted with SRS 11 step 2, 11.2, 11.3, 10.6, 13 and Figure 3, so the user withdrew it: **Manager / GM approval is mandatory** (18.0.1.4.2), on the Stage 1 approval engine.

| Topic | Decision | Reason |
|---|---|---|
| Flow | Submit: Submitted, To-Do for the approvers, no transfer. Approve: Approved, return and delivery created. Swap after the delivery is validated. | SRS 11.2, Figure 3. |
| Approvers | The existing `Replacement GM Approvers` list, never the submitter. Reject and Change New Serial: the same list. | SRS 11 step 2 names Manager / GM; no second list or engine. |
| Finance | None on these types, whatever `Full Product: Finance Approval` says. | User decision; no confirmed SRS rule for ordinary requests. High-value (SRS 16.1) stays B1. |
| Manual date | Entered by the approver before approving, as on Full Product. | SRS 11.3. |
| Chatter | The decision, approver and date on the replacement, ticket, case and card. | User requirement. |
| Request approved under 18.0.1.4.1 (UAT WR/000002) | Not changed by code. Status Approved with no GM signature (`approval_missing`): its transfers cannot be validated, and Change New Serial and Create Missing Transfers are refused. A Manager / GM approver can reject it, which cancels its open transfers, and a new request follows the approval. No retrospective approval: nobody reviewed it before its transfers were created. | SRS 13 "Block replacement delivery", without resetting a record. |

Proposals, not SRS text:

| Decision | Reason |
|---|---|
| The case serial must be the active serial of the role, and a role replacement needs a case serial. | The eligibility of the case was checked on that serial's dates. |
| The Indoor and the Outdoor serial of one unit may have open requests at the same time; the same role may not. Each needs its own case. | They are separate machines; both can fail. |
| Same component product only. | Narrowest behaviour, as in Stage 1. |

## Pending BA decisions

These are not business rules. Nothing below is assumed in the code. B2, B4 and B5 are answered for Stage 3 design; the types stay refused until Stage 3 is built.

| # | Decision | How Stage 1 behaves until it is answered |
|---|---|---|
| B1 | What "high-value" means for Finance approval (SRS 16.1 does not define it). | `Full Product: Finance Approval` in Settings is empty: Submit of a Full Product is refused. The tester or the company chooses a value; Required is a temporary UAT configuration, not a rule. Indoor / Outdoor: Manager / GM only; a high-value rule would need this decision. |
| B2 | Approval level of Component and Vendor; an MRF approval must not replace the Figure 3 approval. | Types refused at Submit. |
| B3 | Fixed Extension base. Also: on a second replacement, the first warranty end or the end in force. | `Fixed Extension Added To` in Settings is empty: that policy is refused. The proposal is the end date before this replacement. |
| B4 | Whether a Vendor Claim is mandatory, and its timing. | Vendor type refused. Claim code unchanged. |
| B5 | Goodwill on a not-eligible case, and how that case completes. | Goodwill type refused, and reason Goodwill refused on a Full Product. No eligibility override exists. |

## Implementation decisions (proposals, not SRS text)

| Decision | Reason |
|---|---|
| GM level always needed on Full Product. | SRS 16. |
| One person signs one level; the submitter signs none. | Same rule as the vendor claim (V-8). |
| Empty policy Return setting means Required. | SRS 11 step 3 is policy-based; SRS 11.1 Full Product says "Old product returned". |
| Empty policy date setting means Continue Original. | SRS 7, 11.3. |
| Requester may change the date policy while Draft; frozen at Submit and shown to the approvers. | SRS 11.2 "configurable". |
| Same product only. | Approved narrowest behaviour. |
| Origin: Eligible case that is Approved, Job Created or In Progress. | The states that can complete through the existing paths. |
| A Repair Order of the old serial must be Done as Not Repairable, cancelled, or returned. | A working machine goes back to the customer. |
| Reject stays available until the replacement delivery is validated. A validated return is never reversed; the old unit goes back with the standard Return of that transfer, or a new replacement reuses it. Case completion is blocked while it waits. | Recovery without an extra status (code review, 2026-11-02). |
| Change New Serial, by an approver with a reason, until the delivery is validated. The open delivery is cancelled first. The approvals stay. | A new serial that cannot be delivered must not cancel the replacement. BA may ask for a new approval instead. |
| Replacement Cost is recorded from the valuation of the validated delivery, using `_warranty_move_value` of the Material Request cost, else the product cost marked as an estimate. The old unit's value is not deducted, and the cost is not added to any case total. | SRS 11 step 8, 17, Figure 3. No entries (Part 8), no report (Part 10). |
| Actions take a row lock on the replacement. | A double click or parallel request cannot create a second transfer or signature. |
| Unit dates change; card header and free services never change. | SRS 11 step 9; header changes would recalculate entitlement flags. |
| Correct Warranty Dates keeps the dates of a unit changed by a replacement. | That correction writes every unit. |
| Serial edit guard only on units with a submitted, approved or done replacement. | SRS 19, without changing the kit correction or any other unit. |

## Stage 3: confirmed BA decisions and proposed design (2026-11-03, not approved for development)

B2, B4 and B5 above are answered here, in part. Open points are listed in the last table.

Status:

- Phase 1 (18.0.1.4.3): done, no behaviour change. The Finance and whole-unit checks read two named rules, `FINANCE_TYPES` and `UNIT_SCOPE_TYPES`.
- Phase 2, Goodwill (18.0.1.4.4): built, see "Goodwill as built". The 54 focused tests passed. **The full regression is incomplete:** the first group was stopped by low memory at about 97%, showing only known failures so far; the other two did not run. By the user's decision it is not rerun; the user performs manual UAT.
- Phase 3, Vendor (18.0.1.4.5): built, see "Vendor as built". Targeted tests only, no full regression, by the user's instruction. **Manual UAT and a browser run are not done.**
- Phase 4, Component (18.0.1.4.6): built, see "Component as built". Targeted tests only, no full regression, by the user's instruction. **Manual UAT and a browser run are not done.**

| BA decision | Goodwill | Vendor / Manufacturer | Component |
|---|---|---|---|
| Scope | Full Product only | Full Product only | Parent serial, card and unit never change |
| Approval | Manager / GM on `Replacement GM Approvers`; no Finance | Figure 3 Manager / GM | Figure 3 Manager / GM, then the Material Request rules |
| Cases | Expired and Not Eligible allowed; the result is never changed to Eligible | Not stated | Not stated |
| Other | Manual date (SRS 11.1, 11.3); explicit, auditable exception | Claim optional; existing workflow; no automatic entries | Existing Material Request flow; defective returns through stock; old and new part details |

Complete kit replacement is out of scope. So a kit unit cannot have a Goodwill or Vendor replacement in this scope.

**Differences from the SRS, by BA decision:** SRS 16.1 lists "High-value replacement/goodwill: GM + Finance"; Goodwill has no Finance level. SRS 13 blocks service on an expired, suspended, voided or cancelled warranty; Goodwill is the controlled exception SRS 11.1 describes as "outside normal rules".

### Goodwill as built

| Topic | Decision | Source |
|---|---|---|
| Cases | Eligibility Checked, result Not Eligible or Out of Warranty. Card Confirmed or Expired; Cancelled and Suspended blocked. Eligible cases refused. | BA |
| Scope | One serial, Full Product; a kit is refused. | BA |
| Approval | Manager / GM on the existing list; no Finance. | BA |
| Date and reason | Always Manual, entered by the approver; reason always Goodwill, set at Submit. | SRS 11.1, 11.3 |
| Exception audit | Reason Details is required. Submit logs the case result, its checked reason and the exception reason on the replacement, ticket, case and card. No new stored field. | BA |
| Case while it has a Goodwill replacement | Stays Eligibility Checked. Submitted, Approved or Done: status, result, product, serial, card and unit cannot change, so Check Eligibility, Reject and Convert to Chargeable are refused. A rejected replacement frees the case. | BA, proposal |
| Case completion | `Complete Warranty Case` on the case after the replacement is Done, with the open replacement, service job, repair, free service and Material Request blockers. Result unchanged. | Proposal |
| Stock, swap, history, PDF | The Full Product code path. | Stage 1 |

Limits: a case without Case Type is refused, because the existing rule (approved B6) cannot complete it. A usage-based warranty is refused, because the date policy check allows it Continue Original only. A case refused here is not selectable from the replacement menu; use the button on the case.

### Automatic warranty expiry (approved 2026-11-04, 18.0.1.4.8)

SRS 9.13, 13, 14. The daily job moves ended Active units and Confirmed period-based cards to Expired, and only expires. A kit unit uses each serial's own dates. A multi-unit card expires when every unit except Replaced and Cancelled is Expired. Q14 is unchanged; see `warranty_management_helpdesk/doc/part3_design_decisions.md`.

| Replacement status when the card expires | Behaviour |
|---|---|
| Draft, Submitted (not Goodwill) | Submit and the final approval need a Confirmed card; the approver can reject. |
| Approved | Finishes its stock; Suspended and Cancelled still block it. Remaining Period Only is checked up to the approval, and Remaining Days is never below 0. |
| Goodwill | Accepts an Expired card, keeps the Not Eligible result. |

A date correction, or a Done replacement that changed the dates, returns units with a valid period to Active and the card to Confirmed, with a chatter note. Component and Continue Original do not.

### Vendor as built

| Topic | Decision | Source |
|---|---|---|
| Scope | One serial, Full Product; a kit is refused. | BA |
| Cases | The existing rule: Eligible and Approved, Job Created or In Progress. | SRS is silent on another rule; none added |
| Approval | Manager / GM on the existing list; no Finance. The claim keeps its own approval. | BA, SRS 16.1 |
| Stock, swap, dates, history, PDF | The Full Product code path. | Stage 1 |
| New unit | The existing New Serial stock check. | Stage 1 |
| Claim | Optional `Create Vendor Claim` on a Done replacement: a Draft claim of the existing workflow. Its completion never depends on it. One active claim per replacement; a vendor-rejected or cancelled claim allows a new one. | BA, SRS 12 #15 |
| Claim line | `mrf_line_id` is optional by inheritance from this module; a line has that or `replacement_id`. Material Request lines take the existing code. Amount up to the verified Replacement Cost. Serial = old serial. | SRS 11.1 |
| Partner | Proposed in the Material Request claim order: supplier of the old serial, Warranty Claim Partner, vendor list. Editable in Draft, with the existing override reason. | V-3, C2 |
| Accounting | None automatic: the claim's existing draft credit note, posted by Accounting. Case Net Warranty Material Cost excludes a replacement recovery. | BA |

| New button | Business decision: Warranty > Vendor Claims offers New to users with create access (Helpdesk and Requisition users). The form takes the case and lines of a Material Request or a Done Vendor Replacement, with the same checks, partner rule and workflow as Create Vendor Claim. Version 18.0.1.4.9, `warranty_management_mrf` 18.0.1.9.4. | User decision 2026-11-04 |

Schema: new column `replacement_id` on the claim line, and NOT NULL removed from `mrf_line_id`. Existing claims are not changed. The New button adds no schema change.

Limits: a claim needs a verified cost above 0, so a product with no cost gets no claim, though its replacement completes. The Material Request cost reports do not list a replacement claim, because it has no Material Request line; the Vendor Claim report lists it.

### Component as built

| Topic | Decision | Source |
|---|---|---|
| Flow | Submit, Manager / GM approval, then the Material Request of the case with its own approval, issue, usage and cost. `Complete Replacement` when every line is used and every required return validated. | BA, SRS 11.1, Figure 3, Figure 7 |
| Data | `warranty.replacement.component.line`: component, quantity, old serial or details, return, Material Request line. New serials and used quantity are read from the Material Request. | SRS 11.1 |
| Defective return | Standard transfer to the Old Unit Location per line. A tracked part without its serial cannot be received, so the return is unticked with a required reason. | BA, proposal |
| Unchanged | Parent serial, card, unit, warranty dates. No replacement delivery and no Replacement Cost. | BA |
| PDF | Regenerated with the existing report and its Updated Copy label; no new row. | SRS 11.2, user decision |
| History | Replacement lines, the Warranty Date History row and the chatter. | SRS 11.1 |
| Reject | Refused once a part is recorded as used. | Proposal |

The case keeps a Material Request of its own, so a part issued before approval can only be linked by a person; the approval does not gate the Material Request itself. The Material Request flow stays unchanged by decision.

### Proposed design

| Topic | Proposal |
|---|---|

### Recommendations (user review 2026-11-03): proposed, not BA approved

These must not be treated as final. Code for them waits for approval.

| # | Recommendation | Open point |
|---|---|---|
| R1 | Resolved by the Phase 2 approval: Not Eligible and expired / out-of-warranty allowed, unless the warranty is Cancelled or Suspended. | - |
| R2 | Dropped: Goodwill on Eligible cases is not an SRS requirement or a confirmed decision. | - |
| R3 | Vendor replacement on expired warranties stays excluded unless approved. | - |
| R4 | Vendor replacement units use normal warehouse stock after a standard receipt. | - |
| R5 | Component replacement keeps the original warranty dates and records component history. | Updated PDF: SRS 11.2 asks for an updated card after replacement, with no exception; SRS 11.1 says the card "may remain same". BA to choose. |
| R6 | Defective component return is supported. A tracked part that cannot be identified needs a controlled exception with a reason. | - |
| R7 | Full Product kit replacement is excluded (confirmed). Goodwill and Vendor apply to single-serial Full Products; no silent extension to Indoor / Outdoor. | Whether to extend them later is a separate decision. |

### Preserved in every phase

Material Request approvals, stock movement controls and cost tracking stay as they are, with no duplicate workflow. The replacement links to Material Request lines and reads their usage and cost; it does not approve, issue or cost a part itself.

## Not in Stages 1 and 2

Accounting treatment and case totals of the replacement cost, Replacement Report, customer PDF sharing (no email,
WhatsApp or portal code exists), Component, Goodwill and Vendor execution, Full Product replacement of a
kit, Vendor Claim extension, Part 8 Closed.
