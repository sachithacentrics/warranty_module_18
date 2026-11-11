> **SUPERSEDED on 2026-11-07 by `figure7_accounting_integration.md` (module 18.0.1.8.0).** The custom parts-expense process described here was removed: covered spare parts now use standard Odoo stock accounting. Kept for history only; do not configure or test from this document.

# Warranty Parts Expense Accounting: Finance setup, security configuration and safe UAT upgrade

Module: `warranty_management_accounting` **18.0.1.7.1** (Warranty Parts Expense Accounting; 18.0.1.7.1 = business terminology on screens, no behaviour change), built on the Figure 7 versions mrf 18.0.1.10.0 and repair 18.0.1.7.2.

Status (2026-11-07):
- Implemented and tested on the isolated database `wt_p7_s2` only. **Warranty Parts Expense Accounting is off.**
- UAT (`warranty_management_18_4`) is unchanged: mrf 18.0.1.9.14, repair 18.0.1.7.1, accounting 18.0.1.6.4.
- The rules are in `figure7_b2_finance_checklist.md`; the evidence and examples are in `figure7_accounting_design.md`.

**Do not switch Warranty Parts Expense Accounting on in UAT until Finance has approved decisions D-F1 to D-F13.** This document never makes those decisions.

## 1. Frontend Finance configuration (in this order)

Each step is a manual action in the frontend. The system only checks; it never creates an account, posts an opening entry or changes a category.

| # | Who | Menu | Action |
|---|---|---|---|
| C1 | Finance | Accounting > Configuration > Chart of Accounts | Create or choose the **Cost Recognition Account** (D-F1). Type **Cost of Revenue** or **Expenses**; company 1. It must be different from 625100, 216100 and 450100, and from any stock valuation / interim account. **Not 600000** (it holds no spare-part cost; see the design document, section 2) |
| C2 | Finance | Inventory > Configuration > Product Categories > category > Account Properties | Set **Expense Account** = the C1 account on every category in scope (D-F2), for example *All / Warranty Spare Parts*. It applies to future bills only. Keep **Inventory Valuation = Manual** (do not switch to Automated) |
| C3 | Finance | Accounting > Accounting > Journal Entries > New | Post the **opening stock entry** (D-F3): Dr the inventory asset account Finance chooses, Cr the account Finance chooses, for the stock value at the opening date (UAT valuation report: 47,507.00). Post it |
| C4 | Finance | Purchase > Orders, filter *To Invoice* | Review the receipts not billed at the opening date (UAT: P00013, Compressor Relay 2 × 1,200) and decide their treatment (D-F4: accrual in C3, or excluded from C3) |
| C5 | Finance | Finance procedure (outside Odoo) | Agree that the **period-end stock adjustment** posts the net change of stock value to the C1 account, and that warranty usage (moves to *Warranty Consumption*, an inventory-adjustment location) is **not** booked again as an inventory loss |
| C6 | Finance | – | Decide the **Accounting Effective Date** (D-F5): on or after the C3 date, not in a locked period. Usage before it is never posted as warranty parts expense |
| C7 | Finance | Settings > Warranty Management > Warranty Accounting > Journal and Accounts; Vendor Claims > Recovery Account | Check: journal **MISC**, Warranty Expense **625100**, Warranty Provision / Reserve **216100**, Cost Recognition = C1, Vendor Recovery **450100** |
| C8 | Administrator | Settings > Users & Companies > Users | Security corrections (section 2) |
| C9 | User with Settings **and** Accounting Administrator rights | Settings > Warranty Management > Warranty Accounting > **Warranty Parts Expense Accounting** | Fill **Accounting Effective Date** and **Opening Stock Entry** (the posted C3 entry). Tick **Opening Stock Verified**, **Unbilled Receipts Reviewed** and **Period-end Stock Adjustment Confirmed** (each records who and when). Leave **Subcontract Cost Uses the Reserve** and **Goodwill Uses the Reserve** off unless Finance approved D-F8 / D-F7. Check **Accounting Configuration Status** (after Save). Only then tick **Warranty Parts Expense Accounting** and Save |

