# 19 – AMC End-to-End Test Report

All scenarios executed as automated tests on `amc_test` on 2026-11-06 (status PASS, see 18).
Database values were asserted inside the tests (states, counts, dates, links, amounts).

## E2E-01 – Retail AMC sold, serviced through Helpdesk / Field Service (TC-090)

| Step | Action (user) | Verified result |
|---|---|---|
| 1 | Coordinator creates a contract: Retail AMC, 2 units | Draft |
| 2 | Calculate Price, Create Quotation; Sales confirms | Active; 6 preventive + 2 free visits; upfront period released |
| 3 | Coordinator selects visit 1 of both units → Create Service Request | ticket (tag AMC), case type AMC with contract; visits Scheduled |
| 4 | Helpdesk user checks eligibility; approver approves (separation of duties) | Eligible → Approved |
| 5 | Prepare Service Job, plan (date, main technician), Confirm | job Confirmed; FSM visit created; 2 worksheet instances (one per AMC visit); visits In Progress |
| 6 | Technician: timer start / stop with timesheet, customer signature, Complete Visit | job and case Completed; both visits Completed once; consumption source names job, visit and signer; ticket / task / worksheet links kept |
| 7 | Request the completed visit again | refused (E09) |

## E2E-02 – Payment-triggered activation (TC-033)

Quotation → SO confirmed → **Awaiting Payment** with period 1 released, no visits → Create Invoice →
post → register payment → **Active**, start = payment day, 4 visits.

## E2E-03 – Expiring, renewal and Renewed (TC-041, TC-042, TC-045)

Contract Active → scheduler 31 days before end: Active; 30 days: **Expiring**, one renewal draft
(Auto Offer), not duplicated the next day → renewal with the same serial priced, sold, Active, start =
end + 1 → scheduler after the old end: old contract **Renewed**, open visits Expired. Late renewal of
a Closed contract → Renewed.

## E2E-04 – Closure without renewal (TC-043)

Quarterly contract → scheduler after the end: due periods released, **Closed**, reason recorded,
open visits Expired, no planned billing left.

## E2E-05 – Warranty to AMC (TC-081, TC-082, TC-084, TC-085)

Warranty card confirmed with auto-create mode *Draft AMC Contract* → Draft contract covering the
card's units, start = warranty end + 1, no entitlements; mode *Opportunity* → opportunity → Won →
contract with units; expired card → Convert to AMC (no retroactive start).

## E2E-06 – Failure branches

Sign-off missing (TC-091), job cancelled / case rejected (TC-092), contract put on hold after the
request (TC-094), incompatible merge (TC-093), warranty auto-create failure (TC-083).
