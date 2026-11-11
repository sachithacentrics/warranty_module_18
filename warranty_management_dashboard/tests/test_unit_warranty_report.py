from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.addons.warranty_management.tests.common import confirm_and_group

from .report_common import _filter_domain


@tagged('post_install', '-at_install', 'warranty_dashboard')
class TestUnitWarrantyReport(TransactionCase):
    """Unit Warranty Number Report and the card events of the Warranty History Report:
    one multi-product card with Kit (Indoor / Outdoor) and serial-tracked units."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'warranty_scope_mode': 'warranty_only',
            'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'delivery',
            'default_warranty_duration': 12,
            'default_warranty_duration_unit': 'months',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Report Customer'})
        cls.stock = cls.env.ref('stock.stock_location_stock')
        cls.indoor = cls._serial_product('Report Indoor Unit', 'RIN')
        cls.outdoor = cls._serial_product('Report Outdoor Unit', 'ROUT')
        cls.ac = cls._serial_product('Report Window AC', 'RAC', warranty=True)
        cls.kit = cls.env['product.product'].create({
            'name': 'Report Split AC Kit', 'type': 'consu', 'warranty_applicable': True,
            'invoice_policy': 'order'})
        cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.kit.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1,
            'bom_line_ids': [
                (0, 0, {'product_id': cls.indoor.id, 'product_qty': 1,
                        'warranty_component_role': 'indoor'}),
                (0, 0, {'product_id': cls.outdoor.id, 'product_qty': 1,
                        'warranty_component_role': 'outdoor'}),
            ]})
        cls.other_company = cls.env['res.company'].create({'name': 'Report Other Company'})
        cls.foreign_user = cls.env['res.users'].create({
            'name': 'Report Foreign User', 'login': 'report_foreign_user',
            'company_id': cls.other_company.id, 'company_ids': [(6, 0, cls.other_company.ids)],
            'groups_id': [(6, 0, cls.env.ref('base.group_user').ids)]})
        cls.internal_user = cls.env['res.users'].create({
            'name': 'Report Internal User', 'login': 'report_internal_user',
            'groups_id': [(6, 0, cls.env.ref('base.group_user').ids)]})

    @classmethod
    def _serial_product(cls, name, prefix, warranty=False):
        vals = {'name': name, 'type': 'consu', 'is_storable': True, 'tracking': 'serial'}
        if warranty:
            vals.update(warranty_applicable=True, invoice_policy='order')
        product = cls.env['product.product'].create(vals)
        for index in range(1, 4):
            lot = cls.env['stock.lot'].create({'name': '%s-%02d' % (prefix, index),
                                               'product_id': product.id})
            cls.env['stock.quant']._update_available_quantity(product, cls.stock, 1, lot_id=lot)
        return product

    def _card(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.kit.id, 'product_uom_qty': 2}),
                           (0, 0, {'product_id': self.ac.id, 'product_uom_qty': 2})]})
        confirm_and_group(order)
        picking = order.picking_ids
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        card = order.warranty_card_ids
        self.assertEqual(len(card), 1)
        self.assertEqual(card.state, 'ready', card.missing_requirements)
        card.action_confirm_warranty()
        return order, picking, card

    def _snapshot(self, card):
        units = card.unit_warranty_ids
        return (card.state, card.write_date, card.partner_id, len(card.message_ids),
                [(u.id, u.state, u.write_date, u.serial_ids.ids, u.start_date, u.end_date)
                 for u in units.sorted('id')])

    def test_01_unit_report(self):
        """Unit Warranty Number (Cards > Warranty Unit Numbers): one row per unit with card, customer, product,
        delivery, serials (Kit Indoor / Outdoor kept), dates and status; report filters; group by;
        read-only list; the unit opens with its card."""
        order, picking, card = self._card()
        Unit = self.env['warranty.unit']
        action = self.env.ref('warranty_management.action_warranty_unit')
        # the Reports menu was removed on request; the Cards menu still opens the action
        self.assertFalse(self.env.ref('warranty_management_dashboard.menu_report_unit_warranty',
                                      raise_if_not_found=False))
        self.assertEqual(self.env.ref('warranty_management.menu_warranty_unit').action, action)
        self.assertIn('form', action.view_mode)
        before = self._snapshot(card)

        units = Unit.search([('warranty_card_id', '=', card.id)])
        self.assertEqual(units, card.unit_warranty_ids)
        self.assertEqual(len(units), 4)
        self.assertEqual(len(set(units.mapped('name'))), 4)
        for unit in units:
            self.assertEqual((unit.partner_id, unit.delivery_picking_id, unit.state),
                             (self.partner, picking, 'active'))
            self.assertTrue(unit.start_date and unit.end_date)
        kits = units.filtered(lambda unit: unit.product_id == self.kit)
        acs = units - kits
        self.assertEqual(len(kits), 2)
        for unit in kits:
            self.assertEqual(unit.serial_ids, unit.indoor_serial_id | unit.outdoor_serial_id)
            self.assertEqual(unit.indoor_serial_id.product_id, self.indoor)
            self.assertEqual(unit.outdoor_serial_id.product_id, self.outdoor)
        self.assertEqual(len(acs.serial_ids), 2)

        # Report filters: card, warranty number, product, delivery, serial, status
        domain = [('warranty_card_id', '=', card.id)]
        self.assertEqual(Unit.search([('warranty_card_id', 'ilike', card.name)]), units)
        self.assertEqual(Unit.search([('name', '=', kits[0].name)]), kits[0])
        self.assertEqual(Unit.search(domain + [('product_id', '=', self.ac.id)]), acs)
        self.assertEqual(Unit.search([('delivery_picking_id', '=', picking.id)]), units)
        self.assertEqual(Unit.search([('serial_ids', 'ilike', acs[0].serial_ids.name)]), acs[0])
        self.assertEqual(Unit.search([('indoor_serial_id', 'ilike', kits[1].indoor_serial_id.name)]),
                         kits[1])
        self.assertEqual(Unit.search(domain + _filter_domain(Unit, 'filter_active')), units)
        self.assertFalse(Unit.search(domain + _filter_domain(Unit, 'filter_draft')))
        self.assertEqual(Unit.search([('partner_id', '=', self.partner.id)]), units)
        groups = Unit.read_group(domain, ['product_id'], ['product_id'])
        self.assertEqual(sorted(group['product_id_count'] for group in groups), [2, 2])
        groups = Unit.read_group(domain, ['partner_id'], ['partner_id'])
        self.assertEqual([group['partner_id_count'] for group in groups], [4])

        arch = etree.fromstring(Unit.get_view(view_type='list')['arch'])
        self.assertEqual((arch.get('create'), arch.get('delete')), ('false', 'false'))
        columns = arch.xpath('//field/@name')
        for name in ('name', 'warranty_card_id', 'partner_id', 'product_id', 'delivery_picking_id',
                     'serial_ids', 'indoor_serial_id', 'outdoor_serial_id', 'start_date',
                     'end_date', 'state'):
            self.assertIn(name, columns)
        form = Unit.get_view(view_type='form')['arch']
        self.assertIn('name="warranty_card_id"', form)
        self.assertIn('action_view_warranty_history', form)

        # company isolation; reading the report changes nothing
        self.assertFalse(Unit.with_user(self.foreign_user).search(domain))
        self.assertEqual(self._snapshot(card), before)
        self.assertEqual(order.warranty_card_ids, card)

    def test_02_history_card_events(self):
        """Reports > Warranty History: card, unit, activation and invoice posting events of
        the card, newest first, opening their records; other companies see nothing; reading
        changes nothing."""
        order, picking, card = self._card()
        invoice = order._create_invoices()
        invoice.action_post()
        self.env.flush_all()  # the SQL view reads the database (each request commits in the UI)
        History = self.env['warranty.history']
        action = self.env.ref('warranty_management.action_warranty_history')
        menu = self.env.ref('warranty_management_dashboard.menu_report_warranty_history')
        self.assertEqual((menu.action, menu.parent_id),
                         (action, self.env.ref('warranty_management_mrf.menu_warranty_reports_quality')))
        self.assertFalse(self.env.ref('warranty_management.menu_warranty_history',
                                      raise_if_not_found=False), 'no second history menu')
        before = self._snapshot(card)

        rows = History.search([('card_id', '=', card.id)])
        events = {(row.entity, row.event_type) for row in rows}
        self.assertTrue({('card', 'Card created'), ('date', 'Activation'),
                         ('invoice', 'Customer invoice created'),
                         ('invoice', 'Customer invoice posted')} <= events, events)
        unit_rows = rows.filtered(lambda row: row.entity == 'unit')
        self.assertEqual(unit_rows.unit_id, card.unit_warranty_ids)
        self.assertEqual(set(unit_rows.mapped('reference')), set(card.unit_warranty_ids.mapped('name')))
        dates = rows.mapped('event_date')
        self.assertEqual(dates, sorted(dates, reverse=True), 'newest first')
        posted = rows.filtered(lambda row: row.event_type == 'Customer invoice posted')
        self.assertEqual(set(posted.mapped('reference')), {invoice.name})
        self.assertEqual(posted[0].user_id, self.env.user)

        # Report filters: entity, event type, user, date
        self.assertEqual(History.search([('card_id', '=', card.id), ('entity', '=', 'unit')]),
                         unit_rows)
        created = History.search([('card_id', '=', card.id)]
                                 + _filter_domain(History, 'filter_created'))
        self.assertTrue(created and all(' created' in r.event_type for r in created))
        self.assertEqual(History.search([('card_id', '=', card.id),
                                         ('user_id', '=', self.env.uid)]), rows)

        # navigation
        open_unit = unit_rows[0].action_open_source()
        self.assertEqual((open_unit['res_model'], open_unit['res_id']),
                         ('warranty.unit', unit_rows[0].unit_id.id))
        open_invoice = posted[0].action_open_source()
        self.assertEqual((open_invoice['res_model'], open_invoice['res_id']),
                         ('account.move', invoice.id))
        card_row = rows.filtered(lambda row: row.entity == 'card')
        self.assertEqual(card_row.action_open_source()['res_id'], card.id)
        list_arch = History.get_view(view_type='list')['arch']
        self.assertIn('action_open_source', list_arch)

        # access: other company none; internal users read card events, no journal entries
        self.assertFalse(History.with_user(self.foreign_user).search([('card_id', '=', card.id)]))
        internal = History.with_user(self.internal_user).search([('card_id', '=', card.id)])
        self.assertEqual(internal, rows.filtered(lambda r: r.entity not in ('cost', 'accounting')))
        self.assertEqual(self._snapshot(card), before)
        self.assertEqual(invoice.state, 'posted')
