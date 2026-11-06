# Warranty Case Coverage Management (design, not implemented)

Status: design finalized 2026-10-29. Business-owner decisions A-F, 3, 8 and 9 approved.
**SRS deviation DEV-1 (Q27 / SRS 10.1) pending BA approval: development blocked until the BA
approves it and the business owner explicitly authorizes development.**

Planned versions: `warranty_management_helpdesk` 18.0.1.1.3, `warranty_management_mrf`
18.0.1.9.4 (no change to `warranty_management_fsm`). Separate release after the current
deployment package (fsm 18.0.1.3.2 / helpdesk 18.0.1.1.2 / mrf 18.0.1.9.3).

## Requirement

Every Warranty Case (single-service and merged, decision A) keeps its own coverage: the
Covered / Excluded Items of the policies of its participating cards, frozen when the case is
created (E). Helpdesk Managers may add, edit, remove and restore coverage items with a reason
(B). The effective case coverage drives eligibility, approval, the Partial / chargeable flow and
the MRF coverage defaults. Warranty Policy records are never written.

## Current implementation (before this change)

| Area | Behaviour | Code |
|---|---|---|
| Policy coverage | `covered_item_ids` / `excluded_item_ids` (Many2many `warranty.coverage.item`; no per-item conditions) | `warranty_management/models/warranty_policy.py` |
| Requested Items | Case `requested_item_ids` (Q22); automatic cases use the policy's Automatic Case Requested Items | `warranty_case.py`, `warranty_service_origin.py`, `warranty_draft_job.py` |
| Eligibility | Requested items checked against the main card's live policy (Q23, Q24, Q27, Q28) | `warranty_case._warranty_check_coverage` |
| Merged cases | D8: classification compared across all participating cards' live policies | `warranty_case._warranty_coverage_conflicts` |
| Approval | Revalidates the full check; segregation Q38-Q43 (creator / latest checker excluded when Case Approval Required) | `action_approve_case`, `_check_case_approver` |
| Chargeable / Partial | Excluded set read from the main card's policy only | `action_open_chargeable_wizard`, `_warranty_convert_chargeable` |
| MRF | Default coverage from the products of all case policies' items (mapping D7) | `material_purchase_requisition_coverage._warranty_default_coverage` |

## Data model (`warranty_management_helpdesk`)

`warranty.case.coverage.line` (never created, written or deleted directly; marker-guarded
like `warranty.shared.visit.line`; no unlink):

| Field | Meaning |
|---|---|
| `case_id`, `company_id` (related, stored) | Case; company record rule |
| `coverage_item_id`, `product_id` (related) | Item; product for quotations / MRF |
| `origin` | `policy` / `manual` |
| `original_type` | Covered / Excluded frozen at snapshot (policy lines; never changes; empty on manual lines) |
| `coverage_type` | Current type used by the checks |
| `removed` | Kept but not counted (lines are never deleted) |
| `source_policy_id`, `source_card_id`, `source_entitlement_ids` | Traceability; `source_entitlement_ids` = services this snapshot was taken for (kept after unlink, for audit) |
| `exception_approved_by_id`, `exception_approved_date` | Independent exception approval (cleared by any later change of the item) |
| `last_changed_by_id`, `last_changed_date`, `last_reason` | Latest change |

Case: `coverage_line_ids`, `coverage_modified_by_id`, `coverage_modified_date` (last manual
change or restore), `coverage_exception_activity_ids`.
Wizard `warranty.case.coverage.wizard`: Add / Edit Type / Remove / Restore; reason required.

## Rules

