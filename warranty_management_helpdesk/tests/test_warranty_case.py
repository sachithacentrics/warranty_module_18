from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCase(TransactionCase):
    """Part 3.1 - Helpdesk Ticket and Warranty Case creation (approved A-E, Q2-Q7)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Other Case Company'})
        cls.company.write({
            'warranty_scope_mode': 'free_services',
            'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'installation',
            'default_warranty_duration': 12,
            'default_warranty_duration_unit': 'months',
        })
        # Part 3.4 coverage items: cases are created with the covered "Standard Service".
        Item = cls.env['warranty.coverage.item']
        cls.item_service = Item.create({'name': 'Case Standard Service'})
        cls.item_pcb = Item.create({'name': 'Case PCB'})
        cls.item_gas = Item.create({'name': 'Case Gas Refill'})
        cls.item_undefined = Item.create({'name': 'Case Installation Kit'})
        cls.policy = cls.env['warranty.policy'].create({
            'name': 'Case Policy',
            'covered_item_ids': [(6, 0, (cls.item_service | cls.item_pcb).ids)],
            'excluded_item_ids': [(6, 0, cls.item_gas.ids)], 'warranty_duration': 12, 'warranty_duration_unit': 'months',
            'free_service_count': 3, 'free_service_period': 12,
            'free_service_period_unit': 'months', 'schedule_method': 'equal_interval',
            'auto_create_services': True, 'grace_period_days': 30, 'auto_expire_services': True,
            # Earlier phases merge services of one card; the service sequence (flexible service
            # dates F3) is tested in warranty_management_fsm test_flexible_service_dates.
            'service_sequence_required': False,
        })
        cls.categ = cls.env['product.category'].create({
            'name': 'Case ACs', 'warranty_policy_id': cls.policy.id})
        cls.customer = cls.env['res.partner'].create({'name': 'ABC Hotel', 'is_company': True})
        cls.site_a = cls.env['res.partner'].create({
            'name': 'ABC Hotel - Weligama', 'parent_id': cls.customer.id, 'type': 'delivery'})
        cls.site_b = cls.env['res.partner'].create({
            'name': 'ABC Hotel - Galle', 'parent_id': cls.customer.id, 'type': 'delivery'})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Hotel Engineer', 'parent_id': cls.customer.id})
        cls.other_customer = cls.env['res.partner'].create({'name': 'Other Customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'Case AC', 'type': 'service', 'categ_id': cls.categ.id,
            'warranty_applicable': True})
        cls.other_product = cls.env['product.product'].create({
            'name': 'Case Fan', 'type': 'service', 'categ_id': cls.categ.id,
            'warranty_applicable': True})
        # Is Warranty: cases need a customer with a confirmed card; tests of the card lookup
        # give the customer an unrelated confirmed card (other product).
        cls.unrelated_product = cls.env['product.product'].create({
            'name': 'Case Heater', 'type': 'service', 'categ_id': cls.categ.id,
            'warranty_applicable': True})
        cls.team = cls.env['helpdesk.team'].create({'name': 'Warranty Service Team'})
        cls.helpdesk_user = cls._user('wcase_helpdesk_user', 'helpdesk.group_helpdesk_user')
        cls.helpdesk_manager = cls._user('wcase_helpdesk_manager',
                                         'helpdesk.group_helpdesk_manager')
        cls.internal_user = cls._user('wcase_internal_user')
        cls.foreign_user = cls._user('wcase_foreign_user', 'helpdesk.group_helpdesk_manager',
                                     company=cls.other_company)

    @classmethod
    def _user(cls, login, group=None, company=None):
        company = company or cls.company
        groups = cls.env.ref('base.group_user')
        if group:
            groups |= cls.env.ref(group)
        return cls.env['res.users'].create({
            'name': login, 'login': login, 'company_id': company.id,
            'company_ids': [(6, 0, company.ids)], 'groups_id': [(6, 0, groups.ids)]})

    # Cross-card service merge D3 (date windows): the earlier tests merge services of other due
    # dates; the window rules are tested with check_service_windows = True
    # (warranty_management_fsm test_service_job_multicard).
    check_service_windows = False

    def setUp(self):
        super().setUp()
        if not self.check_service_windows:
            self.startPatcher(patch.object(type(self.env['warranty.case']),
                                           '_warranty_window_problems',
                                           lambda case, services: []))
            if 'warranty.service.job' in self.env:
                self.startPatcher(patch.object(type(self.env['warranty.service.job']),
                                               '_warranty_planned_date_problems',
                                               lambda job, planned_date=None: []))

    @contextmanager
    def _today(self, today):
        with patch.object(type(self.env['res.company']), '_warranty_today',
                          lambda company, log_missing_timezone=False: today):
            yield

    def _card(self, partner=None, product=None, site=None):
        """Confirmed card started 2026-07-15: services due 2026-11-15, 2027-03-15,
        2027-07-15 (grace 30 days)."""
        order = self.env['sale.order'].create({
            'partner_id': (partner or self.customer).id,
            'partner_shipping_id': (site or partner or self.customer).id,
            'order_line': [(0, 0, {'product_id': (product or self.product).id})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, date(2026, 7, 15))
        card.action_confirm_warranty()
        self.assertEqual(len(card.service_entitlement_ids), 3)
        return card

    def _unrelated_card(self):
        """A confirmed card of another product: the customer may create warranty cases."""
        return self._card(product=self.unrelated_product)

    def _ticket(self, **vals):
        values = {'name': 'AC not cooling', 'team_id': self.team.id, 'is_warranty': True,
                  'partner_id': self.contact.id, 'description': '<p>Cooling not effective</p>'}
        values.update(vals)
        return self.env['helpdesk.ticket'].create(values)

    def _wizard(self, ticket, user=None, **vals):
        env = self.env(user=user) if user else self.env
        values = {'helpdesk_ticket_id': ticket.id, 'case_type': 'warranty_complaint'}
        values.update(vals)
        return env['warranty.case.create.wizard'].create(values)

    def _create_case(self, ticket, user=None, requested_items=None, **vals):
        action = self._wizard(ticket, user, **vals).action_create()
        case = self.env['warranty.case'].browse(action['res_id'])
        case.requested_item_ids = self.item_service if requested_items is None else requested_items
        return case

    # ------------------------------------------------------------------ pending services
    def test_01_pending_services(self):
        """Pending services of the customer (commercial entity): Draft / Pending / Scheduled /
        Rescheduled, Missed within the grace period; not Expired / Completed / Cancelled /
        after grace / balance 0 / other customer / other company."""
        card = self._card()
        s1, s2, s3 = card.service_entitlement_ids.sorted('service_no')
        other = self._card(partner=self.other_customer)
        ticket = self._ticket()
        with self._today(date(2026, 11, 1)):
            self.assertEqual(ticket.warranty_pending_service_ids, s1 | s2 | s3)
        s2.with_context(warranty_schedule_audited=True).write(
            {'state': 'scheduled', 'scheduled_date': date(2027, 3, 10)})
        s3.state = 'rescheduled'
        s1.state = 'missed'
        with self._today(date(2026, 12, 15)):  # grace end of service 1
            ticket.invalidate_recordset(['warranty_pending_service_ids'])
            self.assertEqual(ticket.warranty_pending_service_ids, s1 | s2 | s3)
        with self._today(date(2026, 12, 16)):
            ticket.invalidate_recordset(['warranty_pending_service_ids'])
            self.assertEqual(ticket.warranty_pending_service_ids, s2 | s3)
        for state in ('expired', 'completed', 'cancelled', 'in_progress'):
            s3.state = state
            ticket.invalidate_recordset(['warranty_pending_service_ids'])
            with self._today(date(2026, 11, 1)):
                self.assertNotIn(s3, ticket.warranty_pending_service_ids, state)
        # Free Services Balance 0: the remaining service is not pending.
        s3.state = 'draft'
        card.free_services_allowed = 2
        s1.state = 'expired'
        s2.state = 'cancelled'
        ticket.invalidate_recordset(['warranty_pending_service_ids'])
        with self._today(date(2026, 11, 1)):
            self.assertEqual(card.free_services_balance, 0)
            self.assertFalse(ticket.warranty_pending_service_ids)
        self.assertNotIn(other.service_entitlement_ids, ticket.warranty_pending_service_ids)
        self.assertFalse(self.env['warranty.service.entitlement']._warranty_pending_services(
            self.customer, self.other_company))

    def test_02_pending_filters(self):
        """Optional filters: site (card Sales Order delivery address), product, serial
        (unit serials, also kit Indoor / Outdoor serials)."""
        card_a = self._card(site=self.site_a)
        card_b = self._card(site=self.site_b, product=self.other_product)
        lot = self.env['stock.lot'].create({'name': 'IN-AC-0001', 'product_id': self.product.id})
        card_a.unit_warranty_ids.serial_ids = lot
        ticket = self._ticket()
        with self._today(date(2026, 11, 1)):
            self.assertEqual(ticket.warranty_pending_service_ids.warranty_card_id, card_a | card_b)
            ticket.warranty_site_id = self.site_a
            self.assertEqual(ticket.warranty_pending_service_ids.warranty_card_id, card_a)
            ticket.warranty_site_id = False
            ticket.warranty_product_id = self.other_product
            self.assertEqual(ticket.warranty_pending_service_ids.warranty_card_id, card_b)
            ticket.write({'warranty_product_id': self.product.id, 'warranty_serial_id': lot.id})
            self.assertEqual(ticket.warranty_pending_service_ids.warranty_card_id, card_a)
        with self.assertRaises(ValidationError):
            ticket.warranty_site_id = self.other_customer

    # ------------------------------------------------------------------ case creation
    def test_03_create_case_without_services(self):
        """No pending service selected: case WCAS/xxxxxx in New with the ticket values
        (customer, site, product, serial, complaint, priority mapping 0-3)."""
        self._unrelated_card()
        lot = self.env['stock.lot'].create({'name': 'SN-CASE-1', 'product_id': self.product.id})
        ticket = self._ticket(priority='2', warranty_site_id=self.site_a.id,
                              warranty_product_id=self.product.id, warranty_serial_id=lot.id)
        case = self._create_case(ticket, self.helpdesk_user)
        self.assertRegex(case.name, r'^WCAS/\d{6}$')
        self.assertEqual(
            (case.state, case.eligibility_result, case.partner_id, case.site_id, case.product_id,
             case.serial_id, case.priority, case.customer_complaint, case.case_type),
            ('new', False, self.contact, self.site_a, self.product, lot, '2',
             'Cooling not effective', 'warranty_complaint'))
        self.assertFalse(case.service_entitlement_ids or case.warranty_card_id)
        self.assertEqual((ticket.warranty_case_count, ticket.warranty_case_ids), (1, case))
        for priority in ('0', '1', '3'):
            ticket.priority = priority
            self.assertEqual(self._create_case(ticket).priority, priority)
        case.priority = '0'
        self.assertEqual(case.priority, '0', 'editable')

    def test_04_create_case_with_services(self):
        """Selected pending services are linked; their Helpdesk Ticket is set; the card is
        filled; merged ad-hoc request kept."""
        card = self._card()
        s1, s2 = card.service_entitlement_ids.sorted('service_no')[:2]
        ticket = self._ticket()
        with self._today(date(2026, 11, 1)):
            wizard = self._wizard(ticket, self.helpdesk_user, case_type='free_service')
            self.assertEqual(wizard.available_service_ids, card.service_entitlement_ids)
            wizard.write({'service_entitlement_ids': [(6, 0, (s1 | s2).ids)],
                          'merged_adhoc_request': True,
                          'merged_adhoc_description': 'Gas leak complaint'})
            case = self.env['warranty.case'].browse(wizard.action_create()['res_id'])
        self.assertEqual((case.service_entitlement_ids, case.warranty_card_id), (s1 | s2, card))
        self.assertEqual((s1.helpdesk_ticket_id, s1.warranty_case_ids), (ticket, case))
        self.assertTrue(case.merged_adhoc_request)
        self.assertEqual(case.merged_adhoc_description, 'Gas leak complaint')

    def test_05_link_rules(self):
        """Only pending services of the case customer; one active case per service (approved
        C); allowed again after Rejected / Closed; only while New; unlink clears the ticket."""
        card = self._card()
        s1, s2, s3 = card.service_entitlement_ids.sorted('service_no')
        foreign = self._card(partner=self.other_customer).service_entitlement_ids[:1]
        ticket = self._ticket()
        with self._today(date(2026, 11, 1)):
            case = self._create_case(ticket, service_entitlement_ids=[(6, 0, s1.ids)])
            with self.assertRaises(ValidationError):
                case.service_entitlement_ids = [(4, foreign.id)]
            s3.state = 'expired'
            with self.assertRaises(ValidationError):
                case.service_entitlement_ids = [(4, s3.id)]
            with self.assertRaises(ValidationError):
                self._create_case(self._ticket(), service_entitlement_ids=[(6, 0, s1.ids)])
            case.service_entitlement_ids = [(4, s2.id)]
            case.service_entitlement_ids = [(3, s2.id)]
            self.assertFalse(s2.helpdesk_ticket_id)
            case.sudo().state = 'rejected'
            second = self._create_case(self._ticket(name='Again'),
                                       service_entitlement_ids=[(6, 0, s1.ids)])
            self.assertEqual(s1.helpdesk_ticket_id, second.helpdesk_ticket_id)
            # Cross-card merge D2: changes allowed while Eligibility Checked (reset to New),
            # refused after approval.
            second.sudo().state = 'eligibility_checked'
            second.service_entitlement_ids = [(4, s2.id)]
            self.assertEqual(second.state, 'new')
            second.sudo().state = 'approved'
            with self.assertRaises(UserError):
                second.service_entitlement_ids = [(3, s2.id)]

    def test_06_several_cases_and_all_types(self):
        """Several cases per ticket; every SRS case type, AMC included (no AMC logic)."""
        ticket = self._ticket()
        types = [key for key, __ in self.env['warranty.case']._fields['case_type'].selection]
        self.assertEqual(types, ['warranty_complaint', 'free_service', 'amc',
                                 'chargeable_inspection', 'chargeable_repair', 'replacement',
                                 'repeat_complaint'])
        self._unrelated_card()
        cases = self.env['warranty.case']
        for case_type in types:
            cases |= self._create_case(ticket, case_type=case_type)
        self.assertEqual((ticket.warranty_case_count, set(cases.mapped('state'))),
                         (7, {'new'}))
        self.assertEqual(
            [key for key, __ in cases._fields['state'].selection],
            ['new', 'eligibility_checked', 'approved', 'rejected', 'chargeable', 'job_created',
             'in_progress', 'completed', 'closed'])
        action = ticket.action_view_warranty_cases()
        self.assertEqual(action['domain'], [('helpdesk_ticket_id', '=', ticket.id)])

    def test_07_part2_unchanged(self):
        """Linking does not change the service status, dates, merge status, schedule or
        monitoring (approved B)."""
        card = self._card()
        s1 = card.service_entitlement_ids.sorted('service_no')[:1]
        with self._today(date(2026, 11, 1)):
            self._create_case(self._ticket(), service_entitlement_ids=[(6, 0, s1.ids)])
        self.assertEqual((s1.state, s1.due_date, s1.merge_status, s1.scheduled_date),
                         ('draft', date(2026, 11, 15), 'not_merged', False))
        with self._today(date(2026, 11, 16)):
            self.env['warranty.service.entitlement']._cron_monitor_free_services()
        self.assertEqual(s1.state, 'missed', 'monitoring unchanged')

    def test_08_security(self):
        """Internal users read; Helpdesk users create / edit; Helpdesk managers delete New
        cases only; other company cases are not visible."""
        self._unrelated_card()
        ticket = self._ticket()
        case = self._create_case(ticket, self.helpdesk_user)
        self.assertTrue(case.with_user(self.internal_user).read(['name']))
        with self.assertRaises(AccessError):
            self._create_case(ticket, self.internal_user)
        with self.assertRaises(AccessError):
            case.with_user(self.helpdesk_user).unlink()
        processed = self._create_case(ticket)
        processed.sudo().state = 'eligibility_checked'
        with self.assertRaises(UserError):
            processed.with_user(self.helpdesk_manager).unlink()
        case.with_user(self.helpdesk_manager).unlink()
        self.assertFalse(self.env['warranty.case'].with_user(self.foreign_user).search(
            [('id', '=', processed.id)]))
        with self.assertRaises(UserError):
            self._ticket(partner_id=False).action_create_warranty_case()

    def test_09_views(self):
        """Ticket: Create Warranty Case button, Warranty Cases smart button, Warranty tab;
        menus under Warranty and Helpdesk."""
        arch = etree.fromstring(self.env.ref(
            'warranty_management_helpdesk.helpdesk_ticket_view_form_warranty').arch)
        self.assertTrue(arch.xpath("//button[@name='action_create_warranty_case']"))
        self.assertTrue(arch.xpath("//button[@name='action_view_warranty_cases']"))
        page = arch.xpath("//page[@name='warranty']")[0]
        for name in ('warranty_site_id', 'warranty_product_id', 'warranty_serial_id',
                     'warranty_pending_service_ids'):
            self.assertTrue(page.xpath(".//field[@name='%s']" % name), name)
        for menu in ('menu_warranty_case', 'menu_helpdesk_warranty_case'):
            self.assertEqual(self.env.ref('warranty_management_helpdesk.%s' % menu).action,
                             self.env.ref('warranty_management_helpdesk.action_warranty_case'))
        form = Form(self._ticket())
        self.assertEqual(form.name, 'AC not cooling', 'ticket form with the Warranty tab loads')

    def test_10_site_address(self):
        """The ticket's Site Address is shown in Create Warranty Case (editable) and copied to
        the case; the Site keeps coming from the ticket."""
        self._card()
        ticket = self._ticket(warranty_site_address='12 Lake Road, Colombo 3')
        wizard = self._wizard(ticket)
        self.assertEqual(wizard.site_address, '12 Lake Road, Colombo 3')
        case = self._create_case(ticket)
        self.assertEqual((case.warranty_site_address, case.site_id),
                         ('12 Lake Road, Colombo 3', ticket.warranty_site_id))
        edited = self._create_case(self._ticket(warranty_site_address='old'),
                                   site_address='Unit 4, 12 Lake Road')
        self.assertEqual(edited.warranty_site_address, 'Unit 4, 12 Lake Road')
