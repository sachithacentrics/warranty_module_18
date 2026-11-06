{
    'name': 'Warranty Management - Cost and Accounting',
    'version': '18.0.1.6.2',
    'category': 'Sales/After-Sales',
    'summary': 'Warranty Part 8: warranty cost lines, labour, travel, subcontract, cost approval '
               'and cost report',
    'description': """
Part 8.1 Warranty Cost Lines, see ``doc/part8_1_cost_lines_design.md``.
Part 8.2 Cost Consolidation and Reporting, see ``doc/part8_2_cost_report_design.md``.
Part 8.3 Accounting Configuration, see ``doc/part8_3_accounting_config_design.md``.
Part 8.4 Inspection Fee Adjustment, see ``doc/part8_4_inspection_adjustment_design.md``.
Part 8.5 Warranty Case Closure, see ``doc/part8_5_case_closure_design.md``.
Part 8.6 Warranty Provision Entries, see ``doc/part8_6_provision_entry_design.md``.

* Replacement cost in the case totals, vendor recovery and Net Warranty Cost
* Read-only Warranty Cost Report with SRS filters

* Labour read from the timesheets of service visits, shared visits split equally
* Manual workshop labour, travel and other cost lines with an audit reason
* Subcontract cost read from one purchase order line or posted vendor bill line
* Estimated, approved and actual cost on warranty cases and service jobs
* Cost approval by named approvers, reversal with a reason, full audit trail
* Optional total expected cost gate, off by default
* No journal entries: Part 8.1 changes no accounting, stock or timesheet record
""",
    'depends': [
        'warranty_management_repair',
        'hr_timesheet',
        'purchase',
    ],
    'data': [
        'security/warranty_cost_report_security.xml',
        'security/ir.model.access.csv',
        'security/warranty_accounting_security.xml',
        'data/ir_sequence_data.xml',
        'wizard/warranty_cost_line_wizard_views.xml',
        'views/warranty_cost_line_views.xml',
        'views/warranty_cost_summary_views.xml',
        'views/warranty_cost_report_views.xml',
        'views/res_config_settings_views.xml',
        'views/warranty_accounting_config_views.xml',
        'views/warranty_inspection_adjustment_views.xml',
        'views/warranty_case_closure_views.xml',
        'views/warranty_provision_entry_views.xml',
        'views/warranty_reserve_report_views.xml',
        'data/warranty_cost_report_data.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