| # | Rule |
|---|---|
| R1 Snapshot (E) | On case create: one policy line per participating card policy x item x type, from the current policy. Same policy + item + type for several services of one card = one line with several source services. Same item from different policies = separate lines, never merged. Later policy changes never update the case. |
| R2 Linking services (D2) | A service linked later is snapshotted from its policy at that moment; an existing line with the same policy + item + type only gets the service added as a source. If the service was linked before and unlinked, its earlier frozen lines are reused (no new policy read). |
| R3 Unlinking services | The service stops being an *active* source; a line without any currently linked source service (and not sourced by the case's main card without services) is marked Removed with the system reason "free service unlinked". |
| R4 Manual changes (B) | Helpdesk Managers only, case New / Eligibility Checked, company checked server-side, reason mandatory. Add: manual line (item, type, card / services). Edit: type only (item change = remove + add). Remove: Removed flag. |
| R5 Restore (decision 8, clarification 3) | Policy lines with at least one currently linked source service (or sourced by the main card for cases without services) return to `original_type` and are un-removed; policy lines of unlinked services stay Removed; manual lines are marked Removed ("restored"); exception approvals cleared. The current policy is never read. Nothing is deleted. |
| R6 Audit | Every manual change, restore and system removal: chatter entry with user, date, action, item, before / after, source policy / card / services, reason. |
| R7 Reset (req. 3) | Any change of the effective coverage of an Eligibility Checked case calls `_warranty_reset_eligibility` (back to New, approval activities closed, logged). |
| R8 Effective coverage | `_warranty_effective_coverage()` from the non-removed lines: covered items, excluded items, conflicting items (Covered on one line and Excluded on another), unapproved exception items. Fallback: a case without lines (not migrated) reads the policy as before. |
| R9 Exception (D, decision 9, clarification 2) | An item counted Covered is an **exception** unless an active policy line of a currently linked source has `original_type` = `coverage_type` = Covered **and** no policy line of a currently linked source (active **or removed**) has `original_type` Excluded. Therefore: Excluded -> Covered, manual Covered of an undefined item, and removing / editing the Excluded line of a conflicting policy are all exceptions. |
| R10 Coverage check order | (1) a participating card without policy -> Manual Review (Q27 limitation kept; manual lines never compensate); (2) conflicting items -> Manual Review until resolved (clarification 1); (3) unapproved exception -> Manual Review, approval activities to the eligible approvers (not during approval revalidation); (4) existing Q23 / Q24 / Q28 rules on the effective items. |
| R11 Exception approval (decision 3) | Button Approve Coverage Exception: eligible = `_is_case_approver` users **minus** the last coverage modifier and the user who made the exception change; always a separate manual action, also when Case Approval Required is off; never automatic. Records user / date on the lines, logs; Check Eligibility needed afterwards. Any later change to a line of the item clears the approval. |
| R12 Case approval segregation (decision 3) | Approve refuses `coverage_modified_by_id` **always** (also when Case Approval Required is off), in addition to the existing Q38-Q43 rules. Reject unchanged. Approve revalidates with the effective coverage. |
| R13 Policies | Warranty Policy records are only read (snapshot); never written. |

## Consumers switched to the effective coverage

| Consumer | Change |
|---|---|
| `_warranty_check_coverage`, `_warranty_coverage_conflicts` | R8-R10 |
| Chargeable wizard default, `_warranty_convert_chargeable`, `_warranty_sync_excluded_items` | Effective excluded items (all participating cards) |
| MRF `_warranty_default_coverage` | Effective covered / excluded products; D7 unchanged; submitted / decided MRF lines not recalculated |
| Service Job approved excluded items, FSM, Automatic Case Requested Items | Unchanged |

## Security

Lines: read `base.group_user`, no direct create / write / unlink, company rule. Coverage wizard:
`helpdesk.group_helpdesk_manager` access + server checks (group, state, company). Exception
approval: R11 server check. Existing groups, rules and approval checks unchanged.

## Existing data

Migration (18.0.1.1.3): policy lines only for cases New / Eligibility Checked, from the policy
at migration time; eligibility untouched until the next check. Approved / closed / chargeable /
rejected cases get no lines and use the fallback (approval history not rewritten).

## SRS deviations for BA review

| ID | SRS / decision | Deviation | Status |
|---|---|---|---|
| DEV-1 | Q27 / SRS 10.1: coverage exists only on the Warranty Policy | The case's own coverage snapshot (editable by Helpdesk Managers) decides eligibility | **Pending BA approval - blocks development** |
| DEV-2 | Q23: an item is never assumed covered | Allowed only as an exception with independent approval (R9, R11) | Business owner approved (D, 9); BA review |
| DEV-3 | Q38-Q43 segregation only when Case Approval Required | Last coverage modifier excluded always; exceptions never auto-approved (R11, R12) | Business owner approved (3); BA review |
| DEV-4 | D8: compare the participating cards' live policies | Compare the case snapshot lines | Business owner approved (E); BA review |
| DEV-5 | Q28 / Q53: excluded set from the main card policy | All participating cards (fix for merged cases, behaviour change) | BA review |
| DEV-6 | MRF mapping D7: policy items | Effective case coverage | Business owner approved (req. 4); BA review |
| DEV-7 | E: snapshot at creation | Cases open at deployment are snapshotted at migration time | Accepted limitation; BA review |
| DEV-8 | Restore | Frozen snapshot of the currently linked services, never the current policy (R5) | Business owner approved (8); BA review |
| DEV-9 | Re-linking a previously unlinked service | Its earlier frozen lines are reused (R2) | BA review |

## Planned tests

Snapshot single / merged; duplicates not merged; link / unlink / re-link; add / edit / remove
with reason and chatter; restore (linked services only, history kept, policy unread); policy
unchanged; non-manager / locked state / other company refused; reset on each change; exception
cases of R9 -> Manual Review -> independent approval (modifier and exception author refused,
also with Case Approval Required off); conflict stays Manual Review until resolved; modifier
refused as approver; Partial / chargeable flow; MRF defaults; fallback without lines; migration;
full regression on `wt_p5_mrf`. Manual cases TC-COV-01.. in the Part 3 testing guide.
