from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_inspection_fee_adjustment import InspectionFlowCommon


@tagged('post_install', '-at_install', 'warranty_cost')
class TestWarrantyCaseClosure(InspectionFlowCommon):
    """Part 8.5: Close Case, its blockers per workflow, rights and audit."""

    def _close(self, case, user=None):
        return case.with_user(user or self.helpdesk_user).action_warranty_close_case()

    def _force_state(self, case, state='completed'):
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_case SET state = %s WHERE id = %s", (state, case.id))
        self.env.invalidate_all()

    def _warranty_case(self):
        """A plain warranty case completed through its service job."""
        self.team.warranty_inspection_required = False
        case = self._approved(services=self.env['warranty.service.entitlement'],
                              ticket=self._ticket(warranty_product_id=self.product.id))
        job = self._prepare(case)
        task = self._start_visit(job)
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual(case.state, 'completed')
        self.team.warranty_inspection_required = True
        return case, job

    def _blank_approved(self):
        self.team.warranty_inspection_required = False
        case = self._approved(ticket=self._ticket(warranty_product_id=self.product.id))
        self.team.warranty_inspection_required = True
        return case

    def _blank_completed(self):
        """A completed case with no operations, to test one blocker at a time."""
        case = self._blank_approved()
        self._force_state(case)
        self.assertFalse(case._warranty_close_problems())
        return case

    def _repair_flow(self, invoice_inspection=True, amount=5000.0):
        """Customer went ahead: repair confirmed, its job done, repair invoice posted."""
        case, order, repair = self._inspection()
        invoice = self._posted_invoice(order) if invoice_inspection else False
        self._price(repair, amount)
        return case, order, repair, invoice

    def _finish_repair(self, case, repair):
        repair.action_confirm()
        job = self.env['warranty.service.job'].search(
            [('warranty_case_id', '=', case.id), ('job_type', '=', 'chargeable_repair')])
        task = self._start_visit(job)
        task.with_user(self.tech).action_warranty_complete_visit()
        self.assertEqual((case.state, case.warranty_chargeable_outcome),
                         ('completed', 'repair_completed'))
        return job

    # ------------------------------------------------------------------ 1, 12, audit
    def test_01_completed_warranty_case_closes_once(self):
        case, _job = self._warranty_case()
        messages = len(case.message_ids)
        self.assertIs(self._close(case), True)
        self.assertEqual((case.state, case.warranty_case_closed_by_id), ('closed', self.helpdesk_user))
        self.assertTrue(case.warranty_case_closed_date)
        self.assertIn('closed by', case.message_ids[0].body)
        closed_messages = len(case.message_ids)
        self.assertGreater(closed_messages, messages)
        with self.assertRaisesRegex(UserError, 'already closed'):
            self._close(case)
        case.invalidate_recordset(['message_ids'])
        self.assertEqual(len(case.message_ids), closed_messages, 'no duplicate event')

    def test_02_only_a_completed_case_closes(self):
        self.team.warranty_inspection_required = False
        case = self._approved(ticket=self._ticket(warranty_product_id=self.product.id))
        with self.assertRaisesRegex(UserError, 'Only a Completed warranty case'):
            self._close(case)
        self.assertEqual(case.state, 'approved')

    # ------------------------------------------------------------------ 2 to 5: pending work
    def test_03_pending_service_job_and_visit_block(self):
        case, job = self._warranty_case()
        self.env.cr.execute("UPDATE warranty_service_job SET state = 'in_progress' WHERE id = %s",
                            (job.id,))
        self.env.invalidate_all()
        with self.assertRaisesRegex(UserError, 'Service job .* is not finished'):
            self._close(case)
        self.env.cr.execute("UPDATE warranty_service_job SET state = 'completed' WHERE id = %s",
                            (job.id,))
        self.env.cr.execute("UPDATE project_task SET state = '01_in_progress' WHERE id IN %s",
                            (tuple(job.visit_ids.ids),))
        self.env.invalidate_all()
        with self.assertRaisesRegex(UserError, 'Field Service visit .* is not finished'):
            self._close(case)
        self.assertEqual(case.state, 'completed')

    def test_04_pending_material_request_blocks(self):
        case = self._blank_approved()
        employee = self.env['hr.employee'].create({
            'name': 'Closure Employee',
            'department_id': self.env['hr.department'].create({'name': 'Closure Dept'}).id})
        request = self.env['material.purchase.requisition'].create({
            'employee_id': employee.id, 'department_id': employee.department_id.id,
            'warranty_case_id': case.id,
            'requisition_line_ids': [(0, 0, {'product_id': self.repair_product.id, 'qty': 1,
                                             'description': 'Part',
                                             'uom': self.repair_product.uom_id.id})]})
        self._force_state(case)
        with self.assertRaisesRegex(UserError, 'Material Requests are not closed'):
            self._close(case)
        self.assertEqual(case.state, 'completed')
        request.sudo().write({'state': 'cancel'})
        case.invalidate_recordset()
        self._close(case)
        self.assertEqual(case.state, 'closed', 'a cancelled request does not block')

    def test_05_pending_repair_order_blocks(self):
        case = self._blank_approved()
        repair = self.env['repair.order'].create({
            'product_id': self.product.id, 'warranty_case_id': case.id,
            'partner_id': case.partner_id.id})
        self._force_state(case)
        with self.assertRaisesRegex(UserError, 'Repair Order .* is not finished'):
            self._close(case)
        self.env.flush_all()
        self.env.cr.execute("UPDATE repair_order SET state = 'done' WHERE id = %s", (repair.id,))
        self.env.invalidate_all()
        with self.assertRaisesRegex(UserError, 'machine has not been returned'):
            self._close(case)
        self.env.cr.execute("UPDATE repair_order SET state = 'cancel' WHERE id = %s", (repair.id,))
        self.env.invalidate_all()
        self._close(case)
        self.assertEqual(case.state, 'closed', 'a cancelled Repair Order does not block')

    def test_06_pending_replacement_blocks(self):
        case = self._blank_completed()
        replacement = self.env['warranty.replacement'].create({
            'warranty_case_id': case.id, 'replacement_type': 'component',
            'reason': 'pcb_failure', 'date_policy': 'continue_original',
            'component_line_ids': [(0, 0, {'product_id': self.repair_product.id, 'qty': 1})]})
        with self.assertRaisesRegex(UserError, 'Replacement .* is not finished'):
            self._close(case)
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_replacement SET state = 'done' WHERE id = %s",
                            (replacement.id,))
        self.env.invalidate_all()
        self._close(case)
        self.assertEqual(case.state, 'closed')

    def test_07_pending_cost_approval_blocks(self):
        case = self._blank_completed()
        line = self.env['warranty.cost.line'].create({
            'case_id': case.id, 'cost_type': 'travel', 'reason': 'Trip', 'estimated_amount': 50})
        with self.assertRaisesRegex(UserError, 'waiting for submission or approval'):
            self._close(case)
        line.unlink()
        self._close(case)
        self.assertEqual(case.state, 'closed')

    def test_08_all_blockers_are_listed_together(self):
        case = self._blank_approved()
        self.env['repair.order'].create({'product_id': self.product.id, 'warranty_case_id': case.id,
                                         'partner_id': case.partner_id.id})
        self._force_state(case)
        self.env['warranty.cost.line'].create({'case_id': case.id, 'cost_type': 'travel',
                                               'reason': 'Trip', 'estimated_amount': 50})
        problems = case._warranty_close_problems()
        self.assertEqual(len(problems), 2, problems)

    # ------------------------------------------------------------------ 6, 7: declined
    def test_09_declined_repair_closes_once_the_fee_is_billed(self):
        case, order, repair = self._inspection()
        case.with_user(self.helpdesk_user)._warranty_decline_repair('Too expensive')
        self.assertEqual((case.state, case.warranty_chargeable_outcome),
                         ('completed', 'repair_declined'))
        self.assertEqual(repair.state, 'cancel')
        with self.assertRaisesRegex(UserError, 'not fully invoiced and posted'):
            self._close(case)
        draft = order._create_invoices()
        with self.assertRaisesRegex(UserError, 'not fully invoiced and posted'):
            self._close(case)
        draft.action_post()
        moves = self.env['account.move'].search_count([])
        self._close(case)
        self.assertEqual(case.state, 'closed')
        self.assertFalse(case.warranty_inspection_credit_note_ids, 'the fee stays')
        self.assertFalse(case.warranty_inspection_deduction_line_ids)
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertEqual((draft.state, draft.amount_total), ('posted', 1725))

    # ------------------------------------------------------------------ 8, 9: repair completed
    def test_10_credit_note_route_blocks_until_posted(self):
        case, _order, repair, _invoice = self._repair_flow()
        self._finish_repair(case, repair)
        final = repair._create_invoices()
        with self.assertRaisesRegex(UserError, 'not fully invoiced and posted'):
            self._close(case)
        final.action_post()
        with self.assertRaisesRegex(UserError, 'Apply the inspection fee adjustment'):
            self._close(case)
        self._apply(case)
        with self.assertRaisesRegex(UserError, 'must be posted by Accounting'):
            self._close(case)
        note = case.warranty_inspection_credit_note_ids
        note.action_post()
        counts = self._counts()
        self._close(case)
        self.assertEqual(case.state, 'closed')
        self.assertEqual(self._counts(), counts, 'no posting, payment or reconciliation')
        self.assertEqual(final.payment_state, 'not_paid', 'payment is not required')
        self.assertFalse(case.with_user(self.billing).warranty_inspection_can_adjust)

    def test_11_quotation_route_needs_the_inspection_invoice(self):
        case, order, repair, _invoice = self._repair_flow(invoice_inspection=False)
        self._apply(case, self.approver)
        self._finish_repair(case, repair)
        repair._create_invoices().action_post()
        with self.assertRaisesRegex(UserError, r'Order %s is not fully invoiced' % order.name):
            self._close(case)
        self._posted_invoice(order)
        self._close(case)
        self.assertEqual(case.state, 'closed')
        self.assertEqual(repair.invoice_ids.filtered(lambda m: m.state == 'posted').amount_total, 4025)

    def test_12_fee_above_repair_stays_pending_finance(self):
        case, _order, repair, _invoice = self._repair_flow(amount=1000)
        self._finish_repair(case, repair)
        repair._create_invoices().action_post()
        with self.assertRaisesRegex(UserError, r'above the repair total.*\(F5\)'):
            self._close(case)
        self.assertEqual(case.state, 'completed')

    def test_13_unconfirmed_chargeable_quotation_blocks(self):
        case = self._blank_completed()
        order = self.env['sale.order'].create({'partner_id': case.partner_id.id,
                                               'warranty_case_id': case.id})
        order.sudo().warranty_chargeable_purpose = 'repair'
        with self.assertRaisesRegex(UserError, 'must be confirmed or cancelled'):
            self._close(case)
        order.action_cancel()
        self._close(case)
        self.assertEqual(case.state, 'closed')

    # ------------------------------------------------------------------ 10: vendor claims
    def test_14_open_vendor_claim_does_not_block(self):
        case = self._blank_completed()
        vendor = self.env['res.partner'].create({'name': 'Closure Vendor'})
        self.company.warranty_vendor_claim_enabled = True
        claim = self.env['warranty.vendor.claim'].create({'case_id': case.id,
                                                          'partner_id': vendor.id})
        self.assertEqual(claim.state, 'draft')
        self._close(case)
        self.assertEqual((case.state, claim.state), ('closed', 'draft'), 'the claim stays open')

    # ------------------------------------------------------------------ 11: rights
    def test_15_rights(self):
        case = self._blank_completed()
        for user in (self.tech, self.billing):
            with self.assertRaises(AccessError):
                self._close(case, user)
        self.assertEqual(case.state, 'completed')
        for vals, message in (({'state': 'closed'}, 'closed with Close Case'),
                              ({'warranty_case_closed_date': fields.Datetime.now()},
                               'set by Close Case')):
            with self.assertRaisesRegex(UserError, message):
                case.with_user(self.helpdesk_user).write(vals)
            with self.assertRaisesRegex(UserError, message):
                case.with_user(self.helpdesk_user).sudo().write(vals)
        with self.assertRaisesRegex(UserError, 'closed with Close Case'):
            case.with_user(self.helpdesk_user).with_context(
                warranty_case_close_marker='marker').write({'state': 'closed'})
        self.assertEqual(case.state, 'completed')
        self._close(case)
        with self.assertRaisesRegex(UserError, 'cannot change status'):
            case.with_user(self.helpdesk_user).sudo().write({'state': 'completed'})
        self.assertEqual(case.state, 'closed')

    def test_16_company_isolation(self):
        case = self._blank_completed()
        other = self.env['res.company'].create({'name': 'Close Co B'})
        user = self.env['res.users'].create({
            'name': 'Close Other', 'login': 'close_other', 'company_id': other.id,
            'company_ids': [(6, 0, other.ids)],
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('helpdesk.group_helpdesk_user')).ids)]})
        with self.assertRaises(AccessError):
            self._close(case, user)
        self.assertEqual(case.state, 'completed')

    def test_17_form_button(self):
        arch = self.env['warranty.case'].with_user(self.helpdesk_user).get_view(False, 'form')['arch']
        self.assertIn('action_warranty_close_case', arch)
        arch = self.env['warranty.case'].with_user(self.billing).get_view(False, 'form')['arch']
        self.assertNotIn('action_warranty_close_case', arch)
