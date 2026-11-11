# Figure 7 accounting: integration with standard Odoo Accounting and Inventory

| Item | Value |
|---|---|
| Module | `warranty_management_accounting` **18.0.1.8.0** (replaces the custom parts-expense process of 18.0.1.7.x) |
| SRS | 2.10, 3 (Accounting / Inventory rows), 17, Figure 7 (N7, N9) |
| Status | Built and tested on `wt_p7_s2`; trial upgrade on a copy of UAT (`wt_f7_mrf13`). **Not on UAT.** |
| Supersedes | `figure7_b2_finance_checklist.md`, `figure7_b2_setup_and_upgrade.md` (kept for history only) |

## 1. Principle

Warranty Management records the operational facts (case, request, coverage, usage, claim). Accounting is done by Odoo's own documents: stock valuation and its journal entries, customer invoices, vendor credit notes, payments, reconciliation, journals and financial reports. The module adds only warranty-specific controls on top of them (SRS 3: "custom logic only where standard Odoo does not provide … warranty accounting control").

It never switches a valuation method, creates an account or opening balance, or posts an entry by itself.

## 2. Standard accounting mapping

| SRS 17 scenario | Standard Odoo document | Warranty-specific part (custom) |
|---|---|---|
| Warranty provision at sale | `account.move` (Miscellaneous journal), draft, Dr Warranty Expense / Cr Warranty Provision | Part 8.6: amount rule, draft created at invoice posting, Finance posts it |
| Covered spare-part issue / consumption | `stock.move` + `stock.valuation.layer`; with **automated** valuation Odoo's own stock journal entry | Actual cost from the valuation layers allocated to the case, request line and job (Material Cost tab, Case Cost Breakdown) |
| Optionally debit Warranty Expense or Warranty Provision / Reserve "according to company policy" | Standard **Stock Valuation Account (Incoming / Outgoing)** of the Warranty Consumption location | none: Finance chooses the account on the location |
| Reserve utilization ("applied against warranty provision / reserve") | `account.move`, draft, Dr Warranty Provision / Cr Warranty Expense, Warranty Accounting Journal | Created by Finance per completed case, capped at eligible posted cost and available posted reserve, posted by Bookkeeper / Administrator only |
| Non-covered spare parts | Sales order → delivery → customer invoice; standard COGS / stock valuation | Created from the request (Create Parts Quotation); release on confirmation / payment |
| Vendor / manufacturer reimbursement | Vendor credit note (`in_refund`) on the Vendor Recovery account, payment and reconciliation | Vendor claim links the credit note to the case and request lines; draft only, posted by Accounting |
| Replacement cost, inspection fee, credit note | Standard stock moves, invoices, credit notes | Parts 7 and 8.4 (unchanged) |

## 3. Covered parts: what Odoo posts

The used part moves from the technician location (internal) to the **Warranty Consumption** location (type Inventory Loss). Odoo 18 (`stock_account`, `stock.move._get_accounting_data_for_valuation`) uses the destination location's **Stock Valuation Account (Incoming)**, or the category's Stock Output account when it is empty.

| Valuation of the product category | At issue to the technician (internal) | At use (technician → Warranty Consumption) | At usage reversal | Cost on the case |
|---|---|---|---|---|
| **Manual (periodic)**, as on UAT | no entry | no entry: the cost was expensed by the vendor bill; Finance's period-end stock adjustment applies | no entry | valuation layer value |
| **Automated (real time)** | no entry | Odoo posts **Dr \<location Incoming account\> / Cr Stock Valuation** | Odoo posts **Dr Stock Valuation / Cr \<location Outgoing account\>** | valuation layer value, same as the entry |

There is never a second warranty entry for the same usage, so there is no duplicate expense under either method.

### Journal-entry examples (UAT accounts 625100 Warranty Expense, 216100 Warranty Provision / Reserve, 450100 Vendor Recovery)

**A. Automated valuation, location accounts = 625100 (expense policy).** Compressor Relay used, standard cost 1,200:

| Account | Debit | Credit |
|---|---|---|
| 625100 Warranty Expense | 1,200 | |
| Stock Valuation (category) | | 1,200 |

Journal: the category's Stock Journal. Created and posted by Odoo when the consumption transfer is validated.

**B. Automated valuation, location accounts = 216100 (reserve policy).** The same use is charged to the reserve directly; no utilization is needed:

| Account | Debit | Credit |
|---|---|---|
| 216100 Warranty Provision / Reserve | 1,200 | |
| Stock Valuation (category) | | 1,200 |

**C. Reserve utilization (expense policy, case completed).** Eligible 1,200, posted reserve 5,000. Finance clicks **Create Reserve Utilization Draft**, reviews and posts:

| Account | Debit | Credit |
|---|---|---|
| 216100 Warranty Provision / Reserve | 1,200 | |
| 625100 Warranty Expense | | 1,200 |

Journal: Warranty Accounting Journal; Warranty Reserve Movement = Utilization; linked to the case.

