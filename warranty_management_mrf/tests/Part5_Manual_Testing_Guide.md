# Part 5 – Manual Testing Guide, Phases 5.0 – 5.5 (Material Request / MRF Integration)

## Test environment

* Disposable database **`wt_p5_mrf`** only, test server **http://localhost:8299** (started with the
  temporary `decimal_precision` test shim – blocker **B1** is still open, see
  `doc/part5_design_decisions.md`; the shim is not an approved solution and is not deployed).
* Do **not** use `warranty_management_18_2` or `warranty_test` for these tests.
* Passwords = login. Use a second browser / private window for the other users.
* Write the result in the *Actual* / *Status* columns (Pass / Fail + short note).

### Users

| Login | Name | Role in the tests |
|---|---|---|
| `admin` | Administrator | Requester / Service Coordinator (Helpdesk, Requisitions, Sales); employee in *Administration* |
| `approver_w` | Warranty Approver | Warranty Case Approval User = coverage reviewer (5.2); Chargeable Release Exception User (5.4); no Sales rights |
| `svc_manager` | Service Manager | Manager approver (5.3) |
| `finance_off` | Finance Officer | Finance approver (5.3) |
| `gm_user` | General Manager | GM approver (5.3) |
| `store_user` | Store User | Requisitions + Inventory + Purchase user (5.3 – 5.5) |
| `helpdesk2` | Second Coordinator | Another Helpdesk user, no rights on admin's requests |
| `tech_t` | Technician T | Field Service user, technician of jobs B and G; employee location **WH/Van 1** |
| `tech_x` | Technician X | Another technician (no jobs) |
| `noemp` | No Employee User | Helpdesk user without employee |

### Records (all Approved, customer **ABC Hotel (MRF test)**, no Material Requests yet)

| Case | Number | Use |
|---|---|---|
| A | **WCAS/015553** | 5.1 – case without job; later converted to Chargeable (TC-P5-210, 415) |
| B | **WCAS/015554** | 5.1 – service job **JOB/004690** Confirmed, Technician T, with its visit task |
| C | **WCAS/015897** | 5.2 – coverage |
| D | **WCAS/016338** | 5.3 – approval matrix (E **WCAS/016339** spare) |
| F | **WCAS/016869** | 5.4 – parts quotation |
| G | **WCAS/017739** | 5.5 main scenario – service job **JOB/005430** Confirmed, Technician T, visit *JOB/005430 - WCAS/017739 - MRF Split AC* |
| H | **WCAS/017740** | 5.5 side scenarios |
| I | **WCAS/019824** | 5.6 main scenario – service job **JOB/006038** Confirmed, Technician T, visit *JOB/006038 - WCAS/019824 - MRF Split AC* |
| J | **WCAS/019825** | 5.6 reversal / reschedule / Cancel Remaining / Draft cancel – service job **JOB/006039** Confirmed, Technician T |

### Products and stock (source WH/Stock)

| Product | Cost / Sales price | Coverage (policy *MRF Test Policy*) | Free in WH/Stock | Vendor |
|---|---|---|---|---|
| Outdoor PCB | 18,500 | Covered | 40 | – |
| Expansion Valve | 2,000 | Covered | **2** | Cool Parts Ltd (1,800) |
| Gas R410A | 3,000 / 4,000 | Not Covered (Excluded Item) | 20 | – |
| Fan Motor | 1,000 / 1,500 | Not Covered (Excluded Item) | 20 | – |
| Copper Pipe | 10 | not in the policy -> **Pending** | 5 | – |

### Approval rules (Warranty -> Configuration -> Material Approval Rules, illustrative values)

| Rule | Condition | Levels |
|---|---|---|
| TEST Low value | below 25,000 | No Approval Required |
| TEST Level 1 | 25,000 – 100,000 | Manager (svc_manager) -> Finance (finance_off) |
| TEST High value | from 100,000 | Manager -> Finance + GM (gm_user) |
| TEST Goodwill | goodwill lines | Finance + GM |
| TEST Chargeable only | only Not Covered lines, below 25,000 | Manager |

Routing amount = all lines, each at max(Estimated Unit Cost, product cost). Examples: PCB x1 =
18,500 (no approval); PCB x2 = 37,000 (Level 1); PCB x6 = 111,000 (High value).

### Current settings (Settings -> Warranty -> Material Requests) and when to change them

| Setting | Now | Change |
|---|---|---|
| Material Approval Matrix | **On** | **Switch Off before 5.1** (5.1 / 5.2 use the vendor workflow); **On again at the start of 5.3** |
| Approval To-Do Deadline | 1 day | – |
| Technician Location | WH/Technician Stock | TC-P5-102 |
| Chargeable Parts Release | **On Quotation Confirmation** (set by the 5.6 data) | TC-P5-401 (On Quotation Confirmation), TC-P5-409 (On Payment), On Payment for 5.5, On Quotation Confirmation for 5.6 |
| Chargeable Release Exception Users | approver_w | – |

Recommended order: 5.0 -> 5.1 -> 5.2 -> 5.3 -> 5.4 -> 5.5, because later phases rely on the settings
above and on stock left by earlier steps.

---

## Phase 5.0 – Foundation

B1: the unchanged vendor build of `material_purchase_requisitions` (11.9.12) does not load on Odoo 18
(`import odoo.addons.decimal_precision`). In this environment both modules are installed with the
test shim.

| # | User | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-P5-000 | admin | Apps -> remove the *Apps* filter -> search **Requisitions Material** and **Warranty Management - Material Requests**. | Both **installed** (only thanks to the shim; without it the vendor module fails with `No module named 'odoo.addons.decimal_precision'` – B1, verified on the disposable databases). | | |
| TC-P5-001 | admin | Main menu. | **Purchase** and **Requisitions** apps present; Warranty menu has **Material Requests** (5.1) and Configuration -> **Material Approval Rules** (5.3). | | |
| TC-P5-002 | admin | Settings -> Users -> admin -> *Access Rights*. | Section **Material Purchase Requisitions** (User / Manager) and the separate **Department Manager** checkbox; Helpdesk, Field Service, Inventory, Purchase, Sales, Accounting rights unchanged. | | |
| TC-P5-003 | admin | Requisitions -> New: Employee = admin's employee, Department; line 1 *Internal Picking* Outdoor PCB x1; line 2 *Purchase Order* Fan Motor x1, Vendor Cool Parts Ltd; Picking Details: Source WH/Stock, Destination WH/Technician Stock, Picking Type *Internal Transfers* -> Save. | Number **EPR…**, status **New**; no Warranty section, no coverage / approval fields. | | |
| TC-P5-004 | admin | Confirm -> Department Approve -> Approve -> Create Picking and PO. | Waiting Department Approval -> Waiting IR Approval -> Approved -> **Picking / Purchase Created**; smart buttons Internal Picking (PCB x1) and Purchase Order (RFQ Cool Parts Ltd, Fan Motor x1). | | |
| TC-P5-005 | admin | Received. | Status **Received**. | | |
| TC-P5-006 | admin | Spot check Parts 1–4: confirm a warranty card, create a case -> Check Eligibility -> Approve -> Prepare Service Job -> Plan / Confirm -> Start Visit -> Complete Visit. Open Settings -> Warranty. | Works as before (the open scheduling item JOB/000002 / WSE/00002 is a known blocker, not a 5.x failure); Settings page opens. | | |
| TC-P5-007 | admin | AMC: open an AMC contract and the AMC menus. | Unchanged. | | |

