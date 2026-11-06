# Warranty Management – Warranty Policy Resolution (Strict Policy Priority)

| Item | Value |
|---|---|
| Module | `warranty_management` (manifest 18.0.1.0.0) |
| Primary source | Warranty Module SRS §2.2 (Warranty Policy Resolution), §9.3 step 4, §10.1 |
| Status | Approved by the business owner: strict policy priority (2026-10-16: Q1 A, Q2 A, Q3 B, Q4 A, Decisions 1–2), Pricelist Warranty Policy (2026-10-17: D1–D5) |

This document records the approved warranty policy architecture. It replaces the earlier
"Applies To" design and the Product + Pricelist Warranty Mapping lines – see section 8.

---

## 1. Warranty Policy = reusable configuration

The Warranty Policy (`warranty.policy`) only holds configuration: warranty duration / unit, start
date basis, warranty basis, usage limit / unit, free service count, period, frequency, schedule
method, service offsets, auto-create, monitoring (due alert, expiry reminder, grace period,
auto-expire, responsible users, usage alert %), payment check, coverage and controls.

- No applicability on the policy form / list (Applies To and the mappings are hidden, data kept).
- `free_service_frequency` + unit (unit required with a frequency) and `usage_limit` (shown and
  required with Usage Unit when Warranty Basis = Usage).
- New policies take the current company (Company readonly); a policy without company is
  **shared** by every company.

## 2. Where a policy is selected

| Level | Field | Rules |
|---|---|---|
| P1 | Standard **Pricelist** → tab **Warranty**: **Warranty Applicable** (`product.pricelist.warranty_applicable`) + **Warranty Policy** (`product.pricelist.warranty_policy_id`) | The policy is required when Warranty Applicable is ticked (D2). A company pricelist takes a policy of its company or a shared one; a shared pricelist only a shared policy (D3). Warranty Applicable on the pricelist does **not** make products Warranty Applicable. The selected policy's values are shown readonly in the tab (related, not stored, nothing copied): duration, start criterion, basis, usage limit / unit, free service count, frequency, period, schedule method, auto-create, due alert days, responsible users, usage alert %, auto-expire, grace period, expiry reminder days. |
| P2 | Product → **Warranty Policy** (`product.template.warranty_policy_id`, company-dependent) | One value per company; policy of the current company or shared (constraint). Editable by the users who may write policies (administrators). Selecting a policy ticks Warranty Applicable. |
| P3 | Product Category → **Default Warranty Policy** | Used only for the order company or when shared. Shown on the product as **Category Warranty Policy** when the product has none. |
| P4 | Company Settings → **Default Warranty Policy** | Unchanged. |

**Product form:** while the product's own policy or its category policy applies (current
company), the Warranty Configuration tab shows that policy's values readonly
(`warranty_applied_policy_id`, `warranty_policy_*` related fields) instead of the product's own
values, which are hidden, never written and editable again when no policy applies. The pricelist
policy depends on the Sales Order and is not shown on the product. The Product + Pricelist
Warranty Mapping table is no longer on the product form (D1).

## 3. Resolution (Sales Order line, `_warranty_resolve_rule`)

Only lines of **Warranty Applicable** products are resolved (SO confirmation validates; the
Warranty Grouping wizard resolves again and creates the cards).

1. **P1 → P4:** P1 is the order pricelist's policy when its Warranty Applicable is ticked. The
   first level whose policy is **applicable** – active and of the order company or shared – is
   selected. A level without policy, an unticked pricelist, an archived policy or a policy of
   another company continues with the next level.
