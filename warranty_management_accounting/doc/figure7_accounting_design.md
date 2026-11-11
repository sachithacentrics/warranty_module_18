> **Revision 3 (2026-11-07):** after the SRS review the custom B2 reclassification was replaced by standard Odoo stock accounting and Finance-controlled reserve utilization (accounting 18.0.1.8.0). Current design: `figure7_accounting_integration.md`. Sections below describing B2 are history.

# Figure 7 Warranty Expense / Provision: Finance design (B2 evaluated, not built)

Status, revision 2 (2026-11-07):
- This is a design for Finance approval. **No accounting code was written and no entry was created.**
- Revision 2 evaluates route **B2 (reclassification under manual / periodic valuation)** on the UAT data. The inventory valuation configuration stays as it is.

Based on:
- SRS 2.10, 16.1 and 17;
- the Part 8 mapping (`Part8_Cost_Accounting_Mapping.md`, routes B1–B3 and C/D, decisions F1–F8);
- Part 8.6 (`part8_6_provision_entry_design.md`);
- the UAT database `warranty_management_18_4`, read-only on 2026-11-07.

Labels used below:
- **[SRS]**: requirement stated in the SRS.
- **[Approved]**: existing approved decision.
- **[Policy]**: company accounting policy that needs a Finance decision.
- **[UAT fact]**: read from the UAT database.

## 0. What the SRS requires

| Item | SRS text (17, 2.10, 16.1) | Label |
| --- | --- | --- |
| Covered spare-part issue | "Use standard inventory valuation/stock accounting. Allocate actual cost to warranty case/job; optionally debit Warranty Provision/Reserve or Warranty Expense according to company policy." | [SRS] + [Policy] |
| Part consumption | "Capture inventory cost against warranty case; optionally reclassify against warranty reserve based on accounting configuration." | [SRS] + [Policy] |
| Warranty cost | "may be expensed directly or applied against warranty provision/reserve according to company accounting configuration" | [Policy] |
| Non-covered parts | "Create customer quotation before issue according to trigger; invoice sales price and recognize standard COGS/stock valuation." | [SRS] |
| Material cost approval | "Estimated cost drives approval. Actual cost is locked from valuation/purchase/subcontract records." | [SRS] |
| Vendor reimbursement | "Record vendor credit note against relevant vendor bill or a claim receivable/other recovery account based on accounting policy." | [SRS] + [Policy] |
| Provision at sale | "If enabled, post Warranty Expense Dr and Warranty Provision/Reserve Cr" | [SRS], built in 8.6 |

**Nothing is posted at request submission or approval.** Estimates drive approval only [SRS].

## 1. UAT evidence (read-only, 2026-11-07)

### 1.1 Valuation and accounts

| Item | Value | Label |
| --- | --- | --- |
| Valuation, all 19 categories, both companies | **Manual (periodic)**, **Standard** cost. These are system defaults (`ir_default`); no category overrides them. No category uses automated valuation | [UAT fact] |
| Category expense account | Company default **600000 Expenses** for every category (`ir_default`). No category or product has its own | [UAT fact] |
| 600000 Expenses | Type Expenses. It is the general catch-all expense account | [UAT fact] |
| Posted lines on 600000 | 4 bill lines (1,571.10) and 3 refund lines (−571.10): Office Furniture, Software, the "All" category and one line without a product. Net **1,000.00**. **None is a spare part** | [UAT fact] |
| Stock accounts 110100 / 110200 / 110300 | No journal items | [UAT fact] |
| Stock valuation layers (company 1) | Total value **47,507.00**; general ledger inventory **0** | [UAT fact] |
| Warranty accounts | 625100 Warranty Expense (Expenses); 216100 Warranty Provision / Reserve (Current Liabilities); 450100 Warranty Vendor Recovery (Other Income); journal MISC; Cost Recognition Account not set | [UAT fact] |
| 216100 | One **draft** provision entry (Dr 625100 100, Cr 216100 100). Posted balance **0** | [UAT fact] |
| Warranty Consumption location | Usage **Inventory adjustment**, no valuation accounts | [UAT fact] |
| Lock dates | None set | [UAT fact] |
| Anglo-Saxon accounting | On for company 1 (it only matters with automated valuation) | [UAT fact] |

### 1.2 How the spare-part stock arrived

