# 17 – AMC Functional Test Cases

Automated (A) test methods are named `test_tc<nnn>_…`. Results: `18_AMC_Automated_Test_Results.md`.

| Test ID | Requirement | Scenario | Expected result | Type |
|---|---|---|---|---|
| TC-001 | D11, DEF-01 | Add a factor to an Active formula; to a Draft new version | refused; allowed | A |
| TC-002 | D07, DEF-02 | Usage plan, expected usage 1,000 | price = 20,000 + 15 × 1,000 | A |
| TC-003 | B07, DEF-03 | Change plan duration after sale; re-price a draft | sold end date unchanged; draft 24 months | A |
| TC-004 | B02, DEF-04 | Plan restricted to another pricelist | price calculation refused | A |
| TC-005 | E01 | Quantity 1.5 | refused | A |
| TC-010 | C03, A05 | Quotation state | no visits, no billing | A |
| TC-011 | E01, E02, B04, B06 | Retail 3/yr, 2 units | 6 preventive (4/8/12 months, last = end) + 2 free; idempotent | A |
| TC-012 | B05 | Project 2/yr | due 6 months and end date | A |
| TC-013 | E10 | Usage plan visits; completion without / lower reading | usage due 500 / 1000; refused / refused | A |
| TC-020 | E06, E07, E09 | Manual completion | consumed once; next visit moves | A |
| TC-021 | H05 | Write state / create / unlink visit directly | refused | A |
| TC-022 | E03 | Plan a date; clear it; plan outside period | Scheduled / Pending / refused | A |
| TC-023 | C04 | Cancel visit as Coordinator / empty reason / Manager | refused / refused / Cancelled | A |
| TC-024 | E04, E08 | Cron before alert, at alert, repeat, overdue, after grace, reopen | upcoming; one alert; no duplicate; overdue; Missed; Pending | A |
| TC-030 | B09, G03 | Upfront plan | 1 period released; draft invoice 30,000; no second invoice | A |
| TC-031 | B09 | Quarterly in advance, cron twice | 4 dated periods; one release per due period | A |
| TC-032 | B09 | Per preventive visit | period released at consumption | A |
| TC-033 | A05, G03, G04 | On Payment trigger | Awaiting Payment, period 1 released, no visits; paid → Active with visits | A |
| TC-034 | C02 | Cancel order while Awaiting Payment | Draft, billing removed | A |
| TC-040 | C04 | Hold (Coordinator / Manager), plan, cron, resume | refused / On Hold; planning refused; no alert; Active | A |
| TC-041 | B08, C05 | Cron 31 / 30 / 29 days before end, Auto Offer | Active → Expiring; one renewal draft | A |
| TC-042 | C05 | Renewal with same serial sold; cron after end | renewal Active; old Renewed; visits Expired | A |
| TC-043 | C04 | Cron after end without renewal | Closed; visits Expired; no planned billing | A |
| TC-044 | C04, AS-02 | Cancel Active / cancel its SO / close without reason / close | refused / refused / refused / Closed; renewal possible | A |
| TC-045 | C05 | Renewal of a Closed contract activated | predecessor Renewed | A |
| TC-046 | H05 | Write state, renewal_of_id, close_reason, contract_months | refused | A |
| TC-047 | H01 | Render AMC Visit Schedule | HTML contains contract and visits | A |
| TC-048 | B07 | Manual start 31 Jan | due 31 May / 30 Sep / 30 Jan; end 30 Jan | A |
| TC-050 | H03 | Employee without AMC role reads / creates contract | AccessError | A |
| TC-051 | H03 | Role matrix (User / Coordinator / Manager) | each refused outside its role | A |
| TC-052 | H05 | Forge billing / visit through ORM | refused | A |
| TC-060 | NFR-01 | Company-2 contract seen by company-1 user / both-companies user | hidden / visible | A |
| TC-061 | NFR-01 | Plan of another company on a contract | refused | A |
| TC-062 | E03 | Visit references | AMCV/ sequence | A |
| TC-063 | Settings | AMC Enabled off: menus, new contract / opportunity, renewal of an existing contract | app hidden in that company only; refused; allowed | A |
| TC-070 | REG-01 | Regular SO edit / copy / confirm / deliver / invoice / pay / cancel | standard behaviour | A |
| TC-071 | — | AMC quotation edit / add line / copy / create with contract | refused | A |
| TC-072 | REG-02 | Pay a non-AMC invoice | AMC contract unchanged | A |
| TC-080 | REG-03 | Warranty confirmation, mode None | confirmed, no AMC | A |
| TC-081 | A03, A04, A06, C07 | Mode Draft Contract | one Draft contract with the units, start = warranty end + 1 | A |
| TC-082 | A04 | Mode Draft Opportunity, Won | opportunity; contract with units | A |
| TC-083 | A03 | Auto-create raises | warranty confirmed anyway | A |
| TC-084 | A07 | Convert to AMC twice; draft card | one contract; refused | A |
| TC-085 | A08, C07 | Convert an expired card | no retroactive start | A |
| TC-086 | E09 | Same warranty unit on two open contracts | refused | A |
| TC-087 | X01 | Card expires with offer setting | one offer activity per recipient, no duplicate | A |
| TC-088 | NFR-03 | Write source warranty card | refused | A |
| TC-089 | Settings | AMC Enabled off: warranty confirmation (auto-create), Convert to AMC, warranty expiry (offer) | no AMC; refused; no offer to-do | A |
| TC-090 | F01–F05, H02, H04, E2E-01 | Two visits → request → ticket (AMC tag) → eligible → approved → job → 2 worksheets → visit → sign-off → complete | visits consumed once, links kept; re-request refused | A |
| TC-091 | F06 | Complete without sign-off | refused, not consumed | A |
| TC-092 | F07 | Cancel job; reject case | Scheduled; Pending | A |
| TC-093 | F03 | Merge across contracts; duplicate request | refused | A |
| TC-094 | A08, C04 | Contract put on hold | case Not Eligible; request refused | A |
| TC-095 | F01 | Manual completion with the chain installed | refused | A |
| TC-096 | F02 | Ticket of the customer; add visits to it | pending listed; count decreases | A |
| TC-097 | REG-04 | Non-AMC case and AMC case without contract | standard Manual Review | A |
| TC-100 | D01–D08 | SRS 16.2 examples per method | expected prices | A |
| TC-101 | D11, G06 | Minimum / rounding / maximum / factors / min > max | 2,000 / 9,300 / 20,000 / refused | A |
| TC-102 | D09, D10, D12 | Allowed and forbidden expressions | evaluated / AmcExpressionError | A |
| TC-103 | D11 | Version lock, new version activation, overlap, archive rights | locked; previous ended; refused; refused | A |
| TC-104 | D12 | Price Preview | price + breakdown | A |
| TC-105 | D13, H06 | Override by Coordinator, approval by requester / Approver | refused / applied; quotation at override price | A |
| TC-106 | B03 | Product outside plan categories | refused | A |
| TC-107 | C02 | Cancel a Quotation contract | Cancelled, SO cancelled | A |
| TC-M01 | A09, F13 | Open each new menu / view in the browser | renders, filters work | Manual (UAT) |
| TC-M02 | F08–F10 | MRF, excluded items, costs on an AMC job | standard behaviour | Manual (UAT) |
| TC-M03 | F12 | SLA policy on tag AMC | SLA deadline on AMC tickets | Manual (UAT) |
| TC-M04 | H01 | Print PDF | PDF downloads | Manual (UAT) |
