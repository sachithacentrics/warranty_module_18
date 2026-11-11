# Part 6.3 – Backup Unit Damage / Loss Billing and Deposit – Implementation Notes

| Item | Value |
|---|---|
| Status | **Coded 2026-11-02 (18.0.1.2.0). Never run: static syntax checks only.** Manual UAT by the user pending. |
| Approval | Conditional approval of the Phase 3 mapping, 2026-11-02. D3, D4, D6 and D9 stay open. |
| SRS | §2.9, §2.15 Deposit / Charge, §9.13, §12 #17, §13, §16, §17 Backup unit damage/loss |
| Manual tests | `tests/Part6_3_Backup_Billing_Manual_Testing_Guide.md` |

## Design

* No new model, wizard, report or status value. Fields and four buttons on `warranty.backup.unit`:
  Report Lost, Submit Assessment, Approve Assessment, Send Back.
* One approval step: the company list **Backup Damage / Loss Approvers**; the submitter cannot
  approve. A loss becomes Lost only when approved; damage becomes Damaged when submitted.
* Cost and charge are entered manually. There is no charge formula.
* Approval with a charge creates one draft quotation with the company's Charge Product, in the
  company currency. Nothing is sent, invoiced, posted, scrapped or closed automatically.
* The quotation has no `warranty_case_id`: a case-linked order runs the chargeable job trigger. The
  case and Repair Order links are on the backup record and in the quotation's Origin.
* Duplicate billing: the quotation is created only at approval; the link cannot be removed and the
  order cannot be deleted while linked, or duplicated; line changes are refused; confirmation
  needs the approved line; standard Sales invoices the ordered quantity once.
* **Physical Asset** is read from the serial's stock location; **Financial Recovery** from the
  quotation and invoices. Neither changes the other or the record's Status.
* Paid uses the existing `_warranty_uncovered_amounts` rule. Any posted credit note shows Credit
  Note Issued. A cancelled quotation shows Quotation Cancelled, never No Charge. Standard Set to
  Quotation brings a cancelled quotation back.
* Deposit: amount and a link to an existing customer invoice only.

## Status

| From | To | Trigger |
|---|---|---|
| Returned | Damaged | Submit Assessment (damage found during the inspection; return condition unchanged) |
| Issued / Overdue | Lost | Report Lost, then Approve Assessment |
| Damaged / Lost | Closed | Close (repair 18.0.1.7.1, Figure 6 C2): see `part6_1_repair_intake_design.md` section 16 |
| Lost | (Lost, found) -> Returned / Damaged | Record Found (approver), then the Backup Return (C2, B5) |

Phase 2 is unchanged for Good and Minor Scratch: Returned, transfer to Backup Stock, Close.

## Stock

Stock is never moved by these actions. Repair, transfer, Scrap and inventory adjustment are the
standard screens. A Damaged or Lost record stays open, so its serial cannot be selected or issued
again, wherever the serial is. A return transfer is refused while a loss report waits for approval
and after Lost.

## Open BA decisions

| # | Question | Until decided |
|---|---|---|
| D3 | Does closure need full payment, or physical resolution only? How are approved write-offs handled, and what happens after a cancelled quotation? | **Decided 2026-11-06 (C2, B1–B7):** payment and physical resolution both needed; restored units via Confirm Restored. Still open: a write-off rule for credit notes / cancelled quotations of units that were not recovered (not closable). |
| D4 | Deposit collection, application, refund, forfeiture | Amount and invoice link only. Accounting acts manually. |
| D6 | Recovery of a lost unit that is found | **Decided 2026-11-06 (C2, B5)** before the record is closed: Record Found, stock correction first when written off. Still open: recovery of a Closed Lost record (Part 9); a corrected assessment after approval. |
| D9 | Must actual repair and scrap cost link automatically? | Manual, approved Repair / Scrap Cost; not on the warranty case cost. |

## Decisions accepted from the mapping

| # | Decision |
|---|---|
| D1 | Company approver list, submitter excluded |
| D2 | Charge amount entered per assessment |
| D5 | Lost serial written off with standard Scrap by a user, never automatically |
| D7 | The existing overdue-invoice check counts an overdue charge invoice, unchanged |
| D8 | Minor Scratch: no automatic charge; Submit Assessment is available from Returned |
| D10 | Charge through a service product, not a sale of the serial |

## Known limits

* The approver needs Helpdesk or Inventory rights to open the Backup Units menu.
* `warranty_management_mrf/tests/test_settings_help.py:20` expects 39 settings; with this module it
  is now 44.
* Physical Asset reads current stock only; a standard user can still move or scrap a serial while
  the unit is open, as in Phase 2.
* Lines can still be added to a confirmed charge order with standard Sales; the charge line is
  locked. An added line is billed as itself.
