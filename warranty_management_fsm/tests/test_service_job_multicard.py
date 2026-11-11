from datetime import timedelta

from dateutil.relativedelta import relativedelta

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobMultiCard(ServiceJobCommon):
    """Cross-Warranty-Card Service Merge (approved Option A, D1-D8, UI 1-4): one ticket, one
    case, one job, one visit for free services of several warranty cards."""

    check_service_windows = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_m_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.multicard@example.com'
        cls.env['hr.employee'].create({'name': 'Multi Card Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.policy.write({'grace_period_days': 30, 'service_due_alert_days': 7})
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False
        cls.company.write({'warranty_signoff_required': False,
                           'warranty_worksheet_checklist_required': False,
                           'warranty_worksheet_attachment_required': False})
        Partner = cls.env['res.partner']
        cls.addr_main = Partner.create({'name': 'ABC Hotel - Main Building',
                                        'parent_id': cls.customer.id, 'type': 'delivery',
                                        'street': 'No 5 Galle Road', 'city': 'Colombo'})
        cls.addr_same = Partner.create({'name': 'ABC Hotel - Plant Room',
                                        'parent_id': cls.customer.id, 'type': 'delivery',
                                        'street': ' no 5  GALLE road', 'city': 'colombo'})
        cls.addr_other = Partner.create({'name': 'ABC Hotel - Kandy',
                                         'parent_id': cls.customer.id, 'type': 'delivery',
                                         'street': '12 Peradeniya Road', 'city': 'Kandy'})

    # ------------------------------------------------------------------ helpers
    def _ac_card(self, site=None, due_in=10, qty=1):
        """Confirmed card whose first free service is due in `due_in` days (window: 7 days
        before .. 30 days after)."""
        today = self.company._warranty_today()
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'partner_shipping_id': (site or self.addr_main).id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': qty})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, today - relativedelta(months=4) + timedelta(days=due_in))
        card.action_confirm_warranty()
        return card

    def _first(self, cards):
        return self.env['warranty.service.entitlement'].union(*[
            card.service_entitlement_ids.sorted('service_no')[:1] for card in cards])

    def _case(self, services, site=None):
        ticket = self._ticket(warranty_site_id=(site or self.addr_main).id)
        action = ticket.with_user(self.helpdesk_user).action_view_warranty_pending_services()
        case = self.env['warranty.case'].browse(services.with_user(self.helpdesk_user)
                                                .with_context(action['context'])
                                                .action_create_warranty_case_from_services()['res_id'])
        case.with_user(self.creator).requested_item_ids = self.item_service
        return case

    def _check(self, case):
        case.with_user(self.helpdesk_user).action_check_eligibility()
        return case.eligibility_result

    def _notes(self, record):
        return ' '.join(record.message_ids.mapped('body'))

    def _job(self, case, days=10):
        self.assertEqual(self._check(case), 'eligible', self._notes(case)[:2000])
        case.with_user(self.approver_a).action_approve_case()
        action = case.with_user(self.helpdesk_user).action_prepare_service_job()
        job = self.env['warranty.service.job'].browse(action['res_id'])
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=days),
            'main_technician_id': self.tech.id})
        return job

    def _confirm(self, job):
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        return job.visit_ids

    def _work(self, task, user=None):
        user = user or self.tech
        task.with_user(user).action_timer_start()
        action = task.with_user(user).action_timer_stop()
        self.env[action['res_model']].with_user(user).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Maintenance'}).save_timesheet()

    # ------------------------------------------------------------------ tests
    def test_161_eight_ac_acceptance(self):
        """8 ACs / 8 cards / 8 services: one ticket, case, job and visit; 8 worksheets with
        their own service, card, unit and product; each service consumed once on its card."""
        cards = self.env['warranty.card'].union(*[self._ac_card() for _ in range(8)])
        services = self._first(cards)
        ticket = self._ticket(warranty_site_id=self.addr_main.id)
        self.assertEqual(ticket.warranty_pending_service_count, 24)
        case = self._case(services)
        self.assertEqual((len(case.service_entitlement_ids), case.service_card_ids,
                          case.service_unit_ids), (8, cards, cards.unit_warranty_ids))
        job = self._job(case)
        self.assertEqual((job.entitlement_ids, job.warranty_card_ids), (services, cards))
        task = self._confirm(job)
        self.assertEqual(len(task), 1)
        sheets = job.worksheet_ids
        self.assertEqual(len(sheets), 8)
        for sheet in sheets:
            self.assertEqual(sheet.warranty_card_id, sheet.entitlement_id.warranty_card_id)
            unit = sheet.warranty_card_id.unit_warranty_ids
            self.assertEqual((sheet.unit_id, sheet.product_id, sheet.warranty_unit_id),
                             (unit, self.product, unit))
        self.assertEqual(len(set(sheets.mapped('warranty_card_id'))), 8)
        self._work(task)
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual((job.state, case.state), ('completed', 'completed'))
        self.assertEqual(set(services.mapped('state')), {'completed'})
        for card in cards:
            self.assertEqual((card.free_services_used, card.free_services_balance), (1, 2))
            self.assertIn('Free services consumed', self._notes(card))
        for service in services:
            self.assertIn('Completed and consumed', self._notes(service))

    def test_162_ineligible_card_remove_and_reapprove(self):
        """D1 / D2: one ineligible card blocks the case with its card / service / reason; the
        service is removed (case back to New), checked and approved again; approval To-Dos of
        an earlier Eligible result are closed when the selection changes."""
        cards = self.env['warranty.card'].union(*[self._ac_card() for _ in range(3)])
        services = self._first(cards)
        case = self._case(services)
        bad_card = cards[2]
        bad_card.sudo().state = 'suspended'
        self.assertEqual(self._check(case), 'not_eligible')
        self.assertIn('%s (%s): warranty card is Suspended' % (bad_card.name, services[2].name),
                      self._notes(case))
        case.with_user(self.helpdesk_user).service_entitlement_ids = [(3, services[2].id)]
        self.assertEqual((case.state, case.eligibility_result), ('new', False))
        self.assertEqual(case.service_unit_ids, cards[:2].unit_warranty_ids)
        self.assertEqual(self._check(case), 'eligible')
        self.assertTrue(case.case_approval_activity_ids.filtered('active'))
        case.with_user(self.helpdesk_user).service_entitlement_ids = [(3, services[1].id)]
        self.assertEqual(case.state, 'new')
        self.assertFalse(case.case_approval_activity_ids.exists().filtered('active'))
        self.assertIn('Eligibility reset', self._notes(case))
        self.assertEqual(self._check(case), 'eligible')
        case.with_user(self.approver_a).action_approve_case()
        with self.assertRaisesRegex(UserError, 'New or Eligibility Checked'):
            case.with_user(self.helpdesk_user).service_entitlement_ids = [(4, services[1].id)]

    def test_163_sites_equivalent_different_override(self):
        """D6: an equivalent address (same customer, same normalized address) merges; another
        address needs a Helpdesk manager confirmation with reason (not a Helpdesk user, not
        another customer's address)."""
        main = self._ac_card(self.addr_main)
        same = self._ac_card(self.addr_same)
        other = self._ac_card(self.addr_other)
        ticket = self._ticket(warranty_site_id=self.addr_main.id)
        pending = ticket.warranty_pending_service_ids
        self.assertIn(self._first(same), pending)
        self.assertNotIn(self._first(other), pending)
        matching = self._case(self._first(main | same))
        self.assertEqual(self._check(matching), 'eligible')
        self.assertFalse(matching.warranty_site_confirmation_needed, 'all sites match: no button')
        main2 = self._ac_card(self.addr_main)
        case = self.env['warranty.case'].create({
            'helpdesk_ticket_id': self._ticket(warranty_site_id=self.addr_main.id).id,
            'case_type': 'free_service', 'requested_item_ids': [(6, 0, self.item_service.ids)],
            'service_entitlement_ids': [(6, 0, self._first(main2 | other).ids)]})
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('Confirm Same Site', self._notes(case))
        self.assertTrue(case.warranty_site_confirmation_needed, 'a real mismatch: the button shows')
        self.assertTrue(case.with_user(self.helpdesk_user).warranty_site_confirmation_needed)
        Case = self.env['warranty.case']
        form = 'warranty_management_helpdesk.warranty_case_view_form'
        for user, count in ((self.helpdesk_user, 0), (self.helpdesk_manager, 1)):
            arch = Case.with_user(user).get_view(self.env.ref(form).id, 'form')['arch']
            self.assertEqual(arch.count('name="action_open_site_wizard"'), count, user.login)
        with self.assertRaises(AccessError):
            case.with_user(self.helpdesk_user).action_open_site_wizard()
        with self.assertRaises(AccessError):
            case.with_user(self.helpdesk_user)._warranty_confirm_same_site(self.addr_other, 'x')
        action = case.with_user(self.helpdesk_manager).action_open_site_wizard()
        wizard = self.env[action['res_model']].with_context(action['context']).create(
            {'reason': 'x'})
        self.assertEqual(wizard.candidate_ids, self.addr_other)
        with self.assertRaisesRegex(UserError, 'not a service address'):
            case.with_user(self.helpdesk_manager)._warranty_confirm_same_site(
                self.other_customer, 'same building')
        with self.assertRaisesRegex(UserError, 'site_confirmed|Confirm Same Site'):
            case.with_user(self.helpdesk_user).write(
                {'site_confirmed_partner_ids': [(4, self.addr_other.id)]})
        case.with_user(self.helpdesk_manager)._warranty_confirm_same_site(
            self.addr_other, 'Verified on site: same plant room')
        self.assertEqual((case.state, case.site_confirmed_by_id, case.site_confirmed_partner_ids),
                         ('new', self.helpdesk_manager, self.addr_other))
        self.assertFalse(case.warranty_site_confirmation_needed, 'confirmed: no button')
        self.assertEqual(self._check(case), 'eligible')
        # Nothing left to confirm (all addresses match): no empty wizard.
        with self.assertRaisesRegex(UserError, 'already match the case site'):
            case.with_user(self.helpdesk_manager).action_open_site_wizard()

    def test_164_date_windows(self):
        """D3 revised: non-overlapping service windows no longer block the case (cross-card
        merge, test_169); a planned date (Plan Job, Plan Next Visit) outside a window is a
        service-level note, not a block."""
        soon, late = self._ac_card(due_in=10), self._ac_card(due_in=100)
        case = self._case(self._first(soon | late))
        self.assertEqual(self._check(case), 'eligible', self._notes(case)[:1500])
        mid, soon2 = self._ac_card(due_in=20), self._ac_card(due_in=10)
        services = self._first(soon2 | mid)
        job = self._job(self._case(services), days=5)
        self.assertIn('outside the service window of %s' % services[1].name,
                      ' '.join(job._warranty_planned_date_problems()))
        job.with_user(self.helpdesk_user).planned_date = fields.Datetime.now() + timedelta(days=15)
        task = self._confirm(job)
        self._work(task)
        job.with_user(self.tech)._warranty_visit_not_completed(
            task, 'customer_unavailable', 'Closed office', 'reschedule')
        second = job.with_user(self.helpdesk_user)._warranty_plan_next_visit(
            fields.Datetime.now() + timedelta(days=60), self.tech)
        self.assertEqual((job.state, second.warranty_visit_no), ('rescheduled', 2))
        self.assertIn('outside the service window of %s' % services[0].name,
                      ' '.join(job.message_ids.mapped('body')))

    def test_169_cross_card_different_due_dates(self):
        """Cross-card merge clarification (D3 revised): Free Service 1 of two cards of the same
        customer / site with different due dates -> one case, one job, ONE visit with one
        worksheet per service, each consumed on its own card (due dates unchanged); the
        service-origin route (job before ticket) accepts them too; Enforce Service Sequence:
        services 1 + 2 of one card refused when ON, merged when OFF."""
        card_a, card_b = self._ac_card(due_in=10), self._ac_card(due_in=100)
        services = self._first(card_a | card_b)
        dues = services.mapped('due_date')
        self.assertEqual((dues[1] - dues[0]).days, 90)
        job = self._job(self._case(services))
        self.assertEqual((job.entitlement_ids, job.warranty_card_ids), (services, card_a | card_b))
        task = self._confirm(job)
        self.assertEqual(len(task), 1)
        self.assertEqual(job.worksheet_ids.entitlement_id, services)
        self._work(task)
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(set(services.mapped('state')), {'completed'})
        self.assertEqual(((card_a.free_services_used, card_b.free_services_used),
                          services.mapped('due_date')), ((1, 1), dues))
        # SRS route: one Draft service-origin job before the ticket.
        origin = self._first(self._ac_card(due_in=10) | self._ac_card(due_in=100))
        wizard = self.env['warranty.service.job.create.wizard'].with_user(
            self.helpdesk_user).create({'entitlement_ids': [(6, 0, origin.ids)],
                                        'main_technician_id': self.tech.id})
        origin_job = self.env['warranty.service.job'].browse(wizard.action_create()['res_id'])
        self.assertEqual((origin_job.state, origin_job.job_origin, origin_job.entitlement_ids,
                          origin_job.helpdesk_ticket_id.ids), ('draft', 'service', origin, []))
        # Same card: Enforce Service Sequence.
        card = self._ac_card()
        pair = card.service_entitlement_ids.sorted('service_no')[:2]
        card.sudo().service_sequence_required = True
        self.assertIn('Complete Previous Service First',
                      ' '.join(pair._warranty_sequence_problems()))
        card.sudo().service_sequence_required = False
        self.assertEqual(self._check(self._case(pair)), 'eligible')

    def test_165_duplicates_and_security(self):
        """D7: a service on an active case cannot be selected again; services of other
        customers / tickets and other companies are refused; only Helpdesk users."""
        cards = self.env['warranty.card'].union(*[self._ac_card() for _ in range(2)])
        services = self._first(cards)
        self._case(services)
        with self.assertRaisesRegex(ValidationError, 'already linked to the active warranty case'):
            self._case(services[:1])
        ticket = self._ticket(warranty_site_id=self.addr_main.id)
        other = self._card(partner=self.other_customer).service_entitlement_ids[:1]
        with self.assertRaisesRegex(UserError, 'not a pending free service of this ticket'):
            other.with_user(self.helpdesk_user).with_context(
                warranty_ticket_id=ticket.id).action_create_warranty_case_from_services()
        free = self._first(self._ac_card())
        with self.assertRaises(AccessError):
            free.with_user(self.internal_user).with_context(
                warranty_ticket_id=ticket.id).action_create_warranty_case_from_services()
        with self.assertRaises(AccessError):
            free.with_user(self.foreign_user).with_context(
                warranty_ticket_id=ticket.id).action_create_warranty_case_from_services()

    def test_166_multi_unit_card_worksheets(self):
        """D4: units of a multi-unit card are selected; one worksheet per selected unit (others
        none); every worksheet validated; the card-level service consumed once."""
        multi = self._ac_card(qty=3)
        single = self._ac_card()
        self.assertEqual(len(multi.unit_warranty_ids), 3)
        case = self._case(self._first(multi | single))
        self.assertEqual(case.service_unit_ids, (multi | single).unit_warranty_ids)
        skipped = multi.unit_warranty_ids[2]
        case.with_user(self.helpdesk_user).service_unit_ids = [(3, skipped.id)]
        job = self._job(case)
        task = self._confirm(job)
        sheets = job.worksheet_ids
        self.assertEqual(len(sheets), 3)
        self.assertEqual(sheets.unit_id, (multi | single).unit_warranty_ids - skipped)
        self.company.warranty_worksheet_attachment_required = True
        for sheet in sheets[:2]:
            sheet.sudo().attachment_ids = [(0, 0, {'name': 'report.pdf', 'raw': b'pdf'})]
        self._work(task)
        with self.assertRaisesRegex(UserError, '%s: at least one attachment' % sheets[2].name):
            task.with_user(self.tech).action_warranty_complete_visit()
        sheets[2].sudo().attachment_ids = [(0, 0, {'name': 'report.pdf', 'raw': b'pdf'})]
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual((multi.free_services_used, single.free_services_used), (1, 1))
        no_units = self._case(self._first(self._ac_card(qty=2)))
        no_units.with_user(self.helpdesk_user).service_unit_ids = [(5, 0, 0)]
        self.assertEqual(self._check(no_units), 'manual_review')
        self.assertIn('select the units to service', self._notes(no_units))

    def test_167_cancel_and_reschedule(self):
        """Cancel Job releases every service on its own card (nothing consumed); a rescheduled
        job consumes each service once, on the completed visit."""
        cards = self.env['warranty.card'].union(*[self._ac_card() for _ in range(3)])
        services = self._first(cards)
        case = self._case(services)
        job = self._job(case)
        task = self._confirm(job)
        self._work(task)
        job.with_user(self.helpdesk_user)._warranty_cancel_job('Customer postponed')
        self.assertEqual(set(services.mapped('state')), {'draft'})
        self.assertEqual(set(services.mapped('merge_status')), {'not_merged'})
        self.assertEqual(set(cards.mapped('free_services_used')), {0})
        action = case.with_user(self.helpdesk_user).action_prepare_service_job()
        job = self.env['warranty.service.job'].browse(action['res_id'])
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=10),
            'main_technician_id': self.tech.id})
        task = self._confirm(job)
        self._work(task)
        job.with_user(self.helpdesk_user)._warranty_visit_not_completed(
            task, 'access_issue', 'Gate closed', 'reschedule',
            {'planned_date': fields.Datetime.now() + timedelta(days=12),
             'main_technician': self.tech})
        second = job.visit_ids.sorted('warranty_visit_no')[-1]
        self.assertEqual(len(job.worksheet_ids.filtered(lambda s: s.task_id == second)), 3)
        self._work(second)
        second.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(set(services.mapped('state')), {'completed'})
        for card in cards:
            self.assertEqual(card.free_services_used, 1)

    def test_168_usage_based_and_single_card(self):
        """A usage-based card that is not the case's primary card needs its own case (manual
        review); a single-card case keeps the existing flow."""
        primary = self._ac_card()
        usage = self._ac_card()
        usage.sudo().write({'warranty_basis': 'usage', 'usage_unit': 'operating_hours',
                            'usage_limit': 5000})
        case = self._case(self._first(primary | usage))
        self.assertEqual(case.warranty_card_id, primary)
        self.assertEqual(self._check(case), 'manual_review')
        self.assertIn('usage-based warranty', self._notes(case))
        single = self._ac_card()
        job = self._job(self._case(self._first(single)))
        task = self._confirm(job)
        self.assertEqual((len(job.worksheet_ids), job.warranty_card_ids), (1, single))
        self._work(task)
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(single.free_services_used, 1)

    def test_190_free_services_tab_shows_each_services_units(self):
        """Merged job: per service, one aligned line per unit; the header stays empty."""
        single, double = self._ac_card(), self._ac_card(qty=2)
        lot_a, lot_b = (self.env['stock.lot'].create({'name': name, 'product_id': self.product.id})
                        for name in ('P190-A', 'P190-B'))
        double.unit_warranty_ids[0].serial_ids = lot_a
        double.unit_warranty_ids[1].serial_ids = lot_b
        services = self._first(single | double)
        case = self._case(services)
        job = self.env['warranty.service.job'].create({'warranty_case_id': case.id})
        shown = services.with_context(warranty_service_job_id=job.id)
        first, second = shown.filtered(lambda s: s.warranty_card_id == single), \
            shown.filtered(lambda s: s.warranty_card_id == double)
        self.assertEqual(first.warranty_job_unit_display, single.unit_warranty_ids.name)
        self.assertEqual(first.warranty_job_serial_display, '-', 'no serial: the line stays')
        units = double.unit_warranty_ids.sorted('name')
        self.assertEqual(second.warranty_job_unit_display.split('\n'), units.mapped('name'))
        self.assertEqual(second.warranty_job_serial_display.split('\n'), ['P190-A', 'P190-B'])
        self.assertEqual(second.warranty_job_product_display.split('\n'),
                         [self.product.display_name] * 2)
        # Units to Service removed from the case: not shown on its job.
        case.sudo().service_unit_ids -= units[1]
        self.env.invalidate_all()
        self.assertEqual(second.warranty_job_unit_display, units[0].name)
        self.assertEqual(second.warranty_job_serial_display, 'P190-A')
        # A cancelled unit is not serviced.
        case.sudo().service_unit_ids |= units[1]
        units[0].sudo()._warranty_system_write({'state': 'cancelled'})
        self.env.invalidate_all()
        self.assertEqual(second.warranty_job_unit_display, units[1].name)
        job.sudo().entitlement_ids = services
        self.assertEqual(job.merge_type, 'merged')
        self.assertEqual(job.warranty_card_ids, single | double)
        arch = etree.fromstring(self.env['warranty.service.job'].get_view(
            self.env.ref('warranty_management_fsm.warranty_service_job_view_form').id, 'form')['arch'])
        for name in ('product_id', 'serial_id', 'warranty_card_id', 'warranty_unit_id'):
            node = arch.xpath("//sheet/group//field[@name='%s']" % name)[0]
            self.assertEqual(node.get('invisible'), "merge_type == 'merged'", name)

    def test_191_case_hides_single_record_fields_for_several_units(self):
        """Several cards or units: the four fields are hidden, their values kept; a single unit
        keeps the layout."""
        single, other, double = self._ac_card(), self._ac_card(), self._ac_card(qty=2)
        one = self._case(self._first(single))
        self.assertFalse(one.warranty_multiple_units)
        kept = one.warranty_card_id
        merged = self._case(self._first(other | double))
        self.assertTrue(merged.warranty_multiple_units)
        self.assertTrue(merged.warranty_card_id, 'the stored card is kept')
        self.assertEqual(one.warranty_card_id, kept)
        units = merged.service_entitlement_ids.with_context(
            warranty_service_job_id=False).mapped('warranty_units_display')
        self.assertTrue(all(units), 'product / serial per unit stay in Linked Free Services')
        merged_two = self._case(self._first(self._ac_card(qty=2)))
        self.assertTrue(merged_two.warranty_multiple_units, 'one card, two units')
        merged_two.sudo().service_unit_ids = merged_two.service_unit_ids[:1]
        self.assertFalse(merged_two.warranty_multiple_units, 'one unit selected')
        arch = etree.fromstring(self.env['warranty.case'].get_view(self.env.ref(
            'warranty_management_helpdesk.warranty_case_view_form').id, 'form')['arch'])
        for name in ('product_id', 'serial_id', 'warranty_card_id', 'warranty_unit_id'):
            node = arch.xpath("//sheet/group//field[@name='%s']" % name)[0]
            self.assertEqual(node.get('invisible'), 'warranty_multiple_units', name)
        for name in ('service_card_ids', 'service_unit_ids'):
            self.assertNotEqual(arch.xpath("//sheet/group//field[@name='%s']" % name)[0].get(
                'invisible'), 'warranty_multiple_units', name)