Role mapping (approved in 5.0, design decision R1):

| SRS role | Groups |
|---|---|
| Service Coordinator | Helpdesk User + Requisitions User |
| Technician | Field Service User |
| Store User | Inventory User + Requisitions User |
| Material Approver | Named approver in the approval rule (5.3) |
| Purchasing | Purchase User |
| Accountant | Accounting Read-only / Billing |

---

## Phase 5.1 – Create / link Material Requests

**Before you start:** Settings -> Warranty -> Material Requests -> **Material Approval Matrix off** -> Save.

| # | User | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-P5-101 | admin | Warranty -> **Material Requests**. | Menu exists; list empty ("No warranty material request yet"); no *New* button. | | |
| TC-P5-102 | admin | Settings -> Warranty -> **Material Requests** (Source Location, Technician Location, Picking Type). Technician Location = **WH/Technician Stock** (already set) -> try other values -> keep WH/Technician Stock, save. | Only internal locations / internal transfer types of the company offered. | | |
| TC-P5-103 | admin | Case A **WCAS/015553** -> **Create Material Request**. | New form: Warranty section shows Case, Ticket, Customer, Site, Serviced Product (Card / Unit / Serial when set); Employee = admin's employee, Department Administration; Source WH/Stock, Destination **WH/Technician Stock**, Picking Type Internal Transfers; Reason "Parts for WCAS/015553". | | |
| TC-P5-104 | admin | Line Outdoor PCB, Qty 2 -> Save. | Number **MRF/…** (next free number); Estimated Unit Cost 18,500, Estimated Cost 37,000; Total Estimated Cost 37,000; status **New**; chatter "Warranty links: WCAS/015553". | | |
| TC-P5-105 | admin | Back to case A. | Smart button **Material Requests (1)**; chatter note "Material Request MRF/… created by Administrator". | | |
| TC-P5-106 | admin | Case B -> job **JOB/004690** -> **Create Material Request** -> line PCB x1 -> Save. | Links Case B + Service Job + Field Service Task (the job's visit); Destination **WH/Van 1** (Technician T's location). Job and case: smart button + note. | | |
| TC-P5-107 | tech_t | Field Service -> visit task of JOB/004690 -> **Create Material Request** -> line PCB x1 -> Save. | Created; Employee = Technician T; same links; task smart button **Material Requests**. | | |
| TC-P5-108 | admin | Helpdesk ticket of case B. | Smart button **Material Requests (n)** with the case's requests. | | |
| TC-P5-109 | admin | Request of TC-P5-104: Estimated Unit Cost 17,000; add line Copper Pipe, UoM **Dozens**, Qty 1. | Totals recomputed (17,000 x 2; dozen line unit cost 120). | | |
| TC-P5-110 | admin | Requisitions -> New standalone request (as TC-P5-003, keep it New). Case A -> **Link Material Request** -> pick it -> Link. | Number **EPR…** kept; links set; note "linked" on the case. Wizard offers only New, unlinked requests of the case company. | | |
| TC-P5-111 | admin | Try to link the same request again / a request in Waiting Department Approval. | Not offered (refused if forced). | | |
| TC-P5-112 | admin | A case in New / Rejected; a service job in Draft; an ordinary (non-warranty) Field Service task. | No Create / Link buttons; via the visit of a closed job: refused with a clear message. | | |
| TC-P5-113 | noemp | Case A -> Create Material Request. | Error "You need an employee linked to your user …". (Employee without department: "… has no department".) | | |
| TC-P5-114 | tech_t, then tech_x | Warranty -> Material Requests. | Technician T sees the requests of his jobs (read only); Technician X sees none of them. | | |
| TC-P5-115 | admin | Requisitions -> filters **Warranty Requests** / **Standalone Requests**, group by **Warranty Case**. | Work; standalone requests have no Warranty section or cost columns. | | |
| TC-P5-116 | admin | Standalone request: Confirm -> Department Approve -> Approve -> Create Picking and PO -> Received. | Unchanged vendor workflow. | | |
| TC-P5-117 | admin | Spot check Parts 1–4 and AMC (TC-P5-006 / 007). | Unchanged. | | |

---

## Phase 5.2 – Coverage classification and coverage decision

Matrix still **off**. Data: Outdoor PCB / Expansion Valve = Covered Items, Gas R410A / Fan Motor =
Excluded Items of *MRF Test Policy*; Copper Pipe in neither list; Warranty Case Approval Users include
approver_w.

