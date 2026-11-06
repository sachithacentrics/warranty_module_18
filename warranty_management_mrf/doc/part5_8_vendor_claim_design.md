# Phase 5.8 – Vendor / Manufacturer Reimbursement Claims – Design (revision 2)

| Status | Revision 2 – V-1 – V-18 **approved 2026-10-27 with the corrections of section 0**; implemented (18.0.1.8.0) on `wt_p5_mrf`, see `part5_design_decisions.md` Phase 5.8. |
|---|---|
| Module | `warranty_management_mrf` only (inheritance + new claim models); `material_purchase_requisitions`, Parts 1–4, AMC unchanged; no new bridge needed (claims are built on MRF lines and their 5.7 actual cost) |
| Database | disposable `wt_p5_mrf` for development; `warranty_management_18_4` untouched |

## 0. Revision 2 – approved corrections (they override the rows below where they differ)

| # | Correction | Implementation |
|---|---|---|
| C1 | Eligibility: Customer Paid never; Covered / Goodwill never automatic; verified cost, consumed qty, supplier / manufacturer responsibility; goodwill flagged and reviewed; serial / lot traceability; no duplicate or overlapping claims **including concurrent submissions**. | V-1, V-2, V-5, V-7; goodwill claims always need the Finance level too; claim lines lock their MRF lines (row update) at create / submit / approve, so a concurrent transaction is serialised and re-checked. |
| C2 | Product *Warranty Claim Partner* approved; actual supplying vendor where identifiable; fallback; **auditable override**; one partner per claim; supplier warranty details and **expiry warnings** shown to the approver. | Proposal order **actual supplier first** (lot purchase order, else the MRF line's purchase order), then *Warranty Claim Partner*, then price-list vendor; a partner different from the proposal needs an override reason (tracked); per line: supplier warranty months, reference date (purchase / receipt), expiry and warning. |
| C3 | Approval separate from the MRF matrix; named Warranty and Finance approvers; configurable threshold; segregation of duties; history; server checks. | V-8 as designed (company lists + threshold; goodwill also needs Finance). |
| C4 | Evidence required before sending; separate from the Field Service worksheet attachment setting. | Company *Claim Evidence Required* (own setting). |
| C5 | Accounting: implement the standard **vendor credit note** workflow; direct reimbursement / claim-receivable recovery documented as **remaining SRS scope (Part 8)**; **no fallback to the product expense account** – a configured company *Recovery Account* is required before a credit note is created; nothing posted automatically; only Accounting users post / reconcile; manual valuation kept. | V-12 / V-13 corrected; section 9. |
| C6 | Claimed, Accepted, Recovered, Settled, Outstanding separate; partial acceptance / settlement; one credit note over several claims within its amount; no over-allocation; cancelled (and reversed) credit notes excluded; company currency; a credit note is **not** a cash receipt. | V-14: *Recovered* = posted, not reversed credit-note allocations; *Settled* = the reconciled share of the credit note (offset against bills or a refund payment); no cash assumption. |
| C7 | Reversal after submission → **Over-claimed**; blocks recovery allocation and closure; posted recovery documents only corrected by accounting; rejection / cancellation / re-claim / write-off history kept. | V-15 / V-16; allocations of posted credit notes are removed only by Accounting users with a reason (archived, never deleted); the credit note itself is never changed by the bridge. |
| C8 | Menus Warranty → Vendor Claims, Warranty → Reports (5.9), Accounting / Invoicing shortcut; links to case, job, MRF lines and accounting documents; strict technician / cost access. | Section 6. |

## 1. Sources

| Requirement | SRS / mapping |
|---|---|
| Claim record linked to vendor credit note or claim receivable / recovery entry; recovery status visible on the case | SRS §2.10 b9 |
| *Reimbursement Claim* Many2one, sample `VCL/00012`, "Tracks cost recovery from vendor/manufacturer" | §10.7 (p. 66) |
| MRF menu: "approval, issue, return, **reimbursement** and actual-cost status" | §6 (p. 19) Material Requests |
| Menu **Warranty Management → Vendor Claims**: "Recover warranty cost from supplier/manufacturer where applicable" | §6 (p. 19) |
| Scenario 15 *Vendor warranty claim / recovery*: "Create vendor claim from warranty case or replacement. Track manufacturer/supplier, claim amount, credit note and recovery status." Configuration: "Vendor claim enabled; claimable parts; recovery accounts" | §12 (p. 71), §12.1 must-have (p. 73) |
| Scenario 30 Separate MRF: "Approval, reimbursement, cost and accounting" | §2.14 (p. 12) |
| Vendor / manufacturer replacement of a defective unit → vendor claim linked to the replacement | §11.1 (replacement record – later Part) |
| Vendor Claim Recovery Report: Vendor, claim status, amount | §15 (p. 76) – delivered in 5.9 |
| Accountant: view … credit notes and vendor claims | §16 (p. 77) |
| Cost approval matrix: Vendor/manufacturer reimbursement → **Warranty/Finance approval** → "Create claim and record vendor credit/recovery" | §16.1 |
| "Vendor warranty recovery: Track supplier credit note or reimbursement against vendor claim and warranty case." "Vendor/manufacturer reimbursement: Create reimbursement claim. Record vendor credit note against relevant vendor bill or a claim receivable/other recovery account based on accounting policy." | §17 |
| "Vendor recovery: if not in initial phase, capture claim reference and amount manually on warranty case" | §17 phasing (p. 79) |
| History of materials / accounting events, immutable audit | §2.13, §2.14 row 34, §16 audit trail |
| Mapping 5.8 (model `warranty.vendor.claim`, `VCL/`, credit-note link, T8.1 – T8.5), D13 (claim + manual credit-note link in 5.8, automated recovery accounting in Part 8) | `Part5_MRF_Integration_Mapping.md` |

## 2. Facts checked (read-only)

| Fact | Consequence |
|---|---|
| 5.7 gives per MRF line: bucket (Covered / Goodwill / Customer Paid / Pending), used qty, verified / unverified actual cost, reversed cost, approved snapshot. | Claim amounts are derived from 5.7, never re-computed differently. |
| Consumption entries keep serial / lot numbers (5.6); purchased parts keep PO lines (5.5); `stock.lot` knows its purchase orders (`purchase_stock`). | Vendor proposal and defective-serial evidence come from existing data. |
| Parts 1–4 have **no manufacturer / brand field**; products have vendor price lists (`seller_ids`). | A claim partner per product is needed (V-3). |
| Valuation **Manual (periodic)**; purchases are expensed by the vendor bill to the category expense account; 5.6 / 5.7 post nothing. | A vendor credit note (in_refund) reverses expense; nothing in stock changes (§5). |
| `warranty_management_18_4`: 2 vendor credit notes exist; Accounting app = Invoicing + `account_accountant` installed. | Standard credit notes, payments and reconciliation are available. |
| `warranty_management_18_4` already reports bridge version **18.0.1.7.0** (upgraded outside this session, most likely by the PyCharm start with `-u warranty_management,…`, which also upgrades dependent modules). | 5.8 will upgrade from 1.7.0. |

## 3. Workflow

```
5.7 actual cost (Covered / Goodwill, verified, claimable product)
  -> Create Vendor Claim (case / job / MRF)          eligible lines only, partner proposed, editable
  -> Draft: qty, amounts (<= actual cost), failure description, serials, evidence
  -> Submit for Approval -> Warranty approver (+ Finance above threshold)   [§16.1]
  -> Approved (snapshot) -> Mark Sent to Vendor (reference, date)
  -> Vendor response per line: Accepted / Partially Accepted / Rejected (+ reason)
  -> Accounting: Create Draft Vendor Credit Note (or link an existing posted one) -> accountant posts
  -> Recovered (posted credit notes) / Settled (credit note paid / reconciled)
  -> Close (fully recovered, or remainder written off with reason)
Rejected internally / by vendor / cancelled -> quantities claimable again (new claim, history kept)
```

## 4. Decision table

| ID | Topic | Recommended (safest) option | Alternatives | SRS |
|---|---|---|---|---|
| **V-1** | Eligibility | **Never automatic.** A line can be claimed only when: company *Vendor Claims Enabled*; product marked **Vendor Claimable** (§12 "claimable parts"); bucket **Covered or Goodwill**; **verified** actual cost > 0 (5.7); claimable qty > 0. A person creates the claim and it needs approval. Customer-paid lines are **not** claimable (the customer already paid: double recovery). | Include Customer Paid lines; claim unverified cost | §2.10 b9, §12 #15, user requirement |
| **V-2** | Goodwill lines | Claimable, but flagged *Goodwill* on the claim (vendors often refuse goodwill); approver sees it. | Exclude goodwill | §16.1 goodwill row |
| **V-3** | Responsible party | Proposal order: (1) product **Warranty Claim Partner** (manufacturer, new product field); (2) vendor of the purchase order that supplied the part (MRF purchase line, or the lot's purchase order for tracked parts); (3) first vendor price-list entry. Editable in Draft; **one partner per claim** (`Claim Type`: Vendor / Manufacturer). | Manual only | §12 #15 "manufacturer/supplier" |
| **V-4** | Supplier warranty period | Not computed in 5.8 (no reliable purchase date for untracked parts). Optional product field *Vendor Warranty (months)* shown as information; for lot / serial parts the receipt date is shown; the approver confirms eligibility. | Hard block on expired supplier warranty | – (not in SRS) |
| **V-5** | Claim lines and quantities | Lines from **MRF lines** (consumption basis): qty ≤ used qty (net of reversals) − qty on other active claims; serials = used serials of the line (tracked parts: one serial per unit, required). | Free lines without MRF | §10.7, mapping 5.8 |
| **V-6** | Claim amount | Default = qty × verified actual unit cost of the line (5.7); editable **down** only; never above the actual cost of the claimed qty (no labour / handling fees in Phase 5 → Part 8). Snapshot of the basis kept on the line. | Allow above cost with warning (mapping T8.4 "configurable warning") | §17 "Actual cost is locked from valuation", D12 |
| **V-7** | Duplicate prevention | A unit of an MRF line can be on **one active claim** only (Draft … Closed, except Rejected / Cancelled lines). Server-side check on create / write / approve; serial already claimed → refused. | Warning only | user requirement |
| **V-8** | Internal approval | §16.1 Warranty / Finance: company lists **Vendor Claim Approvers** (warranty) and **Vendor Claim Finance Approvers** + **Finance Approval Threshold**; claim ≥ threshold needs both; separation of duties (creator / submitter never approves); To-Dos; reject with reason. | Reuse the 5.3 MRF approval rules | §16.1 |
| **V-9** | Evidence | Before *Submit for Approval*: failure description, case reference, serials (tracked parts). Before *Mark Sent*: at least one attachment on the claim when company *Claim Evidence Required* is on (default **on**); MRF / case / job attachments listed as references. | Always optional | §2.13 / §16 attachments ("approval documents and rejection evidence") |
| **V-10** | Defective part return to vendor | Recorded only: *Defective Part Return Required* flag + optional return transfer reference / text. Physical old-part logistics are Repair / Replacement (Part 6+). | Create return pickings now | §11.2 (vendor return location) |
| **V-11** | Vendor response | Per line: Accepted amount (≤ claimed), reason; claim result Accepted / Partially Accepted / Rejected computed; vendor reference and response date; changes after the response only by Finance approvers with a reason (audit). | Header amount only | §12 #15 |
| **V-12** | Recovery document | **Standard vendor credit note (in_refund)** for every recovery (credit, cash refund via payment, offset against bills = standard reconciliation). *Create Draft Credit Note* (Accounting users): partner, one line per accepted claim line (product, accepted amount, account per V-13), reference `VCL/…`; **never posted by 5.8** – the accountant posts. Existing posted credit notes can be **linked** instead. | Misc. journal entry Dr Claim Receivable / Cr Recovery (Part 8 recovery accounting) | §17, §2.10 b9 |
| **V-13** | Recovery account | Company setting **Vendor Claim Recovery Account** used as default line account of the draft credit note; empty → the product's expense account (offsets the expensed purchase). | Always product expense | §12 #15 "recovery accounts" |
| **V-14** | Recovered vs settled | *Recovered* = Σ allocations of **posted** linked credit notes (untaxed, company currency). *Settled* = part of it whose credit note is paid / reconciled (payment state). A credit note can be allocated to several claims; Σ allocations ≤ its untaxed amount; Σ recovered ≤ accepted (more → refused, accountant decides). Cancelled / reset credit notes stop counting automatically. | 1 credit note = 1 claim | user requirement, §17 |
| **V-15** | Reversal / return after claiming | Claimed qty > net used qty (consumption reversed / returned later) → line flagged **Over-claimed**: Draft / Approved claims cannot proceed until corrected; Sent / answered claims get a To-Do for the claim owner and Finance (correct via vendor response or credit-note adjustment). Nothing is changed automatically. | Auto-reduce claims | user requirement |
| **V-16** | Rejected / corrected claims | Internal reject → Draft with reason (resubmit = new approval). Vendor rejection → lines released; the claim stays (history); a **new** claim may be created (same or other partner) referencing the earlier one. Close with remainder → *Write-off reason* (operational only, no posting). Claims with history are never deleted (Cancel with reason). | Reopen the same claim | §2.13 audit |
| **V-17** | Case / job display | Case and job: claims smart button; **Vendor Recovery** status (None / Claimed / Partially Recovered / Recovered / Rejected) and amounts (Claimed, Accepted, Recovered, Outstanding); Material Cost tab adds *Net Warranty Material Cost after Recovery* (5.7 values unchanged). | Status only | §2.10 b9 |
| **V-18** | Scope | Material (MRF) claims only. Claims for complete-unit replacements (§11) and labour / travel / subcontract recovery come with their Parts; manual claim reference on the case (§17 phasing) is not needed because claims exist. | – | D12, D13 |

## 5. Accounting and reimbursement handling (Manual valuation kept)

| Event | Stock / valuation | General ledger | Claim figures |
|---|---|---|---|
| Claim created / approved / sent / vendor answer | none | none | Claimed / Approved / Accepted |
| Draft credit note created from the claim | none | none (draft) | – |
| Credit note **posted** by the accountant | none | Dr Vendor payable (partner) / Cr Recovery account (or product expense) [+ tax per vendor] | Recovered + |
| Vendor refund received / offset against a bill | none | standard payment / reconciliation | Settled + |
| Credit note reset to draft / cancelled | none | standard reversal of its own entry | Recovered − (automatic) |

* 5.8 **creates no posted journal entry and no stock move**; the only accounting document it can create is a **draft** credit note on request by an Accounting user. One recovery mechanism (vendor credit note) → no duplicate posting; allocations prevent one credit note from recovering more than its amount and a claim from recovering more than accepted.
* Manual valuation is unaffected: the consumed part already left inventory (5.6); the credit note only reduces the expense (or books recovery income) – no inventory valuation entry.
* Taxes follow the vendor's credit note (standard); claim amounts are untaxed cost amounts; recovered is compared untaxed.
* Currency: claim in the case company's currency; a foreign-currency credit note counts with its company-currency untaxed amount (`amount_untaxed_signed`), never its document-currency figure.

## 6. Odoo design

**Models (new)**

* `warranty.vendor.claim` (`mail.thread`, `mail.activity.mixin`; sequence `VCL/00001`): company, partner (vendor / manufacturer), claim type, warranty case (required), jobs / MRFs (computed from lines), state **Draft / Waiting Approval / Approved / Sent to Vendor / Vendor Answered / Closed / Cancelled** (+ internal rejection back to Draft with reason), vendor result (Accepted / Partially Accepted / Rejected), failure description, defective-return flag and reference, vendor reference, sent / response dates, submitted / approved / finance-approved by & date, approval snapshot amount, amounts (Claimed, Approved, Accepted, Recovered, Settled, Outstanding = Accepted − Recovered, Not Accepted = Claimed − Accepted), recovery status, write-off reason, attachments count, over-claimed flag, activities.
* `warranty.vendor.claim.line`: claim, MRF line (required), product, qty, UoM, serials / lots, unit cost basis (snapshot from 5.7), cost basis status, claimed amount, accepted amount, vendor reason, goodwill flag, over-claimed flag.
* `warranty.vendor.claim.recovery`: claim, credit note (`account.move`, posted in_refund of the claim partner's commercial entity, same company), allocated amount, linked by / date, note; counted only while the move is posted.
* Wizards: Create Vendor Claim (eligible lines, partner proposal), Reject (reason), Vendor Response (per line), Link Credit Note (allocation), Close / Cancel (reason).

**Extended**

* `material.purchase.requisition.line`: claimed qty / amount (active claims), claimable qty, recovered amount, claim links.
* `warranty.case`, `warranty.service.job`, `material.purchase.requisition`: claim count, smart button, recovery status and amounts, net cost after recovery (cost-group fields, 5.7 rule).
* `product.template`: *Vendor Claimable*, *Warranty Claim Partner*, *Vendor Warranty (months)* (information).
* `res.company` / settings (Warranty → Material Requests block): Vendor Claims Enabled, Claim Approvers, Finance Approvers, Finance Threshold, Claim Evidence Required, Recovery Account.
* `account.move`: computed *Warranty Vendor Claims* smart button on credit notes (no stored change to accounting records).

**Menus / actions**

* **Warranty → Vendor Claims** (SRS §6) – list / form / pivot / search (status, partner, case, recovery status, over-claimed).
* Accounting (Invoicing) → Vendors → **Warranty Vendor Claims** (accountants).
* Buttons: *Create Vendor Claim* on MRF, job, case (eligible lines only); on the claim: Submit for Approval, Approve / Reject, Mark Sent, Record Vendor Response, Create Draft Credit Note, Link Credit Note, Close, Cancel, Reset to Draft.
* Warranty → Reports → **Vendor Claim Recovery** report: 5.9 (the claim pivot covers 5.8 testing).

**Security**

* Create / edit Draft: Helpdesk users (Service Coordinators) and Requisition users of the company.
* Approve: named approvers (V-8). Vendor response, close / write-off: claim owner + Finance approvers.
* Credit note create / link: Accounting **Billing** users (standard rights to create credit notes); Accounting Read-only: read claims.
* Technicians (Field Service only): no access (no menu, no record access, amount fields with cost groups).
* Multi-company record rules on claims, lines, recoveries; credit note must belong to the claim company.
* Audit: field tracking on state / amounts / partner / reference; chatter notes on case, job and MRF for create, approve, send, response, recovery, close; no deletion after submission; approval history kept.

## 7. Tests

**Automated (planned T8.1 – T8.14)**: eligibility (not claimable product, customer-paid, unverified, pending → refused; covered / goodwill claimable); partner proposal order; claimed ≤ actual cost and ≤ claimable qty; duplicate claim / serial refused, released after rejection / cancel; approval route (warranty only / + finance above threshold, separation of duties, reject → draft with reason); evidence rules before submit / send; vendor response full / partial / rejected, accepted ≤ claimed; draft credit note creation (draft only, account per V-13, no posting, no stock move); link existing credit note: partner / company / type / posted checks, allocation limits (per credit note and per claim), cancelled credit note stops counting; recovered / settled / outstanding amounts and case status; reversal after claiming → over-claimed flag and blocks; multi-company isolation and foreign-currency credit note (company-currency amount); access (technician refused, accountant reads, billing links); no journal entry except accountant-posted credit notes; 5.7 cost values and MRF approval history unchanged; full regression.

**Manual (TC-P5-801 – 815)**: configure claimable product, partner and approvers; create claim from MRF / case; duplicate attempt; approval with / without finance; evidence; send; partial vendor acceptance; draft credit note → accountant posts → recovered; refund payment → settled; vendor rejection and new claim; reversal after claim → over-claimed; close with write-off; case / job display; access with technician and billing users; standalone requisitions unaffected.

## 9. Remaining SRS scope after 5.8 (not implemented, documented)

* §17 / §2.10 b9 **claim receivable / other recovery account** and direct cash reimbursement without a vendor credit note → Part 8 (recovery accounting). 5.8 records recoveries only through vendor credit notes.
* §11.1 / §12 #15 claims **from a replacement** (complete unit) → replacement Part.
* Labour, travel, subcontract recovery (§2.10 b8) → Part 8.
* §15 *Vendor Claim Recovery Report* → Phase 5.9 (Warranty → Reports).
* Physical return of defective parts to the vendor (§11.2 vendor return location) → Repair / Replacement Part (5.8 records flag and reference only).

## 8. Open business decisions for confirmation (revision 1 – answered in section 0)

1. **V-1 / V-2** – customer-paid lines never claimable; goodwill claimable but flagged?
2. **V-3** – add *Warranty Claim Partner* (manufacturer) on products, or vendors only?
3. **V-6** – hard limit claim ≤ actual cost, or allow a higher amount with a warning?
4. **V-8** – own Claim Approver / Finance lists + threshold, or reuse the 5.3 MRF approval rules?
5. **V-9** – evidence attachment mandatory before sending (default on)?
6. **V-12 / V-13** – recovery only through vendor credit notes; recovery account default = company setting, else product expense?
7. **V-14** – one credit note may be allocated to several claims?
8. **V-15** – flag-and-block (no automatic reduction) after reversals / returns?
9. **V-18** – material claims only in 5.8 (unit replacement and labour recovery later)?