| Source | Quantity | Expense entry |
| --- | --- | --- |
| Inventory adjustments ("Product Quantity Updated") | 22 units: Fan Sensor 6, Gas R410A 10, DEMO Compressor 2, DEMO Fan Motor 3, Compressor Relay 1 | **None** |
| Purchase receipt P00013 (Compressor Relay 2 × 1,200) | 2 units | **None**: the order is still To Invoice |
| Posted vendor bills for spare parts | 0 | n/a |

**Conclusion:** no spare-part cost has ever reached any expense account in UAT.

### 1.3 Usage records already in UAT (before any B2)

| # | Request | Case | Type | Part | Coverage | Valuation value |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | MRF/000005 | WCAS/000003 | Used | Fan Sensor | Covered | 700.00 |
| 3 | MRF/000005 | WCAS/000003 | Used | Compressor Relay | Covered | 1,200.00 |
| 2, 6 | MRF/000005 | WCAS/000003 | Installed, Customer Keeps | Gas R410A | Not Covered | none (no stock move) |
| 4, 5 | MRF/000005 | WCAS/000003 | Unused Return | Fan Sensor 1, Compressor Relay 2 | Covered | none |
| 7, 8, 9, 11 | MRF/000007, 09, 10, 11 | WCAS/000013, 042, 052, 059 | Used | Bolt (category Consumable) | Covered | 0.50 + 0.50 + 0.50 + 1.50 |
| 12 | MRF/000012 | WCAS/000059 | Used | DEMO Fan Motor | Covered | 300.00 |
| 14 | MRF/000012 | WCAS/000059 | Used | Compressor Relay | Covered | 1,200.00 |
| 13 | MRF/000012 | WCAS/000059 | Installed | Gas R410A | Not Covered | none |

- Covered Used total: **3,403.00** (spare parts 3,400.00, Bolt 3.00).
- No goodwill usage exists yet.
- No valuation layer has a journal entry.

Vendor recovery: VCL/00007 (WCAS/000059) has posted credit note RBILL/2026/11/0001, Dr Payable 1,200 / Cr 450100 1,200, for a Compressor Relay. That relay's purchase has not been billed yet.

### 1.4 Who can post today

The UAT users `main_tech` and `support_tech` (technicians) have **Accounting Administrator** and Bookkeeper rights, the same as `admin` and `approval`. They can post and change journal entries. [UAT fact]

## 2. Is 600000 the correct Cost Recognition Account? **No (as UAT stands)**

| Test | Result |
| --- | --- |
| Do spare-part purchases debit it? | Only by default, through the company default expense account. **No spare-part bill has ever been posted**, so it holds 0 of spare-part cost |
| Is it specific to spare parts? | No. It is the catch-all for every category (furniture, software, untagged lines) |
| Does Finance's periodic stock adjustment use it? | No periodic stock adjustment has ever been posted (no entry on any stock account) |
| What would B2 do to it? | Backfilling the 3,403.00 of historical usage would credit it 3,403.00. Its posted balance would fall from 1,000.00 to **−2,403.00**: negative "Expenses" that hides furniture and software cost |

The Cost Recognition Account must be the account where the cost of these parts is recognized under periodic valuation:
- the parts vendor bills debit it;
- **and** Finance's period-end stock adjustment uses it.

In UAT neither exists yet, so Finance has to choose or create the account (decision F2).

## 3. How B2 works under periodic valuation

Under periodic valuation:
- purchases are expensed when billed;
- the inventory asset is corrected only at period end, by Finance's stock adjustment (closing stock value minus the book value).

Total parts expense for a period = purchases − (closing stock − opening stock).

**B2 changes only the classification, never the total.** Each covered usage moves its valuation value from the parts cost account (the Cost Recognition Account) to Warranty Expense.

Total P&L expense stays right **only if** the Cost Recognition Account is the same account the period-end stock adjustment posts to. Then:
- usage taken from stock that was never billed (opening stock, inventory adjustments, P00013) makes the account temporarily negative;
- the period-end adjustment (Dr Cost Recognition, Cr Inventory) brings it back.

Worked check (Fan Sensor from opening stock, 700):

| Step | Inventory (asset) | Cost Recognition | 625100 | Total expense |
| --- | --- | --- | --- | --- |
| Opening stock booked by Finance | 3,500 Dr | | | 0 |
| B2 at usage: Dr 625100 700 / Cr Cost Recognition 700 | 3,500 | −700 | 700 | 0 |
| Period end: count 2,800; Dr Cost Recognition 700 / Cr Inventory 700 | 2,800 | 0 | 700 | **700** |

Result: correct total (700), correct classification (warranty) and correct asset (2,800).

