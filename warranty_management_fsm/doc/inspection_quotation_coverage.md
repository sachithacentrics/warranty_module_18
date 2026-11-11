# Inspection Quotation coverage

2026-11-09, approved Option A. Found during UAT on WCAS/000075 / S00107.

Versions: `warranty_management_helpdesk` 18.0.1.2.7, `warranty_management_fsm` 18.0.1.4.10. Tests are in `warranty_management_accounting`.

## Rule

This applies to Create Inspection Quotation, the Approved / Eligible case with Inspection Required (SRS Figure 4 "Yes").

- **Matching:** the team's Inspection Product is matched against the coverage items of the case policies. These are the card's policy and the policies of the free service cards, as for the Material Request default (D7).
- **Exact product only:** a coverage item counts only when its Product is the Inspection Product itself. Covered Labour or Parts items never cover the inspection.
- **Result:**

| Coverage | Line | Customer amount |
| --- | --- | --- |
| Excluded (wins over Covered) | team amount or list price, no discount | chargeable, as before |
| Covered | same price, **100% discount** | 0.00 (tax on 0.00) |
| Not Listed | team amount or list price, no discount | chargeable, as before |

- **Line field:** `sale.order.line.warranty_inspection_coverage` (Covered / Excluded / Not Listed). It is read-only and set at creation, and shown as an optional column on warranty quotations.
- **Kept on the line:** the original price (`price_unit`) and the covered amount (`price_unit × qty × discount`).
- **Case chatter:** the coverage is logged with the quotation.
- **One line:** the quotation keeps its single inspection line. No Labour or Parts lines are added: they are found after diagnosis and go through the Material Request coverage and chargeable flows.
- **Unchanged:**
  - Sales Order confirmation and the Inspection Trigger. A covered order confirms at 0.00 and creates the Draft service job. With On Payment, posting the 0.00 invoice creates the job.
  - Taxes, invoicing, approvals and security.
  - Convert to Chargeable quotations.
  - Material Request coverage.
- **Inspection fee adjustment (Part 8.4):** a covered fee was never charged. The existing check "Inspection order … has no fee to adjust" refuses it, so no credit note or deduction is created.
- **Existing quotations, such as S00107:** they are not changed.

## Configuration (UAT, by the business)

1. **Coverage item:** Warranty > Configuration > Coverage Items: create "Inspection" with Product = the team's Inspection Product ("UAT - AC Inspection Service").
2. **Policy:** add it to the Covered Items of each policy that covers inspection, or to the Excluded Items to make it explicitly chargeable.

## Out of scope

- Product Category coverage.
- Labour and Parts quotation lines.
- Recalculating existing quotations.
