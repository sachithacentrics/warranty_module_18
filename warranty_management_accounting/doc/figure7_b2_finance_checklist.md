> **SUPERSEDED on 2026-11-07 by `figure7_accounting_integration.md` (module 18.0.1.8.0).** The custom parts-expense process described here was removed: covered spare parts now use standard Odoo stock accounting. Kept for history only; do not configure or test from this document.

# Warranty Parts Expense Accounting: Finance configuration checklist and journal-entry validation rules

Status (2026-11-07):
- Implemented as designed in `warranty_management_accounting` 18.0.1.7.0 (`models/warranty_b2_accounting.py`, tests `test_figure7_b2.py`).
- Built and tested on the isolated database `wt_p7_s2` only, and **off by default**. Not on UAT.
- Two differences from this design:
  - The start date is checked against lock dates when it is set, so later period closings don't stop Warranty Parts Expense Accounting.
  - Subcontract and goodwill reserve eligibility are company policy switches, both off by default (D-F7, D-F8).
- Setup, security and upgrade steps: `figure7_b2_setup_and_upgrade.md`.
- The Finance decisions D-F1 to D-F13 are still open.

This document builds on `figure7_accounting_design.md` revision 2 (UAT evidence, worked examples).

User directions (2026-11-07):
- Warranty Parts Expense Accounting (with manual valuation); no category switches to automated valuation.
- Accounts: 625100 Warranty Expense, 216100 Warranty Provision, 450100 Vendor Recovery.
- **Not** 600000.
- The Cost Recognition Account is mandatory company configuration. It is validated, never created or chosen by the system.
- Finance confirms the opening stock and periodic adjustment treatment before Warranty Parts Expense Accounting can be switched on.
- No historical backfill.
- No automatic permission changes.
- Nothing is activated or posted before the final policy approval.

## 1. Finance configuration checklist (company 1, in this order)

Every item is done by Finance or the administrator through the frontend. The system only checks.

