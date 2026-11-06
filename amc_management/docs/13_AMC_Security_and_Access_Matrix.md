# 13 – AMC Security and Access Matrix

Groups (category *AMC Management*): **User** ⊂ **Coordinator** ⊂ **Manager**; **Approver** (category
*AMC Approval*, implies User). `base.user_root` and `base.user_admin` are AMC Managers.

## 1. Model access (ACL: read / write / create / unlink)

| Model | User | Coordinator | Manager | Approver | Helpdesk User* | FSM User* |
|---|---|---|---|---|---|---|
| amc.plan, amc.billing.plan, amc.pricing.* | R | R | RWCU | R | R (plan) | R (plan) |
| amc.opportunity | RWC | RWC | RWCU | RWC | — | — |
| amc.contract | RWC | RWC | RWCU | RWC | R | R |
| amc.contract.line | RWCU | RWCU | RWCU | RWCU | R | R |
| amc.price.override | R | RWC | RWC | RW | — | — |
| amc.contract.visit (new) | R | RW | RW | R | R | R |
| amc.billing.line (new) | R | R | R | R | — | — |
| wizards (reason: Manager; visit action: Coordinator; service request: Coordinator) | — | ✓ | ✓ | — | — | — |

\* granted by `amc_management_service` so that Helpdesk users / technicians can read the AMC
records of their own cases and jobs. All writes to visits and billing lines happen through
server code (marker + sudo after the group check); the ORM `write`/`create`/`unlink` of these
models refuse unmarked calls, so ACL write rights cannot be used to forge states.

## 2. Sensitive operations (server-side checks)

| Operation | Required |
|---|---|
| Calculate price, request override, create / reissue quotation, invoice, renew, plan / complete visits (core), create service request | Coordinator (+ Salesman for quotations, + Helpdesk User for service requests) |
| Cancel / hold / resume / close contracts, cancel / reopen visits, activate / archive / version formulas | Manager |
| Approve / reject overrides | Approver of the contract company, not the requester |
| Change status / price / lifecycle / service-link fields | never directly (protected fields; UI, import and RPC refused) |

## 3. Multi-company

Record rules `company_id in company_ids` on contracts, lines, visits, billing lines, opportunities,
overrides; shared-or-own rules on plans, billing plans and pricing records. Constraints refuse a plan,
warranty unit or AMC contract of another company. The cron runs per contract; sequences are taken
with the contract company. Tests TC-060 / TC-061.

## 4. Scheduled actions and reports

The cron runs as the cron user (superuser); it only performs idempotent system transitions. The
report reads `amc.contract` with the user's rights (record rules apply).