**D. Vendor recovery.** Claim accepted 600; Accounting posts the draft vendor credit note:

| Account | Debit | Credit |
|---|---|---|
| Vendor (payable) | 600 | |
| 450100 Vendor Recovery | | 600 |

Eligible for utilization becomes 1,200 − 600 = 600 (the recovered part is not charged to the reserve).

**E. Manual valuation (UAT today).** Parts used: no entry. The cost is on the case (Material Cost tab, Case Cost Breakdown, cost report). The parts cost is not in 625100, so reserve utilization finds nothing to apply for parts ("Only cost posted to Warranty Expense counts"); Finance applies the reserve in its period-end process if its policy requires it.

## 4. Reserve utilization: warranty-specific controls (kept)

- Created only by an Accounting Bookkeeper or Administrator from a **completed or closed** case; never at Close Case, never automatic.
- **Eligible** = covered parts cost posted to Warranty Expense by Odoo's stock entries of the case's usage (uses minus reversals, per request line), minus posted vendor recovery of the same line (capped), goodwill only when **Goodwill Uses the Reserve** is on, approved subcontract bill lines posted to Warranty Expense only when **Subcontract Cost Uses the Reserve** is on, minus utilization already made.
- **Available** = posted balance of the reserve account (now and at the entry date, the lower) minus other unposted utilization drafts.
- Amount = the lower of the two; shortfall recorded on the case with a To-Do.
- One draft per case (database index); recalculated when Finance posts; lock dates respected (first open day); lines and links cannot be changed; never deleted (cancel instead); the standard **Reverse** of a posted utilization is capped and posted by Finance only.
- Reported in Reports > Warranty Provision / Reserve.

## 5. Configuration (frontend, Finance)

1. **Settings > Warranty Management > Warranty Accounting > Journal and Accounts:** Warranty Accounting Journal, Warranty Expense, Warranty Provision / Reserve (already set on UAT: 625100, 216100). Vendor Recovery Account under Vendor Claims (450100).
2. **Warranty Reserve Utilization** (same page): Subcontract Cost Uses the Reserve, Goodwill Uses the Reserve (both off by default); **Accounting Configuration Status** (read only) shows what is missing and how covered parts are accounted.
3. **Only if Finance uses automated valuation for spare parts** (a Finance decision, never done by the module): Inventory > Configuration > Product Categories (Inventory Valuation = Automated, stock accounts, stock journal), and Inventory > Configuration > Locations > **Warranty Consumption**: Stock Valuation Account (Incoming) and (Outgoing) = 625100 (expense policy) or 216100 (reserve policy).

Rights are unchanged: configuration needs Settings **and** Accounting Administrator; posting needs Accounting Bookkeeper or Administrator.

## 6. What was removed and why

| Removed (18.0.1.7.x) | Why it is not needed | Standard control that replaces it |
|---|---|---|
| Custom draft Dr 625100 / Cr Cost Recognition per Used record, Pending Verification, Verify Cost, Recheck, reversal drafts | A second, custom recognition of stock cost next to Odoo's own valuation | Standard stock accounting (section 3); actual cost from valuation layers |
| Warranty Parts Expense Accounting switch, Accounting Effective Date | Only controlled the removed process | none needed |
| Opening Stock Entry, Opening Stock Verified, Unbilled Receipts Reviewed, Period-end Stock Adjustment Confirmed | Existed only to make the custom process safe under manual valuation | Finance's standard stock valuation, period-end adjustment and lock dates |
| Cost Recognition Account (Part 8.3) | Its only use was the removed process | none needed |
| Menu Warranty Parts Expense Review, Recheck action, Verify Cost wizard | Same | Accounting > Accounting > Warranty > **Warranty Reserve Utilization** remains |

## 7. Migration impact

- UAT read 2026-11-07: the removed fields are empty; no parts-expense or utilization entry exists; all product categories use manual valuation; the Warranty Consumption location has no valuation accounts. **No data to convert.**
- Pre-migration (`migrations/18.0.1.8.0/pre-migrate.py`): any former parts-expense entry (none on UAT) is kept as an ordinary journal entry and listed in the log; two obsolete unique indexes are dropped; the outdated warranty view records are removed and loaded again from the module.
- Columns of removed fields stay in the database (standard Odoo; harmless). The empty table of the removed Verify Cost wizard also stays.
- Trial upgrade of a UAT copy (`wt_f7_mrf13`, mrf 18.0.1.10.2 → 18.0.1.10.4, accounting 18.0.1.7.0 → 18.0.1.8.0): cases 62, requests 13, request lines 19, usage 14, done stock moves 261, valuation layers 203 / 47,507.00, journal entries (draft 7, posted 47), posted lines 113, sales orders, vendor claims 3, approval history 24, attachments 1,462, MRF/000013 (Approved, round 1, approval signature) and S00098 (Sales Order 4,600) **identical before and after**.
- No Figure 7 operational step changes: Material Request, approval, quotation, issue, usage, return, closure and vendor claim behave as before. MRF/000013 needs no new manual test.
