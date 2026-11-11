{
    'name': 'AMC Management - Warranty Link',
    'version': '18.0.1.2.1',
    'category': 'Services/AMC',
    'summary': 'Bridge between Warranty Management and the separate AMC module: draft AMC on '
               'warranty confirmation, Convert to AMC, warranty units on covered equipment',
    'description': """
AMC Management - Warranty Link (SRS 2.1 / 2.12 / 7 / 12 #12 / 14)
================================================================
Optional bridge; neither amc_management nor warranty_management depends on it.

* AMC Auto-create Mode (None / Draft AMC Opportunity / Draft AMC Contract): warranty
  confirmation optionally creates a draft AMC record; it never activates AMC coverage.
* Convert to AMC on confirmed / expired warranty cards (continuity after warranty expiry).
* Offer AMC on warranty expiry (activity) when configured.
* Warranty unit numbers on AMC covered equipment; smart buttons both ways (card and unit
  warranty number -> AMC contracts, contract -> warranty cards).
""",
    'depends': ['amc_management', 'warranty_management'],
    'data': [
        'views/amc_contract_views.xml',
        'views/amc_opportunity_views.xml',
        'views/warranty_card_views.xml',
        'views/warranty_unit_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'auto_install': False,
    'installable': True,
    'license': 'OPL-1',
}
