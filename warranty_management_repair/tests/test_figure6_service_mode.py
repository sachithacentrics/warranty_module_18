from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from .test_warranty_replacement import ReplacementCommon


class Figure6Common(ReplacementCommon):
    """An Approved, Eligible case of a delivered serial; team with Returns / Repairs and an
    inspection quotation On Sales Order Confirmation; Warranty Repair Intake location."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coordinator.email = 'figure6@example.com'
        cls.coordinator.groups_id |= cls.env.ref('sales_team.group_sale_salesman_all_leads')
        cls.helpdesk_only = cls._user('f6_helpdesk', 'helpdesk.group_helpdesk_user')
        cls.stock_only = cls._user('f6_stock', 'stock.group_stock_user')
        cls.intake_location = cls.env['stock.location'].create({
            'name': 'F6 Intake', 'usage': 'internal', 'company_id': cls.company.id,
            'location_id': cls.env.ref('stock.stock_location_locations').id})
        cls.company.warranty_repair_intake_location_id = cls.intake_location
        cls.inspection_product = cls.env['product.product'].create({
            'name': 'F6 Inspection Fee', 'type': 'service', 'list_price': 850.0,
            'invoice_policy': 'order'})
        cls.team.write({'use_product_returns': True, 'use_product_repairs': True,
                        'warranty_inspection_required': True,
                        'warranty_inspection_product_id': cls.inspection_product.id,
                        'warranty_inspection_amount': 850.0,
                        'warranty_job_trigger': 'sale_confirmation'})
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)])
        cls.warehouse.int_type_id.active = True

    def setUp(self):
        super().setUp()
        self.card = self._card(self.single)
        self.serial = self.card.unit_warranty_ids.serial_ids
        self.case = self._eligible_case(self.serial)
        self.assertEqual(self.case.eligibility_result, 'eligible', self.case.eligibility_reason)
        self._approved_state(self.case)
        self.ticket = self.case.helpdesk_ticket_id

    # ------------------------------------------------------------------ helpers
    def _mode(self, mode, user=None):
        self.case.with_user(user or self.coordinator).write({'warranty_service_mode': mode})

    def _intake(self):
        form = Form(self.env['stock.return.picking'].with_user(self.coordinator).with_context(
            default_ticket_id=self.ticket.id, default_company_id=self.company.id))
        with form.product_return_moves.edit(0) as line:
            line.quantity = 1
        picking = self.env['stock.picking'].browse(form.save().action_create_returns()['res_id'])
        picking.action_assign()
        picking.move_line_ids.lot_id = self.serial
        picking.move_ids.picked = True
        self.assertIs(picking.with_context(skip_backorder=True).button_validate(), True)
        return picking

    def _repair(self):
        context = self.ticket.with_user(self.coordinator).action_repair_order_form()['context']
        return Form(self.env['repair.order'].with_user(self.coordinator).with_context(
            context)).save()

    def _quotation(self):
        self.case.with_user(self.coordinator).action_prepare_service_job()
        order = self.case._warranty_inspection_orders()
        self.assertEqual(len(order), 1)
        return order

    def _jobs(self):
        return self.env['warranty.service.job'].search([('warranty_case_id', '=', self.case.id)])

    def _logs(self, text):
        return [body for body in self.case.message_ids.mapped('body') if text in body]

    def _return_and_complete(self, repair):
        action = repair.with_user(self.coordinator).action_warranty_return_machine()
        form = Form(self.env[action['res_model']].with_user(self.coordinator).with_context(
            action['context']))
        with form.product_return_moves.edit(0) as line:
            line.quantity = 1
        back = self.env['stock.picking'].browse(form.save().action_create_returns()['res_id'])
        self._validate(back)
        self.assertTrue(repair.warranty_equipment_returned)
        self.assertEqual(repair.warranty_intake_state, 'returned')
        repair.with_user(self.coordinator).action_warranty_complete_case()
        self.assertEqual(self.case.state, 'completed')


@tagged('post_install', '-at_install', 'warranty_repair', 'warranty_figure6_mode')
class TestFigure6ServiceMode(Figure6Common):
    """S1 (SRS 12 scenario 18): the Service Mode decides whether the triggers create a Field
    Service job; C1 (F1); C5 (Intake Status)."""

    def test_01_workshop_trigger_before_intake(self):
        """Workshop Repair: the quotation is confirmed before the intake, still no job (the gap
        of 18.0.1.6.3 without the mode); the Repair Order may start, the case completes."""
        self._mode('workshop')
        order = self._quotation()
        order.action_confirm()
        self.assertFalse(self._jobs())
        logs = self._logs('no Field Service job is created')
        self.assertEqual(len(logs), 1)
        self.assertIn('Workshop Repair', logs[0])
        self.case._warranty_check_chargeable_trigger('repeat')
        self.assertEqual(len(self._logs('no Field Service job is created')), 1, 'Logged once.')
        self._intake()
        repair = self._repair()
        repair.with_user(self.coordinator).action_validate()
        repair.with_user(self.coordinator).action_repair_start()
        repair.warranty_repair_result = 'repaired'
        repair.with_user(self.coordinator).action_repair_done()
        self._return_and_complete(repair)
        self.assertFalse(self._jobs())

    def test_02_vendor_payment_trigger(self):
        self._mode('vendor')
        self.case.sudo().warranty_inspection_trigger = 'payment'
        order = self._quotation()
        order.action_confirm()
        self.assertFalse(self._logs('no Field Service job is created'))
        invoice = order._create_invoices()
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        self.assertFalse(self._jobs())
        self.assertIn('Vendor Repair', self._logs('no Field Service job is created')[0])

    def test_03_onsite_creates_the_job_even_with_a_workshop_repair(self):
        """On-site chosen explicitly: the job is created (Figure 4 / 5), the workshop Repair
        Order does not hold it back."""
        self._intake()
        repair = self._repair()
        repair.with_user(self.coordinator).action_validate()
        self._mode('onsite')
        self._quotation().action_confirm()
        self.assertEqual(len(self._jobs()), 1)
        self.assertFalse(self._logs('no on-site service job'))

    def test_04_prepare_service_job(self):
        self._mode('workshop')
        # Inspection required: the quotation is still prepared (Figure 4 "Yes").
        order = self._quotation()
        order.action_confirm()
        with self.assertRaisesRegex(UserError, 'Service Mode Workshop Repair'):
            self.case.with_user(self.coordinator).action_prepare_service_job()
        self.assertFalse(self._jobs())
        # On-site again: Prepare Service Job creates the job on request.
        self._mode('onsite')
        self.case.with_user(self.coordinator).action_prepare_service_job()
        self.assertEqual(len(self._jobs()), 1)

    def test_05_prepare_without_inspection_and_unset_mode(self):
        self.case.sudo().warranty_inspection_required = False
        self._mode('vendor')
        with self.assertRaisesRegex(UserError, 'Service Mode Vendor Repair'):
            self.case.with_user(self.coordinator).action_prepare_service_job()
        # Unset: the behaviour before the field.
        self._mode(False)
        self.case.with_user(self.coordinator).action_prepare_service_job()
        self.assertEqual(len(self._jobs()), 1)

    def test_06_who_and_when(self):
        for user in (self.stock_only, self.outsider):
            with self.subTest(user=user.login), self.assertRaises(AccessError):
                self._mode('workshop', user=user)
        self.assertFalse(self.case.warranty_service_mode)
        self.case.sudo().warranty_inspection_required = False
        self.case.with_user(self.coordinator).action_prepare_service_job()
        job = self._jobs()
        # An open job keeps control.
        with self.assertRaisesRegex(UserError, 'keeps control'):
            self._mode('workshop')
        job.action_cancel()
        self._mode('workshop')
        self.assertEqual(self.case.warranty_service_mode, 'workshop')
        self.case.sudo().write({'state': 'rejected'})
        with self.assertRaisesRegex(UserError, 'is finished|cannot be changed'):
            self._mode('vendor')

    def test_07_job_led_sets_workshop(self):
        """SM3: a Repair Order created for an open job, or the job's Workshop Repair hold, sets
        Workshop Repair; Workshop <-> Vendor stays possible, On-site does not."""
        self.case.sudo().warranty_inspection_required = False
        self._mode('onsite')
        self.case.with_user(self.coordinator).action_prepare_service_job()
        job = self._jobs()
        self._intake()
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        Form(self.env['repair.order'].with_user(self.coordinator).with_context(
            action['context'])).save()
        self.assertEqual(self.case.warranty_service_mode, 'workshop')
        self.assertTrue(self._logs('Service Mode set to Workshop Repair'))
        self._mode('vendor')
        with self.assertRaisesRegex(UserError, 'keeps control'):
            self._mode('onsite')
        self.assertEqual(self._jobs(), job, 'No second job.')

    def test_08_hold_sets_workshop(self):
        self.case.sudo().warranty_inspection_required = False
        self.case.with_user(self.coordinator).action_prepare_service_job()
        job = self._jobs()
        job.sudo().state = 'in_progress'
        job.with_user(self.coordinator)._warranty_set_hold('workshop', 'Unit taken in')
        self.assertEqual((job.state, self.case.warranty_service_mode), ('workshop', 'workshop'))

    def test_09_chargeable_repair_mode(self):
        """Decision 3 with the mode: Workshop / Vendor need no job even without a Repair Order;
        On-site keeps the job even with one. Unset: unchanged (a Repair Order is needed)."""
        self.case.sudo().write({'state': 'chargeable', 'chargeable_type': 'repair'})
        self.assertFalse(self.case._warranty_workshop_repairs_trigger())
        self._mode('workshop')
        self.assertTrue(self.case._warranty_workshop_repairs_trigger())
        with self.assertRaisesRegex(UserError, 'Service Mode Workshop Repair'):
            self.case._warranty_prepare_chargeable_job()
        self._intake()
        self._repair()
        self._mode('onsite')
        self.assertFalse(self.case._warranty_workshop_repairs_trigger())
        self._mode(False)
        self.assertTrue(self.case._warranty_workshop_repairs_trigger())

    def test_10_f1_job_repair_order_with_two_cases(self):
        """C1: the ticket has two active cases; the job's Create Repair Order proposes its own
        case's product and serial."""
        other_serial = self._card(self.single).unit_warranty_ids.serial_ids
        other = self.env['warranty.case'].create({
            'helpdesk_ticket_id': self.ticket.id, 'partner_id': self.partner.id,
            'company_id': self.company.id, 'case_type': 'warranty_complaint',
            'serial_id': other_serial.id, 'requested_item_ids': [(6, 0, self.item.ids)]})
        self.assertEqual(len(self.ticket._warranty_active_cases()), 2)
        # Ticket Repair button: no case chosen for the user, as before.
        context = self.ticket.with_user(self.coordinator).action_repair_order_form()['context']
        self.assertFalse(context['default_warranty_case_id'])
        self.case.sudo().warranty_inspection_required = False
        self.case.with_user(self.coordinator).action_prepare_service_job()
        job = self._jobs()
        context = job.with_user(self.coordinator).action_warranty_open_repair()['context']
        self.assertEqual((context['default_warranty_case_id'], context['default_product_id'],
                          context['default_lot_id']),
                         (self.case.id, self.single.id, self.serial.id))
        self.assertNotIn('warranty_repair_case_id', context)
        self.assertNotEqual(other.serial_id, self.serial)

    def test_11_intake_status(self):
        """C5: Received only when the linked intake received this product and serial."""
        repair = self._repair()
        self.assertEqual(repair.warranty_intake_state, 'awaiting_receipt')
        intake = self._intake()
        repair.picking_id = intake
        self.assertEqual(repair.warranty_intake_state, 'received')
        # A validated transfer that is not this machine's intake: not received.
        repair.sudo().picking_id = self.card.sale_order_id.picking_ids[:1]
        self.assertEqual(repair.warranty_intake_state, 'awaiting_receipt')
        repair.sudo().picking_id = intake
        repair.sudo().lot_id = self._lot(self.single, 6)
        self.assertEqual(repair.warranty_intake_state, 'awaiting_receipt')