If Finance books the adjustment to another account, the total stays right but both accounts are misstated. If Finance books **no** adjustment, the asset stays overstated by 700 and the expense never appears. That is the opening-stock risk (F3).

## 4. Exact B2 entries

**Amount:** the value of the stock valuation layer of the usage stock move. These layers exist under manual valuation, at standard cost when the move is validated (UAT: Fan Sensor −700.00). The current standard cost is never re-read, so later cost changes do not change an entry.

**Date:** the date of the stock move. **Journal:** Warranty Accounting Journal (MISC). **State:** draft.

| Event | Entry | Created when |
| --- | --- | --- |
| **Used**, Covered line | Dr 625100 Warranty Expense / Cr Cost Recognition, valuation value | Confirm Material Usage |
| **Used**, goodwill line | Same accounts (or a Goodwill Expense account, F8); the line is marked Goodwill | Same |
| Installed / Customer Keeps (Not Covered) | **None.** The customer's part: sales order and invoice; under periodic valuation the cost stays in purchases | n/a |
| Unused Return / Customer Return | **None.** Nothing was consumed; the part is back in stock | n/a |
| Cancel Remaining | **None** | n/a |
| **Reverse** of a Used entry, B2 entry still draft | The draft is **cancelled** (kept for audit, not deleted) | Reverse Consumption |
| **Reverse** of a Used entry, B2 entry posted | Draft reversal: Dr Cost Recognition / Cr 625100, same amount, linked to the original | Reverse Consumption |
| Usage with no valuation value (non-stored product, zero cost) | No entry; listed in a Finance view "Usage without valuation" | n/a |

Labour, travel and subcontract are never B2. They have their own documents: timesheets, cost lines, subcontract bills.

## 5. Preventing double accounting

| Risk | Control |
| --- | --- |
| Two entries for one usage (double click, retry, re-confirm) | One B2 entry per usage record: a unique link on the journal entry, ignoring cancelled entries |
| A product valued in real time | No B2 when the usage move's valuation layer already has a journal entry, or when the product's category is automated for the company. Standard Odoo then books the cost, and needs the Warranty Consumption location accounts (section 7) |
| Not Covered parts | Never B2. The line coverage is read from the request line; Not Covered lines never reach the Warranty Consumption location (guard built in D2) |
| Finance also books warranty usage by hand, or books "inventory losses" from the inventory-adjustment report | **Warranty Consumption is an inventory-adjustment location**, so those moves also appear as stock losses. Finance's period-end entry must be the **net stock change only**, to the Cost Recognition Account, with no separate loss entry for these moves (F3) |
| Provision expense at sale plus actual cost | Reserve utilization (section 8) moves the actual cost from 625100 to 216100. A cost covered by the reserve is expensed once, at sale |
| Utilization funded twice | Each case is utilized once (unique link). Available reserve deducts unposted utilization drafts |
| Vendor recovery counted as cost | Utilization is net of posted recoveries |
| Customer billing counted in provision | Parts-quotation invoices are already excluded from the 8.6 provision (`warranty_mrf_line_id`) |
| Historical usage | Not backfilled automatically (F6) |

## 6. Manual and automated valuation products

| Product category valuation | Covered usage | Customer (Not Covered) delivery |
| --- | --- | --- |
| Manual (periodic): all UAT today | B2 draft | No stock entry; income only |
| Automated (real time): none in UAT | **No B2.** Standard entry: Dr the Warranty Consumption location's Incoming account, else Stock Output; Cr Stock Valuation | Standard, plus cost of goods sold at invoice (Anglo-Saxon) |

**Risk found:** the Warranty Consumption location has no valuation accounts. If any category becomes automated, usage would post Dr **Stock Output 110300** / Cr 110100, and 110300 would never clear.

B2 will include a configuration check:
- B2 can't be switched on while an automated category exists in the company and the Warranty Consumption location has no Incoming / Outgoing account;
- the check names the category.

## 7. Goodwill and vendor reimbursement

**Goodwill:**
- It is a company decision outside the warranty obligation. It is warranty-type cost in 625100, with the Goodwill flag on the entry line, or in a separate Goodwill Expense account (F8).
- Recommendation: goodwill is **not** charged to the warranty reserve. The provision was built for warranty obligations, not discretionary goodwill (F9).

**Vendor reimbursement:**
- This is the existing claim and draft credit note (Dr Payable / Cr 450100), posted by Accounting. It is not changed.
- The cost stays in 625100, and the recovery is income in 450100.
- Net warranty cost of a case = posted 625100 lines of the case − posted recoveries. The Warranty Cost report already shows this.

