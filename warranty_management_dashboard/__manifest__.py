{
    'name': 'Warranty Management - Dashboard',
    'version': '18.0.1.0.4',
    'category': 'Services/Warranty',
    'summary': 'Warranty Dashboard and SRS 15 report shortcuts over the existing warranty data',
    'description': """
Warranty Management - Dashboard (SRS 6 / 15 / 17)
=================================================
Presentation and reporting layer only: no business model, workflow or calculation of its own.

* Warranty > Dashboard: KPI cards, charts and filters (company, branch, product category,
  warranty status, date range) read with the user's own access rights; every figure opens the
  existing list, form or report it was counted from.
* Cost and provision figures come from the existing Warranty Cost and Provision / Reserve
  reports (same builders, same access checks).
* Warranty > Reports: the SRS 15 reports that had no menu yet, as list / pivot / graph actions
  on the existing records.

AMC transactions stay in the separate AMC module.
""",
    'depends': [
        'warranty_management_accounting',
        'warranty_management_repair',
    ],
    'data': [
        'views/warranty_dashboard_views.xml',
        'views/warranty_dashboard_report_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'warranty_management_dashboard/static/src/**/*',
            ('remove', 'warranty_management_dashboard/static/src/**/*.dark.scss'),
        ],
        'web.assets_web_dark': [
            'warranty_management_dashboard/static/src/**/*.dark.scss',
        ],
    },
    'installable': True,
    'license': 'OPL-1',
}
