from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_replacement', 'warranty_replacement_completion')
class TestReplacementCaseCompletion(ReplacementCommon):
    """Complete Warranty Case after a Done Full Product / Indoor / Outdoor / Vendor replacement
    (approved 2026-11-10, doc/replacement_case_completion.md). Component and Goodwill excluded."""

    def setUp(self):
        super().setUp()
        self.company.write({'warranty_replacement_gm_user_ids': [(6, 0, self.gm.ids)],
                            'warranty_replacement_full_finance': 'not_required'})
        self.stock_only = self._user('wr_stock_only', 'stock.group_stock_user')

    # ------------------------------------------------------------------ helpers
    def _single_case(self):
        card = self._card(self.single)
        old = card.unit_warranty_ids.serial_ids
        case = self._eligible_case(old)
        self.assertEqual(case.eligibility_result, 'eligible', case.eligibility_reason)
        self._approved_state(case)
        return case, self.env['stock.lot'].search(
            [('product_id', '=', self.single.id), ('id', '!=', old.id)], limit=1)

    def _approve(self, replacement):
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        self.assertEqual(replacement.state, 'approved')

    def _done(self, case, kind, new):
        replacement = self._request(case, kind, new)
        self._approve(replacement)
        self._validate(replacement.sudo().return_picking_id)
        self._validate(replacement.sudo().delivery_picking_id)
        self.assertEqual(replacement.state, 'done')
        return replacement

    def _complete(self, case, user=None):
        return case.with_user(user or self.coordinator).action_warranty_complete_replacement_case()

    def _assert_completed(self, case, replacement):
        self.assertEqual(case.state, 'approved', 'a Done replacement never completes the case')
        self.assertTrue(case.warranty_replacement_can_complete)
        self.assertFalse(case.warranty_goodwill_can_complete)
        self.assertIs(self._complete(case), True)
        self.assertEqual((case.state, case.eligibility_result), ('completed', 'eligible'))
        self.assertFalse(case.warranty_replacement_can_complete)
        for record in (case, replacement):
            self.assertTrue(record.sudo().message_ids.filtered(
                lambda message: 'completed by wr_coordinator after replacement %s'
                % replacement.name in (message.body or '')), record)
        with self.assertRaisesRegex(UserError, 'must be Approved and Eligible'):
            self._complete(case)

    # ------------------------------------------------------------------ mandatory tests
    def test_01_vendor_replacement_complete_then_close(self):
        """Vendor Replacement -> Complete Warranty Case -> Close Case; an open Vendor Claim blocks
        neither step, and no journal entry is created."""
        supplier = self.env['res.partner'].create({'name': 'WR Completion Vendor'})
        self.single.standard_price = 100.0
        self.single.product_tmpl_id.write({'warranty_vendor_claimable': True,
                                           'warranty_claim_partner_id': supplier.id})
        self.company.warranty_vendor_claim_enabled = True
        case, new = self._single_case()
        replacement = self._done(case, 'vendor', new)
        action = replacement.action_warranty_replacement_create_vendor_claim()
        claim = self.env['warranty.vendor.claim'].browse(action['res_id'])
        self.assertEqual(claim.state, 'draft')
        moves = self.env['account.move'].search_count([])
        self._assert_completed(case, replacement)
        if not hasattr(case, 'action_warranty_close_case'):
            self.skipTest("Close Case needs warranty_management_accounting.")
        case.with_user(self.coordinator).action_warranty_close_case()
        self.assertEqual(case.state, 'closed')
        self.assertEqual(claim.state, 'draft', 'the Vendor Claim stays independent')
        self.assertEqual(self.env['account.move'].search_count([]), moves, 'no journal entry')

    def test_02_full_product_replacement(self):
        case, new = self._single_case()
        replacement = self._done(case, 'full', new)
        self._assert_completed(case, replacement)

    def test_03_indoor_and_outdoor_replacements(self):
        card = self._card(self.kit)
        unit = card.unit_warranty_ids
        for role, product in (('indoor', self.indoor), ('outdoor', self.outdoor)):
            old = unit[f'{role}_serial_id']
            case = self._eligible_case(old)
            self.assertEqual(case.eligibility_result, 'eligible', case.eligibility_reason)
            self._approved_state(case)
            new = self.env['stock.lot'].search(
                [('product_id', '=', product.id), ('id', '!=', old.id)], limit=1)
            replacement = self._done(case, role, new)
            self.assertEqual(unit[f'{role}_serial_id'], new)
            self._assert_completed(case, replacement)

    def test_04_incomplete_replacement_refused(self):
        case, new = self._single_case()
        replacement = self._request(case, 'full', new)
        self.assertFalse(case.warranty_replacement_can_complete)
        self._approve(replacement)
        self._validate(replacement.sudo().return_picking_id)
        self.assertEqual(replacement.state, 'approved', 'delivery not validated yet')
        self.assertFalse(case.warranty_replacement_can_complete)
        with self.assertRaisesRegex(UserError, 'must be Approved and Eligible'):
            self._complete(case)
        with self.assertRaisesRegex(UserError, 'is not finished'):
            self._complete(case)
        self.assertEqual(case.state, 'approved')

    def test_05_existing_blockers(self):
        case, new = self._single_case()
        self._done(case, 'full', new)
        # A second, open replacement of the case.
        other = self._request(case, 'full', self._lot(self.single, 5))
        with self.assertRaisesRegex(UserError, 'is not finished'):
            self._complete(case)
        other.unlink()
        # An undetermined Case Type (the write guard would refuse the completion anyway).
        case_type = case.case_type
        case.sudo().with_context(warranty_case_type_marker=None).write({'case_type': False})
        with self.assertRaisesRegex(UserError, 'no Case Type'):
            self._complete(case)
        case.sudo().with_context(warranty_case_type_marker=None).write({'case_type': case_type})
        # An open service job: the job keeps control and completes the case.
        job = self.env['warranty.service.job'].sudo()._warranty_service_marker().create(
            {'warranty_case_id': case.id})
        self.assertEqual(case.open_service_job_id, job)
        with self.assertRaisesRegex(UserError, 'Service job %s is open' % job.name):
            self._complete(case)
        self.assertNotEqual(case.state, 'completed')

    def test_06_unauthorized_users_refused(self):
        case, new = self._single_case()
        self._done(case, 'full', new)
        for user in (self.outsider, self.stock_only):
            with self.assertRaises(AccessError):
                self._complete(case, user)
        self.assertEqual(case.state, 'approved')
        # The K6 guard: no direct write of Completed without the marker.
        with self.assertRaisesRegex(UserError, 'Complete Visit'):
            case.with_user(self.coordinator).write({'state': 'completed'})

    def test_07_goodwill_completion_unchanged(self):
        """A Goodwill case completes with its own action only; the new action refuses it."""
        card = self._card(self.single)
        unit = card.unit_warranty_ids
        old = unit.serial_ids
        start = fields.Date.today() - relativedelta(years=3)
        end = start + relativedelta(years=1)
        card._warranty_system_write({'warranty_start_date': start, 'warranty_end_date': end})
        unit._warranty_system_write({'start_date': start, 'end_date': end})
        case = self._eligible_case(old)
        self.assertEqual(case.eligibility_result, 'out_of_warranty', case.eligibility_reason)
        replacement = self._request(case, 'goodwill', self._lot(self.single, 6), reason='goodwill',
                                    reason_note='Goodwill', date_policy='manual')
        replacement.action_warranty_replacement_submit()
        as_gm = replacement.with_user(self.gm)
        as_gm.write({'manual_end_date': fields.Date.today() + relativedelta(years=1),
                     'manual_date_reason': 'GM decision'})
        as_gm.action_warranty_replacement_approve()
        self._validate(replacement.sudo().return_picking_id)
        self._validate(replacement.sudo().delivery_picking_id)
        self.assertTrue(case.warranty_goodwill_can_complete)
        self.assertFalse(case.warranty_replacement_can_complete)
        with self.assertRaisesRegex(UserError, 'must be Approved and Eligible'):
            self._complete(case)
        case.with_user(self.coordinator).action_warranty_complete_goodwill_case()
        self.assertEqual((case.state, case.eligibility_result), ('completed', 'out_of_warranty'))

    def test_08_goodwill_action_refuses_a_replacement_case(self):
        case, new = self._single_case()
        self._done(case, 'vendor', new)
        with self.assertRaisesRegex(UserError, 'no Done Goodwill'):
            case.with_user(self.coordinator).action_warranty_complete_goodwill_case()
        self.assertEqual(case.state, 'approved')

    def test_09_component_replacement_excluded(self):
        """Component is reviewed separately: its Done replacement does not offer the action."""
        part = self.env['product.product'].create({
            'name': 'WR Completion Filter', 'type': 'consu', 'is_storable': True,
            'standard_price': 5.0})
        case, __ = self._single_case()
        replacement = self.env['warranty.replacement'].with_user(self.coordinator).create({
            'warranty_case_id': case.id, 'replacement_type': 'component',
            'reason': 'pcb_failure', 'date_policy': 'continue_original',
            'component_line_ids': [(0, 0, {'product_id': part.id, 'qty': 1.0,
                                           'return_required': False,
                                           'no_return_reason': 'Consumed part'})]})
        self._approve(replacement)
        employee = self.env['hr.employee'].create({
            'name': 'WR Completion Employee', 'department_id': self.env['hr.department'].create(
                {'name': 'WR Completion Department'}).id})
        request = self.env['material.purchase.requisition'].create({
            'employee_id': employee.id, 'department_id': employee.department_id.id,
            'warranty_case_id': case.id,
            'requisition_line_ids': [(0, 0, {'product_id': part.id, 'description': part.name,
                                             'qty': 1.0, 'uom': part.uom_id.id})]})
        material = request.requisition_line_ids
        self.env['warranty.mrf.consumption'].sudo().create(
            {'line_id': material.id, 'kind': 'used', 'qty': 1.0})
        replacement.sudo().component_line_ids.with_user(self.coordinator).write(
            {'mrf_line_id': material.id})
        replacement.action_warranty_replacement_complete_component()
        self.assertEqual(replacement.state, 'done')
        self.assertFalse(case.warranty_replacement_can_complete)
        with self.assertRaisesRegex(UserError, 'must be Approved and Eligible'):
            self._complete(case)
        self.assertEqual(case.state, 'approved')

    def test_10_form_button(self):
        case_model = self.env['warranty.case'].with_user(self.coordinator)
        arch = case_model.get_view(view_type='form')['arch']
        self.assertIn('action_warranty_complete_replacement_case', arch)
        self.assertIn('warranty_replacement_can_complete', arch)
