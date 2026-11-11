# Complete Warranty Case after a Done replacement: manual testing guide

Run this only on a test database, after `warranty_management_repair` 18.0.1.7.7 has been
upgraded there with your approval. Design: `doc/replacement_case_completion.md`.

## A. Setup

- **Users:**
  - a **Coordinator** with Helpdesk User and Inventory rights;
  - a Replacement GM Approver;
  - a user without Helpdesk rights.
- **Cases:** Approved, Eligible cases, each with a replacement whose return and delivery are
  validated, so the replacement is **Done**:
  - a Vendor Replacement;
  - a Full Product replacement;
  - an Indoor Unit replacement;
  - an Outdoor Unit replacement.

## B. Tests

| # | Step | Expected |
|---|---|---|
| TC-RC-01 | Open a case whose replacement is Done | Status still **Approved**: nothing completes automatically. **Complete Warranty Case** is shown. |
| TC-RC-02 | Vendor case: Complete Warranty Case, confirm | Status **Completed**. The case and the replacement each get the note "completed by … after replacement …". **Close Case** is shown. |
| TC-RC-03 | Same case: Close Case | Status **Closed**. An existing Vendor Claim keeps its status. No new journal entry. |
| TC-RC-04 | Repeat TC-RC-02 for the Full Product case, then for the Indoor and Outdoor cases | Completed |
| TC-RC-05 | A case whose replacement is Approved but the delivery is not validated | No button. The action from the server refuses it: replacement not finished. |
| TC-RC-06 | A Done replacement plus a second Draft replacement on the same case: Complete | Refused: "Replacement … is not finished" |
| TC-RC-07 | A case with an open service job | Status Job Created and no button. The job completes the case. |
| TC-RC-08 | Log in as the user without Helpdesk rights | No button. The server refuses the action. |
| TC-RC-09 | Goodwill case (Out of Warranty, Done Goodwill replacement) | Only the existing Goodwill **Complete Warranty Case**. It completes and keeps the Out of Warranty result. |
| TC-RC-10 | Case with only a Done **Component** replacement | No button (Component is reviewed separately) |
| TC-RC-11 | A Repair Order and service job completion, as in Figure 6 / Part 4 | Unchanged |

## C. Existing UAT cases

After the upgrade, open each case below and use Complete Warranty Case, then Close Case. On the
copy of 2026-11-10, none of them had a blocker.

- WCAS/000039
- WCAS/000043
- WCAS/000044
- WCAS/000049
- WCAS/000060
- WCAS/000082

WCAS/000082 has **Inspection Required = Yes**. This flag only decides the service-job path:
- it is not checked by the completion;
- do not use Prepare Service Job on a case whose replacement is Done.
