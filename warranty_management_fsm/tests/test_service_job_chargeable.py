from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobChargeable(ServiceJobCommon):
    """Phase 4.10 - chargeable jobs and Job Trigger (approved C1-C12)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sales_user = cls._user('job_c_sales', 'helpdesk.group_helpdesk_user')
        cls.sales_user.groups_id |= cls.env.ref('sales_team.group_sale_salesman_all_leads')
        cls.tech = cls._user('job_ch_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.chargeable@example.com'
        cls.env['hr.employee'].create({'name': 'Chargeable Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        Product = cls.env['product.product']
        cls.inspection_product = Product.create({'name': 'Inspection Fee', 'type': 'service',
                                                 'list_price': 850.0, 'invoice_policy': 'order'})
        cls.repair_product = Product.create({'name': 'Compressor Repair', 'type': 'service',
                                             'list_price': 12000.0, 'invoice_policy': 'order'})
        cls.gas_product = Product.create({'name': 'Gas Refill Service', 'type': 'service',
                                          'list_price': 2500.0, 'invoice_policy': 'order'})
        cls.item_gas.product_id = cls.gas_product
        cls.team.write({'warranty_inspection_required': True,
                        'warranty_inspection_product_id': cls.inspection_product.id,
                        'warranty_inspection_amount': 850.0,
                        'warranty_job_trigger': 'sale_confirmation'})
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False
        cls.company.write({'warranty_signoff_required': False,
                           'warranty_worksheet_checklist_required': False})

    # ------------------------------------------------------------------ helpers
    def _ticket_for_product(self):
        return self._ticket(warranty_product_id=self.product.id)

    def _inspection_case(self, services=None):
        vals = {'case_type': 'chargeable_inspection'}
        if services:
            vals['service_entitlement_ids'] = [(6, 0, services.ids)]
        case = self._create_case(self._ticket_for_product(), user=self.creator, **vals)
        action = case.with_user(self.sales_user).action_open_chargeable_wizard()
        wizard = self.env['warranty.case.chargeable.wizard'].with_user(self.sales_user) \
            .with_context(action['context']).create({})
        order = self.env['sale.order'].browse(wizard.action_convert()['res_id'])
        self.assertEqual((case.state, case.chargeable_type), ('chargeable', 'inspection'))
        return case, order

    def _plan_confirm(self, job):
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual(job.state, 'confirmed')
        return job.visit_ids

    def _work(self, task):
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Inspection'}).save_timesheet()

    def _inspect(self, task, repair_required, details='Replace compressor'):
        action = task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(action['res_model'], 'warranty.inspection.result.wizard')
        with Form(self.env[action['res_model']].with_user(self.tech).with_context(
                action['context'])) as form:
            form.diagnosis = 'Compressor seized'
            form.repair_required = repair_required
            if repair_required == 'yes':
                form.repair_details = details
        form.record.action_apply()

    def _pay(self, order, method='delivered', amount=None):
        """Invoice the order (regular, or a percentage down payment) and register its payment."""
        if method == 'percentage':
            wizard = self.env['sale.advance.payment.inv'].with_context(
                active_model='sale.order', active_ids=order.ids).create(
                {'advance_payment_method': 'percentage', 'amount': amount})
            invoice = wizard._create_invoices(order)
        else:
            invoice = order._create_invoices()
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        return invoice

    def _jobs(self, case):
        return self.env['warranty.service.job'].search([('warranty_case_id', '=', case.id)])

    # ------------------------------------------------------------------ tests
    def test_151_sale_confirmation_trigger(self):
        """On Sales Order Confirmation: the quotation gets its purpose and a send To-Do (closed
        when sent); no job before confirmation; at confirmation one Draft Chargeable Inspection
        job without free services (C6); no duplicate from a second check or Prepare."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        case, order = self._inspection_case(services=s1)
        self.assertEqual(order.warranty_chargeable_purpose, 'inspection')
        todo = case.activity_ids.filtered(lambda a: order.name in (a.summary or ''))
        self.assertEqual(len(todo), 1)
        self.assertFalse(self._jobs(case))
        with self.assertRaisesRegex(UserError, 'Job Trigger of .* is not met'):
            case.with_user(self.helpdesk_user).action_prepare_service_job()
        order.with_user(self.sales_user).action_quotation_sent()
        self.assertFalse(todo.exists())
        state_before = s1.state
        order.with_user(self.sales_user).action_confirm()
        job = self._jobs(case)
        self.assertEqual((len(job), job.state, job.job_type, job.chargeable_order_id),
                         (1, 'draft', 'chargeable_inspection', order))
        self.assertFalse(job.entitlement_ids)
        self.assertFalse(order.invoice_ids, 'no invoice needed')
        case._warranty_check_chargeable_trigger('repeat')
        with self.assertRaisesRegex(UserError, 'already has the open service job'):
            case.with_user(self.helpdesk_user).action_prepare_service_job()
        self.assertEqual(self._jobs(case), job)
        task = self._plan_confirm(job)
        self.assertEqual((case.state, task.warranty_entitlement_ids), ('job_created', s1.browse()))
        self.assertEqual(s1.state, state_before)

    def test_152_payment_trigger_full_payment_only(self):
        """On Payment: no job at confirmation, nor after a paid down payment with an unpaid
        remainder; one job once the order is fully invoiced and paid."""
        self.team.warranty_job_trigger = 'payment'
        case, order = self._inspection_case()
        order.with_user(self.sales_user).action_confirm()
        self.assertFalse(self._jobs(case))
        self._pay(order, 'percentage', 50)
        self.assertEqual(order.invoice_status, 'to invoice')
        self.assertFalse(self._jobs(case))
        with self.assertRaisesRegex(UserError, 'not met'):
            case.with_user(self.helpdesk_user).action_prepare_service_job()
        self._pay(order)
        self.assertEqual(order.invoice_status, 'invoiced')
        job = self._jobs(case)
        self.assertEqual((len(job), job.job_type), (1, 'chargeable_inspection'))

    def test_153_inspection_repair_required_then_repair_job(self):
        """Inspection -> repair required: diagnosis kept, inspection job and visit completed,
        case back to Chargeable (Repair) with a draft unpriced repair quotation (not confirmed);
        the repair job comes at confirmation of the priced quotation; repair completion
        completes the case; both jobs stay on the case."""
        case, order = self._inspection_case()
        order.with_user(self.sales_user).action_confirm()
        inspection = self._jobs(case)
        task = self._plan_confirm(inspection)
        self._work(task)
        results = inspection.with_user(self.helpdesk_user)._warranty_batch_complete()
        self.assertIn('inspection result', results[0][2][0])
        with self.assertRaisesRegex(UserError, 'repair details are required'):
            inspection.with_user(self.tech)._warranty_complete_visit(task, inspection={
                'diagnosis': 'Seized', 'repair_required': 'yes'})
        self._inspect(task, 'yes')
        self.assertEqual((inspection.state, inspection.inspection_diagnosis,
                          inspection.inspection_repair_required,
                          inspection.inspection_repair_details),
                         ('completed', 'Compressor seized', 'yes', 'Replace compressor'))
        self.assertEqual((task.state, task.fsm_done, task.warranty_visit_outcome),
                         ('1_done', True, 'completed'))
        self.assertEqual((case.state, case.chargeable_type, case.warranty_chargeable_outcome),
                         ('chargeable', 'repair', False))
        repair_order = inspection.repair_quotation_id
        self.assertEqual((repair_order.state, repair_order.warranty_chargeable_purpose,
                          repair_order.amount_total), ('draft', 'repair', 0.0))
        self.assertIn('Compressor seized', repair_order.order_line.name)
        self.assertEqual(len(self._jobs(case)), 1, 'no repair job before the trigger')
        repair_order.with_user(self.sales_user).write({'order_line': [(0, 0, {
            'product_id': self.repair_product.id, 'product_uom_qty': 1})]})
        repair_order.with_user(self.sales_user).action_confirm()
        repair = self._jobs(case) - inspection
        self.assertEqual((len(repair), repair.job_type, repair.chargeable_order_id),
                         (1, 'chargeable_repair', repair_order))
        repair_task = self._plan_confirm(repair)
        self._work(repair_task)
        repair_task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual((repair.state, case.state, case.warranty_chargeable_outcome),
                         ('completed', 'completed', 'repair_completed'))
        self.assertEqual(case.service_job_ids, inspection | repair)
        self.assertEqual(task.warranty_visit_outcome, 'completed', 'inspection visit unchanged')

    def test_154_inspection_only(self):
        """No repair needed: inspection job completed, case Completed (inspection only, not
        Closed), no repair quotation."""
        case, order = self._inspection_case()
        order.with_user(self.sales_user).action_confirm()
        job = self._jobs(case)
        task = self._plan_confirm(job)
        self._work(task)
        self._inspect(task, 'no')
        self.assertEqual((job.state, job.inspection_repair_required, job.repair_quotation_id),
                         ('completed', 'no', self.env['sale.order']))
        self.assertEqual((case.state, case.warranty_chargeable_outcome),
                         ('completed', 'inspection_only'))
        self.assertIn('Closed after the accounting steps', ' '.join(case.message_ids.mapped('body')))

    def test_155_customer_declines_repair(self):
        """The customer rejects the repair: inspection-only closure, inspection kept, open
        repair quotations cancelled; refused for technicians and after a confirmed repair."""
        case, order = self._inspection_case()
        order.with_user(self.sales_user).action_confirm()
        inspection = self._jobs(case)
        task = self._plan_confirm(inspection)
        self._work(task)
        self._inspect(task, 'yes')
        repair_order = inspection.repair_quotation_id
        with self.assertRaises(AccessError):
            case.with_user(self.tech).action_open_decline_repair_wizard()
        action = case.with_user(self.helpdesk_user).action_open_decline_repair_wizard()
        with Form(self.env[action['res_model']].with_user(self.helpdesk_user).with_context(
                action['context'])) as form:
            form.reason = 'Too expensive'
        form.record.action_apply()
        self.assertEqual((case.state, case.warranty_chargeable_outcome, repair_order.state),
                         ('completed', 'repair_declined', 'cancel'))
        self.assertEqual((inspection.state, inspection.inspection_diagnosis, task.state),
                         ('completed', 'Compressor seized', '1_done'))
        with self.assertRaisesRegex(UserError, 'declined repair is recorded'):
            case.with_user(self.helpdesk_user)._warranty_decline_repair('again')

    def test_156_no_bypass_and_trigger_revalidation(self):
        """Chargeable fields are set by the workflow only; confirmation revalidates the
        trigger (cancelled order -> blocked)."""
        case, order = self._inspection_case()
        Job = self.env['warranty.service.job'].with_user(self.helpdesk_user)
        with self.assertRaisesRegex(UserError, 'created by the Job Trigger'):
            Job.create({'warranty_case_id': case.id, 'job_type': 'chargeable_inspection'})
        with self.assertRaisesRegex(UserError, 'chargeable purpose is set'):
            order.with_user(self.sales_user).warranty_chargeable_purpose = 'repair'
        with self.assertRaisesRegex(UserError, 'chargeable outcome is set'):
            case.with_user(self.helpdesk_user).warranty_chargeable_outcome = 'inspection_only'
        order.with_user(self.sales_user).action_confirm()
        job = self._jobs(case)
        for vals in ({'job_type': 'warranty'}, {'inspection_diagnosis': 'x'},
                     {'chargeable_order_id': False}):
            with self.assertRaisesRegex(UserError, 'set by the chargeable workflow'):
                job.with_user(self.helpdesk_user).write(vals)
        order.sudo()._action_cancel()
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        with self.assertRaisesRegex(UserError, 'no longer met'):
            job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual((job.state, case.state), ('planned', 'chargeable'))

    def test_157_cancel_chargeable_job_back_to_chargeable(self):
        """Cancel Job (4.8) on a chargeable job: case back to Chargeable (not Approved); Prepare
        Service Job then gives a new job for the still confirmed order (the cancelled one does
        not block, no second active job)."""
        case, order = self._inspection_case()
        order.with_user(self.sales_user).action_confirm()
        job = self._jobs(case)
        self._plan_confirm(job)
        job.with_user(self.helpdesk_user)._warranty_cancel_job('Customer asked to postpone')
        self.assertEqual((job.state, case.state), ('cancelled', 'chargeable'))
        action = case.with_user(self.helpdesk_user).action_prepare_service_job()
        new = self.env['warranty.service.job'].browse(action['res_id'])
        self.assertEqual((new.state, new.chargeable_order_id, len(self._jobs(case))),
                         ('draft', order, 2))

    def test_158_partial_case_approved_items_on_warranty_job(self):
        """C9: a Partial case keeps the Part 3 flow (no extra trigger): the warranty job shows
        the customer-approved excluded items."""
        case = self._create_case(self._ticket_for_product(), user=self.creator,
                                 requested_items=self.item_service | self.item_gas)
        self.assertEqual(self._result(case), 'partial')
        action = case.with_user(self.sales_user).action_create_excluded_quotation()
        quotation = self.env['sale.order'].browse(action['res_id'])
        self.assertFalse(quotation.warranty_chargeable_purpose)
        quotation.with_user(self.sales_user).action_confirm()
        self.assertEqual(self._result(case), 'eligible')
        case.with_user(self.approver_a).action_approve_case()
        # This test is about excluded items. An inspection quotation would need Sales rights (by
        # design: Part 3 decisions), which this Helpdesk user does not have.
        case.sudo().warranty_inspection_required = False
        job = self._prepare(case)
        self.assertEqual(job.job_type, 'warranty')
        self.assertIn('Case Gas Refill', job.with_user(self.tech).approved_excluded_items)
