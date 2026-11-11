# Warranty Management – Part 2 Manual Testing Guide

**Free Service Entitlements – Generate Free Service Schedule and Free Service Due Monitoring**

| Item | Value |
|---|---|
| Module | `warranty_management` (version 18.0.1.3.0) |
| Odoo version | Odoo 18.0 Enterprise |
| Scope | Part 2 of the Development Mapping: Generate Free Service Schedule, Service Sequence, Due Date / Usage Due calculation, and Free Service Due Monitoring (due indicator, due alerts, expiry reminders, grace period, Missed / Expired) |
| Sources | Development Mapping p.15 (Part 2 workflow) and p.16–17 (`warranty.service.entitlement`), SRS §2.5, §9.4, §9.13, §10.1, §10.3, §12 (scenarios 6, 23), §13, §14, approved decisions Q1–Q18, D1–D8, B1–B4 and the monitoring decisions in `doc/part2_design_decisions.md` |
| Test case IDs | TC-P2-001 to TC-P2-054 |

---

## 1. Scope

### 1.1 In scope

| # | Workflow step (Mapping p.15) | Covered by |
|---|---|---|
| 1 | Warranty Card Confirmed / Active | All test cases |
| 2 | Free Services Included? (Yes / No) | TC-P2-004, TC-P2-005 |
| 3 | Read Warranty Policy / Values | TC-P2-006 – TC-P2-021 |
| 4 | Auto Create Services Enabled? (Yes / No) | TC-P2-006 – TC-P2-008, TC-P2-022 |
| 5 | Create Draft Service Entitlements / Create Service Entitlements Manually | TC-P2-006, TC-P2-022 – TC-P2-025 |
| 6 | Generate Free Service Schedule (Schedule Method) | TC-P2-009 – TC-P2-018 |
| 7 | Assign Service Sequence (Service 1, 2, 3) | TC-P2-006, TC-P2-022 |
| 8 | Set Planned / Due Date, Usage Due | TC-P2-006, TC-P2-009 – TC-P2-021 |
| 9 | Warranty Basis? → Monitor Service Due Date (period) | TC-P2-039 – TC-P2-050 |
| 10 | Service Due? → Due indicator + Generate Due Alert / Activity | TC-P2-039, TC-P2-045 – TC-P2-047, TC-P2-053, TC-P2-054 |
| 11 | Service Expired? → Extra Allowed Period / Expiry Rule → Keep Available / Mark Expired | TC-P2-040 – TC-P2-044 |

### 1.2 Out of scope (do NOT test – not developed in this phase)

Usage-based monitoring ("Monitor Usage Limit" – no approved usage reading source), carry-forward behaviour, overdue reminders after the due date, entitlement cancellation action, Helpdesk, Service Job, Field Service, entitlement consumption / completion, replacement workflows, warranty card expiry at the warranty end date, customer notifications, AMC schedule generation, Calendar Month calculation (pending business decision).

If any of these appear to work or are missing, do **not** log them as Part 2 defects.

---

## 2. Prerequisites

| # | Prerequisite | How to check |
|---|---|---|
| P1 | Part 1 testing completed and the module upgraded to 18.0.1.3.0 | **Apps** → search *Warranty Management* → **Upgrade** (or Module Info shows version 18.0.1.3.0) |
| P2 | Logged in as an administrator (Settings and policies need *Administration / Settings*) | User menu → Preferences |
| P3 | wkhtmltopdf configured (`bin_path = D:\ODOO\odoo18\thirdparty` in `odoo.conf`) – otherwise **Confirm Warranty** fails with "Unable to find Wkhtmltopdf" | Confirm any Part 1 card |
| P4 | Developer mode not required | – |
| P5 | Use a database created with **Odoo 18** (not an Odoo 19 database) | – |
| P6 | Pricelists enabled: **Sales → Configuration → Settings → Pricing → Pricelists** ticked | Pricelist field visible on the Sales Order |

> **Important – use new products for Part 2.** Products used in Part 1 (e.g. AC-SAM-001) may still have Product + Pricelist rules from Part 1 testing. A matching pricelist rule overrides the product defaults and changes the expected results. Create the Part 2 products in section 3.4.

> **Important – one confirmation per scenario.** Entitlements are generated once, when the warranty card is confirmed. Every test case that says "Run Procedure A" needs a **new** Sales Order.

---

## 3. Test Data Setup

### 3.1 Company settings

**Menu:** Warranty → Configuration → Settings → *General Warranty Settings*

| Field | Value |
|---|---|
| Warranty Scope Mode | *(not shown any more – BA decision 2026-10-28, see TC-P2-080)* |
| Default Warranty Policy | *(empty)* |
| Default Card Grouping Mode | *(hidden – the mode is selected in the Warranty Grouping wizard)* |
| Default Warranty Basis | Period |
| Default Start Criterion | Installation/Commissioning |
| Default Warranty Duration | 0 / Months |
| Auto-create Services | *(unticked)* |
| Draft Job from Service | *(unticked)* |

Click **Save**.

### 3.2 Warranty policy

**Menu:** Warranty → Configuration → Warranty Policies → **New**

| Field | Value |
|---|---|
| Policy Name | **P2 Free Service Policy** |
| Warranty Duration | 12 / Months |
| Start Date Basis | Installation/Commissioning |
| Warranty Basis | Period |
| Free Service Count | **3** |
| Free Service Period | **12 / Months** |
| Schedule Method | **Equal Interval** |
| Auto-create Services | **ticked** |
| Payment Check Required | *(unticked)* |

Click **Save**.

### 3.3 Product category

**Menu:** Inventory → Configuration → Product Categories → **New**

| Field | Value |
|---|---|
| Category | **Air Conditioners P2** |
| Default Warranty – Default Warranty Policy | **P2 Free Service Policy** |

Leave all other *Default Warranty* fields empty. Click **Save**.

### 3.4 Products

**Menu:** Sales → Products → Products → **New** → tab **Warranty Configuration**

General Information for every product: Product Type **Goods**, Track Inventory ticked (quantity tracking), Sales Price 200, Cost 150, Product Category **Air Conditioners P2**. Add 20 units on hand (**Update Quantity** → WH/Stock → 20).

| Field (Warranty Configuration tab) | AC-P2-STD | AC-P2-MON | AC-P2-SIX | AC-P2-FALLBACK | AC-P2-USAGE | FAN-P2 |
|---|---|---|---|---|---|---|
| Product name | Samsung AC P2 Standard | Samsung AC P2 Monthly | Samsung AC P2 Six Monthly | Samsung AC P2 Fallback | Samsung AC P2 Usage | Ceiling Fan P2 |
| Warranty Applicable | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Start Criterion | Installation/Commissioning | Installation/Commissioning | Installation/Commissioning | Installation/Commissioning | Installation/Commissioning | Installation/Commissioning |
| Warranty Basis | Period | Period | Period | Period | **Usage** | Period |
| Default Period No. / Unit | 12 / Months | 12 / Months | 12 / Months | **0** / Months | 12 / Months | 12 / Months |
| Default Free Service Count | 3 | 3 | 3 | **0** | 3 | 3 |
| Free Service Period/Frequency / Unit | **4 / Months** | **1 / Months** | **6 / Months** | **0** / *(empty)* | 4 / Months | 4 / Months |

AC-P2-USAGE uses a usage-based policy selected on a pricelist (set in TC-P2-019).

> **Strict policy priority (2026-10-16, `doc/warranty_policy_resolution.md`):** these products are
> in category Air Conditioners P2, whose Default Warranty Policy is *P2 Free Service Policy*, so
> every warranty and free service value comes from that policy (their own values above are
> readonly and not used). Schedule variations are therefore set on the policy.

### 3.5 Customer and pricelist

| Record | Values |
|---|---|
| Customer (Contacts → New) | **ABC Engineering (Pvt) Ltd**, Email abc.test@example.com, Phone 0771234567 |
| Pricelist (Sales → Products → Pricelists) | **Retail Pricelist** (already created in Part 1 – reuse it) |

---

## 4. Standard Procedures

### Procedure A – Create and confirm a warranty card

1. **Sales → Orders → Quotations → New**.
2. Customer: **ABC Engineering (Pvt) Ltd** (select the customer **first**).
3. Pricelist: **Retail Pricelist** (check it is still selected after choosing the customer).
4. Order Lines → **Add a product** → the product named in the test case → Quantity **1**.
5. Click **Confirm**. No warranty card is created yet.
6. Click **Warranty Grouping** (header) → select **Card Grouping Mode = Per Sales Order** →
   **Confirm**. The Draft warranty card and its unit warranty numbers are created.
7. Click the **Delivery** smart button → **Validate**.
8. Back on the Sales Order click the **Warranty Cards** smart button → open the card.
9. Enter **Installation Date** = the date given in the test case (default **07/15/2026** = 2026-07-15).
10. Check the status bar shows **Ready to Confirm** → click **Confirm Warranty**.
11. Status bar shows **Confirmed**; Warranty Start Date / End Date are filled.

### Procedure B – Open the free services of a card

1. On the confirmed card, open tab **Free Services**.
2. Read the yellow notice box (if shown), *Free Services Allowed*, *Schedule Method*, *Free Service Period/Frequency*, *Free Service Period*, and the entitlement lines.
3. Optional: click the **Services** smart button at the top of the card to open the same lines as a list.

