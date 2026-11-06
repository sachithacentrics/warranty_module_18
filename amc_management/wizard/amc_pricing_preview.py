from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.amc_plan import PRICING_METHODS


class AmcPricingPreview(models.TransientModel):
    """Price Preview (SRS 2.12 "sample preview"; approved P4 / P6): the formula in force on the
    pricing date for sample equipment lines, converted into the currency of the customer's AMC
    pricelist (or a chosen one) with the standard rates; full breakdown. Nothing is stored."""
    _name = 'amc.pricing.preview'
    _description = 'AMC Price Preview'

    plan_id = fields.Many2one('amc.plan', string='AMC Plan', required=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company,
                                 required=True)
    pricing_date = fields.Date(string='Pricing Date', required=True,
                               default=fields.Date.context_today)
    formula_id = fields.Many2one('amc.pricing.formula', string='Formula Version',
                                 compute='_compute_formula_id', precompute=True, store=True, readonly=False,
                                 domain="[('plan_id', '=', plan_id), ('state', '=', 'active')]")
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 help="Resolves the customer's AMC pricelist (customer -> country "
                                      "group -> AMC Default Pricelist -> company currency).")
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist',
                                   compute='_compute_pricelist_id', precompute=True, store=True, readonly=False)
    target_currency_id = fields.Many2one('res.currency', string='Contract Currency',
                                         compute='_compute_target_currency', precompute=True, store=True,
                                         readonly=False, required=True)
    contract_months = fields.Integer(string='Contract Months', compute='_compute_months', precompute=True,
                                     store=True, readonly=False)
    expected_usage = fields.Float(string='Expected Usage')
    line_ids = fields.One2many('amc.pricing.preview.line', 'preview_id', string='Equipment')
    # Result.
    formula_currency_id = fields.Many2one('res.currency', string='Formula Currency',
                                          readonly=True)
    formula_amount = fields.Monetary(string='Formula Amount', currency_field='formula_currency_id',
                                     readonly=True)
    exchange_rate = fields.Float(string='Exchange Rate', digits=(16, 6), readonly=True)
    conversion_date = fields.Date(string='Conversion Date', readonly=True)
    converted_amount = fields.Monetary(string='Converted Amount',
                                       currency_field='target_currency_id', readonly=True)
    price = fields.Monetary(string='Final Price', currency_field='target_currency_id',
                            readonly=True)
    method = fields.Selection(PRICING_METHODS, string='Pricing Method', readonly=True)
    entitlement_info = fields.Char(string='Service Entitlements', readonly=True)
    breakdown = fields.Text(string='Calculation', readonly=True)

    @api.depends('plan_id', 'pricing_date')
    def _compute_formula_id(self):
        for preview in self:
            preview.formula_id = preview.plan_id._amc_pricing_formula(
                preview.pricing_date, raise_missing=False) if preview.plan_id \
                and preview.pricing_date else False

    @api.depends('partner_id', 'company_id')
    def _compute_pricelist_id(self):
        for preview in self:
            company = preview.company_id or self.env.company
            preview.pricelist_id = company._amc_resolve_pricelist(
                preview.partner_id)[0] if preview.partner_id else False

    @api.depends('pricelist_id', 'company_id')
    def _compute_target_currency(self):
        for preview in self:
            company = preview.company_id or self.env.company
            preview.target_currency_id = company._amc_currency(preview.pricelist_id or None)

    @api.depends('plan_id')
    def _compute_months(self):
        for preview in self:
            preview.contract_months = preview.plan_id._duration_months() if preview.plan_id \
                else 12

    def action_calculate(self):
        self.ensure_one()
        formula = self.formula_id
        if not formula:
            raise UserError(_("AMC Plan %(plan)s has no Active pricing formula on %(date)s.",
                              plan=self.plan_id.name, date=self.pricing_date))
        if formula.plan_id != self.plan_id or formula.state != 'active' \
                or not formula._covers(self.pricing_date):
            raise UserError(_("Formula %(formula)s is not the Active version of %(plan)s on "
                              "%(date)s.", formula=formula.name, plan=self.plan_id.name,
                              date=self.pricing_date))
        lines = [{'product': line.product_id, 'quantity': line.quantity,
                  'equipment_value': line.equipment_value,
                  'site': line.site_id.id or 'site-%s' % line.id}
                 for line in self.line_ids]
        if not lines:
            raise UserError(_("Add at least one equipment line."))
        result = formula._amc_compute_price(lines, self.target_currency_id, self.pricing_date,
                                            months=self.contract_months,
                                            usage=self.expected_usage)
        plan = self.plan_id
        self.write({
            'formula_currency_id': result['formula_currency'].id,
            'formula_amount': result['formula_amount'],
            'exchange_rate': result['rate'],
            'conversion_date': result['conversion_date'],
            'converted_amount': result['converted_amount'],
            'price': result['price'],
            'method': result['method'],
            'entitlement_info': _(
                "%(ent)s preventive service entitlements (%(per)s x %(qty)s equipment) + "
                "%(free)s on-demand services; physical technician visits may be fewer when "
                "equipment is serviced together.", ent='%g' % result['entitlements'],
                per=plan.visit_count, qty='%g' % result['quantity'],
                free='%g' % (plan.included_free_services * result['quantity'])),
            'breakdown': '\n'.join(result['breakdown']),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
