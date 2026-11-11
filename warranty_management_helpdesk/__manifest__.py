{
    'name': 'Warranty Management - Helpdesk',
    'version': '18.0.1.2.9',
    'category': 'Sales/After-Sales',
    'summary': 'Helpdesk-first warranty cases (Part 3)',
    'description': """
Warranty Management - Part 3: Helpdesk + Warranty Case + Eligibility
====================================================================
Stages 3.1-3.5 - Helpdesk ticket, warranty case, card / serial / validity, payment,
coverage, free service and repeated failure eligibility checks:

* Warranty panel on Helpdesk tickets: site, product, serial number and the customer's
  pending free services
* Warranty Cases (WCAS/xxxxxx) created from a ticket, several per ticket, with the
  selected pending free services linked
""",
    'depends': ['warranty_management', 'helpdesk'],
    'data': [
        'security/ir.model.access.csv',
        'security/warranty_helpdesk_security.xml',
        'data/ir_sequence_data.xml',
        'views/warranty_case_views.xml',
        'views/helpdesk_ticket_views.xml',
        'views/warranty_service_entitlement_views.xml',
        'wizard/warranty_case_create_wizard_views.xml',
        'wizard/warranty_case_reject_wizard_views.xml',
        'wizard/warranty_case_chargeable_wizard_views.xml',
        'views/warranty_helpdesk_menus.xml',
        'views/res_config_settings_views.xml',
        'views/warranty_policy_views.xml',
        'views/warranty_chargeable_views.xml',
        'views/warranty_service_merge_views.xml',
        'views/warranty_service_date_exception_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
