from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .test_warranty_case_approval import TestWarrantyCaseApproval


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCaseChargeable(TestWarrantyCaseApproval):
    """Part 3.6c - chargeable conversion and partial coverage (approved Q49-Q58)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sales_user = cls._user('wcase_sales_helpdesk', 'helpdesk.group_helpdesk_user')
        cls.sales_user.groups_id |= cls.env.ref('sales_team.group_sale_salesman_all_leads')
        Product = cls.env['product.product']
        cls.gas_product = Product.create({'name': 'Gas Refill Service', 'type': 'service',
                                          'list_price': 2500.0})
        cls.inspection_product = Product.create({'name': 'Inspection Fee', 'type': 'service',
                                                 'list_price': 1000.0})
        cls.item_gas.product_id = cls.gas_product
        cls.team.write({'warranty_inspection_required': False,
                        'warranty_inspection_product_id': cls.inspection_product.id,
                        'warranty_inspection_amount': 850.0})

    def _partial(self):
        case = self._create_case(self.ticket, user=self.creator,
                                 requested_items=self.item_service | self.item_gas)
        self.assertEqual(self._result(case), 'partial')
        return case

    def _quote(self, case):
        action = case.with_user(self.sales_user).action_create_excluded_quotation()
        return self.env['sale.order'].browse(action['res_id'])

    def _gas(self, case):
        return case.excluded_item_ids.filtered(lambda i: i.coverage_item_id == self.item_gas)

    def _decline(self, items, reason='Customer will buy gas elsewhere', user=None):
        user = user or self.helpdesk_user
        action = items.with_user(user).action_open_decline_wizard()
        wizard = self.env['warranty.case.decline.wizard'].with_user(user).with_context(
            action['context']).create({'decline_reason': reason})
        return wizard.action_decline()

    def test_71_partial_quotation_waiting(self):
        """Partial: Excluded Items list; Create Excluded Items Quotation -> Draft quotation
        linked to the case / item, status and result unchanged, Waiting Customer Approval; no
        email to the customer."""
        case = self._partial()
        item = self._gas(case)
        self.assertEqual(item.customer_decision, 'quotation_required')
        self.assertTrue(case.excluded_decision_pending)
        mails = self.env['mail.mail'].search_count([])
        order = self._quote(case)
        self.assertEqual((order.state, order.warranty_case_id, order.company_id),
                         ('draft', case, case.company_id))
        self.assertEqual(order.partner_id, self.customer)
        self.assertEqual(order.order_line.warranty_excluded_item_id, item)
        self.assertEqual((case.state, case.eligibility_result), ('eligibility_checked', 'partial'))
        self.assertEqual((item.customer_decision, item.quoted_qty), ('waiting', 1.0))
        self.assertEqual(case.quotation_count, 1)
        self.assertEqual(self.env['mail.mail'].search_count([]), mails, 'no customer email')
        self.assertEqual(self._result(case), 'partial')
        self.assertIn('waiting for the customer decision', self._last_note(case))
        with self.assertRaises(UserError):
            self._quote(case)

    def test_72_confirmed_quotation_then_eligible(self):
        """Confirmed quotation: item Customer Approved (chargeable, confirmed qty); the covered
        work continues -> Eligible -> Approve Case (3.6a unchanged)."""
        case = self._partial()
        order = self._quote(case)
        order.order_line.product_uom_qty = 2
        order.action_confirm()
        item = self._gas(case)
        self.assertEqual((item.customer_decision, item.confirmed_qty), ('approved', 2.0))
        self.assertEqual(self._result(case), 'eligible')
        self.assertIn('confirmed qty 2.0', self._last_note(case))
        self.assertIn('the excluded items stay chargeable', self._last_note(case))
        self.assertNotIn(self.item_gas, self.policy.covered_item_ids)
        case.with_user(self.approver_a).action_approve_case()
        self.assertEqual(case.state, 'approved')
        # Q57: a confirmed quantity reduced but > 0 stays approved.
        order.order_line.product_uom_qty = 1
        self.assertEqual((item.customer_decision, item.confirmed_qty), ('approved', 1.0))

    def test_73_customer_declined_and_undo(self):
        """Customer Declined: reason required, line removed from the Draft quotation (cancelled
        when empty), covered work continues; Undo Decline -> Quotation Required again, refused
        after approval (Q55 / Q56)."""
        case = self._partial()
        order = self._quote(case)
        item = self._gas(case)
        with self.assertRaises(UserError):
            item.with_user(self.helpdesk_user)._warranty_decline('  ')
        self._decline(item)
        self.assertEqual((item.customer_decision, item.decided_by_id), ('declined',
                                                                         self.helpdesk_user))
        self.assertFalse(order.order_line)
        self.assertEqual(order.state, 'cancel')
        self.assertIn('Customer declined Case Gas Refill', case.message_ids[:1].body)
        self.assertEqual(self._result(case), 'eligible')
        item.with_user(self.helpdesk_user).action_undo_decline()
        self.assertEqual(item.customer_decision, 'quotation_required')
        self.assertEqual(self._result(case), 'partial')
        self._decline(item)
        self.assertEqual(self._result(case), 'eligible')
        case.with_user(self.approver_a).action_approve_case()
        with self.assertRaises(UserError):
            item.with_user(self.helpdesk_user).action_undo_decline()

    def test_74_internal_cancel_is_not_decline(self):
        """An internally cancelled / replaced quotation is not a customer decline: Quotation
        Required, a new quotation can be created; only one active line per item."""
        case = self._partial()
        order = self._quote(case)
        order.with_context(disable_cancel_warning=True).action_cancel()
        item = self._gas(case)
        self.assertEqual(item.customer_decision, 'quotation_required')
        self.assertEqual(self._result(case), 'partial')
        new = self._quote(case)
        self.assertEqual(item.customer_decision, 'waiting')
        self.assertEqual(case.quotation_count, 2)
        with self.assertRaises(ValidationError):
            new.order_line.copy({'order_id': new.id, 'warranty_excluded_item_id': item.id})
        # Quantity 0 on the quotation: Quotation Required again.
        new.order_line.product_uom_qty = 0
        self.assertEqual(item.customer_decision, 'quotation_required')

    def test_75_decline_rules(self):
        """No decline on a confirmed order; only Helpdesk users; product required on the
        coverage item for the quotation."""
        case = self._partial()
        order = self._quote(case)
        order.action_confirm()
        with self.assertRaises(UserError):
            self._decline(self._gas(case))
        with self.assertRaises(AccessError):
            self._gas(case).with_user(self.internal_user).action_open_decline_wizard()
        self.item_gas.product_id = False
        other = self._partial()
        with self.assertRaises(UserError):
            self._quote(other)

    def test_76_convert_not_eligible_to_chargeable(self):
        """Not Eligible -> Convert to Chargeable: status Chargeable, Chargeable Type, original
        case type kept, draft quotation with the inspection (team) and excluded item lines;
        approval activities closed; no further eligibility check."""
        self.team.warranty_inspection_required = True
        case = self._create_case(self.ticket, user=self.creator, requested_items=self.item_gas)
        self.assertEqual(self._result(case), 'not_eligible')
        action = case.with_user(self.sales_user).action_open_chargeable_wizard()
        self.assertEqual(action['context']['default_chargeable_type'], 'excluded_items')
        wizard = self.env['warranty.case.chargeable.wizard'].with_user(self.sales_user).with_context(
            action['context']).create({})
        order = self.env['sale.order'].browse(wizard.action_convert()['res_id'])
        self.assertEqual((case.state, case.chargeable_type, case.case_type,
                          case.chargeable_converted_by_id),
                         ('chargeable', 'excluded_items', 'warranty_complaint', self.sales_user))
        inspection = order.order_line.filtered(lambda l: l.product_id == self.inspection_product)
        self.assertEqual(inspection.price_unit, 850.0)
        self.assertEqual(order.order_line.warranty_excluded_item_id, self._gas(case))
        self.assertEqual(order.state, 'draft')
        with self.assertRaises(UserError):
            case.with_user(self.helpdesk_user).action_check_eligibility()
        self.assertIn('Converted to chargeable (Excluded Items)', case.message_ids[:1].body)

    def test_77_conversion_rules(self):
        """Partial is never converted (covered work stays warranty); chargeable case types
        convert from New; without quotation lines no quotation and no sales rights needed."""
        partial = self._partial()
        with self.assertRaises(UserError):
            partial.with_user(self.sales_user).action_open_chargeable_wizard()
        repair = self._create_case(self.ticket, case_type='chargeable_repair')
        action = repair.with_user(self.helpdesk_user).action_open_chargeable_wizard()
        self.assertEqual(action['context']['default_chargeable_type'], 'repair')
        self.assertTrue(repair.with_user(self.helpdesk_user)._warranty_convert_chargeable('repair'))
        self.assertEqual((repair.state, repair.quotation_count), ('chargeable', 0))
        # Inspection required: a Helpdesk user without sales rights cannot create quotations.
        self.team.warranty_inspection_required = True
        inspection = self._create_case(self.ticket, case_type='chargeable_inspection')
        with self.assertRaises(AccessError):
            inspection.with_user(self.helpdesk_user)._warranty_convert_chargeable('inspection')
        self.assertEqual(inspection.state, 'new')
        with self.assertRaises(AccessError):
            inspection.with_user(self.internal_user).action_open_chargeable_wizard()

    def test_78_approval_revalidation_with_excluded_items(self):
        """3.6a revalidation keeps the customer decisions (no new requests)."""
        case = self._partial()
        self._quote(case).action_confirm()
        self.assertEqual(self._result(case), 'eligible')
        case.with_user(self.approver_a).action_approve_case()
        self.assertEqual((case.state, case.eligibility_result), ('approved', 'eligible'))

    def test_79_multi_company(self):
        """Another company's users cannot convert the case or see its excluded items."""
        case = self._create_case(self.ticket, user=self.creator, requested_items=self.item_gas)
        self._result(case)
        with self.assertRaises(AccessError):
            case.with_user(self.foreign_user).action_open_chargeable_wizard()
        self.assertFalse(self.env['warranty.case.excluded.item'].with_user(
            self.foreign_user).search([('case_id', '=', case.id)]))

    def test_80_quotations_button_on_chargeable_case(self):
        """Quotations smart button also on Chargeable cases with 0 quotations; it opens the
        case's quotations and a new quotation gets the customer and the warranty case."""
        arch = ' '.join(self.env['warranty.case'].get_view(view_type='form')['arch'].split())
        self.assertIn('name="action_view_quotations" type="object" class="oe_stat_button" '
                      'icon="fa-pencil-square-o" invisible="not quotation_count and state != '
                      '\'chargeable\'"', arch.replace('groups="sales_team.group_sale_salesman" ', ''))
        repair = self._create_case(self.ticket, case_type='chargeable_repair')
        repair.with_user(self.helpdesk_user)._warranty_convert_chargeable('repair')
        self.assertEqual((repair.state, repair.quotation_count), ('chargeable', 0))
        action = repair.with_user(self.sales_user).action_view_quotations()
        self.assertEqual(action['domain'], [('warranty_case_id', '=', repair.id)])
        order = self.env['sale.order'].with_user(self.sales_user).with_context(
            action['context']).create({'order_line': [(0, 0, {
                'product_id': self.gas_product.id, 'product_uom_qty': 1})]})
        self.assertEqual((order.warranty_case_id, order.partner_id), (repair, self.customer))
        repair.invalidate_recordset(['quotation_count', 'sale_order_ids'])
        self.assertEqual(repair.quotation_count, 1)
        self.assertEqual(self.env['sale.order'].search(action['domain']), order)
