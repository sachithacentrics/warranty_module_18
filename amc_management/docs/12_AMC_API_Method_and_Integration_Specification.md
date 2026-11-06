# 12 – AMC Method and Integration Specification

## 1. Integration events

| Event | Source | Target | Trigger | Mapping / effect | Errors | Idempotency | Company |
|---|---|---|---|---|---|---|---|
| Quotation created | amc.contract | sale.order | Create Quotation | partner, shipping = site, pricelist, lines = billing periods × period price, `amc_contract_id` | amount / currency mismatch → UserError (rollback) | one open quotation per contract (row lock) | contract company |
| SO confirmed | sale.order | amc.contract | `action_confirm` | price frozen; billing lines; activation or Awaiting Payment | errors roll back the confirmation | state check `quotation` | SO company |
| SO cancelled | sale.order | amc.contract | `_action_cancel` | contract back to Draft (before activation) / refused (activated) | UserError | state check | — |
| Invoice paid | account.move | amc.contract | `_invoice_paid_hook` | Awaiting Payment → Active | — | only `awaiting_payment` contracts | invoice company |
| Billing release | amc.billing.line | sale.order.line | cron / activation / visit consumption | `qty_delivered = released count` | missing confirmed line → UserError (cron: logged) | only `planned` lines | — |
| Warranty confirmed | warranty.card | amc.contract / amc.opportunity | `action_confirm_warranty` | Draft AMC with units (contract) or opportunity | logged, never blocks | one AMC record per card | card company |
| Convert to AMC | warranty.card | amc.contract | button | Draft contract, units, start = warranty end + 1 if ahead | UserError (state / no unit) | opens the open contract | card company |
| Warranty expired | warranty.card | mail.activity | `_warranty_apply_expiry` | To-do for the service alert users | — | only on the transition to Expired, not if an AMC exists | — |
| Service request | amc.contract.visit | helpdesk.ticket, warranty.case | wizard | ticket (AMC tag) / existing ticket; case type AMC, contract, visits Scheduled | compatibility → UserError | visit must be Pending, not on an open case | contract company (checked) |
| Eligibility | warranty.case | — | Check Eligibility / Approve / Confirm Job revalidation | AMC checks | result not_eligible / manual_review | read-only | — |
| Job confirmed | warranty.service.job | amc.contract.visit | `action_confirm_job` | visits In Progress, job, task, worksheets | — | only open visits | — |
| Job completed | warranty.service.job | amc.contract.visit | `_warranty_complete_case` | consumption (date, usage from worksheet, sign-off source) | UserError rolls back the whole completion | `_amc_consume` refuses non-open visits | — |
| Job cancelled | warranty.service.job | amc.contract.visit | `_warranty_cancel` | In Progress → Scheduled | — | — | — |
| Case rejected / closed | warranty.case | amc.contract.visit | `write(state)` | visits back to Pending | — | only Scheduled / In Progress | — |

## 2. Regression risks and guards

All overrides call `super()` first (or last for guards) and act only on AMC records:
`amc_contract_id` on orders / cases / jobs, AMC orders on invoices, `case_type == 'amc'` plus a
contract for eligibility, company auto-create mode ≠ None for warranty confirmation.

## 3. Public action methods (buttons / RPC)

| Method | Server-side check |
|---|---|
| `amc.contract.action_compute_price`, `action_open_override`, `action_create_quotation`, `action_reissue_quotation`, `action_create_invoice`, `action_renew` | AMC Coordinator (`_amc_check_group`); quotation also Salesman |
| `action_cancel_contract`, `action_open_reason_wizard`, `action_resume`, `_amc_hold`, `_amc_close` | AMC Manager |
| `amc.contract.visit.action_open_complete_wizard` | Coordinator; disabled with the service bridge |
| `action_open_cancel_wizard`, `action_reopen`, `_amc_cancel` | AMC Manager |
| `action_open_service_request` / wizard `action_confirm` | Coordinator + Helpdesk User |
| `warranty.card.action_convert_to_amc` | AMC User |
| `amc.pricing.formula.action_activate`, `action_archive_version`, `action_new_version` | AMC Manager |
| `amc.price.override.action_approve`, `action_reject` | AMC Approver of the company, not the requester |
