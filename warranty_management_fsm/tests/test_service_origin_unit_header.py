from datetime import timedelta

from odoo import fields
from odoo.tests import Form, tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceOriginUnitHeader(ServiceJobCommon):
    """Header Product / Serial No. of a service-origin job's ticket and warranty case: set from
    the only unit of the job, never chosen among several units; normal tickets unchanged."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('header_tech', 'industry_fsm.group_fsm_user')
        cls.env['hr.employee'].create({'name': 'Header Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.company.write({'warranty_draft_job_team_id': cls.team.id})
        cls.policy.auto_case_item_ids = cls.item_service

    def _first(self, cards):
        return self.env['warranty.service.entitlement'].union(*[
            card.service_entitlement_ids.sorted('service_no')[:1] for card in cards])

    def _create_job(self, services):
        wizard = self.env['warranty.service.job.create.wizard'].with_user(
            self.helpdesk_user).create({
                'entitlement_ids': [(6, 0, services.ids)],
                'planned_date': fields.Datetime.now() + timedelta(days=2),
                'main_technician_id': self.tech.id})
        return self.env['warranty.service.job'].browse(wizard.action_create()['res_id'])

    def _with_serial(self, card, name):
        unit = card.unit_warranty_ids
        lot = self.env['stock.lot'].create({'name': name, 'product_id': unit.product_id.id})
        unit._warranty_system_write({'serial_ids': [(6, 0, lot.ids)]})
        return unit, lot

    def _browser_case(self, ticket):
        """Create Warranty Case as the browser does it: the form saves only editable fields."""
        action = ticket.with_user(self.helpdesk_user).action_create_warranty_case()
        form = Form(self.env[action['res_model']].with_user(self.helpdesk_user)
                    .with_context(action['context']))
        shown = (form.product_id, form.serial_id)
        case = self.env['warranty.case'].browse(form.save().action_create()['res_id'])
        return shown, case

    def test_01_single_unit_flow(self):
        """Free service -> job -> ticket -> case: the unit's Product and Serial No. on the ticket,
        the case and the job; eligibility and the job link unchanged."""
        unit, lot = self._with_serial(self.card, 'HDR-SN-001')
        services = self._first(self.card)
        job = self._create_job(services)
        ticket = job.with_user(self.helpdesk_user)._warranty_link_ticket()
        self.assertEqual((ticket.warranty_product_id, ticket.warranty_serial_id),
                         (unit.product_id, lot))
        shown, case = self._browser_case(ticket)
        self.assertEqual(shown, (unit.product_id, lot), 'the wizard shows them')
        self.assertEqual((case.product_id, case.serial_id), (unit.product_id, lot),
                         'kept when the browser saves the wizard')
        self.assertEqual((job.warranty_case_id, case.service_entitlement_ids,
                          case.service_unit_ids), (case, services, unit))
        self.assertEqual((job.product_id, job.serial_id), (unit.product_id, lot))
        case.with_user(self.helpdesk_user).action_check_eligibility()
        self.assertEqual((case.state, case.eligibility_result, case.warranty_card_id,
                          case.warranty_unit_id),
                         ('eligibility_checked', 'eligible', self.card, unit))

    def test_02_single_unit_without_serial(self):
        """One unit without serial: the Product, no Serial No."""
        unit = self.card.unit_warranty_ids
        self.assertFalse(unit.serial_ids)
        job = self._create_job(self._first(self.card))
        ticket = job.with_user(self.helpdesk_user)._warranty_link_ticket()
        self.assertEqual((ticket.warranty_product_id, ticket.warranty_serial_id.ids),
                         (unit.product_id, []))
        shown, case = self._browser_case(ticket)
        self.assertEqual((case.product_id, case.serial_id.ids), (unit.product_id, []))
        case.with_user(self.helpdesk_user).action_check_eligibility()
        self.assertEqual(case.eligibility_result, 'eligible')

    def test_03_several_units_no_header(self):
        """Several units: nothing arbitrary in the headers; every unit stays on the case and
        in the linked services' unit details."""
        second = self._card()
        self._with_serial(self.card, 'HDR-SN-A')
        self._with_serial(second, 'HDR-SN-B')
        services = self._first(self.card | second)
        job = self._create_job(services)
        ticket = job.with_user(self.helpdesk_user)._warranty_link_ticket()
        self.assertFalse(ticket.warranty_product_id or ticket.warranty_serial_id)
        shown, case = self._browser_case(ticket)
        self.assertFalse(shown[0] or shown[1])
        self.assertFalse(case.product_id or case.serial_id or job.product_id)
        self.assertEqual(case.service_unit_ids, (self.card | second).unit_warranty_ids)
        for service in services:
            unit = service.warranty_card_id.unit_warranty_ids
            self.assertIn(unit.name, service.with_context(
                warranty_service_job_id=job.id).warranty_job_units_display)

    def test_04_existing_ticket_values_kept(self):
        """Linking an existing ticket fills only empty values; another product is kept, and a
        serial is added only to the same product."""
        unit, lot = self._with_serial(self.card, 'HDR-SN-002')
        other = self._unrelated_card()
        kept = self._ticket(is_warranty=True, warranty_product_id=other.product_id.id)
        job = self._create_job(self._first(self.card))
        job.with_user(self.helpdesk_user)._warranty_link_ticket(ticket=kept)
        self.assertEqual((kept.warranty_product_id, kept.warranty_serial_id.ids),
                         (other.product_id, []), 'another product is not replaced')
        same = self._ticket(is_warranty=True, warranty_product_id=unit.product_id.id)
        empty = self._ticket(is_warranty=True)
        second, second_lot = self._with_serial(self._card(), 'HDR-SN-003')
        third, third_lot = self._with_serial(self._card(), 'HDR-SN-004')
        self._create_job(self._first(second.warranty_card_id)).with_user(
            self.helpdesk_user)._warranty_link_ticket(ticket=same)
        self._create_job(self._first(third.warranty_card_id)).with_user(
            self.helpdesk_user)._warranty_link_ticket(ticket=empty)
        self.assertEqual((same.warranty_product_id, same.warranty_serial_id),
                         (unit.product_id, second_lot), 'same product: the serial is added')
        self.assertEqual((empty.warranty_product_id, empty.warranty_serial_id),
                         (third.product_id, third_lot), 'empty: both filled')

    def test_05_normal_ticket_unchanged(self):
        """A ticket without service-origin job: the user's Product / Serial No. go to the case
        as before."""
        unit, lot = self._with_serial(self.card, 'HDR-SN-005')
        ticket = self._ticket(is_warranty=True, warranty_product_id=unit.product_id.id,
                              warranty_serial_id=lot.id)
        action = ticket.with_user(self.helpdesk_user).action_create_warranty_case()
        form = Form(self.env[action['res_model']].with_user(self.helpdesk_user)
                    .with_context(action['context']))
        form.case_type = 'warranty_complaint'
        self.assertEqual((form.product_id, form.serial_id), (unit.product_id, lot))
        case = self.env['warranty.case'].browse(form.save().action_create()['res_id'])
        self.assertEqual((case.product_id, case.serial_id), (unit.product_id, lot))

    def test_06_ticket_header_visibility(self):
        """Linked tickets hide an empty header Product / Serial No.; others are unchanged."""
        arch = self.env['helpdesk.ticket'].get_view(view_type='form')['arch']
        for name in ('warranty_product_id', 'warranty_serial_id'):
            self.assertRegex(
                arch, r'<field name="%s"[^>]*invisible="warranty_is_linked and not '
                      r'warranty_product_id"' % name)