| # | User | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-P5-201 | admin | Case C **WCAS/015897** -> Create Material Request -> lines Outdoor PCB 1, Gas R410A 1, Copper Pipe 1 -> Save. | Coverage Type: PCB **Covered**, Gas **Not Covered**, Pipe **Pending Coverage Decision** (optional column *Coverage Basis*); header Coverage **Pending Decision**; yellow banner "1 line(s) pending". | | |
| TC-P5-202 | admin | Confirm. | Refused: "the coverage of Copper Pipe is pending". | | |
| TC-P5-203 | admin | **Request Coverage Decision**. Click again. | To-Do "Decide warranty coverage…" for Warranty Approver; second click only logs "already requested". | | |
| TC-P5-204 | admin | Look for **Decide Coverage**. | Not shown to the requester / creator. | | |
| TC-P5-205 | approver_w | Request -> **Decide Coverage** -> Copper Pipe, *Covered (Goodwill)*, empty reason -> then reason "Goodwill for key customer" -> Apply. | Reason required; then Pipe Covered + Goodwill, Decided By / Date / Reason (optional columns); notes on request and case; To-Do done; Coverage **Mixed**; banner gone. | | |
| TC-P5-206 | approver_w | Decide Coverage -> Gas -> *Covered*, reason. | Gas Covered, Goodwill off. | | |
| TC-P5-207 | admin | Change the Copper Pipe line's product to Outdoor PCB. | Line back to its default (Covered), decision cleared. | | |
| TC-P5-208 | admin | Confirm. Then try: edit a product, add a line, delete a line, Decide Coverage. | Status Waiting Department Approval; all refused ("locked"); Coverage read only. | | |
| TC-P5-209 | admin | Department Approve -> Reject -> Reset to Draft. | Coverage editable again. | | |
| TC-P5-210 | admin | Convert case A **WCAS/015553** to **Chargeable** (Part 3) -> Create Material Request with Outdoor PCB. | Every line **Not Covered** ("Chargeable warranty case"). Keep it New. | | |
| TC-P5-211 | admin | Standalone request with a line -> Confirm. Then link a New standalone request with Outdoor PCB to case C. | Standalone: no coverage column / buttons, confirm works. Linked: line becomes Covered. | | |
| TC-P5-212 | admin | Requisitions list: filter **Coverage Pending**, group by **Coverage**. | Work. | | |
| TC-P5-213 | admin | Spot check 5.1 (TC-P5-103 / 106 / 110), Parts 1–4, AMC. | Unchanged. | | |
| TC-P5-214 | approver_w | Case C: request with PCB, Gas, Copper Pipe (and a second request with Copper Pipe) -> **Request Coverage Decision** -> as approver_w **Decide Coverage**. (a) Look at the table; try to add / delete a line. (b) Keep only Copper Pipe ticked -> *Covered (Goodwill)*, reason -> Apply. (c) Decide Coverage again: nothing ticked -> Apply. (d) Tick PCB and Gas -> *Not Covered*, reason "Physical damage" -> Apply. (e) As admin (requester): Decide Coverage. | (a) The wizard itself lists **all lines of this request only**: checkbox, **Product, Quantity, Unit of Measure, Current Coverage Type, Coverage Basis**; Copper Pipe (Pending) preselected; no *Add a line*, no delete, no second popup; product / quantity not editable. (b) Only Copper Pipe changes (Covered + Goodwill); PCB, Gas and the second request unchanged. (c) Nothing preselected; refused "Select the lines …". (d) Both lines Not Covered with that reason; Copper Pipe keeps its goodwill decision. (e) Button not shown / refused. Chatter notes on request and case for every decision. | | |

---

## Phase 5.3 – Material approval matrix

**Before you start:** Settings -> **Material Approval Matrix on**, deadline 1 day -> Save.

| # | User | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-P5-301 | admin | Settings (matrix, deadline); Warranty -> Configuration -> Material Approval Rules list / form: try a rule with no level and not *No Approval Required*; a level without approvers. | Validation errors; the five TEST rules listed. | | |
| TC-P5-302 | admin | Case D **WCAS/016338** -> Create Material Request -> PCB x1 -> Save -> **Confirm / Submit**. | **Approved** at once; Approvals tab: round 1, *No Approval Required* (TEST Low value); chatter + case note. | | |
| TC-P5-303 | admin | Archive *TEST Low value*; new request PCB x1 -> Submit. Unarchive the rule afterwards. | Refused: "No material approval rule matches …"; stays New. | | |
| TC-P5-304 | admin | New request PCB x1 + Gas x3 (27,500) -> Submit. | Routing Amount 27,500; status **Manager Approval**; Approvals: Manager pending (svc_manager), Finance pending, GM skipped; To-Do for svc_manager due tomorrow; vendor buttons *Department Approve / Approve / Reject* hidden. | | |
| TC-P5-305 | finance_off | Warranty -> Material Requests, filter *Waiting for My Approval* -> open it. | Visible, read only; no Approve button yet (Manager first). | | |
| TC-P5-306 | svc_manager, then finance_off | **Approve** each. | After Manager: Finance/GM Approval, To-Do for finance_off. After Finance: **Approved**, Approved By finance_off, Approved Amount 27,500; admin notified; case note. | | |
| TC-P5-307 | store_user | **Create Picking and PO** on that request. | Refused: create the parts quotation or record the customer decline for the Not Covered lines first (5.4). | | |
| TC-P5-308 | admin -> svc_manager -> finance_off -> store_user | New request PCB x2 (37,000) -> Submit -> Approve -> Approve -> Create Picking and PO. | Approved; internal picking PCB x2 (status Picking / PO Created). | | |
| TC-P5-309 | admin, svc_manager, gm_user, finance_off | New request PCB x6 (111,000) -> Submit -> Manager -> **GM** -> Finance. Repeat with Finance before GM. | Manager first; GM and Finance in any order; Approved only after the last. | | |
| TC-P5-310 | admin, approver_w, finance_off, gm_user | New request Copper Pipe x1 -> approver_w: Decide Coverage -> *Covered (Goodwill)* -> admin Submit -> approve. | Levels Finance + GM (goodwill), no Manager. | | |
| TC-P5-311 | admin | New request Gas x1 (only Not Covered, 3,000) -> Submit. | TEST Low value + TEST Chargeable only match -> **Manager** required (strictest wins). | | |
| TC-P5-312 | admin, finance_off | Add **admin** to the Manager approvers of TEST Level 1; admin submits PCB x2. Add **finance_off** to the GM approvers of TEST High value; submit PCB x6; finance_off approves Finance, then tries GM. Restore both rules. | admin is not an approver of his own request; finance_off: "You already approved a level …". | | |
| TC-P5-313 | admin, store_user | On a request waiting for approval: admin edits Reason, a quantity, the estimated unit cost, adds / deletes a line; store_user changes Destination Location and a line's Requisition Action. | admin refused ("locked …"); store_user allowed. | | |
| TC-P5-314 | svc_manager | Reject without / with reason "Use refurbished PCB". | Reason required; **Rejected**; Manager Rejected, Finance Superseded; To-Dos closed; admin notified; case note. | | |
| TC-P5-315 | helpdesk2, admin | helpdesk2: Reset to Draft (refused). admin: Reset to Draft, change quantity, Submit. | Round 2 with all required levels; round 1 kept in the Approvals tab. | | |
| TC-P5-316 | admin, svc_manager, helpdesk2 | Submit PCB x2, svc_manager approves; helpdesk2 opens it (no Withdraw); admin **Withdraw**. | Back to New; Manager Approved, Finance **Withdrawn**; To-Dos closed; resubmission = new round. | | |
| TC-P5-317 | admin | New request PCB x2, Estimated Unit Cost 1,000 -> Submit. | Estimated Cost 2,000 kept; Routing Amount 37,000 -> Level 1. | | |
| TC-P5-318 | admin | Submit PCB x2, then change TEST Level 1 (other manager / remove Finance). | Pending approvers of the submitted request unchanged; restore the rule. | | |
| TC-P5-319 | admin, store_user | The request confirmed in 5.2 without an approval round (TC-P5-208/209 path, if still confirmed) or any request confirmed while the matrix was off. | Red banner "submitted before the approval workflow"; Create Picking and PO / vendor approve refused; Withdraw (requester) -> New. | | |
| TC-P5-320 | admin | Delete a withdrawn request (New, with approval history); then Cancel it. | Delete refused; Cancel allowed (New / Rejected only). | | |
| TC-P5-321 | admin | Received request: Reset to Draft. | Not offered / refused. | | |
| TC-P5-322 | admin | Settings: matrix **off**; submit PCB x2. Then switch the matrix **on** again. | Vendor workflow (Waiting Department Approval, vendor buttons); requester cannot approve own request; department approver cannot also give the final approval. | | |
| TC-P5-323 | admin | Standalone request: Confirm -> Department Approve -> Approve -> Create Picking and PO -> Received. | Unchanged vendor workflow; no approval fields / tab. | | |
| TC-P5-324 | admin | Spot check 5.1 / 5.2, Parts 1–4, AMC. | Unchanged. | | |
| TC-P5-325 | admin | Case D -> new request PCB x2 + Copper Pipe x1 -> approver_w: Copper Pipe *Covered (Goodwill)* -> admin: **Check Approval Route**. | Green "can be submitted"; routing amount $ 37,010.00 (covered / not covered / goodwill); all rules with condition, levels and *Matches* (TEST Level 1 and TEST Goodwill Yes); levels Manager (Service Manager), Finance (Finance Officer), GM (General Manager), excluded "-". Close: the request is still **New**, no Approvals tab entry, no To-Do, no chatter message. | | |
| TC-P5-326 | finance_off | Same request (open it from the list as Finance Officer if visible, or as admin set **TEST Goodwill** / **TEST Level 1** Finance approver = admin) -> Check Approval Route. | Red "cannot be submitted": *The Finance approval … has no available approver. Rule(s): … Configured Finance approvers: Administrator (requester, creator, submitter)*; table shows the excluded approver with the reasons. Restore Finance Officer afterwards. | | |
| TC-P5-327 | admin | Remove the GM approver from TEST Goodwill (untick GM Approval) -> Check Approval Route -> Submit. | Preview and Submit: *Goodwill materials require GM approval (goodwill lines: Copper Pipe), but none of the matching approval rules (…) requires GM approval with GM approvers …*; request stays New. Restore TEST Goodwill (GM Approval, General Manager). | | |
| TC-P5-328 | admin | Set General Manager as Finance **and** GM approver of TEST Goodwill and remove Finance Officer from TEST Level 1 -> Check Approval Route. | *needs a different approver for every approval level … Eligible approvers: Manager: …; Finance: General Manager; GM: General Manager*. Restore the rules. | | |
| TC-P5-329 | admin, svc_manager, finance_off, gm_user, store_user, helpdesk2 | Submit the request of TC-P5-325. Open it as each user at each stage (Manager Approval, then Finance/GM Approval). | Approve / Reject visible **only** to svc_manager at Manager Approval, to finance_off and gm_user at Finance/GM Approval (each until he has approved), never to admin (requester / creator / submitter), store_user or helpdesk2; *Check Approval Route* hidden after Submit. | | |
| TC-P5-330 | admin, dept user, store_user | Settings: matrix **off**. Submit a PCB x1 request as admin (admin has Department Manager rights). | admin: no *Department Approve / Approve / Reject*; department manager (not admin): Department Approve + Reject; after it: the same user sees no *Approve*, store_user sees Approve + Reject. Standalone request: vendor buttons by group as before. Matrix **on** again. | | |

