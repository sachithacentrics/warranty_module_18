import re
from datetime import date

from lxml import etree

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged

from .common import confirm_and_group, set_installation


@tagged('post_install', '-at_install', 'warranty_part1')
class TestWarrantyPart1(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'installation',
            'default_warranty_duration': 0,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Warranty Customer'})
        cls.retail = cls.env['product.pricelist'].create({
            'name': 'Retail Pricelist', 'company_id': cls.company.id})
        cls.project = cls.env['product.pricelist'].create({'name': 'Project Pricelist'})
        cls.categ = cls.env['product.category'].create({'name': 'Air Conditioners'})
        cls.stock_location = cls.env.ref('stock.stock_location_stock')

    # ------------------------------------------------------------------ helpers
    def _product(self, name, tracking='none', **vals):
        values = {
            'name': name,
            'type': 'consu',
            'is_storable': True,
            'tracking': tracking,
            'categ_id': self.categ.id,
            'invoice_policy': 'order',
            'warranty_applicable': True,
            'default_warranty_period': 12,
            'default_warranty_period_unit': 'months',
            'default_free_service_count': 3,
            'free_service_frequency': 4,
            'free_service_frequency_unit': 'months',
        }
        values.update(vals)
        product = self.env['product.product'].create(values)
        if tracking == 'serial':
            for index in range(5):
                lot = self.env['stock.lot'].create({
                    'name': '%s-SN-%s' % (name, index), 'product_id': product.id})
                self.env['stock.quant']._update_available_quantity(
                    product, self.stock_location, 1, lot_id=lot)
        else:
            self.env['stock.quant']._update_available_quantity(product, self.stock_location, 20)
        return product

    def _order(self, lines, pricelist=None, confirm=True, grouping='per_so'):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'pricelist_id': (pricelist or self.retail).id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': qty})
                           for product, qty in lines],
        })
        if confirm:
            confirm_and_group(order, grouping)
        return order

    def _deliver(self, order, quantities=None):
        """Validate the outgoing picking; quantities {product: qty} creates a backorder."""
        picking = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))[:1]
        picking.action_assign()
        for move in picking.move_ids:
            if quantities and move.product_id in quantities:
                move.quantity = quantities[move.product_id]
            move.picked = True
        res = picking.button_validate()
        if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
            Form(self.env[res['res_model']].with_context(res['context'])).save().process()
        return picking

    def _invoice(self, order, pay=False):
        invoice = order._create_invoices()
        invoice.action_post()
        if pay:
            self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        return invoice

    # ------------------------------------------------------------------ tests
    def test_01_models_and_fields(self):
        """T01: documented models and technical fields exist (tasks 3-9)."""
        expected = {
            'res.company': ['warranty_scope_mode', 'default_warranty_policy_id',
                            'default_card_grouping_mode', 'warranty_auto_create_services',
                            'warranty_draft_job_from_service', 'default_warranty_basis',
                            'default_start_criterion', 'default_warranty_duration',
                            'default_warranty_duration_unit'],
            'warranty.policy': ['name', 'applies_to', 'pricelist_ids', 'sale_order_type_id',
                                'warranty_duration', 'warranty_duration_unit', 'start_date_basis',
                                'free_service_count', 'free_service_period',
                                'free_service_period_unit', 'free_service_frequency',
                                'free_service_frequency_unit', 'usage_limit', 'schedule_method',
                                'payment_check_required', 'covered_item_ids', 'excluded_item_ids',
                                'replacement_date_policy', 'warranty_basis', 'usage_unit',
                                'card_grouping_mode', 'auto_create_services',
                                'draft_job_from_service', 'overdue_claim_handling'],
            'product.template': ['warranty_applicable', 'warranty_start_criterion',
                                 'warranty_basis', 'default_warranty_period',
                                 'default_warranty_period_unit', 'default_free_service_count',
                                 'free_service_frequency', 'free_service_frequency_unit',
                                 'warranty_worksheet_template_id', 'warranty_pricelist_rule_ids'],
            'warranty.product.pricelist.rule': ['pricelist_id', 'warranty_period',
                                                'warranty_period_unit', 'free_service_count',
                                                'free_service_frequency',
                                                'free_service_frequency_unit', 'usage_limit',
                                                'usage_unit', 'effective_from', 'effective_to',
                                                'priority', 'active'],
            'warranty.card': ['name', 'partner_id', 'product_id',
                              'indoor_serial_id', 'outdoor_serial_id', 'sale_order_id',
                              'delivery_ids', 'invoice_ids', 'installation_date',
                              'warranty_start_date', 'warranty_end_date', 'state',
                              'free_services_allowed', 'free_services_used',
                              'free_services_balance', 'replacement_count',
                              'current_active_serial', 'pdf_attachment_id', 'print_count',
                              'card_grouping_mode', 'unit_warranty_ids', 'warranty_basis',
                              'start_criterion', 'confirmation_status', 'company_id',
                              'currency_id', 'policy_id', 'pricelist_id', 'policy_source',
                              'sale_order_line_ids'],
            'product.pricelist': ['warranty_applicable', 'warranty_policy_id'],
            'warranty.unit': ['name', 'warranty_card_id', 'sale_order_line_id', 'product_id',
                              'unit_number', 'stock_move_line_id', 'serial_ids', 'start_date',
                              'end_date', 'usage_limit', 'usage_unit', 'state'],
        }
        for model, field_names in expected.items():
            missing = [f for f in field_names if f not in self.env[model]._fields]
            self.assertFalse(missing, '%s missing fields %s' % (model, missing))
        card_states = [s[0] for s in self.env['warranty.card']._fields['state'].selection]
        self.assertEqual(card_states,
                         ['draft', 'pending_installation', 'ready', 'confirmed', 'suspended',
                          'expired', 'cancelled'])
        unit_states = [s[0] for s in self.env['warranty.unit']._fields['state'].selection]
        self.assertEqual(unit_states,
                         ['draft', 'active', 'replaced', 'suspended', 'expired', 'cancelled'])

    def test_02_not_applicable(self):
        """T03: Warranty Applicable = No -> no card / unit number."""
        product = self._product('Plain Item', warranty_applicable=False)
        order = self._order([(product, 2)])
        self.assertEqual(order.state, 'sale')
        self.assertFalse(order.warranty_card_ids)
        self.assertFalse(order.warranty_unit_ids)

    def test_03_sequences_and_units(self):
        """T02/T09: draft card WC/xxxxx, one unit WN/xxxxx-xx per quantity, per SO grouping."""
        ac = self._product('AC A')
        fan = self._product('Fan B')
        order = self._order([(ac, 2), (fan, 1)])
        card = order.warranty_card_ids
        self.assertEqual(len(card), 1)
        self.assertEqual(card.state, 'draft')
        self.assertRegex(card.name, r'^WC/\d{5}$')
        digits = card.name.split('/')[1]
        self.assertEqual(sorted(card.unit_warranty_ids.mapped('name')),
                         ['WN/%s-01' % digits, 'WN/%s-02' % digits, 'WN/%s-03' % digits])
        self.assertEqual(sorted(card.unit_warranty_ids.mapped('unit_number')), [1, 1, 2])
        self.assertTrue(all(u.state == 'draft' for u in card.unit_warranty_ids))
        self.assertEqual(card.sale_order_line_ids, order.order_line)
        self.assertFalse(card.product_id, 'multi-product card has no single product')
        self.assertEqual(order.warranty_card_count, 1)
        self.assertEqual(order.warranty_unit_count, 3)
        self.assertEqual(order.action_view_warranty_cards()['domain'],
                         [('sale_order_id', '=', order.id)])

    def test_04_pricelist_rule_priority(self):
        """T04: the Warranty Policy of the order's pricelist (Warranty Applicable) wins, per
        pricelist; unticked it is ignored; legacy Product + Pricelist mapping lines are kept
        but not used."""
        ac = self._product('AC Rule')
        policy = self.env['warranty.policy'].create({
            'name': 'Retail Pricelist Policy', 'warranty_duration': 24,
            'warranty_duration_unit': 'months', 'free_service_count': 5})
        self.retail.write({'warranty_applicable': True, 'warranty_policy_id': policy.id})
        ac.product_tmpl_id.write({'warranty_pricelist_rule_ids': [
            (0, 0, {'pricelist_id': self.retail.id, 'warranty_period': 18,
                    'warranty_period_unit': 'months', 'free_service_count': 4, 'priority': 5}),
            (0, 0, {'pricelist_id': self.project.id, 'warranty_period': 36,
                    'warranty_period_unit': 'months', 'priority': 1}),
        ]})
        card = self._order([(ac, 1)]).warranty_card_ids
        self.assertEqual((card.policy_source, card.policy_id), ('pricelist_policy', policy))
        self.assertEqual((card.warranty_duration, card.free_services_allowed), (24, 5))
        self.assertEqual(card.pricelist_id, self.retail)
        # Project pricelist without warranty policy: product default (mapping line ignored).
        card_project = self._order([(ac, 1)], pricelist=self.project).warranty_card_ids
        self.assertEqual((card_project.policy_source, card_project.warranty_duration),
                         ('product', 12))
        # Warranty Applicable unticked on the pricelist: its policy is ignored.
        self.retail.warranty_applicable = False
        card = self._order([(ac, 1)]).warranty_card_ids
        self.assertEqual((card.policy_source, card.warranty_duration), ('product', 12))
        self.assertEqual(len(ac.product_tmpl_id.with_context(
            active_test=False).warranty_pricelist_rule_ids), 2, 'legacy lines kept')

    def test_05_hierarchy_fallbacks(self):
        """T05-T07: product default > category > company fallback."""
        ac = self._product('AC Default')
        self.assertEqual(self._order([(ac, 1)]).warranty_card_ids.policy_source, 'product')

        categ_product = self._product('AC Categ', default_warranty_period=0,
                                      default_free_service_count=0)
        self.categ.write({'default_warranty_period': 6, 'default_warranty_period_unit': 'months',
                          'default_free_service_count': 2})
        card = self._order([(categ_product, 1)]).warranty_card_ids
        self.assertEqual((card.policy_source, card.warranty_duration, card.free_services_allowed),
                         ('category', 6, 2))

        self.categ.default_warranty_period = 0
        self.company.write({'default_warranty_duration': 1,
                            'default_warranty_duration_unit': 'years'})
        card = self._order([(categ_product, 1)]).warranty_card_ids
        self.assertEqual((card.policy_source, card.warranty_duration,
                          card.warranty_duration_unit), ('company', 1, 'years'))

    def test_06_configuration_required(self):
        """T08: no rule at any level -> Configuration Required, SO not confirmed."""
        product = self._product('AC No Rule', default_warranty_period=0)
        order = self._order([(product, 1)], confirm=False)
        with self.assertRaisesRegex(UserError, 'Configuration Required'):
            order.action_confirm()

    def test_07_incompatible_lines_split(self):
        """T10: incompatible start criterion forces separate cards."""
        ac = self._product('AC Install', warranty_start_criterion='installation')
        tv = self._product('TV Delivery', warranty_start_criterion='delivery')
        order = self._order([(ac, 1), (tv, 1)])
        self.assertEqual(len(order.warranty_card_ids), 2)
        self.assertEqual(set(order.warranty_card_ids.mapped('start_criterion')),
                         {'installation', 'delivery'})

    def test_08_grouping_per_product_and_unit(self):
        """T11/T12: per product and per unit/serial grouping."""
        ac = self._product('AC PP')
        fan = self._product('Fan PP')
        order = self._order([(ac, 2), (fan, 1)], grouping='per_product')
        self.assertEqual(len(order.warranty_card_ids), 2)
        self.assertEqual(sorted(len(c.unit_warranty_ids) for c in order.warranty_card_ids), [1, 2])

        order = self._order([(ac, 2)], grouping='per_unit')
        self.assertEqual(len(order.warranty_card_ids), 2)
        self.assertTrue(all(len(c.unit_warranty_ids) == 1 for c in order.warranty_card_ids))
        self.assertTrue(all(re.match(r'^WN/\d{5}-01$', u.name) for u in order.warranty_unit_ids))

    def test_09_delivery_serial_allocation(self):
        """T14: delivery validation updates delivery and allocates serials; delivery
        criterion -> Ready to Confirm."""
        ac = self._product('AC Serial', tracking='serial', warranty_start_criterion='delivery')
        order = self._order([(ac, 2)])
        card = order.warranty_card_ids
        self.assertEqual(card.state, 'draft')
        self.assertIn('Delivery for unit', card.missing_requirements)
        picking = self._deliver(order)
        self.assertEqual(card.delivery_ids, picking)
        for unit in card.unit_warranty_ids:
            self.assertTrue(unit.stock_move_line_id)
            self.assertEqual(len(unit.serial_ids), 1)
        self.assertEqual(len(card.unit_warranty_ids.serial_ids), 2)
        self.assertEqual(card.state, 'ready')
        card.action_confirm_warranty()
        expected_start = fields.Datetime.context_timestamp(card, picking.date_done).date()
        self.assertEqual(card.warranty_start_date, expected_start)

    def test_10_per_delivery_partial(self):
        """T13: per delivery grouping, partial delivery moves waiting units to a new draft card."""
        ac = self._product('AC PD', warranty_start_criterion='delivery')
        order = self._order([(ac, 3)], grouping='per_delivery')
        card = order.warranty_card_ids
        self.assertEqual(len(card.unit_warranty_ids), 3)
        picking = self._deliver(order, {ac: 1})
        cards = order.warranty_card_ids
        self.assertEqual(len(cards), 2)
        new_card = cards - card
        self.assertEqual(len(card.unit_warranty_ids), 1)
        self.assertEqual(card.delivery_ids, picking)
        self.assertEqual(len(new_card.unit_warranty_ids), 2)
        self.assertEqual(new_card.delivery_ids, picking.backorder_ids)
        self.assertEqual(new_card.state, 'draft')
        self.assertEqual(card.state, 'ready')
        digits = new_card.name.split('/')[1]
        self.assertEqual(sorted(new_card.unit_warranty_ids.mapped('name')),
                         ['WN/%s-01' % digits, 'WN/%s-02' % digits])
        self._deliver(order)
        self.assertEqual(new_card.state, 'ready')

    def test_11_installation_confirmation(self):
        """T16/T21: installation criterion, dates calculation, activation and soft copy."""
        ac = self._product('AC Inst')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        self.assertEqual(card.state, 'pending_installation', 'only the installation missing')
        self.assertIn('Installation', card.missing_requirements)
        with self.assertRaises(UserError):
            card.action_confirm_warranty()
        set_installation(card, date(2026, 7, 15))
        self.assertEqual(card.state, 'ready')
        card.action_confirm_warranty()
        self.assertEqual(card.state, 'confirmed')
        self.assertEqual(card.confirmation_status, 'confirmed')
        self.assertEqual(card.warranty_start_date, date(2026, 7, 15))
        self.assertEqual(card.warranty_end_date, date(2027, 7, 14))
        unit = card.unit_warranty_ids
        self.assertEqual((unit.state, unit.start_date, unit.end_date),
                         ('active', date(2026, 7, 15), date(2027, 7, 14)))
        self.assertTrue(card.pdf_attachment_id)
        self.assertEqual(card.pdf_attachment_id.res_id, card.id)
        self.assertFalse(card.missing_requirements)
        with self.assertRaises(UserError):
            card.installation_date = date(2026, 8, 1)
        self.assertEqual(card.state, 'confirmed', 'confirmed card keeps its state')

    def test_12_invoice_criterion(self):
        """T17: invoice criterion uses the posted invoice date."""
        ac = self._product('AC Inv', warranty_start_criterion='invoice')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        self.assertEqual(card.state, 'draft')
        invoice = self._invoice(order)
        self.assertEqual(card.invoice_ids, invoice)
        self.assertEqual(card.state, 'ready')
        card.action_confirm_warranty()
        # Start Date Automation (D1): the actual posting time, not the invoice date.
        self.assertEqual(card.warranty_start_date,
                         card.company_id._warranty_local_date(invoice.warranty_posted_at))

    def test_13_custom_range(self):
        """T18: custom date range needs start and end; end not before start."""
        ac = self._product('AC Custom', warranty_start_criterion='custom')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        self.assertEqual(card.state, 'draft')
        card.write({'warranty_start_date': date(2026, 9, 1), 'warranty_end_date': date(2026, 8, 1)})
        self.assertEqual(card.state, 'draft')
        self.assertIn('must not be before', card.missing_requirements)
        card.warranty_end_date = date(2028, 8, 31)
        self.assertEqual(card.state, 'ready')
        card.action_confirm_warranty()
        self.assertEqual((card.warranty_start_date, card.warranty_end_date),
                         (date(2026, 9, 1), date(2028, 8, 31)))

    def test_14_payment_check(self):
        """T19: payment check required -> ready only after the invoice is paid."""
        policy = self.env['warranty.policy'].create({
            'name': 'Paid Policy', 'payment_check_required': True, 'warranty_duration': 12,
            'warranty_duration_unit': 'months', 'start_date_basis': 'delivery'})
        self.categ.warranty_policy_id = policy
        ac = self._product('AC Pay', warranty_start_criterion='delivery')
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self.assertEqual(card.policy_id, policy)
        self._deliver(order)
        self.assertEqual(card.state, 'draft')
        self.assertIn('Invoice payment', card.missing_requirements)
        self._invoice(order, pay=True)
        self.assertEqual(card.state, 'ready')

    def test_15_usage_basis(self):
        """T22: usage basis -> no end date, usage limit copied to the unit."""
        ac = self._product('AC Usage', warranty_basis='usage',
                           warranty_start_criterion='delivery')
        self.retail.write({'warranty_applicable': True, 'warranty_policy_id': self.env[
            'warranty.policy'].create({
                'name': 'Retail Usage Policy', 'warranty_duration': 12,
                'warranty_duration_unit': 'months', 'warranty_basis': 'usage',
                'start_date_basis': 'delivery', 'usage_limit': 2000,
                'usage_unit': 'operating_hours'}).id})
        order = self._order([(ac, 1)])
        card = order.warranty_card_ids
        self._deliver(order)
        self.assertEqual(card.state, 'ready')
        card.action_confirm_warranty()
        self.assertFalse(card.warranty_end_date)
        unit = card.unit_warranty_ids
        self.assertEqual((unit.usage_limit, unit.usage_unit, unit.state),
                         (2000, 'operating_hours', 'active'))

    def test_16_no_duplicate_on_reconfirm(self):
        """T24: re-confirming a Sales Order does not create duplicate unit numbers."""
        ac = self._product('AC Re')
        order = self._order([(ac, 1)])
        order._warranty_create_draft_cards('per_unit')
        self.assertEqual(len(order.warranty_card_ids), 1)
        self.assertEqual(len(order.warranty_unit_ids), 1)

    def test_17_settings_view(self):
        """T25: company warranty settings are exposed in Settings (the Warranty Scope Mode is
        not, BA decision 2026-10-28)."""
        self.env['res.config.settings'].create({
            'warranty_default_duration': 9})
        self.assertEqual(self.company.default_warranty_duration, 9)
        self.assertNotIn('warranty_scope_mode', self.env['res.config.settings']._fields)

    def test_18_settings_default_duration_required(self):
        """Without a Default Warranty Policy, Settings require a Default Warranty Duration > 0
        and a unit (form marker and save check)."""
        arch = etree.fromstring(self.env.ref(
            'warranty_management.res_config_settings_view_form_warranty').arch)
        for name in ('warranty_default_duration', 'warranty_default_duration_unit'):
            self.assertEqual(arch.xpath("//field[@name='%s']" % name)[0].get('required'),
                             'not warranty_default_policy_id', name)
        Settings = self.env['res.config.settings']
        with self.assertRaises(ValidationError):
            Settings.create({'warranty_default_duration': 0,
                             'warranty_default_duration_unit': 'months'}).execute()
        with self.assertRaises(ValidationError):
            Settings.create({'warranty_default_duration': 12,
                             'warranty_default_duration_unit': False}).execute()
        Settings.create({'warranty_default_duration': 12,
                         'warranty_default_duration_unit': 'months'}).execute()
        self.assertEqual((self.company.default_warranty_duration,
                          self.company.default_warranty_duration_unit), (12, 'months'))

    def test_30_grouping_wizard(self):
        """SO confirmation validates the configuration but creates no card; the Warranty
        Grouping wizard lists the products with policy / source, requires a mode, creates the
        Draft cards and units once; the old grouping fields are no longer used."""
        self.categ.card_grouping_mode = 'per_product'
        self.company.default_card_grouping_mode = False
        ac = self._product('AC Wizard')
        fan = self._product('Fan Wizard')
        order = self._order([(ac, 2), (fan, 1)], confirm=False)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertFalse(order.warranty_card_ids)
        self.assertFalse(order.warranty_unit_ids)
        self.assertTrue(order.warranty_grouping_pending)
        action = order.action_open_warranty_grouping()
        self.assertEqual((action['res_model'], action['target']),
                         ('warranty.grouping.wizard', 'new'))

        Wizard = self.env['warranty.grouping.wizard'].with_context(action['context'])
        form = Form(Wizard)
        self.assertFalse(form.card_grouping_mode, 'no default mode')
        self.assertEqual(form.sale_order_id, order)
        with self.assertRaises(AssertionError):
            form.save()  # Card Grouping Mode is required
        form.card_grouping_mode = 'per_so'
        wizard = form.save()
        self.assertEqual(
            [(line.product_id, line.quantity, line.policy_source, line.warranty_duration)
             for line in wizard.line_ids], [(ac, 2, 'product', 12), (fan, 1, 'product', 12)])
        wizard.action_confirm()
        # The selected mode is used (not the category's Per Product).
        card = order.warranty_card_ids
        self.assertEqual((len(card), card.state, card.card_grouping_mode),
                         (1, 'draft', 'per_so'))
        self.assertEqual(len(order.warranty_unit_ids), 3)
        self.assertFalse(order.warranty_grouping_pending)

        # No duplicates: a wizard opened before (or again) is refused.
        with self.assertRaises(UserError):
            Wizard.create({'card_grouping_mode': 'per_unit'}).action_confirm()
        with self.assertRaises(UserError):
            order.action_open_warranty_grouping()
        self.assertEqual(len(order.warranty_card_ids), 1)

    def test_31_grouping_wizard_per_delivery_and_late_grouping(self):
        """Per Delivery is refused when a product has no outgoing delivery; grouping after
        the delivery was validated still allocates the delivery and serials."""
        service = self.env['product.product'].create({
            'name': 'Service Wizard', 'type': 'service', 'categ_id': self.categ.id,
            'warranty_applicable': True, 'default_warranty_period': 12,
            'default_warranty_period_unit': 'months'})
        order = self._order([(service, 1)], confirm=False)
        order.action_confirm()
        wizard = self.env['warranty.grouping.wizard'].with_context(
            default_sale_order_id=order.id).create({'card_grouping_mode': 'per_delivery'})
        with self.assertRaises(UserError) as error:
            wizard.action_confirm()
        self.assertRegex(str(error.exception), 'Per Delivery.*Service Wizard')
        self.assertFalse(order.warranty_card_ids)

        ac = self._product('AC Late Grouping', tracking='serial',
                           warranty_start_criterion='delivery')
        order = self._order([(ac, 2)], confirm=False)
        order.action_confirm()
        picking = self._deliver(order)
        self.assertFalse(order.warranty_card_ids)
        confirm_wizard = self.env['warranty.grouping.wizard'].with_context(
            default_sale_order_id=order.id).create({'card_grouping_mode': 'per_delivery'})
        confirm_wizard.action_confirm()
        card = order.warranty_card_ids
        self.assertEqual((card.card_grouping_mode, card.delivery_ids), ('per_delivery', picking))
        self.assertTrue(all(unit.stock_move_line_id and len(unit.serial_ids) == 1
                            for unit in card.unit_warranty_ids))
        self.assertEqual(card.state, 'ready')

    def test_32_grouping_fields_hidden(self):
        """The company / policy / category grouping fields are kept but hidden."""
        settings = etree.fromstring(self.env.ref(
            'warranty_management.res_config_settings_view_form_warranty').arch)
        self.assertEqual(settings.xpath(
            "//setting[@id='warranty_default_card_grouping']")[0].get('invisible'), '1')
        for xmlid in ('warranty_management.warranty_policy_view_form',
                      'warranty_management.product_category_form_view_warranty'):
            arch = etree.fromstring(self.env.ref(xmlid).arch)
            self.assertEqual(
                arch.xpath("//field[@name='card_grouping_mode']")[0].get('invisible'), '1',
                xmlid)
        self.assertIn('default_card_grouping_mode', self.env['res.company']._fields)

    def test_33_policy_usage_unit_visibility(self):
        """Policy form: Usage Unit and Usage Alert % only visible for Warranty Basis = Usage."""
        form = Form(self.env['warranty.policy'])
        form.name = 'Usage Visibility Policy'
        for basis, hidden in (('period', True), ('usage', False), (False, True)):
            form.warranty_basis = basis
            for name in ('usage_unit', 'usage_alert_percentage'):
                self.assertEqual(bool(form._get_modifier(name, 'invisible')), hidden,
                                 (name, basis))