**UAT note:** RBILL/2026/11/0001 recognized 1,200 of recovery while the relay's purchase P00013 is still unbilled. This is not a code issue, but Finance should know that recovery can be booked before the purchase cost.

## 8. Reserve utilization (route C/D)

| Item | Proposal |
| --- | --- |
| When | Close Case [Approved: mapping D4] |
| Eligible cost | Posted 625100 lines linked to the case: B2 entries, plus subcontract bills of the case posted to 625100, minus posted recoveries of the case. Goodwill excluded (F9). Labour and travel excluded |
| Available reserve | Posted credits minus posted debits on 216100 for the company up to the Close Case date (= Outstanding Reserve of the 8.6 report), **minus unposted utilization drafts** |
| Entry | Draft Dr 216100 / Cr 625100 = min(eligible, available), Warranty Reserve Movement = Utilization, linked to the case |
| Shortfall | Stays in 625100. Finance gets a To-Do. The reserve never goes negative [Approved D] |
| Draft entries | Unposted B2 entries are not eligible: the case shows "B2 entries not posted", and Finance creates the utilization again after posting them |
| Case reopened, or a source reversed after utilization | Draft reversal of the utilization, capped at the original |
| Recovery posted after utilization | No automatic entry; Finance releases manually if wanted [Approved F8] |

Not allowed: Dr 216100 / Cr 625100 for a cost that was never debited to 625100 [Approved].

## 9. Worked examples (UAT data, B2)

"CR" is the Cost Recognition Account that Finance chooses (F2).

### Example 1: WCAS/000003 (MRF/000005), covered, unused return, Not Covered

| Event | Dr | Cr | Amount |
| --- | --- | --- | --- |
| Usage 1: Fan Sensor used | 625100 | CR | 700.00 |
| Usage 3: Compressor Relay used | 625100 | CR | 1,200.00 |
| Usages 4, 5: unused returns (Fan Sensor 1, Relay 2) | none | | |
| Usages 2, 6: Gas R410A installed and kept, Not Covered | none (invoice from the parts sales order: Dr Receivable / Cr 400000) | | |
| Vendor claim VCL/00001: credit note still draft | none until posted | | |
| Close Case, available reserve 5,000 (assumed; UAT posted reserve is 0) | 216100 | 625100 | 1,900.00 |

| Account | Balance after |
| --- | --- |
| 625100 | 0 (1,900 Dr − 1,900 Cr) |
| CR | 1,900 Cr until Finance's period-end stock entry |
| 216100 | 3,100 Cr |

**With the real UAT reserve (posted 0):** no utilization; shortfall 1,900 stays in 625100 and Finance gets a To-Do.

### Example 2: WCAS/000059 (MRF/000011, MRF/000012), recovery and reversal

| Event | Dr | Cr | Amount |
| --- | --- | --- | --- |
| Usage 12: DEMO Fan Motor used | 625100 | CR | 300.00 |
| Usage 14: Compressor Relay used | 625100 | CR | 1,200.00 |
| Usage 11: Bolt × 3 used (category Consumable, if in scope, F4) | 625100 | CR | 1.50 |
| Usage 13: Gas R410A installed, Not Covered | none | | |
| RBILL/2026/11/0001 (exists, posted) | 211000 Payable | 450100 | 1,200.00 |
| Close Case: eligible = 1,501.50 − 1,200.00 = 301.50; reserve 5,000 (assumed) | 216100 | 625100 | 301.50 |

| Account | Balance after |
| --- | --- |
| 625100 | 1,200.00 Dr (the recovered relay) |
| 450100 | 1,200.00 Cr |
| 216100 | 4,698.50 Cr |
| CR | 1,501.50 Cr |

Net warranty P&L: 1,200 − 1,200 = 0 for the relay. Fan Motor and Bolt are funded by the reserve.

**Reversal variant:** the Fan Motor usage is reversed before the case closes:
- B2 draft still open: the draft is cancelled, and eligible becomes 1.50.
- B2 posted: draft reversal Dr CR 300 / Cr 625100 300.

### Example 3: period end (Finance, outside the workflow)

Spare-part stock value falls by the 3,403.00 consumed (no new purchases billed). Finance posts Dr CR 3,403.00 / Cr Inventory 3,403.00.

| Account | Balance |
| --- | --- |
| CR | 0 |
| Inventory | Equals the valuation report |
| 625100 | Before utilization: 3,403.00 Dr |

