from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .amc_plan import ACTIVATION_TRIGGERS, RENEWAL_RULES, START_RULES


class ResCompany(models.Model):
    """AMC General Configuration (Mapping 3): AMC Enabled, default plan, pricelist, billing
    plan, start criteria, renewal rule and alert days, per company."""
    _inherit = 'res.company'

    amc_enabled = fields.Boolean(string='AMC Enabled', default=True)
    amc_default_plan_id = fields.Many2one('amc.plan', string='Default AMC Plan')
    # Fallback only (approved multi-currency A1): used when the customer has no pricelist of
    # its own or of its country; it never restricts the AMC currency.
    amc_default_pricelist_id = fields.Many2one(
        'product.pricelist', string='Default AMC Pricelist',
        help="Fallback when the customer has no applicable pricelist; without any pricelist the "
             "company currency is used.")
    amc_default_billing_plan_id = fields.Many2one('amc.billing.plan',
                                                  string='Default Billing Plan')
    amc_default_start_rule = fields.Selection(START_RULES, string='Default Start Criteria',
                                              default='activation')
    amc_default_renewal_rule = fields.Selection(RENEWAL_RULES, string='Default Renewal Rule',
                                                default='manual')
    amc_default_alert_days = fields.Integer(string='Default Alert Days', default=7)
    # Phase A3 (approved B4a / B4b).
    amc_activation_trigger = fields.Selection(ACTIVATION_TRIGGERS, string='AMC Activation Trigger',
                                              default='payment')
    amc_product_id = fields.Many2one(
        'product.product', string='AMC Service Product',
        default=lambda self: self.env.ref('amc_management.product_amc_service',
                                          raise_if_not_found=False),
        help="Service product of the AMC quotation lines (invoiced on delivered quantities: "
             "one per released billing period).")

    @api.constrains('amc_product_id')
    def _check_amc_product(self):
        """Approved B4a: a service invoiced on delivered quantities (manually set)."""
        for company in self:
            product = company.amc_product_id
            if product and (product.type != 'service' or product.invoice_policy != 'delivery'
                            or product.service_type != 'manual' or not product.sale_ok
                            or product.company_id not in (company, self.env['res.company'])):
                raise ValidationError(_(
                    "The AMC Service Product of %s must be a saleable service of the company (or "
                    "shared), invoiced on delivered quantities set manually.", company.name))

    @api.constrains('amc_default_plan_id', 'amc_default_pricelist_id',
                    'amc_default_billing_plan_id', 'amc_default_alert_days')
    def _check_amc_defaults(self):
        for company in self:
            if company.amc_default_alert_days < 0:
                raise ValidationError(_("The Default Alert Days of %s cannot be negative.",
                                        company.name))
            for record in (company.amc_default_plan_id, company.amc_default_pricelist_id,
                           company.amc_default_billing_plan_id):
                if record and record.company_id and record.company_id != company:
                    raise ValidationError(_(
                        "The AMC default %(record)s belongs to another company than %(company)s.",
                        record=record.display_name, company=company.name))
            plan = company.amc_default_plan_id
            if plan and not plan.active:
                raise ValidationError(_("The Default AMC Plan %s is archived.", plan.name))

    # ------------------------------------------------------------------ multi-currency (A1)
    def _amc_pricelist_usable(self, pricelist):
        """Active pricelist of this company or shared (multi-company)."""
        self.ensure_one()
        return bool(pricelist) and pricelist.active and pricelist.company_id in (
            self, self.env['res.company'])

    def _amc_resolve_pricelist(self, partner):
        """AMC pricelist of `partner` in this company (approved multi-currency A1, C2): the
        pricelist assigned to the customer (commercial entity) for this company, else a
        country-group pricelist of the customer's country, else the AMC Default Pricelist
        (fallback only), else none (company currency). Standard Odoo records only; the
        generic "first available pricelist" fallback of Odoo is not a customer pricelist.
        Returns (pricelist, source) - source: 'customer', 'country', 'default' or False."""
        self.ensure_one()
        Pricelist = self.env['product.pricelist']
        commercial = partner.commercial_partner_id.with_company(self)
        customer = commercial.specific_property_product_pricelist
        if self._amc_pricelist_usable(customer):
            return customer, 'customer'
        country = commercial.country_id
        if country:
            by_country = Pricelist.search([
                ('active', '=', True), ('company_id', 'in', (self.id, False)),
                ('country_group_ids.country_ids', 'in', country.ids)], order='sequence, id',
                limit=1)
            if by_country:
                return by_country, 'country'
        default = self.amc_default_pricelist_id
        if self._amc_pricelist_usable(default):
            return default, 'default'
        return Pricelist, False

    def _amc_currency(self, pricelist=None):
        """Currency of AMC amounts: the pricelist's currency, else the company currency (no
        conversion here; conversions use the standard res.currency rates from phase A2)."""
        self.ensure_one()
        return pricelist.currency_id if pricelist else self.currency_id

    def _amc_product(self):
        """AMC Service Product: the company setting, else the module's AMC Contract Service."""
        self.ensure_one()
        return self.amc_product_id or self.env.ref('amc_management.product_amc_service',
                                                   raise_if_not_found=False)