2. **Configuration error (Q3 B):** a selected policy with Warranty Duration ≤ 0 or no Duration
   Unit raises *Configuration Required* naming the policy and the level (e.g. "selected on:
   Pricelist VIP"); a selected usage-based policy (its basis, else the company basis = Usage)
   without Usage Limit or Usage Unit too.
3. **P5:** no applicable policy at any level → the own values: duration from the product default
   > category default > Company Warranty Settings (else *Configuration Required*); free service
   count / frequency, start criterion and warranty basis from the first own level with a value.
   No policy is linked to the card. The legacy Product + Pricelist mapping lines are **not**
   used (D1).

### Values of a selected policy – no mixing

| Card value | Selected policy (P1–P4) | Empty on the policy (Q2 A) |
|---|---|---|
| Warranty Duration / Unit | policy | configuration error |
| Warranty Basis | policy | Company Warranty Settings |
| Start Criterion | policy Start Date Basis | Company Warranty Settings |
| Usage Limit / Unit | policy | 0 / empty; error when usage-based |
| Free Service Count | policy | 0 (no free services) |
| Free Service Frequency / Unit | policy | empty → due dates spread over the period |
| Free Service Period / Unit (at confirmation) | policy | Company Warranty Settings |
| Schedule Method (at confirmation) | policy | Company Warranty Settings |
| Service Offsets, Auto-create Services, monitoring, payment check | policy | as stored (0 / unticked = disabled); responsible users fall back to the company users (unchanged) |

### Policy Source (Q4 A, D4)

| Level | Policy Source |
|---|---|
| P1 | **Pricelist Warranty Policy** (`pricelist_policy`) |
| P2 | Product Warranty Policy (`product_policy`) |
| P3 | Product Category Policy (`category_policy`) |
| P4 | Company Default Policy (`company_policy`) |
| P5 | Product Default Rule / Product Category Rule / Company Fallback Rule |

Historical sources are kept for existing cards: Product + Pricelist Rule (`pricelist_rule`),
Model / Brand / Customer Type Warranty Policy.

## 4. Card confirmation (free services)

- With a policy: schedule method and free service period from the policy (empty → Company
  Warranty Settings); Auto-create Services = the policy's tick; monitoring snapshot from the
  policy (unchanged).
- Without a policy (P5): schedule method from the product > category > Company Warranty
  Settings; period from the Company Warranty Settings; Auto-create ticked on the product /
  category, else the company setting.
- Due dates: frequency first, then the period. Usage due: usage limit / count. Due alerts,
  expiry reminders and their emails are unchanged.

## 5. Multi-company

- A policy of another company is never applied (all levels); shared policies apply everywhere.
- Product policy per company; pricelist policy checked against the pricelist company (shared
  pricelist: shared policies only); category policy used only for its company (or shared).

## 6. Existing data and compatibility

- **Existing warranty cards and free service entitlements are never recalculated.**
- **Product Brand and Product Model removed** (business owner, 2026-10-19): the `product.brand`
  / `product.model` models, menus, views and access rights, the product Brand / Model fields and
  the policies' legacy Applicable Brands / Models are removed. On upgrade Odoo drops the product
  Brand / Model columns and the policy brand / model links (data lost, accepted); the warranty
  card's own Brand / Model text fields are unchanged. **Calendar Month** is no longer a Schedule
  Method (no record used it).
- **Legacy data kept** (hidden, unused): policy Applies To / Applicable Products / Pricelists /
  Sales Order Type; the pricelists' Customer Type link
  (`product.pricelist.warranty_policy_ids`, not converted to the new pricelist policy); the
  **Product + Pricelist Warranty Mapping** model `warranty.product.pricelist.rule` and all its
  records (D1: retired without conversion; the product field `warranty_pricelist_rule_ids` is
  kept, not shown).
- One-time functions (`data/warranty_policy_migration_data.xml`, once per database through an
  `ir.config_parameter` marker; the manifest version is unchanged, so no versioned migration):
  - `_migrate_legacy_product_policies` – copies the legacy direct product assignments of
    active policies to the product's company-dependent Warranty Policy (policy company, else
    product company); existing values kept; conflicts skipped and logged.
  - `_log_legacy_pricelist_rules` – logs (warning) each active retired mapping line (product,
    pricelist, values, validity) for review; nothing is converted or changed.
- **D5:** the working database's mapping line Samsung AC (Premium) / VIP no longer participates;
  no policy is created or assigned automatically. Until a product / category / VIP policy is
  configured, a new VIP order for this product has no warranty rule (*Configuration Required*).

## 7. Business behaviour (approved)

- A Warranty Applicable pricelist gives the same policy to **every** warranty-applicable product
  of its orders, before their product / category policies; per-product pricelist exceptions are
  no longer possible.
- The order's pricelist when the Warranty Grouping wizard runs decides; orders without a
  pricelist skip P1.
- The product form shows the product / category policy; a card may use the pricelist policy.
- A selected policy gives all values; policies of other companies are never applied; the
  Company Default Warranty Policy (P4) comes before the own values (P5).

## 8. History (replaced designs)

- Until 2026-10-16: the policy's Applies To defined Product, Product Category, Brand, Model,
  Customer Type and Sales Order Type mappings, with priority Product > Model > Brand > Customer
  Type > Category, and free service values resolved per value across levels.
- 2026-10-16: Product + Pricelist Warranty Mapping line (own values, later with a Warranty Policy)
  as level 1. Replaced on 2026-10-17 by the pricelist Warranty Policy (D1–D5).

## Warranty Settings display (approved 2026-10-21)

* General Warranty Settings: when a Default Warranty Policy is selected, its Warranty Basis,
  Warranty Duration / Unit and Start Criterion are shown read-only directly under it (related to
  the selected policy, refreshed when it changes, nothing stored or copied); the Default Warranty
  Basis / Start Criterion / Duration fields are hidden meanwhile and shown as before when no
  policy is selected.
* The company default fields stay the U2 / U3 fallbacks; resolution (`sale_order.py`, P1-P5)
  unchanged; selecting a policy never writes them; existing cards are not recalculated.

### Simplification (2026-10-22, manifest 18.0.1.0.3)

* Free Service Settings: with a Default Warranty Policy, its Free Service Count, Period / Unit,
  Frequency / Unit and Schedule Method are shown read-only (related, nothing stored or copied);
  General block also shows the policy's Usage Limit / Unit for usage-based policies. Values are
  changed on the Warranty Policy only.
* Company fallback fields hidden only where they are not used while a Default Policy is
  selected (dependency review of P1-P5):
  - Default Warranty Duration, Default Free Service Count: hidden (used only by P5, which never
    runs while a valid Default Policy exists).
  - Default Warranty Basis, Start Criterion, Free Service Period, Schedule Method: they fill the
    empty values of **any** selected policy (P1-P4, U2), so they stay visible while the Default
    Policy leaves that value empty and are hidden when it has one. Limitation: a pricelist /
    product / category policy with an empty value still uses the hidden company value.
* Auto-create Services stays a company setting (with a policy the policy's tick applies,
  unchanged).
* Default Warranty Policy: only an active policy of the configured company or a shared one
  (settings domain + `res.company` constraint, checked on change only; existing selections are
  not modified).
* Resolution logic and data unchanged.
