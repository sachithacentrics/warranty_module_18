from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_repair', 'warranty_workshop_trigger')
class TestWorkshopInspectionTrigger(ReplacementCommon):
    """Figure 6 Phase 2: the Inspection Trigger of an Approved case whose machine is already in
    the workshop (Repair Order with a validated intake of the case serial) authorizes Start Repair
    without an on-site service job; every other case keeps the existing behaviour."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coordinator.email = 'workshop.trigger@example.com'
        # The inspection quotation of Prepare Service Job needs Sales rights (existing rule).
        cls.coordinator.groups_id |= cls.env.ref('sales_team.group_sale_salesman_all_leads')
        intake = cls.env['stock.location'].create({
            'name': 'WT Intake', 'usage': 'internal', 'company_id': cls.company.id,
            'location_id': cls.env.ref('stock.stock_location_locations').id})
        cls.company.warranty_repair_intake_location_id = intake
        cls.inspection_product = cls.env['product.product'].create({
            'name': 'WT Inspection Fee', 'type': 'service', 'list_price': 850.0,
            'invoice_policy': 'order'})
        cls.team.write({'use_product_returns': True, 'use_product_repairs': True,
                        'warranty_inspection_required': True,
                        'warranty_inspection_product_id': cls.inspection_product.id,
                        'warranty_inspection_amount': 850.0,
                        'warranty_job_trigger': 'sale_confirmation'})

    def setUp(self):
        super().setUp()
        self.card = self._card(self.single)
        self.serial = self.card.unit_warranty_ids.serial_ids
        self.case = self._eligible_case(self.serial)
        self.assertEqual(self.case.eligibility_result, 'eligible', self.case.eligibility_reason)
        self._approved_state(self.case)
        self.assertTrue(self.case.warranty_inspection_required)
        self.ticket = self.case.helpdesk_ticket_id

    # ------------------------------------------------------------------ helpers
    def _intake(self):
        """The ticket's Return button: Warranty Repair Intake of the machine, validated."""
        form = Form(self.env['stock.return.picking'].with_user(self.coordinator).with_context(
            default_ticket_id=self.ticket.id, default_company_id=self.company.id))
        with form.product_return_moves.edit(0) as line:
            line.quantity = 1
        wizard = form.save()
        picking = self.env['stock.picking'].browse(wizard.action_create_returns()['res_id'])
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
        """Prepare Service Job of an inspection case: the inspection quotation, no job."""
        self.case.with_user(self.coordinator).action_prepare_service_job()
        order =self.case._warranty_inspection_orders()
        self.assertEqual(len(order), 1)
        return order

    def _jobs(self):
        return self.env['warranty.service.job'].search([('warranty_case_id', '=', self.case.id)])

    def _suppressed_logs(self):
        return [body for body in self.case.message_ids.mapped('body')
                if 'no on-site service job' in body]

    def _finish(self, repair):
        repair.with_user(self.coordinator).action_repair_start()
        repair.warranty_repair_result = 'repaired'
        repair.with_user(self.coordinator).action_repair_done()
        action = repair.with_user(self.coordinator).action_warranty_return_machine()
        form = Form(self.env[action['res_model']].with_user(self.coordinator).with_context(
            action['context']))
        with form.product_return_moves.edit(0) as line:
            line.quantity = 1
        back = self.env['stock.picking'].browse(form.save().action_create_returns()['res_id'])
        self._validate(back)
        self.assertTrue(repair.warranty_equipment_returned)

    def _pay(self, order):
        invoice = order._create_invoices()
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()

    # ------------------------------------------------------------------ tests
    def test_01_helpdesk_led_sale_confirmation(self):
        """Scenarios 1, 2 and 6: the gate holds Start Repair until the trigger; the trigger
        creates no job, logs once, and the existing completion completes the case."""
        self._intake()
        repair = self._repair()
        repair.with_user(self.coordinator).action_validate()
        with self.assertRaisesRegex(UserError, 'requires an inspection quotation'):
            repair.with_user(self.coordinator).action_repair_start()
        order = self._quotation()
        with self.assertRaisesRegex(UserError, 'requires an inspection quotation'):
            repair.with_user(self.coordinator).action_repair_start()
        order.action_confirm()
        self.assertFalse(self._jobs(), 'No on-site service job for the workshop repair.')
        logs = self._suppressed_logs()
        self.assertEqual(len(logs), 1)
        for text in (order.name, repair.name, 'On Sales Order Confirmation'):
            self.assertIn(text, logs[0])
        self.assertIn('Repair Order %s: start the repair' % repair.name,
                      repair.activity_ids.mapped('summary'))
        self.case._warranty_check_chargeable_trigger('repeat')
        self.assertEqual(len(self._suppressed_logs()), 1, 'Logged once.')
        self.assertFalse(self._jobs())
        self._finish(repair)
        self.assertEqual(self.case.state, 'approved')
        repair.with_user(self.coordinator).action_warranty_complete_case()
        self.assertEqual(self.case.state, 'completed')

    def test_02_helpdesk_led_payment_trigger(self):
        """Scenario 3: On Payment, nothing at confirmation; at full payment no job either."""
        self.case.sudo().warranty_inspection_trigger = 'payment'
        self._intake()
        repair = self._repair()
        order = self._quotation()
        order.action_confirm()
        self.assertFalse(self._suppressed_logs())
        repair.with_user(self.coordinator).action_validate()
        with self.assertRaisesRegex(UserError, 'requires an inspection quotation'):
            repair.with_user(self.coordinator).action_repair_start()
        self._pay(order)
        self.assertFalse(self._jobs())
        self.assertEqual(len(self._suppressed_logs()), 1)
        self.assertIn('On Payment', self._suppressed_logs()[0])
        repair.with_user(self.coordinator).action_repair_start()
        self.assertEqual(repair.state, 'under_repair')

    def test_03_no_repair_order_on_site_flow(self):
        """Scenario 9 (Figure 4): no Repair Order, the trigger creates the service job."""
        order = self._quotation()
        order.action_confirm()
        job = self._jobs()
        self.assertEqual((len(job), job.state, job.job_type), (1, 'draft', 'warranty'))
        self.assertFalse(self._suppressed_logs())

    def test_04_job_led_workshop_repair(self):
        """Scenario 4: the job comes first (no Repair Order at the trigger); the workshop runs
        under it, no second job, and the job keeps the completion."""
        self._quotation().action_confirm()
        job = self._jobs()
        self.assertEqual(len(job), 1)
        self.assertTrue(job.with_user(self.coordinator).action_warranty_workshop_intake())
        self._intake()
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        repair = Form(self.env['repair.order'].with_user(self.coordinator).with_context(
            action['context'])).save()
        repair.with_user(self.coordinator).action_validate()
        self.case._warranty_check_chargeable_trigger('repeat')
        self.assertEqual(self._jobs(), job)
        self.assertFalse(self._suppressed_logs())
        self._finish(repair)
        with self.assertRaisesRegex(UserError, 'Service job %s is open' % job.name):
            repair.with_user(self.coordinator).action_warranty_complete_case()

    def test_05_cancelled_or_unsupported_repair_order(self):
        """Scenario 5: a cancelled Repair Order, or one without a validated intake of the case
        serial, does not suppress the job."""
        cancelled = self._repair()
        cancelled.with_user(self.coordinator).action_repair_cancel()
        self._repair()  # no intake: the Confirm guard fails
        self._quotation().action_confirm()
        self.assertEqual(len(self._jobs()), 1)
        self.assertFalse(self._suppressed_logs())

    def test_06_other_serial_repair_order(self):
        """Scenario 5: the received machine is not the case serial: the job is created."""
        self._intake()
        repair = self._repair()
        other = self._lot(self.single, 6)
        repair.sudo().lot_id = other
        self.assertTrue(repair._warranty_repair_confirm_problems())
        self._quotation().action_confirm()
        self.assertEqual(len(self._jobs()), 1)

    def test_07_manual_prepare_and_draft_job_blocks_completion(self):
        """Scenarios 7 and 8: Prepare Service Job still creates a job on request; an open Draft
        job blocks Complete Warranty Case until it is cancelled by the user; nothing consumed."""
        self._intake()
        repair = self._repair()
        repair.with_user(self.coordinator).action_validate()
        self._quotation().action_confirm()
        self.assertFalse(self._jobs())
        self.case.with_user(self.coordinator).action_prepare_service_job()
        job =self._jobs()
        self.assertEqual((len(job), job.state), (1, 'draft'))
        self._finish(repair)
        with self.assertRaisesRegex(UserError, 'Service job %s is open' % job.name):
            repair.with_user(self.coordinator).action_warranty_complete_case()
        self.assertEqual((self.case.state, job.state), ('approved', 'draft'), 'Nothing cancelled.')
        job.with_user(self.coordinator).action_cancel()
        repair.with_user(self.coordinator).action_warranty_complete_case()
        self.assertEqual(self.case.state, 'completed')
        self.assertFalse(self.case.service_entitlement_ids.filtered(
            lambda service: service.state == 'completed'))

    def test_08_inspection_not_required_unchanged(self):
        """Scenario 9: a case without inspection is not touched by the trigger."""
        self.case.sudo().warranty_inspection_required = False
        self._intake()
        repair = self._repair()
        self.assertFalse(self.case._warranty_workshop_inspection_repairs())
        repair.with_user(self.coordinator).action_validate()
        repair.with_user(self.coordinator).action_repair_start()
        self.assertEqual(repair.state, 'under_repair')
