from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_inspection_fee_adjustment import InspectionFlowCommon


@tagged('post_install', '-at_install', 'warranty_cost', 'warranty_inspection_coverage')
class TestInspectionQuotationCoverage(InspectionFlowCommon):
    """Inspection Quotation coverage (Approved, Eligible case with Inspection Required): only an
    explicit coverage item of the Inspection Product makes the fee 0.00 (100% discount, price
    kept); Excluded wins; Not Listed stays chargeable; no fee credit when nothing was charged."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Item = cls.env['warranty.coverage.item']
        cls.labour = Item.create({'name': 'Labour', 'product_id': cls.env['product.product'].create(
            {'name': 'Labour', 'type': 'consu', 'list_price': 1.0}).id})
        cls.inspection_item = Item.create({'name': 'Inspection',
                                           'product_id': cls.fee_product.id})
        # Labour and Parts covered, as policy "AT - Machinery Warranty 12 Months" on UAT.
        cls.policy.covered_item_ids |= cls.labour

    def _quotation(self, trigger='sale_confirmation'):
        case = self._approved()
        case.sudo().write({'warranty_inspection_required': True,
                           'warranty_inspection_trigger': trigger})
        with self._today(date(2026, 11, 1)):
            case.with_user(self.sales_user).action_prepare_service_job()
        order = case._warranty_inspection_orders()
        self.assertEqual(len(order), 1)
        self.assertEqual(len(order.order_line), 1, 'one inspection line, no labour or parts')
        return case, order, order.order_line

    def _confirm(self, order):
        with self._today(date(2026, 11, 1)):
            order.with_user(self.sales_user).action_confirm()

    def test_01_not_listed_stays_chargeable(self):
        """Labour / Parts covered does not cover the inspection: today's 1,500 + tax."""
        case, order, line = self._quotation()
        self.assertEqual((line.warranty_inspection_coverage, line.discount, line.price_unit),
                         ('not_listed', 0.0, 1500.0))
        self.assertEqual((order.amount_untaxed, order.amount_tax, order.amount_total),
                         (1500.0, 225.0, 1725.0))
        self.assertIn('Inspection coverage: Not Listed', case.message_ids[0].body)

    def test_02_covered_zero_quotation_and_trigger(self):
        """Covered: original price kept, 100% discount, 0.00 with its tax; confirmation keeps the
        existing trigger (service job) and audit trail."""
        self.policy.covered_item_ids |= self.inspection_item
        case, order, line = self._quotation()
        self.assertEqual((line.warranty_inspection_coverage, line.discount, line.price_unit,
                          line.product_uom_qty, line.tax_id),
                         ('covered', 100.0, 1500.0, 1.0, self.tax))
        self.assertEqual((order.amount_untaxed, order.amount_tax, order.amount_total),
                         (0.0, 0.0, 0.0))
        self.assertEqual(line.price_unit * line.product_uom_qty * line.discount / 100, 1500.0,
                         'covered amount kept on the line')
        self.assertIn('Inspection coverage: Covered (Inspection)', case.message_ids[0].body)
        self.assertEqual(case.warranty_inspection_step, 'waiting')
        self._confirm(order)
        self.assertEqual(order.state, 'sale')
        self.assertTrue(case.open_service_job_id, 'the existing trigger creates the job')
        self.assertEqual(case.open_service_job_id.state, 'draft')

    def test_03_excluded_wins_over_covered(self):
        self.policy.covered_item_ids |= self.inspection_item
        self.policy.excluded_item_ids |= self.inspection_item
        _case, order, line = self._quotation()
        self.assertEqual((line.warranty_inspection_coverage, line.discount), ('excluded', 0.0))
        self.assertEqual(order.amount_total, 1725.0)

    def test_04_no_fee_credit_when_nothing_charged(self):
        """A covered fee invoiced at 0.00: the inspection fee adjustment creates no credit note."""
        self.policy.covered_item_ids |= self.inspection_item
        case, order, _line = self._quotation()
        self._confirm(order)
        invoice = self._posted_invoice(order)
        self.assertEqual((invoice.amount_total, invoice.payment_state), (0.0, 'paid'))
        repair = self.env['sale.order'].create({
            'partner_id': order.partner_id.id, 'warranty_case_id': case.id,
            'order_line': [(0, 0, {'product_id': self.repair_product.id, 'price_unit': 5000.0})]})
        repair.warranty_chargeable_purpose = 'repair'
        repair.action_confirm()
        notes = self.env['account.move'].search_count([('move_type', '=', 'out_refund')])
        with self.assertRaisesRegex(UserError, 'no fee to adjust'):
            self._apply(case)
        self.assertEqual(self.env['account.move'].search_count([('move_type', '=', 'out_refund')]),
                         notes)
        self.assertFalse(case.warranty_inspection_credit_note_ids)

    def test_05_covered_on_payment_trigger(self):
        """On Payment: the 0.00 invoice of a covered fee meets the trigger once posted."""
        self.policy.covered_item_ids |= self.inspection_item
        case, order, _line = self._quotation(trigger='payment')
        self._confirm(order)
        self.assertFalse(case._warranty_trigger_met(order), 'not invoiced yet')
        self._posted_invoice(order)
        self.assertTrue(case._warranty_trigger_met(order))
        self.assertTrue(case.open_service_job_id, 'job created when the 0.00 invoice is posted')
