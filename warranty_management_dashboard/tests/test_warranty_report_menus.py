from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'warranty_dashboard')
class TestWarrantyReportMenus(TransactionCase):
    """Warranty > Reports in five report categories: the existing report menus, actions and
    groups, each report once; Dashboard and AMC Visit Schedule outside."""

    STRUCTURE = [
        # the 4 report menus of this category were removed on request; the empty category
        # stays in warranty_management_mrf and hides itself
        ('menu_warranty_reports_entitlement', 'Warranty & Entitlements', []),
        ('menu_warranty_reports_service', 'Service Operations', [
            ('warranty_management_dashboard.menu_report_helpdesk_pending',
             'Helpdesk Pending Service',
             'warranty_management_dashboard.action_report_helpdesk_pending'),
            ('warranty_management_dashboard.menu_report_service_planning',
             'Service Merge and Job Planning',
             'warranty_management_dashboard.action_report_service_planning'),
            ('warranty_management_dashboard.menu_report_repair_backup',
             'Repair and Backup Unit', 'warranty_management_dashboard.action_report_repair_backup'),
        ]),
        ('menu_warranty_reports_quality', 'Quality & History', [
            ('warranty_management_dashboard.menu_report_failure_pattern',
             'Failure Pattern', 'warranty_management_dashboard.action_report_failure_pattern'),
            ('warranty_management_dashboard.menu_report_repeated_failure',
             'Repeated Failure Escalation',
             'warranty_management_dashboard.action_report_repeated_failure'),
            ('warranty_management_dashboard.menu_report_replacement',
             'Replacement', 'warranty_management_dashboard.action_report_replacement'),
            ('warranty_management_dashboard.menu_report_warranty_history',
             'Warranty History', 'warranty_management.action_warranty_history'),
        ]),
        ('menu_warranty_reports_material', 'Materials & Inventory', [
            ('warranty_management_mrf.menu_warranty_mrf_approval_cost_report',
             'Material Approval and Cost',
             'warranty_management_mrf.action_warranty_mrf_approval_cost_report'),
            ('warranty_management_mrf.menu_warranty_mrf_cost_report',
             'Warranty Material Cost', 'warranty_management_mrf.action_warranty_mrf_cost_report'),
            ('warranty_management_mrf.menu_warranty_mrf_audit_event',
             'Material Audit Trail', 'warranty_management_mrf.action_warranty_mrf_audit_event'),
        ]),
        ('menu_warranty_reports_financial', 'Financial & Recovery', [
            ('warranty_management_accounting.menu_warranty_cost_report',
             'Warranty Cost', 'warranty_management_accounting.action_server_warranty_cost_report'),
            ('warranty_management_accounting.menu_warranty_reserve_report',
             'Warranty Provision / Reserve',
             'warranty_management_accounting.action_server_warranty_reserve_report'),
            ('warranty_management_mrf.menu_warranty_vendor_claim_recovery_report',
             'Vendor Claim Recovery',
             'warranty_management_mrf.action_warranty_vendor_claim_recovery_report'),
            ('warranty_management_dashboard.menu_report_chargeable_revenue',
             'Chargeable Service Revenue',
             'warranty_management_dashboard.action_report_chargeable_revenue'),
        ]),
    ]
    # The report menus with groups, unchanged by the reorganization; the others have none.
    MATERIAL_GROUPS = {'helpdesk.group_helpdesk_user',
                       'material_purchase_requisitions.group_purchase_requisition_user',
                       'account.group_account_readonly', 'account.group_account_invoice'}
    GROUPS = {
        'warranty_management_dashboard.menu_report_repair_backup':
            {'helpdesk.group_helpdesk_user', 'stock.group_stock_user'},
        'warranty_management_dashboard.menu_report_replacement':
            {'account.group_account_invoice', 'helpdesk.group_helpdesk_user',
             'stock.group_stock_user'},
        'warranty_management_mrf.menu_warranty_mrf_approval_cost_report': MATERIAL_GROUPS,
        'warranty_management_mrf.menu_warranty_mrf_cost_report': MATERIAL_GROUPS,
        'warranty_management_mrf.menu_warranty_mrf_audit_event': MATERIAL_GROUPS,
        'warranty_management_mrf.menu_warranty_vendor_claim_recovery_report': MATERIAL_GROUPS,
        'warranty_management_accounting.menu_warranty_cost_report':
            MATERIAL_GROUPS | {'warranty_management_accounting.group_warranty_cost_report'},
        'warranty_management_accounting.menu_warranty_reserve_report':
            {'account.group_account_readonly', 'account.group_account_invoice'},
        'warranty_management_dashboard.menu_report_chargeable_revenue':
            {'sales_team.group_sale_salesman', 'account.group_account_invoice'},
    }

    def _user(self, login, *groups):
        group_ids = [self.env.ref(group).id for group in ('base.group_user',) + groups]
        return self.env['res.users'].create({'name': login, 'login': login,
                                             'groups_id': [(6, 0, group_ids)]})

    def test_04_report_menu_categories(self):
        """Five categories in the required order, each with its reports in order; same actions and
        groups; every report once; categories without groups or action."""
        reports = self.env.ref('warranty_management_mrf.menu_warranty_reports')
        self.assertEqual(reports.child_id.sorted('sequence').mapped('name'),
                         [name for _xid, name, menus in self.STRUCTURE if menus])
        categories = self.env['ir.ui.menu'].with_context(**{'ir.ui.menu.full_list': True}).search(
            [('parent_id', '=', reports.id)]).sorted('sequence')
        self.assertEqual(categories.mapped('name'), [name for _xid, name, _menus in self.STRUCTURE])
        actions = []
        for category, (xid, name, menus) in zip(categories, self.STRUCTURE):
            self.assertEqual(category, self.env.ref('warranty_management_mrf.' + xid))
            self.assertFalse(category.action or category.groups_id, name)
            children = category.child_id.sorted('sequence')
            self.assertEqual(children.mapped('name'), [menu[1] for menu in menus], name)
            for child, (menu_xid, _label, action_xid) in zip(children, menus):
                self.assertEqual(child, self.env.ref(menu_xid))
                self.assertEqual(child.action, self.env.ref(action_xid), menu_xid)
                self.assertFalse(child.child_id)
                groups = {group.get_external_id()[group.id] for group in child.groups_id}
                self.assertEqual(groups, self.GROUPS.get(menu_xid, set()), menu_xid)
                actions.append(child.action)
        self.assertEqual(len(actions), 14)
        self.assertEqual(len(set(actions)), 14, 'each report once')
        report_menus = self.env['ir.ui.menu'].search([('id', 'child_of', reports.id)])
        # Reports + the 4 visible categories + 14 reports (the empty category is filtered out)
        self.assertEqual(len(report_menus), 1 + 4 + 14)
        # Dashboard and AMC Visit Schedule stay outside Warranty > Reports.
        dashboard = self.env.ref('warranty_management_dashboard.menu_warranty_dashboard')
        self.assertEqual(dashboard.parent_id,
                         self.env.ref('warranty_management.menu_warranty_root'))
        self.assertNotIn(dashboard, report_menus)
        amc = self.env.ref('amc_management.amc_contract_visit_menu_schedule_report',
                           raise_if_not_found=False)
        if amc:
            self.assertNotIn(amc, report_menus)

    def test_05_category_visibility(self):
        """A category shows only with one of its reports: an internal user sees no Materials or
        Financial category; an accounting user sees both. Warranty & Entitlements, now without
        reports, shows to nobody."""
        Menu = self.env['ir.ui.menu']
        material = self.env.ref('warranty_management_mrf.menu_warranty_reports_material')
        financial = self.env.ref('warranty_management_mrf.menu_warranty_reports_financial')
        entitlement = self.env.ref('warranty_management_mrf.menu_warranty_reports_entitlement')
        reserve = self.env.ref('warranty_management_accounting.menu_warranty_reserve_report')
        internal = self._user('report_menu_internal')
        accountant = self._user('report_menu_accountant', 'account.group_account_invoice')
        visible = Menu.with_user(internal)._visible_menu_ids()
        self.assertFalse({material.id, financial.id, reserve.id, entitlement.id} & set(visible))
        visible = Menu.with_user(accountant)._visible_menu_ids()
        self.assertTrue({material.id, financial.id, reserve.id} <= set(visible))
        self.assertNotIn(entitlement.id, visible)
        self.assertNotIn(entitlement.id, Menu._visible_menu_ids())
        for xid in ('menu_report_active_expiring', 'menu_report_draft_review',
                    'menu_report_unit_warranty', 'menu_report_free_service_due'):
            self.assertFalse(self.env.ref('warranty_management_dashboard.' + xid,
                                          raise_if_not_found=False), xid)
