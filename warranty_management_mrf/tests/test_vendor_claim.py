from contextlib import contextmanager

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import WarrantyMrfCommon


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyVendorClaim(WarrantyMrfCommon):
    """Phase 5.8 - vendor / manufacturer reimbursement claims (design
    part5_8_vendor_claim_design.md rev. 2, V-1 - V-18, C1 - C8, T8.1 - T8.14). Requests are
    approved by an explicit No Approval rule; parts are received with valuation layers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Product = cls.env['product.product']
        Partner = cls.env['res.partner']
        cls.manufacturer = Partner.create({'name': 'CoolMaker Manufacturing', 'is_company': True})
        cls.vendor = Partner.create({'name': 'Cool Parts Ltd', 'is_company': True})
        cls.other_vendor = Partner.create({'name': 'Other Supplies', 'is_company': True})
        cls.recovery_account = cls.env['account.account'].create({
            'name': 'Warranty Claim Recovery', 'code': 'WRC958', 'account_type': 'income_other',
            'company_ids': [(6, 0, cls.company.ids)]})
        cls.claim_approver = cls._user('mrf_v_approver')
        cls.finance = cls._user('mrf_v_finance', 'account.group_account_readonly')
        cls.coordinator = cls._user('mrf_v_coordinator', 'helpdesk.group_helpdesk_user')
        cls.coordinator.groups_id |= cls.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        cls.store = cls._user('mrf_v_store',
                              'material_purchase_requisitions.group_purchase_requisition_user')
        cls.store.groups_id |= cls.env.ref('stock.group_stock_user') | cls.env.ref(
            'purchase.group_purchase_user')
        cls.accountant = cls._user('mrf_v_accountant', 'account.group_account_invoice')
        cls.company.write({
            'warranty_mrf_approval_matrix': True,
            'warranty_mrf_dest_location_id': cls.default_tech_location.id,
            'warranty_worksheet_checklist_required': False,
            'warranty_vendor_claim_enabled': True,
            'warranty_claim_approver_ids': [(6, 0, cls.claim_approver.ids)],
            'warranty_claim_finance_approver_ids': [(6, 0, cls.finance.ids)],
            'warranty_claim_finance_threshold': 5000,
            'warranty_claim_evidence_required': True,
            'warranty_claim_recovery_account_id': cls.recovery_account.id,
        })
        cls.env['warranty.mrf.approval.rule'].create({
            'name': 'All free (5.8 test)', 'company_id': cls.company.id, 'no_approval': True})
        cls.filter = Product.create({
            'name': 'Air Filter', 'is_storable': True, 'type': 'consu', 'standard_price': 500,
            'warranty_vendor_claimable': True, 'warranty_claim_partner_id': cls.manufacturer.id,
            'warranty_vendor_warranty_months': 12})
        cls.valve = Product.create({
            'name': 'Expansion Valve', 'is_storable': True, 'type': 'consu',
            'standard_price': 2000, 'warranty_vendor_claimable': True,
            'seller_ids': [(0, 0, {'partner_id': cls.vendor.id, 'price': 2000})]})
        cls.coil = Product.create({'name': 'Coil', 'is_storable': True, 'type': 'consu',
                                   'standard_price': 300,
                                   'seller_ids': [(0, 0, {'partner_id': cls.other_vendor.id,
                                                          'price': 300})]})
        cls.sensor = Product.create({
            'name': 'Temperature Sensor', 'is_storable': True, 'type': 'consu',
            'standard_price': 700, 'tracking': 'serial', 'warranty_vendor_claimable': True,
            'seller_ids': [(0, 0, {'partner_id': cls.other_vendor.id, 'price': 700})]})
        cls.oil = Product.create({
            'name': 'Compressor Oil', 'is_storable': True, 'type': 'consu',
            'standard_price': 1000, 'list_price': 4000, 'invoice_policy': 'order',
            'warranty_vendor_claimable': True, 'taxes_id': [(5, 0, 0)]})
        cls.policy.covered_item_ids |= cls.env['warranty.coverage.item'].create([
            {'name': product.name, 'product_id': product.id}
            for product in (cls.filter, cls.valve, cls.coil, cls.sensor)])
        cls.item_gas.product_id = cls.oil
        cls.stock = cls.warehouse.lot_stock_id
        cls.Lot = cls.env['stock.lot']
        cls.Claim = cls.env['warranty.vendor.claim']

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def assertRaisesRegex(self, exception, regex):
        """Refused operations are rolled back as in a real request (savepoint), so partial
        records of the refused call never influence the next checks."""
        with super().assertRaisesRegex(exception, regex):
            with self.env.cr.savepoint():
                yield
        self.env.invalidate_all(flush=False)

    def _receive(self, product, qty, price, lots=None):
        move = self.env['stock.move'].create({
            'name': 'Receipt %s' % product.name, 'product_id': product.id,
            'product_uom': product.uom_id.id, 'product_uom_qty': qty, 'price_unit': price,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock.id, 'company_id': self.company.id})
        move._action_confirm()
        if lots:
            move.move_line_ids.unlink()
            for lot in lots:
                self.env['stock.move.line'].create({
                    'move_id': move.id, 'product_id': product.id, 'lot_id': lot.id,
                    'product_uom_id': product.uom_id.id, 'quantity': 1,
                    'location_id': move.location_id.id, 'location_dest_id': self.stock.id})
        else:
            move.quantity = qty
        move.picked = True
        move._action_done()
        return move

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

    def _issue(self, mrf):
        mrf.with_user(self.store).action_warranty_fulfil()
        for picking in self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id),
                                                         ('state', 'not in', ('done', 'cancel'))]):
            self._validate(picking)
        return mrf

    def _use(self, mrf, product, qty, lots=None):
        mrf.with_user(self.tech)._warranty_record_usage(
            [(self._line(mrf, product), qty, lots or self.Lot)])

    def _consumed(self, lines):
        """Request of a new job, issued and fully used: [(product, qty)]."""
        mrf = self._issue(self._mrf(lines))
        for product, qty in lines:
            self._use(mrf, product, qty)
        return mrf

    def _claim_wizard(self, record, user=None):
        action = record.with_user(user or self.coordinator).action_create_vendor_claim()
        return self.env[action['res_model']].with_user(user or self.coordinator).browse(
            action['res_id'])

    def _vclaim(self, mrf, rows=None, partner=None, reason=None, user=None):
        """Draft claim of the request; rows: {product: (qty, lots)} (default: all claimable)."""
        wizard = self._claim_wizard(mrf, user)
        for row in wizard.line_ids:
            if rows is not None:
                qty, lots = rows.get(row.product_id, (0.0, self.Lot))
                row.write({'selected': bool(qty), 'qty': qty, 'lot_ids': [(6, 0, lots.ids)]})
        wizard.partner_id = False
        wizard._propose_partner()
        wizard.write({'failure_description': 'Failed after 3 months',
                      'partner_override_reason': reason})
        if partner:
            wizard.partner_id = partner
        action = wizard.action_apply()
        return self.Claim.with_user(user or self.coordinator).browse(action['res_id'])

    def _attach(self, claim):
        self.env['ir.attachment'].create({'name': 'failure.jpg', 'raw': b'photo',
                                          'res_model': claim._name, 'res_id': claim.id})

    def _approve_claim(self, claim):
        claim.with_user(self.coordinator).action_submit()
        claim.with_user(self.claim_approver).action_approve()
        if claim.finance_required:
            claim.with_user(self.finance).action_approve()
        self.assertEqual(claim.state, 'approved')
        return claim

    def _answered(self, claim, accepted=None):
        """Sent with evidence and answered: accepted {product: amount} (default all)."""
        if claim.state == 'draft':
            self._approve_claim(claim)
        self._attach(claim)
        claim.with_user(self.coordinator).action_mark_sent()
        values = {line: ((accepted or {}).get(line.product_id, line.claimed_amount), 'ok')
                  for line in claim.line_ids}
        claim.with_user(self.coordinator)._warranty_record_response(values, reference='V-1')
        self.assertEqual(claim.state, 'answered')
        return claim

    def _credit_note(self, partner, amount, currency=None, post=True):
        move = self.env['account.move'].with_user(self.accountant).create({
            'move_type': 'in_refund', 'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'currency_id': (currency or self.company.currency_id).id,
            'invoice_line_ids': [(0, 0, {'name': 'Warranty recovery', 'quantity': 1,
                                         'price_unit': amount, 'tax_ids': [(5, 0, 0)],
                                         'account_id': self.recovery_account.id})]})
        if post:
            move.action_post()
        return move

    # ------------------------------------------------------------------ New button
    def test_new_claim_on_the_form_uses_the_same_checks(self):
        self._receive(self.filter, 5, 500)
        mrf = self._consumed([(self.filter, 2)])
        line = self._line(mrf, self.filter)
        case = mrf.warranty_case_id
        Claim = self.Claim.with_user(self.coordinator)
        vals = {'case_id': case.id, 'partner_id': self.manufacturer.id,
                'failure_description': 'Failed'}
        with self.assertRaisesRegex(UserError, 'only 2'):
            Claim.create({**vals, 'line_ids': [(0, 0, {'mrf_line_id': line.id, 'qty': 3})]})
        with self.assertRaisesRegex(UserError, 'enter the override reason'):
            Claim.create({**vals, 'partner_id': self.other_vendor.id,
                          'line_ids': [(0, 0, {'mrf_line_id': line.id, 'qty': 2})]})
        claim = Claim.create({**vals, 'line_ids': [(0, 0, {'mrf_line_id': line.id, 'qty': 2})]})
        self.assertEqual(claim.claimed_amount, 1000)
        self.assertEqual(claim.proposed_partner_id, self.manufacturer)
        self.assertEqual(claim.partner_source, 'manufacturer')
        with self.assertRaisesRegex(UserError, 'only 0'):
            Claim.create({**vals, 'line_ids': [(0, 0, {'mrf_line_id': line.id, 'qty': 1})]})
        self._approve_claim(claim)

    # ------------------------------------------------------------------ T8.1
    def test_01_eligibility_and_partner_proposal(self):
        """Never automatic: only consumed Covered / Goodwill parts of claimable products with
        verified actual cost; customer-paid and not claimable parts refused; the partner
        proposal (supplier, product claim partner, vendor list) and an audited override."""
        self._receive(self.filter, 5, 500)
        self._receive(self.coil, 5, 300)
        job = self._confirmed_job()
        mrf = self._issue(self._mrf([(self.filter, 2), (self.coil, 1)], job=job))
        with self.assertRaisesRegex(UserError, 'No consumed'):
            mrf.with_user(self.coordinator).action_create_vendor_claim()
        self._use(mrf, self.filter, 2)
        self._use(mrf, self.coil, 1)
        f_line, c_line = self._line(mrf, self.filter), self._line(mrf, self.coil)
        self.assertFalse(f_line._warranty_claim_problem())
        self.assertIn('not marked Vendor Claimable', c_line._warranty_claim_problem())
        self.assertEqual(f_line._warranty_claim_partner_proposal(),
                         (self.manufacturer, 'manufacturer'))
        wizard = self._claim_wizard(job)
        self.assertEqual(wizard.line_ids.mrf_line_id, f_line)
        self.assertEqual((wizard.partner_id, wizard.claim_type, wizard.line_ids.max_qty,
                          wizard.line_ids.amount), (self.manufacturer, 'manufacturer', 2, 1000))
        # Override without / with reason (audit).
        wizard.write({'partner_id': self.other_vendor.id, 'failure_description': 'Broken'})
        with self.assertRaisesRegex(UserError, 'override reason'):
            wizard.action_apply()
        wizard.partner_override_reason = 'Manufacturer delegates claims to its distributor'
        claim = self.Claim.browse(wizard.action_apply()['res_id'])
        self.assertEqual((claim.partner_id, claim.proposed_partner_id, claim.partner_source,
                          claim.state, claim.name[:4], claim.claimed_amount, claim.case_id),
                         (self.other_vendor, self.manufacturer, 'manual', 'draft', 'VCL/', 1000,
                          mrf.warranty_case_id))
        self.assertIn(job, claim.job_ids)
        self.assertIn('12 months', claim.line_ids.supplier_warranty_info)
        # Supplying vendor first: a purchased valve.
        mrf2 = self._mrf([(self.valve, 1)])
        mrf2.with_user(self.store).action_warranty_fulfil()
        order = mrf2.sudo().purchase_order_ids
        order.button_confirm()
        self._validate(order.picking_ids)
        mrf2.with_user(self.store).action_warranty_fulfil()
        self._validate(self.env['stock.picking'].search([
            ('custom_requisition_id', '=', mrf2.id), ('state', 'not in', ('done', 'cancel'))]))
        self._use(mrf2, self.valve, 1)
        self.assertEqual(self._line(mrf2, self.valve)._warranty_claim_partner_proposal(),
                         (self.vendor, 'supplier'))
        # Customer-paid parts are never claimable; disabled company; unverified cost.
        mrf3 = self._mrf([(self.oil, 1)])
        self.assertIn('Covered or Goodwill', self._line(mrf3, self.oil)._warranty_claim_problem())
        self.company.warranty_vendor_claim_enabled = False
        self.assertIn('not enabled', f_line._warranty_claim_problem())
        self.company.warranty_vendor_claim_enabled = True
        self.assertFalse(f_line._warranty_claim_problem())
        f_line.sudo().warranty_consumption_ids.move_ids.stock_valuation_layer_ids.unlink()
        self.assertIn('verified actual cost', f_line._warranty_claim_problem())

    # ------------------------------------------------------------------ T8.2
    def test_02_quantities_amounts_duplicates_and_serials(self):
        """Claimed qty <= consumed qty not on another active claim; amount <= verified actual
        cost; one serial on one active claim; serials must be consumed ones; cancelled /
        vendor-rejected claims release the quantity for a re-claim."""
        lots = self.Lot.create([{'name': 'SN-%s' % i, 'product_id': self.sensor.id}
                                for i in range(1, 4)])
        self._receive(self.sensor, 3, 700, lots=lots)
        self._receive(self.filter, 5, 500)
        mrf = self._issue(self._mrf([(self.sensor, 2), (self.filter, 3)]))
        issued = self._line(mrf, self.sensor).warranty_move_ids.move_line_ids.lot_id
        self._use(mrf, self.sensor, 2, issued[:2])
        self._use(mrf, self.filter, 2)
        claim = self._vclaim(mrf, {self.filter: (2, self.Lot)})
        line = claim.line_ids
        with self.assertRaisesRegex(UserError, 'only 2'):
            with self.env.cr.savepoint():
                line.with_user(self.coordinator).qty = 3
        self.env.invalidate_all(flush=False)
        with self.assertRaisesRegex(UserError, 'not above the verified actual cost'):
            with self.env.cr.savepoint():
                line.with_user(self.coordinator).claimed_amount = 1001
        self.env.invalidate_all(flush=False)
        line.with_user(self.coordinator).claimed_amount = 900
        # Fully claimed quantities are not offered again; the server refuses them anyway
        # (also for API writes and concurrent claims: the MRF lines are locked and re-checked).
        with self.assertRaisesRegex(UserError, 'Select at least one part'):
            self._vclaim(mrf, {self.filter: (1, self.Lot)})
        with self.assertRaisesRegex(UserError, 'not yet on another active claim'):
            with self.env.cr.savepoint():
                claim.with_user(self.coordinator).write({'line_ids': [(0, 0, {
                    'mrf_line_id': self._line(mrf, self.filter).id, 'qty': 1})]})
        self.env.invalidate_all(flush=False)
        with self.assertRaisesRegex(UserError, 'workflow'):
            line.with_user(self.coordinator).accepted_amount = 900
        # Serials: consumed only, one per unit, one active claim per serial.
        unused = lots - issued[:2]
        with self.assertRaisesRegex(UserError, 'consumed ones'):
            self._vclaim(mrf, {self.sensor: (1, unused[:1])})
        s_claim = self._vclaim(mrf, {self.sensor: (1, issued[:1])})
        with self.assertRaisesRegex(UserError, 'already on vendor claim'):
            self._vclaim(mrf, {self.sensor: (1, issued[:1])})
        with self.assertRaisesRegex(UserError, 'select the serial'):
            self._vclaim(mrf, {self.sensor: (1, self.Lot)}).with_user(
                self.coordinator).action_submit()
        # Cancel releases the quantity (history kept); a re-claim references the old claim.
        with self.assertRaisesRegex(UserError, 'reason is required'):
            s_claim.with_user(self.coordinator)._warranty_cancel(' ')
        s_claim.with_user(self.coordinator)._warranty_cancel('Wrong vendor')
        again = self._vclaim(mrf, {self.sensor: (1, issued[:1])})
        self.assertEqual((s_claim.state, again.state), ('cancel', 'draft'))
        with self.assertRaisesRegex(UserError, 'never deleted'):
            s_claim.with_user(self.coordinator).unlink()
        # A vendor rejection releases the quantity of the claim too.
        self._answered(claim, {self.filter: 0.0})
        self.assertEqual((claim.vendor_result, claim.recovery_status), ('rejected', 'rejected'))
        reclaim = self._vclaim(mrf, {self.filter: (2, self.Lot)})
        self.assertEqual(reclaim.claimed_amount, 1000)

    # ------------------------------------------------------------------ T8.3
    def test_03_approval_route_and_segregation_of_duties(self):
        """Named Warranty approver; Finance too from the threshold and for goodwill; the
        responsible / submitter never approves; one person one level; reject / reset with a
        reason; approvers who are not coordinators read only their claims."""
        self._receive(self.valve, 5, 2000)
        mrf = self._consumed([(self.valve, 3)])
        claim = self._vclaim(mrf, {self.valve: (2, self.Lot)})
        claim.with_user(self.coordinator).write({'failure_description': ' '})
        with self.assertRaisesRegex(UserError, 'failure description'):
            claim.with_user(self.coordinator).action_submit()
        claim.with_user(self.coordinator).failure_description = 'Valve leaking'
        self.company.warranty_claim_approver_ids = [(6, 0, self.coordinator.ids)]
        with self.assertRaisesRegex(UserError, 'needs a Warranty approver'):
            claim.with_user(self.coordinator).action_submit()
        self.company.warranty_claim_approver_ids = [(6, 0, self.claim_approver.ids)]
        claim.with_user(self.coordinator).action_submit()
        self.assertEqual((claim.state, claim.finance_required, claim.claimed_amount),
                         ('to_approve', False, 4000))
        self.assertTrue(claim.activity_ids.filtered(lambda a: a.user_id == self.claim_approver))
        with self.assertRaises(AccessError):
            claim.with_user(self.coordinator).action_approve()
        # The named approver (no coordinator rights) reads the claim routed to him.
        self.assertTrue(claim.with_user(self.claim_approver).can_approve)
        with self.assertRaisesRegex(UserError, 'reason is required'):
            claim.with_user(self.claim_approver)._warranty_reject('')
        claim.with_user(self.claim_approver)._warranty_reject('Add photos of the leak')
        self.assertEqual(claim.state, 'draft')
        claim.with_user(self.coordinator).line_ids.qty = 3
        claim.with_user(self.coordinator).action_submit()
        self.assertTrue(claim.finance_required)
        claim.with_user(self.claim_approver).action_approve()
        self.assertEqual(claim.state, 'to_approve')
        with self.assertRaises(AccessError):
            claim.with_user(self.claim_approver).action_approve()
        claim.with_user(self.finance).action_approve()
        self.assertEqual((claim.state, claim.approved_amount, claim.warranty_approved_by_id,
                          claim.finance_approved_by_id),
                         ('approved', 6000, self.claim_approver, self.finance))
        claim.with_user(self.coordinator)._warranty_reset_draft('Vendor asks for another split')
        self.assertEqual((claim.state, claim.approved_amount), ('draft', 0))
        # A user in both lists approves one level only: a second approver is needed.
        self.company.warranty_claim_finance_approver_ids = [(6, 0, self.claim_approver.ids)]
        with self.assertRaisesRegex(UserError, 'two different approvers'):
            claim.with_user(self.coordinator).action_submit()
        # The technician sees no claim.
        self.assertFalse(self.Claim.with_user(self.tech).search([]))
        with self.assertRaises(AccessError):
            claim.with_user(self.tech).read(['claimed_amount'])

    def test_04_goodwill_claim_needs_finance(self):
        """Goodwill lines (reviewer decision, vendor 2-step approval with the matrix off) are
        flagged on the claim and always need the Finance approver, also below the threshold."""
        self.company.warranty_mrf_approval_matrix = False
        self._receive(self.filter, 3, 500)
        job = self._confirmed_job()
        action = job.with_user(self.helpdesk_user).action_create_material_request()
        mrf = self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {'product_id': self.filter.id, 'qty': 1,
                                             'description': 'Filter',
                                             'uom': self.filter.uom_id.id})]})
        line = self._line(mrf, self.filter)
        self.env.flush_all()
        mrf.with_user(self.approver_b)._warranty_decide_coverage(line, 'goodwill', 'Key customer')
        self.env.flush_all()
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        dept = self._user('mrf_v_dept',
                          'material_purchase_requisitions.group_purchase_requisition_department')
        dept.groups_id |= self.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        mrf.with_user(dept).manager_approve()
        mrf.with_user(self.store).user_approve()
        self._issue(mrf)
        self._use(mrf, self.filter, 1)
        self.assertEqual(line.cost_bucket, 'goodwill')
        claim = self._vclaim(mrf)
        self.assertTrue(claim.goodwill and claim.line_ids.goodwill)
        self.assertLess(claim.claimed_amount, self.company.warranty_claim_finance_threshold)
        claim.with_user(self.coordinator).action_submit()
        self.assertTrue(claim.finance_required)
        claim.with_user(self.claim_approver).action_approve()
        self.assertEqual(claim.state, 'to_approve')
        claim.with_user(self.finance).action_approve()
        self.assertEqual(claim.state, 'approved')

    # ------------------------------------------------------------------ T8.4 / T8.5
    def test_05_evidence_response_credit_note_and_settlement(self):
        """Evidence before sending; partial vendor acceptance; draft credit note on the
        Recovery Account only (never posted by the claim, no fallback account); recovered after
        posting, settled after reconciliation; close; no stock move, no other journal entry."""
        self._receive(self.filter, 5, 500)
        self._receive(self.valve, 2, 2000)
        mrf = self._consumed([(self.filter, 2), (self.valve, 1)])
        claim = self._approve_claim(self._vclaim(mrf, reason='One claim to the manufacturer'))
        self.assertEqual(claim.claimed_amount, 3000)
        with self.assertRaisesRegex(UserError, 'evidence'):
            claim.with_user(self.coordinator).action_mark_sent()
        self._attach(claim)
        claim.with_user(self.coordinator).action_mark_sent()
        self.assertEqual(claim.state, 'sent')
        f_line = claim.line_ids.filtered(lambda line: line.product_id == self.filter)
        v_line = claim.line_ids - f_line
        with self.assertRaisesRegex(UserError, 'between 0 and the claimed'):
            claim.with_user(self.coordinator)._warranty_record_response(
                {f_line: (1500, ''), v_line: (2000, '')})
        claim.with_user(self.coordinator)._warranty_record_response(
            {f_line: (800, 'Handling deducted'), v_line: (2000, '')}, reference='CM-77')
        self.assertEqual((claim.state, claim.vendor_result, claim.accepted_amount,
                          claim.not_accepted_amount, claim.vendor_reference),
                         ('answered', 'partial', 2800, 200, 'CM-77'))
        # Corrections: Finance approvers only, with a reason.
        with self.assertRaises(AccessError):
            claim.with_user(self.coordinator)._warranty_record_response({f_line: (900, '')})
        with self.assertRaisesRegex(UserError, 'reason is required'):
            claim.with_user(self.finance)._warranty_record_response({f_line: (900, '')})
        claim.with_user(self.finance)._warranty_record_response(
            {f_line: (900, 'Revised by vendor')}, reason='Vendor letter of 27/10')
        self.assertEqual(claim.accepted_amount, 2900)
        # Credit note: Billing users only; Recovery Account required (no fallback).
        moves_before = self.env['account.move'].search_count([])
        stock_moves_before = self.env['stock.move'].search_count([])
        with self.assertRaises(AccessError):
            claim.with_user(self.coordinator).action_create_credit_note()
        self.company.warranty_claim_recovery_account_id = False
        with self.assertRaisesRegex(UserError, 'Recovery Account'):
            claim.with_user(self.accountant).action_create_credit_note()
        self.company.warranty_claim_recovery_account_id = self.recovery_account
        action = claim.with_user(self.accountant).action_create_credit_note()
        move = self.env['account.move'].browse(action['res_id'])
        self.assertEqual((move.move_type, move.state, move.partner_id, move.amount_untaxed),
                         ('in_refund', 'draft', self.manufacturer, 2900))
        self.assertEqual(move.invoice_line_ids.account_id, self.recovery_account)
        self.assertEqual(self.env['account.move'].search_count([]), moves_before + 1)
        self.assertEqual(self.env['stock.move'].search_count([]), stock_moves_before)
        self.assertEqual((claim.allocated_amount, claim.recovered_amount, claim.outstanding_amount),
                         (2900, 0, 2900))
        with self.assertRaisesRegex(UserError, 'already allocated'):
            claim.with_user(self.accountant).action_create_credit_note()
        with self.assertRaisesRegex(UserError, 'draft credit note'):
            claim.with_user(self.coordinator)._warranty_close('x')
        move.invoice_date = fields.Date.today()
        move.with_user(self.accountant).action_post()
        self.assertEqual((claim.recovered_amount, claim.settled_amount, claim.outstanding_amount,
                          claim.recovery_status), (2900, 0, 0, 'recovered'))
        # Settlement: the credit note is offset by a vendor refund payment (reconciliation).
        self.env['account.payment.register'].with_user(self.accountant).with_context(
            active_model='account.move', active_ids=move.ids).create({})._create_payments()
        claim.invalidate_recordset()
        self.assertEqual(claim.settled_amount, 2900)
        case = claim.case_id
        self.assertEqual((case.vendor_recovery_status, case.vendor_recovered_amount,
                          case.net_warranty_material_cost),
                         ('recovered', 2900, case.warranty_material_cost - 2900))
        claim.with_user(self.coordinator)._warranty_close()
        self.assertEqual((claim.state, claim.written_off_amount), ('closed', 0))
        # 5.7 cost values unchanged by claims.
        self.assertEqual(self._line(mrf, self.filter).actual_cost, 1000)

    # ------------------------------------------------------------------ T8.6
    def test_06_existing_credit_note_allocation_and_corrections(self):
        """One posted credit note over two claims within its amount; no over-allocation;
        other partner / draft credit notes refused; a cancelled credit note stops counting;
        allocation corrections by Accounting with a reason; partial recovery -> write-off."""
        self._receive(self.filter, 6, 500)
        mrf = self._consumed([(self.filter, 4)])
        claim_a = self._answered(self._vclaim(mrf, {self.filter: (2, self.Lot)}))
        claim_b = self._answered(self._vclaim(mrf, {self.filter: (2, self.Lot)}))
        credit = self._credit_note(self.manufacturer, 1500)
        with self.assertRaises(AccessError):
            claim_a.with_user(self.coordinator)._warranty_allocate(credit, 1000)
        claim_a.with_user(self.accountant)._warranty_allocate(credit, 1000)
        with self.assertRaisesRegex(UserError, 'still available for claims'):
            claim_b.with_user(self.accountant)._warranty_allocate(credit, 600)
        claim_b.with_user(self.accountant)._warranty_allocate(credit, 500)
        self.assertEqual((claim_a.recovery_status, claim_b.recovery_status,
                          claim_b.outstanding_amount), ('recovered', 'partial', 500))
        with self.assertRaisesRegex(UserError, 'not from'):
            claim_b.with_user(self.accountant)._warranty_allocate(
                self._credit_note(self.other_vendor, 500), 100)
        with self.assertRaisesRegex(UserError, 'Only posted'):
            claim_b.with_user(self.accountant)._warranty_allocate(
                self._credit_note(self.manufacturer, 500, post=False), 100)
        with self.assertRaisesRegex(UserError, 'not yet recovered'):
            claim_a.with_user(self.accountant)._warranty_allocate(
                self._credit_note(self.manufacturer, 500), 100)
        # Closing B with 500 outstanding needs a write-off reason.
        with self.assertRaisesRegex(UserError, 'write-off reason'):
            claim_b.with_user(self.coordinator)._warranty_close()
        # Accounting correction: the credit note is cancelled -> nothing recovered any more.
        credit.with_user(self.accountant).button_draft()
        credit.with_user(self.accountant).button_cancel()
        self.assertEqual((claim_a.recovered_amount, claim_b.recovered_amount), (0, 0))
        allocation = claim_b.recovery_ids
        with self.assertRaises(AccessError):
            allocation.with_user(self.coordinator)._warranty_remove('x')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            allocation.with_user(self.accountant)._warranty_remove('')
        allocation.with_user(self.accountant)._warranty_remove('Credit note cancelled')
        self.assertFalse(allocation.active)
        self.assertIn(allocation, claim_b.recovery_ids)
        replacement = self._credit_note(self.manufacturer, 600)
        claim_b.with_user(self.accountant)._warranty_allocate(replacement, 600)
        claim_b.with_user(self.coordinator)._warranty_close('Vendor pays 600 only')
        self.assertEqual((claim_b.state, claim_b.written_off_amount, claim_b.recovery_status),
                         ('closed', 400, 'written_off'))

    # ------------------------------------------------------------------ T8.7
    def test_07_reversal_after_claim_over_claimed(self):
        """A consumption reversed after the claim -> Over-claimed, To-Do, recovery allocation
        and closure blocked until corrected; a draft claim cannot be submitted."""
        self._receive(self.filter, 5, 500)
        mrf = self._consumed([(self.filter, 2)])
        claim = self._answered(self._vclaim(mrf))
        entry = self._line(mrf, self.filter).warranty_consumption_ids.filtered(
            lambda e: e.kind == 'used')
        entry.with_user(self.coordinator)._warranty_reverse('Wrong job')
        claim.invalidate_recordset()
        self.assertTrue(claim.over_claimed)
        self.assertTrue(claim.activity_ids.filtered(lambda a: 'over-claimed' in a.summary))
        credit = self._credit_note(self.manufacturer, 1000)
        with self.assertRaisesRegex(UserError, 'over-claimed'):
            claim.with_user(self.accountant)._warranty_allocate(credit, 1000)
        with self.assertRaisesRegex(UserError, 'over-claimed'):
            claim.with_user(self.coordinator)._warranty_close('x')
        # Correction: the consumption is recorded again.
        self._use(mrf, self.filter, 2)
        claim.invalidate_recordset()
        self.assertFalse(claim.over_claimed)
        claim.with_user(self.accountant)._warranty_allocate(credit, 1000)
        self.assertEqual(claim.recovery_status, 'recovered')

    # ------------------------------------------------------------------ T8.8 / T8.9
    def test_08_access_company_currency_and_history(self):
        """Technicians see no claims or claim figures; accountants read claims but do not create
        them; company isolation; a foreign-currency credit note counts in company currency;
        the MRF approval history and 5.7 costs are unchanged."""
        self._receive(self.filter, 5, 500)
        mrf = self._consumed([(self.filter, 2)])
        approvals = len(mrf.sudo().warranty_approval_ids)
        cost = self._line(mrf, self.filter).actual_cost
        claim = self._answered(self._vclaim(mrf))
        line = self._line(mrf, self.filter)
        with self.assertRaises(AccessError):
            line.with_user(self.tech).read(['vendor_claimed_qty'])
        with self.assertRaises(AccessError):
            mrf.warranty_service_job_id.with_user(self.tech).read(['vendor_recovered_amount'])
        self.assertFalse(self.Claim.with_user(self.tech).search([]))
        arch = self.env['warranty.service.job'].with_user(self.tech).get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertNotIn('vendor_claim_count', arch)
        self.assertEqual(self.Claim.with_user(self.accountant).search(
            [('id', '=', claim.id)]), claim)
        with self.assertRaises(AccessError):
            self._vclaim(mrf, user=self.accountant)
        with self.assertRaises(UserError):
            claim.with_user(self.accountant).write({'state': 'closed'})
        # Foreign currency credit note: company-currency amount (rate 2.0 -> half).
        other_currency = self.env['res.currency'].with_context(active_test=False).search(
            [('id', '!=', self.company.currency_id.id)], limit=1)
        other_currency.active = True
        self.env['res.currency.rate'].create({'currency_id': other_currency.id, 'rate': 2.0,
                                              'name': fields.Date.today(),
                                              'company_id': self.company.id})
        credit = self._credit_note(self.manufacturer, 1200, currency=other_currency)
        self.assertEqual(credit._warranty_claim_available(), 600)
        claim.with_user(self.accountant)._warranty_allocate(credit, 600)
        self.assertEqual((claim.recovered_amount, claim.outstanding_amount), (600, 400))
        self.assertEqual(len(mrf.sudo().warranty_approval_ids), approvals)
        self.assertEqual(self._line(mrf, self.filter).actual_cost, cost)
        self.assertTrue(any('Vendor claim' in (m.body or '') for m in mrf.message_ids))
        self.assertTrue(any('Vendor claim' in (m.body or '')
                            for m in mrf.warranty_case_id.message_ids))
        # Company isolation.
        other = self.env['res.company'].create({'name': 'Claims Co B',
                                                'currency_id': other_currency.id})
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_vendor_claim SET company_id = %s WHERE id = %s",
                            (other.id, claim.id))
        self.env.invalidate_all()
        self.assertFalse(self.Claim.with_user(self.accountant).search([('id', '=', claim.id)]))

    # ------------------------------------------------------------------ menus
    def test_09_menus(self):
        """Warranty -> Vendor Claims; Accounting -> Vendors shortcut for accountants; neither for
        technicians."""
        menu = self.env.ref('warranty_management_mrf.menu_warranty_vendor_claim')
        shortcut = self.env.ref('warranty_management_mrf.menu_warranty_vendor_claim_accounting')
        self.assertEqual(menu.parent_id, self.env.ref('warranty_management.menu_warranty_root'))
        self.assertEqual(shortcut.parent_id, self.env.ref('account.menu_finance_payables'))
        Menu = self.env['ir.ui.menu']
        for user, expected in ((self.coordinator, (True, False)), (self.accountant, (True, True)),
                               (self.tech, (False, False))):
            visible = Menu.with_user(user)._visible_menu_ids()
            self.assertEqual((menu.id in visible, shortcut.id in visible), expected, user.login)

    # ------------------------------------------------------------------ serial / lot selection
    def test_09b_reversed_credit_note_is_not_recovery(self):
        """Part 8.2 correction: a posted reversal linked to the credit note reduces its recovery in
        proportion, in every figure; the payment state alone would miss it."""
        self._receive(self.filter, 5, 500)
        mrf = self._consumed([(self.filter, 2)])
        case = mrf.warranty_case_id
        claim = self._answered(self._vclaim(mrf))
        self.assertEqual(claim.accepted_amount, 1000)
        action = claim.with_user(self.accountant).action_create_credit_note()
        move = self.env['account.move'].browse(action['res_id'])
        move.invoice_date = fields.Date.today()
        move.with_user(self.accountant).action_post()
        self.env.invalidate_all()
        cost = case.warranty_material_cost
        self.assertEqual((claim.recovered_amount, claim.outstanding_amount), (1000, 0))
        self.assertEqual(case.net_warranty_material_cost, cost - 1000)
        partial = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        partial.invoice_line_ids.write({'price_unit': 300})
        partial.action_post()
        self.env.invalidate_all()
        self.assertEqual((claim.recovered_amount, claim.outstanding_amount, claim.recovery_status),
                         (700, 300, 'partial'))
        self.assertEqual(case.net_warranty_material_cost, cost - 700)
        report = self.env['warranty.vendor.claim.recovery.report']
        self.assertEqual(report.search([('claim_id', '=', claim.id),
                                        ('allocation_scope', '=', 'line')]).recovered_amount, 700)
        approval = self.env['warranty.mrf.approval.cost.report'].search(
            [('requisition_id', '=', mrf.id)])
        self.assertEqual((approval.vendor_recovered, approval.net_warranty_cost),
                         (700, cost - 700))
        material = self.env['warranty.mrf.cost.report'].search([('requisition_id', '=', mrf.id)])
        self.assertEqual(sum(material.mapped('vendor_recovered_amount')), 700)
        self.assertEqual(claim.allocated_amount, 700, 'the reversed share can be claimed again')
        rest = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        rest.invoice_line_ids.write({'price_unit': 700})
        rest.action_post()
        self.env.invalidate_all()
        self.assertEqual((claim.recovered_amount, claim.outstanding_amount, claim.recovery_status),
                         (0, 1000, 'pending'))
        self.assertEqual(case.net_warranty_material_cost, cost)
        self.assertEqual(move.state, 'posted', 'the credit note itself is not changed')
        self.assertEqual(claim.recovery_ids.filtered('active').amount, 1000, 'the history stays')

    def test_10_serial_selection_limited_to_consumed_serials(self):
        """The claim line offers only the serials consumed on its MRF line (not reversed, not
        returned unused, not on another active claim, never other products' lots); no lot
        creation from the field; the server refuses anything else, also for untracked parts."""
        lots = self.Lot.create([{'name': 'SN-%s' % i, 'product_id': self.sensor.id}
                                for i in range(1, 4)])
        other_product = self.env['product.product'].create({
            'name': 'Other Serial Part', 'is_storable': True, 'type': 'consu',
            'tracking': 'serial'})
        foreign = self.Lot.create({'name': 'OTHER-1', 'product_id': other_product.id})
        self._receive(self.sensor, 3, 700, lots=lots)
        self._receive(self.filter, 2, 500)
        mrf = self._issue(self._mrf([(self.sensor, 3), (self.filter, 1)]))
        line = self._line(mrf, self.sensor)
        issued = line.sudo().warranty_move_ids.move_line_ids.lot_id
        sn1, sn2, sn3 = issued.sorted('name')
        self._use(mrf, self.sensor, 1, sn1)
        self._use(mrf, self.sensor, 1, sn2)
        self._use(mrf, self.filter, 1)
        line.sudo().warranty_consumption_ids.filtered(
            lambda e: e.kind == 'used' and sn2 in e.lot_ids).with_user(
            self.coordinator)._warranty_reverse('Recorded on the wrong unit')
        mrf.with_user(self.tech)._warranty_return_unused(
            [(line.with_user(self.tech), 2.0, sn2 | sn3)], note='Unused')
        self.assertEqual(line._warranty_claimable_lots(), sn1)
        wizard = self._claim_wizard(mrf)
        row = wizard.line_ids.filtered(lambda r: r.product_id == self.sensor)
        self.assertEqual((row.max_qty, row.allowed_lot_ids), (1, sn1))
        claim = self._vclaim(mrf, {self.sensor: (1, sn1)})
        claim_line = claim.line_ids
        self.assertEqual(claim_line.allowed_lot_ids, sn1)
        self.assertFalse(line._warranty_claimable_lots(), 'SN-1 is now claimed')
        self.assertIn('allowed_lot_ids', self.env['warranty.vendor.claim.line']._fields[
            'lot_ids'].domain)
        arch = self.Claim.with_user(self.coordinator).get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertIn('no_create', arch)
        # Server side (API / import): other product, reversed and returned serials refused.
        for lot in (foreign, sn2, sn3):
            with self.assertRaisesRegex(UserError, 'consumed ones'):
                claim_line.with_user(self.coordinator).lot_ids = [(6, 0, lot.ids)]
        # Untracked part: no serial accepted.
        f_claim = self._vclaim(mrf, {self.filter: (1, self.Lot)})
        with self.assertRaisesRegex(UserError, 'not tracked'):
            f_claim.line_ids.with_user(self.coordinator).lot_ids = [(6, 0, sn1.ids)]
        self.assertFalse(f_claim.line_ids.allowed_lot_ids)
