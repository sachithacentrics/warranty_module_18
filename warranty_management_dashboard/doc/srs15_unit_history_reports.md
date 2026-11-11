# SRS 15 (page 76): Unit Warranty Number and Warranty History reports

2026-11-09. Both reports reuse the existing actions, which the Dashboard already links to, so the
Dashboard is unchanged.

## Menus (Warranty > Reports)

| Category | Seq | Menu | Action |
| --- | --- | --- | --- |
| ~~Warranty & Entitlements~~ | - | Unit Warranty Number (menu removed, see below) | `warranty_management.action_warranty_unit` |
| Quality & History | 40 | Warranty History | `warranty_management.action_warranty_history` |

### Report categories

The Reports menu is grouped into five categories. They are defined in `warranty_management_mrf`, next to the Reports root.

- Each category menu has no action and no groups. It shows only when one of its reports is visible to the user.
- Every report menu keeps its xml id, action and groups. Only its parent and sequence changed.
- Sequences: categories 10 to 50, reports 10, 20, 30, 40 within a category.

| Category | Reports |
| --- | --- |
| Warranty & Entitlements | none (its 4 menus were removed, see below) |
| Service Operations | Helpdesk Pending Service, Service Merge and Job Planning, Repair and Backup Unit |
| Quality & History | Failure Pattern, Repeated Failure Escalation, Replacement, Warranty History |
| Materials & Inventory | Material Approval and Cost, Warranty Material Cost, Material Audit Trail |
| Financial & Recovery | Warranty Cost, Warranty Provision / Reserve, Vendor Claim Recovery, Chargeable Service Revenue |

### Warranty & Entitlements menus removed (dashboard 18.0.1.0.5)

The user asked for the 4 report menus to be removed because they are not useful: Active / Expiring Warranty, Draft Warranty Review, Unit Warranty Number and Free Service Due.

- Only the menus were removed (the user chose "menus only"). The module upgrade deletes the menu records.
- The actions stay: the Dashboard report shortcuts open them, and Cards > Warranty Unit Numbers (plus the Sales Order button) opens the unit list.
- The empty category stays in `warranty_management_mrf` (unchanged). It has no action and no groups, so Odoo hides it for every user.
- Reports now hold 4 visible categories and 14 report menus.

The Dashboard stays a top-level Warranty menu. AMC Visit Schedule stays in the AMC module under its own Reporting menu.

Cards > Warranty History was moved here, so there is only one history menu. Cards > Warranty Unit
Numbers stays as the operational list and uses the same action.

## Unit Warranty Number

- **Model:** `warranty.unit`, one row per unit warranty number.
- **New field:** `partner_id`, stored and related to the card customer, used for the filter and grouping.
- **Columns:** Warranty Number, Card, Customer, Sale Order, Product, Unit No., Delivery, Delivered On, Serial(s), Indoor / Outdoor Serial (`warranty_management_mrp`), Start and End Date, Status.
- **Filters:**
  - Search fields: card, warranty number, customer, product, serial, Indoor / Outdoor serial, delivery, sale order.
  - Status filters, plus Start and End Date.
- **Group by:** card, customer, product, sale order, status, end date.
- **Read-only:** the list has no create or delete, and the unit fields are read-only. A row opens the unit form, which links to its card and its history.

## Warranty History

`warranty.history` stays a read-only SQL view: nothing is copied or stored. Changes:

- **Navigation:** new `res_model` / `res_id` columns. The row's Open button opens the source record with the user's own rights.
- **Created rows:** they used to show the record's current status at its creation date, which was misleading. They now read "X created", and status changes come from the chatter tracking of each record's `state` field. This uses the helper `_warranty_history_status_query()`. Tracked records:
  - free service, case, job, replacement, backup unit, repair order;
  - Material Request, vendor claim, cost line;
  - warranty journal entries.
- **New rows:**
  - unit warranty created;
  - customer invoice posting events (`warranty.invoice.posting.event`);
  - cost lines (entity Warranty Cost);
  - provision, reserve utilization and inspection fee credit note entries (entity Journal Entry).
- **No amounts in any row.**
- **Access:**
  - Company rule, unchanged.
  - Cost rows only for users who see the company's cost lines: Helpdesk, Material Request and Purchase users.
  - Journal Entry rows only for accounting users. These are record rules in `warranty_management_accounting`.
- **Stable row ids:** the ids are ordered on every column, so rows sharing a timestamp keep their id.

## Not recorded by the current implementation (gaps)

- Card and unit status changes that are not controlled actions, such as automatic expiry: the card status is computed and untracked, and units have no chatter.
- Kit Indoor / Outdoor serial corrections on draft cards: there is only the `kit_serials_corrected` flag, with no before / after values.
- Field Service visit and worksheet events: they show only through the job status. This follows the Part 9 Q4 decision.
- Material Request line, issue and usage detail: it stays in Reports > Material Audit Trail.
- Chargeable quotations and invoices: they stay in Chargeable Service Revenue.
- Status changes made without chatter tracking: none appear.
