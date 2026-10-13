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

    @api.depends('warranty_card_ids', 'warranty_unit_ids')
    def _compute_warranty_counts(self):
        for order in self:
            order.warranty_card_count = len(order.warranty_card_ids)
            order.warranty_unit_count = len(order.warranty_unit_ids)

    def _action_confirm(self):
        res = super()._action_confirm()
        self._warranty_create_draft_cards()
        return res

    def _warranty_create_draft_cards(self):
        """On SO confirmation: resolve rule, group lines, create Draft Warranty Card(s)
        and one Unit Warranty Number per product quantity / unit."""
        for order in self:
            lines = order.order_line.filtered(
                lambda line: not line.display_type
                and line.product_id.warranty_applicable
                and line.product_uom_qty > 0
                and not line.warranty_unit_ids)
            if not lines:
                continue
            groups = defaultdict(list)
            for line in lines:
                values = line._warranty_resolve_rule()
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
            pickings = line.move_ids.filtered(
                lambda move: move.picking_code == 'outgoing' and move.state != 'cancel'
            ).picking_id
            key += (pickings[:1].id,)
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

    def _warranty_unit_count(self):
        self.ensure_one()
        qty = self.product_uom._compute_quantity(self.product_uom_qty, self.product_id.uom_id)
        return int(float_round(qty, precision_digits=0))

    def _warranty_resolve_rule(self):
        """Resolve the applicable warranty configuration. The first valid rule wins:
        Product + Pricelist rule > Product default > Product category > Company fallback.
        Values the winning rule does not hold fall back product > category > policy > company."""
        self.ensure_one()
        order = self.order_id
        template = self.product_id.product_tmpl_id
        category = template.categ_id
        company = order.company_id
        policy = category.warranty_policy_id or company.default_warranty_policy_id
        order_date = order.date_order.date()

        rule = template.warranty_pricelist_rule_ids.filtered(
            lambda r: r.pricelist_id == order.pricelist_id
            and (not r.effective_from or r.effective_from <= order_date)
            and (not r.effective_to or r.effective_to >= order_date)
        ).sorted(lambda r: (r.priority, r.id))[:1]

        values = {'free_service_count': 0, 'free_service_frequency': 0,
                  'free_service_frequency_unit': False, 'usage_limit': 0.0, 'usage_unit': False}
        if rule:
            values.update({
                'policy_source': 'pricelist_rule',
                'warranty_duration': rule.warranty_period,
                'warranty_duration_unit': rule.warranty_period_unit,
                'free_service_count': rule.free_service_count,
                'free_service_frequency': rule.free_service_frequency,
                'free_service_frequency_unit': rule.free_service_frequency_unit,
                'usage_limit': rule.usage_limit,
                'usage_unit': rule.usage_unit,
            })
        elif template.default_warranty_period > 0:
            values.update({
                'policy_source': 'product',
                'warranty_duration': template.default_warranty_period,
                'warranty_duration_unit': template.default_warranty_period_unit,
                'free_service_count': template.default_free_service_count,
                'free_service_frequency': template.free_service_frequency,
                'free_service_frequency_unit': template.free_service_frequency_unit,
            })
        elif category.default_warranty_period > 0:
            values.update({
                'policy_source': 'category',
                'warranty_duration': category.default_warranty_period,
                'warranty_duration_unit': category.default_warranty_period_unit,
                'free_service_count': category.default_free_service_count,
                'free_service_frequency': category.free_service_frequency,
                'free_service_frequency_unit': category.free_service_frequency_unit,
            })
        elif company.default_warranty_duration > 0:
            values.update({
                'policy_source': 'company',
                'warranty_duration': company.default_warranty_duration,
                'warranty_duration_unit': company.default_warranty_duration_unit,
                'free_service_count': policy.free_service_count,
            })
        elif company.default_warranty_policy_id.warranty_duration > 0:
            company_policy = company.default_warranty_policy_id
            values.update({
                'policy_source': 'company',
                'warranty_duration': company_policy.warranty_duration,
                'warranty_duration_unit': company_policy.warranty_duration_unit,
                'free_service_count': company_policy.free_service_count,
            })
        else:
            raise UserError(_(
                "Configuration Required: no warranty rule was found for product "
                "\"%(product)s\" on %(order)s. Configure a Product + Pricelist rule, a product "
                "default rule, a product category rule or the company fallback rule.",
                product=self.product_id.display_name, order=order.name))

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
            'card_grouping_mode': (category.card_grouping_mode
                                   or policy.card_grouping_mode
                                   or company.default_card_grouping_mode),
        })
        missing = [label for key, label in (
            ('start_criterion', _("Start Criterion")),
            ('warranty_basis', _("Warranty Basis")),
            ('card_grouping_mode', _("Card Grouping Mode")),
        ) if not values[key]]
        if missing:
            raise UserError(_(
                "Configuration Required: %(fields)s could not be resolved for product "
                "\"%(product)s\" on %(order)s.",
                fields=', '.join(missing), product=self.product_id.display_name,
                order=order.name))
        return values
