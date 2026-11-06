from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from odoo.addons.warranty_management_fsm.tests.common import ServiceJobCommon


class InspectionFlowCommon(ServiceJobCommon):
    """A chargeable inspection through to Repair Required, as in the Part 4 tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sales_user = cls._user('fee_sales', 'helpdesk.group_helpdesk_user')
        cls.sales_user.groups_id |= cls.env.ref('sales_team.group_sale_salesman_all_leads')
        cls.tech = cls._user('fee_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'fee.tech@example.com'
        cls.env['hr.employee'].create({'name': 'Fee Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.billing = cls._user('fee_billing', 'account.group_account_invoice')
        cls.approver = cls._user('fee_approver', 'helpdesk.group_helpdesk_user')
        cls.approver.groups_id |= cls.env.ref('sales_team.group_sale_salesman_all_leads')
        cls.approver_no_sales = cls._user('fee_approver2', 'helpdesk.group_helpdesk_user')
        cls.outsider = cls._user('fee_outsider', 'helpdesk.group_helpdesk_user')
        cls.company.warranty_cost_approver_ids = cls.approver
        Product = cls.env['product.product']
        cls.tax = cls.env['account.tax'].create({'name': 'Fee Tax 15', 'amount': 15.0,
                                                 'amount_type': 'percent',
                                                 'company_id': cls.company.id})
        cls.fee_product = Product.create({'name': 'Inspection Fee', 'type': 'service',
                                          'list_price': 850.0, 'invoice_policy': 'order',
                                          'taxes_id': [(6, 0, cls.tax.ids)]})
        cls.repair_product = Product.create({'name': 'Compressor Repair', 'type': 'service',
                                             'list_price': 5000.0, 'invoice_policy': 'order',
                                             'taxes_id': [(6, 0, cls.tax.ids)]})
        cls.deduction = Product.create({'name': 'Inspection Deduction', 'type': 'service',
                                        'list_price': 0.0, 'invoice_policy': 'order',
                                        'taxes_id': [(5, 0, 0)]})
        cls.team.write({'warranty_inspection_required': True,
                        'warranty_inspection_product_id': cls.fee_product.id,
                        'warranty_inspection_amount': 1500.0,
                        'warranty_inspection_deduction_product_id': cls.deduction.id,
                        'warranty_job_trigger': 'sale_confirmation'})
        cls.company._warranty_fsm_project().sudo().worksheet_template_id = False
        cls.company.write({'warranty_signoff_required': False,
                           'warranty_worksheet_checklist_required': False})

    # ------------------------------------------------------------------ helpers
    def _start_visit(self, job):
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        task = job.visit_ids
        task.with_user(self.tech).action_timer_start()
        action = task.with_user(self.tech).action_timer_stop()
        self.env[action['res_model']].with_user(self.tech).with_context(action['context']).create(
            {'time_spent': 1.0, 'description': 'Work'}).save_timesheet()
        return task

    def _inspection(self):
        """A completed inspection with Repair Required: confirmed fee order, draft repair quote."""
        case = self._create_case(self._ticket(warranty_product_id=self.product.id),
                                 user=self.creator, case_type='chargeable_inspection')
        action = case.with_user(self.sales_user).action_open_chargeable_wizard()
        wizard = self.env['warranty.case.chargeable.wizard'].with_user(self.sales_user) \
            .with_context(action['context']).create({})
        order = self.env['sale.order'].browse(wizard.action_convert()['res_id'])
        fee = order.order_line.filtered(lambda line: line.warranty_case_id == case)
        fee.tax_id = self.tax
        order.action_confirm()
        job = self.env['warranty.service.job'].search([('warranty_case_id', '=', case.id)])
        task = self._start_visit(job)
        action = task.with_user(self.tech).action_warranty_complete_visit()
        with Form(self.env[action['res_model']].with_user(self.tech).with_context(
                action['context'])) as form:
            form.diagnosis = 'Compressor seized'
            form.repair_required = 'yes'
            form.repair_details = 'Replace compressor'
        form.record.action_apply()
        self.assertEqual((case.state, case.chargeable_type), ('chargeable', 'repair'))
        return case, order, job.repair_quotation_id

    def _price(self, repair, amount=5000.0):
        repair.write({'order_line': [(0, 0, {'product_id': self.repair_product.id,
                                             'product_uom_qty': 1, 'price_unit': amount,
                                             'tax_id': [(6, 0, self.tax.ids)]})]})

    def _posted_invoice(self, order):
        invoice = order._create_invoices()
        invoice.action_post()
        return invoice

    def _apply(self, case, user=None):
        return case.with_user(user or self.billing).action_apply_inspection_fee_adjustment()

    def _credit_route(self, amount=5000.0):
        case, order, repair = self._inspection()
        invoice = self._posted_invoice(order)
        self._price(repair, amount)
        repair.action_confirm()
        return case, order, repair, invoice

    def _counts(self):
        return (self.env['account.move'].search_count([('state', '=', 'posted')]),
                self.env['account.payment'].search_count([]),
                self.env['account.partial.reconcile'].search_count([]))


@tagged('post_install', '-at_install', 'warranty_cost')
class TestInspectionFeeAdjustment(InspectionFlowCommon):
    """Part 8.4: credit note route, quotation route, declined repair, limits, rights."""

    # ------------------------------------------------------------------ route A
    def test_01_posted_invoice_gives_one_linked_draft_credit_note(self):
        case, order, repair, invoice = self._credit_route()
        self.assertTrue(case.with_user(self.billing).warranty_inspection_can_adjust)
        counts = self._counts()
        action = self._apply(case)
        note = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(action['res_model'], 'account.move')
        self.assertEqual((note.move_type, note.state, note.reversed_entry_id),
                         ('out_refund', 'draft', invoice))
        self.assertEqual((note.partner_id, note.company_id, note.currency_id),
                         (invoice.partner_id, invoice.company_id, invoice.currency_id))
        self.assertEqual((note.amount_untaxed, note.amount_tax, note.amount_total),
                         (invoice.amount_untaxed, invoice.amount_tax, invoice.amount_total))
        self.assertEqual(note.amount_total, 1725, '1,500 plus 15% tax')
        self.assertEqual(note.invoice_line_ids.tax_ids, self.tax)
        self.assertEqual(note.invoice_line_ids.account_id, invoice.invoice_line_ids.account_id)
        self.assertEqual(note.warranty_inspection_case_id, case)
        self.assertIn(case.name, note.ref)
        self.assertIn(invoice.name, note.ref)
        self.assertEqual(case.warranty_inspection_adjustment_status, 'credit_draft')
        self.assertEqual(self._counts(), counts, 'nothing posted, paid or reconciled')
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(repair.amount_total, 5750, 'the repair quotation is not changed')
        self.assertIn('Inspection fee adjustment', case.message_ids[0].body)
        self.assertEqual(case.action_open_inspection_fee_adjustment()['res_id'], note.id)

    def test_02_repeat_gives_no_duplicate(self):
        case, _order, _repair, _invoice = self._credit_route()
        self._apply(case)
        note = case.warranty_inspection_credit_note_ids
        self.assertFalse(case.with_user(self.billing).warranty_inspection_can_adjust)
        with self.assertRaisesRegex(UserError, 'already has an inspection fee adjustment'):
            self._apply(case)
        self.assertEqual(case.warranty_inspection_credit_note_ids, note)
        note.action_post()
        with self.assertRaisesRegex(UserError, 'already has an inspection fee adjustment'):
            self._apply(case)
        self.assertEqual(case.warranty_inspection_adjustment_status, 'credit_posted')

    def test_03_cancelled_or_reversed_note_can_be_redone(self):
        case, _order, _repair, _invoice = self._credit_route()
        self._apply(case)
        note = case.warranty_inspection_credit_note_ids
        note.button_cancel()
        case.invalidate_recordset()
        self.assertEqual(case.warranty_inspection_adjustment_status, 'none')
        second = self.env['account.move'].browse(self._apply(case)['res_id'])
        self.assertEqual((second.state, second.amount_total), ('draft', 1725))
        self.assertNotEqual(second, note)
        # A posted note reversed by Accounting is no longer effective, but the documents need a
        # person's review: no third note is created automatically.
        second.action_post()
        second._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=True)
        case.invalidate_recordset()
        self.assertEqual(case.warranty_inspection_adjustment_status, 'none')
        notes = case.warranty_inspection_credit_note_ids
        with self.assertRaises(UserError):
            self._apply(case)
        self.assertEqual(case.warranty_inspection_credit_note_ids, notes)

    def test_04_paid_unpaid_and_partly_paid_invoices(self):
        for label, percent in (('unpaid', 0), ('partly paid', 50), ('paid', 100)):
            case, _order, _repair, invoice = self._credit_route()
            if percent:
                self.env['account.payment.register'].with_context(
                    active_model='account.move', active_ids=invoice.ids).create(
                    {'amount': invoice.amount_total * percent / 100.0})._create_payments()
            state = invoice.payment_state
            reconciled = self.env['account.partial.reconcile'].search_count([])
            note = self.env['account.move'].browse(self._apply(case)['res_id'])
            self.assertEqual((note.state, note.amount_total), ('draft', 1725), label)
            self.assertEqual(invoice.payment_state, state, label)
            self.assertEqual(self.env['account.partial.reconcile'].search_count([]), reconciled,
                             '%s: nothing is reconciled' % label)
            self.assertFalse(self.env['account.payment'].search(
                [('reconciled_invoice_ids', 'in', note.ids)]), label)

    def test_05_invoice_already_credited_is_refused(self):
        case, _order, _repair, invoice = self._credit_route()
        invoice._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=False)
        with self.assertRaisesRegex(UserError, 'already has a credit note'):
            self._apply(case)
        self.assertFalse(case.warranty_inspection_credit_note_ids)

    def test_06_only_the_fee_line_and_the_limit_at_posting(self):
        case, order, _repair = self._inspection()
        order.write({'order_line': [(0, 0, {'product_id': self.repair_product.id,
                                            'product_uom_qty': 1, 'price_unit': 100,
                                            'tax_id': [(5, 0, 0)]})]})
        invoice = self._posted_invoice(order)
        self.assertEqual(invoice.amount_total, 1825)
        repair = self.env['sale.order'].search([('warranty_case_id', '=', case.id),
                                                ('warranty_chargeable_purpose', '=', 'repair')])
        self._price(repair)
        repair.action_confirm()
        note = self.env['account.move'].browse(self._apply(case)['res_id'])
        self.assertEqual(note.amount_total, 1725, 'the other invoice line is not credited')
        note.invoice_line_ids.price_unit = 2000
        with self.assertRaisesRegex(UserError, 'above the inspection fee'):
            note.action_post()
        note.invoice_line_ids.price_unit = 1500
        note.action_post()
        self.assertEqual(note.state, 'posted')
        order.invalidate_recordset()
        self.assertNotEqual(order.invoice_status, 'to invoice', 'the fee is finished')

    def test_07_repair_must_be_confirmed_for_a_credit_note(self):
        case, order, repair = self._inspection()
        self._posted_invoice(order)
        self._price(repair)
        with self.assertRaisesRegex(UserError, 'must be confirmed first'):
            self._apply(case)
        self.assertEqual(repair.state, 'draft')

    # ------------------------------------------------------------------ route B
    def test_08_no_posted_invoice_gives_a_quotation_deduction(self):
        case, order, repair = self._inspection()
        draft = order._create_invoices()
        self.assertEqual(draft.state, 'draft')
        self._price(repair)
        moves = self.env['account.move'].search_count([])
        action = self._apply(case, self.approver)
        self.assertEqual((action['res_model'], action['res_id']), ('sale.order', repair.id))
        self.assertEqual(self.env['account.move'].search_count([]), moves, 'no credit note')
        self.assertFalse(case.warranty_inspection_credit_note_ids)
        line = case.warranty_inspection_deduction_line_ids
        fee = order.order_line.filtered(lambda aml: aml.warranty_case_id == case)
        self.assertEqual((line.order_id, line.product_id, line.price_unit, line.tax_id),
                         (repair, self.deduction, -1500, fee.tax_id))
        self.assertEqual((repair.amount_untaxed, repair.amount_tax, repair.amount_total),
                         (3500, 525, 4025), 'correct amount and tax')
        self.assertEqual(case.warranty_inspection_adjustment_status, 'quotation')
        self.assertEqual(draft.state, 'draft', 'a draft inspection invoice stays as it is')
        with self.assertRaisesRegex(UserError, 'already has an inspection fee adjustment'):
            self._apply(case, self.approver)
        self.assertEqual(len(case.warranty_inspection_deduction_line_ids), 1)
        # A later posted inspection invoice gives no second benefit.
        draft.action_post()
        with self.assertRaisesRegex(UserError, 'already has an inspection fee adjustment'):
            self._apply(case)
        self.assertFalse(case.warranty_inspection_credit_note_ids)
        # The line reaches the repair invoice at its amount.
        repair.action_confirm()
        final = repair._create_invoices()
        self.assertEqual(final.amount_total, 4025)
        self.assertEqual(final.state, 'draft')

    def test_09_deduction_line_is_protected_and_can_be_redone(self):
        case, _order, repair = self._inspection()
        self._price(repair)
        self._apply(case, self.approver)
        line = case.warranty_inspection_deduction_line_ids
        with self.assertRaisesRegex(UserError, 'cannot be changed'):
            line.with_user(self.sales_user).write({'price_unit': -9999})
        with self.assertRaisesRegex(UserError, 'added from the warranty case'):
            self.env['sale.order.line'].with_user(self.sales_user).create({
                'order_id': repair.id, 'product_id': self.deduction.id,
                'warranty_inspection_deduction_case_id': case.id})
        line.unlink()
        case.invalidate_recordset()
        self.assertEqual(case.warranty_inspection_adjustment_status, 'none')
        self._apply(case, self.approver)
        self.assertEqual(len(case.warranty_inspection_deduction_line_ids), 1)

    def test_10_fee_not_charged_or_not_eligible(self):
        case, order, repair = self._inspection()
        self._price(repair)
        self.team.warranty_inspection_deduction_product_id = False
        with self.assertRaisesRegex(UserError, 'Set the Inspection Deduction Product'):
            self._apply(case)
        self.team.warranty_inspection_deduction_product_id = self.deduction
        self.deduction.invoice_policy = 'delivery'
        with self.assertRaisesRegex(UserError, 'ordered quantities'):
            self._apply(case)
        self.deduction.invoice_policy = 'order'
        self.env.flush_all()
        self.env.cr.execute("UPDATE sale_order SET state = 'draft' WHERE id = %s", (order.id,))
        self.env.invalidate_all()
        with self.assertRaisesRegex(UserError, 'no confirmed inspection order'):
            self._apply(case)
        self.env.cr.execute("UPDATE sale_order SET state = 'sale' WHERE id = %s", (order.id,))
        self.env.cr.execute("UPDATE warranty_service_job SET state = 'confirmed' "
                            "WHERE warranty_case_id = %s", (case.id,))
        self.env.invalidate_all()
        with self.assertRaisesRegex(UserError, 'no completed inspection job'):
            self._apply(case)
        self.env.cr.execute("UPDATE warranty_service_job SET state = 'completed' "
                            "WHERE warranty_case_id = %s", (case.id,))
        self.env.invalidate_all()
        repair.action_confirm()
        with self.assertRaisesRegex(UserError, 'Post the inspection invoice first'):
            self._apply(case)

    # ------------------------------------------------------------------ declined, F5, rights
    def test_11_declined_repair_blocks_and_keeps_the_fee(self):
        case, order, repair = self._inspection()
        invoice = self._posted_invoice(order)
        self.assertTrue(case.with_user(self.billing).warranty_inspection_can_adjust)
        case.with_user(self.helpdesk_user)._warranty_decline_repair('Too expensive')
        self.assertEqual(case.warranty_chargeable_outcome, 'repair_declined')
        self.assertEqual(repair.state, 'cancel')
        case.invalidate_recordset()
        self.assertFalse(case.with_user(self.billing).warranty_inspection_can_adjust)
        with self.assertRaisesRegex(UserError, 'the inspection fee stays charged'):
            self._apply(case)
        self.assertFalse(case.warranty_inspection_credit_note_ids)
        self.assertEqual((invoice.state, invoice.amount_total), ('posted', 1725))

    def test_12_decline_removes_a_quotation_deduction_with_its_quotation(self):
        case, _order, repair = self._inspection()
        self._price(repair)
        self._apply(case, self.approver)
        case.with_user(self.helpdesk_user)._warranty_decline_repair('Too expensive')
        case.invalidate_recordset()
        self.assertEqual(repair.state, 'cancel')
        self.assertEqual(case.warranty_inspection_adjustment_status, 'none')

    def test_13_fee_above_the_repair_total_is_refused(self):
        case, _order, repair, _invoice = self._credit_route(amount=1000)
        with self.assertRaisesRegex(UserError, r'above the repair total.*\(F5\)'):
            self._apply(case)
        self.assertFalse(case.warranty_inspection_credit_note_ids)
        self.assertEqual(repair.amount_total, 1150)
        case, _order, repair = self._inspection()
        self._price(repair, 1000)
        with self.assertRaisesRegex(UserError, r'above the repair total.*\(F5\)'):
            self._apply(case)
        self.assertFalse(case.warranty_inspection_deduction_line_ids)
        self.assertEqual(repair.amount_total, 1150)
        case, _order, repair = self._inspection()
        with self.assertRaisesRegex(UserError, 'Check that the repair is priced'):
            self._apply(case)

    def test_14_rights(self):
        case, _order, repair = self._inspection()
        self._price(repair)
        self.assertFalse(case.with_user(self.outsider).warranty_inspection_can_adjust)
        with self.assertRaisesRegex(AccessError, 'Only Billing users and named Cost Approvers'):
            self._apply(case, self.outsider)
        with self.assertRaises(AccessError):
            self._apply(case, self.tech)
        with self.assertRaises(AccessError):
            case.with_user(self.tech).read(['warranty_inspection_adjustment_status'])
        self.assertFalse(case.warranty_inspection_deduction_line_ids)
        self.company.warranty_cost_approver_ids = False
        with self.assertRaises(AccessError):
            self._apply(case, self.approver)
        self.company.warranty_cost_approver_ids = self.approver_no_sales
        self.assertIs(self._apply(case, self.approver_no_sales), True,
                      'no Sales rights: the adjustment is made, the status shows on the case')
        self.assertTrue(case.warranty_inspection_deduction_line_ids)
        self.assertEqual(case.with_user(self.approver_no_sales).warranty_inspection_adjustment_status,
                         'quotation')

    def test_15_company_isolation(self):
        case, _order, repair = self._inspection()
        self._price(repair)
        other = self.env['res.company'].create({'name': 'Fee Co B'})
        user = self.env['res.users'].create({
            'name': 'Fee Other', 'login': 'fee_other', 'company_id': other.id,
            'company_ids': [(6, 0, other.ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('account.group_account_invoice')
                                  | self.env.ref('helpdesk.group_helpdesk_user')).ids)]})
        with self.assertRaises(AccessError):
            case.with_user(user).action_apply_inspection_fee_adjustment()
        self.assertFalse(case.warranty_inspection_deduction_line_ids)
        approver_other = self.env['res.users'].create({
            'name': 'Fee Approver B', 'login': 'fee_approver_b', 'company_id': self.company.id,
            'company_ids': [(6, 0, (self.company | other).ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('helpdesk.group_helpdesk_user')).ids)]})
        other.warranty_cost_approver_ids = approver_other
        with self.assertRaisesRegex(AccessError, 'Only Billing users and named Cost Approvers'):
            self._apply(case, approver_other)

    # ------------------------------------------------------------------ final safety corrections
    def _fee_line(self, order, case):
        return order.order_line.filtered(lambda line: line.warranty_case_id == case)

    def test_17_credited_fee_cannot_be_invoiced_again(self):
        case, order, _repair, invoice = self._credit_route()
        fee = self._fee_line(order, case)
        self.assertEqual(fee.qty_to_invoice, 0)
        note = self.env['account.move'].browse(self._apply(case)['res_id'])
        self.env.flush_all()
        fee.invalidate_recordset()
        self.assertEqual(fee.qty_to_invoice, 0, 'a draft credit note: not to invoice again')
        note.action_post()
        self.env.flush_all()
        fee.invalidate_recordset()
        order.invalidate_recordset()
        self.assertEqual(fee.qty_invoiced, 0, 'the standard figure is unchanged')
        self.assertEqual(fee.qty_to_invoice, 0)
        self.assertNotEqual(order.invoice_status, 'to invoice')
        with self.assertRaises(UserError):
            order._create_invoices()
        moves = self.env['account.move'].search_count([('move_type', '=', 'out_invoice')])
        # A manual invoice linked to the same line is refused when it is posted.
        manual = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': invoice.partner_id.id,
            'company_id': invoice.company_id.id, 'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'product_id': self.fee_product.id, 'quantity': 1,
                                         'price_unit': 1500,
                                         'sale_line_ids': [(6, 0, fee.ids)]})]})
        self.assertEqual(self.env['account.move'].search_count([('move_type', '=', 'out_invoice')]),
                         moves + 1)
        with self.assertRaisesRegex(UserError, 'cannot be invoiced again'):
            manual.action_post()
        self.assertEqual(manual.state, 'draft')
        self.assertEqual((invoice.state, note.state), ('posted', 'posted'), 'not modified')

    def test_18_unrelated_lines_stay_invoiceable(self):
        case, order, _repair, _invoice = self._credit_route()
        self._apply(case)
        case.warranty_inspection_credit_note_ids.action_post()
        order.write({'order_line': [(0, 0, {'product_id': self.repair_product.id,
                                            'product_uom_qty': 1, 'price_unit': 100,
                                            'tax_id': [(5, 0, 0)]})]})
        extra = order.order_line.filtered(lambda line: line.product_id == self.repair_product)
        self.assertEqual(extra.qty_to_invoice, 1)
        second = order._create_invoices()
        self.assertEqual((second.amount_total, second.invoice_line_ids.sale_line_ids),
                         (100, extra), 'only the unrelated line')
        second.action_post()
        self.assertEqual(second.state, 'posted')

    def test_19_cancel_and_standard_reversal_stay_possible(self):
        case, order, _repair, invoice = self._credit_route()
        fee = self._fee_line(order, case)
        self._apply(case)
        note = case.warranty_inspection_credit_note_ids
        note.button_cancel()
        self.env.flush_all()
        fee.invalidate_recordset()
        self.assertEqual(fee.qty_to_invoice, 0, 'the invoice still stands')
        self.assertEqual(fee.qty_invoiced, 1)
        second = self.env['account.move'].browse(self._apply(case)['res_id'])
        second.action_post()
        reversal = second._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=True)
        self.assertEqual((reversal.state, reversal.move_type), ('posted', 'out_invoice'),
                         'a standard reversal of the credit note is not blocked')
        self.env.flush_all()
        fee.invalidate_recordset()
        self.assertEqual(fee.qty_invoiced, 1, 'net: the fee is charged once')
        self.assertEqual(fee.qty_to_invoice, 0)
        self.assertEqual(invoice.state, 'posted')

    def test_20_duplicated_quotation_has_no_deduction(self):
        case, _order, repair = self._inspection()
        self._price(repair)
        self._apply(case, self.approver)
        original = case.warranty_inspection_deduction_line_ids
        self.assertEqual(repair.amount_total, 4025)
        copied = repair.copy()
        self.assertFalse(copied.order_line.filtered(lambda line: line.price_unit < 0),
                         'no negative line')
        self.assertFalse(copied.order_line.filtered('warranty_inspection_deduction_case_id'))
        self.assertTrue(copied.order_line.filtered(lambda line: line.product_id == self.repair_product))
        self.assertEqual(copied.amount_total, 5750, 'other lines are copied as usual')
        self.assertEqual(case.warranty_inspection_deduction_line_ids, original, 'still one')
        self.assertEqual(repair.amount_total, 4025)
        # The copy can't take a second adjustment.
        with self.assertRaisesRegex(UserError, 'already has an inspection fee adjustment'):
            self._apply(case, self.approver)
        plain = self.env['sale.order'].create({
            'partner_id': repair.partner_id.id,
            'order_line': [(0, 0, {'product_id': self.repair_product.id, 'price_unit': -50})]})
        self.assertEqual(len(plain.copy().order_line), 1, 'unrelated quotations copy as usual')

    def test_21_rpc_cannot_set_the_links(self):
        case, _order, repair, _invoice = self._credit_route()
        self._apply(case)
        note = case.warranty_inspection_credit_note_ids
        for vals in ({'warranty_inspection_case_id': False},
                     {'warranty_inspection_credit_limit': 999999}):
            with self.assertRaisesRegex(UserError, 'cannot be changed'):
                note.with_user(self.billing).write(vals)
        with self.assertRaisesRegex(UserError, 'set by its action'):
            case.with_user(self.helpdesk_user).write(
                {'warranty_inspection_credit_note_ids': [(5, 0, 0)]})
        self.assertEqual(case.warranty_inspection_credit_note_ids, note)
        other = self.env['res.company'].create({'name': 'Fee Co C'})
        user = self.env['res.users'].create({
            'name': 'Fee C', 'login': 'fee_c', 'company_id': other.id,
            'company_ids': [(6, 0, other.ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('helpdesk.group_helpdesk_user')).ids)]})
        with self.assertRaises(AccessError):
            case.with_user(user).action_open_inspection_fee_adjustment()
        self.assertEqual(repair.state, 'sale')

    def test_22_report_hides_brand_and_model_and_keeps_the_fields(self):
        Report = self.env['warranty.cost.report'].with_user(self.helpdesk_user)
        for view_type in ('list', 'search'):
            arch = Report.get_view(False, view_type)['arch']
            self.assertNotIn('name="brand"', arch)
            self.assertNotIn('name="model"', arch)
            self.assertNotIn('group_brand', arch)
            self.assertNotIn('group_model', arch)
        self.assertIn('brand', Report._fields)
        self.assertIn('warranty_brand', self.env['product.template']._fields)

    def test_16_view_and_configuration_stay(self):
        arch = self.env['warranty.case'].with_user(self.billing).get_view(False, 'form')['arch']
        self.assertIn('action_apply_inspection_fee_adjustment', arch)
        self.assertEqual(self.team.warranty_inspection_amount, 1500)
        case, order, _repair = self._inspection()
        fee = order.order_line.filtered(lambda line: line.warranty_case_id == case)
        self.assertEqual((fee.product_id, fee.price_unit), (self.fee_product, 1500))
