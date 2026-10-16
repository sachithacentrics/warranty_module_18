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

    def _warranty_product_policy(self):
        """Product-level warranty policy of this line for the order: the product's Product /
        Model / Brand policy, else the Customer Type policy of the order's pricelist, else the
        Default Warranty Policy inherited from its category. Returns (policy, assigned directly
        to the product, inherited from the category)."""
        self.ensure_one()
        order = self.order_id
        template = self.product_id.product_tmpl_id
        company = order.company_id
        Policy = self.env['warranty.policy']
        product_policy = Policy._get_product_policy(template, company, include_category=False)
        # A policy the product is assigned to directly (any Applies To) is a Product policy.
        direct_policy = template in product_policy.product_tmpl_ids
        if not direct_policy and (
                not product_policy or product_policy.applies_to == 'customer_type'):
            # Customer Type policy of the order's pricelist; no product link to the pricelist
            # (mapping line or price rule) is required.
            product_policy = Policy._get_customer_type_policy_map(
                company, order.pricelist_id.ids).get(order.pricelist_id.id, Policy)
        # Lowest priority: the active Default Warranty Policy of the category (order company
        # or shared), inherited by the product.
        category_policy = template.categ_id.warranty_policy_id
        inherited = bool(not product_policy and category_policy.active
                         and category_policy.company_id in (company, self.env['res.company']))
        if inherited:
            product_policy = category_policy
        return product_policy, direct_policy, inherited

    def _warranty_pricelist_rule(self):
        """Product + Pricelist mapping line of this line: the order's pricelist, valid on the
        order date, highest priority."""
        self.ensure_one()
        order = self.order_id
        order_date = order.date_order.date()
        return self.product_id.product_tmpl_id.warranty_pricelist_rule_ids.filtered(
            lambda r: r.pricelist_id == order.pricelist_id
            and (not r.effective_from or r.effective_from <= order_date)
            and (not r.effective_to or r.effective_to >= order_date)
        ).sorted(lambda r: (r.priority, r.id))[:1]

    def _warranty_resolve_rule(self):
        """Resolve the applicable warranty configuration. The first valid rule wins:
        Product + Pricelist rule > Product warranty policy (Product > Model > Brand policy)
        > Product default > Product category > Company fallback (approved change to SRS §2.2, see
        doc/warranty_policy_resolution.md).
        Values the winning rule does not hold fall back product > category > policy > company."""
        self.ensure_one()
        order = self.order_id
        template = self.product_id.product_tmpl_id
        category = template.categ_id
        company = order.company_id

        product_policy, direct_policy, category_policy = self._warranty_product_policy()
        policy = product_policy or category.warranty_policy_id \
            or company.default_warranty_policy_id
        rule = self._warranty_pricelist_rule()

        values = {'usage_limit': 0.0, 'usage_unit': False}
        if rule:
            values.update({
                'policy_source': 'pricelist_rule',
                'warranty_duration': rule.warranty_period,
                'warranty_duration_unit': rule.warranty_period_unit,
                'usage_limit': rule.usage_limit,
                'usage_unit': rule.usage_unit,
            })
        elif product_policy.warranty_duration > 0:
            values.update({
                'policy_source': 'category' if category_policy
                else 'product_policy' if direct_policy else {
                    'model': 'model_policy', 'brand': 'brand_policy',
                    'customer_type': 'customer_type_policy'}.get(
                    product_policy.applies_to, 'product_policy'),
                'warranty_duration': product_policy.warranty_duration,
                'warranty_duration_unit': product_policy.warranty_duration_unit,
            })
        elif template.default_warranty_period > 0:
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
        elif company.default_warranty_policy_id.warranty_duration > 0:
            company_policy = company.default_warranty_policy_id
            values.update({
                'policy_source': 'company',
                'warranty_duration': company_policy.warranty_duration,
                'warranty_duration_unit': company_policy.warranty_duration_unit,
            })
        else:
            raise UserError(_(
                "Configuration Required: no warranty rule was found for product "
                "\"%(product)s\" on %(order)s. Configure a Product + Pricelist rule, a product "
                "default rule, a product category rule or the company fallback rule.",
                product=self.product_id.display_name, order=order.name))

        # Free service values, resolved separately from the duration (approved priority):
        # Product + Pricelist line > product's mapped policy, else product > category's
        # policy, else category > applicable policy > Company Default Warranty Policy >
        # Company Warranty Settings; for each value the first level with a value wins
        # (0 / empty is not a value). Policies have no frequency: their Free Service Period
        # is used at card confirmation.
        levels = self.env['warranty.card']._get_free_service_levels(
            template, company, product_policy, policy)
        values['free_service_count'] = next((count for count in [rule.free_service_count] + [
            level.free_service_count if level._name == 'warranty.policy'
            else level.default_free_service_count for level in levels] + [
            company.default_free_service_count] if count > 0), 0)
        values['free_service_frequency'], values['free_service_frequency_unit'] = next((
            (level.free_service_frequency, level.free_service_frequency_unit)
            for level in [rule] + levels if level._name != 'warranty.policy'
            and level.free_service_frequency > 0 and level.free_service_frequency_unit),
            (0, False))
        values.update({
            'policy': policy,
            'usage_unit': values['usage_unit'] or policy.usage_unit,
            'start_criterion': (template.warranty_start_criterion
                                or category.warranty_start_criterion
                                or policy.start_date_basis
                                or company.default_start_criterion),
            'warranty_basis': (template.warranty_basis
                               or category.warranty_basis
                               or policy.warranty_basis
                               or company.default_warranty_basis),
        })
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