**What the system refuses (server-side):**
- Switching Warranty Parts Expense Accounting on while anything in C1, C3, C6, C7 or C9 is missing. The message lists every missing item.
- A Cost Recognition Account equal to Warranty Expense, Provision or Recovery, a stock account, or an account of another company.
- An opening entry that is not posted, belongs to another company, or is dated after the start date.
- A start date in a locked period, when the date is set.
- Changing the accounts, journal, start date, opening entry or confirmations while Warranty Parts Expense Accounting is on. Switch it off first; the same settings save may switch it off and change them.
- Changes by users without both Settings and Accounting Administrator rights.

**Information shown, not blocking:**
- Categories of covered parts whose expense account is not the Cost Recognition Account. Their usage waits in Pending Verification.
- Receipts not fully billed.

## 2. Security configuration (manual; nothing is changed automatically)

### What the code enforces on the server

| Action | Required right | Others |
|---|---|---|
| Configure Warranty Parts Expense Accounting and reserve policy | Settings **and** Accounting Administrator | AccessError |
| Post a warranty parts expense entry, a warranty parts expense reversal or a utilization | Accounting **Bookkeeper** or **Administrator** | AccessError, also through RPC |
| Create a reserve utilization draft; Recheck Expense Entry; Verify Cost | Bookkeeper or Administrator | AccessError |
| Change accounts, amounts or lines of a warranty parts expense / utilization entry; delete it | Nobody | UserError ("cancel it instead"; "never deleted") |
| Change the date or label of a draft | Users who can edit journal entries | Allowed |
| Create an entry with warranty links by hand | Nobody | UserError |
| Read Warranty Parts Expense Accounting fields, the Warranty Accounting page, the menus | Accounting Read-only / Invoicing and above | Hidden, and field access is refused |

Technicians, store and Helpdesk users record usage as before. The draft is created by the system on their behalf; they get no accounting right.

### UAT membership found (read-only, 2026-11-07) and the required correction

| User | Now | Required for Figure 7 accounting UAT |
|---|---|---|
| `main_tech` (technician) | Accounting Administrator | **Remove** accounting rights (none), or Invoicing only if Finance confirms it is needed |
| `support_tech` (technician) | Accounting Administrator | Same as `main_tech` |
| `demo` | Bookkeeper | Confirm it is intended; otherwise none |
| `approval` | Administrator | Keep only if this is the Finance approver |
| Finance user(s) who post | – | Bookkeeper (or Administrator) |
| User who configures Warranty Parts Expense Accounting | – | Accounting Administrator **and** Settings (Administration) |

How to correct a user:
1. Go to Settings > Users & Companies > Users > the user > Access Rights.
2. Under *Accounting*, choose the right level (empty = no access).
3. Save, and log the change in the UAT record.

Separation of duties: the user who records usage or approves materials should not be the user who posts the entries.

## 3. Behaviour summary (for UAT and Finance)

| Event | Warranty Parts Expense Accounting off (default) | Warranty Parts Expense Accounting on |
|---|---|---|
| Used, Covered or goodwill line, all checks pass | Nothing (status **Not Active**) | One **draft** Dr 625100 / Cr Cost Recognition at the valuation value, dated the move date (first open day if locked) |
| Used, a check fails | Nothing | **Pending Verification** with the reason; Finance fixes it and clicks **Recheck Expense Entry**, or **Verify Cost** for stock added by inventory adjustment |
| Used before the start date | Nothing | **Before Effective Date**: never posted as warranty parts expense |
| Installed / Customer Keeps (Not Covered), unused or customer return, Cancel Remaining | Nothing | Nothing (**Not Applicable**) |
| Automated-valuation product | Standard Odoo | No warranty parts expense entry (**Not Applicable**: the standard stock entry records the cost) |
| Usage reversed | Nothing | Draft **cancelled**; a posted entry gets one draft reversal |
| Reserve utilization | Finance button only | Same: draft Dr 216100 / Cr 625100 = min(eligible, available), rechecked at posting |
| Vendor recovery | Unchanged (Dr Payable / Cr 450100) | Unchanged; deducted from eligibility |

