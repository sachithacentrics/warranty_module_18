# Part 6.2 – Backup Unit Issue / Return – Implementation Notes

| Item | Value |
|---|---|
| Status | **Coded 2026-11-02 (18.0.1.1.0). Never run: static syntax checks only.** Manual UAT by the user pending. |
| Scope | Phase 2 only. Damage / Loss Billing (Phase 3) and reporting (Phase 4) are not included. |
| SRS | §2.9, §2.13, §2.15 Backup Unit Issue / Return, §7 Backup Unit Locations, §9.13, §13, §12 #17 |
| Manual tests | `tests/Part6_2_Backup_Manual_Testing_Guide.md` |

## Design

* One model, `warranty.backup.unit` (`BKU/00001`), with the §2.15 fields except Deposit / Charge.
* Stock: standard internal transfers of two user-created Operation Types. Their default locations
  are the three §7 locations, so the only settings are the two types. All locations must be outside
  every warehouse: warehouse quantities count everything under the WH view.
* Reservation: Odoo 18 has no lot restriction on moves and may reserve any serial on confirmation,
  so the code releases that reservation and reserves the exact serial.
* `stock.picking._action_done` checks before the stock moves (exactly one unit, exact product and
  serial record, operation locations, status, return condition) and sets status, actual dates and
  history afterwards.
* Standard Return is refused on backup transfers, which would bypass the record.
* Status, dates and transfers are written only through a Python marker.
* Overdue: daily cron with the company Warranty Timezone; a To-Do, no email.
* No Sales Order, delivery, MRF, job or task is created or changed. Internal transfers do not run
  the delivery or return logic of warranty cards.

## Status

| From | To | Trigger |
|---|---|---|
| Draft | Issued | Issue transfer validated |
| Issued | Overdue | Cron, after the Expected Return |
| Overdue | Issued | Cron, after the Expected Return is moved later |
| Issued / Overdue | Returned | Return transfer validated, condition Good or Minor Scratch |
| Issued / Overdue | Damaged | Return transfer validated, condition Damaged |
| Returned | Closed | Close, once the serial is back in Backup Stock (manual, D-R1) |
| Returned | Damaged | Submit Assessment (Part 6.3) |
| Issued / Overdue | Lost | Approved loss report (Part 6.3) |
| Damaged / Lost | Closed | **Not implemented: BA decision D3**, `part6_3_backup_billing_design.md` |

## BA decisions (Phase 2 defaults)

| # | Question | Default |
|---|---|---|
| BB-1 | Deposit: recorded, invoiced, refunded or offset? | Not implemented; §2.15 Deposit / Charge left to Phase 3 |
| BB-2 | Does Minor Scratch need assessment? | No: only Damaged goes to Damaged |
| BB-3 | How is a lost unit recorded and written off? | Phase 3; the serial stays in the Loan location, Overdue |
| BB-4 | Must the backup return wait for the repaired machine's return (§2.9 order)? | Not blocked; a To-Do when the machine goes back |
| BB-5 | "Loan unit allowed", return deadline and damage charge rules (§12 #17) | Not configured; expected return per record |
| BB-6 | Who may issue or return? §16 role Repair / Backup Coordinator | Inventory users; the role is Phase 4 |
| BB-7 | Backup record on a non-warranty ticket | Warranty tickets only |

## Return to Backup Stock (18.0.1.6.2, Figure 6)

* Button on a Returned unit with Return Condition Good and no assessment (Inventory users): a
  standard Internal Transfer Returned-Inspection -> Backup Stock of exactly the backup serial,
  linked as Return to Stock Transfer. Validated by the user; Close stays manual (D-R1).
* Operation type: the existing Internal Transfers of the Backup Issue type's warehouse, else of the
  company's only warehouse (D-R2); no new type, setting or status.
* A linked pending transfer is opened again. One unlinked pending transfer of exactly this serial
  to Backup Stock is opened, never linked; any other pending transfer of the serial is listed and
  nothing is created. Serial already in Backup Stock: Close.
* Validation is checked like the issue / return (serial, quantity, locations) and refused if the
  unit is no longer Returned / Good / without assessment. Standard Return of it is refused.
* Minor Scratch keeps the manual internal transfer; Damaged / Lost unchanged.

## Known limits

* `warranty.unit` has no chatter: history is on the record, ticket, case, card, job and repair.
* Stock valuation counts backup units as company stock wherever they are; the transfers post no value.
* `warranty_management_mrf/tests/test_settings_help.py:20` expects 39 settings; with this module it is
  now 42.
