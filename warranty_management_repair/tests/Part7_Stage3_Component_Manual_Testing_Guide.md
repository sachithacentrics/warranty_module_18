# Part 7 Stage 3 Phase 4: manual UAT checklist (Component Replacement)

Version 18.0.1.4.6. Users: a **Coordinator** (Helpdesk + Inventory) and an **Approver** in Replacement GM Approvers.

**Setup:** an Eligible, Approved case on a Confirmed card; a tracked part `PCB` with serials `PCB-OLD` and `PCB-NEW`, with `PCB-NEW` in stock for the Material Request.

| # | Step | Expected |
|---|---|---|
| 1 | Coordinator: Request Replacement, Type **Component**, a Reason | Serial and date policy fields are hidden; a Components list shows |
| 2 | Add a line: `PCB`, quantity 1, Old Serial `PCB-OLD`. Save, Submit | **Submitted**, no transfers, parent serial unchanged |
| 3 | Coordinator | No Approve button |
| 4 | Approver: To-Do and Approve | "approval needed (Manager / GM)"; **Approved**, GM fields filled, no Finance, one Return Picking on the line, **no delivery** |
| 5 | **Create Material Request**, line `PCB`. Take it through its usual approval, issue and Record Usage with `PCB-NEW` | The existing Material Request steps, unchanged |
| 6 | On the replacement line, select the **Material Request Line** | Used and New Serial / Lot fill in |
| 7 | **Complete Replacement** before validating the return | Refused |
| 8 | Validate the return, then Complete Replacement | **Done**, Updated Card Generated = Yes |

**After Done**

| Check | Expected |
|---|---|
| Parent serial, card number, unit number, warranty dates | Unchanged |
| Replacement Cost | Empty; the cost is on the Material Request |
| Warranty Date History, chatter | One row and notes showing `PCB-OLD` and `PCB-NEW` |
| PDF | Regenerated, Updated Copy label, parent serial unchanged |
| Stock | `PCB-OLD` in the Old Unit Location; `PCB-NEW` moved only by the Material Request |
| Case | Completes through its usual job or repair path |

**Other checks**

1. **No return:** Old Serial empty on a tracked part: Submit refused. Untick Return Defective Part: a reason is required, then no return is created.
2. **Untracked part:** return with no serial and the entered quantity.
3. **Partial usage:** fewer used than the line quantity: Complete Replacement refused.
4. **Wrong link:** only lines of this case and this product are offered.
5. **Reject:** allowed before usage, and the open return is cancelled; refused once usage is recorded.
6. **Kit unit:** Component on a kit case: Indoor and Outdoor serials unchanged.
7. **Out of Warranty case:** refused.
8. **Regression:** one quick flow each of Full Product, Indoor or Outdoor, Goodwill and Vendor.
