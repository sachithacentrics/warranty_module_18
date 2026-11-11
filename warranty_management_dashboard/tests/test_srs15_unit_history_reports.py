from datetime import timedelta

from lxml import etree

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.warranty_management.tests.common import confirm_and_group
from odoo.addons.warranty_management_fsm.tests.common import ServiceJobCommon


def _filter_domain(model, name):
    """Domain of the search view filter `name`, as the web client applies it."""
    arch = etree.fromstring(model.get_view(view_type='search')['arch'])
    return safe_eval(arch.xpath(f"//filter[@name='{name}']")[0].get('domain'))


@tagged('post_install', '-at_install', 'warranty_dashboard')
class TestUnitWarrantyReport(TransactionCase):
    """SRS 15 Unit Warranty Number Report and the card events of the Warranty History Report:
    one multi-product card with Kit (Indoor / Outdoor) and serial-tracked units."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'warranty_scope_mode': 'warranty_only',
            'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'delivery',
            'default_warranty_duration': 12,
            'default_warranty_duration_unit': 'months',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Report Customer'})
        cls.stock = cls.env.ref('stock.stock_location_stock')
        cls.indoor = cls._serial_product('Report Indoor Unit', 'RIN')
        cls.outdoor = cls._serial_product('Report Outdoor Unit', 'ROUT')
        cls.ac = cls._serial_product('Report Window AC', 'RAC', warranty=True)
        cls.kit = cls.env['product.product'].create({
            'name': 'Report Split AC Kit', 'type': 'consu', 'warranty_applicable': True,
            'invoice_policy': 'order'})
        cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.kit.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1,
            'bom_line_ids': [
                (0, 0, {'product_id': cls.indoor.id, 'product_qty': 1,
                        'warranty_component_role': 'indoor'}),
                (0, 0, {'product_id': cls.outdoor.id, 'product_qty': 1,
                        'warranty_component_role': 'outdoor'}),
            ]})
        cls.other_company = cls.env['res.company'].create({'name': 'Report Other Company'})
        cls.foreign_user = cls.env['res.users'].create({
            'name': 'Report Foreign User', 'login': 'report_foreign_user',
            'company_id': cls.other_company.id, 'company_ids': [(6, 0, cls.other_company.ids)],
            'groups_id': [(6, 0, cls.env.ref('base.group_user').ids)]})
        cls.internal_user = cls.env['res.users'].create({
            'name': 'Report Internal User', 'login': 'report_internal_user',
            'groups_id': [(6, 0, cls.env.ref('base.group_user').ids)]})

    @classmethod
    def _serial_product(cls, name, prefix, warranty=False):
        vals = {'name': name, 'type': 'consu', 'is_storable': True, 'tracking': 'serial'}
        if warranty:
            vals.update(warranty_applicable=True, invoice_policy='order')
        product = cls.env['product.product'].create(vals)
        for index in range(1, 4):
            lot = cls.env['stock.lot'].create({'name': '%s-%02d' % (prefix, index),
                                               'product_id': product.id})
            cls.env['stock.quant']._update_available_quantity(product, cls.stock, 1, lot_id=lot)
        return product

    def _card(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.kit.id, 'product_uom_qty': 2}),
                           (0, 0, {'product_id': self.ac.id, 'product_uom_qty': 2})]})
        confirm_and_group(order)
        picking = order.picking_ids
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        card = order.warranty_card_ids
        self.assertEqual(len(card), 1)
        self.assertEqual(card.state, 'ready', card.missing_requirements)
        card.action_confirm_warranty()
        return order, picking, card

    def _snapshot(self, card):
        units = card.unit_warranty_ids
        return (card.state, card.write_date, card.partner_id, len(card.message_ids),
                [(u.id, u.state, u.write_date, u.serial_ids.ids, u.start_date, u.end_date)
                 for u in units.sorted('id')])

    def test_01_unit_report(self):
        """Unit Warranty Number (Cards > Warranty Unit Numbers): one row per unit with card, customer, product,
        delivery, serials (Kit Indoor / Outdoor kept), dates and status; SRS filters; group by;
        read-only list; the unit opens with its card."""
        order, picking, card = self._card()
        Unit = self.env['warranty.unit']
        action = self.env.ref('warranty_management.action_warranty_unit')
        # the Reports menu was removed on request; the Cards menu still opens the action
        self.assertFalse(self.env.ref('warranty_management_dashboard.menu_report_unit_warranty',
                                      raise_if_not_found=False))
        self.assertEqual(self.env.ref('warranty_management.menu_warranty_unit').action, action)
        self.assertIn('form', action.view_mode)
        before = self._snapshot(card)

        units = Unit.search([('warranty_card_id', '=', card.id)])
        self.assertEqual(units, card.unit_warranty_ids)
        self.assertEqual(len(units), 4)
        self.assertEqual(len(set(units.mapped('name'))), 4)
        for unit in units:
            self.assertEqual((unit.partner_id, unit.delivery_picking_id, unit.state),
                             (self.partner, picking, 'active'))
            self.assertTrue(unit.start_date and unit.end_date)
        kits = units.filtered(lambda unit: unit.product_id == self.kit)
        acs = units - kits
        self.assertEqual(len(kits), 2)
        for unit in kits:
            self.assertEqual(unit.serial_ids, unit.indoor_serial_id | unit.outdoor_serial_id)
            self.assertEqual(unit.indoor_serial_id.product_id, self.indoor)
            self.assertEqual(unit.outdoor_serial_id.product_id, self.outdoor)
        self.assertEqual(len(acs.serial_ids), 2)

        # SRS filters: card, warranty number, product, delivery, serial, status
        domain = [('warranty_card_id', '=', card.id)]
        self.assertEqual(Unit.search([('warranty_card_id', 'ilike', card.name)]), units)
        self.assertEqual(Unit.search([('name', '=', kits[0].name)]), kits[0])
        self.assertEqual(Unit.search(domain + [('product_id', '=', self.ac.id)]), acs)
        self.assertEqual(Unit.search([('delivery_picking_id', '=', picking.id)]), units)
        self.assertEqual(Unit.search([('serial_ids', 'ilike', acs[0].serial_ids.name)]), acs[0])
        self.assertEqual(Unit.search([('indoor_serial_id', 'ilike', kits[1].indoor_serial_id.name)]),
                         kits[1])
        self.assertEqual(Unit.search(domain + _filter_domain(Unit, 'filter_active')), units)
        self.assertFalse(Unit.search(domain + _filter_domain(Unit, 'filter_draft')))
        self.assertEqual(Unit.search([('partner_id', '=', self.partner.id)]), units)
        groups = Unit.read_group(domain, ['product_id'], ['product_id'])
        self.assertEqual(sorted(group['product_id_count'] for group in groups), [2, 2])
        groups = Unit.read_group(domain, ['partner_id'], ['partner_id'])
        self.assertEqual([group['partner_id_count'] for group in groups], [4])

        arch = etree.fromstring(Unit.get_view(view_type='list')['arch'])
        self.assertEqual((arch.get('create'), arch.get('delete')), ('false', 'false'))
        columns = arch.xpath('//field/@name')
        for name in ('name', 'warranty_card_id', 'partner_id', 'product_id', 'delivery_picking_id',
                     'serial_ids', 'indoor_serial_id', 'outdoor_serial_id', 'start_date',
                     'end_date', 'state'):
            self.assertIn(name, columns)
        form = Unit.get_view(view_type='form')['arch']
        self.assertIn('name="warranty_card_id"', form)
        self.assertIn('action_view_warranty_history', form)

        # company isolation; reading the report changes nothing
        self.assertFalse(Unit.with_user(self.foreign_user).search(domain))
        self.assertEqual(self._snapshot(card), before)
        self.assertEqual(order.warranty_card_ids, card)

    def test_02_history_card_events(self):
        """Reports > Warranty History: card, unit, activation and invoice posting events of
        the card, newest first, opening their records; other companies see nothing; reading
        changes nothing."""
        order, picking, card = self._card()
        invoice = order._create_invoices()
        invoice.action_post()
        self.env.flush_all()  # the SQL view reads the database (each request commits in the UI)
        History = self.env['warranty.history']
        action = self.env.ref('warranty_management.action_warranty_history')
        menu = self.env.ref('warranty_management_dashboard.menu_report_warranty_history')
        self.assertEqual((menu.action, menu.parent_id),
                         (action, self.env.ref('warranty_management_mrf.menu_warranty_reports_quality')))
        self.assertFalse(self.env.ref('warranty_management.menu_warranty_history',
                                      raise_if_not_found=False), 'no second history menu')
        before = self._snapshot(card)

        rows = History.search([('card_id', '=', card.id)])
        events = {(row.entity, row.event_type) for row in rows}
        self.assertTrue({('card', 'Card created'), ('date', 'Activation'),
                         ('invoice', 'Customer invoice created'),
                         ('invoice', 'Customer invoice posted')} <= events, events)
        unit_rows = rows.filtered(lambda row: row.entity == 'unit')
        self.assertEqual(unit_rows.unit_id, card.unit_warranty_ids)
        self.assertEqual(set(unit_rows.mapped('reference')), set(card.unit_warranty_ids.mapped('name')))
        dates = rows.mapped('event_date')
        self.assertEqual(dates, sorted(dates, reverse=True), 'newest first')
        posted = rows.filtered(lambda row: row.event_type == 'Customer invoice posted')
        self.assertEqual(set(posted.mapped('reference')), {invoice.name})
        self.assertEqual(posted[0].user_id, self.env.user)

        # SRS filters: entity, event type, user, date
        self.assertEqual(History.search([('card_id', '=', card.id), ('entity', '=', 'unit')]),
                         unit_rows)
        created = History.search([('card_id', '=', card.id)]
                                 + _filter_domain(History, 'filter_created'))
        self.assertTrue(created and all(' created' in r.event_type for r in created))
        self.assertEqual(History.search([('card_id', '=', card.id),
                                         ('user_id', '=', self.env.uid)]), rows)

        # navigation
        open_unit = unit_rows[0].action_open_source()
        self.assertEqual((open_unit['res_model'], open_unit['res_id']),
                         ('warranty.unit', unit_rows[0].unit_id.id))
        open_invoice = posted[0].action_open_source()
        self.assertEqual((open_invoice['res_model'], open_invoice['res_id']),
                         ('account.move', invoice.id))
        card_row = rows.filtered(lambda row: row.entity == 'card')
        self.assertEqual(card_row.action_open_source()['res_id'], card.id)
        list_arch = History.get_view(view_type='list')['arch']
        self.assertIn('action_open_source', list_arch)

        # access: other company none; internal users read card events, no journal entries
        self.assertFalse(History.with_user(self.foreign_user).search([('card_id', '=', card.id)]))
        internal = History.with_user(self.internal_user).search([('card_id', '=', card.id)])
        self.assertEqual(internal, rows.filtered(lambda r: r.entity not in ('cost', 'accounting')))
        self.assertEqual(self._snapshot(card), before)
        self.assertEqual(invoice.state, 'posted')


@tagged('post_install', '-at_install', 'warranty_dashboard')
class TestWarrantyHistoryStatusEvents(ServiceJobCommon):
    """Warranty History Report: case / job status changes from their tracking, cost lines and
    journal entries for the users allowed to see them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('report_hist_tech', 'industry_fsm.group_fsm_user')
        cls.env['hr.employee'].create({'name': cls.tech.name, 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.account_user = cls._user('report_hist_account', 'account.group_account_invoice')

    def _commit_tracking(self):
        """What a request commit does: write the chatter tracking (pre-commit) and the pending
        fields, which the SQL view reads."""
        self.env.flush_all()
        self.env.cr.precommit.run()
        self.env.flush_all()

    def test_03_status_events_and_access(self):
        """Job / case status changes with their user, newest first; cost line rows for
        coordinators, journal entry rows for accounting users only; no amounts."""
        # each step in its own request, as in the UI (no tracking within the creating one)
        case = self._approved()
        self._commit_tracking()
        job = self._prepare(case)
        self._commit_tracking()
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        History = self.env['warranty.history']
        card_domain = [('card_id', '=', case.warranty_card_id.id)]
        self._commit_tracking()

        # job: created + one row per tracked status change, with its user
        job_rows = History.search(card_domain + [('entity', '=', 'job')])
        self.assertEqual(job_rows.filtered(lambda r: r.event_type == 'Job created').reference,
                         job.name)
        tracked = self.env['mail.tracking.value'].search([
            ('mail_message_id.model', '=', 'warranty.service.job'),
            ('mail_message_id.res_id', '=', job.id), ('field_id.name', '=', 'state')])
        status_rows = job_rows.filtered(lambda r: r.event_type.startswith('Job status: '))
        self.assertEqual(len(status_rows), len(tracked))
        self.assertTrue(status_rows)
        self.assertTrue(status_rows[0].event_type.endswith(
            dict(job._fields['state']._description_selection(self.env))[job.state]))
        self.assertEqual(status_rows[0].user_id, self.helpdesk_user)
        self.assertEqual(status_rows[0].action_open_source()['res_id'], job.id)
        dates = job_rows.mapped('event_date')
        self.assertEqual(dates, sorted(dates, reverse=True))
        # case: created + status change when its job was prepared
        case_rows = History.search(card_domain + [('reference', '=', case.name)])
        self.assertIn('Case created', case_rows.mapped('event_type'))
        labels = dict(case._fields['state']._description_selection(self.env))
        changed = case_rows.filtered(
            lambda r: r.event_type == 'Case status: %s -> %s' % (labels['approved'],
                                                                  labels['job_created']))
        self.assertEqual(changed.user_id, self.helpdesk_user)
        self.assertEqual(changed.action_open_source()['res_id'], case.id)
        self.assertTrue(History.search(card_domain + _filter_domain(History, 'filter_status')))

        # cost line and journal entry rows: only for the users who may see them
        line = self.env['warranty.cost.line'].create({
            'case_id': case.id, 'cost_type': 'travel', 'reason': 'Site travel',
            'estimated_amount': 25.0})
        move = self.env['account.move'].create({
            'move_type': 'out_refund', 'partner_id': case.partner_id.id,
            'warranty_inspection_case_id': case.id})
        self._commit_tracking()
        rows = History.search(card_domain)
        self.assertIn(('cost', line.name), [(r.entity, r.reference) for r in rows])
        self.assertIn(('accounting', 'Inspection fee credit note created'),
                      [(r.entity, r.event_type) for r in rows])
        texts = filter(None, rows.mapped('summary') + rows.mapped('event_type'))
        self.assertNotIn('25.0', ' '.join(texts), 'no amounts in the history')
        entities = {
            user: set(History.with_user(user).search(card_domain).mapped('entity'))
            for user in (self.internal_user, self.helpdesk_user, self.account_user)}
        self.assertFalse(entities[self.internal_user] & {'cost', 'accounting'})
        self.assertIn('cost', entities[self.helpdesk_user])
        self.assertNotIn('accounting', entities[self.helpdesk_user])
        self.assertTrue({'cost', 'accounting'} <= entities[self.account_user])
        self.assertFalse(History.with_user(self.foreign_user).search(card_domain))
        # the report reads only
        self.assertEqual((job.state, case.state, move.state, line.state),
                         ('confirmed', 'job_created', 'draft', 'draft'))


@tagged('post_install', '-at_install', 'warranty_dashboard')
class TestWarrantyReportMenus(TransactionCase):
    """Warranty > Reports in five SRS 15 categories: the existing report menus, actions and
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
        """Five categories in SRS order, each with its reports in order; same actions and
        groups; every report once; categories without groups or action. The empty Warranty &
        Entitlements category exists but is left out of the visible menu tree."""
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
