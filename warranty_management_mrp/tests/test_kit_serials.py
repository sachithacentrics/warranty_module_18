from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged

from odoo.addons.warranty_management.tests.common import confirm_and_group


@tagged('post_install', '-at_install', 'warranty_kit')
class TestWarrantyKitSerials(TransactionCase):
    """Indoor / Outdoor serial numbers of Kit products (approved K1-K4)."""

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
        cls.partner = cls.env['res.partner'].create({'name': 'Kit Customer'})
        cls.stock = cls.env.ref('stock.stock_location_stock')
        cls.categ = cls.env['product.category'].create({'name': 'Kit Test ACs'})
        cls.indoor = cls._component('Kit Indoor Unit', 'IN')
        cls.outdoor = cls._component('Kit Outdoor Unit', 'OUT')
        cls.pipe = cls.env['product.product'].create({
            'name': 'Kit Copper Pipe', 'type': 'consu', 'is_storable': True})
        cls.env['stock.quant']._update_available_quantity(cls.pipe, cls.stock, 50)
        cls.kit = cls.env['product.product'].create({
            'name': 'Split AC Kit', 'type': 'consu', 'categ_id': cls.categ.id,
            'warranty_applicable': True, 'invoice_policy': 'order'})
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.kit.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1,
            'bom_line_ids': [
                (0, 0, {'product_id': cls.indoor.id, 'product_qty': 1,
                        'warranty_component_role': 'indoor'}),
                (0, 0, {'product_id': cls.outdoor.id, 'product_qty': 1,
                        'warranty_component_role': 'outdoor'}),
                (0, 0, {'product_id': cls.pipe.id, 'product_qty': 3}),
            ]})

    @classmethod
    def _component(cls, name, prefix):
        product = cls.env['product.product'].create({
            'name': name, 'type': 'consu', 'is_storable': True, 'tracking': 'serial'})
        for index in range(1, 6):
            lot = cls.env['stock.lot'].create({
                'name': '%s-%02d' % (prefix, index), 'product_id': product.id})
            cls.env['stock.quant']._update_available_quantity(product, cls.stock, 1, lot_id=lot)
        return product

    def _order(self, qty, product=None, grouping='per_so'):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': (product or self.kit).id,
                                   'product_uom_qty': qty})]})
        confirm_and_group(order, grouping)
        return order

    def _deliver(self, order, keep=None):
        """Validate the open delivery; keep {product: n} delivers only n move lines of that
        product (backorder for the rest)."""
        picking = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))[:1]
        picking.action_assign()
        for move in picking.move_ids:
            if keep and move.product_id in keep:
                lines = move.move_line_ids.sorted('id')
                lines[keep[move.product_id]:].unlink()
            move.picked = True
        res = picking.button_validate()
        if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
            Form(self.env[res['res_model']].with_context(res['context'])).save().process()
        return picking

    def _delivered_lots(self, picking, product):
        return picking.move_ids.filtered(
            lambda m: m.product_id == product).move_line_ids.sorted('id').lot_id

    # ------------------------------------------------------------------ allocation
    def test_01_single_kit(self):
        """Kit x1: Indoor / Outdoor serials of the delivered components on the unit, in its
        Serial(s) and on the single-unit card; the card can be confirmed."""
        order = self._order(1)
        card = order.warranty_card_ids
        self.assertIn('Indoor Unit serial number', card.missing_requirements)
        picking = self._deliver(order)
        unit = card.unit_warranty_ids
        indoor = self._delivered_lots(picking, self.indoor)
        outdoor = self._delivered_lots(picking, self.outdoor)
        self.assertEqual((unit.indoor_serial_id, unit.outdoor_serial_id), (indoor, outdoor))
        self.assertEqual(unit.serial_ids, indoor | outdoor)
        self.assertTrue(unit.stock_move_line_id)
        self.assertFalse(unit.kit_serials_corrected)
        self.assertEqual((card.indoor_serial_id, card.outdoor_serial_id), (indoor, outdoor))
        self.assertEqual(card.state, 'ready', card.missing_requirements)
        card.action_confirm_warranty()
        self.assertEqual(card.state, 'confirmed')
        self.assertEqual(self.env['stock.lot'].search_count([
            ('product_id', 'in', (self.indoor | self.outdoor).ids)]), 10, 'no serial created')

    def test_02_multiple_kits_paired_in_delivery_order(self):
        """Kit x3: the k-th delivered Indoor and Outdoor serials go to unit k; each serial on
        one unit only; card-level fields stay empty (several units)."""
        order = self._order(3)
        card = order.warranty_card_ids
        picking = self._deliver(order)
        units = card.unit_warranty_ids.sorted('unit_number')
        self.assertEqual(units.indoor_serial_id, self._delivered_lots(picking, self.indoor))
        self.assertEqual(units.outdoor_serial_id, self._delivered_lots(picking, self.outdoor))
        self.assertEqual([len(u.indoor_serial_id | u.outdoor_serial_id) for u in units], [2, 2, 2])
        self.assertFalse(card.indoor_serial_id or card.outdoor_serial_id)
        self.assertEqual(card.state, 'ready', card.missing_requirements)

    def test_03_partial_delivery(self):
        """Partial delivery: missing Outdoor serials block the confirmation; the backorder
        fills the remaining units without changing the allocated ones."""
        order = self._order(3)
        card = order.warranty_card_ids
        first = self._deliver(order, keep={self.outdoor: 1})
        units = card.unit_warranty_ids.sorted('unit_number')
        self.assertEqual(len(units.indoor_serial_id), 3)
        self.assertEqual(units[0].outdoor_serial_id, self._delivered_lots(first, self.outdoor))
        self.assertFalse(units[1].outdoor_serial_id or units[2].outdoor_serial_id)
        self.assertEqual(card.state, 'draft')
        self.assertIn('Outdoor Unit serial number for unit', card.missing_requirements)
        with self.assertRaises(UserError):
            card.action_confirm_warranty()

        allocated = units.mapped(lambda u: (u.indoor_serial_id, u.outdoor_serial_id))
        backorder = self._deliver(order)
        self.assertEqual(units[0].mapped(lambda u: (u.indoor_serial_id, u.outdoor_serial_id)),
                         allocated[:1], 'allocated pairs unchanged')
        self.assertEqual((units[1] | units[2]).outdoor_serial_id,
                         self._delivered_lots(backorder, self.outdoor))
        self.assertEqual(card.state, 'ready', card.missing_requirements)
        self.assertEqual(len(card.delivery_ids), 2)

    def test_04_manual_correction(self):
        """K4: swap two Indoor serials in one save; only delivered serials of the same line
        and role; no duplicates; corrected units are never changed by later deliveries;
        locked after confirmation."""
        order = self._order(2)
        card = order.warranty_card_ids
        self._deliver(order, keep={self.outdoor: 1})
        first, second = card.unit_warranty_ids.sorted('unit_number')
        a, b = first.indoor_serial_id, second.indoor_serial_id
        self.assertEqual(first.allowed_indoor_serial_ids, a)
        card.write({'unit_warranty_ids': [
            (1, first.id, {'indoor_serial_id': b.id}),
            (1, second.id, {'indoor_serial_id': a.id})]})
        self.assertEqual((first.indoor_serial_id, second.indoor_serial_id), (b, a))
        self.assertTrue(first.kit_serials_corrected and second.kit_serials_corrected)
        self.assertEqual(first.serial_ids, b | first.outdoor_serial_id)

        not_delivered = self.env['stock.lot'].search([
            ('product_id', '=', self.indoor.id), ('id', 'not in', (a | b).ids)], limit=1)
        with self.assertRaises(ValidationError):
            first.indoor_serial_id = not_delivered
        with self.assertRaises(ValidationError):
            first.outdoor_serial_id = a  # Indoor serial as Outdoor
        with self.assertRaises(ValidationError):
            first.indoor_serial_id = a  # already on the second unit

        # The corrected second unit keeps its empty Outdoor serial after the backorder.
        self._deliver(order)
        self.assertFalse(second.outdoor_serial_id)
        self.assertIn('Outdoor Unit serial number for unit %s' % second.name,
                      card.missing_requirements)
        second.outdoor_serial_id = second.allowed_outdoor_serial_ids
        self.assertEqual(card.state, 'ready', card.missing_requirements)
        card.action_confirm_warranty()
        with self.assertRaises(UserError):
            first.indoor_serial_id = a

    def test_05_single_unit_card_fields(self):
        """Single-unit card: card fields follow the unit (also after a correction) unless the
        user entered another value on the card; multi-unit cards (per unit grouping) get
        their own unit's serials."""
        order = self._order(2, grouping='per_unit')
        cards = order.warranty_card_ids
        self.assertEqual(len(cards), 2)
        self._deliver(order)
        for card in cards:
            unit = card.unit_warranty_ids
            self.assertEqual((card.indoor_serial_id, card.outdoor_serial_id),
                             (unit.indoor_serial_id, unit.outdoor_serial_id))
        first, second = cards.sorted('id')
        outdoor_a = first.unit_warranty_ids.outdoor_serial_id
        outdoor_b = second.unit_warranty_ids.outdoor_serial_id
        first.unit_warranty_ids.outdoor_serial_id = False
        second.unit_warranty_ids.outdoor_serial_id = outdoor_a
        first.unit_warranty_ids.outdoor_serial_id = outdoor_b
        self.assertEqual((first.outdoor_serial_id, second.outdoor_serial_id),
                         (outdoor_b, outdoor_a))
        # A value entered by the user on the card is kept.
        manual = self.env['stock.lot'].create({'name': 'CARD-MANUAL', 'product_id': self.indoor.id})
        first.indoor_serial_id = manual
        indoor_b = second.unit_warranty_ids.indoor_serial_id
        indoor_a = first.unit_warranty_ids.indoor_serial_id
        second.unit_warranty_ids.indoor_serial_id = False
        first.unit_warranty_ids.indoor_serial_id = indoor_b
        self.assertEqual(first.indoor_serial_id, manual)
        self.assertTrue(indoor_a)

    # ------------------------------------------------------------------ other products
    def test_06_kit_without_roles_and_non_kit(self):
        """Kit without roles: allocated once from its first component (no overwrite, no
        role serials, no extra requirement). Non-kit serial product: unchanged handling."""
        self.bom.bom_line_ids.write({'warranty_component_role': 'none'})
        order = self._order(2)
        card = order.warranty_card_ids
        picking = self._deliver(order)
        units = card.unit_warranty_ids.sorted('unit_number')
        self.assertEqual(units.stock_move_line_id.product_id, self.indoor)
        self.assertEqual(units.serial_ids, self._delivered_lots(picking, self.indoor))
        self.assertFalse(units.indoor_serial_id | units.outdoor_serial_id)
        self.assertEqual(card.state, 'ready', card.missing_requirements)

        serial_ac = self.env['product.product'].create({
            'name': 'Window AC', 'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'warranty_applicable': True, 'invoice_policy': 'order'})
        for index in range(2):
            lot = self.env['stock.lot'].create({'name': 'WIN-%s' % index,
                                                'product_id': serial_ac.id})
            self.env['stock.quant']._update_available_quantity(serial_ac, self.stock, 1, lot_id=lot)
        order = self._order(2, product=serial_ac)
        picking = self._deliver(order)
        units = order.warranty_card_ids.unit_warranty_ids.sorted('unit_number')
        self.assertEqual(units.serial_ids, picking.move_line_ids.sorted('id').lot_id)
        self.assertEqual([len(u.serial_ids) for u in units], [1, 1])
        self.assertFalse(units.indoor_serial_id | units.outdoor_serial_id)

    # ------------------------------------------------------------------ BoM rules
    def test_07_bom_role_rules(self):
        """K2 rules: one Indoor / Outdoor line per kit, Kit BoMs only, serial-tracked, 1 per
        kit unit; the role column is shown for Kits only."""
        with self.assertRaises(ValidationError):
            self.bom.bom_line_ids.filtered(
                lambda l: l.product_id == self.outdoor).warranty_component_role = 'indoor'
        with self.assertRaises(ValidationError):
            self.bom.bom_line_ids.filtered(
                lambda l: l.product_id == self.pipe).warranty_component_role = 'outdoor'
        with self.assertRaises(ValidationError):
            self.bom.bom_line_ids.filtered(
                lambda l: l.product_id == self.indoor).product_qty = 2
        with self.assertRaises(ValidationError):
            self.bom.type = 'normal'
        self.assertEqual(self.bom._warranty_role_lines()['indoor'].product_id, self.indoor)

        from lxml import etree
        arch = etree.fromstring(self.env.ref(
            'warranty_management_mrp.mrp_bom_form_view_warranty_role').arch)
        node = arch.xpath("//field[@name='warranty_component_role']")[0]
        self.assertEqual(node.get('column_invisible'), "parent.type != 'phantom'")

    # ------------------------------------------------------------------ serial field visibility
    def _shown(self, record):
        return record.warranty_show_indoor_serial, record.warranty_show_outdoor_serial

    def _normal_product(self):
        product = self.env['product.product'].create({
            'name': 'Normal AC', 'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'categ_id': self.categ.id, 'warranty_applicable': True, 'invoice_policy': 'order'})
        lot = self.env['stock.lot'].create({'name': 'NORMAL-01', 'product_id': product.id})
        self.env['stock.quant']._update_available_quantity(product, self.stock, 1, lot_id=lot)
        return product

    def _kit_without(self, *roles):
        kit = self.env['product.product'].create({
            'name': 'Other Kit', 'type': 'consu', 'categ_id': self.categ.id,
            'warranty_applicable': True, 'invoice_policy': 'order'})
        self.env['mrp.bom'].create({
            'product_tmpl_id': kit.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1,
            'bom_line_ids': [(0, 0, {'product_id': self.pipe.id, 'product_qty': 1})] + [
                (0, 0, {'product_id': {'indoor': self.indoor, 'outdoor': self.outdoor}[role].id,
                        'product_qty': 1, 'warranty_component_role': role}) for role in roles]})
        return kit

    def test_30_kit_shows_both_serials(self):
        card = self._order(1).warranty_card_ids
        self.assertEqual(self._shown(card), (True, True))
        self.assertEqual(self._shown(card.unit_warranty_ids), (True, True))

    def test_31_normal_product_hides_them_and_keeps_its_serial(self):
        product = self._normal_product()
        order = self._order(1, product)
        picking = order.picking_ids
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        card = order.warranty_card_ids
        self.assertEqual(self._shown(card), (False, False))
        self.assertEqual(self._shown(card.unit_warranty_ids), (False, False))
        self.assertEqual(card.unit_warranty_ids.serial_ids.name, 'NORMAL-01')

    def test_32_kit_without_roles_hides_them(self):
        card = self._order(1, self._kit_without()).warranty_card_ids
        self.assertEqual(self._shown(card), (False, False))
        self.assertEqual(self._shown(card.unit_warranty_ids), (False, False))

    def test_33_kit_with_one_role_shows_only_that_one(self):
        card = self._order(1, self._kit_without('indoor')).warranty_card_ids
        self.assertEqual(self._shown(card), (True, False))
        self.assertEqual(self._shown(card.unit_warranty_ids), (True, False))

    def test_34_mixed_card_shows_columns_but_only_on_kit_rows(self):
        product = self._normal_product()
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.kit.id, 'product_uom_qty': 1}),
                           (0, 0, {'product_id': product.id, 'product_uom_qty': 1})]})
        confirm_and_group(order, 'per_so')
        card = order.warranty_card_ids
        self.assertEqual(self._shown(card), (True, True))
        kit_unit = card.unit_warranty_ids.filtered(lambda unit: unit.product_id == self.kit)
        self.assertEqual(self._shown(kit_unit), (True, True))
        self.assertEqual(self._shown(card.unit_warranty_ids - kit_unit), (False, False))

    def test_35_visibility_follows_the_product_in_the_form(self):
        form = Form(self.env['warranty.card'])
        form.product_id = self._normal_product()
        self.assertEqual((form.warranty_show_indoor_serial, form.warranty_show_outdoor_serial),
                         (False, False))
        form.product_id = self.kit
        self.assertEqual((form.warranty_show_indoor_serial, form.warranty_show_outdoor_serial),
                         (True, True))
        form.product_id = self._kit_without('outdoor')
        self.assertEqual((form.warranty_show_indoor_serial, form.warranty_show_outdoor_serial),
                         (False, True))

    def test_36_a_recorded_serial_stays_visible(self):
        lot = self.env['stock.lot'].search([('product_id', '=', self.indoor.id)], limit=1)
        card = self.env['warranty.card'].create({
            'partner_id': self.partner.id, 'product_id': self._normal_product().id,
            'indoor_serial_id': lot.id, 'company_id': self.company.id})
        self.assertEqual(self._shown(card), (True, False))
        self.assertEqual(card.indoor_serial_id, lot, 'data is not touched')

    def test_37_user_without_stock_rights_can_open_the_values(self):
        card = self._order(1).warranty_card_ids
        user = self.env['res.users'].create({
            'name': 'Plain', 'login': 'kit_plain', 'company_id': self.company.id,
            'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, self.env.ref('base.group_user').ids)]})
        self.assertEqual(self._shown(card.with_user(user)), (True, True))

    # ------------------------------------------------------------------ printed warranty card
    def _printed(self, card):
        report = self.env.ref('warranty_management.report_warranty_card')
        return str(self.env['ir.qweb']._render(report.id, {
            'docs': card, 'doc_ids': card.ids, 'doc_model': 'warranty.card',
            'company': self.company, 'res_company': self.company, 'user': self.env.user}))

    def test_40_printed_kit_card(self):
        order = self._order(1)
        self._deliver(order)
        card = order.warranty_card_ids
        unit = card.unit_warranty_ids
        html = self._printed(card)
        for text in ('WARRANTY CERTIFICATE', 'REGISTRATION COPY', 'CUSTOMER INFORMATION',
                     'Serial No ID', 'Serial No OD', card.name, unit.name, self.partner.name,
                     unit.indoor_serial_id.name, unit.outdoor_serial_id.name):
            self.assertIn(text, html)

    def test_41_printed_normal_card_and_blanks(self):
        order = self._order(1, self._normal_product())
        picking = order.picking_ids
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        card = order.warranty_card_ids
        html = self._printed(card)
        self.assertIn('NORMAL-01', html)
        self.assertNotIn('Serial No ID', html)
        self.assertNotIn('WARRANTY TERMS', html, 'no empty section without terms')
        self.company.warranty_card_terms = '<p>Company terms</p>'
        self.company.warranty_card_return_note = 'Return within 14 days'
        html = self._printed(card)
        self.assertIn('Company terms', html)
        self.assertIn('Return within 14 days', html)

    def test_42_one_sheet_per_unit_without_cancelled_units(self):
        card = self._order(2).warranty_card_ids
        self.assertEqual(len(card._warranty_card_print_units()), 2)
        first = card.unit_warranty_ids[0]
        first.sudo()._warranty_system_write({'state': 'cancelled'})
        self.assertEqual(card._warranty_card_print_units(), card.unit_warranty_ids - first)

    def test_43_dealer_is_not_the_system_user(self):
        card = self._order(1).warranty_card_ids
        card.sale_order_id.user_id = self.env.ref('base.user_root')
        unit = card.unit_warranty_ids
        self.assertFalse(card._warranty_card_print_values(unit)['dealer'])
        card.sale_order_id.user_id = self.env.ref('base.user_admin')
        self.assertEqual(card._warranty_card_print_values(unit)['dealer'],
                         self.env.ref('base.user_admin').name)

    def test_44_several_units_print_one_sheet_and_the_schedule(self):
        card = self._order(3).warranty_card_ids
        cancelled = card.unit_warranty_ids[0]
        cancelled.sudo()._warranty_system_write({'state': 'cancelled'})
        units = card._warranty_card_print_units()
        html = self._printed(card)
        self.assertEqual(html.count('WARRANTY CERTIFICATE'), 1, 'one sheet, not one per unit')
        self.assertIn('UNIT WARRANTY SCHEDULE', html)
        self.assertIn('See Unit Warranty Schedule', html)
        for unit in units:
            self.assertIn(unit.name, html)
        self.assertNotIn(cancelled.name, html)
        rows = card._warranty_card_print_schedule(units)
        self.assertEqual([row['number'] for row in rows], units.mapped('name'))
        self.assertEqual([row['product'] for row in rows], units.product_id.mapped('name') * 2)

    def test_45_one_unit_prints_without_schedule(self):
        card = self._order(1).warranty_card_ids
        html = self._printed(card)
        self.assertNotIn('UNIT WARRANTY SCHEDULE', html)
        self.assertIn(card.unit_warranty_ids.name, html)