| # | Item | Who | Where | Checked by the system at activation |
| --- | --- | --- | --- | --- |
| C1 | **Choose or create the Cost Recognition Account**: the account where spare-part purchase cost is recognized under periodic valuation | Finance | Accounting > Chart of Accounts | Type Expenses or Cost of Revenue; belongs to the company; not deprecated; different from Warranty Expense, Warranty Provision, Vendor Recovery, any stock / interim account and the journal's default account |
| C2 | **Set it as the Expense Account of every category used on covered lines** (UAT: All / Warranty Spare Parts, All / Consumable for Bolt). Applies to future bills only; existing bills are not changed | Finance | Inventory > Product Categories > Account Properties | Each category in scope has Expense Account = C1 and Manual (periodic) valuation. Products with their own expense account must also use C1 |
| C3 | **Opening stock entry**: post one entry that puts the existing stock on the balance sheet (UAT valuation report 47,507.00; ledger 0). Dr Inventory asset account (Finance's choice), Cr the account Finance chooses (opening balance / equity or C1) | Finance | Accounting > Journal Entries | The entry is selected on the company, **posted**, of the company, and dated on or before the Accounting Effective Date |
| C4 | **Receipts not billed at the opening date** (UAT: P00013, Compressor Relay 2 × 1,200). Decide how they are treated so the later bill (to C1) does not double the opening stock: accrual in C3, or exclude them from C3 | Finance | C3 entry / Purchase | Activation lists the company's receipts with quantity received but not billed, for Finance to tick as reviewed |
| C5 | **Period-end stock adjustment procedure**: net change of stock value posted to C1, Dr / Cr Inventory, at least every period end. Warranty usage moves (Warranty Consumption is an inventory-adjustment location) are **not** booked again as inventory losses | Finance | Accounting procedure | Finance ticks the confirmation; their name and the date are recorded |
| C6 | **Accounting Effective Date**: usage on or after this date is posted as warranty parts expense; earlier usage is never posted as warranty parts expense (no backfill) | Finance | Settings > Warranty Accounting | On or after the C3 date; not inside a locked period |
| C7 | Existing warranty settings: journal MISC (Miscellaneous, company 1), Warranty Expense 625100, Warranty Provision 216100, Vendor Recovery 450100 | Finance | Settings > Warranty Accounting | Existing checks: journal type and company, account types, Expense ≠ Provision |
| C8 | **Security correction** (section 5) | Administrator | Settings > Users | Not checked automatically; reported on the settings page |
| C9 | **Activate Warranty Parts Expense Accounting**: Settings > Warranty Accounting > "Warranty Parts Expense Accounting" | Settings + Accounting Administrator (existing rule) | Settings | All of C1 to C7 valid; the refusal names every missing item |

**Switching Warranty Parts Expense Accounting off** stops new drafts. Existing drafts and posted entries are kept. Changing C1, C3 or C6 while Warranty Parts Expense Accounting is on is refused: Finance switches Warranty Parts Expense Accounting off first.

## 2. Warranty Parts Expense Status of each usage record

Each covered Used record gets a visible status for Finance, so nothing is created silently or skipped silently.

| Status | Meaning |
| --- | --- |
| Not applicable | Not Covered, unused / customer return, Cancel Remaining, Installed, Customer Keeps |
| Before Effective Date | Usage before the start date (the 3,403.00 history), or Warranty Parts Expense Accounting is off |
| Pending verification | A rule in section 3 fails; the reason is shown. Finance clicks **Recheck Expense Entry** after correcting it |
| Draft created | Draft warranty parts expense entry exists |
| Posted | Finance posted it |
| Cancelled | The usage was reversed while the draft was unposted |
| Reversed | The usage was reversed after posting; a draft reversal exists |

## 3. Journal-entry validation rules

### 3.1 Draft warranty parts expense entry (created at Confirm Material Usage, or by Recheck Expense Entry)

A draft is created only if **every** rule passes. Otherwise the status is Pending verification, with the reason.

| # | Rule | Reason shown when it fails |
| --- | --- | --- |
| V1 | Warranty Parts Expense Accounting is on for the request's company and every configuration check (C1–C7) still passes | "Warranty Parts Expense Accounting configuration incomplete: …" |
| V2 | Usage type Used, state Done, on a Covered line or a goodwill line. Never Not Covered | (Not applicable) |
| V3 | Usage date ≥ Accounting Effective Date | (Before Effective Date) |
| V4 | Exactly one validated stock move to the company's Warranty Consumption location | "No validated consumption move" |
| V5 | The move has a stock valuation layer with a value below 0, in company currency, and **no journal entry** (an automated product posts its own) | "No valuation value" / "Valued in real time: no warranty parts expense entry" |
| V6 | The product's category uses Manual valuation, and its expense account (product, else category) is the Cost Recognition Account. **This proves bills of the product reach the Cost Recognition Account** | "Purchase cost of this product is not recognized in the Cost Recognition Account (account X)" |
| V7 | No stock of the product entered from an inventory-adjustment location after the opening stock date, except reversals of warranty usage. Stock found by an adjustment has no recognized purchase cost | "Stock added by inventory adjustment on <date>: Finance review" |
| V8 | No other non-cancelled warranty parts expense entry exists for this usage (also enforced by a unique database index) | (Draft created: the existing one is shown) |
| V9 | Accounts: Dr Warranty Expense, Cr Cost Recognition. Amount = −valuation value, rounded to the currency, > 0 | n/a (built from configuration) |
| V10 | Date = usage move date. If that date is locked, the first unlocked day, with a chatter note naming the usage date | n/a |

**Content of the entry:**
- Journal: warranty journal.
- Reference: "Warranty parts: <request> / <case> / <product>".
- One debit line and one credit line, carrying the product, quantity, case, request, request line, usage record and a Goodwill flag.
- The usage record, request and case each show a link and a chatter note.

**Protection:**
- The accounts, amounts and links of a generated draft can't be changed; Finance may change only the date and the label.
- A draft is cancelled, never deleted.
- Manual entries never get warranty parts expense links.

### 3.2 Posting a warranty parts expense entry (Finance)

| # | Rule |
| --- | --- |
| P1 | Standard Odoo posting rights (Bookkeeper or Administrator) and lock dates |
| P2 | The source usage is still Done, not reversed. Otherwise posting is refused: "Usage reversed: cancel this entry" |
| P3 | The accounts and amount still equal the values of section 3.1 (they can't drift) |

### 3.3 Reversal of a usage (Reverse Consumption, existing workflow)

| Warranty Parts Expense Status | Action |
| --- | --- |
| None / Pending | Nothing; status becomes Not applicable |
| Draft | Draft **cancelled**; status Cancelled |
| Posted | **Draft reversal**: Dr Cost Recognition / Cr Warranty Expense, same amount, linked to the original (`reversed_entry_id`). At most one reversal per entry; status Reversed. Finance posts it |

The stock move back to the technician location stays as built. Unused and customer returns never create an entry.

### 3.4 Reserve utilization draft (controlled by Finance)

A Finance button **Create Reserve Utilization Draft** on a closed or completed case, also available for several cases from a list. It is visible to Accounting Bookkeeper and Administrator. Nothing is created automatically at Close Case: the case only shows the utilizable amount.

| # | Rule |
| --- | --- |
| U1 | The case is closed or completed and belongs to the company; Warranty Parts Expense Accounting configuration is valid |
| U2 | **Eligible** = posted Warranty Expense lines with a warranty parts expense link to the case (covered, not goodwill), minus their posted reversals, minus posted vendor credit notes of the case's claims (450100), minus existing non-cancelled utilization of the case. Draft warranty parts expense entries are excluded; the case shows "x draft warranty parts expense entries not posted" |
| U3 | **Available** = posted credits − posted debits on 216100 for the company up to the entry date, minus every non-cancelled unposted utilization draft of the company |
| U4 | Amount = min(eligible, available), and it must be > 0. When eligible > available, the shortfall stays in Warranty Expense; the message and a Finance To-Do name it. The reserve never goes negative |
| U5 | Entry: Dr 216100 / Cr 625100, Warranty Reserve Movement = Utilization, linked to the case, one non-cancelled utilization per case. Its lines are locked like a warranty parts expense entry |
| U6 | **At posting**, U3 is recalculated without this draft. If the amount now exceeds the posted reserve, posting is refused |
| U7 | Case reopened, or a warranty parts expense source reversed after utilization was posted: Finance creates a draft reversal of the utilization, capped at the original. Nothing is automatic |
| U8 | A vendor recovery posted after utilization: no automatic entry; Finance decides any reserve release (manual entry, Movement = Release) [Approved F8] |

**Why expense is never counted twice:**
- The provision (8.6) recognized the expense at sale.
- Warranty Parts Expense Accounting puts the actual cost in 625100, and utilization moves exactly that cost out of 625100 into 216100.
- Utilization is capped at posted warranty parts expense cost net of recovery, and at the posted reserve.

### 3.5 Goodwill

- Goodwill usage gets the same warranty parts expense entry, with the Goodwill flag on both lines (or a separate Goodwill Expense account if Finance chooses, decision D-F6).
- Goodwill is excluded from utilization eligibility unless Finance decides otherwise (D-F7). The Warranty Cost report shows goodwill separately.

### 3.6 Vendor recovery

Unchanged: the existing claim and draft credit note, Dr Payable / Cr 450100, posted by Accounting. It is used only as a deduction in U2.

## 4. Case-level traceability

The case, request and usage list show a breakdown with drill-down to the entries:
- Material cost (operational);
- warranty parts expense draft and posted;
- Pending verification, with reasons;
- recoveries posted;
- utilization draft and utilization posted;
- shortfall.

The Finance menu "Warranty Parts and Reserve Entries" lists every warranty parts expense and utilization entry with these links. The existing Case Cost Breakdown tab is not changed.

## 5. Security configuration to correct manually (UAT, not changed by the system)

Current UAT membership (read-only, 2026-11-07):

| Accounting group | Users |
| --- | --- |
| Administrator | admin, approval, **main_tech**, **support_tech** |
| Bookkeeper | admin, approval, **demo**, main_tech, support_tech |
| Invoicing | admin, approval, demo, main_tech, support_tech |
| Read-only | admin, approval, demo, main_tech, support_tech |

Required before Figure 7 accounting UAT:

| User / role | Required Accounting right | Reason |
| --- | --- | --- |
| main_tech, support_tech (technicians) | **None**, or Invoicing only if Finance confirms they need it | Today they can post and change any journal entry, including warranty drafts and the reserve |
| demo | Confirm whether Bookkeeper is intended; otherwise none | Bookkeeper can post |
| approval | Confirm whether this is the Finance approver; keep Administrator only if so | |
| Finance user(s) who post | Bookkeeper (or Administrator) | Posts warranty parts expense and utilization drafts, creates utilization drafts |
| Finance user who configures Warranty Parts Expense Accounting | Accounting Administrator **and** Settings (existing rule) | C1–C9 |

Separation of duties needs at least one Finance user other than the technicians and requesters. Material approval rules are unaffected.

## 6. Decisions still requiring Finance approval

| # | Decision | Recommendation |
| --- | --- | --- |
| D-F1 | Which account is the Cost Recognition Account (C1), and its type | A new dedicated account, for example "Spare Parts Purchases / Change in Inventory", type Cost of Revenue |
| D-F2 | Categories in scope and changing their Expense Account to C1 (C2), which also changes where future bills of those categories post | Warranty Spare Parts and Consumable (Bolt), or move Bolt to Warranty Spare Parts |
| D-F3 | Opening stock entry: inventory asset account, counter account, date (C3) | Finance's choice; the system only checks that the entry is posted and dated |
| D-F4 | Treatment of receipts not billed at the opening date (C4, P00013) | Accrual in the opening entry |
| D-F5 | Accounting Effective Date (C6) | First day of the next open period after C3 |
| D-F6 | Goodwill account | 625100 with the Goodwill flag |
| D-F7 | Goodwill reserve-eligible | No |
| D-F8 | Subcontract bills of the case posted to 625100: reserve-eligible | Yes, if posted to 625100 and linked to the case. Otherwise only parts |
| D-F9 | Stock found by inventory adjustment after the opening date (V7): hold for review, or treat as normal periodic stock | Hold for review (Pending verification) |
| D-F10 | Locked usage date: draft on the first open day, or Finance re-dates manually | First open day, with a note |
| D-F11 | Utilization: Finance button only (recommended, as asked), or an automatic draft at Close Case | Finance button |
| D-F12 | Historical 3,403.00 | Not posted as warranty parts expense. Finance may book a manual entry; the system lists it under "Before Effective Date" |
| D-F13 | Security corrections in section 5 | As listed |

**Final accounting-policy approval of D-F1 to D-F13 is needed before Warranty Parts Expense Accounting is switched on or any warranty parts expense entry is posted.**

The code can be built and tested on `wt_p7_s2` with Warranty Parts Expense Accounting **off** by default, once you approve the implementation.

## 7. What stays unchanged

- Figure 7 non-accounting behaviour (approval, Not Covered quotation, stock, partial issue, Repair Order request, Case Cost Breakdown).
- The 8.6 provision entry.
- Vendor claims and credit notes.
- Figures 3–6, Part 7 and Part 8 closure.
- Existing permissions.

With Warranty Parts Expense Accounting off, behaviour is exactly as today (the standard accounting route).
