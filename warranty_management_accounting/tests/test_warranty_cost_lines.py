from contextlib import contextmanager
from datetime import timedelta

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.warranty_management_fsm.tests.test_shared_visit import TestSharedVisit
from odoo.addons.warranty_management_mrf.tests.common import WarrantyMrfCommon


class _SavepointMixin:
    @contextmanager
    def assertRaisesRegex(self, exception, regex):
        """Refused operations are rolled back as in a real request."""
        with super().assertRaisesRegex(exception, regex):
            with self.env.cr.savepoint():
                yield
        self.env.invalidate_all(flush=False)


@tagged('post_install', '-at_install', 'warranty_cost')
class TestWarrantyCostLines(_SavepointMixin, WarrantyMrfCommon):
    """Part 8.1: cost lines, approval, subcontract links, totals, gate and security."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls._user('cost_manager', 'helpdesk.group_helpdesk_user')
        cls.finance = cls._user('cost_finance', 'account.group_account_readonly')
        cls.billing = cls._user('cost_billing', 'account.group_account_invoice')
        cls.outsider = cls._user('cost_outsider')
        cls.company.write({
            'warranty_cost_approver_ids': [(6, 0, cls.manager.ids)],
            'warranty_cost_finance_approver_ids': [(6, 0, cls.finance.ids)],
            'warranty_cost_finance_threshold': 1000,
            'warranty_cost_gate_enabled': False,
            'warranty_cost_gate_threshold': 0,
            'warranty_mrf_approval_matrix': True,
        })
        cls.env['warranty.mrf.approval.rule'].create({
            'name': 'All free (8.1 test)', 'company_id': cls.company.id, 'no_approval': True})
        cls.covered_part = cls.env['product.product'].create({
            'name': 'Air Filter', 'is_storable': True, 'type': 'consu', 'standard_price': 500})
        cls.policy.covered_item_ids |= cls.env['warranty.coverage.item'].create({
            'name': cls.covered_part.name, 'product_id': cls.covered_part.id})
        cls.Line = cls.env['warranty.cost.line']
        cls.employee = cls.env['hr.employee'].search([('user_id', '=', cls.tech.id)], limit=1)
        cls.employee.hourly_cost = 50
        cls.vendor = cls.env['res.partner'].create({'name': 'Subcontractor', 'is_company': True})
        cls.service = cls.env['product.product'].create({
            'name': 'Gas Recovery Service', 'type': 'service', 'standard_price': 100})
        cls.expense = cls.env['account.account'].create({
            'name': 'Subcontract Expense', 'code': 'WCL810', 'account_type': 'expense',
            'company_ids': [(6, 0, cls.company.ids)]})

    # ------------------------------------------------------------------ helpers
    def _line(self, case, cost_type='travel', user=None, **vals):
        return self.Line.with_user(user or self.helpdesk_user).create(dict({
            'case_id': case.id, 'cost_type': cost_type, 'reason': 'Needed for the visit',
            'estimated_amount': 500}, **vals))

    def _approve(self, line):
        line.with_user(self.helpdesk_user).action_submit()
        line.with_user(self.manager).action_approve()
        if line.finance_required:
            line.with_user(self.finance).action_approve()
        self.assertEqual(line.state, 'approved')
        return line

    def _timesheet(self, task, hours=2.0):
        return self.env['account.analytic.line'].create({
            'name': 'Visit work', 'project_id': task.project_id.id, 'task_id': task.id,
            'employee_id': self.employee.id, 'unit_amount': hours})

    def _bill(self, amount=1000, post=True):
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice', 'partner_id': self.vendor.id,
            'invoice_date': fields.Date.today(), 'company_id': self.company.id,
            'invoice_line_ids': [(0, 0, {'product_id': self.service.id, 'name': 'Subcontract',
                                         'quantity': 1, 'price_unit': amount,
                                         'tax_ids': [(5, 0, 0)],
                                         'account_id': self.expense.id})]})
        if post:
            move.action_post()
        return move, move.invoice_line_ids

    def _order(self, amount=1000, currency=None):
        order = self.env['purchase.order'].with_company(self.company).create({
            'partner_id': self.vendor.id, 'company_id': self.company.id,
            'currency_id': (currency or self.company.currency_id).id,
            'order_line': [(0, 0, {'product_id': self.service.id, 'product_qty': 1,
                                   'price_unit': amount, 'taxes_id': [(5, 0, 0)]})]})
        order.button_confirm()
        return order

    def _approved_mrf(self, job):
        action = job.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {'product_id': self.covered_part.id, 'qty': 1,
                                             'description': self.covered_part.name,
                                             'uom': self.covered_part.uom_id.id})]})
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual(mrf.state, 'approve')
        return mrf

    def _side_effects(self):
        return (self.env['account.move'].search_count([]),
                self.env['stock.valuation.layer'].search_count([]))

    # ------------------------------------------------------------------ labour
    def test_01_labour_from_timesheets_read_only(self):
        job = self._confirmed_job()
        sheet = self._timesheet(job.visit_ids)
        self.env.flush_all()
        before = (sheet.unit_amount, sheet.amount, sheet.write_date)
        self.assertEqual(sheet.amount, -100)
        self.assertEqual(job.warranty_labour_cost, 100)
        self.assertEqual(job.warranty_labour_hours, 2)
        self.assertEqual(job.warranty_case_id.warranty_labour_cost, 100)
        self.assertEqual(job.warranty_total_actual, 100)
        self.assertEqual((sheet.unit_amount, sheet.amount, sheet.write_date), before,
                         'the timesheet is only read')

    def test_02_labour_estimate_cannot_hold_manual_actual(self):
        job = self._confirmed_job()
        case = job.warranty_case_id
        with self.assertRaisesRegex(ValidationError, 'read from its timesheets'):
            self._line(case, 'labour', job_id=job.id, actual_amount=50)
        line = self._line(case, 'labour', job_id=job.id, estimated_amount=300)
        self._timesheet(job.visit_ids)
        self.assertEqual(case.warranty_total_expected, 300, 'estimate or timesheet, not both')
        self.env['account.analytic.line'].search([('task_id', '=', job.visit_ids.id)]).write(
            {'unit_amount': 8})
        job.invalidate_recordset()
        case.invalidate_recordset()
        self.assertEqual(case.warranty_labour_cost, 400)
        self.assertEqual(case.warranty_total_expected, 400)
        self.assertEqual(line.counted_actual_amount, 0)

    def test_03_workshop_labour_on_repair_order(self):
        job = self._confirmed_job()
        case = job.warranty_case_id
        repair = self.env['repair.order'].create({
            'product_id': self.part.id, 'warranty_case_id': case.id,
            'partner_id': case.partner_id.id})
        line = self._approve(self._line(case, 'labour', repair_id=repair.id, estimated_amount=300,
                                        actual_amount=250))
        self.assertEqual(line.counted_actual_amount, 250)
        self.assertEqual(case.warranty_total_actual, 250)
        self.assertEqual(job.warranty_total_actual, 0, 'a Repair Order line is not on the job')
        self.assertEqual(repair.warranty_cost_line_count, 1)
        with self.assertRaisesRegex(ValidationError, 'one service job or one Repair Order'):
            self._line(case, 'labour', repair_id=repair.id, job_id=job.id)
        other = self._approved()
        with self.assertRaisesRegex(ValidationError, 'does not belong to warranty case'):
            self._line(other, 'labour', repair_id=repair.id)

    # ------------------------------------------------------------------ approval and reversal
    def test_04_approval_reversal_and_audit(self):
        moves = self._side_effects()
        case = self._approved()
        line = self._line(case)
        self.assertEqual(line.counted_actual_amount, 0)
        with self.assertRaisesRegex(UserError, 'not waiting for approval'):
            line.with_user(self.manager).action_approve()
        line.with_user(self.helpdesk_user).action_submit()
        self.assertTrue(line.with_user(self.manager).can_approve)
        self.assertFalse(line.with_user(self.helpdesk_user).can_approve, 'no self approval')
        with self.assertRaisesRegex(AccessError, 'not a pending approver'):
            line.with_user(self.helpdesk_user).action_approve()
        line.with_user(self.manager).action_approve()
        self.assertEqual((line.state, line.approved_amount, line.manager_approved_by_id),
                         ('approved', 500, self.manager))
        with self.assertRaisesRegex(UserError, 'only be changed in Draft'):
            line.with_user(self.helpdesk_user).write({'estimated_amount': 1})
        with self.assertRaisesRegex(UserError, 'set by the approval workflow'):
            line.with_user(self.helpdesk_user).write({'state': 'draft'})
        with self.assertRaisesRegex(UserError, 'never deleted'):
            line.with_user(self.helpdesk_user).unlink()
        with self.assertRaisesRegex(UserError, 'between 0 and the approved'):
            line.with_user(self.helpdesk_user)._warranty_record_actual(501, 'Too high')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            line.with_user(self.helpdesk_user)._warranty_record_actual(400, '  ')
        line.with_user(self.helpdesk_user)._warranty_record_actual(400, 'Taxi receipt')
        self.assertEqual(case.warranty_total_actual, 400)
        self.assertIn('Taxi receipt', case.message_ids[0].body)
        with self.assertRaisesRegex(AccessError, 'can reverse'):
            line.with_user(self.helpdesk_user)._warranty_reverse('Mistake')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            line.with_user(self.manager)._warranty_reverse('')
        line.with_user(self.manager)._warranty_reverse('Wrong case')
        case.invalidate_recordset()
        self.assertEqual((line.state, line.approved_amount, line.actual_amount,
                          line.reversal_reason, line.reversed_by_id),
                         ('reversed', 500, 400, 'Wrong case', self.manager), 'history is kept')
        self.assertEqual(case.warranty_total_actual, 0)
        self.assertEqual(case.warranty_total_approved, 0)
        self.assertIn('Wrong case', case.message_ids[0].body)
        self.assertEqual(self._side_effects(), moves, 'no journal entry and no valuation layer')

    def test_05_rejection_needs_a_reason(self):
        line = self._line(self._approved())
        line.with_user(self.helpdesk_user).action_submit()
        with self.assertRaisesRegex(UserError, 'reason is required'):
            line.with_user(self.manager)._warranty_reject('')
        line.with_user(self.manager)._warranty_reject('Not justified')
        self.assertEqual((line.state, line.rejection_reason), ('rejected', 'Not justified'))
        self.assertEqual(line.expected_amount, 0)

    def test_06_finance_threshold_zero_never_skips_approval(self):
        case = self._approved()
        small = self._line(case, estimated_amount=500)
        small.with_user(self.helpdesk_user).action_submit()
        self.assertFalse(small.finance_required)
        big = self._line(case, estimated_amount=700)
        big.with_user(self.helpdesk_user).action_submit()
        self.assertTrue(big.finance_required, 'total expected 1,200 reaches 1,000')
        big.with_user(self.manager).action_approve()
        self.assertEqual(big.state, 'submitted')
        big.with_user(self.finance).action_approve()
        self.assertEqual(big.state, 'approved')
        small.with_user(self.manager).action_approve()
        self.assertTrue(small.finance_required, 'the total rose after it was submitted')
        self.assertEqual(small.state, 'submitted')
        small.with_user(self.finance).action_approve()
        self.assertEqual(small.state, 'approved')
        self.company.warranty_cost_finance_threshold = 0
        other = self._line(self._approved(), estimated_amount=999999)
        other.with_user(self.helpdesk_user).action_submit()
        self.assertFalse(other.finance_required, 'threshold 0 turns the Finance level off')
        self.assertEqual(other.state, 'submitted', 'the Manager approval stays mandatory')
        self.assertEqual(other.counted_approved_amount, 0)
        with self.assertRaisesRegex(AccessError, 'not a pending approver'):
            other.with_user(self.finance).action_approve()
        other.with_user(self.manager).action_approve()
        self.assertEqual(other.state, 'approved')
        self.company.write({'warranty_cost_approver_ids': [(5, 0, 0)]})
        unconfigured = self._line(self._approved())
        with self.assertRaisesRegex(UserError, 'configure the approvers'):
            unconfigured.with_user(self.helpdesk_user).action_submit()

    # ------------------------------------------------------------------ subcontract
    def test_07_subcontract_bill_line_allocated_once(self):
        moves_before = self.env['account.move'].search_count([])
        move, bill_line = self._bill(1000)
        moves = self.env['account.move'].search_count([])
        self.assertEqual(moves, moves_before + 1)
        case = self._approved()
        line = self._line(case, 'subcontract', estimated_amount=0)
        with self.assertRaisesRegex(UserError, 'needs its purchase order line'):
            line.with_user(self.helpdesk_user).action_submit()
        line.with_user(self.billing).write({'bill_line_id': bill_line.id})
        with self.assertRaisesRegex(AccessError, 'only link'):
            line.with_user(self.billing).write({'estimated_amount': 1})
        self.assertEqual(line.source_reference, move.name)
        self.assertEqual(line.source_amount, 1000)
        self._approve(line)
        self.assertEqual(line.approved_amount, 1000)
        self.assertEqual(case.warranty_total_actual, 1000)
        other = self._approved()
        with self.assertRaisesRegex(ValidationError, 'already allocated'):
            self._line(other, 'subcontract', bill_line_id=bill_line.id)
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertEqual(move.state, 'posted')
        line.with_user(self.manager)._warranty_reverse('Wrong case')
        relinked = self._line(other, 'subcontract', bill_line_id=bill_line.id)
        self.assertEqual(relinked.source_amount, 1000, 'a reversed line frees its bill line')

    def test_15_reversed_bill_flags_the_line_and_stops_counting(self):
        move, bill_line = self._bill(1000)
        case = self._approved()
        line = self._approve(self._line(case, 'subcontract', estimated_amount=0,
                                        bill_line_id=bill_line.id))
        self.assertEqual(case.warranty_total_actual, 1000)
        move._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=True)
        self.assertEqual(move.payment_state, 'reversed')
        line.invalidate_recordset()
        case.invalidate_recordset()
        self.assertIn('reversed', line.source_warning)
        self.assertEqual(line.counted_actual_amount, 0)
        self.assertEqual(case.warranty_total_actual, 0)
        self.assertEqual((line.state, line.approved_amount), ('approved', 1000), 'history is kept')

    def test_08_subcontract_refuses_invalid_sources(self):
        case = self._approved()
        draft_move, draft_line = self._bill(100, post=False)
        with self.assertRaisesRegex(ValidationError, 'posted vendor bill'):
            self._line(case, 'subcontract', bill_line_id=draft_line.id)
        part_move, part_line = self._bill(100)
        part_move.button_draft()
        part_line.write({'product_id': self.part.id, 'price_unit': 100,
                         'account_id': self.expense.id, 'tax_ids': [(5, 0, 0)]})
        part_move.action_post()
        with self.assertRaisesRegex(ValidationError, 'stockable product'):
            self._line(case, 'subcontract', bill_line_id=part_line.id)
        with self.assertRaisesRegex(ValidationError, 'Only Subcontract lines'):
            self._line(case, 'travel', bill_line_id=self._bill(100)[1].id)
        with self.assertRaisesRegex(ValidationError, 'read from its purchase'):
            self._line(case, 'subcontract', actual_amount=10)

    def test_09_purchase_line_conversion_and_cross_duplicates(self):
        currency = self.env.ref('base.EUR')
        currency.active = True
        if currency == self.company.currency_id:
            currency = self.env.ref('base.GBP')
            currency.active = True
        self.env['res.currency.rate'].search([('currency_id', '=', currency.id)]).unlink()
        self.env['res.currency.rate'].create({
            'currency_id': currency.id, 'company_id': self.company.id, 'rate': 0.5,
            'name': fields.Date.today() - timedelta(days=30)})
        order = self._order(100, currency)
        case = self._approved()
        line = self._line(case, 'subcontract', estimated_amount=0,
                          purchase_line_id=order.order_line.id)
        self.assertEqual(line.source_commitment, 200, 'standard conversion to company currency')
        self.assertEqual(line.expected_amount, 200)
        self.assertEqual(line.counted_actual_amount, 0)
        order.action_create_invoice()
        move = order.invoice_ids
        move.write({'invoice_date': fields.Date.today()})
        move.action_post()
        line.invalidate_recordset()
        self.assertEqual(line.source_amount, 200)
        with self.assertRaisesRegex(ValidationError, 'already allocated'):
            self._line(self._approved(), 'subcontract',
                       bill_line_id=move.invoice_line_ids.filtered('purchase_line_id').id)
        self._approve(line)
        self.assertEqual(case.warranty_total_actual, 200)

    # ------------------------------------------------------------------ totals
    def test_10_no_double_counting_between_job_and_case(self):
        job = self._confirmed_job()
        case = job.warranty_case_id
        self._approve(self._line(case, job_id=job.id, estimated_amount=100, actual_amount=100))
        self._approve(self._line(case, 'other', estimated_amount=40, actual_amount=40))
        self._timesheet(job.visit_ids)
        self.assertEqual(job.warranty_total_actual, 200, 'its line and its labour')
        self.assertEqual(case.warranty_total_actual, 240, 'also the case-level line')
        self.assertEqual(case.warranty_total_approved, 140)
        self.assertEqual(case.warranty_cost_line_count, 2)
        self.assertEqual(job.warranty_cost_line_count, 1)
        self.assertIn('Travel', case.warranty_cost_overview)

    # ------------------------------------------------------------------ gate
    def test_11_gate_off_by_default_then_enforced(self):
        case = self._approved()
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        pending = self._line(case, estimated_amount=1500)
        self.assertFalse(case._warranty_expected_cost_error(), 'disabled by default')
        self.company.write({'warranty_cost_gate_enabled': True,
                            'warranty_cost_gate_threshold': 1000})
        self.assertIn(pending.name, case._warranty_expected_cost_error())
        with self.assertRaisesRegex(UserError, 'waiting for approval'):
            job.with_user(self.helpdesk_user).action_confirm_job()
        self._approve(pending)
        self.assertFalse(case._warranty_expected_cost_error())
        job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual(job.state, 'confirmed')
        low = self.company.warranty_cost_gate_threshold
        self.company.warranty_cost_gate_threshold = 5000
        self._line(case, estimated_amount=1)
        self.assertFalse(case._warranty_expected_cost_error(), 'at or below the threshold')
        self.company.warranty_cost_gate_threshold = low
        self.assertTrue(case._warranty_expected_cost_error())
        self.assertEqual(job.state, 'confirmed', 'a confirmed job is not reversed')

    def test_12_gate_threshold_zero_and_next_visit_and_release(self):
        job = self._confirmed_job()
        case = job.warranty_case_id
        mrf = self._approved_mrf(job)
        self.company.write({'warranty_cost_gate_enabled': True,
                            'warranty_cost_gate_threshold': 0})
        self.assertFalse(mrf._warranty_release_error(), 'an approved request is not blocked')
        self._line(case, estimated_amount=1)
        self.assertIn('waiting for approval', mrf._warranty_release_error())
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_service_job SET state = 'incomplete' WHERE id = %s",
                            (job.id,))
        job.invalidate_recordset(['state'])
        with self.assertRaisesRegex(UserError, 'waiting for approval'):
            job.with_user(self.helpdesk_user)._warranty_plan_next_visit(
                fields.Datetime.now() + timedelta(days=1), self.tech)
        self.assertFalse(self.company.warranty_cost_gate_threshold)

    # ------------------------------------------------------------------ security and views
    def test_13_security(self):
        job = self._confirmed_job()
        case = job.warranty_case_id
        line = self._line(case)
        with self.assertRaises(AccessError):
            line.with_user(self.tech).read(['name'])
        with self.assertRaises(AccessError):
            job.with_user(self.tech).read(['warranty_total_actual'])
        with self.assertRaises(AccessError):
            self.Line.with_user(self.billing).create({
                'case_id': case.id, 'cost_type': 'travel', 'reason': 'x'})
        self.assertEqual(line.with_user(self.finance).read(['name'])[0]['name'], line.name)
        with self.assertRaises(AccessError):
            line.with_user(self.finance).write({'estimated_amount': 1})
        with self.assertRaises(AccessError):
            line.with_user(self.outsider).read(['name'])
        other_company = self.env['res.company'].create({'name': 'Cost Other Company'})
        stranger = self._user('cost_stranger', 'helpdesk.group_helpdesk_user')
        stranger.write({'company_ids': [(6, 0, other_company.ids)],
                        'company_id': other_company.id})
        with self.assertRaises(AccessError):
            line.with_user(stranger).read(['name'])
        line.with_user(self.helpdesk_user).action_submit()
        self.assertEqual(line.with_user(self.manager).read(['name'])[0]['name'], line.name)
        with self.assertRaisesRegex(UserError, 'set by the approval workflow'):
            self._line(case, approved_amount=5)

    def test_17_missing_hourly_cost_is_flagged_not_verified(self):
        job = self._confirmed_job()
        case = job.warranty_case_id
        self.employee.hourly_cost = 0
        sheet = self._timesheet(job.visit_ids)
        self.env.flush_all()
        before = (sheet.amount, sheet.unit_amount, sheet.write_date, self.employee.hourly_cost)
        self.assertEqual(job.warranty_labour_cost, 0)
        self.assertEqual(job.warranty_labour_missing_hours, 2)
        self.assertTrue(job.warranty_labour_incomplete)
        self.assertTrue(case.warranty_labour_incomplete)
        for record in (job, case):
            self.assertIn('Labour cost is incomplete', record.warranty_cost_overview)
            self.assertIn('Incomplete', record.warranty_cost_overview)
            self.assertIn(self.employee.name, record.warranty_cost_overview)
        self.assertEqual((sheet.amount, sheet.unit_amount, sheet.write_date,
                          self.employee.hourly_cost), before, 'nothing is written')
        self.employee.hourly_cost = 50
        self._timesheet(job.visit_ids, hours=1)
        job.invalidate_recordset()
        self.assertEqual(job.warranty_labour_cost, 50)
        self.assertEqual(job.warranty_labour_missing_hours, 2, 'the old line stays incomplete')
        complete = self._confirmed_job()
        self._timesheet(complete.visit_ids)
        self.assertFalse(complete.warranty_labour_incomplete)
        self.assertNotIn('Incomplete', complete.warranty_cost_overview)

    def test_18_partial_refund_on_a_linked_bill_line(self):
        move, bill_line = self._bill(1000)
        case = self._approved()
        line = self._approve(self._line(case, 'subcontract', estimated_amount=0,
                                        bill_line_id=bill_line.id))
        refund = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        refund.invoice_line_ids.price_unit = 300
        line.invalidate_recordset()
        self.assertEqual(line.source_amount, 1000, 'a draft credit note does not count')
        refund.action_post()
        line.invalidate_recordset()
        case.invalidate_recordset()
        self.assertEqual(line.source_amount, 700)
        self.assertEqual(line.counted_actual_amount, 700)
        self.assertEqual(line.approved_amount, 1000, 'the approved figure is kept')
        self.assertEqual(case.warranty_total_actual, 700)
        self.assertIn('credit notes', line.source_warning)
        self.assertFalse(line.source_invalid)
        self.assertEqual(move.state, 'posted')
        late = self._line(self._approved(), 'subcontract', estimated_amount=0,
                          bill_line_id=self._partly_refunded_bill()[1].id)
        late.with_user(self.helpdesk_user).action_submit()
        self.assertEqual(late.state, 'submitted', 'a partial refund does not block the line')

    def _partly_refunded_bill(self):
        move, bill_line = self._bill(500)
        refund = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        refund.invoice_line_ids.price_unit = 100
        refund.action_post()
        return move, bill_line

    def test_19_partial_refund_split_across_bill_lines_and_through_a_purchase_line(self):
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice', 'partner_id': self.vendor.id,
            'invoice_date': fields.Date.today(), 'company_id': self.company.id,
            'invoice_line_ids': [(0, 0, {'product_id': self.service.id, 'name': 'Part %s' % amount,
                                         'quantity': 1, 'price_unit': amount,
                                         'tax_ids': [(5, 0, 0)],
                                         'account_id': self.expense.id})
                                 for amount in (600, 400)]})
        move.action_post()
        first, second = move.invoice_line_ids.sorted('balance', reverse=True)
        lines = self._line(self._approved(), 'subcontract', estimated_amount=0,
                           bill_line_id=first.id) | self._line(
            self._approved(), 'subcontract', estimated_amount=0, bill_line_id=second.id)
        refund = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        refund.invoice_line_ids[1:].unlink()
        refund.invoice_line_ids.price_unit = 100
        refund.action_post()
        lines.invalidate_recordset()
        by_bill = {line.bill_line_id: line.source_amount for line in lines}
        self.assertEqual((by_bill[first], by_bill[second]), (540, 360),
                         'one refund of 100 is split 60 / 40, not deducted twice')

    def test_20_purchase_line_nets_a_partial_refund(self):
        order = self._order(1000)
        order.action_create_invoice()
        move = order.invoice_ids
        move.write({'invoice_date': fields.Date.today()})
        move.action_post()
        line = self._line(self._approved(), 'subcontract', estimated_amount=0,
                          purchase_line_id=order.order_line.id)
        self.assertEqual(line.source_amount, 1000)
        refund = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        refund.invoice_line_ids.price_unit = 250
        refund.action_post()
        line.invalidate_recordset()
        self.assertEqual(line.source_amount, 750)

    def test_21_mandatory_approvals_are_preserved(self):
        """The expected cost checks only add a condition: Material Request and Service Job checks
        still decide first, with the gate off, or on and passing."""
        self.env['warranty.mrf.approval.rule'].search([]).active = False
        self.env['warranty.mrf.approval.rule'].create({
            'name': 'Manager (8.1 test)', 'company_id': self.company.id, 'manager_required': True,
            'manager_user_ids': [(6, 0, self.manager.ids)]})
        job = self._confirmed_job()
        case = job.warranty_case_id
        action = job.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {'product_id': self.covered_part.id, 'qty': 1,
                                             'description': self.covered_part.name,
                                             'uom': self.covered_part.uom_id.id})]})
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertNotEqual(mrf.state, 'approve')
        expected_error = mrf._warranty_release_error()
        self.assertTrue(expected_error)
        self.company.write({'warranty_cost_gate_enabled': True,
                            'warranty_cost_gate_threshold': 9999999})
        self.assertFalse(case._warranty_expected_cost_error(), 'below the threshold')
        self.assertEqual(mrf._warranty_release_error(), expected_error,
                         'passing the gate never approves a Material Request')
        self._approve(self._line(case, estimated_amount=10))
        self.assertNotEqual(mrf.state, 'approve', 'a cost line approval does not touch it')
        self.company.warranty_cost_gate_threshold = 0
        self.assertIn(mrf.name, case._warranty_expected_cost_error())
        draft_case = self._approved()
        draft_job = self._prepare(draft_case)
        off = draft_job._warranty_confirm_problems()
        self.assertTrue(off, 'no technician or planned date')
        self.company.warranty_cost_gate_threshold = 9999999
        self.assertEqual(draft_job._warranty_confirm_problems(), off,
                         'the Service Job checks stay as they are')
        with self.assertRaises(UserError):
            draft_job.with_user(self.helpdesk_user).action_confirm_job()

    def test_16_settings_have_help_and_gate_is_off_by_default(self):
        arch = etree.fromstring(self.env['res.config.settings'].get_view(view_type='form')['arch'])
        fields_info = self.env['res.config.settings']._fields
        for setting_id in ('warranty_cost_approvers', 'warranty_cost_gate'):
            setting = arch.xpath("//setting[@id='%s']" % setting_id)[0]
            self.assertGreaterEqual(len(setting.get('help')), 30)
            first = next(iter(setting))
            if first.tag == 'field':
                self.assertEqual(fields_info[first.get('name')].help, setting.get('help'))
            else:
                self.assertEqual(setting.get('title'), setting.get('help'))
        company = self.env['res.company'].create({'name': 'Cost New Company'})
        self.assertFalse(company.warranty_cost_gate_enabled)

    def test_14_views_load_for_each_role(self):
        job = self._confirmed_job()
        case = job.warranty_case_id
        for user in (self.helpdesk_user, self.billing, self.finance, self.tech):
            for model, record in (('warranty.case', case), ('warranty.service.job', job)):
                self.env[model].with_user(user).get_view(False, 'form')
        for user in (self.helpdesk_user, self.billing, self.finance):
            self.Line.with_user(user).get_view(False, 'form')
            self.Line.with_user(user).get_view(False, 'list')
        form = Form(self.Line.with_user(self.helpdesk_user))
        form.case_id = case
        form.cost_type = 'travel'
        form.reason = 'Field visit'
        form.estimated_amount = 75
        line = form.save()
        self.assertTrue(line.name.startswith('WCL/'))
        self.assertEqual(line.company_id, case.company_id)
        action = job.with_user(self.helpdesk_user).action_view_warranty_cost_lines()
        self.assertEqual(action['context']['default_job_id'], job.id)

    def test_22_report_identifies_incomplete_labour(self):
        job = self._confirmed_job()
        case = job.warranty_case_id
        self.employee.hourly_cost = 0
        self._timesheet(job.visit_ids[0], 3)
        Report = self.env['warranty.cost.report'].with_user(self.helpdesk_user)
        Report.action_open_warranty_cost_report()
        row = Report.search([('case_id', '=', case.id), ('cost_type', '=', 'labour')])
        self.assertEqual((row.job_id, row.is_incomplete, row.labour_missing_hours,
                          row.actual_amount, row.cost_source),
                         (job, True, 3, 0, 'timesheet'))
        self.assertEqual(Report.search([('is_incomplete', '=', True),
                                        ('case_id', '=', case.id)]), row)
        self.assertTrue(case.warranty_labour_incomplete)

    def test_23_every_cost_type_on_its_incurred_date(self):
        """One case, costs in different months: each stays in its month and all add up to the case
        and job totals, also after reversal and refund. Source records keep their dates."""
        date = fields.Date.to_date
        job = self._confirmed_job()
        case = job.warranty_case_id
        timesheet = self._timesheet(job.visit_ids[0], 2)
        timesheet.date = '2026-02-10'
        second = self._timesheet(job.visit_ids[0], 1)
        second.date = '2026-03-05'
        travel = self._approve(self._line(case, job_id=job.id, cost_type='travel',
                                          actual_amount=60, cost_date='2026-04-01'))
        other = self._approve(self._line(case, job_id=job.id, cost_type='other',
                                         actual_amount=25, cost_date='2026-05-01'))
        repair = self.env['repair.order'].create({
            'product_id': self.covered_part.id, 'warranty_case_id': case.id,
            'partner_id': case.partner_id.id})
        self._approve(self._line(case, cost_type='labour', repair_id=repair.id, actual_amount=70,
                                 cost_date='2026-06-01'))
        bill, bill_line = self._bill(1000, post=False)
        bill.date = '2026-07-01'
        bill.invoice_date = '2026-07-01'
        bill.action_post()
        bill_date = bill.date
        self._approve(self._line(case, cost_type='subcontract', bill_line_id=bill_line.id,
                                 estimated_amount=1000))
        refund = bill._reverse_moves([{'invoice_date': date('2026-08-01'),
                                       'date': date('2026-08-01')}])
        refund.invoice_line_ids.write({'price_unit': 300})
        refund.action_post()
        self.env.invalidate_all()
        Report = self.env['warranty.cost.report'].with_user(self.helpdesk_user)
        Report.action_open_warranty_cost_report()

        def month(start, stop, cost_type):
            return sum(Report.search([('case_id', '=', case.id), ('cost_type', '=', cost_type),
                                      ('cost_date', '>=', start), ('cost_date', '<', stop)]).mapped(
                'actual_amount'))

        self.assertEqual(month('2026-02-01', '2026-03-01', 'labour'), 100, 'timesheet, 2 hours')
        self.assertEqual(month('2026-03-01', '2026-04-01', 'labour'), 50, 'timesheet, 1 hour')
        self.assertEqual(month('2026-06-01', '2026-07-01', 'labour'), 70, 'workshop')
        self.assertEqual(month('2026-04-01', '2026-05-01', 'travel'), 60)
        self.assertEqual(month('2026-05-01', '2026-06-01', 'other'), 25)
        self.assertEqual(month('2026-07-01', '2026-08-01', 'subcontract'), 1000)
        self.assertEqual(month('2026-08-01', '2026-09-01', 'subcontract'), -300)
        rows = Report.search([('case_id', '=', case.id)])
        self.assertEqual(sum(rows.mapped('actual_amount')), case.warranty_total_actual)
        self.assertEqual(case.warranty_total_actual, 150 + 70 + 60 + 25 + 700)
        self.assertEqual(sum(rows.filtered(lambda row: row.job_id == job).mapped('actual_amount')),
                         job.warranty_total_actual)
        # Update Actual Cost moves the line to the date entered, with an audit note.
        with self.assertRaisesRegex(UserError, 'cannot be in the future'):
            other.with_user(self.helpdesk_user)._warranty_record_actual(
                20, 'Later', fields.Date.add(fields.Date.today(), days=2))
        other.with_user(self.helpdesk_user)._warranty_record_actual(20, 'Receipt', '2026-05-20')
        self.assertIn('Receipt', case.message_ids[0].body)
        # A reversal shows on its own date: the original month keeps what happened in it.
        travel.with_user(self.manager)._warranty_reverse('Wrong case')
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_cost_line SET reversed_date = '2026-09-15 08:00:00' "
                            "WHERE id = %s", (travel.id,))
        self.env.invalidate_all()
        Report.action_open_warranty_cost_report()
        self.assertEqual(month('2026-04-01', '2026-05-01', 'travel'), 60)
        self.assertEqual(month('2026-09-01', '2026-10-01', 'travel'), -60)
        self.assertEqual(month('2026-05-01', '2026-06-01', 'other'), 20)
        rows = Report.search([('case_id', '=', case.id)])
        self.assertEqual(sum(rows.mapped('actual_amount')), case.warranty_total_actual)
        self.assertEqual(case.warranty_total_actual, 150 + 70 + 20 + 700)
        self.assertEqual(timesheet.date, date('2026-02-10'), 'source dates are not changed')
        self.assertEqual(bill.date, bill_date)

    def test_24_cost_date_defaults_and_existing_lines_fall_back(self):
        case = self._confirmed_job().warranty_case_id
        line = self._line(case)
        self.assertEqual(line.cost_date, fields.Date.context_today(line), 'a new line')
        self._approve(line)
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_cost_line SET cost_date = NULL WHERE id = %s",
                            (line.id,))
        self.env.invalidate_all()
        self.assertEqual(line._warranty_effective_date(),
                         self.company._warranty_local_date(line.manager_approved_date),
                         'a line from before this field: the approval date')
        with self.assertRaisesRegex(UserError, 'only be changed in Draft'):
            line.with_user(self.helpdesk_user).write({'cost_date': '2026-01-01'})

    def test_25_parts_on_their_stock_move_dates(self):
        """A usage counts on its stock move date; a reversal takes it back on its own date."""
        date = fields.Date.to_date
        self.company.write({'warranty_mrf_dest_location_id': self.default_tech_location.id,
                            'warranty_worksheet_checklist_required': False})
        store = self._user('cost_store',
                           'material_purchase_requisitions.group_purchase_requisition_user')
        store.groups_id |= self.env.ref('stock.group_stock_user')
        stock = self.warehouse.lot_stock_id
        receipt = self.env['stock.move'].create({
            'name': 'Receipt', 'product_id': self.covered_part.id,
            'product_uom': self.covered_part.uom_id.id, 'product_uom_qty': 5, 'price_unit': 500,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': stock.id, 'company_id': self.company.id})
        receipt._action_confirm()
        receipt.quantity = 5
        receipt.picked = True
        receipt._action_done()
        job = self._confirmed_job()
        case = job.warranty_case_id
        mrf = self._approved_mrf(job)
        line = mrf.requisition_line_ids
        mrf.with_user(store).action_warranty_fulfil()
        for picking in self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id),
                                                         ('state', 'not in', ('done', 'cancel'))]):
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.with_user(store).button_validate()
        mrf.with_user(self.tech)._warranty_record_usage([(line, 1, self.env['stock.lot'])])
        entry = line.warranty_consumption_ids.filtered(lambda e: e.kind == 'used').sudo()
        self.assertEqual(line.sudo().actual_cost, 500)
        self.env.flush_all()
        self.env.cr.execute("UPDATE stock_move SET date = '2026-02-20 10:00:00' WHERE id IN %s",
                            (tuple(entry.move_ids.ids),))
        self.env.invalidate_all()
        Report = self.env['warranty.cost.report'].with_user(self.helpdesk_user)
        Report.action_open_warranty_cost_report()
        row = Report.search([('case_id', '=', case.id), ('cost_type', '=', 'parts'),
                             ('actual_amount', '!=', 0)])
        self.assertEqual((row.cost_date, row.actual_amount, row.job_id),
                         (date('2026-02-20'), 500, job))
        rows = Report.search([('case_id', '=', case.id)])
        self.assertEqual(sum(rows.mapped('estimated_amount')), case.warranty_total_estimated)
        self.assertEqual(sum(rows.mapped('approved_amount')), case.warranty_total_approved)
        self.assertEqual(sum(rows.mapped('actual_amount')), case.warranty_total_actual)
        entry.with_user(self.helpdesk_user)._warranty_reverse('Wrong job')
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_mrf_consumption SET reversed_date = "
                            "'2026-03-25 10:00:00' WHERE id = %s", (entry.id,))
        self.env.invalidate_all()
        self.assertEqual(line.sudo().actual_cost, 0)
        Report.action_open_warranty_cost_report()
        rows = Report.search([('case_id', '=', case.id), ('cost_type', '=', 'parts'),
                              ('actual_amount', '!=', 0)])
        self.assertEqual({row.cost_date: row.actual_amount for row in rows},
                         {date('2026-02-20'): 500, date('2026-03-25'): -500})
        self.assertEqual(sum(rows.mapped('actual_amount')), case.warranty_total_actual)


@tagged('post_install', '-at_install', 'warranty_cost')
class TestWarrantyCostSharedVisit(TestSharedVisit):
    """D7: labour of a shared visit is split equally, with no double counting."""

    def _sheet(self, task, hours):
        employee = self.env['hr.employee'].search([('user_id', '=', self.tech.id)], limit=1)
        employee.hourly_cost = 50
        return self.env['account.analytic.line'].create({
            'name': 'Shared work', 'project_id': task.project_id.id, 'task_id': task.id,
            'employee_id': employee.id, 'unit_amount': hours})

    def _cancel(self, job):
        action = job.with_user(self.helpdesk_user).action_open_cancel_wizard()
        wizard = self.env[action['res_model']].with_user(self.helpdesk_user).with_context(
            action['context']).create({'reason': 'Customer cancelled this unit'})
        wizard.action_apply()
        self.assertEqual(job.state, 'cancelled')

    def _shared_jobs(self, count):
        jobs = self.env['warranty.service.job']
        for _index in range(count):
            jobs |= self._job(self._ac_card(), plan=True)
        return jobs, self._share(jobs)

    def test_01_equal_split_adds_up_to_the_visit(self):
        jobs, task = self._shared_jobs(3)
        self._sheet(task, 2)
        shares = [job.warranty_labour_cost for job in jobs.sorted('id')]
        self.assertEqual(shares, [33.33, 33.33, 33.34], 'the last job takes the rounding')
        self.assertEqual(round(sum(shares), 2), 100)
        self.assertAlmostEqual(sum(jobs.mapped('warranty_labour_hours')), 2)
        for job in jobs:
            self.assertEqual(job.warranty_case_id.warranty_labour_cost, job.warranty_labour_cost)

    def test_02_job_cancelled_by_its_normal_workflow_takes_no_share(self):
        jobs, task = self._shared_jobs(3)
        self._sheet(task, 2)
        jobs = jobs.sorted('id')
        self._cancel(jobs[0])
        jobs.invalidate_recordset()
        shares = [job.warranty_labour_cost for job in jobs]
        self.assertEqual(shares, [0, 50, 50], 'the visit total moves to the remaining jobs')
        self.assertAlmostEqual(sum(jobs.mapped('warranty_labour_hours')), 2)
        self.assertEqual(jobs[0].warranty_case_id.warranty_labour_cost, 0)
        self._cancel(jobs[1])
        self._cancel(jobs[2])
        jobs.invalidate_recordset()
        self.assertEqual(round(sum(jobs.mapped('warranty_labour_cost')), 2), 100,
                         'all cancelled: the hours worked stay counted once')

    def test_03_no_duplicate_cost_across_all_sources_and_no_journal_entry(self):
        company = self.company
        manager = self._user('cost_int_manager', 'helpdesk.group_helpdesk_user')
        company.write({'warranty_cost_approver_ids': [(6, 0, manager.ids)],
                       'warranty_cost_finance_threshold': 0})
        service = self.env['product.product'].create({'name': 'Subcontract', 'type': 'service'})
        expense = self.env['account.account'].create({
            'name': 'Subcontract Expense', 'code': 'WCL811', 'account_type': 'expense',
            'company_ids': [(6, 0, company.ids)]})
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'in_invoice', 'partner_id': self.customer.id, 'company_id': company.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'product_id': service.id, 'name': 'Work', 'quantity': 1,
                                         'price_unit': 1000, 'tax_ids': [(5, 0, 0)],
                                         'account_id': expense.id})]})
        move.action_post()
        jobs, task = self._shared_jobs(2)
        jobs = jobs.sorted('id')
        case_a, case_b = jobs.mapped('warranty_case_id')
        repair = self.env['repair.order'].create({
            'product_id': self.product.id, 'warranty_case_id': case_a.id,
            'partner_id': case_a.partner_id.id})
        counts = (self.env['account.move'].search_count([]),
                  self.env['account.move.line'].search_count([]),
                  self.env['stock.valuation.layer'].search_count([]))
        self._sheet(task, 2)
        Line = self.env['warranty.cost.line'].with_user(self.helpdesk_user)
        values = {'reason': 'Integration'}
        rows = Line.create({**values, 'case_id': case_a.id, 'job_id': jobs[0].id,
                            'cost_type': 'travel', 'estimated_amount': 30, 'actual_amount': 30})
        rows |= Line.create({**values, 'case_id': case_a.id, 'repair_id': repair.id,
                             'cost_type': 'labour', 'estimated_amount': 200, 'actual_amount': 200})
        rows |= Line.create({**values, 'case_id': case_b.id, 'cost_type': 'subcontract',
                             'bill_line_id': move.invoice_line_ids.id})
        rows |= Line.create({**values, 'case_id': case_a.id, 'job_id': jobs[0].id,
                             'cost_type': 'labour', 'estimated_amount': 300})
        for row in rows:
            row.action_submit()
            row.with_user(manager).action_approve()
        self.env.invalidate_all()
        self.assertEqual(jobs[0].warranty_total_actual, 80, 'its share of 50 and travel 30')
        self.assertEqual(jobs[1].warranty_total_actual, 50, 'its share only')
        self.assertEqual(case_a.warranty_total_actual, 280, 'share 50, travel 30, workshop 200')
        self.assertEqual(case_b.warranty_total_actual, 1050, 'share 50, subcontract 1,000')
        self.assertEqual(case_a.warranty_total_actual + case_b.warranty_total_actual,
                         100 + 30 + 200 + 1000, 'every source counted exactly once')
        self.assertEqual(case_a.warranty_total_expected, 530,
                         'labour estimate 300 replaces its timesheets, then travel and workshop')
        self.assertEqual((self.env['account.move'].search_count([]),
                          self.env['account.move.line'].search_count([]),
                          self.env['stock.valuation.layer'].search_count([])), counts,
                         'no journal entry, journal item or valuation layer')
        self.assertEqual(move.state, 'posted')
        # Part 8.2: the report adds up to the same totals, per job and per case.
        Report = self.env['warranty.cost.report'].with_user(self.helpdesk_user)
        Report.action_open_warranty_cost_report()
        reported = Report.search([('case_id', 'in', (case_a | case_b).ids)])
        for case in (case_a, case_b):
            case_rows = reported.filtered(lambda row: row.case_id == case)
            for column, total in (('estimated_amount', case.warranty_total_estimated),
                                  ('approved_amount', case.warranty_total_approved),
                                  ('actual_amount', case.warranty_total_actual),
                                  ('net_amount', case.warranty_net_cost)):
                self.assertAlmostEqual(sum(case_rows.mapped(column)), total, msg=column)
        for job in jobs:
            job_rows = reported.filtered(lambda row: row.job_id == job)
            for column, total in (('estimated_amount', job.warranty_total_estimated),
                                  ('approved_amount', job.warranty_total_approved),
                                  ('actual_amount', job.warranty_total_actual)):
                self.assertAlmostEqual(sum(job_rows.mapped(column)), total, msg=column)
            self.assertEqual(job_rows.technician_id, job.main_technician_id)
        self.assertEqual(sum(reported.mapped('actual_amount')), 1330, 'every source once')
        manual = reported.filtered('is_manual')
        self.assertEqual(sum(manual.filtered(lambda row: row.cost_type == 'labour').mapped(
            'actual_amount')), 200, 'workshop labour is identified as manual')
        self.assertEqual(case_a.warranty_labour_manual_cost, 200)
        self.assertEqual(sum(reported.filtered(lambda row: row.cost_source == 'document').mapped(
            'actual_amount')), 1000)
        # A reversed line leaves the totals and the report, and keeps its history.
        travel = rows.filtered(lambda row: row.cost_type == 'travel')
        travel.with_user(manager)._warranty_reverse('Wrong job')
        self.env.invalidate_all()
        Report.action_open_warranty_cost_report()
        reported = Report.search([('case_id', '=', case_a.id)])
        self.assertEqual(case_a.warranty_total_actual, 250)
        self.assertEqual(sum(reported.mapped('actual_amount')), 250)
        self.assertFalse(reported.filtered(lambda row: row.cost_type == 'travel'))
        self.assertEqual(travel.actual_amount, 30)
        # Technicians read no cost at all, also not through the report.
        with self.assertRaises(AccessError):
            Report.with_user(self.tech).action_open_warranty_cost_report()
        self.assertEqual((self.env['account.move'].search_count([]),
                          self.env['account.move.line'].search_count([]),
                          self.env['stock.valuation.layer'].search_count([])), counts,
                         'the report posts nothing')
