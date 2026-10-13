{
    'name': 'Warranty Management',
    'version': '18.0.1.0.0',
    'category': 'Sales/After-Sales',
    'summary': 'Configurable warranty engine: policies, product/pricelist rules, '
               'draft warranty cards and unit warranty numbers',
    'description': """
Warranty Management - Part 1 (Configuration + Warranty Card Creation)
=====================================================================
* Company warranty settings
* Warranty policies and coverage items
* Product warranty configuration and Product + Pricelist warranty mapping
* Product category default warranty fields
* Draft warranty cards and unit warranty numbers on Sales Order confirmation
* Delivery / serial allocation on delivery validation
* Warranty confirmation (start criterion, dates, activation, soft-copy card)
""",
    'depends': [
        'sale_management',
        'sale_stock',
        'account',
        'worksheet',
    ],
    'data': [
        'security/warranty_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'report/warranty_card_report.xml',
        'views/warranty_card_views.xml',
        'views/warranty_unit_views.xml',
        'views/warranty_policy_views.xml',
        'views/warranty_coverage_item_views.xml',
        'views/product_template_views.xml',
        'views/product_category_views.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/warranty_menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
