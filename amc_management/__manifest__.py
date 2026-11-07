{
    'name': 'AMC Management',
    'version': '18.0.1.3.1',
    'category': 'Services/AMC',
    'summary': 'Annual Maintenance Contracts: plans, pricing, contracts, visits, billing and '
               'renewals',
    'description': """
AMC Management (separate module, SRS 2.1 / 2.12 / 9.9)
======================================================
Standalone AMC application, independent of Warranty Management (optional bridges:
amc_management_warranty, amc_management_service). Developed phase by phase:

* A1 - application, settings and company defaults, security groups, multi-company rules,
  AMC Plans (Visit Count and Included Free Services per covered equipment line), Billing Plans,
  multi-currency pricelist resolution.
* A2 - pricing formula versions (8 SRS methods, controlled Hybrid expression, tiers, factors,
  effective dates, currency conversion, min / max, rounding), price preview.
* A3 - AMC opportunities, contracts with covered equipment, contract pricing (engine snapshot),
  price / pricelist override approval, standard quotation, activation trigger.
* A4 - service entitlements generated at activation (preventive visits per covered unit and
  included free services), due / overdue / missed monitoring, alert activities, manual
  completion with usage capture, next visit, AMC Visit Schedule report.
* A5 - billing schedule from the Billing Plan (upfront, periodic in advance / arrears, per
  preventive visit) releasing periods to the standard Sales invoicing; activation on payment
  of the first invoice.
* A6 - On Hold / Resume, Expiring (renewal notice), Renew (linked renewal contract), Closed
  and Renewed, daily scheduler.

Documentation: docs/00_AMC_Documentation_Index.md
""",
    'depends': ['mail', 'product', 'sale_management', 'stock'],
    'data': [
        'security/amc_management_groups.xml',
        'security/amc_plan_security.xml',
        'security/amc_billing_plan_security.xml',
        'security/amc_pricing_formula_security.xml',
        'security/amc_pricing_tier_security.xml',
        'security/amc_pricing_factor_security.xml',
        'security/amc_pricing_rounding_security.xml',
        'security/amc_opportunity_security.xml',
        'security/amc_contract_security.xml',
        'security/amc_contract_line_security.xml',
        'security/amc_price_override_security.xml',
        'security/amc_contract_visit_security.xml',
        'security/amc_billing_line_security.xml',
        'security/ir.model.access.csv',
        'data/amc_billing_plan_data.xml',
        'data/ir_sequence_data.xml',
        'data/product_product_data.xml',
        'data/ir_cron_data.xml',
        'report/amc_contract_templates.xml',
        'report/amc_contract_reports.xml',
        'views/amc_management_menus.xml',
        'views/amc_billing_plan_views.xml',
        'views/amc_plan_views.xml',
        'views/amc_pricing_formula_views.xml',
        'views/amc_opportunity_views.xml',
        'views/amc_contract_views.xml',
        'views/amc_price_override_views.xml',
        'views/amc_contract_visit_views.xml',
        'views/sale_order_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/amc_pricing_preview_views.xml',
        'wizard/amc_opportunity_lost_views.xml',
        'wizard/amc_contract_cancel_views.xml',
        'wizard/amc_contract_reason_views.xml',
        'wizard/amc_price_override_reject_views.xml',
        'wizard/amc_contract_visit_action_views.xml',
    ],
    'application': True,
    'installable': True,
    'license': 'OPL-1',
}