> Dates are displayed in the user's language format (e.g. 11/15/2026 for 2026-11-15). This guide writes dates as YYYY-MM-DD.

### Procedure C – Run the free service monitoring now

The monitoring runs once a day. To run it immediately:

1. Activate **Developer mode** (Settings → Developer Tools → *Activate the developer mode*).
2. **Settings → Technical → Automation → Scheduled Actions** → open **Warranty: Monitor Free Service Due Dates**.
3. Click **Run Manually**.

> **Test date T.** Monitoring compares due dates with *today* in the company Warranty Timezone. In section 5.13 **T** is the date you run the test. Example values are given for T = 2026-10-14; recalculate them for your test date. Service 1 of product AC-P2-STD is due **4 months after the Installation Date**.

---

## 5. Test Cases

Fill in **Actual Result** and **Status** (Pass / Fail / Blocked / N/A) for each test.

### 5.1 Configuration

#### TC-P2-001 – Warranty Scope Mode no longer shown (revised 2026-10-28)
| | |
|---|---|
| **Requirement** | BA decision 2026-10-28 (deviation from SRS §1.2 item 12): the Scope Mode no longer limits warranty functionality |
| **Steps** | 1. Warranty → Configuration → Settings. 2. Search for "Scope". |
| **Expected** | No *Warranty Scope Mode* setting. The blocks *Free Service Settings* and *Free Service Monitoring* are always shown. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-002 – Policy free-service fields and Service Offsets grid
| | |
|---|---|
| **Requirement** | SRS §10.1, D3 |
| **Steps** | 1. Open **P2 Free Service Policy**. 2. Check the *Free Services* group. 3. Change Schedule Method to **Fixed Offsets**. 4. Change it back to **Equal Interval** (do not save Fixed Offsets yet). |
| **Expected** | *Free Services* group shows Free Service Count, Free Service Period (number + unit), Schedule Method (Equal Interval, Fixed Offsets, Manual Schedule, AMC Plan), Auto-create Services, Draft Job from Service. The **Service Offsets** grid (Service No., Offset, Offset Unit) appears **only** when Schedule Method = Fixed Offsets. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-003 – Service offset validation
| | |
|---|---|
| **Requirement** | D3 / B3 – validate service numbers, prevent duplicates |
| **Steps** | 1. Duplicate the policy (Action → Duplicate), name **P2 Offset Check**. 2. Schedule Method = Fixed Offsets. 3. Add lines: (1, 3, Months), (3, 9, Months). Save. 4. Change line 3 to service no. **1** (two lines with service no. 1). Save. 5. Change it to (2, 0, Months). Save. 6. Discard / delete the test policy. |
| **Expected** | Step 3: error "Service offsets of policy P2 Offset Check must be numbered 1, 2, 3, ... without gaps." Step 4: error "Each service number can only have one offset per warranty policy." Step 5: error "The offset of service 2 must be greater than zero." |
| **Actual Result** | |
| **Status** | |

### 5.2 Free Services Included?

#### TC-P2-004 – Company formerly "Warranty Only" → free services by the policy count (revised 2026-10-28)
| | |
|---|---|
| **Requirement** | BA decision 2026-10-28: free services follow the resolved count and Auto-create Services in every company; the stored Scope Mode is no longer used |
| **Preconditions** | Company **My Company (Chicago)** (stored Scope Mode Warranty Only, not shown). A Chicago policy with Free Service Count 2, Free Service Period 12 Months, Equal Interval, Auto-create ✔, on a Chicago product category. |
| **Steps** | 1. Switch to Chicago. 2. Run Procedure A with a product of that category. 3. Procedure B. |
| **Expected** | Card confirms normally. Free Services tab shown with **2** Draft entitlements and their due dates; **Services** smart button. No error message. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-005 – Free Services Allowed = 0 → no entitlements
| | |
|---|---|
| **Requirement** | Q2 |
| **Preconditions** | On **AC-P2-STD** temporarily set Default Free Service Count = **0** |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Procedure B. 3. Set Default Free Service Count back to **3**. |
| **Expected** | Card confirmed. Free Services Allowed = 0. No lines, no notice, no error. |
| **Actual Result** | |
| **Status** | |

### 5.3 Auto Create Services Enabled?

#### TC-P2-006 – Automatic Draft entitlements and Equal Interval schedule (main scenario)
| | |
|---|---|
| **Requirement** | SRS §2.5, §9.4 steps 2–4, Q14, D1, D2/B1 |
| **Steps** | 1. Run Procedure A with **AC-P2-STD** (Installation Date 2026-07-15). 2. Procedure B. 3. Open the **Resolved Rule** and **Other Information** tabs. |
| **Expected** | Warranty Start 2026-07-15, End **2027-07-14**. Free Services tab: Free Services Allowed 3, Schedule Method **Equal Interval**, Free Service Period/Frequency 4 Months, Free Service Period 12 Months. **Three** lines: |

| Reference | Service No. | Service Type | Due Date | Due After Warranty End | Status | Merge Status |
|---|---|---|---|---|---|---|
| WSE/xxxxx | 1 | Free Preventive Service | 2026-11-15 | ☐ | Draft | Not Merged |
| WSE/xxxxx | 2 | Free Preventive Service | 2027-03-15 | ☐ | Draft | Not Merged |
| WSE/xxxxx | 3 | Free Preventive Service | **2027-07-15** (red) | **☑** | Draft | Not Merged |

| | |
|---|---|
| **Expected (continued)** | Notice: "Service 3 is due on 2027-07-15, after the warranty end date 2027-07-14: manual decision required." The due date is **not** capped or changed. Confirmation was **not** blocked. **Services** smart button shows **3**. Resolved Rule tab: Free Services Used 0, Balance 3. PDF Soft Copy attached. References use the format WSE/ + 5 digits. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-007 – Policy Auto-create unticked is not overridden by the company
| | |
|---|---|
| **Requirement** | Q3 / B3 – policy first, company fallback; explicit "No" on the policy wins |
| **Preconditions** | Policy **P2 Free Service Policy** → Auto-create Services **unticked**. (Auto-create Services is no longer in the Warranty Settings - 2026-11-08; the policy decides alone.) |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Procedure B. 3. Restore: policy Auto-create **ticked**. |
| **Expected** | **No** lines created. Notice: "Auto-create Services is disabled: create the service entitlements manually." Free Services Allowed still 3 (eligibility kept). |
| **Actual Result** | |
| **Status** | |

#### TC-P2-008 – No policy: product Auto-create decides, no default schedule method
| | |
|---|---|
| **Requirement** | Q3, Q4 – no silent default schedule method |
| **Preconditions** | Category **Air Conditioners P2** → Default Warranty Policy **empty**. Settings → Default Warranty Policy empty. Product **AC-P2-STD** → Warranty tab → Auto-create Services **ticked** (shown while no policy applies). |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Procedure B. 3. Restore: category policy = P2 Free Service Policy, product Auto-create **unticked**. |
| **Expected** | Resolved Rule tab: Warranty Policy empty. 3 Draft lines created **without due dates**. Schedule Method empty. Notice: "Schedule Method not resolved: the warranty card has no warranty policy with a Schedule Method. Enter the due dates manually." |
| **Actual Result** | |
| **Status** | |

### 5.4 Generate Free Service Schedule – Equal Interval