---

## Phase 5.4 – Commercial control of Not Covered lines

| # | User | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-P5-401 | admin | Settings -> *Chargeable Parts Release* = **On Quotation Confirmation**; *Chargeable Release Exception Users* = approver_w -> Save. | Settings shown and saved. | | |
| TC-P5-402 | admin | Case F **WCAS/016869** -> Create Material Request -> PCB x1, Gas R410A x2, Fan Motor x1 (total 25,500 -> Level 1) -> Submit -> svc_manager and finance_off approve. | Approved; PCB no chargeable status, Gas / Fan Motor **To Quote**; button **Create Parts Quotation**. | | |
| TC-P5-403 | store_user | **Create Picking and PO**. | Refused: create the parts quotation or record the customer decline first. | | |
| TC-P5-404 | admin | **Create Parts Quotation**. | Quotation with only Gas x2 and Fan Motor x1 (sales prices 4,000 / 1,500), customer ABC Hotel, delivery address = site, field Material Request; in the case's Quotations; To-Do "Send quotation …" on the case; **no Service Job**; request lines action **Customer Quotation**, status **Waiting Customer**. | | |
| TC-P5-405 | admin | Quotation: change a quantity / delete a line / change a price. | Quantity and delete refused; price allowed. | | |
| TC-P5-406 | admin | Request -> **Customer Declined** -> Fan Motor, reason "Too expensive". | Fan Motor removed from the quotation, **Customer Declined**; Gas still quoted; notes on request and case. | | |
| TC-P5-407 | store_user | **Create Picking and PO**. | Internal picking with **only Outdoor PCB** (no Gas, no Fan Motor). | | |
| TC-P5-408 | admin | Confirm the quotation. | Gas **Released**; quotation delivery Gas x2 – validate it (the only issue of the Gas). | | |
| TC-P5-409 | admin | Settings: **On Payment**. Case F -> new request Gas x1 -> Submit (Manager approval, TEST Chargeable only) -> svc_manager approves -> Create Parts Quotation -> Confirm. | Quotation shows Parts Release Trigger **On Payment**; Gas **Waiting Payment**; validating the delivery refused. | | |
| TC-P5-410 | admin | Create Invoice -> post -> register **half** the amount. | Still Waiting Payment; delivery still refused. | | |
| TC-P5-411 | admin | Register the rest. | **Released**; delivery can be validated. | | |
| TC-P5-412 | admin, approver_w | New request Gas x1 -> approve -> quotation -> confirm. admin: look for *Approve Release Exception*. approver_w: Approve Release Exception, empty reason, then reason. | admin: not offered; approver_w: reason required, then **Released (Exception)**; delivery can be validated. | | |
| TC-P5-413 | admin | New request Gas x1 -> approve -> quotation -> **cancel** the quotation. | Gas back to **To Quote**; a new quotation can be created. | | |
| TC-P5-414 | admin | Confirmed quotation's request: Customer Declined. | Not offered / refused. | | |
| TC-P5-415 | admin | Chargeable case A **WCAS/015553** (TC-P5-210): submit its request (all lines Not Covered) -> approve if required -> quotation -> confirm. | No Chargeable Purpose on the quotation; no Service Job created. | | |
| TC-P5-416 | approver_w | Create Parts Quotation on a request with To Quote lines. | Refused ("requires Sales rights"). | | |
| TC-P5-417 | admin | Approvals tab / coverage columns of the requests above. | Unchanged by quotation, decline and release. | | |
| TC-P5-418 | admin | Spot check 5.1 – 5.3, Parts 1–4, AMC. | Unchanged. | | |

