{
    'name': 'Warranty Management - Repair Intake',
    'version': '18.0.1.7.7',
    'category': 'Sales/After-Sales',
    'summary': 'Warranty Part 6.1: repair intake and workshop repair with standard Repair Orders',
    'description': """
Bridge between Warranty Management (Parts 1-5) and the standard Repairs / Inventory apps, see
``doc/part6_1_repair_intake_design.md``.

* Repair intake through the standard return of the ticket: Warranty Repair Intake location,
  Sales Order quantities, warranty dates and unit allocation unchanged
* Standard Repair Order linked to the warranty case, ticket, service job, card and unit
* Parts of a linked Repair Order only through the Material Request (no second consumption)
* Repair result, intake status, return of the repaired machine with the standard Return
* Workshop-only completion of the warranty case (no open service job, no pending free service,
  Material Requests reconciled)
* Chargeable repair: the Job Trigger authorizes Start Repair, no second Field Service job
* Backup Unit Issue / Return (BKU/, Part 6.2): serial-tracked standard internal transfers, custody
  dates and condition, status and overdue follow-up, see ``doc/part6_2_backup_unit_design.md``
* Backup Damage / Loss (Part 6.3): approved assessment, one draft quotation, physical and financial
  status, deposit reference; see ``doc/part6_3_backup_billing_design.md``
* Warranty Replacement / Serial Swap (WR/, Part 7 Stage 1): Full Product of one serial, GM and Finance
  approval, standard return and delivery, date policy, updated card; Indoor Unit and Outdoor Unit of
  a kit (Stage 2): Manager / GM approval, one serial and its own dates; Goodwill of one serial
  (Stage 3): Manager / GM approval, manual date, eligibility result kept; Vendor Replacement of one
  serial (Stage 3): Manager / GM approval, optional Vendor Claim; Component (Stage 3): Manager / GM
  approval, the existing Material Request, defective part return, part history; see
  ``doc/part7_replacement_design.md``
* Figure 6 navigation: Workshop Intake / Repair Order from the service job, Issue Backup Machine and
  Return Machine to Customer on the Repair Order, Backup Units smart buttons, Repair Order Next Step
* Warranty tickets: no Sales Order Item proposed automatically (helpdesk_sale_timesheet)
* Backup unit Return to Backup Stock: standard Internal Transfer Returned-Inspection -> Backup
  Stock of the serial for a Good return; Close stays manual
* Workshop inspection trigger: an Approved case whose machine is in the workshop (Repair Order with
  a validated intake) gets no on-site service job from its Inspection Trigger; Start Repair may start
* Figure 6 Service Mode (SRS 12 scenario 18) on the warranty case: On-site / Workshop Repair /
  Vendor Repair decides whether the triggers create a Field Service job
* Vendor Repair: Send for Repair / Receive from Repair, standard internal transfers of the serial to
  an internal location or a Vendor Repair Custody location (no sale, purchase or revaluation)
* Return to Backup Stock also for Minor Scratch; Intake Status checks the received serial
* Damaged / Lost backup Close (Figure 6 C2): approved assessment, settled charge and a verified
  standard Scrap / missing count / confirmed restoration; Lost -> Found recovery; written-off
  serials are never issued again. Close creates no stock or accounting entry
""",
    'depends': [
        'warranty_management_mrf',
        'warranty_management_mrp',
        'helpdesk_repair',
        'helpdesk_account',
        'helpdesk_timesheet',
        'helpdesk_sale_timesheet',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/warranty_repair_security.xml',
        'data/warranty_backup_data.xml',
        'data/warranty_replacement_data.xml',
        'views/warranty_backup_unit_views.xml',
        'views/warranty_replacement_views.xml',
        'views/res_config_settings_views.xml',
        'views/repair_order_views.xml',
        'views/warranty_case_views.xml',
        'views/warranty_service_job_views.xml',
        'views/helpdesk_ticket_views.xml',
        'wizard/stock_picking_return_views.xml',
        'wizard/repair_vendor_send_views.xml',
        'views/stock_location_views.xml',
        'report/warranty_card_report.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
