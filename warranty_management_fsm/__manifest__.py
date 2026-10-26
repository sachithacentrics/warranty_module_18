{
    'name': 'Warranty Management - Field Service',
    'version': '18.0.1.0.0',
    'category': 'Sales/After-Sales',
    'summary': 'Warranty Service Jobs executed through Field Service (Part 4)',
    'description': """
Warranty Management - Part 4: Service Job + Field Service
=========================================================
Service Jobs prepared from approved warranty cases (Helpdesk Ticket -> Service Job ->
Field Service task), merged free services, planning, visits, worksheets and completion.
Developed phase by phase (4.0 setup, 4.1 service selection and merge, ...).
""",
    'depends': ['warranty_management_helpdesk', 'industry_fsm', 'industry_fsm_report',
                'helpdesk_fsm'],
    'data': [
        'security/warranty_fsm_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/warranty_service_job_views.xml',
        'views/warranty_fsm_menus.xml',
        'views/project_task_views.xml',
        'views/res_config_settings_views.xml',
        'views/warranty_job_worksheet_views.xml',
        'wizard/warranty_service_job_hold_wizard_views.xml',
        'wizard/warranty_visit_wizards_views.xml',
        'wizard/warranty_service_job_batch_wizard_views.xml',
        'wizard/warranty_chargeable_wizards_views.xml',
        'views/warranty_chargeable_views.xml',
        'views/worksheet_template_views.xml',
        'views/warranty_draft_job_views.xml',
        'report/worksheet_custom_report_templates.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
