// Mermaid sources of the AMC technical architecture diagrams (rendered to PNG by render.py).
module.exports = {
  d01_layers: `flowchart TB
    subgraph L4["AMC bridges (optional)"]
      W["amc_management_warranty<br/>draft AMC, Convert to AMC,<br/>warranty units, expiry offer"]
      S["amc_management_service<br/>service request, AMC eligibility,<br/>job / worksheet / completion hooks"]
    end
    subgraph L3["AMC core"]
      A["amc_management 18.0.1.1.0<br/>plans, pricing, contracts, visits,<br/>billing schedule, lifecycle, report"]
    end
    subgraph L2["Warranty solution (unchanged)"]
      WM["warranty_management"] --> WH["warranty_management_helpdesk"] --> WF["warranty_management_fsm"]
    end
    subgraph L1["Odoo 18 standard"]
      O1["mail / product / stock"]
      O2["sale_management / account"]
      O3["helpdesk / industry_fsm / worksheet"]
    end
    A --> O1 & O2
    W --> A
    W --> WM
    S --> A
    S --> WF
    WF --> O3
    META["warranty_meta_dependencies"] -.installs.-> W & S`,

  d02_components: `flowchart LR
    subgraph CORE["amc_management"]
      PL["amc.plan"] --> FO["amc.pricing.formula<br/>tier / factor / rounding"]
      PL --> BP["amc.billing.plan"]
      OP["amc.opportunity"] --> CO["amc.contract"]
      CO --> LI["amc.contract.line"]
      CO --> VI["amc.contract.visit"]
      CO --> BL["amc.billing.line"]
      CO --> OV["amc.price.override"]
      PR["amc.pricing.preview (wizard)"] --> FO
      SE["amc_safe_expression"] --> FO
    end
    subgraph STD["Odoo standard"]
      SO["sale.order / line"]
      AM["account.move"]
      CR["ir.cron"]
    end
    CO <--> SO
    BL --> SO
    AM -->|"_invoice_paid_hook"| CO
    CR -->|"_cron_amc_daily"| CO`,

  d03_erd: `erDiagram
    AMC_PLAN ||--o{ AMC_PRICING_FORMULA : "versions"
    AMC_BILLING_PLAN ||--o{ AMC_PLAN : "billing"
    AMC_OPPORTUNITY ||--o{ AMC_CONTRACT : "won"
    AMC_PLAN ||--o{ AMC_CONTRACT : "plan"
    AMC_CONTRACT ||--o{ AMC_CONTRACT_LINE : "equipment"
    AMC_CONTRACT ||--o{ AMC_CONTRACT_VISIT : "entitlements"
    AMC_CONTRACT_LINE ||--o{ AMC_CONTRACT_VISIT : "per unit"
    AMC_CONTRACT ||--o{ AMC_BILLING_LINE : "schedule"
    AMC_CONTRACT ||--o{ AMC_PRICE_OVERRIDE : "overrides"
    AMC_CONTRACT ||--o{ AMC_CONTRACT : "renewal_of"
    AMC_CONTRACT ||--o| SALE_ORDER : "quotation"
    SALE_ORDER_LINE ||--o{ AMC_BILLING_LINE : "periods"
    WARRANTY_CARD ||--o{ AMC_CONTRACT : "source card"
    WARRANTY_UNIT ||--o{ AMC_CONTRACT_LINE : "covered unit"
    WARRANTY_CASE ||--o{ AMC_CONTRACT_VISIT : "executes"
    WARRANTY_SERVICE_JOB ||--o{ AMC_CONTRACT_VISIT : "service job"`,

  d04_contract_states: `stateDiagram-v2
    [*] --> draft
    draft --> quotation: action_create_quotation
    quotation --> draft: SO cancelled
    quotation --> active: SO confirmed (trigger SO)
    quotation --> awaiting_payment: SO confirmed (trigger payment)
    awaiting_payment --> active: _invoice_paid_hook
    awaiting_payment --> draft: SO cancelled
    draft --> cancelled: action_cancel_contract
    quotation --> cancelled
    awaiting_payment --> cancelled
    active --> on_hold: _amc_hold
    expiring --> on_hold
    on_hold --> active: action_resume
    active --> expiring: _amc_check_expiring
    active --> closed: _amc_close / end date
    expiring --> closed
    on_hold --> closed
    expiring --> renewed: _amc_mark_renewed
    active --> renewed
    closed --> renewed: late renewal`,

  d05_visit_states: `stateDiagram-v2
    [*] --> pending: _amc_generate_visits (activation)
    pending --> scheduled: planned date / service request
    scheduled --> pending: date cleared / case rejected or closed
    scheduled --> in_progress: Service Job confirmed
    in_progress --> scheduled: Service Job cancelled
    in_progress --> completed: job completed + sign-off (_amc_consume)
    pending --> completed: manual completion (core only)
    pending --> missed: cron after grace period
    missed --> pending: action_reopen
    pending --> cancelled: _amc_cancel
    scheduled --> cancelled
    missed --> cancelled
    pending --> expired: contract closed / renewed
    scheduled --> expired
    in_progress --> expired`,

  d06_sell_activate: `sequenceDiagram
    autonumber
    actor C as Coordinator
    participant K as amc.contract
    participant F as amc.pricing.formula
    participant S as sale.order
    participant B as amc.billing.line
    participant V as amc.contract.visit
    participant M as account.move
    C->>K: action_compute_price()
    K->>F: _amc_compute_price(lines, currency, date, months, usage)
    F-->>K: price + snapshot + breakdown
    C->>K: action_create_quotation() [row lock]
    K->>S: create (marker context, locked lines)
    S->>K: action_confirm() -> _amc_on_order_confirmed (sudo)
    K->>B: _amc_generate_billing()
    alt trigger = SO confirmation
      K->>K: _amc_activate()
      K->>V: _amc_generate_visits()
      K->>B: _amc_schedule_billing() + release due periods
    else trigger = payment
      K->>B: release period 1 (qty_delivered +1)
      C->>S: Create Invoice -> post -> payment
      M->>K: _invoice_paid_hook -> _amc_on_invoice_paid -> _amc_activate()
    end`,

  d07_service_chain: `sequenceDiagram
    autonumber
    actor C as Coordinator
    participant V as amc.contract.visit
    participant WZ as amc.service.request.wizard
    participant T as helpdesk.ticket
    participant CA as warranty.case (AMC)
    participant J as warranty.service.job
    participant P as project.task (FSM)
    actor TE as Technician
    C->>WZ: Create Service Request (visits)
    WZ->>V: _amc_service_problems()
    WZ->>T: create (tag AMC) or link existing
    WZ->>CA: create(case_type=amc, amc_contract_id)
    WZ->>V: _amc_link_case -> scheduled
    CA->>CA: _warranty_run_checks -> _amc_run_checks (eligible)
    CA->>J: action_prepare_service_job
    J->>J: action_confirm_job (revalidation)
    J->>P: Field Service visit + worksheets (1 per AMC visit)
    J->>V: in_progress (job, task, worksheet)
    TE->>P: worksheet, usage, signature, Complete Visit
    P->>J: _warranty_complete_visit (savepoint)
    J->>V: _warranty_complete_case -> _amc_consume -> completed
    V->>V: per-visit billing release`,

  d08_scheduler: `flowchart TD
    CRON["ir_cron_amc_daily<br/>amc.contract._cron_amc_daily(today)"] --> LOOP{"for each contract<br/>Active / Expiring / On Hold"}
    LOOP --> SP["savepoint per contract"]
    SP --> R["_amc_release_due_billing:<br/>planned lines with date <= today"]
    R --> E["_amc_check_expiring:<br/>end - notice <= today -> expiring,<br/>to-do, Auto Offer renewal"]
    E --> END{"end_date < today?"}
    END -->|"renewal running"| RN["_amc_mark_renewed"]
    END -->|"no renewal"| CL["_amc_close (automatic)"]
    END -->|"no"| NX["next contract"]
    SP -. "exception" .-> LOG["_logger.exception, continue"]
    LOOP --> VIS["amc.contract.visit._cron_amc_visits(today)"]
    VIS --> DS["due indicator: upcoming / due / overdue"]
    VIS --> AL["alert to-do (alert mode, once)"]
    VIS --> MS["missed after grace (if enabled)"]`,

  d09_pricing: `flowchart TB
    IN["lines: product, quantity,<br/>equipment value, site<br/>+ usage, months"] --> FV["formula in force<br/>plan._amc_pricing_formula(date)"]
    FV --> MT{"method"}
    MT --> M1["fixed / per_unit / per_visit /<br/>percentage / tiered / site / usage"]
    MT --> M2["hybrid:<br/>amc_safe_expression<br/>(AST whitelist)"]
    M1 & M2 --> FA["x product / category factors"]
    FA --> MM["min / max price"]
    MM --> CV["currency conversion<br/>(rate of pricing date)"]
    CV --> RD["rounding: formula step or<br/>target-currency rule"]
    RD --> OUT["price + snapshot + breakdown"]`,

  d10_security: `flowchart TB
    U["AMC User<br/>read; prepare Draft"] --> CO["AMC Coordinator<br/>price, quote, invoice, plan,<br/>service request, renew"]
    CO --> MA["AMC Manager<br/>configure, hold, resume,<br/>close, cancel, reopen"]
    U --> AP["AMC Approver<br/>approve overrides (not own)"]
    HD["Helpdesk user / FSM user"] -. "read AMC records (service bridge)" .-> U
    subgraph G["Guards on every write"]
      MK["Python marker objects<br/>(_CONTRACT_MARKER, ...)<br/>cannot be sent by RPC"]
      RR["record rules: company_id in company_ids"]
      GC["_amc_check_group in actions"]
    end`,
};
