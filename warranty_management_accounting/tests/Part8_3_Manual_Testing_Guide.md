# Part 8.3 Accounting Configuration: manual testing guide

Run after `warranty_management_accounting` 18.0.1.2.0 is upgraded, with your approval. Configuration only: no journal entry should appear from any step.

**View only, change nothing:** WCAS/000042, WCAS/000049, JOB/000036, WR/000006, VCL/00006 and its draft credit note. Use test products, categories, policies and accounts.

## Users

- **Finance admin:** Settings and Accounting Manager. On UAT, `admin` qualifies.
- **`main_tech` or `support_tech`:** Accounting Manager without Settings.
- **Product user:** can edit products, with no accounting role.
- **Field Service-only user:** new test user.

## A. Settings (Settings > Warranty > Warranty Accounting, as Finance admin)

| # | Step | Expected |
|---|---|---|
| 1 | Open after upgrade | Switch off, method Disabled, journal and accounts empty. Readiness names what is missing |
| 2 | Turn on with accounts empty, Save | Refused, naming the journal and accounts |
| 3 | Open the Provision / Reserve list | Only liability accounts of this company |
| 4 | Open the Journal list | Only Miscellaneous journals of this company |
| 5 | Pick Warranty Expense and Provision, Save | Saved, still off |
| 6 | Method Fixed, amount 0, Save | Refused: must be above 0 |
| 7 | Method Percentage, 120, Save | Refused: at most 100 |
| 8 | Add the journal, method Percentage 5, switch on, Save | Saved. Readiness says Ready if the Vendor Recovery Account is set |
| 9 | Settings > Users & Companies > Companies > this company | Chatter shows the old and new values, user and date |
| 10 | Vendor Claims block | Recovery Account unchanged, and there's no second copy under Warranty Accounting |

## B. Precedence (test product in a test category, with a test policy)

| # | Step | Expected Effective Provision on the product |
|---|---|---|
| 1 | Company 5%, no overrides | 5% from company default |
| 2 | Policy 4% on the category's default policy | 4% from policy |
| 3 | Parent category 3% | 3% from that category |
| 4 | Child category 2.5% | 2.5% from the child category |
| 5 | Product Fixed 20 | 20.00 per unit, from this product |
| 6 | Product Use Next Level | Back to 2.5% |
| 7 | Product No Provision | No provision, from this product |
| 8 | Turn the company switch off | Shows that provision accounting is off |

## C. Inspection (Helpdesk team form)

| # | Step | Expected |
|---|---|---|
| 1 | Inspection Product and Amount | Unchanged, still used by a new inspection quotation |
| 2 | Inspection Deduction Product, as Finance admin | Saved, shown in team chatter. Nothing uses it until Part 8.4 |

## D. Rights

| # | User and step | Expected |
|---|---|---|
| 1 | `main_tech`: product, category and policy forms | Sees values read-only, can't change them |
| 2 | `main_tech`: open Settings | Not available |
| 3 | Product user: rename a product and create a new one | Works; no provision fields shown |
| 4 | Field Service-only user: product form | No provision fields |
| 5 | Administrator without Accounting Manager (test user), Settings | No Warranty Accounting block; other settings save normally |
| 6 | Finance admin: change a policy override | Note on the company chatter with policy, old and new values |

## E. Companies

| # | Step | Expected |
|---|---|---|
| 1 | Switch to Company 2, open Settings | Its own empty configuration, off |
| 2 | Same product in Company 2 | No Company 1 override applies |
| 3 | In Company 1, a policy of Company 2 | Not applied |

## F. No accounting impact

| # | Step | Expected |
|---|---|---|
| 1 | With provision on, post a test customer invoice | Normal invoice; no entry on the Warranty Expense or Provision accounts |
| 2 | Compare journal entry and valuation counts before and after sections A-E | Only your test invoice |
| 3 | Part 8.2 guide, sections B and E, steps 11-12 | Same figures |
