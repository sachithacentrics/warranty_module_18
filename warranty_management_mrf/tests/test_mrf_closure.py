import importlib.util
import os
from contextlib import contextmanager

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.modules.module import get_module_path
from odoo.tests import tagged

from .common import WarrantyMrfCommon


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyMrfClosure(WarrantyMrfCommon):
    """Phase 5.9 - closure, audit trail and reporting (design
    part5_9_closure_audit_reporting_design.md rev. 2, K-1 - K-7, reports A - D, T9.1 - T9.12)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Product = cls.env['product.product']
        Partner = cls.env['res.partner']
        cls.manufacturer = Partner.create({'name': 'CoolMaker Manufacturing', 'is_company': True})
        cls.vendor = Partner.create({'name': 'Cool Parts Ltd', 'is_company': True})
        cls.recovery_account = cls.env['account.account'].create({
            'name': 'Warranty Claim Recovery', 'code': 'WRC959', 'account_type': 'income_other',
            'company_ids': [(6, 0, cls.company.ids)]})
        cls.claim_approver = cls._user('mrf_k9_approver')
        cls.finance = cls._user('mrf_k9_finance', 'account.group_account_readonly')
        cls.coordinator = cls._user('mrf_k9_coordinator', 'helpdesk.group_helpdesk_user')
        cls.coordinator.groups_id |= cls.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        cls.store = cls._user('mrf_k9_store',
                              'material_purchase_requisitions.group_purchase_requisition_user')
        cls.store.groups_id |= cls.env.ref('stock.group_stock_user') | cls.env.ref(
            'purchase.group_purchase_user')
        cls.manager = cls._user('mrf_k9_manager',
                                'material_purchase_requisitions.group_purchase_requisition_manager')
        cls.manager2 = cls._user('mrf_k9_manager2',
                                 'material_purchase_requisitions.group_purchase_requisition_manager')
        cls.accountant = cls._user('mrf_k9_accountant', 'account.group_account_invoice')
        cls.company.write({
            'warranty_mrf_approval_matrix': True,
            'warranty_mrf_dest_location_id': cls.default_tech_location.id,
            'warranty_worksheet_checklist_required': False,
            'warranty_vendor_claim_enabled': True,
            'warranty_claim_approver_ids': [(6, 0, cls.claim_approver.ids)],
            'warranty_claim_finance_approver_ids': [(6, 0, cls.finance.ids)],
            'warranty_claim_finance_threshold': 100000,
            'warranty_claim_evidence_required': False,
            'warranty_claim_recovery_account_id': cls.recovery_account.id,
            'warranty_mrf_close_requires_invoice': False,
        })
        cls.env['warranty.mrf.approval.rule'].create({
            'name': 'All free (5.9 test)', 'company_id': cls.company.id, 'no_approval': True})
        cls.filter = Product.create({
            'name': 'Air Filter', 'is_storable': True, 'type': 'consu', 'standard_price': 500,
            'warranty_vendor_claimable': True, 'warranty_claim_partner_id': cls.manufacturer.id})
        cls.valve = Product.create({
            'name': 'Expansion Valve', 'is_storable': True, 'type': 'consu',
            'standard_price': 2000, 'warranty_vendor_claimable': True,
            'warranty_claim_partner_id': cls.manufacturer.id,
            'seller_ids': [(0, 0, {'partner_id': cls.vendor.id, 'price': 2000})]})
        cls.oil = Product.create({
            'name': 'Compressor Oil', 'is_storable': True, 'type': 'consu',
            'standard_price': 1000, 'list_price': 4000, 'invoice_policy': 'delivery',
            'taxes_id': [(5, 0, 0)]})
        cls.policy.covered_item_ids |= cls.env['warranty.coverage.item'].create([
            {'name': product.name, 'product_id': product.id}
            for product in (cls.filter, cls.valve)])
        cls.item_gas.product_id = cls.oil
        cls.helpdesk_user.groups_id |= cls.env.ref('sales_team.group_sale_salesman')
        cls.stock = cls.warehouse.lot_stock_id
        cls.Lot = cls.env['stock.lot']
        cls.Claim = cls.env['warranty.vendor.claim']

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def assertRaisesRegex(self, exception, regex):
        with super().assertRaisesRegex(exception, regex):
            with self.env.cr.savepoint():
                yield
        self.env.invalidate_all(flush=False)

    def _receive(self, product, qty, price):
        move = self.env['stock.move'].create({
            'name': 'Receipt %s' % product.name, 'product_id': product.id,
            'product_uom': product.uom_id.id, 'product_uom_qty': qty, 'price_unit': price,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock.id, 'company_id': self.company.id})
        move._action_confirm()
        move.quantity = qty
        move.picked = True
        move._action_done()

    def _mrf(self, lines, job=None):
        record = job or self._confirmed_job()
        action = record.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {
                'product_id': product.id, 'description': product.name, 'qty': qty,
                'uom': product.uom_id.id}) for product, qty in lines]})
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual(mrf.state, 'approve')
        return mrf

    def _line(self, mrf, product):
        return mrf.requisition_line_ids.filtered(lambda line: line.product_id == product)

    def _validate(self, picking, user=None):
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        result = picking.with_user(user or self.store).button_validate()
        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            self.env['stock.backorder.confirmation'].with_context(result['context']) \
                .create({}).process()

    def _open_pickings(self, mrf):
        return self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id),
                                                 ('state', 'not in', ('done', 'cancel'))])

    def _issue(self, mrf):
        mrf.with_user(self.store).action_warranty_fulfil()
        for picking in self._open_pickings(mrf):
            self._validate(picking)
        return mrf

    def _use(self, mrf, product, qty):
        mrf.with_user(self.tech)._warranty_record_usage(
            [(self._line(mrf, product).with_user(self.tech), qty, self.Lot)])

    def _consumed(self, lines, job=None):
        mrf = self._issue(self._mrf(lines, job=job))
        for product, qty in lines:
            self._use(mrf, product, qty)
        return mrf

    def _claim(self, mrf, rows):
        """Answered claim (all accepted) of rows {product: qty} of the request."""
        action = mrf.with_user(self.coordinator).action_create_vendor_claim()
        wizard = self.env[action['res_model']].with_user(self.coordinator).browse(
            action['res_id'])
        for row in wizard.line_ids:
            qty = rows.get(row.product_id, 0.0)
            row.write({'selected': bool(qty), 'qty': qty})
        wizard.partner_id = False
        wizard._propose_partner()
        wizard.failure_description = 'Failed'
        claim = self.Claim.with_user(self.coordinator).browse(wizard.action_apply()['res_id'])
        claim.action_submit()
        claim.with_user(self.claim_approver).action_approve()
        claim.action_mark_sent()
        claim._warranty_record_response({line: (line.claimed_amount, 'ok')
                                         for line in claim.line_ids}, reference='V-9')
        return claim

    def _close(self, mrf, user=None):
        mrf.with_user(user or self.coordinator)._warranty_close()

    # ------------------------------------------------------------------ T9.1 / K-1 / K-2
    def test_01_reconciled_vs_closed_and_close_checks(self):
        """Close only without operational obligations: issue / RFQ / open picking / open return /
        unreconciled quantities listed; Reconciled -> Closed with Closed By / On and notes."""
        self._receive(self.filter, 3, 500)
        job = self._confirmed_job()
        mrf = self._mrf([(self.filter, 3), (self.valve, 1)], job=job)
        problems = ' '.join(mrf._warranty_close_problems())
        self.assertIn('Expansion Valve', problems)
        mrf.with_user(self.store).action_warranty_fulfil()
        problems = ' '.join(mrf._warranty_close_problems())
        self.assertIn('stock movements not done', problems)
        self.assertIn('requests for quotation', problems)
        with self.assertRaisesRegex(UserError, 'cannot be closed'):
            self._close(mrf)
        for picking in self._open_pickings(mrf):
            self._validate(picking)
        order = mrf.sudo().purchase_order_ids
        order.button_confirm()
        self.assertIn('purchase orders not fully received',
                      ' '.join(mrf._warranty_close_problems()))
        self._validate(order.picking_ids)
        self._issue(mrf)
        self._use(mrf, self.filter, 2)
        self._use(mrf, self.valve, 1)
        line = self._line(mrf, self.filter)
        mrf.with_user(self.tech)._warranty_return_unused([(line.with_user(self.tech), 1.0,
                                                           self.Lot)])
        self.assertEqual(mrf.warranty_mrf_status, 'returned')
        self.assertIn('return transfer', ' '.join(mrf._warranty_close_problems()))
        returns = line.sudo().warranty_consumption_ids.filtered(
            lambda e: e.kind == 'unused_return').picking_id
        self._validate(returns)
        mrf.invalidate_recordset()
        self.assertEqual((mrf.warranty_mrf_status, mrf._warranty_close_problems(),
                          mrf.warranty_closed), ('reconciled', [], False))
        with self.assertRaises(AccessError):
            self._close(mrf, self.tech)
        self._close(mrf)
        self.assertEqual((mrf.warranty_mrf_status, mrf.warranty_closed,
                          mrf.warranty_closed_by_id), ('closed', True, self.coordinator))
        self.assertTrue(mrf.warranty_closed_date)
        self.assertTrue(any('closed by' in (m.body or '') for m in job.message_ids))
        with self.assertRaisesRegex(UserError, 'Closure fields'):
            mrf.with_user(self.coordinator).write({'warranty_closed': False})

    # ------------------------------------------------------------------ K-2 invoicing
    def test_02_customer_paid_invoicing_policy(self):
        """Customer-paid parts: operational closure without invoice by default (Pending
        Invoicing shown separately); strict company policy requires posted invoices; closure
        never creates invoices."""
        self._receive(self.oil, 3, 1000)
        job = self._confirmed_job()
        mrf = self._mrf([(self.oil, 2)], job=job)
        order = self.env['sale.order'].browse(
            mrf.with_user(self.helpdesk_user).action_create_parts_quotation()['res_id'])
        self.assertIn('To Quote', ' '.join(mrf._warranty_close_problems()) + 'To Quote')
        order.action_confirm()
        self.assertTrue(mrf._warranty_close_problems())
        self._validate(order.picking_ids)
        line = self._line(mrf, self.oil)
        mrf.with_user(self.tech)._warranty_record_usage([(line.with_user(self.tech), 2.0,
                                                          self.Lot)])
        self.assertEqual(mrf.warranty_invoice_status, 'pending')
        invoices = self.env['account.move'].search_count([])
        self.company.warranty_mrf_close_requires_invoice = True
        self.assertIn('not fully invoiced', ' '.join(mrf._warranty_close_problems()))
        invoice = order._create_invoices()
        self.assertIn('not fully invoiced', ' '.join(mrf._warranty_close_problems()),
                      'a draft invoice is not enough')
        invoice.action_post()
        mrf.invalidate_recordset()
        self.assertEqual((mrf.warranty_invoice_status, mrf._warranty_close_problems()),
                         ('invoiced', []))
        invoices = self.env['account.move'].search_count([])
        self._close(mrf)
        self.assertEqual(self.env['account.move'].search_count([]), invoices)
        # Default policy: closable while invoicing is still pending.
        self.company.warranty_mrf_close_requires_invoice = False
        mrf2 = self._mrf([(self.oil, 1)])
        order2 = self.env['sale.order'].browse(
            mrf2.with_user(self.helpdesk_user).action_create_parts_quotation()['res_id'])
        order2.action_confirm()
        self._validate(order2.picking_ids)
        mrf2.with_user(self.tech)._warranty_record_usage(
            [(self._line(mrf2, self.oil).with_user(self.tech), 1.0, self.Lot)])
        self.assertEqual(mrf2.warranty_invoice_status, 'pending')
        self._close(mrf2)
        self.assertTrue(mrf2.warranty_closed)

    # ------------------------------------------------------------------ T9.2 / T9.3 / K-3 / K-4
    def test_03_freeze_and_claims_continue(self):
        """A closed request refuses material, coverage, issue, quotation, cancellation and edits
        (also API); open vendor claims never block closure and claims / credit notes continue
        after it."""
        self._receive(self.filter, 5, 500)
        mrf = self._consumed([(self.filter, 2)])
        claim = self._claim(mrf, {self.filter: 1})
        self.assertEqual(claim.state, 'answered')
        self._close(mrf)
        line = self._line(mrf, self.filter)
        entry = line.sudo().warranty_consumption_ids
        with self.assertRaisesRegex(UserError, 'closed'):
            self._use(mrf, self.filter, 1)
        with self.assertRaisesRegex(UserError, 'closed'):
            entry.with_user(self.coordinator)._warranty_reverse('x')
        with self.assertRaisesRegex(UserError, 'closed'):
            mrf.with_user(self.tech)._warranty_return_unused([(line.with_user(self.tech), 1.0,
                                                               self.Lot)])
        with self.assertRaisesRegex(UserError, 'closed'):
            mrf.with_user(self.store)._warranty_cancel_remaining([(line, 1.0, self.Lot)], 'x')
        with self.assertRaisesRegex(UserError, 'closed'):
            mrf.with_user(self.store).action_warranty_fulfil()
        with self.assertRaisesRegex(UserError, 'closed'):
            mrf.with_user(self.helpdesk_user).action_create_parts_quotation()
        with self.assertRaisesRegex(UserError, 'closed'):
            mrf.with_user(self.approver_b)._warranty_decide_coverage(line, 'goodwill', 'x')
        with self.assertRaisesRegex(UserError, 'closed'):
            mrf.with_user(self.coordinator).action_cancel()
        with self.assertRaisesRegex(UserError, 'closed'):
            mrf.with_user(self.store).write({'reason': 'changed'})
        with self.assertRaisesRegex(UserError, 'closed'):
            line.with_user(self.store).write({'description': 'changed'})
        # Claims and accounting continue after the closure.
        claim2 = self._claim(mrf, {self.filter: 1})
        move = self.env['account.move'].browse(
            claim.with_user(self.accountant).action_create_credit_note()['res_id'])
        move.invoice_date = fields.Date.today()
        move.with_user(self.accountant).action_post()
        self.assertEqual((claim.recovered_amount, claim2.state, mrf.warranty_mrf_status),
                         (500, 'answered', 'closed'))

    # ------------------------------------------------------------------ T9.4 / K-5
    def test_04_reopen(self):
        """Requisition Managers reopen with a reason, never the closer; administrator exception
        with reason; history kept; the request can be corrected and closed again."""
        self._receive(self.filter, 5, 500)
        mrf = self._consumed([(self.filter, 2)])
        self.manager.groups_id |= self.env.ref('helpdesk.group_helpdesk_user')
        self._close(mrf, self.manager)
        self.assertTrue(mrf.with_user(self.manager2).can_warranty_reopen)
        self.assertFalse(mrf.with_user(self.manager).can_warranty_reopen)
        with self.assertRaises(AccessError):
            mrf.with_user(self.coordinator)._warranty_reopen('Correction')
        with self.assertRaises(AccessError):
            mrf.with_user(self.manager)._warranty_reopen('Correction')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            mrf.with_user(self.manager2)._warranty_reopen(' ')
        mrf.with_user(self.manager2)._warranty_reopen('Wrong quantity recorded')
        self.assertEqual((mrf.warranty_closed, mrf.warranty_mrf_status,
                          mrf.warranty_reopened_by_id, mrf.warranty_reopen_reason,
                          mrf.warranty_closed_by_id),
                         (False, 'reconciled', self.manager2, 'Wrong quantity recorded',
                          self.manager))
        self.assertTrue(any('reopened by' in (m.body or '') for m in mrf.message_ids))
        entry = self._line(mrf, self.filter).sudo().warranty_consumption_ids
        entry.with_user(self.coordinator)._warranty_reverse('Correction after reopening')
        self._use(mrf, self.filter, 2)
        # Administrator exception (the closer is the administrator).
        admin = self.env.ref('base.user_admin')
        self._close(mrf, admin)
        with self.assertRaises(AccessError):
            mrf.with_user(self.manager2)._warranty_reopen('x', admin_exception=True)
        mrf.with_user(admin)._warranty_reopen('Data recovery', admin_exception=True)
        self.assertTrue(mrf.warranty_reopen_admin_exception)
        self.assertTrue(any('administrator exception' in (m.body or '')
                            for m in mrf.message_ids))

    # ------------------------------------------------------------------ T9.5 / K-6 / batch
    def test_05_batch_close_and_case_guard(self):
        """Close Material Requests on a job / case lists every request with its validation
        result, closes only the selected eligible ones; a case cannot be Closed while a
        request is not closed (claims never block)."""
        self._receive(self.filter, 6, 500)
        job = self._confirmed_job()
        ready = self._consumed([(self.filter, 2)], job=job)
        open_mrf = self._issue(self._mrf([(self.filter, 2)], job=job))
        self._claim(ready, {self.filter: 1})
        case = job.warranty_case_id
        with self.assertRaisesRegex(UserError, 'Ready to close'):
            case.sudo().write({'state': 'closed'})
        with self.assertRaisesRegex(UserError, 'Open obligations'):
            case.sudo().write({'state': 'closed'})
        action = case.with_user(self.coordinator).action_warranty_close_requests()
        wizard = self.env[action['res_model']].with_user(self.coordinator).browse(
            action['res_id'])
        rows = {row.requisition_id: row for row in wizard.line_ids}
        self.assertEqual((rows[ready].eligible, rows[ready].selected,
                          rows[open_mrf].eligible, rows[open_mrf].selected),
                         (True, True, False, False))
        self.assertIn('issued but not recorded', rows[open_mrf].problems)
        rows[open_mrf].selected = True
        with self.assertRaisesRegex(UserError, 'Only requests without blockers'):
            wizard.action_apply()
        rows[open_mrf].selected = False
        wizard.action_apply()
        self.assertEqual((ready.warranty_closed, open_mrf.warranty_closed), (True, False))
        self._use(open_mrf, self.filter, 2)
        self.assertTrue(job.with_user(self.coordinator).warranty_has_open_requests)
        job_action = job.with_user(self.coordinator).action_warranty_close_requests()
        self.env[job_action['res_model']].with_user(self.coordinator).browse(
            job_action['res_id']).action_apply()
        self.assertTrue(open_mrf.warranty_closed)
        # All closed: the button is hidden; a stale screen gets the message, nothing changes.
        self.assertFalse(job.with_user(self.coordinator).warranty_has_open_requests)
        self.assertFalse(case.with_user(self.coordinator).warranty_has_open_requests)
        with self.assertRaisesRegex(UserError, 'no open warranty Material Request to close'):
            job.with_user(self.coordinator).action_warranty_close_requests()
        self.assertTrue(ready.warranty_closed and open_mrf.warranty_closed)
        case.sudo().write({'state': 'closed'})
        self.assertEqual(case.state, 'closed')

    # ------------------------------------------------------------------ T9.7 - T9.9 reports
    def test_06_reports_totals_and_recovery_allocation(self):
        """Report A = form totals per request; report B per claim line (explicit allocations):
        draft credit notes not recovered, settled separate, unassigned allocations shown as
        claim-level rows; report D recovery columns; job figures from the job's own claim lines
        (a claim over two jobs is not counted twice)."""
        self._receive(self.filter, 10, 500)
        self._receive(self.valve, 2, 2000)
        job1, job2 = self._confirmed_job(), self._confirmed_job()
        mrf1 = self._consumed([(self.filter, 2), (self.valve, 1)], job=job1)
        mrf2 = self._consumed([(self.filter, 1)], job=job2)
        claim = self._claim(mrf1, {self.filter: 2, self.valve: 1})
        A = self.env['warranty.mrf.approval.cost.report'].with_user(self.coordinator)
        row = A.search([('requisition_id', '=', mrf1.id)])
        mrf1.invalidate_recordset()
        self.assertEqual((row.estimated_cost, row.actual_cost, row.warranty_cost,
                          row.covered_actual, row.vendor_claimed, row.vendor_accepted,
                          row.vendor_recovered, row.warranty_mrf_status),
                         (mrf1.warranty_estimated_cost, 3000, 3000, 3000, 3000, 3000, 0,
                          'reconciled'))
        move = self.env['account.move'].browse(
            claim.with_user(self.accountant).action_create_credit_note()['res_id'])
        self.assertEqual(len(claim.recovery_ids), 2, 'one explicit allocation per claim line')
        self.assertEqual(claim.recovery_ids.claim_line_id, claim.line_ids)
        B = self.env['warranty.vendor.claim.recovery.report'].with_user(self.accountant)
        rows = B.search([('claim_id', '=', claim.id)])
        self.assertEqual((sum(rows.mapped('claimed_amount')), sum(rows.mapped('recovered_amount'))),
                         (3000, 0), 'draft credit note is not recovered')
        move.invoice_date = fields.Date.today()
        move.with_user(self.accountant).action_post()
        rows = B.search([('claim_id', '=', claim.id)])
        valve_row = rows.filtered(lambda r: r.product_id == self.valve)
        self.assertEqual((valve_row.accepted_amount, valve_row.recovered_amount,
                          valve_row.settled_amount, valve_row.outstanding_amount),
                         (2000, 2000, 0, 0))
        self.assertEqual(sum(rows.mapped('recovered_amount')), claim.recovered_amount)
        self.env['account.payment.register'].with_user(self.accountant).with_context(
            active_model='account.move', active_ids=move.ids).create({})._create_payments()
        rows = B.search([('claim_id', '=', claim.id)])
        self.assertEqual(sum(rows.mapped('settled_amount')), 3000)
        claim.invalidate_recordset()
        self.assertEqual(claim.settled_amount, 3000)
        # Report D: recovery per line, net warranty cost.
        D = self.env['warranty.mrf.cost.report'].with_user(self.coordinator)
        drow = D.search([('line_id', '=', self._line(mrf1, self.valve).id)])
        self.assertEqual((drow.warranty_cost, drow.vendor_recovered_amount,
                          drow.net_warranty_cost), (2000, 2000, 0))
        # No double counting across levels: job2 has no claim line of this claim.
        job1.invalidate_recordset()
        job2.invalidate_recordset()
        self.assertEqual((job1.vendor_recovered_amount, job2.vendor_recovered_amount), (3000, 0))
        self.assertEqual(job1.warranty_case_id.vendor_recovered_amount
                         if job1.warranty_case_id != job2.warranty_case_id else 3000, 3000)
        # A claim-level allocation without line (pre-5.9) is reported unassigned, not split.
        claim2 = self._claim(mrf2, {self.filter: 1})
        credit = self.env['account.move'].with_user(self.accountant).create({
            'move_type': 'in_refund', 'partner_id': self.manufacturer.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'name': 'Recovery', 'quantity': 1, 'price_unit': 300,
                                         'tax_ids': [(5, 0, 0)],
                                         'account_id': self.recovery_account.id})]})
        credit.action_post()
        allocation = claim2.with_user(self.accountant)._warranty_allocate(credit, 300)
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_vendor_claim_recovery SET claim_line_id = NULL "
                            "WHERE id = %s", (allocation.id,))
        self.env.invalidate_all()
        rows = B.search([('claim_id', '=', claim2.id)])
        self.assertEqual(sorted(rows.mapped('allocation_scope')), ['claim', 'line'])
        self.assertEqual(rows.filtered(lambda r: r.allocation_scope == 'claim').recovered_amount,
                         300)
        self.assertEqual(rows.filtered(lambda r: r.allocation_scope == 'line').recovered_amount,
                         0)
        self.assertEqual(sum(rows.mapped('recovered_amount')), claim2.recovered_amount)

    # ------------------------------------------------------------------ T9.10 audit
    def test_07_audit_trail(self):
        """The audit trail lists field changes (before / after), usage, reversal with reason,
        stock moves, closure / reopen notes, credit note allocation and the credit note's own
        changes, and opens the source documents."""
        self._receive(self.filter, 5, 500)
        mrf = self._consumed([(self.filter, 2)])
        # As in the UI, creation and later changes are separate transactions: Odoo does not
        # track fields of records created in the same transaction.
        self.env.flush_all()
        self.env.cr.precommit.run()
        entry = self._line(mrf, self.filter).sudo().warranty_consumption_ids
        entry.with_user(self.coordinator)._warranty_reverse('Wrong unit')
        self._use(mrf, self.filter, 2)
        claim = self._claim(mrf, {self.filter: 1})
        move = self.env['account.move'].browse(
            claim.with_user(self.accountant).action_create_credit_note()['res_id'])
        self.env.flush_all()
        self.env.cr.precommit.run()
        move.invoice_date = fields.Date.today()
        move.with_user(self.accountant).action_post()
        self._close(mrf)
        self.manager.groups_id |= self.env.ref('helpdesk.group_helpdesk_user')
        mrf.with_user(self.manager)._warranty_reopen('Audit test')
        # Field tracking is written when the transaction commits (pre-commit hook).
        self.env.flush_all()
        self.env.cr.precommit.run()
        Event = self.env['warranty.mrf.audit.event'].with_user(self.coordinator)
        events = Event.search([('requisition_id', '=', mrf.id)])
        types = set(events.mapped('event_type'))
        self.assertTrue({'tracking', 'message', 'usage', 'reversal', 'stock'} <= types, types)
        closer = events.filtered(lambda e: e.event_type == 'tracking'
                                 and e.field_name == 'Closed By')
        self.assertIn(self.coordinator.name, closer.mapped('new_value'))
        reopener = events.filtered(lambda e: e.event_type == 'tracking'
                                   and e.field_name == 'Last Reopen Reason')
        self.assertIn('Audit test', reopener.mapped('new_value'))
        reversal = events.filtered(lambda e: e.event_type == 'reversal')
        self.assertEqual((reversal.note, reversal.user_id), ('Wrong unit', self.coordinator))
        self.assertTrue(events.filtered(lambda e: 'reopened by' in (e.note or '')
                                        and 'Audit test' in e.note))
        claim_events = Event.search([('claim_id', '=', claim.id)])
        self.assertTrue(claim_events.filtered(lambda e: e.event_type == 'recovery'))
        self.assertTrue(claim_events.filtered(lambda e: e.event_type == 'credit_note'))
        action = reversal.action_open_document()
        self.assertEqual((action['res_model'], action['res_id']),
                         ('warranty.mrf.consumption', entry.id))

    # ------------------------------------------------------------------ T9.11 access / migration
    def test_08_access_and_upgrade(self):
        """Technicians cannot read the reports; accountants can; company rule. The upgrade
        recomputes the status only: a request computed Closed before 5.9 becomes Reconciled, no
        closing user or date is invented."""
        self._receive(self.filter, 3, 500)
        mrf = self._consumed([(self.filter, 1)])
        for model in ('warranty.mrf.approval.cost.report', 'warranty.vendor.claim.recovery.report',
                      'warranty.mrf.audit.event', 'warranty.mrf.cost.report'):
            with self.assertRaises(AccessError):
                self.env[model].with_user(self.tech).search([])
            self.assertTrue(self.env[model].with_user(self.accountant).has_access('read'))
        with self.assertRaises(AccessError):
            mrf.with_user(self.tech).read(['warranty_invoice_status'])
        menus = self.env['ir.ui.menu']
        reports = self.env.ref('warranty_management_mrf.menu_warranty_reports')
        children = reports.child_id.child_id.mapped('name')  # report categories
        for name in ('Material Approval and Cost', 'Warranty Material Cost',
                     'Vendor Claim Recovery', 'Material Audit Trail'):
            self.assertIn(name, children)
        visible = menus.with_user(self.tech)._visible_menu_ids()
        self.assertNotIn(reports.id, visible)
        shortcut = self.env.ref(
            'warranty_management_mrf.menu_warranty_mrf_approval_cost_report_accounting')
        self.assertEqual(shortcut.action, self.env.ref(
            'warranty_management_mrf.action_warranty_mrf_approval_cost_report'))
        # Upgrade simulation.
        self.env.flush_all()
        self.env.cr.execute("UPDATE material_purchase_requisition SET warranty_mrf_status = "
                            "'closed' WHERE id = %s", (mrf.id,))
        self.env.invalidate_all()
        path = os.path.join(get_module_path('warranty_management_mrf'), 'migrations',
                            '18.0.1.9.0', 'post-migrate.py')
        spec = importlib.util.spec_from_file_location('warranty_mrf_migration_190', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.migrate(self.env.cr, '18.0.1.8.1')
        self.env.invalidate_all()
        self.assertEqual((mrf.warranty_mrf_status, mrf.warranty_closed,
                          mrf.warranty_closed_by_id, mrf.warranty_closed_date),
                         ('reconciled', False, self.env['res.users'], False))