If CR were **600000**, it would end at the furniture and software figure only if Finance also posted the stock adjustment to 600000. Today none is posted, so 600000 would show −2,403.00 (section 2).

### Reconciliation checks per case

- Warranty Cost report actual material cost = posted B2 lines of the case (before utilization).
- Utilization ≤ eligible and ≤ available reserve.
- Customer billed = posted invoice lines of the parts quotations.
- Recovered = posted credit notes allocated to the claim.

## 10. Posting permissions, multi-company and audit trail

**Creation:** the workflow creates drafts as the system. Users never type the accounts.

**Posting:** standard Accounting rights only (Bookkeeper or Administrator). Technicians and store users get no new right.
- **UAT finding:** `main_tech` and `support_tech` hold Accounting Administrator. Finance / the administrator should remove it before Figure 7 UAT (configuration through the frontend; I will not change UAT users).

**Locked period:** posting is refused by Odoo. Finance changes the draft date (8.6 pattern).

**Configuration:**
- only users with Settings and Accounting Manager rights can change it (existing rule);
- it is tracked in chatter;
- B2 is off until all of the following are set: journal, Warranty Expense, Cost Recognition (≠ Warranty Expense, type Expenses / Cost of Revenue) and the B2 switch.

**Multi-company:** the request's company only, with its own journal, accounts and currency.

**Audit:**
- Each entry stores the usage record, request line, request, case, stock move and route.
- It is linked and logged in chatter on the usage, request and case.
- A "Warranty parts entries" filter for Finance.
- Entries are never deleted (cancelled or reversed instead).
- The Reserve report shows utilization.

## 11. What changes in code if approved (no change yet)

- **`warranty_management_accounting` only** (new file and tests):
  - company B2 switch and checks;
  - B2 draft on Used, cancel or reverse on Reverse;
  - utilization draft at Close Case;
  - links, filters and the "Usage without valuation" list.
- **Request workflow:** only one call each after Confirm Material Usage, Reverse and Close Case, through overridable methods. Approval, quotation, stock, Repair Order and cost breakdown behaviour stay unchanged.
- **Nothing in UAT changes** until the separately authorized upgrade (Phase 6).

## Decisions for Finance (needed before any accounting code)

| # | Decision | Options | Recommendation |
| --- | --- | --- | --- |
| F1 | Route for company 1 | B1 (operational only) / B2 / B3 (automated) | **B2**, keeping manual / periodic valuation. B3 stays possible later |
| F2 | Cost Recognition Account | 600000 / a dedicated account | **Not 600000** (section 2). A dedicated account, for example "Spare Parts Purchases / Change in Inventory", type Cost of Revenue. Set it as the expense account of the categories in scope, and post the period-end stock adjustment to it |
| F3 | Opening stock and periodic adjustments | Finance books opening inventory and a period-end net stock adjustment to the account in F2 / no periodic adjustment | Finance confirms both. UAT has 47,507.00 stock value and 0 inventory in the ledger. Without both, B2 understates total expense |
| F4 | Categories in scope | Warranty Spare Parts only / every stored product used on a covered line | Every stored product on a covered line (UAT: also Bolt in Consumable), provided its category uses the F2 account. Activation lists the categories that don't |
| F5 | Timing and amount | Each Used record at valuation value / at request closure | Each Used record, dated the stock move, valuation-layer value |
| F6 | Historical usage before activation (UAT: 3,403.00) | No backfill / backfill drafts | No automatic backfill. A list for Finance, who may book one manual entry |
| F7 | Reversal | Cancel draft and reverse posted / delete | Cancel draft, draft reversal of posted. Never delete |
| F8 | Goodwill account | 625100 with flag / separate Goodwill Expense | 625100 with the Goodwill flag, unless Finance wants a separate account |
| F9 | Reserve-eligible costs | Parts, subcontract, goodwill, labour, travel | Covered parts and subcontract posted to 625100; **not** goodwill, labour or travel |
| F10 | Utilization timing and basis | Close Case / each usage; gross / net of recovery | Close Case, net of posted recoveries; only posted B2 entries count |
| F11 | Available reserve | Posted balance / posted balance minus unposted utilization drafts | Posted 216100 balance minus unposted utilization drafts |
| F12 | Vendor recovery credit | 450100 income (current) / credit 625100 | Keep 450100 (current, approved) |
| F13 | Posting | Drafts posted by Finance / automatic | Drafts posted by Finance. Remove Accounting Administrator from the technicians in UAT |
| F14 | Automated categories in future | Configuration check / none | Check built with B2 (section 6) |
