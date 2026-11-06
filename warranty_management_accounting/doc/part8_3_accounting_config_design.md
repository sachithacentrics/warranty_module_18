# Part 8.3 Accounting Configuration: decision record

Module `warranty_management_accounting` 18.0.1.2.0. Mapping row 10, section 10A of `Part8_Cost_Accounting_Mapping.md` revision 3. **Configuration only: no journal entry is created or posted, and nothing is backfilled.**

## Approved decisions

| Decision | Result |
| --- | --- |
| Architecture | Existing models only. No `warranty.accounting.rule`, new module or new menu |
| Fixed provision | Per unit: quantity x amount |
| Percentage provision | Untaxed sales value of the invoice line, in company currency (D1) |
| Reserve | One Warranty Provision / Reserve account per company |
| Who can change it | Users with **both** Settings and Accounting Manager rights |
| Future rates | Not scheduled. A change applies when saved |
| Default | Disabled |

## Fields

**New on `res.company`:** `warranty_provision_enabled`, `warranty_provision_method` (Disabled, Fixed Amount per Unit, Percentage of Sales Value), `warranty_provision_rate`, `warranty_provision_amount`, `warranty_accounting_journal_id`, `warranty_expense_account_id`, `warranty_provision_account_id`, `warranty_cost_recognition_account_id`.

**New on `product.template`, `product.category`, `warranty.policy`:** `warranty_provision_method` (Use Next Level, No Provision, Fixed Amount per Unit, Percentage of Sales Value), `warranty_provision_rate`, `warranty_provision_amount`. Company-dependent on product and category; normal fields on the policy, which belongs to one company.

**New on `helpdesk.team`:** `warranty_inspection_deduction_product_id`, for Part 8.4.

**Reused, not duplicated:** team `warranty_inspection_product_id` and `warranty_inspection_amount`; company `warranty_claim_recovery_account_id`, which stays under Vendor Claims and is only read by the readiness message.

**Changed from Revision 3:** no separate Inspection Deduction account field. The deduction product's income account is the standard Odoo source, so a second field would duplicate it. If Finance needs a different account, set it on that product.

## Precedence

Implemented in `res.company._warranty_provision_rule`, read only:

1. Product override
2. Category override, nearest category first, then its parents
3. Warranty policy: the product's applied policy, or the category's default policy, if it applies to this company
4. Company default

Empty or Use Next Level continues. No Provision stops, with no provision. Disabled at company level means no company default; overrides still resolve, but no value is calculated while the company switch is off. `_warranty_provision_value` returns 0 in that case and posts nothing.

## Validation

- Journal: Miscellaneous type, same company.
- Warranty Expense and Cost Recognition: Expense or Direct Cost.
- Provision: Current or Non-current Liability, different from Warranty Expense.
- Every account: belongs to the company and isn't deprecated.
- Percentage: above 0 and up to 100. Fixed amount: above 0. Checked at every level.
- Enabling needs the journal, Warranty Expense and Provision accounts, and names what is missing.
- A linked journal or account can't be deleted while used here.

Settings saves all company values in one write, because the checks need the whole configuration at once.

## Security

| User | Read | Change |
| --- | --- | --- |
| Settings **and** Accounting Manager | Yes | Yes |
| Accounting Manager only (includes `main_tech`, `support_tech` on UAT) | Yes | **No** |
| Settings only | Not unless an accounting user | **No** |
| Accountant, billing | Yes | No |
| Product or policy user without an accounting role | No | No |
| Technician | No | No |

- The check is on every create and write of these fields, in `warranty.accounting.config.mixin`, and looks at the real user, so calling through sudo doesn't bypass it. Only the system itself (module data) is exempt.
- An unchanged value in a form save needs no rights, so normal product, category, team and policy editing stays open.
- Overrides are not copied when a product, category or policy is duplicated.
- Each user's group membership is unchanged. Roles of `main_tech` and `support_tech` are not touched.
- Company isolation: Settings act on the active company; product and category values are per company; another company's account, journal or policy is refused or ignored.

## Audit

| Record | Where the history is |
| --- | --- |
| Company | Field tracking in its chatter, added to the company form |
| Product, category, team | Field tracking in their chatter |
| Warranty policy | A note on the company's chatter with policy, user, old and new values, because a policy has no chatter |

## Existing data on upgrade

- New columns start empty. `warranty_provision_method` on existing companies becomes Disabled.
- No account, journal, product, category, policy or team value is filled in.
- Saving Settings without changing these values writes nothing to the company.

## Finance decisions and limits

- **F2:** Finance chooses real accounts and journal per company.
- **F1, F4:** parts route and reserve-eligible costs wait for Part 8.6.
- **F3:** rates are Finance's to set. The percentage base is the D1 definition, which 8.6 will apply to posted invoice lines.
- **Quantity:** the fixed amount uses the quantity the later stage passes in; 8.6 must use the product's unit of measure.
- **Reading by Settings-only users:** they don't see the block, and can't change it.
- **Other-role users opening Settings:** only `base.group_system` opens Settings at all. A Finance user who isn't an administrator can't use this screen.
- **Rate changes apply at save time:** there are no scheduled rates, and no effect on past invoices because nothing has posted.
- **Part 8.2 limits stay open:** F6 and reversal after a claim is closed. See `part8_2_cost_report_design.md`.
