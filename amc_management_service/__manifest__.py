{
    'name': 'AMC Management - Service Execution',
    'version': '18.0.1.0.0',
    'category': 'Services/AMC',
    'summary': 'AMC visits through the mandatory Helpdesk Ticket -> Service Job -> Field '
               'Service chain of the warranty solution',
    'description': """
AMC Management - Service Execution (SRS 2.1 / 2.5 / 2.6 / 2.12 / 9.9)
=====================================================================
Optional bridge; neither amc_management nor the warranty modules depend on it.

* Create Service Request from AMC visits: Helpdesk ticket (new or existing) + warranty case of
  type AMC linked to the AMC contract and the selected compatible visits (merge, AMC-F03).
* AMC eligibility for AMC cases (contract running, entitlements open, coverage period).
* The standard warranty Service Job / Field Service task / worksheet / sign-off flow; one
  worksheet instance per AMC visit (AMC-F05); usage readings for usage-based visits.
* Job completion with customer sign-off consumes the AMC visits once (AMC-E07); a cancelled
  job or rejected case releases them unconsumed (AMC-F07).
* Pending AMC services on Helpdesk tickets (AMC-F02); traceability links (AMC-H02 / H04).
""",
    'depends': ['amc_management', 'warranty_management_fsm'],
    'data': [
        'security/ir.model.access.csv',
        'data/helpdesk_tag_data.xml',
        'views/amc_visit_views.xml',
        'views/warranty_case_views.xml',
        'views/helpdesk_ticket_views.xml',
    ],
    'auto_install': False,
    'installable': True,
    'license': 'LGPL-3',
}
