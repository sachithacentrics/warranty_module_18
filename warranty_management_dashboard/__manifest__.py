{
    'name': 'Warranty Management - Dashboard',
    'version': '18.0.1.0.7',
    'category': 'Services/Warranty',
    'summary': 'Warranty Dashboard over the existing warranty data, and report actions',
    'description': """
Warranty Management - Dashboard
===============================
Presentation and reporting layer only: no business model, workflow or calculation of its own.

* Warranty > Dashboard: the five areas - Warranty Status, Pending Services, Approvals,
  Replacements and Escalations - with their filters (company, branch, product category,
  warranty card status, date range), read with the user's own access rights; every figure opens
  the existing list it was counted from. Opening or refreshing the dashboard writes nothing.
* Warranty > Reports: report actions (list / pivot / graph) on the existing records.

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
