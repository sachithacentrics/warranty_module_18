// Shared content of the AMC technical architecture document (Word and HTML renderers).
// flush(landscape) ends a Word section (ignored by the HTML renderer).
module.exports = function (api) {
  const { run, p, code, b, h1, h2, h3, bullet, note, codeBlock, diagram, table, add, flush } = api;
// =============================================================== 1 overview
add(h1('1. Architecture overview'),
  p('The AMC (Annual Maintenance Contract) solution is implemented as one standalone core module and two optional bridge modules. The core owns the complete commercial and contractual lifecycle (plans, pricing, contracts, entitlements, billing, renewals). The bridges connect it to the warranty solution without modifying any warranty file: they extend warranty models by inheritance and act only on records linked to an AMC.'),
  h2('1.1 Architectural principles'),
  bullet([b('Separation (SRS 2.1 / 2.12): '), run('AMC stages, formulas, visits and billing never live on the warranty card; the core depends only on mail, product, sale_management and stock.')]),
  bullet([b('Reuse of standard Odoo: '), run('quotations / Sales Orders, invoicing on delivered quantities, payments, activities, chatter, Helpdesk, Field Service and worksheets are reused rather than re-implemented.')]),
  bullet([b('Mandatory service chain: '), run('AMC visits are executed through Helpdesk Ticket → Warranty Case → Service Job → Field Service Task (bridge amc_management_service).')]),
  bullet([b('Server-side integrity: '), run('every state, price, schedule and link field is written only by server actions protected by non-serialisable Python marker objects; the UI, imports and RPC cannot forge them.')]),
  bullet([b('Scoped extension: '), run('every override of a shared model calls super() and acts only when an AMC link exists (amc_contract_id, case_type = amc + contract, AMC order lines).')]),
  bullet([b('Idempotent automation: '), run('generation, releases and the daily scheduler can run repeatedly without duplicates.')]),
  h2('1.2 Module layers'),
  ...diagram('d01_layers', 'Module layers and dependencies', 560),
  ...table(['Module', 'Depends on', 'Responsibility'], [
    ['amc_management', 'mail, product, sale_management, stock', 'Plans, billing plans, pricing engine, opportunities, contracts, overrides, quotations, entitlements (visits), billing schedule, lifecycle, scheduler, report'],
    ['amc_management_warranty', 'amc_management, warranty_management', 'Auto-create draft AMC on warranty confirmation, Convert to AMC, warranty units on covered equipment, AMC offer on warranty expiry, smart buttons'],
    ['amc_management_service', 'amc_management, warranty_management_fsm', 'Service requests (ticket + AMC case), AMC eligibility, Service Job / worksheet / completion / cancellation hooks, pending AMC services on tickets, AMC ticket tag'],
    ['warranty_meta_dependencies', 'all custom addons', 'Installs the complete solution in one step'],
  ], [2500, 2600, 3926]),
  note('No warranty module depends on an AMC module, so the AMC modules can be installed, upgraded or removed independently. Neither bridge is auto_install.'),
  h2('1.3 Component view of the core'),
  ...diagram('d02_components', 'Core components and their standard Odoo collaborators', 600),
);

// =============================================================== 2 code map
add(h1('2. Code organisation'),
  ...codeBlock([
    'amc_management/                    (one class per file, file = model technical name)',
    '  __manifest__.py                  18.0.1.3.0, OPL-1, data load order',
    '  controllers/amc_management.py    Configuration > Documents pages (manual, architecture, video)',
    '  models/',
    '    amc_plan.py                    amc.plan (+ constants PRICING_METHODS, ACTIVATION_TRIGGERS ...)',
    '    amc_billing_plan.py            amc.billing.plan',
    '    amc_pricing_formula.py         amc.pricing.formula (pricing engine)',
    '    amc_pricing_tier.py            amc.pricing.tier',
    '    amc_pricing_factor.py          amc.pricing.factor',
    '    amc_pricing_rounding.py        amc.pricing.rounding',
    '    amc_safe_expression.py         AST-based controlled expression evaluator',
    '    amc_opportunity.py             amc.opportunity',
    '    amc_contract.py                amc.contract: lifecycle, scheduler',
    '    amc_contract_line.py           amc.contract.line (covered equipment)',
    '    amc_contract_visit.py          amc.contract.visit (entitlements)',
    '    amc_billing_line.py            amc.billing.line (billing schedule)',
    '    amc_price_override.py          amc.price.override',
    '    sale_order.py, sale_order_line.py   quotation guards and hooks',
    '    account_move.py                account.move._invoice_paid_hook',
    '    res_company.py, res_config_settings.py   AMC settings, AMC Enabled check',
    '    ir_ui_menu.py                  hides the AMC app when AMC Enabled is off',
    '  wizard/                          <transient>.py + <transient>_views.xml',
    '    amc_pricing_preview(_line)     price preview',
    '    amc_opportunity_lost           lost reason',
    '    amc_contract_cancel            cancellation',
    '    amc_contract_reason            hold / close reason',
    '    amc_contract_visit_action      visit completion / cancellation',
    '    amc_price_override_reject      override rejection',
    '  views/                           <model>_views.xml (views, actions, model menus),',
    '                                   amc_management_menus.xml (root, sections, documents)',
    '  report/                          amc_contract_reports.xml, amc_contract_templates.xml',
    '  data/                            amc_billing_plan, ir_sequence, product_product, ir_cron _data.xml',
    '  security/                        amc_management_groups.xml, <model>_security.xml, ir.model.access.csv',
    '  tests/                           test_amc_lifecycle, test_amc_pricing, test_amc_security,',
    '                                   test_amc_documentation',
    '  docs/                            00-28, user manual, this document',
    'amc_management_warranty/models/    res_company, res_config_settings, amc_contract,',
    '                                   amc_contract_line, amc_opportunity, warranty_card, warranty_unit',
    'amc_management_service/models/     amc_contract_visit, warranty_case, warranty_service_job,',
    '                                   helpdesk_ticket',
    'amc_management_service/wizard/     amc_service_request (+ _views.xml)',
  ]),
);

// =============================================================== 3 data model
add(h1('3. Data model'),
  p('The ERD on the next page shows the AMC models and their links to Sales, the warranty card / unit and the warranty service chain. All transactional AMC models carry company_id (stored) for multi-company record rules.'),
  h2('3.1 Models'),
  ...table(['Model', 'Purpose', 'Key fields'], [
    ['amc.plan', 'AMC type (e.g. Retail / Project AMC)', 'service_basis, visit_count, frequency_value/unit, usage_interval/unit, included_free_services, visit_planning_mode, alert_days, grace_days, auto_mark_missed, pricing_method, billing_plan_id, start_rule, duration_value/unit, renewal_rule, renewal_notice_days, activation_trigger, pricelist_ids, product_ids, category_ids'],
    ['amc.billing.plan', 'How the value is invoiced', 'billing_frequency (upfront / monthly / quarterly / half_yearly / annual / per_visit), billing_timing (advance / arrears), interval_months'],
    ['amc.pricing.formula', 'Versioned price formula of a plan', 'version, state (draft / active / archived), method, effective_from/to, currency_id, method parameters, hybrid_expression, min_price, max_price, rounding_step/method, tier_ids, factor_ids, rounding_rule_ids'],
    ['amc.opportunity', 'Pre-sales follow-up', 'state (new / offer_sent / won / lost), plan_id, expected_quantity / value, contract_ids'],
    ['amc.contract', 'The AMC contract', 'state (9 values), partner_id, site_id, plan_id, line_ids, pricelist_id, currency_id, start_date, contract_months (snapshot), end_date, expected_usage, price snapshot fields, sale_order_id, activation_trigger, visit statistics, next_visit_date, billing_line_ids, hold/close/expiring fields, renewal_of_id'],
    ['amc.contract.line', 'Covered equipment', 'product_id, serial_id, quantity (whole units), site_id, original_value / currency, equipment_value, (bridge) warranty_unit_id'],
    ['amc.contract.visit', 'One entitlement of one covered unit', 'visit_type (preventive / free_service), sequence_no/total, unit_no, due_date, usage_due/unit, alert_date, grace_end_date, scheduled_date, state (7 values), due_status, completion evidence; (bridge) warranty_case_id, service_job_id, task_id, worksheet_id'],
    ['amc.billing.line', 'One billing period', 'sequence, sale_line_id, amount, date, period_start/end, visit_id, state (planned / released / cancelled), invoiced (computed)'],
    ['amc.price.override', 'Price / pricelist override request', 'override_type, original / requested values, reason, state, requested_by_id, decided_by_id'],
  ], [2200, 2100, 4726]),
  h2('3.2 Integrity constraints'),
  bullet([code('UNIQUE(contract_id, line_id, visit_type, unit_no, sequence_no)'), run(' on amc.contract.visit – no duplicate entitlement.')]),
  bullet([code('UNIQUE(name, company_id)'), run(' on amc.plan.')]),
  bullet('Covered quantity > 0 and whole; a serial line covers quantity 1; a serial / warranty unit belongs to one open contract only (predecessor and renewal excepted); plan applicability by pricelist, product and category.'),
  bullet('Plan: counts ≥ 0, visits fit into the duration at the frequency, Per Preventive Visit billing requires activation on SO confirmation.'),
  bullet('Formula: non-negative amounts, min ≤ max, effective_to ≥ effective_from, valid Hybrid expression, tiers without gaps / overlaps, unique factor per product / category, unique rounding rule per currency.'),
  bullet('Company consistency: plan / contract, warranty unit / contract, AMC case / contract.'),
);
flush(false);
add(h2('3.3 Entity-relationship diagram'), ...diagram('d03_erd', 'AMC entity-relationship diagram (core and bridges)', 900, 520));
flush(true);

// =============================================================== 4 lifecycle
add(h1('4. State machines', true),
  h2('4.1 Contract lifecycle'),
  ...diagram('d04_contract_states', 'amc.contract state machine', 520, 560),
  ...table(['Transition', 'Method', 'Guard', 'Side effects'], [
    ['draft → quotation', 'action_create_quotation', 'Coordinator + Salesman; priced today; billing plan; no open quotation / override request; row lock', 'sale.order created with locked lines (qty = periods)'],
    ['quotation → active / awaiting_payment', 'sale.order.action_confirm → _amc_on_order_confirmed (sudo)', 'order = contract open quotation', 'price frozen, billing schedule; activation or period 1 released'],
    ['awaiting_payment → active', 'account.move._invoice_paid_hook → _amc_on_invoice_paid', 'invoice has lines of the AMC order', '_amc_activate'],
    ['* → active (activation)', '_amc_activate', 'state quotation / awaiting_payment; row lock', 'start date, visits, billing dates, due release, predecessor renewed, expiring check'],
    ['active / expiring → on_hold', '_amc_hold(reason)', 'Manager, reason', 'hold fields; planning / requests / alerts blocked'],
    ['on_hold → active', 'action_resume', 'Manager; end not passed', 'expiring re-check'],
    ['active → expiring', '_amc_check_expiring (cron / activation)', 'end − notice ≤ today', 'to-do; Auto Offer → _amc_create_renewal'],
    ['running → closed', '_amc_close(reason, automatic)', 'Manager or scheduler after end', '_amc_end_entitlements (visits expired, planned billing cancelled)'],
    ['running / closed → renewed', '_amc_mark_renewed', 'renewal activated after end, or running renewal at end', 'entitlements ended'],
    ['draft / quotation / awaiting → cancelled', 'action_cancel_contract(reason)', 'Manager; no posted invoice', 'SO cancelled, billing cancelled'],
  ], [2000, 2300, 2400, 2326]),
  h2('4.2 Entitlement (visit) lifecycle'),
  ...diagram('d05_visit_states', 'amc.contract.visit state machine', 600, 420),
  note('Consumption (_amc_consume) is the only path to completed. It validates the open state, a running contract, the coverage period and – for usage-based visits – a positive, non-decreasing usage reading, and is called either by manual completion (core without service bridge) or inside the warranty job completion savepoint (service bridge).'),
);
flush(false);

// =============================================================== 5 process flows (landscape)
add(h1('5. Process flows', true),
  h2('5.1 Sell, price and activate'),
  ...diagram('d06_sell_activate', 'Sequence – pricing, quotation, confirmation and activation', 900, 470),
  h2('5.2 AMC visit execution through the warranty service chain'),
  ...diagram('d07_service_chain', 'Sequence – service request to consumption (amc_management_service)', 900, 380),
);
flush(true);

// =============================================================== 6 engines
add(h1('6. Core engines', true),
  h2('6.1 Pricing engine'),
  ...diagram('d09_pricing', 'Pricing pipeline (amc.pricing.formula._amc_compute_price)', 300, 560),
  ...table(['Method', 'Calculation'], [
    ['fixed', 'fixed_amount'],
    ['per_unit', 'Σ unit_rate × quantity × factor(line)'],
    ['per_visit', 'visit_rate × visit_count × covered quantity (entitlements, not physical visits)'],
    ['percentage', 'Σ equipment_value × percentage / 100 × factor(line)'],
    ['tiered', 'rate of the tier containing quantity (or site count) × that basis'],
    ['site', 'site_rate × number of distinct sites'],
    ['usage', 'usage_base + usage_rate × expected usage'],
    ['hybrid', 'controlled expression over equipment_value, quantity, visit_count, contract_months, usage, site_count, factor, min_price, max_price'],
  ], [2000, 7026]),
  p([b('Snapshot. '), run('action_compute_price stores formula, version, method, formula currency and amount, exchange rate, conversion date, calculated price and the textual breakdown on the contract. The quotation is refused if the snapshot is not from today (approved C3); confirmation freezes it (price_approved_date).')]),
  p([b('Controlled expression (amc_safe_expression). '), run('The Hybrid expression is parsed with ast.parse(mode="eval") and checked against a whitelist: numeric constants, approved variable names, + − * /, unary ±, and calls of min, max, round, abs with positional arguments. Attributes, subscripts, comparisons, power, lambdas, strings and any other name are rejected; length is limited to 500 characters; evaluation is a custom tree walk – eval / safe_eval are never used; division by zero raises a business error.')]),
  h2('6.2 Entitlement generation'),
  p([code('amc.contract._amc_generate_visits()'), run(' runs once at activation (idempotent: returns existing visits). For every line and every covered unit (quantity rounded to whole units):')]),
  bullet([b('Period plans: '), run('Visit Count preventive visits; due date n = start + n × (12 / frequency) months (fractional months as 30-day days), capped at end_date.')]),
  bullet([b('Usage plans: '), run('usage_due n = n × usage_interval, no due date.')]),
  bullet([b('Free services: '), run('Included Free Services on-demand entitlements without due date.')]),
  p('Monitoring fields are stored computes (alert_date = due − alert days for Alert-Driven plans, grace_end_date = due + grace days); due_status is written by actions and the scheduler only when it changes.'),
  h2('6.3 Billing engine'),
  ...table(['Step', 'Method', 'Detail'], [
    ['Quotation lines', '_amc_quotation_lines', 'quantity = billing periods; unit price = value / periods; final period absorbs the rounding difference'],
    ['Schedule', '_amc_generate_billing', 'one amc.billing.line per ordered unit, mapped to its sale.order.line (on SO confirmation)'],
    ['Dates', '_amc_schedule_billing(release)', 'upfront: start; periodic: advance = period start, arrears = period end (capped at end); per visit: linked preventive visit'],
    ['Release', 'amc.billing.line._amc_release', 'planned → released; sale line qty_delivered = released count (contract marker); chatter log'],
    ['Invoicing', 'action_create_invoice', 'sale.order._create_invoices() of the released quantities – draft only'],
    ['Activation on payment', 'account.move._invoice_paid_hook', 'Awaiting Payment contract of the invoiced AMC order → _amc_activate'],
  ], [1900, 2700, 4426]),
  note('Billing reuses the standard "invoice on delivered quantity" mechanism of a manual service product, so taxes, fiscal positions, journals, payment terms and accounting entries remain 100 % standard Odoo.'),
  h2('6.4 Scheduler'),
  ...diagram('d08_scheduler', 'Daily scheduler (ir_cron_amc_daily)', 560, 520),
);

// =============================================================== 7 integration
add(h1('7. Integration architecture'),
  h2('7.1 Extension points on shared models'),
  ...table(['Model.method', 'Module', 'Behaviour', 'Scope guard'], [
    ['sale.order.create / write / copy / action_update_prices', 'core', 'AMC quotations created only by the contract; customer, pricelist, currency locked; no copy', 'amc_contract_id set'],
    ['sale.order.line.create / write / unlink', 'core', 'quantities, prices, discount, delivered quantity locked', 'order has amc_contract_id; contract marker bypass'],
    ['sale.order.action_confirm', 'core', 'expired AMC quotation refused; contract hook (sudo)', 'AMC orders'],
    ['sale.order._action_cancel', 'core', 'refused for activated contracts; Draft again before activation', 'AMC orders'],
    ['account.move._invoice_paid_hook', 'core', 'activation on payment', 'invoice lines of AMC orders'],
    ['warranty.card.action_confirm_warranty', 'warranty bridge', 'draft AMC (savepoint, never raises)', 'company mode ≠ none'],
    ['warranty.card._warranty_apply_expiry', 'warranty bridge', 'AMC offer activity', 'setting on, card newly expired, no AMC'],
    ['warranty.case._warranty_run_checks', 'service bridge', 'AMC eligibility', "case_type = 'amc' and amc_contract_id"],
    ['warranty.case.write', 'service bridge', 'release visits on rejected / closed', 'cases with AMC visits'],
    ['warranty.service.job.action_confirm_job', 'service bridge', 'visits In Progress, job / task links', 'job case has AMC contract'],
    ['warranty.service.job._warranty_worksheet_lines / _warranty_create_worksheets', 'service bridge', 'one worksheet per AMC visit; usage flags', 'idem'],
    ['warranty.service.job._warranty_visit_completion_problems', 'service bridge', 'AMC consumption checks added', 'idem'],
    ['warranty.service.job._warranty_complete_case', 'service bridge', 'consumption inside the completion savepoint', 'idem'],
    ['warranty.service.job._warranty_cancel', 'service bridge', 'visits back to Scheduled', 'idem'],
    ['helpdesk.ticket (compute)', 'service bridge', 'pending AMC visits of the customer / site / product / serial', 'read-only'],
  ], [3100, 1400, 2700, 1826]),
  h2('7.2 AMC eligibility (service bridge)'),
  p([code('warranty.case._amc_run_checks()'), run(' replaces the warranty-card checks for AMC cases with a contract and returns the same tuple as the warranty engine (result, steps, payment values, failure values), so Check Eligibility, Approve Case and the confirmation revalidation of the Service Job work unchanged. Checks: contract Active or Expiring; ticket date (service date of the warranty engine) inside the contract period; visits linked, of this contract and still Scheduled / In Progress; overdue receivables shown as information.')]),
  h2('7.3 Warranty integration (warranty bridge)'),
  bullet([code('_amc_auto_create'), run(' – after a successful confirmation, per company mode: Draft opportunity or Draft contract (units as lines, start = warranty end + 1 if ahead); savepoint + log on failure; never twice per card.')]),
  bullet([code('action_convert_to_amc'), run(' – Confirmed / Expired cards; opens the open AMC of the card instead of creating a second one.')]),
  bullet([code('amc.contract.line.warranty_unit_id'), run(' – unit of the customer and company, state Active / Expired / Suspended, one open contract per unit.')]),
  bullet([code('_warranty_apply_expiry'), run(' – optional to-do for the card\'s service alert users.')]),
);

// =============================================================== 8 security
add(h1('8. Security architecture'),
  ...diagram('d10_security', 'Roles and write guards', 470, 440),
  h2('8.1 Access control'),
  ...table(['Model', 'User', 'Coordinator', 'Manager', 'Approver', 'Helpdesk / FSM*'], [
    ['amc.plan, amc.billing.plan, amc.pricing.*', 'R', 'R', 'RWCD', 'R', 'R (plan)'],
    ['amc.opportunity', 'RWC', 'RWC', 'RWCD', 'RWC', '—'],
    ['amc.contract', 'RWC', 'RWC', 'RWCD', 'RWC', 'R'],
    ['amc.contract.line', 'RWCD', 'RWCD', 'RWCD', 'RWCD', 'R'],
    ['amc.contract.visit', 'R', 'RW', 'RW', 'R', 'R'],
    ['amc.billing.line', 'R', 'R', 'R', 'R', '—'],
    ['amc.price.override', 'R', 'RWC', 'RWC', 'RW', '—'],
  ], [2900, 1000, 1200, 1200, 1100, 1626]),
  p('* granted by amc_management_service. Record rules restrict every transactional model to company_id in company_ids; configuration models allow shared (company-less) records.'),
  h2('8.2 Protected fields (marker pattern)'),
  p('Each model keeps a module-level object() as marker (_CONTRACT_MARKER, _FORMULA_MARKER, _OVERRIDE_MARKER, _OPPORTUNITY_MARKER). Server code writes protected fields with with_context(amc_contract_marker=_CONTRACT_MARKER); write() / create() refuse protected keys when the context value is not that exact object. A Python object cannot be serialised into a JSON-RPC context, so neither the web client, imports nor external RPC can bypass the guard, and sudo() alone does not pass it either.'),
  ...codeBlock([
    "PROTECTED_FIELDS = {'state', 'price_state', 'calculated_price', 'sale_order_id', 'contract_months',",
    "                    'renewal_of_id', 'close_reason', ... }",
    'def write(self, vals):',
    "    if self.env.context.get('amc_contract_marker') is not _CONTRACT_MARKER:",
    '        if PROTECTED_FIELDS & set(vals): raise UserError(...)',
    '    return super().write(vals)',
  ]),
  h2('8.3 Privilege elevation (sudo) boundaries'),
  bullet('Only after an explicit group check in the calling action, or for system consequences of an authorised standard event (SO confirmation by a salesman, payment by an accountant, job completion by a technician).'),
  bullet('Internal writes of billing lines and entitlements (users have no write right on billing lines).'),
  bullet('Cross-record chatter logs and activities.'),
);

// =============================================================== 9 transactions
add(h1('9. Transactions, concurrency and reliability'),
  ...table(['Concern', 'Mechanism'], [
    ['Double click / concurrent quotation, activation, renewal', '_amc_lock(): parameterised SELECT … FOR UPDATE on the contract row'],
    ['Atomic consumption with job completion', 'consumption in _warranty_complete_case, inside the warranty completion savepoint; any AMC error rolls back the whole completion'],
    ['Warranty confirmation must not fail because of AMC', 'auto-create inside a savepoint; error logged on the card'],
    ['Scheduler failures', 'one savepoint per contract; _logger.exception; next contract continues'],
    ['Duplicate generation', 'visits generated only if none exist; billing only if no non-cancelled line exists; unique constraint'],
    ['Duplicate release / alert / renewal', 'state filters (planned only), alert_sent flag, one open renewal check'],
  ], [3600, 5426]),
);

// =============================================================== 10 config
add(h1('10. Configuration parameters'),
  ...table(['Level', 'Parameter', 'Effect'], [
    ['Company', 'amc_activation_trigger', 'sale_confirmation / payment (plan can override)'],
    ['Company', 'amc_product_id', 'AMC service product (service, invoice on delivery, manual delivery)'],
    ['Company', 'amc_default_plan_id / _pricelist_id / _billing_plan_id / _start_rule / _renewal_rule / _alert_days', 'defaults'],
    ['Company (W)', 'amc_auto_create_mode, amc_offer_on_warranty_expiry', 'warranty integration'],
    ['Company (FSM)', 'warranty_draft_job_team_id, warranty_signoff_required, warranty_case_approver_ids', 'reused by AMC service requests'],
    ['Plan', 'visit / frequency / usage / free services / planning / grace / missed / renewal / duration / start rule', 'entitlements and lifecycle'],
    ['Formula version', 'method parameters, min / max / rounding, factors, tiers, effective dates', 'pricing'],
    ['Product', 'warranty_worksheet_template_id', 'worksheet template of AMC visits'],
    ['Helpdesk', 'SLA policy on tag "AMC"', 'AMC response / resolution SLA'],
  ], [1700, 3700, 3626]),
);

// =============================================================== 11 migration / deployment / testing
add(h1('11. Deployment and testing'),
  h2('11.1 Data migration'),
  p('None: the AMC modules are not yet used in production, so they ship without migration scripts. A database with an older AMC version is reinstalled (or upgraded on a copy and checked) rather than migrated.'),
  h2('11.2 Deployment'),
  ...codeBlock([
    'pg_dump -Fc <db> > before_amc_110.dump   (+ filestore)',
    'odoo-bin -c odoo.conf -d <copy> -u amc_management -i amc_management_warranty,amc_management_service --stop-after-init',
    'validate (docs/14 §4), then repeat on the target database with the server stopped',
  ]),
  h2('11.3 Test architecture'),
  ...table(['Suite', 'Base class', 'Tests', 'Focus'], [
    ['amc_management/tests/test_amc_lifecycle.py', 'AmcCommon (AccountTestInvoicingCommon)', '28', 'entitlements, billing, lifecycle, scheduler, report'],
    ['amc_management/tests/test_amc_pricing.py', 'AmcCommon', '9', 'pricing methods, governance, expression, override'],
    ['amc_management/tests/test_amc_security.py', 'AmcCommon', '10', 'roles, RPC protection, multi-company, AMC Enabled, non-AMC regression'],
    ['amc_management_warranty/tests/test_amc_warranty.py', 'TransactionCase', '10', 'auto-create, conversion, units, expiry offer, AMC Enabled'],
    ['amc_management_service/tests/test_amc_service_chain.py', 'AmcCommon', '8', 'end-to-end Helpdesk → Job → FSM → sign-off → consumption'],
  ], [3500, 2300, 800, 2426]),
  p('Result on 2026-11-07: 65 / 65 passed (68 with the 3 documentation tests); 866 warranty regression tests with the AMC modules installed: 860 passed, 6 failures identical on a database without any AMC module (pre-existing).'),
);

// =============================================================== 12 extension guide
add(h1('12. Extension guide'),
  ...table(['Need', 'Extend'], [
    ['Allow / forbid manual visit completion', 'amc.contract.visit._amc_manual_completion_allowed()'],
    ['Block cancellation of visits in another process', 'amc.contract.visit._amc_check_not_in_service()'],
    ['Copy more data to renewals', 'amc.contract.line._amc_renewal_values(), amc.contract._amc_create_renewal()'],
    ['Additional activation side effects', 'amc.contract._amc_activate() (call super first)'],
    ['Visit generation rules (e.g. offsets)', 'amc.contract._amc_generate_visits() / amc.plan._amc_visit_interval_months()'],
    ['New pricing variable', 'HYBRID_VARIABLES and the values dict in _amc_compute_price'],
    ['Additional scheduler step', 'amc.contract._amc_daily(today) (one contract, inside its savepoint)'],
    ['New protected field', 'add it to PROTECTED_FIELDS / PROTECTED_VISIT_FIELDS and write it with the marker'],
  ], [3500, 5526]),
  note('Keep new logic scoped to AMC records, call super() in every override, write protected fields only through the marker helpers (_marked) and add a test with a TC identifier to the relevant suite.'),
);
flush(false);
};