## 4. Safe future UAT upgrade (steps only; not executed)

The PyCharm "odoo18" run configuration starts with `-u`, so **restarting it upgrades UAT**. Only the user does that, after the steps below and explicit approval.

1. **Approvals:** Finance decisions D-F1 to D-F13 approved in writing; the user approves the upgrade window. Warranty Parts Expense Accounting stays off after the upgrade either way.
2. **Freeze:** agree a time with no UAT users; note any open transactions.
3. **Fresh backup** to `D:\ODOO\odoo18\backups\warranty_management_18_4_before_f7_b2_<date>`:
   - `pg_dump -Fc` of `warranty_management_18_4`;
   - a copy of the filestore `D:\ODOO\odoo18\sessions\filestore\warranty_management_18_4`;
   - record counts (cases, MRFs, MRF lines, usage records, account moves by state, stock moves, valuation layers) and key values (216100, 625100, 600000 and 450100 balances, the stock valuation total, module versions).
4. **Test restore:** restore the dump to a new database (for example `wm18_4_f7b2_check`) and copy its filestore; compare the counts.
5. **Trial upgrade on the copy**, never on UAT:
   - run `odoo-bin -c odoo.conf -d wm18_4_f7b2_check --http-port=8399 --max-cron-threads=0 --stop-after-init -u warranty_management_mrf,warranty_management_repair,warranty_management_accounting`;
   - the log must have no ERROR and no new warnings.
6. **Compare the copy with the backup values:**
   - counts unchanged;
   - account balances unchanged;
   - **no** new journal entry;
   - `warranty_b2_enabled` false;
   - every existing usage record shows Not Active / Not Applicable;
   - versions mrf 18.0.1.10.0, repair 18.0.1.7.2, accounting 18.0.1.7.0.
7. **Smoke test on the copy:**
   - open an MRF, a case (Warranty Accounting page as admin), Settings > Warranty Parts Expense Accounting (readiness Not ready), and Accounting > Accounting > Warranty menus;
   - record one usage on a test case and confirm no entry.
8. **Report** the trial results to the user and wait for go / no-go.
9. **Upgrade UAT:** on go, the user stops and restarts the PyCharm server (its `-u` upgrades UAT). Verify the log, the versions, the counts and that Warranty Parts Expense Accounting is off.
10. **After the upgrade:** apply the security corrections (section 2), then the Material Approval Rules (Figure 7 guide, section 4). Run Scenarios A to E with Warranty Parts Expense Accounting off. Run Scenario F only after the Finance configuration (section 1) is done.
11. **Rollback (if needed):**
    - stop the server;
    - restore the step 3 dump and filestore;
    - put the previous module sources back (`rollback_f7_src` for the pre-Figure-7 state; `rollback_b2_src/pre_b2_accounting` for accounting 18.0.1.6.5);
    - restart.
12. Keep every backup, copy and dump until the user approves cleanup.

## 5. Known limitations

- **Readiness text:** it reflects the saved configuration; save first, then read it.
- **Opening stock:** the system checks that the entry exists, is posted, belongs to the company and is dated correctly. It cannot check that its amount equals the stock value. That is Finance's verification (the "Opening Stock Verified" tick).
- **Inventory-adjustment check:** it compares stock move dates with the day after the opening entry date in server time (UTC). An adjustment made on the opening date itself is treated as part of the opening stock.
- **Recovery deduction:** it uses the posted recovery of the claim lines of the same request line, capped at that line's posted warranty parts expense cost. Recovery on replacement units (Part 7) is not part of Warranty Parts Expense Accounting and does not reduce parts eligibility.
- **Subcontract eligibility:** it counts only approved subcontract cost lines whose posted bill lines use the Warranty Expense account. Bills on other accounts never count, even with the policy on.
- **Utilization reversal:** case reopened, or a source reversed after utilization was posted. Finance uses the standard Reverse button on the utilization entry; posting it is capped at the original amount. Nothing is automatic.
- **Shortfall To-Do:** it goes to the Finance user who created the utilization.
- **Multi-currency:** entries are in company currency at the valuation value (the valuation layers are in company currency).
