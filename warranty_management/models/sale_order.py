from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import float_round


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    warranty_card_ids = fields.One2many('warranty.card', 'sale_order_id', string='Warranty Cards')
    warranty_unit_ids = fields.One2many(
        'warranty.unit', 'sale_order_id', string='Unit Warranty Numbers')
    warranty_card_count = fields.Integer(
        string='Warranty Card Count', compute='_compute_warranty_counts')
    warranty_unit_count = fields.Integer(
        string='Unit Warranty Count', compute='_compute_warranty_counts')

    warranty_grouping_pending = fields.Boolean(
        string='Warranty Grouping Pending', compute='_compute_warranty_grouping_pending')

    @api.depends('warranty_card_ids', 'warranty_unit_ids')
    def _compute_warranty_counts(self):
        for order in self:
            order.warranty_card_count = len(order.warranty_card_ids)
            order.warranty_unit_count = len(order.warranty_unit_ids)

    @api.depends('state', 'order_line.product_id.warranty_applicable',
                 'order_line.product_uom_qty', 'order_line.warranty_unit_ids')
    def _compute_warranty_grouping_pending(self):
        for order in self:
            order.warranty_grouping_pending = (
                order.state == 'sale' and bool(order._warranty_pending_lines()))

    def action_view_warranty_history(self):
        self.ensure_one()
        cards = self.env['warranty.card'].search([('sale_order_id', '=', self.id)])
        return self.env['warranty.history']._warranty_open([('card_id', 'in', cards.ids)])

    def _warranty_pending_lines(self):
        """Eligible warranty lines without Unit Warranty Numbers (no warranty card yet)."""
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: not line.display_type
            and line.product_id.warranty_applicable
            and line.product_uom_qty > 0
            and not line.warranty_unit_ids)

    def _action_confirm(self):
        res = super()._action_confirm()

        for order in self:
            for line in order._warranty_pending_lines():
                line._warranty_resolve_rule()
        return res

    def action_open_warranty_grouping(self):
        self.ensure_one()
        if not self.warranty_grouping_pending:
            raise UserError(_("No warranty products are waiting for warranty grouping on %s.",
                              self.name))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Warranty Grouping"),
            'res_model': 'warranty.grouping.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sale_order_id': self.id},
        }

    def _warranty_create_draft_cards(self, grouping_mode):
        """From the Warranty Grouping wizard: re-resolve the rule of the pending lines, group
        them with the selected Card Grouping Mode (incompatible rule values still split the
        cards), create Draft Warranty Card(s) and one Unit Warranty Number per product
        quantity / unit, then allocate deliveries already validated."""
        for order in self:
            lines = order._warranty_pending_lines()
            if not lines:
                continue
            if grouping_mode == 'per_delivery':
                undelivered = lines.filtered(lambda line: not line._warranty_outgoing_pickings())
                if undelivered:
                    raise UserError(_(
                        "Per Delivery grouping is not possible on %(order)s: no outgoing "
                        "delivery for %(products)s. Select another Card Grouping Mode.",
                        order=order.name,
                        products=', '.join(undelivered.product_id.mapped('display_name'))))
            groups = defaultdict(list)
            for line in lines:
                values = dict(line._warranty_resolve_rule(), card_grouping_mode=grouping_mode)
                unit_count = line._warranty_unit_count()
                if values['card_grouping_mode'] == 'per_unit':
                    for unit_number in range(1, unit_count + 1):
                        groups[(line.id, unit_number)].append((values, line, [unit_number]))
                    continue
                key = order._warranty_grouping_key(values, line)
                groups[key].append((values, line, list(range(1, unit_count + 1))))

            for group in groups.values():
                values = group[0][0]
                group_lines = self.env['sale.order.line'].concat(*[item[1] for item in group])
                card = self.env['warranty.card'].create(
                    order._warranty_prepare_card_vals(values, group_lines))
                card._create_unit_warranty_numbers(
                    [(line, unit_number) for __, line, numbers in group for unit_number in numbers])

            order.picking_ids.filtered(
                lambda picking: picking.picking_type_code == 'outgoing'
                and picking.state == 'done'
            ).sorted('id')._warranty_allocate_delivery()

    def _warranty_grouping_key(self, values, line):
        """Lines share a card only when the grouping mode and the resolved rule values
        are compatible; incompatible lines are forced into separate cards."""
        self.ensure_one()
        key = (
            self.partner_id.id, self.company_id.id, self.pricelist_id.id,
            values['policy'].id, values['policy_source'], values['card_grouping_mode'],
            values['start_criterion'], values['warranty_basis'],
            values['warranty_duration'], values['warranty_duration_unit'],
            values['free_service_count'], values['free_service_frequency'],
            values['free_service_frequency_unit'], values['usage_limit'], values['usage_unit'],
        )
        mode = values['card_grouping_mode']
        if mode == 'per_product':
            key += (line.product_id.id,)
        elif mode == 'per_delivery':
            key += (line._warranty_outgoing_pickings()[:1].id,)
        return key

    def _warranty_prepare_card_vals(self, values, lines):
        self.ensure_one()
        products = lines.product_id
        return {
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'sale_order_id': self.id,
            'sale_order_line_ids': [Command.set(lines.ids)],
            'pricelist_id': self.pricelist_id.id,
            'product_id': products.id if len(products) == 1 else False,
            'policy_id': values['policy'].id,
            'policy_source': values['policy_source'],
            'card_grouping_mode': values['card_grouping_mode'],
            'warranty_basis': values['warranty_basis'],
            'start_criterion': values['start_criterion'],
            'warranty_duration': values['warranty_duration'],
            'warranty_duration_unit': values['warranty_duration_unit'],
            'free_services_allowed': values['free_service_count'],
            'free_service_frequency': values['free_service_frequency'],
            'free_service_frequency_unit': values['free_service_frequency_unit'],
            'usage_limit': values['usage_limit'],
            'usage_unit': values['usage_unit'],
        }

    def action_view_warranty_cards(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management.action_warranty_card')
        action['domain'] = [('sale_order_id', '=', self.id)]
        action['context'] = {'create': False}
        return action

    def action_view_warranty_units(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management.action_warranty_unit')
        action['domain'] = [('sale_order_id', '=', self.id)]
        action['context'] = {'create': False}
        return action


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    warranty_unit_ids = fields.One2many(
        'warranty.unit', 'sale_order_line_id', string='Unit Warranty Numbers')

    def _warranty_outgoing_pickings(self):
        self.ensure_one()
        return self.move_ids.filtered(
            lambda move: move.picking_code == 'outgoing' and move.state != 'cancel'
        ).picking_id

    def _warranty_unit_count(self):
        self.ensure_one()
        qty = self.product_uom._compute_quantity(self.product_uom_qty, self.product_id.uom_id)
        return int(float_round(qty, precision_digits=0))

    def _warranty_invoice_coverage(self):
        """Start Date Automation (D3, Q2): net quantities of this line invoiced by posted
        customer invoices, in posting order: [(invoice, quantity, posted_at, verification)].
        Credit notes reduce the invoice they reverse first, then the latest posted invoices
        (LIFO). Draft / cancelled moves and other lines (e.g. down payments) never count;
        fully credited invoices are left out."""
        self.ensure_one()
        uom = self.product_id.uom_id
        quantities = defaultdict(float)
        credits = defaultdict(float)
        for line in self.invoice_lines.filtered(
                lambda aml: aml.display_type == 'product' and aml.move_id.state == 'posted'):
            quantity = line.product_uom_id._compute_quantity(line.quantity, uom) \
                if line.product_uom_id else line.quantity
            if line.move_id.move_type == 'out_invoice':
                quantities[line.move_id] += quantity
            elif line.move_id.move_type == 'out_refund':
                credits[line.move_id] += quantity
        info = {invoice: invoice._warranty_posting_info() for invoice in quantities}
        # Unverifiable postings last: they never decide the order of verified ones.
        ordered = sorted(quantities, key=lambda invoice: (
            not info[invoice][0], info[invoice][0] or fields.Datetime.now(), invoice.id))
        for refund in sorted(credits, key=lambda move: move.id):
            remaining = credits[refund]
            targets = [refund.reversed_entry_id] if refund.reversed_entry_id in quantities else []
            targets += [invoice for invoice in reversed(ordered) if invoice not in targets]
            for invoice in targets:
                if float_round(remaining, precision_digits=6) <= 0:
                    break
                taken = min(remaining, max(quantities[invoice], 0.0))
                quantities[invoice] -= taken
                remaining -= taken
        return [(invoice, quantities[invoice], *info[invoice]) for invoice in ordered
                if float_round(quantities[invoice], precision_digits=6) > 0]

    def _warranty_policy_levels(self):
        """The four Warranty Policy levels of this line, in the approved strict priority:
        [(policy source, level label, selected policy)]."""
        self.ensure_one()
        order = self.order_id
        company = order.company_id
        template = self.product_id.product_tmpl_id
        pricelist = order.pricelist_id
        return [
            ('pricelist_policy', _("Pricelist %s", pricelist.name),
             pricelist.warranty_policy_id if pricelist.warranty_applicable
             else self.env['warranty.policy']),
            ('product_policy', _("Product"), template.with_company(company).warranty_policy_id),
            ('category_policy', _("Product Category"), template.categ_id.warranty_policy_id),
            ('company_policy', _("Company Default Warranty Policy"),
             company.default_warranty_policy_id),
        ]

    def _warranty_selected_policy(self):
        """(policy, policy source, level label) of the first level whose policy applies to the
        order company (active, of the order company or shared); empty policy when none."""
        self.ensure_one()
        company = self.order_id.company_id
        for source, level, policy in self._warranty_policy_levels():
            if policy and policy._is_applicable_for_company(company):
                return policy, source, level
        return self.env['warranty.policy'], False, False

    def _warranty_resolve_rule(self):
        """Resolve the applicable warranty configuration (approved strict priority, see
        doc/warranty_policy_resolution.md):
        P1 Sales Order pricelist policy (Warranty Applicable pricelist) > P2 Product policy >
        P3 Product Category policy > P4 Company Default Warranty Policy: every value comes from
        the selected policy (no values of lower levels); the Company Warranty Settings only
        fill its empty Warranty Basis / Start Criterion (and, at confirmation, Free Service
        Period / Schedule Method). A selected policy without a valid duration, or usage-based
        without usage limit / unit, is a configuration error.
        P5 (no policy at any level): the own values, product > category > Company Warranty
        Settings. The legacy Product + Pricelist Warranty Mapping lines are not used."""
        self.ensure_one()
        order = self.order_id
        company = order.company_id
        policy, source, level = self._warranty_selected_policy()
        if policy:
            warranty_basis = policy.warranty_basis or company.default_warranty_basis
            policy._check_warranty_configuration(level, self.product_id, order, warranty_basis)
            frequency = policy.free_service_frequency > 0 and policy.free_service_frequency_unit
            values = {
                'policy': policy,
                'policy_source': source,
                'warranty_duration': policy.warranty_duration,
                'warranty_duration_unit': policy.warranty_duration_unit,
                'free_service_count': policy.free_service_count,
                'free_service_frequency': policy.free_service_frequency if frequency else 0,
                'free_service_frequency_unit': frequency or False,
                'usage_limit': policy.usage_limit,
                'usage_unit': policy.usage_unit,
                'start_criterion': policy.start_date_basis or company.default_start_criterion,
                'warranty_basis': warranty_basis,
            }
        else:
            values = self._warranty_resolve_own_values()
        missing = [label for key, label in (
            ('start_criterion', _("Start Criterion")),
            ('warranty_basis', _("Warranty Basis")),
        ) if not values[key]]
        if missing:
            raise UserError(_(
                "Configuration Required: %(fields)s could not be resolved for product "
                "\"%(product)s\" on %(order)s.",
                fields=', '.join(missing), product=self.product_id.display_name,
                order=order.name))
        return values

    def _warranty_resolve_own_values(self):
        """P5 - no Warranty Policy at any level: the own warranty values. Duration: product
        default > category default > Company Warranty Settings; for each other value the first
        level with a value wins (0 / empty is not a value). No policy is linked to the card."""
        self.ensure_one()
        order = self.order_id
        template = self.product_id.product_tmpl_id
        category = template.categ_id
        company = order.company_id

        values = {'policy': self.env['warranty.policy'], 'usage_limit': 0.0, 'usage_unit': False}
        if template.default_warranty_period > 0:
            values.update({
                'policy_source': 'product',
                'warranty_duration': template.default_warranty_period,
                'warranty_duration_unit': template.default_warranty_period_unit,
            })
        elif category.default_warranty_period > 0:
            values.update({
                'policy_source': 'category',
                'warranty_duration': category.default_warranty_period,
                'warranty_duration_unit': category.default_warranty_period_unit,
            })
        elif company.default_warranty_duration > 0:
            values.update({
                'policy_source': 'company',
                'warranty_duration': company.default_warranty_duration,
                'warranty_duration_unit': company.default_warranty_duration_unit,
            })
        else:
            raise UserError(_(
                "Configuration Required: no warranty rule was found for product "
                "\"%(product)s\" on %(order)s. Select a Warranty Policy (pricelist, product, "
                "product category or company default) or configure the warranty values of the "
                "product, the product category or the company.",
                product=self.product_id.display_name, order=order.name))

        levels = self.env['warranty.card']._get_own_value_levels(template)
        values['free_service_count'] = next((count for count in [
            level.default_free_service_count for level in levels] + [
            company.default_free_service_count] if count > 0), 0)
        values['free_service_frequency'], values['free_service_frequency_unit'] = next((
            (level.free_service_frequency, level.free_service_frequency_unit)
            for level in levels
            if level.free_service_frequency > 0 and level.free_service_frequency_unit),
            (0, False))
        values.update({
            'start_criterion': (template.warranty_start_criterion
                                or category.warranty_start_criterion
                                or company.default_start_criterion),
            'warranty_basis': (template.warranty_basis
                               or category.warranty_basis
                               or company.default_warranty_basis),
        })
        return values
