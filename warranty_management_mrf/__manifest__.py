{
    'name': 'Warranty Management - Material Requests',
    'version': '18.0.1.9.14',
    'category': 'Sales/After-Sales',
    'summary': 'Warranty Phase 5: Material Request (MRF) integration with warranty cases, '
               'service jobs and Field Service tasks',
    'description': """
Bridge between Warranty Management (Parts 1-4) and the installed Material Purchase
Requisitions module (``material_purchase_requisitions``), see
``doc/part5_design_decisions.md``.

The vendor module is reused unchanged through standard inheritance; requisitions that are not
linked to a warranty record keep the vendor behaviour.

* 5.0 foundation: dependencies, role mapping, regression baseline
* 5.1 create / link Material Requests from warranty cases, service jobs and Field Service
  visits: warranty links, auto-filled header, MRF/ numbering, estimated line cost, smart
  buttons, menu Warranty / Material Requests, default locations in Warranty Settings
* 5.2 coverage classification: line Coverage Type (Covered / Not Covered / Pending) from
  the case and policy, Request Coverage Decision, Decide Coverage (reviewers = Warranty Case
  Approval Users, reason, goodwill), Confirm blocked while lines are pending, coverage locked
  after submission
* 5.3 material approval matrix: approval rules (amount, coverage, goodwill, products /
  categories, company and branches), named Manager / Finance / GM approvers, separation of
  duties, approval rounds and history, reject / withdraw / resubmit, server-side protection of
  the vendor workflow, pickings and purchase orders
* 5.4 commercial control of Not Covered lines: Create Parts Quotation (standard Sales), release
  On Quotation Confirmation or On Payment, release exception, Customer Declined, delivery of
  chargeable parts by the quotation only (no double issue)
* 5.5 availability-driven issue and purchasing: free stock issued by internal pickings,
  shortages bought by RFQs, Issue / Purchase Remaining after receipts, backorders, issued /
  outstanding quantities, Partially Issued / Issued, over-issue and serial checks, links on
  pickings and purchase orders, job material status
* 5.6 actual consumption and returns: Record Used Parts (validated moves to the Warranty
  Consumption location), installation of customer-paid parts, Customer Keeps / Customer Return,
  Return Unused (store-validated return transfers), Confirm Full Consumption, Reverse, Cancel
  Remaining, reconciliation, Returned / Closed, completion blocker, Materials tab, no Field
  Service Products on warranty visits
* 5.7 estimated, approved and actual material cost: approved cost snapshot per line, actual
  cost from stock valuation layers (verified / unverified), Covered / Goodwill / Customer Paid
  buckets, customer billed amounts, Material Cost tabs on requests, jobs and cases, Warranty
  Material Cost report; no journal entries
* 5.8 vendor / manufacturer reimbursement claims (VCL/): eligible verified consumption of
  claimable Covered / Goodwill parts, supplier proposal with audited override, Warranty /
  Finance approval, evidence, vendor response (full / partial / rejected), draft vendor credit
  notes on the Recovery Account, credit note allocations, recovered / settled / outstanding,
  over-claim control after reversals, write-off, case / job / request recovery figures
* 5.9 closure, audit and reporting: Reconciled vs formally Closed requests (Closed By / On),
  freeze and controlled reopen, batch closure from job / case, case-closure guard, customer
  invoicing follow-up, explicit claim-line recovery allocation, header field tracking, reports
  Material Approval and Cost, Vendor Claim Recovery, Material Audit Trail (Warranty -> Reports)
""",
    'depends': [
        'warranty_management_fsm',
        'material_purchase_requisitions',
        'purchase_stock',
        'sale_stock',
        'industry_fsm_sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/warranty_mrf_security.xml',
        'data/ir_sequence_data.xml',
        'views/material_purchase_requisition_views.xml',
        'views/warranty_views.xml',
        'views/warranty_mrf_approval_views.xml',
        'views/warranty_mrf_sale_views.xml',
        'views/warranty_mrf_fulfilment_views.xml',
        'views/warranty_mrf_consumption_views.xml',
        'views/warranty_mrf_cost_views.xml',
        'views/warranty_vendor_claim_views.xml',
        'views/warranty_mrf_closure_report_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