---

## Phase 5.5 – Stock availability, issue and purchase

**Before you start:** Settings -> *Chargeable Parts Release* = **On Payment**; matrix **on**.
Columns on the request lines (some optional): **Approved Qty, Free at Source, Stock Availability**
(Available / Partially Available / Not Available), **Issued, In Picking, Purchased, Received,
Outstanding, Issue Status** (To Issue / Partially Issued / Issued); header **Issue Progress**.

### Main scenario – case G **WCAS/017739**, job **JOB/005430**

Warranty case -> request -> coverage decision -> approval -> customer quotation / payment -> stock
availability -> issue / purchase -> receipt -> remaining issue.

| # | User | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-P5-501 | admin | Job **JOB/005430** -> **Create Material Request** -> Outdoor PCB 2, Expansion Valve 3, Gas R410A 1, Copper Pipe 1 -> Save. | Links Case G, job, visit; Destination **WH/Van 1**. PCB / Valve **Covered**, Gas **Not Covered**, Pipe **Pending**; banner "1 line(s) pending". Job **Material Status** = Waiting Approval. | | |
| TC-P5-502 | admin | **Confirm / Submit**. | Refused: coverage of Copper Pipe pending. | | |
| TC-P5-503 | admin | **Request Coverage Decision**. | To-Do for approver_w. | | |
| TC-P5-504 | approver_w | **Decide Coverage** -> Copper Pipe -> *Covered (Goodwill)*, reason "Goodwill for key customer". | Pipe Covered + Goodwill; Coverage **Mixed**. | | |
| TC-P5-505 | admin | **Confirm / Submit**. | Routing Amount **46,010**; Approvals round 1: Manager (svc_manager), Finance (finance_off), **GM** (gm_user – goodwill) pending; status Manager Approval. | | |
| TC-P5-506 | svc_manager; gm_user; finance_off | Approve (Manager, then GM, then Finance). | **Approved**, Approved Amount 46,010; admin notified. Line **Approved Qty** = requested qty. | | |
| TC-P5-507 | admin | **Create Parts Quotation**. | Quotation with only Gas x1 (4,000), Parts Release Trigger **On Payment**; Gas **Waiting Customer**. | | |
| TC-P5-508 | admin | Confirm the quotation. | Gas **Waiting Payment**; validating the quotation delivery refused. | | |
| TC-P5-509 | store_user | Open the request -> line columns. | **Free at Source / Stock Availability**: PCB (≥ 2) **Available**; Valve 2 **Partially Available**; Pipe 5 **Available**; Gas (customer quotation) no availability. Issue Status **To Issue**. | | |
| TC-P5-510 | store_user | **Create Picking and PO**. | One internal picking WH/Stock -> WH/Van 1 with **PCB 2, Valve 2, Pipe 1** (no Gas); one RFQ to **Cool Parts Ltd** for **Valve 1** at 1,800; status **Picking / PO Created**; chatter "Materials processed by Store User: issue picking … RFQ …". Picking / RFQ show *Warranty Material Request*, *MRF Warranty Case*, *MRF Service Job*. Job Material Status **Shortage** with the *Awaiting Parts* suggestion banner (job status not changed automatically). | | |
| TC-P5-511 | store_user | Validate the internal picking with the full quantities. | PCB / Pipe **Issued**; Valve Issued 2, **Outstanding 1** (on the open RFQ, Purchased 1); request **Partially Issued**, Issue Progress "2 / 4 lines issued" (Gas is issued later by the quotation delivery). | | |
| TC-P5-512 | store_user | **Received**; then **Issue / Purchase Remaining**. | Received refused: not completely issued. Issue / Purchase Remaining refused: "Nothing to issue or purchase … in open pickings or purchase orders" (no duplicate RFQ). | | |
| TC-P5-513 | store_user | RFQ -> Confirm Order -> validate its receipt. | Receipt linked to request / case / job; Valve **Purchased 1 / Received 1**. | | |
| TC-P5-514 | store_user | Request -> **Issue / Purchase Remaining**. | New internal picking with **Valve 1** only; no new RFQ. Validate it -> Valve **Issued** (3). | | |
| TC-P5-515 | admin | Quotation -> Create Invoice -> post -> register **half**. | Gas still Waiting Payment; delivery still refused. | | |
| TC-P5-516 | admin | Register the rest -> validate the quotation delivery (Gas 1). | Gas **Released** -> **Issued**; request status **Issued**; job Material Status **Issued**. | | |
| TC-P5-517 | store_user | **Received**. | Request **Received**; Approvals tab and coverage columns unchanged. | | |
| TC-P5-518 | admin | Inventory -> Reporting -> Moves Analysis, product Gas R410A. | Only the quotation delivery moved the Gas (no internal picking / RFQ for it). | | |

### Side scenarios – case H **WCAS/017740** (admin creates each request with *Create Material Request*)

| # | User | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-P5-519 | admin, store_user | PCB x1 + Gas x1 -> Submit (approved, < 25,000) -> store_user Create Picking and PO **before** the quotation / decline. | Refused: quote or decline the Not Covered lines first. | | |
| TC-P5-520 | admin, store_user | PCB x3 (55,500) -> Submit -> svc_manager and finance_off approve -> Create Picking and PO -> validate with **2** -> **Create Backorder**. | Backorder linked to the request; Issued 2, In Picking 1; **Partially Issued**; validate the backorder -> **Issued**. | | |
| TC-P5-521 | admin, store_user | PCB x1 -> Submit -> Create Picking and PO -> set quantity **2** on the picking -> Validate. | Refused: exceeds the approved quantity. | | |
| TC-P5-522 | admin, approver_w, store_user | Copper Pipe x10 (more than the 4 free after TC-P5-510; no vendor) -> approver_w decides Covered -> Submit -> store_user Create Picking and PO. Then store_user sets **Vendors** = Cool Parts Ltd on the line -> Create Picking and PO. | First: refused "No stock and no vendor for Copper Pipe …". Then: picking for the free quantity (4) + RFQ for the rest (6). | | |
| TC-P5-523 | helpdesk2 | Create Picking and PO on an approved request. | Refused (only Requisition / Inventory users issue materials). | | |
| TC-P5-524 | admin, store_user | PCB x1 -> Submit -> Create Picking and PO -> **cancel** that picking -> request -> **Issue / Purchase Remaining**. | After the cancel: In Picking 0, Outstanding 1; a new picking with PCB 1 is created. | | |
| TC-P5-525 | admin | Standalone request (Requisitions -> New): Confirm -> Department Approve -> Approve -> Create Picking and PO -> Received. | Vendor workflow unchanged (full quantities by line action, no fulfilment columns / approval tab). | | |
| TC-P5-526 | admin | Spot check 5.1 – 5.4, Parts 1–4, AMC screens. | Unchanged. | | |


