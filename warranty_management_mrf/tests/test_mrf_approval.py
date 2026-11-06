from datetime import timedelta

from markupsafe import escape

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import format_amount

from .common import WarrantyMrfCommon


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyMrfApproval(WarrantyMrfCommon):
    """Phase 5.3 - material approval matrix (design rev. 2, T3.1 - T3.23). Illustrative
    thresholds 25,000 / 100,000 (D-I). Outdoor PCB 18,500 is a covered item, Gas R410A 3,000 an
    excluded item, Copper Pipe 10 is not in the policy (Pending)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.warranty_mrf_approval_matrix = True
        Product = cls.env['product.product']
        cls.gas = Product.create({'name': 'Gas R410A', 'type': 'consu', 'standard_price': 3000})
        cls.pipe = Product.create({'name': 'Copper Pipe', 'type': 'consu', 'standard_price': 10})
        cls.item_pcb.product_id = cls.part
        cls.item_gas.product_id = cls.gas
        cls.manager = cls._user('mrf_appr_manager')
        cls.finance = cls._user('mrf_appr_finance')
        cls.gm = cls._user('mrf_appr_gm')
        cls.store = cls._user('mrf_store', 'material_purchase_requisitions.group_purchase_requisition_user')
        cls.dept = cls._user('mrf_dept', 'material_purchase_requisitions.group_purchase_requisition_department')
        cls.Rule = cls.env['warranty.mrf.approval.rule']
        cls.company.warranty_mrf_dest_location_id = cls.default_tech_location
        cls.env['stock.quant']._update_available_quantity(cls.part, cls.warehouse.lot_stock_id, 20)

    # ------------------------------------------------------------------ helpers
    def _rule(self, name, levels=(), users=None, **vals):
        users = users or {}
        values = {'name': name, 'company_id': self.company.id}
        if not levels:
            values['no_approval'] = True
        for level in levels:
            default = {'manager': self.manager, 'finance': self.finance, 'gm': self.gm}[level]
            values['%s_required' % level] = True
            values['%s_user_ids' % level] = [(6, 0, users.get(level, default).ids)]
        values.update(vals)
        return self.Rule.create(values)

    def _matrix(self):
        """Illustrative rules of design 3.4."""
        self._rule('Low value', max_amount=25000)
        self._rule('Level 1', ('manager', 'finance'), min_amount=25000, max_amount=100000)
        self._rule('High value', ('manager', 'finance', 'gm'), min_amount=100000)

    def _mrf(self, lines, case=None, user=None):
        """lines: [(product, qty)]"""
        user = user or self.helpdesk_user
        case = case or self._approved()
        action = case.with_user(user).action_create_material_request()
        return self.Mrf.with_user(user).with_context(**action['context']).create({
            'requisition_line_ids': [(0, 0, {
                'product_id': product.id, 'description': product.name, 'qty': qty,
                'uom': product.uom_id.id, 'requisition_type': 'internal'})
                for product, qty in lines],
        })

    def _submit(self, mrf, user=None):
        mrf.with_user(user or self.helpdesk_user).requisition_confirm()
        return mrf

    def _round(self, mrf, round_no=None):
        lines = mrf.sudo().warranty_approval_ids
        return lines.filtered(lambda line: line.round == (round_no or mrf.approval_round))

    def _level(self, mrf, level):
        return self._round(mrf).filtered(lambda line: line.level == level)

    def _approve(self, mrf, user):
        mrf.with_user(user).action_warranty_approve()

    # ------------------------------------------------------------------ T3.1 / T3.2
    def test_01_rule_matching_and_routing_amount(self):
        """T3.1 / T3.2: routing amount = all lines (D-A), each at max(entered, product cost)
        (D-F); amount boundaries; low value -> explicit No Approval Required rule."""
        self._matrix()
        low = self._submit(self._mrf([(self.part, 1)]))
        self.assertEqual((low.state, low.approval_status, low.approval_routing_amount),
                         ('approve', 'approved', 18500))
        self.assertEqual(self._round(low).level, 'none')
        self.assertFalse(low.approved_by_id, 'no approving person for a No Approval rule')
        mixed = self._submit(self._mrf([(self.part, 1), (self.gas, 3)]))
        self.assertEqual((mixed.approval_routing_amount, mixed.approval_covered_amount,
                          mixed.approval_not_covered_amount), (27500, 18500, 9000))
        self.assertEqual(mixed.state, 'dept_confirm')
        self.assertEqual(set(self._round(mixed).filtered(lambda l: l.state == 'pending')
                             .mapped('level')), {'manager', 'finance'})
        lowered = self._mrf([(self.part, 2)])
        line = lowered.requisition_line_ids
        line.with_user(self.helpdesk_user).estimated_unit_cost = 1000
        self.assertEqual((line.estimated_cost, line.routing_cost), (2000, 37000))
        self._submit(lowered)
        self.assertEqual(lowered.approval_routing_amount, 37000)
        self.assertEqual(line.estimated_unit_cost, 1000, 'entered value preserved')
        boundary = self.env['product.product'].create(
            {'name': 'Compressor', 'type': 'consu', 'standard_price': 25000})
        self.policy.covered_item_ids |= self.env['warranty.coverage.item'].create(
            {'name': 'Compressor', 'product_id': boundary.id})
        exact = self._submit(self._mrf([(boundary, 1)]))
        self.assertEqual(exact.state, 'dept_confirm', '25,000 is Level 1 (minimum inclusive)')

    def test_02_rule_conditions(self):
        """T3.1: coverage, goodwill, category (child) and product conditions."""
        mrf = self._mrf([(self.part, 1), (self.gas, 1)])
        lines = mrf.requisition_line_ids
        child = self.env['product.category'].create(
            {'name': 'Child', 'parent_id': self.part.categ_id.id})
        self.gas.categ_id = child
        rule = self._rule('Probe', ('manager',))
        cases = [
            ({'coverage_condition': 'covered'}, True),
            ({'coverage_condition': 'not_covered'}, True),
            ({'coverage_condition': 'only_not_covered'}, False),
            ({'coverage_condition': 'any', 'goodwill_condition': 'goodwill'}, False),
            ({'goodwill_condition': 'any', 'categ_ids': [(6, 0, child.ids)]}, True),
            ({'categ_ids': [(6, 0, child.parent_id.ids)]}, True),
            ({'categ_ids': [(5,)], 'product_ids': [(6, 0, self.pipe.ids)]}, False),
            ({'product_ids': [(6, 0, self.part.ids)]}, True),
            ({'product_ids': [(5,)], 'min_amount': 30000}, False),
            ({'min_amount': 0, 'max_amount': 21500}, False),
            ({'max_amount': 21501}, True),
        ]
        for vals, expected in cases:
            rule.write(vals)
            self.assertEqual(rule._matches(21500, lines), expected, vals)
        with self.assertRaises(ValidationError):
            self.Rule.create({'name': 'Nothing', 'company_id': self.company.id})
        with self.assertRaises(ValidationError):
            self._rule('Both', ('manager',), no_approval=True)
        with self.assertRaises(ValidationError):
            self.Rule.create({'name': 'No users', 'company_id': self.company.id,
                              'finance_required': True})

    # ------------------------------------------------------------------ T3.3 - T3.5
    def test_03_no_rule_combination_and_branch(self):
        """T3.5: no matching rule -> submit refused (no auto-approval); a No Approval rule plus
        a Manager rule -> Manager (strictest, D-C); a parent-company rule applies to a branch
        request, a branch rule does not apply to the parent (D-B, Q1)."""
        mrf = self._mrf([(self.part, 1)])
        with self.assertRaisesRegex(UserError, 'No material approval rule matches'):
            self._submit(mrf)
        self.assertEqual((mrf.state, mrf.approval_round), ('draft', 0))
        self._rule('Everything free')
        self._rule('PCB needs manager', ('manager',), product_ids=[(6, 0, self.part.ids)])
        self._submit(mrf)
        self.assertEqual(mrf.state, 'dept_confirm')
        self.assertEqual(self._round(mrf).filtered(lambda l: l.state == 'pending').level,
                         'manager')
        branch = self.env['res.company'].create({'name': 'Branch Galle',
                                                 'parent_id': self.company.id})
        self.manager.company_ids |= branch
        branch_rule = self.Rule.create({'name': 'Branch GM', 'company_id': branch.id,
                                        'gm_required': True,
                                        'gm_user_ids': [(6, 0, self.manager.ids)]})
        self.assertEqual(self.company.parent_ids, self.company)
        self.assertIn(self.company, branch.parent_ids)
        self.assertNotIn(branch_rule, self.Rule.search(
            [('company_id', 'in', self.company.parent_ids.ids)]))
        self.assertIn(branch_rule, self.Rule.search([('company_id', 'in', branch.parent_ids.ids)]))

    # ------------------------------------------------------------------ T3.6 - T3.8
    def test_04_manager_then_finance(self):
        """T3.6 / T3.7: Level 1 -> Manager first (Finance refused before), then Finance ->
        Approved (vendor Approve by the bridge, D-O); To-Dos; notifications (D-P)."""
        self._matrix()
        mrf = self._submit(self._mrf([(self.part, 2)]))
        self.assertEqual((mrf.warranty_mrf_status, mrf.approval_status), ('manager', 'submitted'))
        manager_line = self._level(mrf, 'manager')
        self.assertEqual(manager_line.activity_ids.user_id, self.manager)
        self.assertFalse(self._level(mrf, 'finance').activity_ids)
        self.assertFalse(mrf.with_user(self.finance).can_warranty_approve)
        with self.assertRaises(AccessError):
            self._approve(mrf, self.finance)
        self.assertTrue(mrf.with_user(self.manager).can_warranty_approve)
        self._approve(mrf, self.manager)
        self.assertEqual((mrf.state, mrf.approval_status), ('ir_approve', 'manager_approved'))
        self.assertEqual((manager_line.state, manager_line.user_id), ('approved', self.manager))
        self.assertFalse(manager_line.activity_ids.exists().filtered('active'))
        self.assertEqual(self._level(mrf, 'finance').activity_ids.user_id, self.finance)
        self._approve(mrf, self.finance)
        self.assertEqual((mrf.state, mrf.approved_by_id, mrf.approved_amount),
                         ('approve', self.finance, 37000))
        self.assertEqual(self._level(mrf, 'gm').state, 'skipped')
        notice = mrf.message_ids.filtered(lambda m: 'approved (round 1' in (m.body or ''))
        self.assertIn(self.helpdesk_user.partner_id, notice.partner_ids)
        self.assertTrue(any('approved (round 1)' in (m.body or '')
                            for m in mrf.warranty_case_id.message_ids))

    def test_05_finance_only_and_high_value(self):
        """T3.6: Finance-only rule -> Manager skipped, straight to Finance/GM Approval.
        T3.8: high value -> Manager, then GM and Finance in any order (D-N)."""
        self._rule('Finance only', ('finance',))
        mrf = self._submit(self._mrf([(self.part, 1)]))
        self.assertEqual(mrf.state, 'ir_approve')
        self.assertEqual(self._level(mrf, 'manager').state, 'skipped')
        self._approve(mrf, self.finance)
        self.assertEqual(mrf.state, 'approve')
        self.Rule.search([]).active = False
        self._matrix()
        high = self._submit(self._mrf([(self.part, 6)]))
        self.assertEqual(high.approval_routing_amount, 111000)
        with self.assertRaises(AccessError):
            self._approve(high, self.gm)
        self._approve(high, self.manager)
        self._approve(high, self.gm)
        self.assertEqual((high.state, high.approval_status), ('ir_approve', 'gm_approved'))
        self._approve(high, self.finance)
        self.assertEqual(high.state, 'approve')

    # ------------------------------------------------------------------ T3.9
    def test_06_goodwill_finance_and_gm(self):
        """T3.9 (D-G, Q8, Q9): goodwill always needs Finance + GM; Manager only when a rule
        requires it; the coverage reviewer may approve; goodwill without configured approvers
        is refused."""
        self._rule('Manager for all', ('manager',))
        mrf = self._mrf([(self.pipe, 1)])
        action = mrf.with_user(self.approver_b).action_decide_coverage()
        self.env['warranty.mrf.coverage.wizard'].with_user(self.approver_b).with_context(
            **action['context']).create({'decision': 'goodwill', 'reason': 'Key customer'}
                                        ).action_apply()
        with self.assertRaisesRegex(UserError, 'Goodwill materials require Finance'):
            self._submit(mrf)
        self._rule('Goodwill', ('finance', 'gm'), goodwill_condition='goodwill',
                   users={'finance': self.approver_b})
        self._submit(mrf)
        self.assertEqual(set(self._round(mrf).filtered(lambda l: l.state == 'pending')
                             .mapped('level')), {'manager', 'finance', 'gm'})
        self._approve(mrf, self.manager)
        self._approve(mrf, self.approver_b)
        self._approve(mrf, self.gm)
        self.assertEqual(mrf.state, 'approve')
        self.assertEqual(self._level(mrf, 'finance').user_id, self.approver_b)

    # ------------------------------------------------------------------ T3.10
    def test_07_separation_of_duties(self):
        """T3.10 (D-D): requester / creator / submitter removed from the approvers; a level
        without other approvers blocks the submission; one person one level; an approver no
        longer allowed in the company is removed."""
        self._rule('Self only', ('manager',), users={'manager': self.helpdesk_user})
        mrf = self._mrf([(self.part, 1)])
        with self.assertRaisesRegex(UserError, 'no available approver'):
            self._submit(mrf)
        self.Rule.search([]).active = False
        self._rule('Same person', ('finance', 'gm'), users={'finance': self.finance,
                                                            'gm': self.finance})
        with self.assertRaisesRegex(UserError, 'different approver for every'):
            self._submit(mrf)
        self.Rule.search([]).active = False
        both = self.finance | self.gm
        self._rule('Shared lists', ('manager', 'finance', 'gm'),
                   users={'manager': self.manager | self.helpdesk_user, 'finance': both, 'gm': both})
        self.manager.company_ids = self.other_company | self.company
        self._submit(mrf)
        self.assertEqual(self._level(mrf, 'manager').allowed_user_ids, self.manager)
        with self.assertRaises(AccessError):
            self._approve(mrf, self.helpdesk_user)
        self._approve(mrf, self.manager)
        self._approve(mrf, self.finance)
        with self.assertRaisesRegex(AccessError, 'already approved a level'):
            self._approve(mrf, self.finance)
        self._approve(mrf, self.gm)
        self.assertEqual(mrf.state, 'approve')
        # Removed from the company before submission: not an approver.
        self.manager.write({'company_ids': [(6, 0, self.other_company.ids)],
                            'company_id': self.other_company.id})
        other = self._mrf([(self.part, 1)])
        with self.assertRaisesRegex(UserError, 'no available approver'):
            self._submit(other)

    # ------------------------------------------------------------------ T3.11 / T3.12
    def test_08_vendor_actions_and_writes_guarded(self):
        """T3.11 / T3.12: vendor methods and direct writes cannot bypass the matrix, also for
        vendor group members and in superuser mode for the approval steps."""
        self._matrix()
        mrf = self._submit(self._mrf([(self.part, 2)]))
        with self.assertRaisesRegex(UserError, 'approval matrix'):
            mrf.with_user(self.dept).manager_approve()
        with self.assertRaisesRegex(UserError, 'approval matrix'):
            mrf.sudo().manager_approve()
        with self.assertRaisesRegex(UserError, 'approval matrix'):
            mrf.with_user(self.store).user_approve()
        with self.assertRaisesRegex(UserError, 'approval matrix'):
            mrf.with_user(self.dept).requisition_reject()
        with self.assertRaisesRegex(UserError, 'approved Material Requests only'):
            mrf.with_user(self.store).request_stock()
        with self.assertRaises(UserError):
            mrf.with_user(self.store).action_received()
        with self.assertRaisesRegex(UserError, 'reset to New only'):
            mrf.with_user(self.helpdesk_user).reset_draft()
        with self.assertRaisesRegex(UserError, 'cancelled only'):
            mrf.with_user(self.helpdesk_user).action_cancel()
        for vals in ({'state': 'approve'}, {'approve_manager_id': False},
                     {'approval_round': 5}, {'approved_amount': 1}):
            with self.assertRaisesRegex(UserError, 'set by the approval workflow'):
                mrf.with_user(self.helpdesk_user).write(vals)
        with self.assertRaisesRegex(UserError, 'locked after submission'):
            mrf.with_user(self.helpdesk_user).write({'reason': 'changed'})
        with self.assertRaises(AccessError):
            mrf.with_user(self.helpdesk_user).write({'location_id': self.tech_location.id})
        mrf.with_user(self.store).write({'dest_location_id': self.default_tech_location.id})
        self.assertEqual(mrf.dest_location_id, self.default_tech_location)
        case = self._approved()
        action = case.with_user(self.helpdesk_user).action_create_material_request()
        with self.assertRaisesRegex(UserError, 'created as New'):
            self.Mrf.with_user(self.helpdesk_user).with_context(**action['context']).create(
                {'state': 'approve'})
        self.assertEqual(mrf.state, 'dept_confirm')

    def test_09_lines_locked_after_submission(self):
        """T3.13: product, quantity, UoM, estimated cost, coverage, add / delete refused after
        Submit; Requisition users still set the line type until the picking exists."""
        self._matrix()
        mrf = self._submit(self._mrf([(self.part, 2)]))
        line = mrf.requisition_line_ids
        for vals in ({'qty': 1}, {'estimated_unit_cost': 1},
                     {'uom': self.env.ref('uom.product_uom_dozen').id},
                     {'product_id': self.pipe.id}):
            with self.assertRaisesRegex(UserError, 'locked'):
                line.with_user(self.helpdesk_user).write(vals)
        with self.assertRaisesRegex(UserError, 'locked'):
            line.with_user(self.store).write({'qty': 3})
        with self.assertRaisesRegex(UserError, 'locked'):
            line.with_user(self.helpdesk_user).write({'requisition_type': 'purchase'})
        line.with_user(self.store).write({'requisition_type': 'purchase'})
        with self.assertRaisesRegex(UserError, 'locked'):
            line.with_user(self.helpdesk_user).unlink()
        self.assertEqual((line.qty, mrf.approval_routing_amount), (2, 37000))

    # ------------------------------------------------------------------ T3.14 - T3.16
    def test_10_reject_reset_resubmit(self):
        """T3.14 / T3.16: reject needs a reason, notifies, closes To-Dos; requester / creator
        resets; resubmission = round 2 with all levels again; round 1 kept (D-K)."""
        self._matrix()
        mrf = self._submit(self._mrf([(self.part, 2)]))
        with self.assertRaisesRegex(UserError, 'reason is required'):
            mrf.with_user(self.manager)._warranty_reject('  ')
        action = mrf.with_user(self.manager).action_warranty_reject()
        self.env['warranty.mrf.reject.wizard'].with_user(self.manager).with_context(
            **action['context']).create({'reason': 'Use refurbished PCB'}).action_reject()
        self.assertEqual((mrf.state, mrf.approval_status), ('reject', 'rejected'))
        round1 = self._round(mrf, 1)
        self.assertEqual(self._level(mrf, 'manager').state, 'rejected')
        self.assertEqual(self._level(mrf, 'finance').state, 'superseded')
        self.assertFalse(round1.activity_ids.exists().filtered('active'))
        notice = mrf.message_ids.filtered(lambda m: 'Use refurbished PCB' in (m.body or ''))
        self.assertIn(self.helpdesk_user.partner_id, notice.partner_ids)
        with self.assertRaises(AccessError):
            mrf.with_user(self.approver_b).reset_draft()
        mrf.with_user(self.helpdesk_user).reset_draft()
        mrf.requisition_line_ids.with_user(self.helpdesk_user).qty = 1
        self._submit(mrf)
        self.assertEqual(mrf.approval_round, 2)
        self.assertEqual(mrf.approval_routing_amount, 18500)
        self.assertEqual(sorted(self._round(mrf, 1).mapped('state')),
                         ['rejected', 'skipped', 'superseded'], 'round 1 history kept')
        self.assertEqual(mrf.state, 'approve', 'round 2: low value, No Approval rule')

    def test_11_withdraw(self):
        """T3.15 (D-J, Q2): requester / creator withdraw before the final approval (also after
        the manager approved); other Helpdesk users cannot; history kept."""
        self._matrix()
        mrf = self._submit(self._mrf([(self.part, 2)]))
        self._approve(mrf, self.manager)
        self.assertFalse(mrf.with_user(self.approver_b).can_warranty_withdraw)
        with self.assertRaises(AccessError):
            mrf.with_user(self.approver_b).action_warranty_withdraw()
        self.assertTrue(mrf.with_user(self.helpdesk_user).can_warranty_withdraw)
        mrf.with_user(self.helpdesk_user).action_warranty_withdraw()
        self.assertEqual(mrf.state, 'draft')
        self.assertEqual(self._level(mrf, 'manager').state, 'approved')
        self.assertEqual(self._level(mrf, 'finance').state, 'withdrawn')
        self.assertFalse(self._round(mrf).activity_ids.exists().filtered('active'))
        self._submit(mrf)
        self.assertEqual(mrf.approval_round, 2)
        self._approve(mrf, self.manager)
        self._approve(mrf, self.finance)
        with self.assertRaises(AccessError):
            mrf.with_user(self.helpdesk_user).action_warranty_withdraw()

    # ------------------------------------------------------------------ T3.17
    def test_12_snapshot(self):
        """T3.17 (D-H): rule changes after submission do not change the route."""
        self._matrix()
        mrf = self._submit(self._mrf([(self.part, 2)]))
        level1 = self.Rule.search([('name', '=', 'Level 1')])
        level1.write({'manager_user_ids': [(6, 0, self.gm.ids)], 'finance_required': False})
        self.assertEqual(self._level(mrf, 'manager').allowed_user_ids, self.manager)
        with self.assertRaises(AccessError):
            self._approve(mrf, self.gm)
        self._approve(mrf, self.manager)
        self._approve(mrf, self.finance)
        self.assertEqual(mrf.state, 'approve')

    # ------------------------------------------------------------------ T3.18 / T3.19
    def test_13_release_guards(self):
        """T3.18 / T3.19 (D-L): pickings / RFQs only for fully approved requests without Not
        Covered lines; manual pickings and RFQs linked to other warranty requests refused, also
        in superuser mode."""
        self._matrix()
        approved = self._submit(self._mrf([(self.part, 1)]))
        with self.assertRaises(AccessError):
            approved.with_user(self.helpdesk_user).request_stock()
        approved.with_user(self.store).request_stock()
        self.assertEqual(approved.state, 'stock')
        picking = self.env['stock.picking'].search([('custom_requisition_id', '=', approved.id)])
        self.assertEqual(picking.move_ids.product_id, self.part)
        mixed = self._submit(self._mrf([(self.gas, 1)]))
        self.assertEqual(mixed.state, 'approve')
        with self.assertRaisesRegex(UserError, 'Not Covered'):
            mixed.with_user(self.store).request_stock()
        waiting = self._submit(self._mrf([(self.part, 2)]))
        Picking = self.env['stock.picking'].sudo()
        vals = {'picking_type_id': self.warehouse.int_type_id.id,
                'location_id': self.warehouse.lot_stock_id.id,
                'location_dest_id': self.tech_location.id}
        for mrf in (waiting, mixed):
            with self.assertRaises(UserError):
                Picking.create(dict(vals, custom_requisition_id=mrf.id))
            with self.assertRaises(UserError):
                self.env['purchase.order'].sudo().create(
                    {'partner_id': self.customer.id, 'custom_requisition_id': mrf.id})
        with self.assertRaises(UserError):
            picking.sudo().write({'custom_requisition_id': waiting.id})
        standalone = self._standalone()
        Picking.create(dict(vals, custom_requisition_id=standalone.id))
        # Received only when issued (Phase 5.5, tested there with validation).
        with self.assertRaisesRegex(UserError, 'not completely issued'):
            approved.with_user(self.store).action_received()
        approved.sudo().write({'state': 'receive'})
        with self.assertRaisesRegex(UserError, 'reset to New only'):
            approved.with_user(self.helpdesk_user).reset_draft()

    # ------------------------------------------------------------------ T3.20 - T3.23
    def test_14_deadline(self):
        """T3.20 (D-M): To-Do deadline from the company setting."""
        self._matrix()
        self.company.warranty_mrf_approval_deadline_days = 3
        mrf = self._submit(self._mrf([(self.part, 2)]))
        activity = self._level(mrf, 'manager').activity_ids
        self.assertEqual(activity.date_deadline,
                         fields.Date.context_today(mrf) + timedelta(days=3))

    def test_15_matrix_off(self):
        """T3.21 (D-E): matrix off -> vendor 2-step workflow with separation of duties and the
        state / release guards."""
        self.company.warranty_mrf_approval_matrix = False
        mrf = self._submit(self._mrf([(self.part, 1)]))
        self.assertEqual((mrf.state, mrf.warranty_approval_mode), ('dept_confirm', 'vendor'))
        self.helpdesk_user.groups_id |= self.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_department')
        with self.assertRaises(AccessError):
            mrf.with_user(self.helpdesk_user).manager_approve()
        self.dept.groups_id |= self.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        mrf.with_user(self.dept).manager_approve()
        self.assertEqual(mrf.state, 'ir_approve')
        with self.assertRaisesRegex(AccessError, 'another person'):
            mrf.with_user(self.dept).user_approve()
        mrf.with_user(self.store).user_approve()
        self.assertEqual((mrf.state, mrf.approved_by_id), ('approve', self.store))
        mrf.with_user(self.store).request_stock()
        self.assertEqual(mrf.state, 'stock')
        self.assertTrue(self.env['res.company'].create({'name': 'New Co'}).warranty_mrf_approval_matrix)

    def test_16_standalone_unchanged(self):
        """T3.22 (control 5): standalone requests keep the vendor workflow (no rules needed,
        group-based buttons, direct state writes as before)."""
        self._matrix()
        standalone = self._standalone()
        standalone.write({
            'location_id': self.warehouse.lot_stock_id.id,
            'dest_location_id': self.tech_location.id,
            'custom_picking_type_id': self.warehouse.int_type_id.id,
            'requisition_line_ids': [(0, 0, {
            'product_id': self.part.id, 'description': 'PCB', 'qty': 10,
            'uom': self.part.uom_id.id, 'requisition_type': 'internal'})]})
        standalone.with_user(self.helpdesk_user).requisition_confirm()
        self.assertEqual(standalone.state, 'dept_confirm')
        self.assertFalse(standalone.approval_round)
        standalone.with_user(self.dept).manager_approve()
        standalone.with_user(self.store).user_approve()
        standalone.with_user(self.store).request_stock()
        self.assertEqual(standalone.state, 'stock')
        standalone.with_user(self.helpdesk_user).action_received()
        self.assertEqual(standalone.state, 'receive')
        self.assertFalse(standalone.warranty_mrf_status)

    def test_17_approver_access_and_views(self):
        """T3.23 (requirement 10): a named approver reads the routed request, its lines and its
        history, cannot edit it and does not see other requests; views render."""
        self._matrix()
        mrf = self._submit(self._mrf([(self.part, 2)]))
        other = self._mrf([(self.part, 2)])
        Mrf = self.Mrf.with_user(self.finance)
        self.assertEqual(Mrf.search([('id', 'in', (mrf | other).ids)]), mrf)
        self.assertTrue(mrf.with_user(self.finance).requisition_line_ids.read(['qty']))
        self.assertEqual(len(mrf.with_user(self.finance).warranty_approval_ids), 3)
        with self.assertRaises(AccessError):
            mrf.with_user(self.finance).check_access('write')
        with self.assertRaises(AccessError):
            self._round(mrf).with_user(self.manager).write({'state': 'approved'})
        with self.assertRaises(AccessError):
            self._round(mrf).with_user(self.helpdesk_user).unlink()
        for user in (self.helpdesk_user, self.finance, self.store, self.tech):
            views = self.env['material.purchase.requisition'].with_user(user).get_views(
                [(False, 'form'), (False, 'list'), (False, 'search')])
            self.assertIn('warranty_approval_ids', views['views']['form']['arch'])
            self.env['warranty.mrf.reject.wizard'].with_user(user).get_views([(False, 'form')])
        self.env['warranty.mrf.approval.rule'].get_views([(False, 'form'), (False, 'list')])
        settings = self.env['res.config.settings'].get_views([(False, 'form')])
        self.assertIn('warranty_mrf_approval_matrix', settings['views']['form']['arch'])

    def test_18_legacy_and_unlink(self):
        """Requirement 9 / Q10: a warranty request submitted without an approval round is never
        approved or released; it can be withdrawn; requests with a history are not deleted."""
        legacy = self._mrf([(self.part, 1)])
        legacy.sudo().write({'state': 'approve'})
        self.assertTrue(legacy.warranty_approval_legacy)
        with self.assertRaisesRegex(UserError, 'not approved through the warranty'):
            legacy.with_user(self.store).request_stock()
        with self.assertRaisesRegex(UserError, 'before the warranty approval workflow'):
            legacy.with_user(self.store).user_approve()
        legacy.with_user(self.helpdesk_user).action_warranty_withdraw()
        self.assertEqual(legacy.state, 'draft')
        self._matrix()
        submitted = self._submit(self._mrf([(self.part, 2)]))
        submitted.with_user(self.helpdesk_user).action_warranty_withdraw()
        with self.assertRaisesRegex(UserError, 'approval history cannot be deleted'):
            submitted.with_user(self.helpdesk_user).unlink()
        fresh = self._mrf([(self.part, 1)])
        fresh.with_user(self.helpdesk_user).unlink()

    # ------------------------------------------------------------------ approval UI (5.3)
    def _goodwill(self, mrf, product=None):
        # As in the UI, creation, coverage decision and submission are separate transactions:
        # flushing keeps a later failed submission (assertRaises savepoint) from undoing them.
        self.env.flush_all()
        line = mrf.requisition_line_ids.filtered(
            lambda rec: rec.product_id == (product or self.pipe))
        mrf.with_user(self.approver_b)._warranty_decide_coverage(line, 'goodwill', 'Key customer')
        self.env.flush_all()

    def test_19_route_error_messages(self):
        """Every route problem names the level, the rules, the approvers and why each one is
        excluded; the separation-of-duties rules are unchanged."""
        mrf = self._mrf([(self.pipe, 1)])
        self._goodwill(mrf)
        rule = self._rule('Low Value', ('finance',), users={'finance': self.helpdesk_user})
        # MRF/000004: the only Finance approver is the requester / creator / submitter.
        with self.assertRaisesRegex(UserError, 'no available approver') as error:
            self._submit(mrf)
        message = str(error.exception)
        for text in ('Finance approval', 'Low Value', self.helpdesk_user.name, 'requester',
                     'creator', 'submitter'):
            self.assertIn(text, message)
        # The only approver submits the request himself.
        rule.finance_user_ids = self.finance
        analysis = mrf._warranty_route_analysis(submitter=self.finance)
        self.assertIn('%s (submitter)' % self.finance.name, analysis['errors'][0])
        # Valid Finance, but goodwill also needs GM: the missing GM rule is explained.
        analysis = mrf.with_user(self.helpdesk_user)._warranty_route_analysis()
        self.assertEqual(len(analysis['errors']), 1)
        self.assertIn('Goodwill materials require GM approval', analysis['errors'][0])
        self.assertIn(self.pipe.display_name, analysis['errors'][0])
        self.assertIn('Low Value', analysis['errors'][0])
        # Archived and company exclusions are named.
        rule.write({'gm_required': True, 'gm_user_ids': [(6, 0, self.gm.ids)]})
        self.finance.active = False
        self.gm.write({'company_ids': [(6, 0, (self.company | self.other_company).ids)],
                       'company_id': self.other_company.id})
        self.gm.write({'company_ids': [(6, 0, self.other_company.ids)]})
        with self.assertRaisesRegex(UserError, 'no available approver') as error:
            self._submit(mrf)
        message = str(error.exception)
        self.assertIn('archived user', message)
        self.assertIn('not allowed in %s' % self.company.name, message)
        self.assertIn('GM approval', message)
        self.finance.active = True
        self.gm.write({'company_ids': [(6, 0, (self.company | self.other_company).ids)],
                       'company_id': self.company.id})
        # One person for both goodwill levels: distinct approvers required, eligible listed.
        rule.gm_user_ids = self.finance
        with self.assertRaisesRegex(UserError, 'different approver for every') as error:
            self._submit(mrf)
        self.assertIn('Finance: %s; GM: %s' % (self.finance.name, self.finance.name),
                      str(error.exception))
        self.assertEqual((mrf.state, mrf.approval_round), ('draft', 0))
        rule.gm_user_ids = self.gm
        self._submit(mrf)
        self.assertEqual(set(self._round(mrf).filtered(lambda l: l.state == 'pending')
                             .mapped('level')), {'finance', 'gm'})

    def test_20_check_route_preview(self):
        """Check Approval Route: read-only preview (rules, amount, levels, eligible / excluded
        approvers, blocking reasons) for New warranty requests only; Submit saves the route."""
        mrf = self._mrf([(self.pipe, 1), (self.part, 1)])
        user_mrf = mrf.with_user(self.helpdesk_user)
        can_submit, html = user_mrf._warranty_route_preview()
        self.assertFalse(can_submit)
        self.assertIn('pending', html)
        self._goodwill(mrf)
        self._rule('Low Value', ('finance',), max_amount=25000)
        self._rule('High Value', ('manager',), min_amount=25000)
        before = (mrf.write_date, len(mrf.message_ids), len(mrf.activity_ids))
        action = user_mrf.action_warranty_check_route()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        html = str(wizard.preview_html)
        self.assertFalse(wizard.can_submit)
        amount = format_amount(self.env, 18510, self.company.currency_id)
        for text in ('cannot be submitted', 'Low Value', 'High Value', str(escape(amount)),
                     'Goodwill materials require GM approval', self.finance.name):
            self.assertIn(text, html)
        self.assertEqual((mrf.write_date, len(mrf.message_ids), len(mrf.activity_ids)), before)
        self.assertEqual((mrf.state, mrf.approval_round, mrf.warranty_approval_ids),
                         ('draft', 0, self.env['warranty.mrf.approval']))
        self._rule('Goodwill', ('finance', 'gm'), goodwill_condition='goodwill',
                   users={'finance': self.approver_b})
        can_submit, html = user_mrf._warranty_route_preview()
        self.assertTrue(can_submit)
        for text in ('can be submitted with this route', self.approver_b.name, self.gm.name,
                     'Not required: Manager'):
            self.assertIn(text, html)
        self.company.warranty_mrf_approval_matrix = False
        can_submit, html = user_mrf._warranty_route_preview()
        self.assertTrue(can_submit)
        self.assertIn('Requisition workflow', html)
        self.company.warranty_mrf_approval_matrix = True
        self.assertFalse(mrf.approval_round)
        self._submit(mrf)
        self.assertEqual(mrf.state, 'ir_approve')
        with self.assertRaisesRegex(UserError, 'New warranty Material Requests only'):
            user_mrf.action_warranty_check_route()
        with self.assertRaisesRegex(UserError, 'New warranty Material Requests only'):
            self._standalone().action_warranty_check_route()
        for user in (self.helpdesk_user, self.finance, self.tech):
            arch = self.Mrf.with_user(user).get_views([(False, 'form')])['views']['form']['arch']
            self.assertIn('action_warranty_check_route', arch)
            self.env['warranty.mrf.route.preview.wizard'].with_user(user).get_views(
                [(False, 'form')])

    def test_21_matrix_buttons_per_stage(self):
        """Approve / Reject only for the named approvers of the current stage; the requester,
        creator and submitter and users of other stages neither see nor run them."""
        self._rule('All levels', ('manager', 'finance', 'gm'),
                   users={'manager': self.manager | self.helpdesk_user})
        mrf = self._submit(self._mrf([(self.part, 1)]))
        arch = self.Mrf.with_user(self.manager).get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertIn('invisible="not can_warranty_approve"', arch)
        others = (self.helpdesk_user, self.store, self.dept)
        # Manager stage, then Finance / GM (GM first), then GM after Finance.
        for state, allowed, approver in (('dept_confirm', {self.manager}, self.manager),
                                         ('ir_approve', {self.finance, self.gm}, self.finance),
                                         ('ir_approve', {self.gm}, self.gm)):
            self.assertEqual(mrf.state, state)
            for user in (self.manager, self.finance, self.gm) + others:
                self.assertEqual(mrf.with_user(user).can_warranty_approve, user in allowed,
                                 (state, user.login))
                if user in allowed:
                    continue
                with self.assertRaises(AccessError):
                    mrf.with_user(user).action_warranty_approve()
                with self.assertRaises(AccessError):
                    mrf.with_user(user).action_warranty_reject()
                with self.assertRaises(AccessError):
                    mrf.with_user(user)._warranty_reject('No')
            self._approve(mrf, approver)
        self.assertEqual(mrf.state, 'approve')
        for user in (self.manager, self.finance, self.gm) + others:
            self.assertFalse(mrf.with_user(user).can_warranty_approve)
        for method in ('manager_approve', 'user_approve', 'requisition_reject'):
            with self.assertRaisesRegex(UserError, 'approval matrix'):
                getattr(mrf.with_user(self.store), method)()

    def test_22_vendor_buttons_matrix_off(self):
        """Matrix off: the vendor Department Approve / Approve / Reject buttons of warranty
        requests are shown only to users who pass the server checks; standalone requests keep
        the vendor (group-based) buttons."""
        self.company.warranty_mrf_approval_matrix = False
        self.helpdesk_user.groups_id |= self.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_department')
        self.dept.groups_id |= self.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        mrf = self._submit(self._mrf([(self.part, 1)]))
        arch = self.Mrf.with_user(self.dept).get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('is_warranty_mrf and not can_warranty_vendor_manager_approve', arch)
        flags = ('can_warranty_vendor_manager_approve', 'can_warranty_vendor_user_approve',
                 'can_warranty_vendor_reject')

        def buttons(user):
            record = mrf.with_user(user)
            return tuple(record[flag] for flag in flags)
        self.assertEqual(buttons(self.helpdesk_user), (False, False, False), 'requester')
        self.assertEqual(buttons(self.dept), (True, False, True))
        self.assertEqual(buttons(self.store), (False, False, True))
        with self.assertRaises(AccessError):
            mrf.with_user(self.helpdesk_user).manager_approve()
        with self.assertRaises(AccessError):
            mrf.with_user(self.helpdesk_user).requisition_reject()
        mrf.with_user(self.dept).manager_approve()
        self.assertEqual(buttons(self.dept), (False, False, True))
        self.assertEqual(buttons(self.store), (False, True, True))
        self.assertEqual(buttons(self.helpdesk_user), (False, False, False))
        with self.assertRaisesRegex(AccessError, 'another person'):
            mrf.with_user(self.dept).user_approve()
        mrf.with_user(self.store).user_approve()
        self.assertEqual(mrf.state, 'approve')
        standalone = self._standalone()
        self.assertFalse(standalone.is_warranty_mrf)
        self.assertEqual(tuple(standalone[flag] for flag in flags), (False, False, False))

    def test_23_matrix_requests_hide_vendor_buttons(self):
        """Matrix requests never offer the vendor buttons, also not to vendor group members."""
        self._matrix()
        self.dept.groups_id |= self.env.ref(
            'material_purchase_requisitions.group_purchase_requisition_user')
        mrf = self._submit(self._mrf([(self.part, 2)]))
        record = mrf.with_user(self.dept)
        self.assertFalse(record.can_warranty_vendor_manager_approve
                         or record.can_warranty_vendor_user_approve
                         or record.can_warranty_vendor_reject)
