{
    'name': 'AMC Management',
    'version': '18.0.1.0.0',
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
""",
    'depends': ['mail', 'product', 'sale_management', 'stock'],
    'data': [
        'security/amc_security.xml',
        'security/ir.model.access.csv',
        'data/amc_billing_plan_data.xml',
        'data/amc_contract_data.xml',
        'views/amc_billing_plan_views.xml',
        'views/amc_plan_views.xml',
        'views/amc_pricing_formula_views.xml',
        'wizard/amc_pricing_preview_views.xml',
        'views/amc_contract_views.xml',
        'views/amc_opportunity_views.xml',
        'views/sale_order_views.xml',
        'views/res_config_settings_views.xml',
        'views/amc_menus.xml',
    ],
    'application': True,
    'installable': True,
    'license': 'LGPL-3',
}