---

## Phase 5.6 – Actual consumption, unused returns and reconciliation

Data (`p56_manual_data.py`): case I **WCAS/019824** with job **JOB/006038** (Technician T, visit
*JOB/006038 - WCAS/019824 - MRF Split AC*), case J **WCAS/019825** with job **JOB/006039**; product **Fan Sensor** (serial, 700, Covered,
serials FS-001 – FS-003 in WH/Stock), **Compressor Relay** (1,200, Covered, **1** in stock, vendor
Cool Parts Ltd). *Chargeable Parts Release* = **On Quotation Confirmation**. `helpdesk2` = Service
Coordinator (Helpdesk + Requisition rights). Technician T's location: **WH/Van 1**.
Visit completion follows Part 4: start / stop the timer, fill in the worksheet checklist and capture the customer sign-off (both **required** in this company).

| # | User | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-P5-601 | admin | Settings -> Warranty -> Material Requests. | Setting **Warranty Consumption Location** (empty until the first consumption, then *Virtual Locations/Warranty Consumption*). | | |
| TC-P5-602 | admin, svc_manager, finance_off | Job **JOB/006038** -> Create Material Request: Outdoor PCB 2, Fan Sensor 2, Gas R410A 2 -> Submit -> approvals as routed -> **Create Parts Quotation** -> confirm the quotation. | Request Approved; Gas Released (On Quotation Confirmation). | | |
| TC-P5-603 | store_user | Request -> Create Picking and PO -> validate the issue transfer (PCB 2, Fan Sensor FS-001 + FS-002) -> validate the quotation delivery (Gas 2). | PCB / Sensor **Issued** to WH/Van 1; Gas delivered 2. | | |
| TC-P5-604 | admin | Job -> tab **Materials**. | All lines with Requested / Approved / Issued-Delivered / Used / Returned / To Reconcile / Reconciliation **To Reconcile**; yellow box lists the open items ("issued but not recorded as used or returned", "delivered but not recorded as installed …"). | | |
| TC-P5-605 | tech_t | Visit -> **Confirm Material Usage**: PCB 1, Fan Sensor 1 (serial **FS-001**), Gas 1 -> Apply. | Entries Used (PCB, Sensor) and **Installed** (Gas); Inventory -> Moves Analysis: PCB 1 and FS-001 moved **Van 1 -> Warranty Consumption** (done); **no second movement for Gas**; visit tab *Material Usage* shows the entries. | | |
| TC-P5-606 | tech_t, tech_x | Confirm Material Usage again: PCB 5 / Fan Sensor with FS-003 (not issued) / Sensor qty 1 without serial. As **tech_x** open the job's Confirm Material Usage. | "at most 1 … can be used", "was not issued …", "select the serial numbers"; tech_x refused. | | |
| TC-P5-607 | tech_t | Complete Visit. | Refused, listing the request: PCB 1 / Sensor 1 issued but not recorded, Gas 1 delivered but not recorded. | | |
| TC-P5-608 | tech_t, store_user | **Return Unused**: PCB 1, Fan Sensor FS-002 (default rows) -> Apply. tech_t: open the return transfer -> Validate. store_user: Validate. | Transfer Van 1 -> WH/Stock (*Warranty Unused Return*, request / case / job shown); lines **Return Pending**, request status **Returned**; tech_t refused ("validated by Inventory users"); after the store: Returned 1 / Reconciled. | | |
| TC-P5-609 | tech_t, admin, store_user | Gas: **Customer Keeps** as tech_t (refused). As admin: Customer Return without reason (refused), then reason "Not needed, refund" -> store validates the return. | Return of the quotation delivery (Customers -> WH/Stock); after validation the quotation shows Delivered 1; Sales can create the credit note (*Create Invoice* on the quotation). Gas Reconciled. (Alternative: *Customer Keeps* with reason, no stock movement.) | | |
| TC-P5-610 | tech_t | Complete Visit (after the Part 4 steps). | Allowed; request status **Closed**; job Materials all **Reconciled**; chatter of request / case / job lists every entry. | | |
| TC-P5-611 | admin, store_user | Job **JOB/006039**: Create Material Request Fan Sensor 1 -> approve -> issue (FS-003) -> tech_t Confirm Material Usage FS-003. As tech_t try **Reverse** on the entry (Material Usage tab); as admin Reverse without / with reason. | tech_t: no Reverse button / refused; reason required; entry **Reversed** (kept, with reason); FS-003 back in Van 1; line To Reconcile 1. | | |
| TC-P5-612 | admin, tech_t | Job JOB/006039: tech_t -> Visit Not Completed -> Awaiting Parts, Reschedule. | Allowed although the request is not reconciled (Incomplete / Reschedule never blocked); job Incomplete. | | |
| TC-P5-613 | admin, store_user, tech_t | Job JOB/006039 (plan the next visit first if needed): Create Material Request **Compressor Relay 3** -> approve -> store Create Picking and PO (picking 1 + RFQ 2). **Cancel Remaining** as store_user. Cancel the RFQ (Purchase), then Cancel Remaining as tech_t, then as store_user without / with reason "Customer replaced the unit", quantity 2. | First: nothing cancellable (on RFQ); tech_t refused; reason required; Cancelled 2, Outstanding 0, approval history unchanged; chatter note. Validate the picking (1) -> Issued. | | |
| TC-P5-614 | admin, tech_t, helpdesk2 | Job JOB/006039: Create Material Request (any part) and keep it **New**. Check the job's open items; Cancel as tech_t; Cancel as helpdesk2 without / with reason. | Open items "not submitted (New): submit it or cancel it with a reason"; tech_t refused; Cancel opens a reason dialog; reason required; Cancelled with the reason in the chatter; no longer blocking. | | |
| TC-P5-615 | tech_t / admin | Warranty visit: look for the **Products** button. Open an ordinary Field Service task (not from a warranty job). | Warranty visit: no Products button; ordinary task: Products as before. | | |
| TC-P5-616 | admin | Inventory -> Reporting -> Valuation (or Stock Moves -> valuation): the consumption moves of TC-P5-605 / 611. Accounting -> Journal Entries. | Consumption: negative valuation at the standard price; reversal: positive; **no journal entries** (manual valuation unchanged). | | |
| TC-P5-617 | admin | Standalone request (Requisitions -> New): Confirm -> … -> Received; Cancel a standalone New request. | Vendor workflow unchanged; no material usage buttons; standalone Cancel without reason dialog. | | |

---

## Phase 5.7 - Material cost (TC-P5-701 - 712)

