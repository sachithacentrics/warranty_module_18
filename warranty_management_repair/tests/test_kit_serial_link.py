from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import Form, tagged
from odoo.tools.safe_eval import safe_eval

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_kit_link')
class TestKitSerialLink(ReplacementCommon):
    """Kit serials on the ticket, the Create Warranty Case wizard and the case (Part 7 Stage 2 fix
    in warranty_management_helpdesk). Here because a real kit delivery needs warranty_management_mrp,
    which the Helpdesk module does not depend on."""

    def setUp(self):
        super().setUp()
        self.company.warranty_replacement_gm_user_ids = self.gm
        self.card = self._card(self.kit)
        self.unit = self.card.unit_warranty_ids
        self.indoor_serial = self.unit.indoor_serial_id
        self.outdoor_serial = self.unit.outdoor_serial_id
        self.other_customer = self.env['res.partner'].create({'name': 'Other Kit Customer'})

    def _ticket(self, **vals):
        return self.env['helpdesk.ticket'].create(dict({
            'name': 'Kit ticket', 'team_id': self.team.id, 'is_warranty': True,
            'partner_id': self.partner.id, 'description': '<p>Broken</p>'}, **vals))

    def _other_customer_card(self):
        self.partner, customer = self.other_customer, self.partner
        try:
            return self._card(self.kit)
        finally:
            self.partner = customer

    def _choices(self, record, fname, product):
        """What the Serial No. list offers, from the domain of the field."""
        return self.env['stock.lot'].search(safe_eval(record._fields[fname].domain, {
            'product_id': product.id, 'warranty_product_id': product.id,
            'warranty_unit_serial_ids': record.warranty_unit_serial_ids.ids}))

    def _wizard(self, ticket):
        return self.env['warranty.case.create.wizard'].create({'helpdesk_ticket_id': ticket.id})

    def _case_from_wizard(self, ticket):
        """The screens in order: the wizard copies the product and serial of the ticket."""
        form = Form(self.env['warranty.case.create.wizard'].with_context(
            default_helpdesk_ticket_id=ticket.id))
        form.case_type = 'warranty_complaint'
        self.assertEqual(form.product_id, ticket.warranty_product_id)
        self.assertEqual(form.serial_id, ticket.warranty_serial_id)
        wizard = form.save()
        case = self.env['warranty.case'].browse(wizard.action_create()['res_id'])
        case.requested_item_ids = self.item
        return case

    def test_01_same_choices_on_all_three_forms(self):
        """Kit product: the serials of this customer's units, on the ticket, wizard and case. Not
        another customer's serial, and not a spare component serial in stock."""
        other_unit = self._other_customer_card().unit_warranty_ids
        spare = self._lot(self.indoor, 6)
        self.assertFalse(self.env['warranty.unit'].search([('serial_ids', 'in', spare.ids)]))
        ticket = self._ticket(warranty_product_id=self.kit.id)
        case = self.env['warranty.case'].create({
            'helpdesk_ticket_id': ticket.id, 'product_id': self.kit.id})
        expected = self.indoor_serial | self.outdoor_serial
        for record, fname in ((ticket, 'warranty_serial_id'), (self._wizard(ticket), 'serial_id'),
                              (case, 'serial_id')):
            with self.subTest(model=record._name):
                choices = self._choices(record, fname, self.kit)
                self.assertEqual(choices, expected)
                self.assertFalse(choices & other_unit.serial_ids)
                self.assertNotIn(spare, choices)

    def test_02_other_company_is_not_offered(self):
        other_company = self.env['res.company'].create({'name': 'Other Kit Company'})
        self.assertFalse(self.env['warranty.case']._warranty_unit_serials(
            self.partner, other_company, self.kit))

    def test_03_kit_product_and_serial_identify_card_and_unit(self):
        """Both serials, in the ticket form: the automatic lookup finds the card and the unit."""
        for serial in (self.indoor_serial, self.outdoor_serial):
            with self.subTest(serial=serial.name):
                form = Form(self._ticket())
                form.warranty_product_id = self.kit
                form.warranty_serial_id = serial
                self.assertEqual(form.warranty_card_id, self.card)
                self.assertEqual(form.warranty_unit_id, self.unit)
                self.assertEqual(form.save().warranty_serial_id, serial)

    def test_04_product_change_clears_only_an_invalid_serial(self):
        form = Form(self._ticket())
        form.warranty_serial_id = self.indoor_serial  # no product yet: the list is not filtered
        self.assertEqual(form.warranty_card_id, self.card)
        form.warranty_product_id = self.kit
        self.assertEqual(form.warranty_serial_id, self.indoor_serial, "Valid for the kit: kept.")
        single_card = self._card(self.single)
        form = Form(self._ticket())
        form.warranty_product_id = self.kit
        form.warranty_serial_id = self.indoor_serial
        form.warranty_product_id = self.single
        self.assertFalse(form.warranty_serial_id, "A kit serial is not valid for another product.")
        form.warranty_serial_id = single_card.unit_warranty_ids.serial_ids
        form.warranty_product_id = self.kit
        self.assertFalse(form.warranty_serial_id, "A single serial is not valid for the kit.")
        form.warranty_serial_id = self.outdoor_serial
        form.warranty_product_id = self.env['product.product']
        self.assertFalse(form.warranty_serial_id, "Empty product: cleared, as before.")

    def test_05_customer_change_drops_the_kit_serial(self):
        """Part 3 behaviour, unchanged: the customer change drops the product and the serial."""
        self._other_customer_card()
        form = Form(self._ticket())
        form.warranty_product_id = self.kit
        form.warranty_serial_id = self.indoor_serial
        form.partner_id = self.other_customer
        self.assertFalse(form.warranty_product_id)
        self.assertFalse(form.warranty_serial_id)
        self.assertFalse(form.warranty_card_id)

    def test_06_single_product_is_unchanged(self):
        """All serials of the product are offered, as before; the lookup and case work as before."""
        card = self._card(self.single)
        unit = card.unit_warranty_ids
        ticket = self._ticket(warranty_product_id=self.single.id)
        self.assertEqual(self._choices(ticket, 'warranty_serial_id', self.single),
                         self.env['stock.lot'].search([('product_id', '=', self.single.id)]))
        ticket.warranty_serial_id = unit.serial_ids
        self.assertEqual((ticket.warranty_card_id, ticket.warranty_unit_id), (card, unit))
        case = self._case_from_wizard(ticket)
        case.action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'eligible', case.eligibility_reason)
        self.assertEqual(case.warranty_unit_id, unit)
        form = Form(self._ticket(warranty_product_id=self.single.id,
                                 warranty_serial_id=unit.serial_ids.id))
        form.warranty_product_id = self.single
        self.assertEqual(form.warranty_serial_id, unit.serial_ids)

    def test_07_full_flow_indoor_and_outdoor(self):
        """Ticket, wizard, eligibility and replacement, with the kit as product: same card and
        unit, only the serial of the role changes."""
        for kind, product, new_number in (('indoor', self.indoor, 5), ('outdoor', self.outdoor, 5)):
            with self.subTest(kind=kind):
                old = self.unit[kind + '_serial_id']
                other = self.unit[('outdoor' if kind == 'indoor' else 'indoor') + '_serial_id']
                ticket = self._ticket(warranty_product_id=self.kit.id, warranty_serial_id=old.id)
                self.assertEqual((ticket.warranty_card_id, ticket.warranty_unit_id),
                                 (self.card, self.unit))
                case = self._case_from_wizard(ticket)
                case.action_check_eligibility()
                self.assertEqual(case.eligibility_result, 'eligible', case.eligibility_reason)
                self.assertEqual((case.warranty_card_id, case.warranty_unit_id),
                                 (self.card, self.unit))
                self.assertEqual(case.action_warranty_create_replacement()['context'][
                    'default_replacement_type'], kind)
                self._approved_state(case)
                new = self._lot(product, new_number)
                replacement = self._request(case, kind, new)
                self.assertEqual(replacement.product_id, product)
                self.assertEqual(replacement.old_serial_id, old)
                self.assertEqual(replacement.unaffected_serial_id, other)
                replacement.action_warranty_replacement_submit()
                replacement.with_user(self.gm).action_warranty_replacement_approve()
                self._validate(replacement.sudo().return_picking_id)
                self._validate(replacement.sudo().delivery_picking_id)
                self.assertEqual(replacement.state, 'done')
                self.assertEqual(self.unit[kind + '_serial_id'], new)
                self.assertEqual(self.unit.serial_ids, new | other)
                self.assertEqual(self.card.unit_warranty_ids, self.unit)
                offered = self._choices(self._ticket(warranty_product_id=self.kit.id),
                                        'warranty_serial_id', self.kit)
                self.assertIn(new, offered)
                self.assertNotIn(old, offered)

    def test_08_checks_are_not_bypassed(self):
        """A serial written past the list gets no card; the validity check still decides."""
        other_serial = self._other_customer_card().unit_warranty_ids.indoor_serial_id
        spare = self._lot(self.indoor, 6)
        for serial in (other_serial, spare):
            with self.subTest(serial=serial.name):
                ticket = self._ticket(warranty_product_id=self.kit.id, warranty_serial_id=serial.id)
                self.assertFalse(ticket.warranty_card_id)
                case = self._case_from_wizard(ticket)
                case.action_check_eligibility()
                self.assertEqual(case.eligibility_result, 'manual_review')
                self.assertFalse(case.warranty_card_id)
        past = fields.Date.today() - relativedelta(years=3)
        self.unit._warranty_system_write({
            'start_date': past, 'end_date': past + relativedelta(years=1)})
        ticket = self._ticket(warranty_product_id=self.kit.id,
                              warranty_serial_id=self.indoor_serial.id)
        case = self._case_from_wizard(ticket)
        case.action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'out_of_warranty', case.eligibility_reason)

    def test_09_serial_of_the_kit_product_gets_no_card(self):
        """A serial of the kit product itself (not delivered, on no unit) stays in the list like
        any serial of the product, and the eligibility check refuses it."""
        self.kit.tracking = 'serial'
        parent = self.env['stock.lot'].create({'name': 'WRKIT-01', 'product_id': self.kit.id})
        ticket = self._ticket(warranty_product_id=self.kit.id, warranty_serial_id=parent.id)
        self.assertIn(parent, self._choices(ticket, 'warranty_serial_id', self.kit))
        self.assertFalse(ticket.warranty_card_id)
        case = self._case_from_wizard(ticket)
        case.action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'manual_review')

    def test_11_downstream_of_a_kit_case(self):
        """Service Job, Repair and Material Request with the kit as product and a component serial."""
        ticket = self._ticket(warranty_product_id=self.kit.id,
                              warranty_serial_id=self.indoor_serial.id)
        case = self._case_from_wizard(ticket)
        case.action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'eligible', case.eligibility_reason)
        self._approved_state(case)
        job = case.with_user(self.coordinator)._warranty_create_case_job()
        self.assertEqual((job.product_id, job.serial_id, job.warranty_unit_id),
                         (self.kit, self.indoor_serial, self.unit))
        self.assertEqual(ticket._warranty_repair_machine(), (self.indoor, self.indoor_serial))
        request = self.env['material.purchase.requisition'].new({'warranty_case_id': case.id})
        self.assertEqual((request.warranty_product_id, request.warranty_serial_id),
                         (self.kit, self.indoor_serial))

    def test_10_helpdesk_user_without_stock_rights(self):
        """A Helpdesk user without Inventory rights gets the same list."""
        user = self._user('wr_helpdesk_only', 'helpdesk.group_helpdesk_user')
        ticket = self._ticket(warranty_product_id=self.kit.id).with_user(user)
        self.assertEqual(ticket.warranty_unit_serial_ids.ids,
                         (self.indoor_serial | self.outdoor_serial).sorted().ids)
        form = Form(ticket)
        form.warranty_serial_id = self.indoor_serial.with_user(user)
        self.assertEqual(form.warranty_card_id, self.card)
