# Complete Warranty Case after a Done replacement

Version: `warranty_management_repair` 18.0.1.7.7. Approved by the user on 2026-11-10.

## 1. Problem

An eligible case can get a replacement without a service job or a Repair Order. When the
replacement is Done, nothing completes the case:

- the K6 guard allows Completed only with the internal completion marker;
- the marker is used only by the service job, the Repair Order and the Goodwill paths;
- a replacement-only case has none of these, so it stays Approved and cannot be closed.

On UAT on 2026-11-10 this affected WCAS/000039, 000043, 000044, 000049, 000060 and 000082.

## 2. Decisions

| # | Decision |
|---|---|
| R1 | Applies to Done **Full Product, Vendor Replacement, Indoor Unit and Outdoor Unit** replacements. |
| R2 | **Component** replacements are not included; they will be reviewed separately. Goodwill keeps its own completion. |
| R3 | No new Inspection Quotation requirement for this action (see section 4). |
| R4 | The K6 guard and the `_COMPLETION_MARKER` stay. The new action uses the same marker. |
| R5 | Reuse the Goodwill blockers; the Goodwill, service job and Repair Order paths do not change. |
| R6 | The user starts the completion. A Done replacement never completes the case by itself. |
| R7 | Close Case stays a separate step with all its checks. Vendor Claims never block. No journal entries. |

## 3. Behaviour

Case form button **Complete Warranty Case**:

- **Shown when** the case is Approved, its result is Eligible, it has a Done replacement of an R1
  type, and the user is a Helpdesk User. The field is `warranty_replacement_can_complete`.
- **Rights:** Helpdesk User. Any other user gets an AccessError.
- **Blockers:** every blocker is listed in one message:
  - the case is not Approved and Eligible with a Done R1 replacement;
  - the case has no Case Type;
  - the return of the old serial or the delivery of the new serial is not validated (a defensive
    check: Done already means the replacement was approved and both transfers were validated);
  - a Repair Order of the case is not finished;
  - the shared blockers, `_warranty_completion_blockers()`, taken unchanged from the Goodwill
    check:
    - an open or unresolved rejected replacement;
    - an open service job;
    - a Repair Order whose machine has not been returned (unless the replacement covers it);
    - a free service waiting to be used;
    - Material Request problems.
- **Result:**
  - the state becomes Completed (written with sudo and the completion marker);
  - Repair Orders covered by the replacement close their "complete the warranty case" To-Do;
  - a note "Warranty case … completed by … after replacement …" is added to the replacement,
    ticket, case, card and the related Repair Orders.
- **Close Case** does not change: it still needs a Completed case and runs all its checks.

The approved case states with an open job (`job_created`, `in_progress`) still complete through
their job. An open service job is also a blocker.

## 4. Inspection Required on replacement-only cases

`warranty_inspection_required` comes from the Helpdesk team (SRS Figure 4 / 10.4). It decides
only the **service job path**:

- Prepare Service Job first creates an inspection quotation;
- the job is created when the quotation meets the Inspection Trigger;
- Convert to Chargeable adds the inspection line.

It is not a completion or closure check, and it does not apply to a replacement-only case. This
change does not read, change or bypass the flag.

On a case such as WCAS/000082 (Inspection Required = Yes, no quotation, no job), Prepare Service
Job is still visible. Do not use it after a Done replacement: it would create an inspection
quotation that the replacement does not need.

## 5. Code

- `models/warranty_case.py`:
  - `COMPLETION_REPLACEMENT_TYPES`;
  - the field `warranty_replacement_can_complete`;
  - `_warranty_completion_replacements()`;
  - `_warranty_replacement_completion_problems()`;
  - `action_warranty_complete_replacement_case()`;
  - `_warranty_completion_blockers()`, extracted from `_warranty_goodwill_completion_problems()`
    with the same checks, order and messages.
- `views/warranty_case_views.xml`: the button with a confirmation.
- `tests/test_replacement_case_completion.py`: `TestReplacementCaseCompletion`, 10 tests.
- Manual guide: `tests/Replacement_Case_Completion_Manual_Testing_Guide.md`.

## 6. Open items

- Component replacement completion: separate review (R2).
- The existing UAT cases are not changed automatically. After the upgrade, a Helpdesk user
  completes each one with the button, then uses Close Case.
