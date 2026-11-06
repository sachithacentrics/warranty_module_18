# 15 – AMC Regression Impact Matrix

| Modified component | AMC behaviour | Existing non-AMC behaviour | Regression test | Result |
|---|---|---|---|---|
| `sale.order.action_confirm` | AMC orders: billing schedule, activation (sudo side effect) | unchanged for orders without `amc_contract_id` | TC-070; Sales flows inside the warranty suites (cards from SO confirmation) | see 20 |
| `sale.order._action_cancel` | refuse for activated contracts | unchanged | TC-070 (cancel of a regular quotation) | PASS |
| `sale.order.line` write (1.0.0) | AMC lines locked; `qty_delivered` written with the contract marker | unchanged | TC-070 (regular delivered quantity / price / discount edits) | PASS |
| `account.move._invoice_paid_hook` | activation of Awaiting Payment contracts | unchanged (`sale` hook still called via `super`) | TC-072, TC-070 (regular payment) | PASS |
| `warranty.card.action_confirm_warranty` | optional draft AMC (savepoint) | unchanged with mode None | TC-080, TC-083; warranty core / helpdesk / fsm suites | see 20 |
| `warranty.card._warranty_apply_expiry` | optional AMC offer activity | unchanged when setting off | TC-087; warranty expiry tests | see 20 |
| `warranty.case._warranty_run_checks` | AMC eligibility for AMC cases with contract | unchanged for all other cases, incl. AMC cases without contract | TC-097; helpdesk eligibility suites | see 20 |
| `warranty.case.write` | release AMC visits on rejected / closed | unchanged (only cases with AMC visits) | helpdesk suites | see 20 |
| `warranty.service.job` confirm / worksheets / completion / cancel | AMC visit statuses, one worksheet per AMC visit, consumption | unchanged for jobs without AMC contract | FSM suites (confirm, worksheets, completion, batch, reschedule, cancel, shared visit) | see 20 |
| `helpdesk.ticket` | pending AMC visits (non-stored compute) | unchanged | helpdesk / fsm ticket tests | see 20 |
| ACL additions (Helpdesk / FSM read on AMC) | read AMC records of AMC cases | additive only | TC-090 (as Helpdesk / FSM users) | PASS |
| `warranty_meta_dependencies` depends | installs bridges | — | fresh install (21) | PASS |
