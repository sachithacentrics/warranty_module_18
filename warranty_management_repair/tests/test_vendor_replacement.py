from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_replacement', 'warranty_replacement_vendor')
class TestVendorReplacement(ReplacementCommon):
    """Part 7 Stage 3 Phase 3: one serial, Manager / GM approval, optional Vendor Claim."""

    def setUp(self):
        super().setUp()
        self.supplier = self.env['res.partner'].create({'name': 'WR Manufacturer'})
        self.single.standard_price = 100.0
        self.single.product_tmpl_id.write({'warranty_vendor_claimable': True,
                                           'warranty_claim_partner_id': self.supplier.id})
        self.company.warranty_vendor_claim_enabled = True
        self.company.warranty_replacement_gm_user_ids = self.gm
        self.card = self._card(self.single)
        self.unit = self.card.unit_warranty_ids
        self.old = self.unit.serial_ids
        self.new = self._lot(self.single, 6)
        self.case = self._eligible_case(self.old)
        self.assertEqual(self.case.eligibility_result, 'eligible', self.case.eligibility_reason)
        self._approved_state(self.case)

    def _done(self, **vals):
        replacement = self._request(self.case, 'vendor', self.new, **vals)
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        return replacement

    def _claim(self, replacement):
        action = replacement.action_warranty_replacement_create_vendor_claim()
        return self.env['warranty.vendor.claim'].browse(action['res_id'])

    def test_01_flow_without_a_claim(self):
        """Manager / GM only, return before delivery, swap after delivery, no claim needed."""
        self.company.write({'warranty_replacement_full_finance': 'required',
                            'warranty_replacement_finance_user_ids': [(6, 0, self.finance.ids)]})
        names = (self.card.name, self.unit.name)
        replacement = self._request(self.case, 'vendor', self.new)
        replacement.action_warranty_replacement_submit()
        record = replacement.sudo()
        self.assertEqual(replacement.state, 'submitted')
        self.assertFalse(replacement.finance_required)
        self.assertFalse(record.delivery_picking_id)
        self.assertFalse(replacement.with_user(self.finance).can_approve)
        with self.assertRaises(AccessError):
            replacement.action_warranty_replacement_approve()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        self.assertEqual(replacement.state, 'approved')
        with self.assertRaises(UserError):
            self._validate(record.delivery_picking_id)
        self.assertEqual(self.unit.serial_ids, self.old)
        self._validate(record.return_picking_id)
        self.assertEqual(self.unit.serial_ids, self.old)
        self._validate(record.delivery_picking_id)
        self.assertEqual(replacement.state, 'done')
        self.assertEqual(self.unit.serial_ids, self.new)
        self.assertEqual((self.card.name, self.unit.name), names)
        self.assertTrue(replacement.updated_card_generated)
        self.assertEqual(replacement.replacement_cost, 100.0)
        self.assertFalse(replacement.vendor_claim_count)
        self.assertFalse(self.case._warranty_replacement_problems(), 'no claim is required')

    def test_02_claim_uses_the_existing_workflow(self):
        moves = self.env['account.move'].search_count([])
        replacement = self._done()
        claim = self._claim(replacement)
        self.assertEqual(claim.state, 'draft')
        self.assertEqual(claim.partner_id, self.supplier)
        self.assertEqual(claim.case_id, self.case)
        self.assertEqual(claim.line_ids.replacement_id, replacement)
        self.assertEqual(claim.line_ids.product_id, self.single)
        self.assertEqual(claim.line_ids.lot_ids, self.old)
        self.assertEqual(claim.line_ids.allowed_lot_ids, self.old)
        self.assertEqual(claim.claimed_amount, 100.0)
        self.assertFalse(claim.line_ids.requisition_id)
        self.assertFalse(claim.over_claimed)
        self.assertEqual(replacement.vendor_claim_count, 1)
        self.assertEqual(self.env['account.move'].search_count([]), moves, 'nothing is posted')
        self.company.warranty_claim_approver_ids = self.gm
        claim.with_user(self.coordinator).action_submit()
        self.assertEqual(claim.state, 'to_approve')
        claim.with_user(self.gm).action_approve()
        self.assertEqual(claim.state, 'approved')
        self.assertEqual(replacement.state, 'done')
        self.assertEqual(self.env['account.move'].search_count([]), moves, 'nothing is posted')

    def test_03_one_active_claim(self):
        replacement = self._done()
        self._claim(replacement)
        with self.assertRaisesRegex(UserError, 'already on vendor claim'):
            replacement.action_warranty_replacement_create_vendor_claim()

    def test_04_claim_refused_before_done_and_without_conditions(self):
        replacement = self._request(self.case, 'vendor', self.new)
        with self.assertRaisesRegex(UserError, 'Done Vendor'):
            replacement.action_warranty_replacement_create_vendor_claim()
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.single.product_tmpl_id.warranty_vendor_claimable = False
        with self.assertRaisesRegex(UserError, 'Vendor Claimable'):
            replacement.action_warranty_replacement_create_vendor_claim()
        self.single.product_tmpl_id.warranty_vendor_claimable = True
        self.company.warranty_vendor_claim_enabled = False
        with self.assertRaisesRegex(UserError, 'not enabled'):
            replacement.action_warranty_replacement_create_vendor_claim()
        self.company.warranty_vendor_claim_enabled = True
        self.single.product_tmpl_id.warranty_claim_partner_id = False
        with self.assertRaisesRegex(UserError, 'Warranty Claim Partner'):
            replacement.action_warranty_replacement_create_vendor_claim()
        self.assertEqual(replacement.state, 'done')

    def test_05_zero_cost_refuses_the_claim_not_the_replacement(self):
        self.single.standard_price = 0.0
        replacement = self._done()
        self.assertEqual(replacement.state, 'done')
        with self.assertRaisesRegex(UserError, 'verified cost'):
            replacement.action_warranty_replacement_create_vendor_claim()

    def test_06_claim_only_on_vendor_type(self):
        self.company.write({'warranty_replacement_full_finance': 'not_required'})
        replacement = self._request(self.case, 'full', self.new)
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        with self.assertRaisesRegex(UserError, 'Done Vendor'):
            replacement.action_warranty_replacement_create_vendor_claim()

    def test_07_kit_and_ineligible_cases_refused(self):
        kit_card = self._card(self.kit)
        kit_unit = kit_card.unit_warranty_ids
        kit_case = self._eligible_case(kit_unit.indoor_serial_id)
        self._approved_state(kit_case)
        kit = self._request(kit_case, 'vendor', self._lot(self.indoor, 6))
        with self.assertRaisesRegex(UserError, 'must hold one product with one serial'):
            kit.action_warranty_replacement_submit()
        self.case.sudo().write({'state': 'eligibility_checked',
                                'eligibility_result': 'out_of_warranty'})
        expired = self._request(self.case, 'vendor', self.new)
        with self.assertRaisesRegex(UserError, 'must be Eligible'):
            expired.action_warranty_replacement_submit()

    def test_08_goodwill_reason_refused(self):
        replacement = self._request(self.case, 'vendor', self.new, reason='goodwill')
        with self.assertRaisesRegex(UserError, 'Goodwill replacement type'):
            replacement.action_warranty_replacement_submit()

    def test_09_claim_line_source_and_protection(self):
        replacement = self._done()
        line = self._claim(replacement).line_ids
        with self.assertRaises(ValidationError):
            line.sudo().write({'replacement_id': False})
        with self.assertRaisesRegex(UserError, 'set by the claim workflow'):
            line.with_user(self.coordinator).write({'replacement_id': False})

    def test_10_amount_limit(self):
        line = self._claim(self._done()).line_ids
        with self.assertRaisesRegex(UserError, 'not above the verified cost'):
            line.write({'claimed_amount': 101.0})
        line.write({'claimed_amount': 60.0})
        self.assertEqual(line.claim_id.claimed_amount, 60.0)

    def test_11_case_material_cost_ignores_replacement_recovery(self):
        replacement = self._done()
        claim = self._claim(replacement)
        self.assertEqual(self.case.vendor_claim_count, 1)
        self.assertEqual(self.case.vendor_claimed_amount, 100.0)
        self.assertEqual(self.case.net_warranty_material_cost,
                         self.case.warranty_material_cost)
        self.assertEqual(claim.line_ids.recovered_amount, 0.0)

    def test_12_date_policy_and_history(self):
        replacement = self._done(date_policy='remaining_period')
        self.assertTrue(replacement.remaining_days > 0)
        self.assertEqual(len(self.env['warranty.card.date.log'].search(
            [('card_id', '=', self.card.id), ('event', '=', 'replacement')])), 1)

    def _manual_vals(self, replacement, **vals):
        return {'case_id': replacement.warranty_case_id.id, 'partner_id': self.supplier.id,
                'failure_description': 'Failed', 'line_ids': [(0, 0, {
                    'replacement_id': replacement.id})], **vals}

    def test_13_new_button_follows_access_rights(self):
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_mrf.action_warranty_vendor_claim')
        self.assertNotIn('create', action['context'])
        Claim = self.env['warranty.vendor.claim']
        reader = self.env['res.users'].sudo().create({
            'name': 'Claim Reader', 'login': 'wr_claim_reader',
            'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                  | self.env.ref('account.group_account_readonly')).ids)]})
        view = self.env.ref('warranty_management_mrf.warranty_vendor_claim_view_list').id
        self.assertIn('create="False"', Claim.with_user(reader).get_view(view, 'list')['arch'])
        self.assertNotIn('create="False"',
                         Claim.with_user(self.coordinator).get_view(view, 'list')['arch'])
        with self.assertRaises(AccessError):
            Claim.with_user(reader).create(self._manual_vals(self._done()))

    def test_14_new_claim_on_the_form_links_the_replacement(self):
        moves = self.env['account.move'].search_count([])
        replacement = self._done()
        Claim = self.env['warranty.vendor.claim'].with_user(self.coordinator)
        form = Form(Claim)
        form.case_id = self.case
        with form.line_ids.new() as line:
            line.replacement_id = replacement
            self.assertEqual(line.qty, 1.0)
        self.assertEqual(form.partner_id, self.supplier, 'the proposal of Create Vendor Claim')
        form.failure_description = 'Failed after 3 months'
        claim = form.save()
        self.assertEqual(claim.state, 'draft')
        self.assertEqual(claim.case_id, self.case)
        self.assertEqual(claim.claim_type, 'manufacturer')
        self.assertEqual(claim.partner_source, 'manufacturer')
        self.assertEqual(claim.line_ids.replacement_id, replacement)
        self.assertEqual(claim.line_ids.lot_ids, self.old)
        self.assertEqual(claim.claimed_amount, 100.0)
        self.assertEqual(replacement.vendor_claim_count, 1)
        with self.assertRaisesRegex(UserError, 'set by the claim workflow'):
            claim.write({'case_id': self.case.id})
        self.company.warranty_claim_approver_ids = self.gm
        claim.action_submit()
        claim.with_user(self.gm).action_approve()
        self.assertEqual(claim.state, 'approved')
        self.assertEqual(replacement.state, 'done')
        self.assertEqual(self.env['account.move'].search_count([]), moves, 'nothing is posted')

    def test_15_new_claim_keeps_the_rules(self):
        replacement = self._done()
        Claim = self.env['warranty.vendor.claim'].with_user(self.coordinator)
        other = self.env['res.partner'].create({'name': 'Other Vendor'})
        with self.assertRaisesRegex(UserError, 'enter the override reason'), self.env.cr.savepoint():
            Claim.create(self._manual_vals(replacement, partner_id=other.id))
        with self.assertRaisesRegex(UserError, 'not above the verified cost'), self.env.cr.savepoint():
            Claim.create(self._manual_vals(replacement, line_ids=[(0, 0, {
                'replacement_id': replacement.id, 'claimed_amount': 101.0})]))
        other_card = self._card(self.single)
        other_case = self._eligible_case(other_card.unit_warranty_ids.serial_ids)
        with self.assertRaisesRegex(UserError, 'another warranty case'), self.env.cr.savepoint():
            Claim.create(self._manual_vals(replacement, case_id=other_case.id))
        self.single.product_tmpl_id.warranty_vendor_claimable = False
        with self.assertRaisesRegex(UserError, 'Vendor Claimable'), self.env.cr.savepoint():
            Claim.create(self._manual_vals(replacement))
        self.single.product_tmpl_id.warranty_vendor_claimable = True
        empty = Claim.create({'case_id': self.case.id, 'partner_id': self.supplier.id,
                              'failure_description': 'Failed'})
        with self.assertRaisesRegex(UserError, 'Add the claimed parts'), self.env.cr.savepoint():
            empty.action_submit()
        claim = Claim.create(self._manual_vals(replacement, partner_id=other.id,
                                               partner_override_reason='Supplier changed'))
        self.assertEqual(claim.partner_source, 'manual')
        self.assertEqual(claim.proposed_partner_id, self.supplier)
        with self.assertRaisesRegex(UserError, 'already on vendor claim'), self.env.cr.savepoint():
            Claim.create(self._manual_vals(replacement))

    def test_16_new_claim_refuses_other_replacement_types(self):
        self.company.write({'warranty_replacement_full_finance': 'not_required'})
        replacement = self._request(self.case, 'full', self.new)
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        with self.assertRaisesRegex(UserError, 'Done Vendor'):
            self.env['warranty.vendor.claim'].with_user(self.coordinator).create(
                self._manual_vals(replacement))
