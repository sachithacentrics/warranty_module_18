from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero


class AmcContractLine(models.Model):
    """Covered equipment (Mapping 7): product, serial, site, quantity, equipment value (C4:
    original amount and currency kept, converted into the contract currency at the transfer
    date), coverage dates. Approved B5a: entitlements per covered unit."""
    _name = 'amc.contract.line'
    _description = 'AMC Covered Equipment'
    _order = 'contract_id, id'

    contract_id = fields.Many2one('amc.contract', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    serial_id = fields.Many2one('stock.lot', string='Serial / Lot',
                                domain="[('product_id', '=', product_id)]")
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    site_id = fields.Many2one('res.partner', string='Site',
                              help="Service location; empty = the contract site.")
    original_value = fields.Float(string='Original Equipment Value')
    original_currency_id = fields.Many2one('res.currency', string='Original Currency')
    value_rate = fields.Float(string='Conversion Rate', digits=(16, 6), readonly=True)
    value_date = fields.Date(string='Conversion Date', readonly=True)
    equipment_value = fields.Monetary(
        string='Equipment Value', compute='_compute_equipment_value', store=True,
        help="In the contract currency (formula input of Percentage / Hybrid pricing).")
    coverage_start_date = fields.Date(related='contract_id.start_date', string='Coverage Start')
    coverage_end_date = fields.Date(related='contract_id.end_date', string='Coverage End')

    @api.depends('product_id', 'serial_id', 'contract_id.name')
    def _compute_display_name(self):
        """e.g. "AMC/00003 - GREE 9000 BTU (SN-001)" (was the technical "amc.contract.line,1")."""
        for line in self:
            name = '%s - %s' % (line.contract_id.name or '', line.product_id.display_name or '')
            line.display_name = '%s (%s)' % (name, line.serial_id.name) if line.serial_id else name

    @api.depends('original_value', 'original_currency_id', 'contract_id.currency_id')
    def _compute_equipment_value(self):
        """Approved C4: converted with the standard rate of the transfer (entry) date."""
        for line in self:
            target = line.contract_id.currency_id
            source = line.original_currency_id or target
            date = line.value_date or fields.Date.context_today(line)
            company = line.contract_id.company_id or self.env.company
            if source and target and source != target:
                line.equipment_value = source._convert(line.original_value, target, company,
                                                       date)
            else:
                line.equipment_value = line.original_value

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.context_today(self)
        for vals in vals_list:
            vals.setdefault('value_date', today)
        lines = super().create(vals_list)
        lines._amc_snapshot_rate()
        lines.contract_id._amc_check_draft_lines()
        lines.contract_id.filtered(lambda c: c.price_state != 'none')._amc_reset_price(
            _("covered equipment changed"))
        return lines

    def write(self, vals):
        self.contract_id._amc_check_draft_lines()
        if {'original_value', 'original_currency_id'} & set(vals):
            vals = dict(vals, value_date=vals.get('value_date')
                        or fields.Date.context_today(self))
        result = super().write(vals)
        if {'original_value', 'original_currency_id'} & set(vals):
            self._amc_snapshot_rate()
        if {'product_id', 'quantity', 'original_value', 'original_currency_id', 'site_id',
                'serial_id'} & set(vals):
            self.contract_id.filtered(lambda c: c.price_state != 'none')._amc_reset_price(
                _("covered equipment changed"))
        return result

    def unlink(self):
        contracts = self.contract_id
        contracts._amc_check_draft_lines()
        result = super().unlink()
        contracts.exists().filtered(lambda c: c.price_state != 'none')._amc_reset_price(
            _("covered equipment changed"))
        return result

    def _amc_snapshot_rate(self):
        for line in self:
            target = line.contract_id.currency_id
            source = line.original_currency_id
            company = line.contract_id.company_id
            if source and target and source != target:
                rate = self.env['res.currency']._get_conversion_rate(source, target, company,
                                                                     line.value_date)
            else:
                rate = 1.0
            if line.value_rate != rate:
                super(AmcContractLine, line).write({'value_rate': rate})

    def _amc_renewal_values(self):
        """Values copied to the renewal contract (AS-04)."""
        self.ensure_one()
        return {'product_id': self.product_id.id, 'serial_id': self.serial_id.id or False,
                'quantity': self.quantity, 'site_id': self.site_id.id or False,
                'original_value': self.original_value,
                'original_currency_id': self.original_currency_id.id or False}

    def _amc_serial_conflicts(self):
        """Open contracts already covering the serial of this line. The predecessor / successor
        of a renewal never conflict with each other (same unit, consecutive periods)."""
        self.ensure_one()
        contract = self.contract_id
        others = self.search([
            ('id', '!=', self.id), ('serial_id', '=', self.serial_id.id),
            ('contract_id.state', 'not in', ('cancelled', 'closed', 'renewed'))])
        return others.filtered(lambda other: other.contract_id != contract.renewal_of_id
                               and other.contract_id.renewal_of_id != contract
                               and other.contract_id != contract)

    def _amc_line_problems(self):
        """Plan applicability (products / categories), serial of the product, quantity 1 per
        serial, a serial covered by only one open contract, whole covered quantities."""
        problems = []
        for line in self:
            plan = line.contract_id.plan_id
            product = line.product_id
            if plan.product_ids or plan.category_ids:
                in_category = any(product.categ_id.parent_path.startswith(categ.parent_path)
                                  for categ in plan.category_ids if product.categ_id.parent_path)
                if product not in plan.product_ids and not in_category:
                    problems.append(_("%(product)s is not covered by AMC Plan %(plan)s",
                                      product=product.display_name, plan=plan.name))
            if line.serial_id:
                if line.serial_id.product_id != product:
                    problems.append(_("serial %s belongs to another product",
                                      line.serial_id.name))
                if line.quantity != 1:
                    problems.append(_("a line with serial %s covers quantity 1",
                                      line.serial_id.name))
                others = line._amc_serial_conflicts()
                if others:
                    problems.append(_("serial %(serial)s is already covered by %(contract)s",
                                      serial=line.serial_id.name,
                                      contract=', '.join(others.contract_id.mapped('name'))))
            if line.quantity <= 0:
                problems.append(_("equipment quantities must be greater than zero"))
            elif not float_is_zero(line.quantity - round(line.quantity), precision_digits=6):
                # AMC-E01 / B5a: entitlements are generated per covered unit.
                problems.append(_("covered quantities are whole units (%s)",
                                  product.display_name))
            site = line.site_id
            if site and site.commercial_partner_id != line.contract_id.commercial_partner_id:
                problems.append(_("site %s is not an address of the customer", site.display_name))
        return problems

    def _amc_pricing_lines(self):
        return [{'product': line.product_id, 'quantity': line.quantity,
                 'equipment_value': line.equipment_value,
                 'site': (line.site_id or line.contract_id.site_id
                          or line.contract_id.partner_id).id} for line in self]

    @api.constrains('quantity', 'serial_id', 'product_id', 'site_id')
    def _check_line(self):
        problems = self._amc_line_problems()
        if problems:
            raise ValidationError('; '.join(problems))
