from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from .common import WarrantyMrfCommon


@tagged('post_install', '-at_install', 'warranty_mrf')
class TestWarrantyMrfCoverage(WarrantyMrfCommon):
    """Phase 5.2 - coverage classification and coverage decision (mapping 5.2, T2.1 - T2.7).
    Policy of the Part 3 fixture: Case PCB covered (product Outdoor PCB), Case Gas Refill
    excluded (product Gas R410A); Copper Pipe is not in the policy."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Product = cls.env['product.product']
        cls.gas = Product.create({'name': 'Gas R410A', 'type': 'consu', 'standard_price': 3000})
        cls.pipe = Product.create({'name': 'Copper Pipe', 'type': 'consu', 'standard_price': 10})
        cls.item_pcb.product_id = cls.part
        cls.item_gas.product_id = cls.gas

    def _mrf(self, case=None, products=None):
        case = case or self._approved()
        return self._save(case.with_user(self.helpdesk_user).action_create_material_request(),
                          self.helpdesk_user, products=products or (self.part | self.gas | self.pipe))

    def _line(self, mrf, product):
        return mrf.requisition_line_ids.filtered(lambda line: line.product_id == product)

    def _coverage_wizard(self, mrf, user=None):
        user = user or self.approver_b
        action = mrf.with_user(user).action_decide_coverage()
        return Form(self.env['warranty.mrf.coverage.wizard'].with_user(user).with_context(
            **action['context']))

    def _decide(self, mrf, lines, decision='covered', user=None, reason='Checked policy'):
        """Decide Coverage as in the form: tick exactly the given lines, decision, reason."""
        form = self._coverage_wizard(mrf, user)
        for index in range(len(form.line_ids)):
            with form.line_ids.edit(index) as row:
                row.selected = row.requisition_line_id in lines
        form.decision = decision
        form.reason = reason
        form.save().action_apply()

    def _logged(self, record, text):
        return any(text in (message.body or '') for message in record.message_ids)

    # ------------------------------------------------------------------ T2.1 / T2.2
    def test_01_default_rules(self):
        """T2.1 / T2.2: covered item product on an Eligible case -> Covered, excluded item
        product -> Not Covered, other products -> Pending, mixed on one request; a chargeable
        case -> Not Covered."""
        mrf = self._mrf()
        part, gas, pipe = (self._line(mrf, p) for p in (self.part, self.gas, self.pipe))
        self.assertEqual((part.coverage_type, part.covered_under_warranty), ('covered', 'yes'))
        self.assertIn(self.item_pcb.name, part.coverage_default_reason)
        self.assertEqual((gas.coverage_type, gas.covered_under_warranty), ('not_covered', 'no'))
        self.assertIn(self.item_gas.name, gas.coverage_default_reason)
        self.assertEqual(pipe.coverage_type, 'pending')
        self.assertFalse(pipe.covered_under_warranty)
        self.assertEqual(mrf.coverage_status, 'pending')
        self.assertEqual((mrf.coverage_covered_count, mrf.coverage_not_covered_count,
                          mrf.coverage_pending_count), (1, 1, 1))
        case = mrf.warranty_case_id
        case.write({'state': 'chargeable'})
        chargeable = self._mrf(case, self.part | self.pipe)
        self.assertEqual(set(chargeable.requisition_line_ids.mapped('coverage_type')),
                         {'not_covered'})
        self.assertEqual(chargeable.coverage_status, 'not_covered')

    # ------------------------------------------------------------------ T2.3
    def test_02_confirm_blocked_while_pending(self):
        """T2.3: Confirm is refused while a line is Pending; allowed once decided."""
        mrf = self._mrf()
        with self.assertRaisesRegex(UserError, 'Copper Pipe'):
            mrf.sudo().requisition_confirm()
        self.assertEqual(mrf.state, 'draft')
        self._decide(mrf, self._line(mrf, self.pipe), 'not_covered')
        self.assertEqual(mrf.coverage_status, 'mixed')
        mrf.sudo().requisition_confirm()
        self.assertEqual(mrf.state, 'dept_confirm')

    # ------------------------------------------------------------------ T2.4
    def test_03_reviewers(self):
        """T2.4: To-Do per coverage reviewer (Warranty Case Approval Users), not the requester /
        creator; no duplicates; only reviewers decide; reason mandatory; coverage cannot be
        written directly. Approval not required: Helpdesk users of the company decide."""
        mrf = self._mrf()
        mrf.with_user(self.helpdesk_user).action_request_coverage_decision()
        activities = mrf.coverage_activity_ids
        self.assertEqual(activities.user_id, self.approver_a | self.approver_b | self.creator)
        self.assertEqual(mrf.coverage_requested_by_id, self.helpdesk_user)
        mrf.with_user(self.helpdesk_user).action_request_coverage_decision()
        self.assertEqual(mrf.coverage_activity_ids, activities, 'no duplicates')
        self.assertIn('already requested', mrf.message_ids[:1].body)
        self.assertFalse(mrf.with_user(self.helpdesk_user).can_decide_coverage)
        self.assertTrue(mrf.with_user(self.approver_b).can_decide_coverage)
        with self.assertRaises(AccessError):
            mrf.with_user(self.helpdesk_user).action_decide_coverage()
        pipe = self._line(mrf, self.pipe)
        with self.assertRaises(AccessError):
            mrf.with_user(self.no_dept_user)._warranty_decide_coverage(pipe, 'covered', 'ok')
        with self.assertRaisesRegex(UserError, 'reason is required'):
            mrf.with_user(self.approver_b)._warranty_decide_coverage(pipe, 'covered', '  ')
        with self.assertRaisesRegex(UserError, 'Decide Coverage'):
            pipe.with_user(self.helpdesk_user).write({'coverage_type': 'covered'})
        mrf.with_user(self.helpdesk_user).write({'requisition_line_ids': [(0, 0, {
            'product_id': self.pipe.id, 'description': 'Pipe', 'qty': 1,
            'uom': self.pipe.uom_id.id, 'coverage_type': 'covered'})]})
        self.assertEqual(mrf.requisition_line_ids[-1:].coverage_type, 'pending',
                         'coverage values of a new line are ignored')
        self.company.warranty_case_approval_required = False
        self.assertTrue(mrf.with_user(self.no_dept_user).can_decide_coverage)
        self.assertFalse(mrf.with_user(self.helpdesk_user).can_decide_coverage)

    # ------------------------------------------------------------------ T2.5
    def test_04_decision_logged(self):
        """T2.5: decision fields, goodwill, notes on request / case / job, activities closed
        when nothing is pending; a reviewer can override a default; a new product resets the
        line to its default."""
        job = self._confirmed_job()
        mrf = self._save(job.with_user(self.helpdesk_user).action_create_material_request(),
                         self.helpdesk_user, products=self.pipe | self.gas)
        mrf.with_user(self.helpdesk_user).action_request_coverage_decision()
        pipe, gas = self._line(mrf, self.pipe), self._line(mrf, self.gas)
        self._decide(mrf, pipe, 'goodwill', reason='Customer goodwill')
        self.assertEqual((pipe.coverage_type, pipe.goodwill, pipe.coverage_decided_by_id,
                          pipe.coverage_decision_reason),
                         ('covered', True, self.approver_b, 'Customer goodwill'))
        self.assertTrue(pipe.coverage_decision_date)
        for record in (mrf, job, job.warranty_case_id):
            self.assertTrue(self._logged(record, 'Free of Charge'), record)
        self.assertFalse(mrf.coverage_activity_ids.exists().filtered('active'))
        self.assertEqual(mrf.coverage_status, 'mixed')
        self._decide(mrf, gas, 'covered', reason='Leak caused by a factory defect')
        self.assertEqual((gas.coverage_type, gas.goodwill), ('covered', False))
        self.assertEqual(mrf.coverage_status, 'covered')
        pipe.with_user(self.helpdesk_user).write({'product_id': self.part.id})
        self.assertEqual((pipe.coverage_type, pipe.goodwill, pipe.coverage_decided_by_id.id),
                         ('covered', False, False))

    # ------------------------------------------------------------------ T2.6
    def test_05_locked_after_submission(self):
        """T2.6: after Confirm the coverage, products and lines are locked; Reset to Draft
        (vendor, after rejection) reopens them."""
        mrf = self._mrf(products=self.part)
        mrf.sudo().requisition_confirm()
        line = mrf.requisition_line_ids
        with self.assertRaisesRegex(UserError, 'locked'):
            mrf.with_user(self.approver_b).action_decide_coverage()
        with self.assertRaisesRegex(UserError, 'locked'):
            mrf.with_user(self.helpdesk_user).action_request_coverage_decision()
        with self.assertRaisesRegex(UserError, 'locked'):
            line.with_user(self.helpdesk_user).write({'product_id': self.gas.id})
        with self.assertRaisesRegex(UserError, 'locked'):
            mrf.with_user(self.helpdesk_user).write({'requisition_line_ids': [(0, 0, {
                'product_id': self.pipe.id, 'description': 'Pipe', 'qty': 1,
                'uom': self.pipe.uom_id.id})]})
        with self.assertRaisesRegex(UserError, 'locked'):
            line.with_user(self.helpdesk_user).unlink()
        mrf.sudo().requisition_reject()
        mrf.sudo().reset_draft()
        self._decide(mrf, line, 'not_covered')
        self.assertEqual(line.coverage_type, 'not_covered')

    # ------------------------------------------------------------------ T2.7
    def test_06_standalone(self):
        """T2.7: standalone requests have no coverage and confirm as before; a linked
        standalone request gets the default coverage."""
        standalone = self._standalone()
        standalone.write({'requisition_line_ids': [(0, 0, {
            'product_id': self.pipe.id, 'description': 'Pipe', 'qty': 1,
            'uom': self.pipe.uom_id.id})]})
        self.assertFalse(standalone.requisition_line_ids.coverage_type)
        self.assertFalse(standalone.coverage_status)
        with self.assertRaisesRegex(UserError, 'warranty Material Requests only'):
            standalone.action_request_coverage_decision()
        standalone.sudo().requisition_confirm()
        self.assertEqual(standalone.state, 'dept_confirm')
        to_link = self._standalone()
        to_link.write({'requisition_line_ids': [(0, 0, {
            'product_id': self.part.id, 'description': 'PCB', 'qty': 1,
            'uom': self.part.uom_id.id})]})
        to_link._warranty_link(self._approved())
        self.assertEqual(to_link.requisition_line_ids.coverage_type, 'covered')

    def test_08_wizard_line_selection(self):
        """Decide Coverage lists the existing lines of the request (product, quantity, unit,
        coverage type, basis) with a checkbox, pending lines preselected; no line can be
        added, removed or edited there; only the ticked lines are decided."""
        mrf = self._mrf()
        other = self._mrf(products=self.pipe)
        part, gas, pipe = (self._line(mrf, product) for product in (self.part, self.gas, self.pipe))
        arch = self.env['warranty.mrf.coverage.wizard'].with_user(self.approver_b).get_views(
            [(False, 'form')])['views']['form']['arch']
        for snippet in ('create="0"', 'delete="0"', 'name="selected"', 'name="product_id"',
                        'name="qty"', 'name="uom"', 'name="coverage_type"',
                        'name="coverage_default_reason"'):
            self.assertIn(snippet, arch)
        form = self._coverage_wizard(mrf)
        self.assertEqual(len(form.line_ids), 3)
        selected = {}
        for index in range(len(form.line_ids)):
            with form.line_ids.edit(index) as row:
                selected[row.requisition_line_id] = row.selected
                self.assertEqual((row.product_id, row.qty, row.uom),
                                 (row.requisition_line_id.product_id,
                                  row.requisition_line_id.qty, row.requisition_line_id.uom))
                self.assertTrue(row.coverage_default_reason or row.coverage_type == 'pending')
        self.assertEqual(selected, {part: False, gas: False, pipe: True})
        form.decision, form.reason = 'covered', 'Checked'
        wizard = form.save()
        self.assertEqual(wizard.line_ids.requisition_line_id, mrf.requisition_line_ids)
        with self.assertRaisesRegex(UserError, 'only selects lines'):
            wizard.line_ids[0].write({'qty': 5})
        with self.assertRaisesRegex(UserError, 'only selects lines'):
            wizard.line_ids[0].write({'product_id': self.gas.id})
        self.assertEqual(part.product_id, self.part)

        # Single line: the preselected pending line only.
        self._decide(mrf, pipe, 'goodwill', reason='Customer goodwill')
        self.assertEqual((pipe.coverage_type, pipe.goodwill), ('covered', True))
        self.assertEqual((part.coverage_type, part.coverage_decided_by_id.id), ('covered', False))
        self.assertEqual((gas.coverage_type, gas.coverage_decided_by_id.id),
                         ('not_covered', False))
        self.assertEqual(other.requisition_line_ids.coverage_type, 'pending')

        # No pending line left: nothing preselected; applying without a selection is refused.
        form = self._coverage_wizard(mrf)
        for index in range(len(form.line_ids)):
            with form.line_ids.edit(index) as row:
                self.assertFalse(row.selected)
        form.decision, form.reason = 'covered', 'Checked'
        with self.assertRaisesRegex(UserError, 'Select the lines'):
            form.save().action_apply()
        # The reason stays required.
        with self.assertRaisesRegex(UserError, 'reason is required'):
            self._decide(mrf, gas, 'covered', reason='  ')

        # Multiple lines in one decision.
        self._decide(mrf, part | gas, 'not_covered', reason='Physical damage')
        self.assertEqual((part.coverage_type, gas.coverage_type, pipe.coverage_type),
                         ('not_covered', 'not_covered', 'covered'))
        self.assertEqual(set((part | gas).mapped('coverage_decision_reason')), {'Physical damage'})
        self.assertEqual(pipe.coverage_decision_reason, 'Customer goodwill')
        self.assertTrue(self._logged(mrf, 'Physical damage'))

        # Unauthorized users: the requester cannot open or apply the wizard.
        with self.assertRaises(AccessError):
            mrf.with_user(self.helpdesk_user).action_decide_coverage()
        wizard = self.env['warranty.mrf.coverage.wizard'].with_user(self.helpdesk_user)             .with_context(default_requisition_id=other.id).create(
                {'decision': 'covered', 'reason': 'Own decision'})
        self.assertEqual(wizard.line_ids.mapped('selected'), [True])
        with self.assertRaises(AccessError):
            wizard.action_apply()
        self.assertEqual(other.requisition_line_ids.coverage_type, 'pending')
        # Lines of another request are refused by the decision itself.
        with self.assertRaisesRegex(UserError, 'Only lines of'):
            mrf.with_user(self.approver_b)._warranty_decide_coverage(
                other.requisition_line_ids, 'covered', 'Checked')

    def test_07_views_render(self):
        """The coverage elements render for a reviewer, a Helpdesk user and a technician."""
        for user in (self.approver_b, self.helpdesk_user, self.tech):
            arch = self.env['material.purchase.requisition'].with_user(user).get_views(
                [(False, 'form'), (False, 'list'), (False, 'search')])
            self.assertIn('coverage_status', arch['views']['form']['arch'])
            self.assertTrue(self.env['warranty.mrf.coverage.wizard'].with_user(user).get_views(
                [(False, 'form')])['views'])
