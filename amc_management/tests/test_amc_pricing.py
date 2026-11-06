from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import AmcCommon
from ..models.amc_safe_expression import AmcExpressionError, check_expression, \
    evaluate_expression


@tagged('post_install', '-at_install', 'amc')
class TestAmcPricing(AmcCommon):
    """Pricing engine, formula governance, preview and override approval (AMC-D01 .. D13,
    B03, G06, H06). The engine predates 1.1.0 (phase A2 / A3); these tests add the missing
    automated coverage (docs/17)."""

    def _formula(self, plan, **values):
        formula = self.env['amc.pricing.formula'].create(dict({
            'plan_id': plan.id, 'effective_from': date(2020, 1, 1),
            'currency_id': self.currency.id}, **values))
        return formula

    def _price(self, formula, lines, usage=0.0):
        return formula._amc_compute_price(lines, self.currency, date.today(), usage=usage)

    def _lines(self, quantity=10.0, value=1000000.0, sites=1):
        return [{'product': self.equipment_untracked, 'quantity': quantity / sites,
                 'equipment_value': value / sites, 'site': index} for index in range(sites)]

    def test_tc100_srs_formula_examples(self):
        """TC-100 / AMC-D01 .. D08 (SRS 16.2 examples): Fixed 30,000; Per Unit 4,000 x 10;
        Per Visit 8,000 x 3 visits; Percentage 1,000,000 x 8 %; Tiered 11-25 at 4,500; Usage
        20,000 + 15 x hours; Site-Based; Hybrid max(minimum, fixed + % value + visits)."""
        plan = self._create_plan('Pricing (test)', visits=3, free=0)
        one = self._lines(quantity=1.0)
        cases = [
            ({'method': 'fixed', 'fixed_amount': 30000.0}, one, 0.0, 30000.0),
            ({'method': 'per_unit', 'unit_rate': 4000.0}, self._lines(10.0), 0.0, 40000.0),
            ({'method': 'per_visit', 'visit_rate': 8000.0}, one, 0.0, 24000.0),
            ({'method': 'percentage', 'percentage': 8.0}, self._lines(1.0, 1000000.0), 0.0,
             80000.0),
            ({'method': 'usage', 'usage_base': 20000.0, 'usage_rate': 15.0}, one, 1000.0,
             35000.0),
            ({'method': 'site', 'site_rate': 12000.0}, self._lines(4.0, sites=2), 0.0, 24000.0),
            ({'method': 'hybrid',
              'hybrid_expression': 'max(min_price, 5000 + equipment_value * 0.02 + '
                                   'visit_count * 1000)', 'min_price': 25000.0},
             self._lines(1.0, 100000.0), 0.0, 25000.0),
        ]
        for values, lines, usage, expected in cases:
            formula = self._formula(plan, **values)
            self.assertAlmostEqual(self._price(formula, lines, usage)['price'], expected,
                                   msg=values['method'])
        tiered = self._formula(plan, method='tiered', tier_ids=[
            Command.create({'from_value': 1, 'to_value': 10, 'rate': 5000.0}),
            Command.create({'from_value': 11, 'to_value': 25, 'rate': 4500.0})])
        self.assertEqual(self._price(tiered, self._lines(12.0))['price'], 12 * 4500.0)
        with self.assertRaises(UserError):
            self._price(tiered, self._lines(30.0))

    def test_tc101_min_max_rounding_factors(self):
        """TC-101 / AMC-D11 / G06: minimum, maximum, rounding step and product / category
        factors."""
        plan = self._create_plan('Rounding (test)', visits=1, free=0)
        formula = self._formula(plan, method='per_unit', unit_rate=1234.0, rounding_step=100.0,
                                min_price=2000.0, max_price=20000.0, factor_ids=[
                                    Command.create({'category_id': self.category.id,
                                                    'factor': 1.5})])
        self.assertEqual(self._price(formula, self._lines(1.0))['price'], 2000.0)  # minimum
        self.assertEqual(self._price(formula, self._lines(5.0))['price'], 9300.0)  # 9255 -> 9300
        self.assertEqual(self._price(formula, self._lines(50.0))['price'], 20000.0)  # maximum
        with self.assertRaises(ValidationError):
            self._formula(plan, method='fixed', fixed_amount=1.0, min_price=10.0, max_price=5.0)

    def test_tc102_controlled_expression(self):
        """TC-102 / AMC-D09 / D10 / D12: only numbers, approved variables, + - * / and
        min / max / round / abs; anything else is rejected before evaluation."""
        allowed = ('equipment_value', 'quantity')
        self.assertEqual(evaluate_expression('round(quantity * 2.5, 0) + abs(-1)',
                                             {'quantity': 3.0}), 9.0)
        for expression in ('__import__("os")', 'quantity ** 2', 'quantity.real',
                           'open("x")', 'price', 'quantity if 1 else 2', '[1, 2]', '"text"',
                           'lambda: 1', '', 'x' * 600, 'quantity / 0'):
            with self.assertRaises(AmcExpressionError, msg=expression):
                if expression == 'quantity / 0':
                    evaluate_expression(expression, {'quantity': 1.0})
                else:
                    check_expression(expression, allowed)
        plan = self._create_plan('Hybrid (test)', visits=1, free=0)
        with self.assertRaises(ValidationError):
            self._formula(plan, method='hybrid', hybrid_expression='quantity ** 2')

    def test_tc103_formula_versions(self):
        """TC-103 / AMC-D11: Active versions are locked; activating a new version ends the
        open-ended previous one the day before; overlaps are refused; Draft only deletable."""
        plan = self.plan_retail
        current = plan.current_formula_id
        with self.assertRaises(UserError):
            current.write({'fixed_amount': 1.0})
        with self.assertRaises(UserError):
            current.unlink()
        new = self.env['amc.pricing.formula'].browse(current.action_new_version()['res_id'])
        new.write({'effective_from': date.today() + timedelta(days=10), 'fixed_amount': 33000.0})
        new.action_activate()
        self.assertEqual(current.effective_to, new.effective_from - timedelta(days=1))
        self.assertEqual(plan._amc_pricing_formula(date.today()), current)
        self.assertEqual(plan._amc_pricing_formula(date.today() + timedelta(days=10)), new)
        # Approved P1: an earlier version is ended automatically; a version that would run into
        # a later Active version is refused.
        overlapping = self._formula(plan, method='fixed', fixed_amount=1.0,
                                    effective_from=date.today() + timedelta(days=5))
        overlapping.effective_to = date.today() + timedelta(days=15)
        with self.assertRaises(UserError):
            overlapping.action_activate()
        with self.assertRaises(UserError):
            current.with_user(self.user_coordinator).action_archive_version()

    def test_tc104_price_preview(self):
        """TC-104 / AMC-D12: the Price Preview calculates with the formula in force and stores
        nothing on contracts."""
        preview = self.env['amc.pricing.preview'].create({
            'plan_id': self.plan_retail.id, 'partner_id': self.customer.id,
            'line_ids': [Command.create({'product_id': self.equipment_untracked.id,
                                         'quantity': 2.0})]})
        preview.action_calculate()
        self.assertEqual(preview.price, 30000.0)
        self.assertIn('Final price', preview.breakdown)

    def test_tc105_override_approval(self):
        """TC-105 / AMC-D13 / H06: a Coordinator requests a price override with a reason; the
        requester cannot approve; an AMC Approver of the company can; the price is used."""
        approver = self.user_manager
        approver.groups_id |= self.env.ref('amc_management.group_amc_approver')
        contract = self._create_contract()
        contract.action_compute_price()
        request = self.env['amc.price.override'].with_user(self.user_coordinator).create({
            'contract_id': contract.id, 'override_type': 'price', 'requested_price': 27500.0,
            'reason': 'Long-term customer'})
        with self.assertRaises(AccessError):
            request.with_user(self.user_coordinator).action_approve()
        with self.assertRaises(UserError):
            contract.action_create_quotation()
        request.with_user(approver).action_approve()
        self.assertEqual(contract.price, 27500.0)
        self.assertEqual(request.decided_by_id, approver)
        with self.assertRaises(UserError):
            request.unlink()
        self._sell(contract)
        self.assertEqual(contract.sale_order_id.amount_untaxed, 27500.0)

    def test_tc106_product_applicability(self):
        """TC-106 / AMC-B03: a plan limited to products / categories refuses other equipment."""
        other = self.env['product.product'].create({'name': 'Water heater', 'type': 'consu'})
        self.plan_project.category_ids = [Command.set(self.category.ids)]
        self._create_contract(plan=self.plan_project)
        with self.assertRaises(ValidationError):
            self._create_contract(plan=self.plan_project,
                                  lines=[{'product_id': other.id, 'quantity': 1.0}])

    def test_tc108_target_currency_rounding_rules(self):
        """TC-108 / AMC-D11 (defect DEF-09: the rule constraint raised NameError): a rounding
        rule needs a positive step, another currency than the formula's, once per currency."""
        plan = self._create_plan('Currency rounding (test)', visits=1, free=0)
        other = self.setup_other_currency('EUR')
        formula = self._formula(plan, method='fixed', fixed_amount=1000.0)
        with self.assertRaises(ValidationError):
            self.env['amc.pricing.rounding'].create({'formula_id': formula.id,
                                                     'currency_id': other.id, 'step': 0.0})
        with self.assertRaises(ValidationError):
            self.env['amc.pricing.rounding'].create({'formula_id': formula.id,
                                                     'currency_id': self.currency.id,
                                                     'step': 10.0})
        self.env['amc.pricing.rounding'].create({'formula_id': formula.id,
                                                 'currency_id': other.id, 'step': 10.0})
        result = formula._amc_compute_price(self._lines(1.0), other, date.today())
        self.assertEqual(result['price'] % 10, 0)

    def test_tc107_cancel_before_activation(self):
        """TC-107 / AMC-C02: a Quotation contract is cancelled by an AMC Manager with a reason;
        its quotation is cancelled; no entitlement exists."""
        contract = self._create_contract()
        contract.action_compute_price()
        contract.action_create_quotation()
        order = contract.sale_order_id
        contract.with_user(self.user_manager).action_cancel_contract('Customer declined')
        self.assertEqual(contract.state, 'cancelled')
        self.assertEqual(order.state, 'cancel')
        self.assertFalse(contract.visit_ids)