Database **`wm18_4_57_check`** (disposable copy of `warranty_management_18_4`, upgraded to
18.0.1.7.0; start it on a free port, e.g. `--http-port=8399 -d wm18_4_57_check`). Data: WCAS/000003
with MRF/000004 (Bolt, Goodwill, approved, issued) and MRF/000005 (Fan Sensor 2 + Compressor Relay 3
covered, Gas R410A 2 customer-paid; used 1 + 1, unused returns, installed / kept gas);
MRF/000002 / 000003 pre-matrix. All five users are Helpdesk users there, so all of them see costs;
for TC-P5-710 create one Field Service-only user and one Accounting (Billing) user.

| ID | User | Steps | Expected | Result | Notes |
|---|---|---|---|---|---|
| TC-P5-701 | admin | MRF/000005 -> lines: show the optional columns Approved Cost, Actual Cost (Verified), Cost Status; tab **Material Cost**. | Fan Sensor approved 1,400 / actual 700, Compressor Relay 3,600 / 1,200 (Verified); Gas: bucket Customer Paid, actual 4,000; summary: Warranty Material Cost 1,900; unused returns not counted. | | |
| TC-P5-702 | admin | MRF/000004 and MRF/000003 / 000002 -> Material Cost tab; Chatter of MRF/000004 / 000005. | MRF/000004 Approved Cost 0.50 Recorded (upgrade note "approved cost per line recorded"); MRF/000002 / 000003 **Not Recorded (Legacy)** with the warning note; no approval record changed. | | |
| TC-P5-703 | admin | WCAS/000003 and its job -> tab **Material Cost**. | Estimated 9,000.50, Warranty Material Cost 1,900, Customer-Paid Parts Cost 4,000, Customer Billed 0; bucket table Covered / Goodwill / Customer Paid / Pending. | | |
| TC-P5-704 | admin, main_tech | MRF/000004: Confirm Material Usage Bolt 1 (main_tech) -> Material Cost tab. Reverse it with a reason (admin) -> tab again. | After use: Goodwill actual 0.50, Verified. After reversal: actual 0, **Reversed** 0.50; never negative. | | |
| TC-P5-705 | admin | Inventory: Bolt receipt at a different cost / change the Bolt cost; record use again on MRF/000004. | Actual = value of the new consumption layer; the approved snapshot 0.50 is unchanged. | | |
| TC-P5-706 | admin | Gas line of MRF/000005: quotation -> Create Invoice -> Post. Then Customer Return 1 (if still kept / installed qty allows) and a credit note. | Customer Invoiced = invoice untaxed amount; after the credit note Customer Credited / Billed (Net) reduced; Warranty Material Cost unchanged (customer-paid cost separate). | | |
| TC-P5-707 | admin | New request on the job (Bolt 3) -> approve -> issue 1 -> **Cancel Remaining** 2 with reason. | Approved Cost unchanged; Cancelled Cost 2 x approved unit cost; Approved (Net) reduced. | | |
| TC-P5-708 | admin | **Warranty -> Reports -> Warranty Material Cost** (pivot; also Accounting -> Reporting -> Warranty Material Cost): group by Warranty Case / Cost Bucket; filters Unverified, Approved Cost Not Recorded, With Reversals, With Cancellations; list view totals. | Figures equal the form tabs; Warranty Material Cost column only for Covered + Goodwill. | | |
| TC-P5-709 | admin | Accounting -> Journal Entries before / after TC-P5-704 - 707 (except the invoice / credit note of 706); Inventory -> Configuration -> Product Categories. | No journal entry from usage, reversal, return or the cost report; valuation still Manual. | | |
| TC-P5-710 | FSM-only user (technician of the job), Billing user | FSM user: open the job / visit / request. Billing user: Accounting -> Reporting -> Warranty Material Cost. | FSM user: no Material Cost tab, no cost columns, no report menu. Billing user: report readable (no write), no access needed to cases. | | |
| TC-P5-711 | admin | Try to edit Approved Cost on a New request (Studio / import / developer mode). | Refused: "The approved cost is recorded by the approval workflow." | | |
| TC-P5-712 | admin | Standalone request (Requisitions). | No Material Cost tab; not in the report. | | |

## Phase 5.8 - Vendor claims (TC-P5-801 - 815)

Database `warranty_management_18_4` after the approved upgrade to 18.0.1.8.0 (or the disposable
`wm18_4_57_restore`). Records: **MRF/000005** (JOB/000003 / WCAS/000003): Fan Sensor 1 used
(serial FS-001, 700, no vendor), Compressor Relay 1 used (1,200, purchased on P00013 from Cool Parts
Ltd), Gas R410A customer-paid. Users: admin (coordinator), approval (Warranty approver), demo
(Finance approver), main_tech (technician). Claims are off until enabled (TC-801).

| ID | User | Steps | Expected | Result | Notes |
|---|---|---|---|---|---|
| TC-P5-801 | admin | Settings -> Warranty -> **Vendor Claims**: enable; Warranty Approvers = approval; Finance Approvers = demo; Finance Threshold 1,500; Evidence Required on; Recovery Account = e.g. 450000 Other Income (or a new Warranty Recovery account). Products Fan Sensor and Compressor Relay -> Purchase tab: **Vendor Claimable**; Fan Sensor: Warranty Claim Partner = a manufacturer partner, Vendor Warranty 12 months. | Saved; nothing else changes. | | |
| TC-P5-802 | admin | MRF/000005 -> **Create Vendor Claim**. | Wizard lists Fan Sensor and Compressor Relay only (Gas = customer-paid, not offered); Relay proposal Cool Parts Ltd (Supplying Vendor), Sensor = the manufacturer; note "different responsible partners". | | |
| TC-P5-803 | admin | Keep only Compressor Relay, partner Cool Parts Ltd, failure description -> Create Claim. Then Create Vendor Claim again. | Claim **VCL/00001** Draft, Claimed 1,200; second wizard: the Relay is no longer offered. | | |
| TC-P5-804 | admin | On VCL/00001 set the quantity to 2, then the claimed amount to 1,500. | Refused: only 1 consumed; not above the verified cost 1,200. | | |
| TC-P5-805 | admin | Create a claim for the Fan Sensor (serial FS-001) with partner Cool Parts Ltd (not the proposal): first without, then with an override reason. | Override reason required; claim saved with Partner Basis *Manual Override*, reason tracked. | | |
| TC-P5-806 | admin, approval | VCL/00001 **Submit for Approval**; try Approve as admin; Approve as approval. | Admin cannot approve (submitter); 1,200 < 1,500: approval alone -> Approved; To-Do for approval. A claim from 1,500 or a goodwill claim also needs demo (Finance). | | |
| TC-P5-807 | admin | **Mark Sent to Vendor** without attachment; then attach a photo / PDF (chatter) and send. | Refused without evidence; then Sent. | | |
| TC-P5-808 | admin, demo | **Record Vendor Response**: accept 1,000 of 1,200 ("handling deducted"). Then try **Correct Vendor Response** as admin, then as demo with a reason. | Partially Accepted, Accepted 1,000, Not Accepted 200; admin cannot correct; demo can (reason in chatter). | | |
| TC-P5-809 | admin | **Create Draft Credit Note** with the Recovery Account emptied in Settings, then set again. | Without account: refused (no fallback). Draft vendor credit note for Cool Parts Ltd, 1,000 on the Recovery Account, ref VCL/00001; claim Recovered 0, Outstanding 1,000. | | |
| TC-P5-810 | admin | Post the credit note (bill date). | Claim Recovered 1,000, Outstanding 0, Settled 0; Recovery Status Recovered; WCAS/000003 Material Cost tab: Vendor Recovered 1,000, Net Warranty Material Cost 900. | | |
| TC-P5-811 | admin | Register Payment on the credit note (refund received) or reconcile it with a vendor bill. | Settled 1,000. | | |
| TC-P5-812 | admin | **Close** the claim. | Closed, written off 0. | | |
| TC-P5-813 | admin | Sensor claim: approve, send, response **Reject All** -> Close. Create Vendor Claim again for the sensor. | Rejected by Vendor; the sensor is claimable again; the new claim can reference the old one (Re-claim of). | | |
| TC-P5-814 | admin | (Only on data you may change) On a sent claim, reverse the consumption of its part (MRF -> Material Usage -> Reverse). | **Over-claimed** banner and To-Do; credit note, allocation and close blocked until the use is recorded again. | | |
| TC-P5-815 | Field Service-only user, Billing-only user | Technician opens the job / request; Billing user opens Invoicing -> Vendors -> Warranty Vendor Claims. | Technician: no Vendor Claims menu or figures; Billing user: claims readable, credit note buttons. Standalone requisitions: no claim button. | | |