#### TC-P2-009 – Interval from policy period when no frequency exists
| | |
|---|---|
| **Requirement** | D1 – 3 services within 12 months = 4-month interval (SRS sample) |
| **Preconditions** | P2 Free Service Policy without Free Service Frequency |
| **Steps** | 1. Run Procedure A with **AC-P2-FALLBACK**. 2. Procedure B and Resolved Rule tab. |
| **Expected** | Resolved Rule: Policy Source **Product Category Policy**, Free Service Frequency 0 (the product's own values are not used). Free Services Allowed 3 (from the policy). Due dates **2026-11-15, 2027-03-15, 2027-07-15** (service 3 flagged). |
| **Actual Result** | |
| **Status** | |

#### TC-P2-010 – Non-divisible period (12 months ÷ 5)
| | |
|---|---|
| **Requirement** | D1b – day-based, rounded down, last service on the period end |
| **Preconditions** | Policy Free Service Count = **5** |
| **Steps** | 1. Run Procedure A with AC-P2-FALLBACK. 2. Procedure B. 3. Restore: policy Free Service Count 3. |
| **Expected** | 5 lines. Due dates (365 days ÷ 5 = 73-day steps): **2026-09-26, 2026-12-08, 2027-02-19, 2027-05-03, 2027-07-15**. Last date = start + 12 months. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-011 – Month-end dates (no drift)
| | |
|---|---|
| **Requirement** | D1 – each date calculated from the original start date |
| **Preconditions** | Policy Free Service Frequency **1 / Months** |
| **Steps** | 1. Run Procedure A with **AC-P2-MON**, Installation Date **2027-01-31**. 2. Procedure B. 3. Afterwards clear the policy Free Service Frequency. |
| **Expected** | Due dates **2027-02-28, 2027-03-31, 2027-04-30** (not 03-28 / 04-28). |
| **Actual Result** | |
| **Status** | |

#### TC-P2-012 – Leap-year start date
| | |
|---|---|
| **Requirement** | D1 – leap years |
| **Preconditions** | Policy temporarily: Free Service Count **1**, Free Service Frequency **12 / Months** |
| **Steps** | 1. Run Procedure A with AC-P2-MON, Installation Date **2028-02-29**. 2. Procedure B. 3. Restore the policy (Count 3, Frequency empty). |
| **Expected** | Warranty End 2029-02-27. One line, due date **2029-02-28**, flagged *Due After Warranty End* with the matching notice. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-013 – Frequency and policy period conflict notice
| | |
|---|---|
| **Requirement** | D1a – frequency wins; conflict shown, not silently ignored |
| **Preconditions** | Policy Free Service Frequency **6 / Months** (Free Service Period 12 Months) |
| **Steps** | 1. Run Procedure A with **AC-P2-SIX**. 2. Procedure B. 3. Afterwards clear the policy Free Service Frequency. |
| **Expected** | Due dates **2027-01-15, 2027-07-15, 2028-01-15** (frequency used). Services 2 and 3 flagged. Notice contains: "Free service frequency (every 6 months x 3 services, until 2028-01-15) differs from the policy Free Service Period (12 months, until 2027-07-15). The frequency is used for the due dates; the policy period is kept." Free Service Period on the tab still shows 12 Months. |
| **Actual Result** | |
| **Status** | |

### 5.5 Generate Free Service Schedule – other schedule methods

#### TC-P2-014 – Fixed Offsets and snapshot
| | |
|---|---|
| **Requirement** | D3 / B3 |
| **Preconditions** | Policy: Schedule Method **Fixed Offsets**; Service Offsets (1, 3, Months), (2, 6, Months), (3, 1, Years). Save. |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Procedure B. 3. Edit the policy: line 1 offset **2** Months. Save. 4. Reopen the card → Free Services. |
| **Expected** | Due dates **2026-10-15, 2027-01-15, 2027-07-15** (service 3 flagged). *Service Offsets (snapshot)* section shows 3 read-only lines. After step 3 the card still shows offset 3 Months and the due dates are unchanged. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-015 – Fixed Offsets incomplete for the card's resolved count
| | |
|---|---|
| **Requirement** | B3 – validate against the card's resolved Free Service Count |
| **Preconditions** | Policy still Fixed Offsets with 3 offset lines; policy Free Service Count **4**. |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Procedure B. 3. Afterwards set the policy Free Service Count back to 3. |
| **Expected** | Resolved Rule: Policy Source **Product Category Policy**, Free Services Allowed **4**. 4 lines, **no due dates**. Notice: "Fixed Offsets incomplete: 3 offset line(s) are configured for 4 free service(s); service numbers 1 to 4 are required. Due dates are not calculated." |
| **Actual Result** | |
| **Status** | |

#### TC-P2-016 – Calendar Month removed
| | |
|---|---|
| **Requirement** | Removed by the business owner (2026-10-19) |
| **Steps** | Open the Schedule Method on a policy, the company Warranty Settings, a product category and a product. |
| **Expected** | **Calendar Month** is not offered anywhere (Equal Interval, Fixed Offsets, Manual Schedule, AMC Plan on the policy; Equal Interval, Manual Schedule as defaults). |
| **Actual Result** | |
| **Status** | |

#### TC-P2-017 – Manual Schedule
| | |
|---|---|
| **Requirement** | Q9 |
| **Preconditions** | Policy Schedule Method **Manual Schedule** |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Procedure B. 3. On line 1 click the calendar icon (**Change Due Date**) → New Due Date 2026-10-01, Reason "Agreed with customer" → **Apply**. |
| **Expected** | 3 Draft lines without due dates; notice "Manual Schedule: enter the due dates manually." After step 3 line 1 shows 2026-10-01. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-018 – AMC Plan (handled by the AMC module)
| | |
|---|---|
| **Requirement** | Q2 / Q9 – no AMC schedule generation in the warranty module |
| **Preconditions** | Policy Schedule Method **AMC Plan** |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Procedure B. 3. Try **Add a line** on the Free Services tab. 4. Afterwards set the policy back to **Equal Interval**. |
| **Expected** | **No** lines. Notice: "AMC Plan: free service schedules are managed by the separate AMC module; no service entitlements are generated by the warranty module." The entitlement list is read-only (no *Add a line*). |
| **Actual Result** | |
| **Status** | |

### 5.6 Usage Due

#### TC-P2-019 – Usage milestones (2,000 h ÷ 4)
| | |
|---|---|
| **Requirement** | D5 |
| **Preconditions** | New policy **P2 Usage Policy**: Warranty Duration 12 Months, Start Date Basis Installation/Commissioning, Warranty Basis **Usage**, Usage Limit **2000**, Usage Unit **Operating Hours**, Free Service Count **4**, Free Service Frequency **4 Months**, Schedule Method Equal Interval, Auto-create ticked. Pricelist **Usage Pricelist** (company of the test) → tab **Warranty**: Warranty Applicable ticked, Warranty Policy **P2 Usage Policy**. Use this pricelist on the Sales Order of AC-P2-USAGE (Procedure A). |
| **Steps** | 1. Run Procedure A with AC-P2-USAGE. 2. Procedure B. |
| **Expected** | Policy Source **Pricelist Warranty Policy**. Warranty End Date **empty** (usage basis). 4 lines: Usage Due **500, 1,000, 1,500, 2,000**, Usage Unit Operating Hours. Due dates (calendar, separate) 2026-11-15, 2027-03-15, 2027-07-15, 2027-11-15. **No** *Due After Warranty End* flags. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-020 – Non-divisible usage (2,000 h ÷ 3)
| | |
|---|---|
| **Requirement** | D5 – 2-decimal precision, last milestone = limit |
| **Preconditions** | Change P2 Usage Policy Free Service Count to **3** |
| **Steps** | 1. Run Procedure A with AC-P2-USAGE. 2. Procedure B. |
| **Expected** | Usage Due **666.67, 1,333.33, 2,000.00**. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-021 – Missing usage limit
| | |
|---|---|
| **Requirement** | D5 / Decision 1 – usage-based policy without usage limit |
| **Preconditions** | Change P2 Usage Policy Usage Limit to **0** |
| **Steps** | 1. Create and confirm a Sales Order for AC-P2-USAGE with the Usage Pricelist. 2. Afterwards restore Usage Limit 2000. |
| **Expected** | Confirmation is refused: "Configuration Required: the usage-based warranty policy "P2 Usage Policy" (selected on: Pricelist Usage Pricelist) … needs a Usage Limit and a Usage Unit." No card is created. (A usage product without any policy (P5) has no usage limit: only the notice "Usage Due not calculated".) |
| **Actual Result** | |
| **Status** | |

### 5.7 Manual creation (Auto-create disabled)

#### TC-P2-022 – Manual line gets the next service number and calculated due date
| | |
|---|---|
| **Requirement** | Q16, SRS §2.5 |
| **Preconditions** | Policy Auto-create Services **unticked**, Schedule Method Equal Interval |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Free Services tab → **Add a line** → leave Service No. and Due Date empty → **Save** the card. |
| **Expected** | Before step 2: no lines, notice "Auto-create Services is disabled…". After save: line **WSE/xxxxx**, Service No. **1**, Free Preventive Service, Due Date **2026-11-15**, Draft. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-023 – Manually entered due date is kept
| | |
|---|---|
| **Requirement** | Q9 / Q16 |
| **Steps** | On the same card: **Add a line** → Service No. **3**, Due Date **2027-06-01** → Save. |
| **Expected** | Line 3 keeps **2027-06-01** (not replaced by the calculated date). |
| **Actual Result** | |
| **Status** | |

#### TC-P2-024 – Count and service number limits
| | |
|---|---|
| **Requirement** | Q16 / B4 – total ≤ Free Services Allowed, valid numbers |
| **Steps** | 1. On the same card add a line with Service No. **5** → Save. 2. Discard. Add a line with Service No. empty → Save (line 2). 3. Add another line → Save. |
| **Expected** | Step 1: error "Service numbers on warranty card WC/xxxxx must be between 1 and 3." Step 2: saved as Service No. 2. Step 3: error "Warranty card WC/xxxxx allows 3 free service(s); no further service entitlement can be created." |
| **Actual Result** | |
| **Status** | |

#### TC-P2-025 – No manual lines before confirmation
| | |
|---|---|
| **Requirement** | Q17 – only after the card is confirmed |
| **Steps** | 1. Run Procedure A with AC-P2-STD but stop at step 10 (card **Ready to Confirm**). 2. Open tab Free Services. 3. Menu Warranty → Service Entitlements → **New** → select this card → Save. |
| **Expected** | Step 2: entitlement list read-only. Step 3: error "Service entitlements can only be created for confirmed warranty cards (WC/xxxxx)." Restore policy Auto-create **ticked** after the test. |
| **Actual Result** | |
| **Status** | |

### 5.8 Duplicate prevention

#### TC-P2-026 – Duplicate service number rejected
| | |
|---|---|
| **Requirement** | Q14 / B4 |
| **Preconditions** | Policy Auto-create Services **unticked** |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Add a line Service No. 1 → Save. 3. Add another line Service No. **1** → Save. 4. Restore Auto-create **ticked**. |
| **Expected** | Step 3: error "Service numbers must be unique per warranty card." |
| **Actual Result** | |
| **Status** | |

#### TC-P2-027 – No regeneration on a confirmed card
| | |
|---|---|
| **Requirement** | Q17 – idempotent generation |
| **Steps** | Open the TC-P2-006 card. Reload the page; open/close tabs; edit Installation Date and save. |
| **Expected** | Still exactly 3 lines with the same references. **Confirm Warranty** button is not shown on a Confirmed card. No new lines appear. |
| **Actual Result** | |
| **Status** | |

### 5.9 Due date correction and audit trail

#### TC-P2-028 – Change Due Date with reason and history
| | |
|---|---|
| **Requirement** | B1 / B2 |
| **Steps** | 1. Open the TC-P2-006 card → Free Services. 2. Try to click into the Due Date of line 3. 3. Click the calendar icon on line 3 → leave Reason empty → **Apply**. 4. Enter New Due Date **2027-07-14**, Reason "Moved inside warranty validity" → **Apply**. 5. Open line 3 (click the row in the Service Entitlements list) → tab **Due Date History**. |
| **Expected** | Step 2: field is read-only. Step 3: Reason is required (cannot apply). Step 4: line 3 shows 2027-07-14, *Due After Warranty End* cleared, card notice no longer mentions Service 3. Step 5: one history row with Changed On (now), Changed By (your user), Previous Due Date 2027-07-15, New Due Date 2027-07-14, Reason. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-029 – Change Due Date only while Draft
| | |
|---|---|
| **Requirement** | B2 |
| **Steps** | Check the *Change Due Date* button / calendar icon on Draft lines. |
| **Expected** | Shown on Draft lines. Lines cannot leave Draft in Part 2 (status transitions are deferred), so the non-Draft case is **N/A in the UI** – covered by automated test `test_16_due_date_change_audit`. |
| **Actual Result** | |
| **Status** | |

### 5.10 Worksheet template

#### TC-P2-030 – Single-product card takes the product worksheet template
| | |
|---|---|
| **Requirement** | Q11 / D7 |
| **Preconditions** | A Worksheet Template exists and is selectable in the product field *Worksheet Template* (needs Field Service worksheets). If none exists mark **Blocked**. Set it on AC-P2-STD. |
| **Steps** | 1. Run Procedure A with AC-P2-STD. 2. Open a line from the **Services** smart button. |
| **Expected** | *Product Worksheet Template* = the product's template on all 3 lines. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-031 – Multi-product card does not pick one product's template
| | |
|---|---|
| **Requirement** | Q11 / D7 |
| **Steps** | 1. Procedure A with **two** lines on one Sales Order: AC-P2-STD and FAN-P2 (qty 1 each). 2. Open the lines. |
| **Expected** | One card with 2 unit warranty numbers, 3 card-level lines (not 6). *Product Worksheet Template* empty. |
| **Actual Result** | |
| **Status** | |

### 5.11 Navigation and security

#### TC-P2-032 – Service Entitlements menu, list and filters
| | |
|---|---|
| **Requirement** | Q18 |
| **Steps** | 1. Warranty → **Service Entitlements**. 2. Filters **Draft**, **Due After Warranty End**, **No Due Date**. 3. Group By **Warranty Card**, **Customer**, **Status**. 4. Open a record. |
| **Expected** | All lines from the tests are listed (Reference, Warranty Card, Customer, Service No., Service Type, Due Date, Due After Warranty End, Due Indicator, Usage Due, Usage Unit, Status). Filters and groupings work. Form shows the header *Change Due Date*, status bar, tabs *Due Date History* and *Other Information* (Grace Period End Date, Alert Date, Expiry Reminder Date, Usage Threshold, Payment Eligibility, Reschedule Count, Due Alert Sent, Expiry Reminder Sent) and the chatter. Monitoring dates are empty when the policy has no Service Due Monitoring values. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-033 – Internal user rights
| | |
|---|---|
| **Requirement** | Q18 – reuse Warranty Management security conventions |
| **Steps** | Log in as a normal internal user (no Settings rights). 1. Open a confirmed card → Free Services. 2. Open Warranty → Service Entitlements → select a line → Actions menu. 3. Open a warranty policy. |
| **Expected** | User can view lines, add manual lines (when allowed) and use Change Due Date. No **Delete** action on entitlements. Policy, its Service Offsets and its Service Due Monitoring values are read-only. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-034 – Multi-company record rule
| | |
|---|---|
| **Requirement** | Q18 |
| **Preconditions** | A second company exists and a user who has access **only** to the second company |
| **Steps** | Log in as that user → Warranty → Service Entitlements. |
| **Expected** | Entitlements of the first company are **not** visible. |
| **Actual Result** | |
| **Status** | |

### 5.12 Regression and automated tests

#### TC-P2-035 – Part 1 regression
| | |
|---|---|
| **Requirement** | Preserve Part 1 functionality |
| **Steps** | Repeat Part 1 test cases for: draft card from the Warranty Grouping wizard, unit warranty numbers WN/xxxxx-xx, pricelist rule priority, delivery / serial allocation, Confirm Warranty dates, PDF soft copy. |
| **Expected** | Same results as in Part 1 testing. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-036 – Automated test suites
| | |
|---|---|
| **Steps** | Stop the Odoo service and run in a terminal:<br>`D:\ODOO\odoo18\python\python.exe D:\ODOO\odoo18\server\odoo-bin -c D:\ODOO\odoo18\server\odoo.conf -d warranty_test -u warranty_management --test-tags=warranty_part1,warranty_part2 --stop-after-init --http-port=8099` |
| **Expected** | Log ends with "0 failed, 0 error(s) of 56 tests" (17 Part 1 + 19 Part 2 schedule + 20 Part 2 monitoring). |
| **Actual Result** | |
| **Status** | |

### 5.13 Free Service Due Monitoring

**Additional setup (once):**

| Where | Field | Value |
|---|---|---|
| Warranty → Configuration → Settings → *Free Service Monitoring* | Service Alert Responsible Users | *(empty – set in TC-P2-046)* |
| | Warranty Timezone | **Asia/Colombo** |
| Policy **P2 Free Service Policy** → group *Service Due Monitoring* | Grace Period (Days) | **30** |
| | Auto-expire | **ticked** |
| | Carry-forward Allowed | *(not shown on the policy form – always off)* |
| | Service Due Alert Days | **14** |
| | Expiry Reminder Days | **7** |
| | Usage Alert % | **90** |
| | Service Alert Responsible Users | **Mitchell Admin** (or the tester) |

Policy values are copied to the card at confirmation: always create a **new** Sales Order after changing the policy.

#### TC-P2-037 – Service Due Monitoring configuration and validation
| | |
|---|---|
| **Requirement** | Q2, Q6, SRS §12 scenarios 6 / 23 |
| **Steps** | 1. Open the policy; check group *Service Due Monitoring*. 2. Enter Grace Period **-1** → Save. 3. Enter Usage Alert % **150** → Save. 4. Add a portal user to *Service Alert Responsible Users* → Save. 5. Discard. Open Settings → *Free Service Monitoring*. |
| **Expected** | 1. Six fields shown (Carry-forward Allowed is hidden). 2–4. Validation error each time. 5. *Service Alert Responsible Users* (several users allowed) and *Warranty Timezone* settings shown. When the policy has no responsible users and alert / reminder days > 0, a blue notice explains the company fallback. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-038 – Snapshot on the warranty card
| | |
|---|---|
| **Requirement** | Q2, Configuration snapshot |
| **Steps** | 1. Run Procedure A with AC-P2-STD (Installation Date 2026-07-15). 2. Procedure B. 3. Change the policy Grace Period to 5 and save. 4. Reopen the card. |
| **Expected** | Group *Service Due Monitoring (snapshot)*: Grace 30, Auto-expire ✔, Carry-forward ☐, Alert Days 14, Reminder Days 7, Usage Alert 90, responsible users. Service 1: Grace Period End 2026-12-15, Alert Date 2026-11-01, Expiry Reminder Date 2026-12-08 (*Other Information* tab). After step 3 the card still shows 30. Reset the policy to 30. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-039 – Upcoming indicator and one due alert
| | |
|---|---|
| **Requirement** | C2, A3, SRS §2.5 / §14 |
| **Steps** | 1. Procedure A with AC-P2-STD, Installation Date = (T + 10 days) − 4 months (T = 2026-10-14 → **2026-06-24**; service 1 due 2026-10-24). 2. Procedure C. 3. Open service 1. 4. Procedure C again. |
| **Expected** | Due Indicator **Upcoming**, Status still **Draft**. One activity **Free Service 1 due on 2026-10-24** (type *Free Service Due Alert*) assigned to the responsible user, deadline = due date. After step 4 still **one** activity. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-040 – Missed within the grace period
| | |
|---|---|
| **Requirement** | C4 (T1), SRS §12 scenario 6 |
| **Steps** | 1. Procedure A, Installation Date = (T − 5 days) − 4 months (→ **2026-06-09**; due 2026-10-09). 2. Procedure C. 3. Procedure B. |
| **Expected** | Service 1 **Missed**, indicator **Overdue**. No due alert (the alert window ended on the due date). Free Services Missed 1, Balance **3**. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-041 – Expiry reminder
| | |
|---|---|
| **Requirement** | X4, A3 |
| **Steps** | 1. Procedure A, Installation Date = (T − 25 days) − 4 months (→ **2026-05-19**; due 2026-09-19, grace end 2026-10-19, reminder date 2026-10-12). 2. Procedure C twice. |
| **Expected** | Service 1 **Missed**. Exactly one activity **Free Service 1 expires after 2026-10-19** (type *Free Service Expiry Reminder*), deadline = grace end. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-042 – Expired after the grace period (late run, no obsolete reminders)
| | |
|---|---|
| **Requirement** | C4 (T2), A3, D1 |
| **Steps** | 1. Procedure A, Installation Date = (T − 40 days) − 4 months (→ **2026-05-04**; due 2026-09-04, grace end 2026-10-04). 2. Procedure C. 3. Procedure B. |
| **Expected** | Service 1 **Expired**, indicator empty, **no** due alert and **no** expiry reminder. Free Services Expired 1, Balance **2**. Services 2 and 3 unchanged (Draft). Chatter shows the status change. Closing of existing system activities on expiry is covered by automated test `test_05`. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-043 – Auto-expire off / Carry-forward on
| | |
|---|---|
| **Requirement** | Q4, Q6 (T3) |
| **Steps** | 1. Policy: untick Auto-expire. Repeat TC-P2-042 with a new Sales Order. 2. Reset the policy (Auto-expire ✔). |
| **Expected** | Service 1 **Missed** (not Expired), Expiry Reminder Date empty, no expiry reminder, Balance 3. The Carry-forward case is not testable in the UI (field hidden) – covered by automated test `test_07_auto_expire_off_and_carry_forward`. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-044 – Grace period 0
| | |
|---|---|
| **Requirement** | Q6 |
| **Steps** | 1. Policy Grace Period **0**. 2. Procedure A, Installation Date = (T − 1 day) − 4 months (→ **2026-06-13**). 3. Procedure C. 4. Reset Grace Period to 30. |
| **Expected** | Grace Period End Date = Due Date; service 1 **Expired**. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-045 – Reminders disabled with 0 days
| | |
|---|---|
| **Requirement** | Q6 |
| **Steps** | 1. Policy: Service Due Alert Days **0**, Expiry Reminder Days **0**. 2. Repeat TC-P2-039 with a new Sales Order. 3. Reset to 14 / 7. |
| **Expected** | Alert Date and Expiry Reminder Date empty, **no** activity; indicator empty until the due date. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-046 – Missing responsible user and company fallback
| | |
|---|---|
| **Requirement** | Q2, A1, A2 |
| **Steps** | 1. Policy: clear *Service Alert Responsible Users*; Settings: responsible users empty. 2. Repeat TC-P2-039 (new Sales Order). 3. Procedure B. 4. Procedure C. 5. Settings: set *Service Alert Responsible Users* = another internal user. 6. Procedure C. 7. Reset the policy users. |
| **Expected** | 3. Yellow notice "No valid Service Alert Responsible User is configured…"; card snapshot users empty. 4. No activity; server log shows a warning naming the service. 6. One due alert assigned to the company user; the card snapshot users stay empty. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-047 – Due date change moves the open alert
| | |
|---|---|
| **Requirement** | A3.4 |
| **Steps** | On the TC-P2-039 card, service 1 → **Change Due Date** → T + 12 days, reason "Customer request" → Apply. |
| **Expected** | The same activity now has the new deadline (no second activity). Grace Period End / Alert / Expiry Reminder dates follow the new due date. Due Date History records the change. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-048 – Deletion restrictions
| | |
|---|---|
| **Requirement** | D3, Q7 |
| **Steps** | As administrator: 1. Delete a Draft service of any card. 2. Try to delete the Missed service of TC-P2-040 and the Expired service of TC-P2-042. 3. Try to delete the TC-P2-042 warranty card. |
| **Expected** | 1. Deleted. 2. and 3. Blocked with "…cannot be deleted; they are kept for history." |
| **Actual Result** | |
| **Status** | |

#### TC-P2-049 – Balance and counts
| | |
|---|---|
| **Requirement** | D1, D2 |
| **Steps** | Procedure B on the TC-P2-040 and TC-P2-042 cards. |
| **Expected** | Free Services Allowed, Used (Completed), Missed, Expired, Cancelled and Balance shown. Balance = Allowed − Completed − Expired − Cancelled; Missed stays in the balance. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-050 – Not monitored: usage cards and cards confirmed before 18.0.1.2.0
| | |
|---|---|
| **Requirement** | A9 / scope, "do not modify historical records" |
| **Steps** | 1. Procedure C. 2. Open a usage-based card (TC-P2-019) and any card confirmed before the upgrade. |
| **Expected** | No status change, no indicator, no activity on those services. Usage service shows Usage Threshold = 90 % of Usage Due (usage card confirmed after the upgrade). |
| **Actual Result** | |
| **Status** | |

#### TC-P2-051 – Expiry blocked by merge status
| | |
|---|---|
| **Requirement** | A7 |
| **Steps** | Not testable in the UI (nothing sets Selected / Merged before Part 3/4). |
| **Expected** | N/A in the UI – covered by automated test `test_09_expiry_blocked_by_merge_status`. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-052 – Filters, grouping and chatter
| | |
|---|---|
| **Requirement** | Reporting (SRS §15 Free Service Due Report) |
| **Steps** | Warranty → Service Entitlements: filters **Missed**, **Expired**, **Upcoming**, **Due**, **Overdue**; Group By **Due Indicator**; open a Missed service. |
| **Expected** | Filters and grouping work; badges coloured; the chatter shows the status change by OdooBot and the activities. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-053 – Several responsible users: one activity each
| | |
|---|---|
| **Requirement** | Q2 (multi-user), A3.4, Q5 |
| **Steps** | 1. Policy: *Service Alert Responsible Users* = **Mitchell Admin** + a second internal user. 2. Repeat TC-P2-039 (new Sales Order). 3. Procedure B. 4. Procedure C twice. 5. Open service 1. 6. Log in as one of the users and mark their activity **Done**. 7. Service 1 → **Change Due Date** → T + 12 days → Apply. 8. Reset the policy users. |
| **Expected** | 3. The card snapshot shows **both** users. 4–5. **Two** *Free Service Due Alert* activities, one per user, same deadline; still two after the second run. 7. Only the open activity moves to the new deadline; no new activity is created. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-054 – Several users: validation and invalid user skipped
| | |
|---|---|
| **Requirement** | Q2 (multi-user), A2 |
| **Steps** | 1. Settings → *Free Service Monitoring* → add an internal user **and** a portal user → Save. 2. Remove the portal user, keep two internal users → Save. 3. Policy: set the same two users; create a new card as in TC-P2-039. 4. Archive one of the two users (Settings → Users). 5. Procedure C. |
| **Expected** | 1. Validation error naming the portal user. 2. Saved; both shown as tags. 5. One due alert, assigned to the active user only; the server log shows a warning naming the skipped (archived) user. The archived user stays visible on the card snapshot. Reactivate the user afterwards. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-055 – Due alert email to each responsible user
| | |
|---|---|
| **Requirement** | A4 / section 6a (D1–D5) |
| **Steps** | 1. Settings → Companies → set the company **Email**. 2. Give the two responsible users an email; set one user's *Notification* to **Handle in Odoo**. 3. Create and confirm a new card as in TC-P2-039. 4. Procedure C (Run Manually) on the alert date. 5. Settings → Technical → Email → **Emails**, filter on the service reference. 6. Run the action again. |
| **Expected** | 4. One due alert activity per user (unchanged). 5. One email per user (also for the *Handle in Odoo* user), From / Reply-To = company email, subject "Free Service 1 due on … – WC/…", body with Warranty Card, Customer, Product, Service No., Due Date and *View Free Service* link; status Outgoing → Sent (or Failed with the reason; **Retry** resends only that email). 6. No new email or activity. A user without an email gets the activity only (server log warning). |
| **Actual Result** | |
| **Status** | |


#### TC-P2-056 – Expiry reminder email
| | |
|---|---|
| **Requirement** | section 6b (E1–E4) |
| **Steps** | Setup as TC-P2-055 with a policy: Grace Period 30, Auto-expire ✔, Expiry Reminder Days 7. Confirm a new card; Procedure C on the expiry reminder date (Grace Period End − 7); run it again. |
| **Expected** | One expiry reminder activity per user (unchanged) and one email per user: subject "Free Service 1 expires after <grace end> – WC/…", body with Warranty Card, Customer, Product, Service No., Due Date, Grace Period End Date and link. The second run creates nothing. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-057 – Service expired email
| | |
|---|---|
| **Requirement** | section 6b (E1–E4) |
| **Steps** | Same card as TC-P2-056; Procedure C on a day after the Grace Period End; run it again. Repeat with Auto-expire unticked on a new card. |
| **Expected** | Status **Expired**, system activities closed (unchanged); one email per user: subject "EXPIRED: Free Service 1 – WC/…", body states the service has expired, with Service Reference, Warranty Card, Customer, Product, Due Date, Expiry Date (Grace Period End) and Expired On. The second run sends nothing. With Auto-expire off: Missed only, no expiry reminder or expired email. |
| **Actual Result** | |
| **Status** | |

### 5.14 Warranty Policy priority (strict, approved 2026-10-16)

Reference: `doc/warranty_policy_resolution.md`. Use a product **AC-POL** (Warranty Applicable,
own Default Period 3 Months) in a category **Policy Test** and four policies with different
durations: **Pricelist Policy** 36, **Product Policy** 24, **Category Policy** 18, **Company
Policy** 6 Months.

#### TC-P2-058 – Four levels at the same time
| | |
|---|---|
| **Requirement** | Strict priority P1 > P2 > P3 > P4 > P5 |
| **Preconditions** | Retail Pricelist → tab Warranty: Warranty Applicable, Warranty Policy **Pricelist Policy**. AC-POL Warranty Policy **Product Policy**. Category Policy Test Default Warranty Policy **Category Policy**. Settings → Default Warranty Policy **Company Policy**. |
| **Steps** | Confirm a Retail Pricelist SO for AC-POL and group it; open the card → Resolved Rule. Then untick Warranty Applicable on the pricelist and remove the policy of the product, the category and the company one after the other, with a new SO each time. |
| **Expected** | Policy / Source / Duration: Pricelist Policy – **Pricelist Warranty Policy** – 36; Product Policy – **Product Warranty Policy** – 24; Category Policy – **Product Category Policy** – 18; Company Policy – **Company Default Policy** – 6; finally no policy – **Product Default Rule** – 3 (P5). Earlier cards keep their values. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-059 – No mixing of lower levels
| | |
|---|---|
| **Requirement** | Q2 A – only the Company Warranty Settings fill empty policy values |
| **Preconditions** | Settings: Default Start Criterion Installation, Default Free Service Period 6 Months, Default Schedule Method Manual. Pricelist Policy: Free Service Count 2, no Start Date Basis / Period / Schedule Method / Frequency, Auto-create unticked. Product / Category / Company policies with other values (count 4, Equal Interval, Auto-create ticked). |
| **Steps** | Confirm an SO for AC-POL, group, set the Installation Date and confirm the card. |
| **Expected** | Source Pricelist Warranty Policy; Free Services Allowed 2; Free Service Frequency 0; Start Criterion Installation; Schedule Method **Manual** and Free Service Period **6 Months** (Company Warranty Settings); no Draft services (the policy's Auto-create is unticked); grace period etc. from Pricelist Policy only. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-060 – Invalid selected policy
| | |
|---|---|
| **Requirement** | Q3 B |
| **Steps** | Select a policy with Warranty Duration 0 (or no unit) on the Retail Pricelist (Warranty Applicable), then on the product, the category and the company (one at a time) and confirm an SO for AC-POL. Then select an **archived** policy on the product with a valid Category Policy. |
| **Expected** | Each time: "Configuration Required: the warranty policy "…" (selected on: <level>) for product "AC-POL" on S… has no valid Warranty Duration and Duration Unit." The archived policy is ignored: the card gets Category Policy. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-061 – Company-specific policies
| | |
|---|---|
| **Requirement** | Decision 2 |
| **Steps** | 1. On a shared product select Product Policy in company A, switch to company B and select a company B policy. 2. In company A try to select a company B policy on the product and on a company A pricelist; on a shared pricelist (no company) try a company A policy. 3. Set a category's Default Warranty Policy to a company B policy and confirm a company A SO. 4. Use a policy without company on any level. |
| **Expected** | 1. Each company keeps its own product policy. 2. Refused (validation error). 3. The company B policy is not applied in company A (next level / own values); the product shows no Category Warranty Policy in company A. 4. The shared policy applies in every company. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-062 – Policy and product forms
| | |
|---|---|
| **Requirement** | Applicability removed from the policy; selection at the source |
| **Steps** | Open a policy, a product (Warranty Configuration tab) as administrator and as a non-administrator user. |
| **Expected** | Policy form / list: no Applies To, Applicable Products / Categories / Pricelists, Sales Order Type; new Free Service Frequency / Unit; Usage Limit and Usage Unit only (and required) for Warranty Basis Usage. Product: Warranty Policy editable by administrators only; *Category Warranty Policy* shown when the product has none; the applied (product / category) policy's values shown readonly instead of the own values; no Product + Pricelist Warranty Mapping table any more. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-064 – Pricelist Warranty tab
| | |
|---|---|
| **Requirement** | D2 / D3 / display |
| **Steps** | Sales → Products → Pricelists → open a company pricelist → tab **Warranty**. 1. Tick Warranty Applicable without a policy and save. 2. Select a policy, save; change a value on the policy and reopen the pricelist. 3. Untick Warranty Applicable. 4. Confirm an SO with this pricelist for a product that is **not** Warranty Applicable. |
| **Expected** | 1. Saving is refused (Warranty Policy required). 2. The policy's duration, start criterion, basis, (usage), free services, frequency, period, schedule method, auto-create, due alert, responsible users, auto-expire, grace period and expiry reminder are shown readonly and follow the policy (nothing stored on the pricelist). 3. The policy stays selected but is not used. 4. No warranty card (the pricelist never makes products Warranty Applicable). |
| **Actual Result** | |
| **Status** | |

#### TC-P2-065 – Retired Product + Pricelist Warranty Mapping
| | |
|---|---|
| **Requirement** | D1 / D5 |
| **Steps** | After the module update: open Samsung AC (Premium) (San Francisco); check the server log; confirm a VIP SO for it before any VIP / product / category policy is configured. |
| **Expected** | No mapping table on the product; the log contains "Retired Product + Pricelist Warranty Mapping (not used any more, kept): product Samsung AC (Premium), pricelist VIP …" once; the SO confirmation reports *Configuration Required* (no rule) until a policy is configured (D5). Existing cards unchanged. |
| **Actual Result** | |
| **Status** | |

### 5.15 Free service scheduling (section 6c)

Use a new card of AC-P2-STD started 2026-07-15 (service 1 due 2026-11-15, grace period 30 days
→ end 2026-12-15) and Procedure C to run the monitoring on the given dates.

#### TC-P2-066 – Schedule
| | |
|---|---|
| **Steps** | After the due alert of 2026-11-01, open service 1 → **Schedule**; check the default date and the "Already Scheduled in this Month" list; select 2026-11-20 → **Confirm Schedule**. |
| **Expected** | Status **Scheduled**, Scheduled Service Date 2026-11-20, Due Date still 2026-11-15; Schedule History 1 line (Scheduled); due alert activity Done with "Service scheduled"; the service appears on **Warranty → Free Service Calendar** on 2026-11-20. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-067 – Reschedule and calendar
| | |
|---|---|
| **Steps** | **Reschedule** without reason, then with the same date, then 2026-11-25 with reason "Customer away". Try to drag the calendar entry to another day. |
| **Expected** | Refused without reason / with the same date. Then status **Rescheduled**, Reschedule Count 1, history 2 lines (previous and new date, reason); the calendar entry moved to 2026-11-25 (one entry). Drag-and-drop is refused with a message to use Reschedule. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-068 – Validations
| | |
|---|---|
| **Steps** | Try a past date and 2026-12-16 (after the Grace Period End); try Schedule on a Completed / Expired / Cancelled service. |
| **Expected** | Each is refused with a clear message. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-069 – S2 monitoring of a scheduled service
| | |
|---|---|
| **Steps** | Schedule on 2026-11-10 for 2026-11-20; Procedure C on 2026-11-16, 2026-11-21; reschedule on 2026-11-25 for 2026-12-05; Procedure C on 2026-12-06, 2026-12-08, 2026-12-16. |
| **Expected** | 11-16 Scheduled; 11-21 **Missed**; 11-25 **Rescheduled**; 12-06 **Missed**; 12-08 one expiry reminder activity + email; 12-16 **Expired**, activities closed, one EXPIRED email. Due Date, Scheduled Service Date (12-05) and history kept; scheduling is refused after expiry. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-070 – R1 expiry reminder kept
| | |
|---|---|
| **Steps** | New card: Procedure C on 2026-11-16 (Missed) and 2026-12-08 (expiry reminder); schedule on 2026-12-09 for 2026-12-12; Procedure C on 2026-12-13. |
| **Expected** | The open expiry reminder stays open after scheduling; on 12-13 Missed again with no second reminder activity or email. |
| **Actual Result** | |
| **Status** | |

### 5.16 Kit products – Indoor / Outdoor serials (module warranty_management_mrp, section 6d)

Requires Manufacturing + Sales MRP. Kit **Split AC Kit** (Warranty Applicable) with a Kit BoM:
Indoor Unit (serial-tracked, role Indoor Unit), Outdoor Unit (serial-tracked, role Outdoor Unit),
Copper Pipe (role None); serials in stock for both units.

#### TC-P2-071 – Single kit
| | |
|---|---|
| **Steps** | Sell 1 kit, Warranty Grouping, validate the delivery. |
| **Expected** | Unit: Indoor / Outdoor Serial No. = the delivered serials (also in Serial(s)); card Indoor / Outdoor Serial No. filled; card Ready to Confirm. Before the delivery the card lists "Indoor Unit serial number for unit …". |
| **Actual Result** | |
| **Status** | |

#### TC-P2-072 – Several kits and partial delivery
| | |
|---|---|
| **Steps** | Sell 3 kits; deliver all Indoor Units and 1 Outdoor Unit (backorder); then the backorder. |
| **Expected** | After the first delivery: units 1–3 Indoor, unit 1 Outdoor (delivery order); card Draft with "Outdoor Unit serial number for unit …" (confirmation refused); card-level serial fields empty. After the backorder: units 2–3 get the Outdoor serials, unit 1 unchanged; card Ready. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-073 – Correct the pairing
| | |
|---|---|
| **Steps** | On the card → Unit Warranty Numbers: swap the Indoor serials of two units and save; try a serial that was not delivered, an Outdoor serial in the Indoor column, a serial of another unit; confirm the card and try again. |
| **Expected** | The swap is saved (Serial Pairing Corrected); only delivered serials of the same line and role are offered; the invalid choices are refused; after confirmation the serials are read-only. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-074 – BoM rules, kits without roles, non-kit products
| | |
|---|---|
| **Steps** | On the Kit BoM try two Indoor lines, a role on a non-serial component, quantity 2 for a role, switching the BoM to Manufacture. Sell a kit whose lines all have role None, and a serial-tracked non-kit product. |
| **Expected** | Each BoM change is refused. Kit without roles: units allocated from its first component, no Indoor / Outdoor fields. Non-kit product: serials as before. |
| **Actual Result** | |
| **Status** | |

### 5.17 Warranty card PDF download approval (section 6e)

Setup: Warranty Settings → *Warranty Card PDF Download Approval*: Require PDF Download Approval ✔,
Free Download Count 1, Download Approval Responsible Users = **Approver A**, **Approver B**.
User **Clerk** (internal, not approver). A confirmed warranty card.

#### TC-P2-075 – Confirmation and first download
| | |
|---|---|
| **Steps** | Confirm a card; open tab *Other Information* and *Download History*; as Clerk click **Download PDF**. |
| **Expected** | After confirmation: Download Count **0**, no download line, the PDF is not in the card's attachments. Download PDF downloads the PDF without approval; Download Count **1**, one history line (Clerk, date / time, no. 1). |
| **Actual Result** | |
| **Status** | |

#### TC-P2-076 – Second download with approval
| | |
|---|---|
| **Steps** | As Clerk click Download PDF again → enter a reason → Submit; click Download PDF again; as Approver A open the activity / Warranty Cards → Download Approval Requests → **Approve**; as Clerk click Download PDF twice. |
| **Expected** | Request WDR/… To Approve (also shown as a request row in the card's Download History), activities for Approver A and B; second click: "waiting for approval". After approval: one download (Download Count 2, request **Used**, history line with the request); the next click opens the request dialog again. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-077 – Reject, own request, other users
| | |
|---|---|
| **Steps** | Reject a request; add Clerk to the approvers and let Clerk request and try to approve; try Approve as a user who is not an approver; log in to another company's approver. |
| **Expected** | Rejected: no download, a new request is possible. Clerk cannot approve own request; non-approvers cannot approve; another company's users do not see the request. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-078 – Links cannot bypass the approval
| | |
|---|---|
| **Steps** | Copy the download link from the browser and open it again; as administrator open `/web/content/<PDF attachment id>`, `/report/pdf/warranty_management.report_warranty_card/<card id>`; upload a normal file to the card and download it. |
| **Expected** | The used link and the standard / report URLs are refused (no PDF); a link is only valid 10 minutes for its user; the normal file downloads as usual. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-079 – Existing cards after the update
| | |
|---|---|
| **Steps** | After the module update open a card confirmed before; check its attachments and Download Count; click Download PDF. |
| **Expected** | Download Count 0; the old PDF is no longer listed as an attachment; Download PDF delivers the same PDF (first download, free). |
| **Actual Result** | |
| **Status** | |

#### TC-P2-063 – Legacy product assignments copied once (after the module update)
| | |
|---|---|
| **Requirement** | Data and compatibility |
| **Steps** | After the module update open, in company Chicago, FN-SAM-001 Samsung Ceiling Fan and Samsung AC (No Unit); then the same products in San Francisco; open existing warranty cards. Check the server log. |
| **Expected** | Chicago: Warranty Policy **policy1** / **standed policy**; San Francisco: empty. Existing cards unchanged; all policies still exist (legacy mappings hidden). Log lines "Warranty policy migration: …". A second module update does not copy again. |
| **Actual Result** | |
| **Status** | |

### 5.18 Scope Mode limitation removed and Settings help (BA decision 2026-10-28)

#### TC-P2-080 – No Scope Mode limitation on the screens
| | |
|---|---|
| **Requirement** | BA decision 2026-10-28 – L3 / L5 / L6 |
| **Steps** | In **San Francisco** and in **Chicago**: open a product with Warranty Applicable, a product category, a Warranty Applicable pricelist with a policy, a warranty card, a Helpdesk ticket with a warranty card (and **Create Warranty Case**), a warranty case and a service job. |
| **Expected** | Free service sections are shown in both companies: product *Free Services*, category *Free Service Configuration*, pricelist *Free Services* / *Service Due Alert* / *Service Expiry*, card tab *Free Services*, ticket *Pending Services*, wizard *Pending Services* and *Merged Ad-hoc Request*, case tabs *Linked Free Services* / *Pending Customer Services*, job tab *Free Services*. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-081 – Existing cards and entitlements unchanged after the update
| | |
|---|---|
| **Requirement** | Data preservation (no regeneration, no duplicates) |
| **Steps** | After the module update open WC/00001 – WC/00004 (San Francisco) and their Services. |
| **Expected** | Same Free Services Allowed (1 / 2 / 2 / 3), same entitlements and statuses as before the update (WC/00001: 1 Job Created; WC/00002: Draft + Missed; WC/00003: Completed + Draft; WC/00004: 3 Draft); balances unchanged; no new entitlement. |
| **Actual Result** | |
| **Status** | |

#### TC-P2-082 – Settings help texts
| | |
|---|---|
| **Requirement** | Small Fix 2026-10-28 – every visible Warranty setting has a description and hover help |
| **Steps** | Settings → Warranty. Read the grey description under each setting; hover the setting label (or the setting, for settings without a field label). Toggle **Warranty Case Approval Required** off to see the approval users setting hide. |
| **Expected** | 38 visible settings, each with a plain English description; the hover shows the same text. *Warranty Case Approval Required*: "… If disabled, any Helpdesk user of the company can approve or reject them. In both cases approval is a manual step." (never "automatic"). *Require Customer Invoice to Close* and *Vendor Claims* as approved. |
| **Actual Result** | |
| **Status** | |

---

### 5.19 Warranty Start Date Automation (design `doc/start_date_design.md`, approved 2026-10-28)

Preparation: Settings → Warranty → **Warranty Timezone** = Asia/Colombo. Give one test user the
group **Warranty: Date Correction** (Settings → Users → Extra Rights). Keep a second user without
it. Times below are local (Asia/Colombo).

#### TC-SD-01 – Delivery basis: actual validation date
| | |
|---|---|
| **Requirement** | D2, Warranty Timezone |
| **Steps** | SO with 1 unit of a Delivery-basis warranty product → Warranty Grouping. Open the card: *Expected Start Date* empty. Validate the delivery. Reopen the card. Confirm Warranty. |
| **Expected** | Before validation: Draft, missing *Delivery for unit …*. After validation: Ready, Expected Start = validation date (local), Expected End = start + duration − 1 day; *Warranty Start Date Source* shows "Delivery WH/OUT/… validated on …". After Confirm: Start Date Source = Delivery, Source Delivery and Source Date / Time filled, chatter note *Warranty activated …*, Warranty Date History line *Activation*. SO date / scheduled date not used. |
| **Actual Result** | |
| **Status** | |

#### TC-SD-02 – Delivery basis: partial deliveries
| | |
|---|---|
| **Requirement** | D2, Q15 |
| **Steps** | SO with 3 units (Per SO grouping). Deliver 2 (create backorder), wait a day or note the time, deliver the backorder. |
| **Expected** | After the first delivery the card stays Draft (*Delivery for unit WN/…-03*), no split. After the backorder: Ready, start = backorder validation date; each unit shows its own *Delivered On*. |
| **Actual Result** | |
| **Status** | |

#### TC-SD-03 – Invoice basis: actual posting time, not the invoice date
| | |
|---|---|
| **Requirement** | D1, D3 |
| **Steps** | Invoice-basis product, SO delivered. Create the invoice, set **Invoice Date** to an earlier date (e.g. 01/01), post it. Check the invoice tab *Other Info* (Actual Posting Time) and *Posting History*. Open the card. |
| **Expected** | Card Ready; Expected Start = posting date (local), not 01/01. Invoice shows Actual Posting Time and one *Posted* event. Draft invoice before posting: card Draft, *Posted invoice for unit …*. |
| **Actual Result** | |
| **Status** | |

#### TC-SD-04 – Invoice reset to draft and posted again
| | |
|---|---|
| **Requirement** | D1b |
| **Steps** | On the invoice of TC-SD-03 (card not confirmed): Reset to Draft, then post again later. |
| **Expected** | After the reset: card Draft, Actual Posting Time empty. After reposting: Expected Start = new posting date. Posting History: Posted, Reset to Draft, Posted (earlier events kept). |
| **Actual Result** | |
| **Status** | |

#### TC-SD-05 – Partial invoices, down payment, credit note
| | |
|---|---|
| **Requirement** | D3, Q1–Q3 |
| **Steps** | SO with 3 units (Invoice basis), delivered. (a) Down payment invoice, post. (b) Invoice 2 units, post. (c) Invoice the last unit, post. (d) Credit note (Reverse) of invoice (c), post. |
| **Expected** | (a) card Draft – down payment never counts. (b) Draft, *Posted invoice for unit …-03*. (c) Ready, start = posting date of (c). (d) Draft again (unit 3 no longer invoiced). |
| **Actual Result** | |
| **Status** | |

#### TC-SD-06 – Credit note after confirmation
| | |
|---|---|
| **Requirement** | Q16, D11 |
| **Steps** | Confirm an Invoice-basis card, then reverse its invoice and post the credit note. |
| **Expected** | Card stays Confirmed with the same dates; chatter note *Credit note … posted … warranty dates unchanged*; Warranty Date History *Invoice Reversal*; To-Do activity for the Service Alert Responsible User(s). |
| **Actual Result** | |
| **Status** | |

#### TC-SD-07 – Invoice posted before the automation (live data)
| | |
|---|---|
| **Requirement** | D1a, Q4 |
| **Steps** | Only on a copy of 18_4 after the upgrade: new Invoice-basis card covered by INV/2026/00001 – 00004 (no posting history), or by INV/2026/00005 – 00007 (posting tracked). |
| **Expected** | 00001 – 00004: missing *Verified invoice posting time … an authorized exception is required*; never the invoice / creation date. 00005 – 00007: start from the tracked posting time, source note "(verified from the invoice posting history)". |
| **Actual Result** | |
| **Status** | |

#### TC-SD-08 – Authorized exception
| | |
|---|---|
| **Requirement** | D1a, D8, Q10, Q14 |
| **Steps** | Card of a service-type warranty product with Delivery basis (no physical delivery). As the user without the group: no *Record Start Date Exception* button. As the Date Correction user: Record Start Date Exception, enter a date, try without reason, then with reason and an attachment; Confirm Warranty. |
| **Expected** | Missing requirement *Validated delivery: … authorized exception is required*. Reason mandatory. After the exception: Ready (other requirements still apply), manual Confirm; Start Date Source = Authorized Exception; chatter note with the reason; history *Authorized Exception* with the evidence. |
| **Actual Result** | |
| **Status** | |

#### TC-SD-09 – Confirmed dates protected
| | |
|---|---|
| **Requirement** | D9 |
| **Steps** | On a confirmed card try to change the dates / Installation Date (form, Import with the card's ID and a new end date). |
| **Expected** | Fields are read-only; the import is refused ("Warranty dates and their sources are set by the system …"). WC/00001 – WC/00004 still show their dates; Start Date Source shows "Not recorded (confirmed before the start date automation)". |
| **Actual Result** | |
| **Status** | |

#### TC-SD-10 – Correct Warranty Dates
| | |
|---|---|
| **Requirement** | D9, D10, Q11, Q12 |
| **Steps** | Confirmed card with Draft free services; change one due date with *Change Due Date*. As the Date Correction user: **Correct Warranty Dates**, new start date, reason, Apply. |
| **Expected** | The wizard lists the services that will be recalculated and the ones kept (manually re-dated, scheduled, finalized). After Apply: card and units have the new start / end (end from the duration), eligible Draft / Pending services have new due dates (Due Date History entry), the manually changed one is kept, PDF soft copy regenerated (Download Count unchanged), history *Date Correction* with before / after and reason. Without the group: no button. |
| **Actual Result** | |
| **Status** | |

#### TC-SD-11 – Custom Date Range and Usage unchanged
| | |
|---|---|
| **Requirement** | Additional requirement 8 |
| **Steps** | Confirm a Custom Date Range card (manual start / end) and a Usage-basis card. |
| **Expected** | Custom: same as before (manual dates in Draft, Start Date Source = Custom Date Range). Usage: no end date. |
| **Actual Result** | |
| **Status** | |

---

## 6. Traceability Matrix

| Requirement / Decision | Description | Test cases | Status |
|---|---|---|---|
| Mapping p.15 – Free Services Included? | Allowed > 0 (Scope Mode limitation removed, BA decision 2026-10-28) | 004, 005, 080, 081 | |
| Mapping p.15 – Read Warranty Policy / Values | Count, frequency, period, schedule method, basis, start / end | 006, 009, 013 | |
| Mapping p.15 – Auto Create Services Enabled? | Policy first, company fallback | 006, 007, 008 | |
| Mapping p.15 – Create Draft Service Entitlements | N Draft lines, Free Preventive | 006 | |
| Mapping p.15 – Create Service Entitlements Manually | Manual lines, limits | 022 – 025 | |
| Mapping p.15 – Generate Free Service Schedule | Schedule Method branches | 009 – 018 | |
| Mapping p.15 – Assign Service Sequence | Service 1, 2, 3 / WSE reference | 006, 022, 024 | |
| Mapping p.15 – Set Planned / Due Date | Due Date / Usage Due | 006, 009 – 021 | |
| Mapping §2.2 – entitlement fields | Fields present; later-phase fields empty | 006, 032 | |
| SRS §10.3 – statuses (+ Draft) | Draft start state; Merge Status separate | 006, 032 | |
| Q2 | Scope-based eligibility, no AMC entitlements | 004, 005, 018 | |
| Q3 | Policy explicit "No" not overridden | 007 | |
| Q4 | Schedule method snapshot, no silent default | 008, 014 | |
| D1 / D1a / D1b | Frequency first, period ÷ count, days for non-divisible, month-end, leap year, conflict notice | 009 – 013 | |
| D2 / B1 | Dates unchanged, after-end flag, not blocking | 006, 012, 013 | |
| D3 / B3 | Fixed Offsets configuration, snapshot, validation vs resolved count | 002, 003, 014, 015 | |
| – | Calendar Month removed | 016 | |
| D5 | Usage Due formula, precision, missing limit | 019 – 021 | |
| D6 | Schedule notice on Free Services tab | 006 – 008, 013, 015 – 018, 021 | |
| D7 | Card-level lines, no unit auto-assignment | 031 | |
| D8 / B4 | Unique numbers, count limit, no automatic extra lines | 024, 026, 027 | |
| B2 | Draft-only due date correction with audit trail | 017, 028, 029 | |
| Q11 | Worksheet template rule | 030, 031 | |
| Q17 | After confirmation only, idempotent, rollback | 025, 027, 036 (`test_17_pdf_failure_rolls_back`) | |
| Q18 | Menu, views, navigation, security | 032 – 034 | |
| Part 1 preservation | Regression | 035, 036 | |
| C1 | Draft kept, SRS §10.3 statuses unchanged | 006, 032 | |
| C2 | Due indicator separate from status | 039, 052 | |
| C4 / T1–T4 | Missed / Expired rules | 040 – 044 | |
| D1 / D2 | Balance formula and counts | 040, 042, 049 | |
| D3 / Q7 | Deletion restrictions | 048 | |
| Q2 / A1 / A2 | Responsible users (several allowed, one activity each), fallback, missing / skipped user warning | 037, 038, 046, 053, 054 | |
| Q4 | Carry-forward stops expiry | 043 | |
| Q5 | System activities closed on expiry, history kept | 036 (`test_05`) | |
| Q6 | 0-day alerts disabled, grace 0 | 044, 045 | |
| A3 | No duplicates, late runs, due date change | 039, 041, 042, 047, 053 | |
| A7 | Expiry block | 051 | |
| A8 | Warranty timezone | 037, 036 (`test_17`) | |
| X4 | Expiry Reminder Days | 041 | |

---

## 7. Defect Log

| Defect ID | Test case | Summary | Steps to reproduce | Expected | Actual | Severity | Status |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

---

## 8. Test Summary and Sign-off

| Item | Value |
|---|---|
| Test cases executed | ___ / 54 |
| Passed | |
| Failed | |
| Blocked | |
| N/A | |
| Open defects | |
| Tester | |
| Test date | |
| Database | |

**Readiness status (choose one):**

- ☐ PART 2 (FREE SERVICE SCHEDULE AND DUE MONITORING) – PASSED, READY FOR APPROVAL
- ☐ PART 2 – PASSED WITH MINOR ISSUES
- ☐ PART 2 – FAILED, FIXES REQUIRED
- ☐ PART 2 – TESTING IN PROGRESS

| Role | Name | Signature | Date |
|---|---|---|---|
| Tester | | | |
| Functional reviewer | | | |
| Approver | | | |

---

## 9. Known Limitations in This Phase (not defects)

1. Calendar Month was removed from the Schedule Methods (2026-10-19).
2. Entitlements only move Draft / Pending → Missed → Expired through the scheduled action; Completed is set in Part 4, so Free Services Used stays 0.
3. Cancellation / replacement of entitlements is deferred (B4).
4. `helpdesk_ticket_id` and `field_service_task_id` fields are deferred to the parts that add Helpdesk / Field Service.
5. Entitlements are card-level; unit / serial allocation is deferred (D7).
6. Status lists differ between Mapping §2.2 / SRS §12 and SRS §10.3; SRS §10.3 + Draft is implemented as approved.
7. With the Part 1 end-date rule (start + period − 1 day), the last Equal Interval service of a standard card is always one day after the warranty end and is flagged (approved under B1).
8. Usage-based monitoring, carry-forward behaviour, overdue reminders and an entitlement cancellation action are not implemented (see `doc/part2_design_decisions.md` §9).
9. The expiry block (merge status Selected / Merged) has no UI trigger until Part 3/4.
10. Cards confirmed before version 18.0.1.2.0 are never monitored.
11. Carry-forward Allowed is hidden on the policy form (always off) until the carry-forward rules are defined.
