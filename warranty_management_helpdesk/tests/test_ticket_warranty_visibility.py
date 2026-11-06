import importlib.util
import os

from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group

from .test_warranty_case import TestWarrantyCase


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestTicketWarrantyVisibility(TestWarrantyCase):
    """Is Warranty on Helpdesk tickets: Warranty tab, available cards, Create Warranty Case."""

    def _plain_ticket(self, **vals):
        return self._ticket(is_warranty=False, **vals)

    def test_01_view(self):
        """Is Warranty after the customer; tab and button visibility (Odoo 18 expressions)."""
        arch = etree.fromstring(self.env['helpdesk.ticket'].get_view(
            self.env.ref('helpdesk.helpdesk_ticket_view_form').id)['arch'])
        self.assertTrue(arch.xpath(
            "//field[@name='partner_id']/following-sibling::field[1][@name='is_warranty']"))
        self.assertEqual(arch.xpath("//page[@name='warranty']")[0].get('invisible'),
                         'not is_warranty')
        buttons = arch.xpath("//button[@name='action_create_warranty_case']")
        self.assertEqual(len(buttons), 1, 'no duplicate button')
        self.assertEqual(buttons[0].get('invisible'),
                         'not is_warranty or not partner_id or not warranty_has_cards')
        self.assertEqual(len(arch.xpath("//page[@name='warranty']")), 1, 'no duplicate tab')

    def test_02_normal_ticket(self):
        """Warranty unchecked (default): no cards offered, no case."""
        self._card()
        ticket = self.env['helpdesk.ticket'].create({
            'name': 'Printer jam', 'team_id': self.team.id, 'partner_id': self.contact.id})
        self.assertFalse(ticket.is_warranty)
        self.assertFalse(ticket.warranty_has_cards)
        with self.assertRaisesRegex(UserError, 'Tick Is Warranty'):
            ticket.with_user(self.helpdesk_user).action_create_warranty_case()
        with self.assertRaisesRegex(UserError, 'Tick Is Warranty'):
            self._wizard(ticket, self.helpdesk_user).action_create()

    def test_03_without_customer(self):
        ticket = self._ticket(partner_id=False)
        self.assertFalse(ticket.warranty_has_cards)
        with self.assertRaisesRegex(UserError, 'Set the customer'):
            ticket.action_create_warranty_case()

    def test_04_customer_without_warranty(self):
        ticket = self._ticket()
        self.assertFalse(ticket.warranty_available_card_ids)
        with self.assertRaisesRegex(UserError, 'no confirmed warranty card'):
            ticket.with_user(self.helpdesk_user).action_create_warranty_case()

    def test_05_customer_with_confirmed_card(self):
        """Only the customer's confirmed cards of the ticket company; products offered."""
        card = self._card()
        other_customer = self.env['res.partner'].create({'name': 'Other Hotel'})
        self._card(partner=other_customer, product=self.other_product)
        ticket = self._ticket()
        self.assertEqual(ticket.warranty_available_card_ids, card)
        self.assertEqual(ticket.warranty_available_product_ids, self.product)
        action = ticket.with_user(self.helpdesk_user).action_create_warranty_case()
        self.assertEqual(action['res_model'], 'warranty.case.create.wizard')
        case = self._create_case(ticket, self.helpdesk_user)
        self.assertEqual(case.helpdesk_ticket_id, ticket)
        ticket.company_id = self.env['res.company'].create({'name': 'Other Warranty Co'})
        self.assertFalse(ticket.warranty_has_cards, 'recomputed for another company')

    def test_06_only_draft_or_pending_cards(self):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'order_line': [(0, 0, {'product_id': self.product.id})]})
        confirm_and_group(order)
        self.assertIn(order.warranty_card_ids.state, ('draft', 'pending_installation'))
        ticket = self._ticket()
        self.assertFalse(ticket.warranty_has_cards)
        with self.assertRaisesRegex(UserError, 'no confirmed warranty card'):
            ticket.action_create_warranty_case()

    def test_07_customer_change(self):
        """Changing the customer recomputes the cards and drops the previous selection."""
        card = self._card()
        other_customer = self.env['res.partner'].create({'name': 'No Warranty Ltd'})
        with Form(self.env['helpdesk.ticket']) as form:
            form.name = 'AC noisy'
            form.team_id = self.team
            form.partner_id = self.contact
            form.is_warranty = True
            form.warranty_product_id = self.product
            self.assertEqual(form.warranty_card_id, card)
            form.partner_id = other_customer
            self.assertFalse(form.warranty_has_cards)
            self.assertFalse(form.warranty_product_id)
            self.assertFalse(form.warranty_card_id)

    def test_08_existing_ticket_with_case(self):
        """Unticking keeps the cases; creating a case ticks Is Warranty; the migration ticks
        historical warranty tickets."""
        self._card()
        ticket = self._ticket()
        case = self._create_case(ticket)
        ticket.is_warranty = False
        self.assertTrue(case.exists())
        self.assertEqual((ticket.warranty_case_ids, ticket.warranty_case_count), (case, 1))
        self.env['warranty.case'].create({'helpdesk_ticket_id': ticket.id,
                                          'case_type': 'warranty_complaint'})
        self.assertTrue(ticket.is_warranty, 'a case makes the ticket a warranty ticket')
        legacy = self._plain_ticket(warranty_product_id=self.product.id)
        plain = self._plain_ticket()
        ticket.is_warranty = False
        self.env.flush_all()
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'migrations', '18.0.1.0.3', 'post-migrate.py')
        spec = importlib.util.spec_from_file_location('warranty_ticket_migration', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '18.0.1.0.2')
        (ticket | legacy | plain).invalidate_recordset(['is_warranty'])
        self.assertEqual((ticket.is_warranty, legacy.is_warranty, plain.is_warranty),
                         (True, True, False))

    def test_09_unauthorized_direct_creation(self):
        """Without Helpdesk rights: no direct case creation; permissions unchanged."""
        self._card()
        ticket = self._ticket()
        internal = self._user('wvis_internal', 'base.group_user')
        with self.assertRaises(AccessError):
            self._wizard(ticket, internal).action_create()
        with self.assertRaises(AccessError):
            self.env['warranty.case'].with_user(internal).create(
                {'helpdesk_ticket_id': ticket.id, 'case_type': 'warranty_complaint'})

    def test_10_site_address(self):
        """Site Address: typed and saved, informational only; the hidden Site keeps its value
        and logic (free service matching, case site)."""
        arch = etree.fromstring(self.env['helpdesk.ticket'].get_view(
            self.env.ref('helpdesk.helpdesk_ticket_view_form').id)['arch'])
        page = arch.xpath("//page[@name='warranty']")[0]
        self.assertTrue(page.xpath(".//field[@name='warranty_site_address']"))
        self.assertEqual(page.xpath(".//field[@name='warranty_site_id']")[0].get('invisible'), '1')
        card = self._card(site=self.site_a)
        with Form(self.env['helpdesk.ticket']) as form:
            form.name = 'AC leaking'
            form.team_id = self.team
            form.partner_id = self.contact
            form.is_warranty = True
            form.warranty_site_address = 'No. 12, Galle Road, Colombo 03 - 4th floor'
            form.partner_id = self.env['res.partner'].create({'name': 'Walk-in Customer'})
            form.partner_id = self.contact
        ticket = form.record
        self.assertEqual(ticket.warranty_site_address, 'No. 12, Galle Road, Colombo 03 - 4th floor')
        services = card.service_entitlement_ids
        self.assertEqual(ticket.warranty_pending_service_ids & services, services,
                         'address not used for matching')
        ticket.warranty_site_id = self.site_a
        self.assertEqual(ticket.warranty_pending_service_ids & services, services)
        ticket.warranty_site_address = 'Somewhere else entirely'
        self.assertEqual(ticket.warranty_site_id, self.site_a, 'Site value preserved')
        case = self._create_case(ticket, self.helpdesk_user)
        self.assertEqual(case.site_id, self.site_a)