## Phase 5.9 - Closure, audit and reports (UAT-901 - 915)

Database `warranty_management_18_4` after the approved upgrade to 18.0.1.9.0 (or the disposable
copy `wm18_4_581_check`). Records: WCAS/000003, JOB/000003, MRF/000004 (Bolt issued, not recorded),
MRF/000005 (Reconciled, S00041 not invoiced), VCL/00001 (answered 1,200, draft credit note).

| ID | User | Steps | Expected | Result | Notes |
|---|---|---|---|---|---|
| UAT-901 | admin | Open MRF/000005 -> tab **Closure**; list of Material Requests (filters Reconciled / Closed). | Status **Reconciled** (was shown Closed before 5.9), Closed By / On empty, Customer Invoicing **Pending Invoicing**, no blocker. Chatter: one tracking entry Closed -> Reconciled by OdooBot (upgrade). | | |
| UAT-902 | admin | MRF/000004 -> **Close Material Request**. | Wizard row blocked: "Bolt: 1 Units issued but not recorded as used or returned"; Close button hidden. | | |
| UAT-903 | admin | Settings -> Warranty -> **Require Customer Invoice to Close** on; MRF/000005 Close. Then switch it off again. | With the option: blocked "not fully invoiced"; without: closable. No invoice is created. | | |
| UAT-904 | admin | MRF/000005 -> **Close Material Request** -> Close Selected. | Status Closed, banner Closed by admin on ..., notes on WCAS/000003 / JOB/000003; VCL/00001 (open claim, draft credit note) did not block. | | |
| UAT-905 | admin | On the closed MRF/000005 try Confirm Material Usage / Return Unused / Cancel Remaining / Create Picking / edit a line. | All refused ("closed ... reopen"). | | |
| UAT-906 | admin (Billing) | VCL/00001 after closure: Post the draft credit note (optional), Register Payment (optional). | Claim Recovered / Settled update; MRF/000005 stays Closed. Draft = not recovered. | | |
| UAT-907 | admin, approval | **Reopen** MRF/000005: as admin (the closer) without administrator exception; as `approval` (Requisition Manager) without / with reason; or admin with **Administrator Exception** + reason. | Closer refused; reason required; reopened (Reconciled), Last Reopened By / On / Reason tracked, notes; close again afterwards. | | |
| UAT-908 | admin | WCAS/000003 -> **Close Material Requests**. | MRF/000004 blocked (Bolt), MRF/000005 eligible/selected (if reopened); closes only the eligible one. | | |
| UAT-909 | admin | (Optional, only if a case-close path is used) set WCAS/000003 to Closed. | Refused while MRF/000004 is open; lists open obligations / ready requests; never because of VCL/00001. | | |
| UAT-910 | admin | Warranty -> Reports -> **Material Approval and Cost**, filter WCAS/000003; pivot by MRF Stage. | MRF/000004: estimated 0.50; MRF/000005: estimated 9,000, actual 5,900 (warranty 1,900 + customer 4,000), approvers Finance / GM, claimed / accepted 1,200, recovered 0 (1,200 after posting); totals = case Material Cost tab. | | |
| UAT-911 | admin | Reports -> **Vendor Claim Recovery**: VCL/00001. | One line (Compressor Relay): claimed 1,200, accepted 1,200, not accepted 0, recovered 0 (draft) / 1,200 after posting, settled 0 / 1,200 after payment, outstanding 1,200 / 0. | | |
| UAT-912 | admin | Reports -> **Warranty Material Cost**: MRF/000005 lines; columns Vendor Claimed / Recovered / Net. | Relay: warranty 1,200, claimed 1,200, net 1,200 (0 after posting); Fan Sensor 700; 5.7 values unchanged. | | |
| UAT-913 | admin | Reports -> **Material Audit Trail**, filter MRF/000005; then VCL/00001. | Chronological approvals, issue / delivery moves with value, usage records, field changes with before / after (status, closed by, reopen reason), notes; claim: tracking, allocation, credit note changes; **Open Document** opens the source. | | |
| UAT-914 | admin | Invoicing -> Reporting: the three Warranty shortcuts. | Same reports and figures as under Warranty -> Reports. | | |
| UAT-915 | Field Service-only user / Billing user | Open Warranty -> Reports; open MRF/000005 Closure tab. | Technician: no Reports menu, no invoicing status; Billing user: reports readable, nothing editable. | | |

## Known open items (not failures of these tests)

* **B1** vendor compatibility blocker (`decimal_precision`); shim only in the disposable environment.
* 5.3 manual test blocker: scheduling issue **JOB/000002 / WSE/00002** (scheduling validations
  unchanged).
* Part 3 `test_13_serial_rules`: serial-name AccessError for Helpdesk users without Inventory rights
  (Part 3 change awaiting approval).
* Serial-tracked issue (requested serial enforced at validation) is covered by the automated tests;
  the manual data has no serial-tracked spare part.
* Decisions awaiting confirmation: 5.4 D8, D9, C-1 – C-5; 5.5 F-1 – F-7
  (`doc/part5_design_decisions.md`).
