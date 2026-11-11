from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.models import NewId
from odoo.tests import Form, tagged

from .common import WarrantyMrfCommon


@tagged('post_install', '-at_install', 'warranty_mrf', 'warranty_figure7')
class TestWarrantyMrfFigure7(WarrantyMrfCommon):
    """SRS Figure 7 (doc/figure7_workflow_decisions.md): Approval required? (D1, D3), Not
    Covered -> customer quotation (D2), Stock available? / Awaiting Stock loop (D4). Outdoor
    PCB 18,500 is a covered item, Gas R410A 3,000 an excluded item (Not Covered), Copper Pipe
    is not in the policy (Pending). Amounts are test values, not SRS thresholds."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({'warranty_mrf_approval_matrix': True,
                           'warranty_mrf_dest_location_id': cls.default_tech_location.id})
        Product = cls.env['product.product']
        cls.gas = Product.create({'name': 'Gas R410A', 'type': 'consu', 'standard_price': 3000,
                                  'list_price': 4000, 'invoice_policy': 'order'})
        cls.pipe = Product.create({'name': 'Copper Pipe', 'type': 'consu', 'standard_price': 10})
        cls.vendor = cls.env['res.partner'].create({'name': 'F7 Parts Ltd', 'is_company': True})
        cls.filter = Product.create({'name': 'Air Filter', 'type': 'consu', 'is_storable': True,
                                     'standard_price': 500})
        cls.valve = Product.create({'name': 'Expansion Valve', 'type': 'consu',
                                    'is_storable': True, 'standard_price': 2000,
                                    'seller_ids': [(0, 0, {'partner_id': cls.vendor.id,
                                                           'price': 1800})]})
        cls.motor = Product.create({'name': 'Fan Motor', 'type': 'consu', 'is_storable': True,
                                    'standard_price': 300})
        cls.box = Product.create({'name': 'Cable Box', 'type': 'consu', 'is_storable': True,
                                  'standard_price': 70, 'tracking': 'lot'})
        cls.compressor = Product.create({'name': 'Compressor', 'type': 'consu',
                                         'standard_price': 20000})
        cls.item_pcb.product_id = cls.part
        cls.item_gas.product_id = cls.gas
        cls.policy.covered_item_ids |= cls.env['warranty.coverage.item'].create([
            {'name': product.name, 'product_id': product.id}
            for product in (cls.filter, cls.valve, cls.motor, cls.box, cls.compressor)])
        cls.manager = cls._user('f7_manager')
        cls.finance = cls._user('f7_finance')
        cls.gm = cls._user('f7_gm')
        cls.store = cls._user('f7_store',
                              'material_purchase_requisitions.group_purchase_requisition_user')
        cls.helpdesk_user.groups_id |= cls.env.ref('sales_team.group_sale_salesman')
        cls.Rule = cls.env['warranty.mrf.approval.rule']
        cls.stock = cls.warehouse.lot_stock_id
        cls.env['stock.quant']._update_available_quantity(cls.part, cls.stock, 20)

    # ------------------------------------------------------------------ helpers
    def _rule(self, name, levels=(), **vals):
        values = {'name': name, 'company_id': self.company.id}
        if not levels:
            values['no_approval'] = True
        for level in levels:
            values['%s_required' % level] = True
            values['%s_user_ids' % level] = [(6, 0, getattr(self, level).ids)]
        values.update(vals)
        return self.Rule.create(values)

    def _draft(self, lines, record=None):
        """lines: [(product, qty)] or [(product, qty, extra line values)]"""
        record = record or self._approved()
        action = record.with_user(self.helpdesk_user).action_create_material_request()
        commands = []
        for product, qty, *extra in lines:
            commands.append((0, 0, dict({
                'product_id': product.id, 'description': product.name, 'qty': qty,
                'uom': product.uom_id.id}, **(extra[0] if extra else {}))))
        return self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create(
            {'requisition_line_ids': commands})

    def _mrf(self, lines, record=None):
        mrf = self._draft(lines, record)
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        return mrf

    def _line(self, mrf, product):
        return mrf.requisition_line_ids.filtered(lambda line: line.product_id == product)

    def _round(self, mrf):
        return mrf.sudo().warranty_approval_ids.filtered(
            lambda line: line.round == mrf.approval_round)

    def _pending(self, mrf):
        return set(self._round(mrf).filtered(lambda line: line.state == 'pending')
                   .mapped('level'))

    def _quote(self, mrf):
        action = mrf.with_user(self.helpdesk_user).action_create_parts_quotation()
        return self.env['sale.order'].browse(action['res_id'])

    def _historical_quote(self, mrf):
        """A quotation created before the change request of 2026-11-07 (while the request
        waited for approval): such orders still exist and keep their release controls."""
        with patch.object(type(mrf), '_warranty_quotation_error',
                          lambda rec: rec._warranty_chargeable_request_error()):
            return self._quote(mrf)

    def _validate(self, picking, lot=None):
        for move in picking.move_ids:
            if lot:
                move.move_line_ids.lot_id = lot
            move.quantity = move.product_uom_qty
            move.picked = True
        return picking.button_validate()

    def _pickings(self, mrf):
        return self.env['stock.picking'].search([('custom_requisition_id', '=', mrf.id)])

    def _add_stock(self, product, qty, lot=None):
        """Replenishment, as in a later request (free quantities are read again)."""
        self.env['stock.quant']._update_available_quantity(product, self.stock, qty, lot_id=lot)
        self.env.invalidate_all()

    # ------------------------------------------------------------------ D1 Approval required?
    def test_01_no_rule_and_no_approval_rule(self):
        """NO branch: no matching rule, or only No Approval Required rules -> approved at
        submission without approver, To-Do or approving person, shown as Approved - No Approval
        Required; a matching approval rule is never bypassed (strictest)."""
        can_submit, html = self._draft([(self.filter, 1)]).with_user(
            self.helpdesk_user)._warranty_route_preview()
        self.assertTrue(can_submit)
        self.assertIn('no material approval rule matches', html)
        free = self._mrf([(self.part, 1)])
        line = self._round(free)
        self.assertEqual((free.state, free.approval_status, line.level, line.state),
                         ('approve', 'not_required', 'none', 'approved'))
        self.assertIn('no material approval rule matches', line.reason)
        self.assertFalse(free.approved_by_id or free.activity_ids or line.allowed_user_ids)
        self.assertTrue(any('no material approval rule matches' in (m.body or '')
                            for m in free.message_ids))
        self._rule('F7 Free')
        ruled = self._mrf([(self.part, 1)])
        self.assertEqual(ruled.approval_status, 'not_required')
        self.assertIn('F7 Free', self._round(ruled).reason)
        self._rule('F7 PCB Manager', ('manager',), product_ids=[(6, 0, self.part.ids)])
        strict = self._mrf([(self.part, 1)])
        self.assertEqual((strict.state, self._pending(strict)), ('dept_confirm', {'manager'}))
        strict.with_user(self.manager).action_warranty_approve()
        self.assertEqual((strict.state, strict.approval_status, strict.approved_by_id),
                         ('approve', 'approved', self.manager), 'approved by a person')

    def test_02_amount_basis_boundaries_and_overlap(self):
        """D3: Amount Basis All Lines (default) / Covered Lines Only; minimum inclusive, maximum
        exclusive; overlapping matching rules combine to the strictest."""
        low = self._rule('F7 Covered low', max_amount=20000, amount_basis='covered')
        high = self._rule('F7 Covered high', ('manager',), min_amount=20000,
                          amount_basis='covered')
        self.assertEqual(self.Rule.new({}).amount_basis, 'all', 'existing behaviour by default')
        mixed = self._mrf([(self.part, 1), (self.gas, 3)])
        self.assertEqual((mixed.approval_routing_amount, mixed.approval_covered_amount),
                         (27500, 18500))
        self.assertEqual(mixed.approval_status, 'not_required', 'covered 18,500 < 20,000')
        (low | high).write({'amount_basis': 'all'})
        mixed_all = self._mrf([(self.part, 1), (self.gas, 3)])
        self.assertEqual(self._pending(mixed_all), {'manager'}, 'all lines 27,500 >= 20,000')
        (low | high).write({'amount_basis': 'covered'})
        boundary = self._mrf([(self.compressor, 1)])
        self.assertEqual(self._pending(boundary), {'manager'}, '20,000 = minimum (inclusive)')
        self.assertFalse(low._matches(low._basis_amount({'routing': 20000, 'covered': 20000}),
                                      boundary.requisition_line_ids), 'maximum exclusive')
        self._rule('F7 Gas Finance', ('finance',), product_ids=[(6, 0, self.gas.ids)])
        overlap = self._mrf([(self.compressor, 1), (self.gas, 1)])
        self.assertEqual((overlap.state, self._pending(overlap)),
                         ('dept_confirm', {'manager', 'finance'}))

    def test_03_approval_level_combinations(self):
        """Manager only, Finance only, GM only, Manager + Finance, Finance + GM, Manager +
        Finance + GM: first status, sequence (Manager first, then Finance / GM in any order),
        unauthorized user refused, final status Approved by a person."""
        combos = [('manager',), ('finance',), ('gm',), ('manager', 'finance'),
                  ('finance', 'gm'), ('manager', 'finance', 'gm')]
        for levels in combos:
            self.Rule.search([]).active = False
            self._rule('F7 %s' % '+'.join(levels), levels)
            mrf = self._mrf([(self.part, 1)])
            first = 'dept_confirm' if 'manager' in levels else 'ir_approve'
            self.assertEqual((mrf.state, self._pending(mrf)), (first, set(levels)), levels)
            with self.assertRaises(AccessError):
                mrf.with_user(self.tech).action_warranty_approve()
            with self.assertRaises(AccessError):
                mrf.with_user(self.helpdesk_user).action_warranty_approve()
            if 'manager' in levels and len(levels) > 1:
                other = getattr(self, levels[-1])
                with self.assertRaises(AccessError):
                    mrf.with_user(other).action_warranty_approve()
            for level in sorted(levels, key=lambda lvl: lvl != 'manager'):
                mrf.with_user(getattr(self, level)).action_warranty_approve()
            self.assertEqual((mrf.state, mrf.approval_status), ('approve', 'approved'), levels)
            self.assertEqual(set(self._round(mrf).filtered(lambda l: l.state == 'skipped')
                                 .mapped('level')), {'manager', 'finance', 'gm'} - set(levels))

    def test_04_goodwill_needs_finance_and_gm(self):
        """Goodwill always needs Finance + GM (SRS 16.1), also without any matching rule: a
        clear configuration error, then the goodwill rule's approvers."""
        mrf = self._draft([(self.pipe, 1)])
        self.env.flush_all()
        mrf.with_user(self.approver_b)._warranty_decide_coverage(
            mrf.requisition_line_ids, 'goodwill', 'Key customer')
        self.env.flush_all()
        with self.assertRaisesRegex(UserError, 'Goodwill materials require Finance') as error:
            mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertIn('no matching rule', str(error.exception))
        self.assertEqual((mrf.state, mrf.approval_round), ('draft', 0))
        self._rule('F7 Goodwill', ('finance', 'gm'), goodwill_condition='goodwill')
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual((mrf.state, self._pending(mrf)), ('ir_approve', {'finance', 'gm'}))
        mrf.with_user(self.gm).action_warranty_approve()
        mrf.with_user(self.finance).action_warranty_approve()
        self.assertEqual(mrf.approval_status, 'approved')

    def test_05_reject_resubmit_revalidation(self):
        """Rejection -> Rejected (reason, history); Reset to New, changed quantity, Submit ->
        new round on the new amount; lines locked while submitted."""
        self._rule('F7 Manager', ('manager',))
        mrf = self._mrf([(self.part, 1)])
        with self.assertRaisesRegex(UserError, 'locked'):
            self._line(mrf, self.part).with_user(self.helpdesk_user).qty = 2
        mrf.with_user(self.manager)._warranty_reject('Use the spare from the van')
        self.assertEqual((mrf.state, mrf.approval_status), ('reject', 'rejected'))
        mrf.with_user(self.helpdesk_user).reset_draft()
        self._line(mrf, self.part).with_user(self.helpdesk_user).qty = 2
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual((mrf.approval_round, mrf.approval_routing_amount), (2, 37000))
        history = mrf.sudo().warranty_approval_ids
        first = history.filtered(lambda l: l.round == 1)
        self.assertEqual(first.filtered(lambda l: l.level == 'manager').state, 'rejected')
        self.assertEqual(set(first.filtered(lambda l: l.level != 'manager').mapped('state')),
                         {'skipped'})
        self.assertEqual(self._pending(mrf), {'manager'})

    # ------------------------------------------------------------------ D2 Not Covered quotation
    def test_06_mixed_quotation_after_approval(self):
        """Change request 2026-11-07: Not Covered -> quotation only after every required
        approval level (also when no rule explicitly approves Not Covered materials); the
        confirmed quotation releases and delivers the gas, the covered PCB is issued by the
        request's own picking; each line once."""
        self._rule('F7 Covered Manager', ('manager',), coverage_condition='covered')
        mrf = self._mrf([(self.part, 1), (self.gas, 2)])
        self.assertEqual(mrf.state, 'dept_confirm')
        self.assertFalse(mrf.can_create_parts_quotation)
        with self.assertRaisesRegex(UserError, 'waiting for approval'):
            self._quote(mrf)
        self.assertFalse(mrf.sudo().parts_quotation_ids)
        mrf.with_user(self.manager).action_warranty_approve()
        self.assertTrue(mrf.can_create_parts_quotation)
        order = self._quote(mrf)
        self.assertEqual((order.order_line.product_id, order.order_line.product_uom_qty),
                         (self.gas, 2))
        with self.assertRaisesRegex(UserError, 'no Not Covered line to quote'):
            self._quote(mrf)
        order.action_confirm()
        gas = self._line(mrf, self.gas)
        self.assertEqual(gas.chargeable_state, 'released')
        self._validate(order.picking_ids)
        self.assertEqual((order.picking_ids.state, gas.issued_qty), ('done', 2))
        mrf.with_user(self.store).action_warranty_fulfil()
        self.assertEqual(self._pickings(mrf).move_ids.product_id, self.part, 'no gas on it')

    def test_07_rule_explicitly_approving_not_covered(self):
        """A matching rule with a Not Covered condition and approval levels makes the quotation
        wait for the final approval."""
        self._rule('F7 Chargeable Manager', ('manager',), coverage_condition='not_covered')
        mrf = self._mrf([(self.gas, 1)])
        self.assertFalse(mrf.can_create_parts_quotation)
        with self.assertRaisesRegex(UserError, 'require the approval of Not Covered'):
            self._quote(mrf)
        mrf.with_user(self.manager).action_warranty_approve()
        self.assertTrue(mrf.can_create_parts_quotation)
        self.assertEqual(self._quote(mrf).order_line.product_id, self.gas)

    def test_08_rejected_request_blocks_confirmed_order(self):
        """A confirmed order never overrides a rejected request: Release Blocked, delivery
        refused, order kept (not cancelled); its lines keep product, quantity and coverage; the
        request cannot be cancelled while the order is confirmed; resubmitted -> released.
        Historical early quotation (before the change request of 2026-11-07)."""
        self._rule('F7 Covered Manager', ('manager',), coverage_condition='covered')
        mrf = self._mrf([(self.part, 1), (self.gas, 2)])
        order = self._historical_quote(mrf)
        order.action_confirm()
        gas = self._line(mrf, self.gas)
        mrf.with_user(self.manager)._warranty_reject('Wrong part')
        self.assertEqual((order.state, gas.chargeable_state), ('sale', 'blocked'))
        with self.assertRaisesRegex(UserError, 'not released'):
            self._validate(order.picking_ids)
        mrf.with_user(self.helpdesk_user).reset_draft()
        self.assertEqual(gas.chargeable_state, 'blocked')
        with self.assertRaisesRegex(UserError, 'confirmed customer order'):
            gas.with_user(self.helpdesk_user).qty = 5
        with self.assertRaisesRegex(UserError, 'confirmed customer order'):
            gas.with_user(self.helpdesk_user).unlink()
        with self.assertRaisesRegex(UserError, 'confirmed customer order'):
            mrf.with_user(self.helpdesk_user).action_cancel()
        part = self._line(mrf, self.part)
        part.with_user(self.helpdesk_user).qty = 2
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual((mrf.approval_round, gas.chargeable_state), (2, 'released'))
        self._validate(order.picking_ids)
        self.assertEqual(gas.issued_qty, 2)

    def test_09_withdraw_cancels_unconfirmed_quotation(self):
        """Withdraw / reject: quotations the customer has not confirmed are cancelled (logged);
        the line is To Quote again after the new submission, quoted again only after the new
        approval; no duplicate quotation. Historical early quotation (before 2026-11-07)."""
        self._rule('F7 Covered Manager', ('manager',), coverage_condition='covered')
        mrf = self._mrf([(self.part, 1), (self.gas, 1)])
        order = self._historical_quote(mrf)
        mrf.with_user(self.helpdesk_user).action_warranty_withdraw()
        self.assertEqual((mrf.state, order.state), ('draft', 'cancel'))
        self.assertTrue(any('cancelled' in (m.body or '') for m in mrf.message_ids))
        gas = self._line(mrf, self.gas)
        self.assertFalse(mrf.can_create_parts_quotation, 'New: not quoted')
        with self.assertRaisesRegex(UserError, 'need a submitted request'):
            self._quote(mrf)
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual(gas.chargeable_state, 'to_quote')
        self.assertFalse(mrf.can_create_parts_quotation, 'pending again')
        mrf.with_user(self.manager).action_warranty_approve()
        second = self._quote(mrf)
        self.assertEqual(mrf.sudo().parts_quotation_ids.filtered(
            lambda o: o.state != 'cancel'), second)

    def test_10_pending_draft_and_requisition_workflow_not_quoted(self):
        """Pending coverage blocks the submission (no premature charge); a New request is not
        quoted; the Requisition workflow (matrix off) quotes after the final approval only."""
        pending = self._draft([(self.pipe, 1), (self.gas, 1)])
        with self.assertRaisesRegex(UserError, 'pending'):
            pending.with_user(self.helpdesk_user).requisition_confirm()
        self.assertFalse(pending.can_create_parts_quotation)
        with self.assertRaisesRegex(UserError, 'need a submitted request'):
            self._quote(pending)
        self.company.warranty_mrf_approval_matrix = False
        vendor = self._mrf([(self.gas, 1)])
        self.assertEqual(vendor.state, 'dept_confirm')
        with self.assertRaisesRegex(UserError, 'Requisition workflow'):
            self._quote(vendor)

    # ------------------------------------------------------------------ D4 Stock available?
    def test_11_stock_loop(self):
        """YES / NO / Awaiting Stock / Recheck on the same request: free stock issued (lot
        respected), shortage with vendor -> RFQ, no stock and no vendor -> Awaiting Stock (note,
        one To-Do, notification); recheck creates nothing twice; replenishment -> issued."""
        lots = self.env['stock.lot'].create([{'name': name, 'product_id': self.box.id}
                                             for name in ('F7-L1', 'F7-L2')])
        self._add_stock(self.box, 5, lots[0])
        self._add_stock(self.box, 4, lots[1])
        self._add_stock(self.filter, 2)
        mrf = self._mrf([(self.filter, 2), (self.valve, 1), (self.motor, 1),
                         (self.box, 3, {'lot_ids': [(6, 0, lots[0].ids)]})])
        self.assertEqual(mrf.warranty_stock_status, 'partial')
        result = mrf.with_user(self.store).action_warranty_fulfil()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn(self.motor.display_name, result['params']['message'])
        picking = self._pickings(mrf)
        self.assertEqual(set(picking.move_ids.product_id.ids), {self.filter.id, self.box.id})
        self.assertEqual(mrf.purchase_order_ids.order_line.product_id, self.valve)
        valve, motor = self._line(mrf, self.valve), self._line(mrf, self.motor)
        self.assertIn(mrf.purchase_order_ids.name, valve.stock_wait_reason)
        self.assertIn('no vendor', motor.stock_wait_reason)
        self.assertEqual(mrf.warranty_stock_status, 'awaiting')
        todo = mrf.activity_ids.filtered(lambda a: 'Awaiting stock' in (a.summary or ''))
        self.assertEqual(todo.user_id, self.helpdesk_user, 'the requester')
        self.assertIn(mrf, self.Mrf.search([('warranty_stock_status', '=', 'awaiting')]))
        mrf.with_user(self.store).action_warranty_fulfil()
        todos = mrf.activity_ids.filtered(lambda a: 'Awaiting stock' in (a.summary or ''))
        self.assertEqual((len(self._pickings(mrf)), len(mrf.purchase_order_ids), len(todos)),
                         (1, 1, 1), 'nothing twice')
        box_move = picking.move_ids.filtered(lambda move: move.product_id == self.box)
        box_move.move_line_ids.lot_id = lots[1]
        with self.assertRaisesRegex(UserError, 'requested serial / lot'):
            self._validate(picking)
        box_move.move_line_ids.lot_id = lots[0]
        self._validate(picking)
        self._add_stock(self.motor, 1)
        mrf.with_user(self.store).action_warranty_fulfil()
        order = mrf.sudo().purchase_order_ids
        order.button_confirm()
        self._validate(order.picking_ids)
        mrf.with_user(self.store).action_warranty_fulfil()
        for remaining in self._pickings(mrf) - picking:
            self._validate(remaining)
        self.assertEqual(
            [(line.product_id.name, line.issue_state, line.outstanding_qty, line.in_issue_qty)
             for line in mrf.requisition_line_ids],
            [(product.name, 'issued', 0, 0)
             for product in (self.filter, self.valve, self.motor, self.box)])
        self.assertEqual(mrf.warranty_stock_status, 'issued')
        self.assertEqual(len(mrf.purchase_order_ids), 1)
        self.assertEqual(set(mrf.requisition_line_ids.mapped('issue_state')), {'issued'})

    def test_12_job_awaiting_parts_and_coordinator(self):
        """Awaiting Stock on a job: the Requisition Responsible gets the To-Do; Put Job on
        Awaiting Parts opens the existing hold wizard (In Progress jobs only); the job shows
        Awaiting Stock; nothing is put on hold automatically."""
        job = self._confirmed_job()
        responsible = self.env['hr.employee'].create({'name': 'F7 Store', 'user_id': self.store.id,
                                                      'company_id': self.company.id})
        mrf = self._draft([(self.motor, 1)], record=job)
        mrf.with_user(self.helpdesk_user).write({'requisiton_responsible_id': responsible.id})
        mrf.with_user(self.helpdesk_user).requisition_confirm()
        mrf.with_user(self.store).action_warranty_fulfil()
        todo = mrf.activity_ids.filtered(lambda a: 'Awaiting stock' in (a.summary or ''))
        self.assertEqual(todo.user_id, self.store)
        job.invalidate_recordset(['material_status'])
        self.assertEqual((job.material_status, job.state), ('shortage', 'confirmed'))
        self.assertEqual(dict(job._fields['material_status']._description_selection(self.env))
                         ['shortage'], 'Awaiting Stock')
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_service_job SET state = 'in_progress' WHERE id = %s",
                            (job.id,))
        job.invalidate_recordset(['state'])
        action = mrf.with_user(self.helpdesk_user).action_warranty_job_awaiting_parts()
        self.env[action['res_model']].with_user(self.helpdesk_user).with_context(
            **action['context']).create({'reason': 'Fan motor out of stock'}).action_apply()
        self.assertEqual(job.state, 'awaiting_parts')
        for user in (self.helpdesk_user, self.store):
            arch = self.Mrf.with_user(user).get_views([(False, 'form')])['views']['form']['arch']
            self.assertIn('warranty_stock_status', arch)
            self.assertIn('stock_wait_reason', arch)
        arch = self.Mrf.with_user(self.store).get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('Recheck Stock / Issue Remaining', arch)
        self.assertNotIn('action_warranty_job_awaiting_parts', arch, 'Helpdesk / FSM users only')
        arch = self.Mrf.with_user(self.helpdesk_user).get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertIn('action_warranty_job_awaiting_parts', arch)

    # ------------------------------------------------------------------ change request 2026-11-07
    def test_13_quotation_waits_for_full_approval(self):
        """Create Parts Quotation (MRF/000013 UAT): hidden and refused on the server while
        Manager or Finance / GM approval is pending; available when every level is approved or
        no approval is required; never for a fully covered request; sudo paths refused too."""
        self._rule('F7 Manager Finance', ('manager', 'finance'))
        mrf = self._mrf([(self.part, 1), (self.gas, 1)])
        self.assertEqual(mrf.state, 'dept_confirm')
        self.assertFalse(mrf.can_create_parts_quotation, 'Manager Approval pending')
        with self.assertRaisesRegex(UserError, 'waiting for approval'):
            self._quote(mrf)
        mrf.with_user(self.manager).action_warranty_approve()
        self.assertEqual((mrf.state, self._pending(mrf)), ('ir_approve', {'finance'}))
        self.assertFalse(mrf.can_create_parts_quotation, 'Finance / GM Approval pending')
        with self.assertRaisesRegex(UserError, 'waiting for approval'):
            self._quote(mrf)
        gas = self._line(mrf, self.gas)
        with self.assertRaisesRegex(UserError, 'waiting for approval'), \
                self.env.cr.savepoint():
            self.env['sale.order'].sudo().create({
                'partner_id': self.customer.id, 'warranty_mrf_id': mrf.id,
                'order_line': [(0, 0, {'product_id': self.gas.id, 'product_uom_qty': 1,
                                       'warranty_mrf_line_id': gas.id})]})
        self.assertFalse(mrf.sudo().parts_quotation_ids)
        mrf.with_user(self.finance).action_warranty_approve()
        self.assertEqual((mrf.state, mrf.approval_status), ('approve', 'approved'))
        self.assertTrue(mrf.can_create_parts_quotation, 'fully approved')
        order = self._quote(mrf)
        self.assertEqual(order.order_line.warranty_mrf_line_id, gas)
        self.assertFalse(mrf.can_create_parts_quotation, 'quoted: hidden')
        with self.assertRaisesRegex(UserError, 'no Not Covered line to quote'):
            self._quote(mrf)
        with self.assertRaisesRegex(Exception, 'already on another active quotation'):
            with self.env.cr.savepoint():
                self.env['sale.order'].sudo().create({
                    'partner_id': self.customer.id, 'warranty_mrf_id': mrf.id,
                    'order_line': [(0, 0, {'product_id': self.gas.id, 'product_uom_qty': 1,
                                           'warranty_mrf_line_id': gas.id})]})
        self.assertEqual(len(mrf.sudo().parts_quotation_ids), 1, 'no duplicate')

    def test_14_quotation_no_approval_rejected_withdrawn_covered(self):
        """No Approval Required -> quotation right after submission; Rejected, Withdrawn and
        Cancelled requests are not quoted; a fully covered request never shows the button."""
        self._rule('F7 Free', max_amount=5000)
        self._rule('F7 Manager', ('manager',), min_amount=5000)
        free = self._mrf([(self.gas, 1)])
        self.assertEqual((free.state, free.approval_status), ('approve', 'not_required'))
        self.assertTrue(free.can_create_parts_quotation)
        self.assertEqual(self._quote(free).order_line.product_id, self.gas)
        rejected = self._mrf([(self.part, 1), (self.gas, 1)])
        rejected.with_user(self.manager)._warranty_reject('Not needed')
        self.assertEqual(rejected.state, 'reject')
        self.assertFalse(rejected.can_create_parts_quotation)
        with self.assertRaisesRegex(UserError, 'need a submitted request'):
            self._quote(rejected)
        withdrawn = self._mrf([(self.part, 1), (self.gas, 1)])
        withdrawn.with_user(self.helpdesk_user).action_warranty_withdraw()
        self.assertEqual(withdrawn.state, 'draft')
        self.assertFalse(withdrawn.can_create_parts_quotation)
        with self.assertRaisesRegex(UserError, 'need a submitted request'):
            self._quote(withdrawn)
        withdrawn.sudo().state = 'cancel'
        with self.assertRaisesRegex(UserError, 'need a submitted request'):
            self._quote(withdrawn)
        self.assertFalse((rejected | withdrawn).sudo().parts_quotation_ids)
        covered = self._mrf([(self.filter, 1)])
        self.assertEqual(covered.state, 'approve')
        self.assertFalse(covered.can_create_parts_quotation, 'fully covered: hidden')
        with self.assertRaisesRegex(UserError, 'no Not Covered line to quote'):
            self._quote(covered)

    # ------------------------------------------------------------------ UAT fix 2026-11-07
    def _approved_mixed_sold(self):
        """MRF/000013 shape: mixed request, approved, parts quotation confirmed (Released)."""
        (self.part | self.gas).is_storable = True
        self._add_stock(self.part, 5)
        self._add_stock(self.gas, 5)
        self._rule('F7 Manager', ('manager',))
        mrf = self._mrf([(self.part, 1), (self.gas, 1)])
        mrf.with_user(self.manager).action_warranty_approve()
        self._quote(mrf).action_confirm()
        self.assertEqual((mrf.state, self._line(mrf, self.gas).chargeable_state),
                         ('approve', 'released'))
        return mrf

    def test_15_picking_destination_onchange(self):
        """UAT MRF/000013: changing the Picking Details destination of an approved mixed
        request with a confirmed quotation ran the onchange on NewId lines and failed sorting
        them ('<' not supported between NewId). Location-only changes keep the approval, the
        quotation release and the stock issue."""
        mrf = self._approved_mixed_sold()
        signature = mrf.approval_signature
        destination = self.env['stock.location'].create({
            'name': 'F7 Technician Stock 2', 'usage': 'internal',
            'location_id': self.warehouse.view_location_id.id})
        with Form(mrf.with_user(self.store)) as form:
            form.dest_location_id = destination
        self.assertEqual(mrf.dest_location_id, destination)
        self.assertEqual(mrf.approval_signature, signature, 'approval history unchanged')
        self.assertEqual(mrf._warranty_line_signature(), signature)
        self.assertFalse(mrf._warranty_approved_error())
        gas = self._line(mrf, self.gas)
        self.assertEqual(gas.chargeable_state, 'released')
        order = gas.sudo().sale_line_ids.order_id
        self._validate(order.picking_ids)
        self.assertEqual(gas.issued_qty, 1)
        mrf.with_user(self.store).action_warranty_fulfil()
        self.assertEqual(self._pickings(mrf).move_ids.product_id, self.part)

    def test_16_signature_on_unsaved_lines(self):
        """Signature of onchange records: saved lines read as NewId keep the stored signature;
        one or several unsaved lines never match it; a real material change still invalidates
        the approval and lines stay locked after submission."""
        mrf = self._approved_mixed_sold()
        signature = mrf.approval_signature
        snapshot = mrf.new(origin=mrf)
        snapshot.requisition_line_ids = mrf.requisition_line_ids.mapped(
            lambda line: line.new(origin=line))
        self.assertTrue(all(isinstance(line.id, NewId)
                            for line in snapshot.requisition_line_ids))
        self.assertEqual(snapshot._warranty_line_signature(), signature)
        self.assertFalse(snapshot._warranty_approved_error())
        self.assertEqual(snapshot.requisition_line_ids.mapped('chargeable_state'),
                         mrf.requisition_line_ids.mapped('chargeable_state'))
        Line = self.env['material.purchase.requisition.line']
        added = mrf.new(origin=mrf)
        added.requisition_line_ids = snapshot.requisition_line_ids | Line.new(
            {'product_id': self.filter.id, 'qty': 1, 'uom': self.filter.uom_id.id}) | Line.new(
            {'product_id': self.motor.id, 'qty': 2, 'uom': self.motor.uom_id.id})
        self.assertNotEqual(added._warranty_line_signature(), signature, 'two unsaved lines')
        self.assertIn('changed after submission', added._warranty_approved_error())
        blank = mrf.new(origin=mrf)
        blank.requisition_line_ids = snapshot.requisition_line_ids | Line.new({}) | Line.new({})
        self.assertNotEqual(blank._warranty_line_signature(), signature, 'empty unsaved lines')
        with self.assertRaisesRegex(UserError, 'locked'):
            self._line(mrf, self.part).with_user(self.helpdesk_user).qty = 3
        self._line(mrf, self.part).sudo().qty = 3
        self.assertIn('changed after submission', mrf._warranty_approved_error())
        self.env.invalidate_all()
        self.assertEqual(self._line(mrf, self.gas).chargeable_state, 'blocked')
