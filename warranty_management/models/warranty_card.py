from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


CARD_STATES = [
    ('draft', 'Draft'),
    ('ready', 'Ready to Confirm'),
    ('confirmed', 'Confirmed'),
    ('suspended', 'Suspended'),
    ('expired', 'Expired'),
    ('cancelled', 'Cancelled'),
]

# Fields read by _get_missing_requirements(); the Draft <-> Ready to Confirm
# state and the missing-requirements text are recomputed when they change.
REQUIREMENT_DEPENDS = [
    'policy_source', 'warranty_basis', 'start_criterion',
    'warranty_duration', 'warranty_duration_unit',
    'installation_date', 'warranty_start_date', 'warranty_end_date',
    'partner_id', 'company_id', 'policy_id.payment_check_required',
    'unit_warranty_ids', 'unit_warranty_ids.product_id',
    'unit_warranty_ids.sale_order_line_id', 'unit_warranty_ids.stock_move_line_id',
    'unit_warranty_ids.serial_ids',
    'delivery_ids', 'delivery_ids.state', 'delivery_ids.date_done',
    'sale_order_line_ids.invoice_lines.move_id.state',
    'sale_order_line_ids.invoice_lines.move_id.invoice_date',
    'sale_order_line_ids.invoice_lines.move_id.payment_state',
]


class WarrantyCard(models.Model):
    _name = 'warranty.card'
    _description = 'Warranty Card'
    _order = 'id desc'

    name = fields.Char(
        string='Warranty Card No.', required=True, readonly=True, copy=False, default='New')
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, index=True)
    product_id = fields.Many2one('product.product', string='Product')
    brand_id = fields.Char(string='Brand')
    model_id = fields.Char(string='Model')
    indoor_serial_id = fields.Many2one('stock.lot', string='Indoor Serial No.')
    outdoor_serial_id = fields.Many2one('stock.lot', string='Outdoor Serial No.')
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', index=True, readonly=True)
    sale_order_line_ids = fields.Many2many(
        'sale.order.line', 'warranty_card_sale_order_line_rel', 'card_id', 'line_id',
        string='Sales Order Lines', readonly=True)
    delivery_ids = fields.Many2many(
        'stock.picking', 'warranty_card_stock_picking_rel', 'card_id', 'picking_id',
        string='Delivery Orders', readonly=True)
    invoice_ids = fields.Many2many(
        'account.move', string='Invoices', compute='_compute_invoice_ids')
    installation_date = fields.Date(string='Installation Date')
    warranty_start_date = fields.Date(string='Warranty Start Date')
    warranty_end_date = fields.Date(string='Warranty End Date')
    state = fields.Selection(
        CARD_STATES, string='Status', default='draft', required=True, copy=False,
        compute='_compute_state', store=True, readonly=False, index=True)
    confirmation_status = fields.Selection(
        related='state', string='Confirmation Status')
    missing_requirements = fields.Text(
        string='Missing Confirmation Requirements', compute='_compute_missing_requirements',
        store=True)

    free_services_allowed = fields.Integer(string='Free Services Allowed', readonly=True)
    free_services_used = fields.Integer(
        string='Free Services Used', compute='_compute_free_services')
    free_services_balance = fields.Integer(
        string='Free Services Balance', compute='_compute_free_services')
    replacement_count = fields.Integer(
        string='Replacement Count', compute='_compute_replacement_count')
    current_active_serial = fields.Boolean(string='Current Active Serial Flag', default=True)
    pdf_attachment_id = fields.Many2one(
        'ir.attachment', string='PDF Soft Copy', readonly=True, copy=False)
    print_count = fields.Integer(string='Print Count', compute='_compute_print_count')

    card_grouping_mode = fields.Selection([
        ('per_so', 'Per Sales Order'),
        ('per_product', 'Per Product'),
        ('per_delivery', 'Per Delivery'),
        ('per_unit', 'Per Unit/Serial'),
    ], string='Card Grouping Mode', readonly=True)
    unit_warranty_ids = fields.One2many(
        'warranty.unit', 'warranty_card_id', string='Unit Warranty Numbers')
    warranty_basis = fields.Selection([
        ('period', 'Period'),
        ('usage', 'Usage'),
    ], string='Warranty Basis', readonly=True)
    start_criterion = fields.Selection([
        ('installation', 'Installation/Commissioning'),
        ('delivery', 'Delivery'),
        ('invoice', 'Invoice'),
        ('custom', 'Custom Date Range'),
    ], string='Start Criterion', readonly=True)

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    policy_id = fields.Many2one('warranty.policy', string='Warranty Policy', readonly=True)
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', readonly=True)
    policy_source = fields.Selection([
        ('pricelist_rule', 'Product + Pricelist Rule'),
        ('product', 'Product Default Rule'),
        ('category', 'Product Category Rule'),
        ('company', 'Company Fallback Rule'),
    ], string='Policy Source', readonly=True)

    # Values of the resolved warranty rule, needed to calculate the dates on confirmation.
    warranty_duration = fields.Integer(string='Warranty Duration', readonly=True)
    warranty_duration_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Duration Unit', readonly=True)
    free_service_frequency = fields.Integer(string='Free Service Frequency', readonly=True)
    free_service_frequency_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Free Service Frequency Unit', readonly=True)
    usage_limit = fields.Float(string='Usage Limit', readonly=True)
    usage_unit = fields.Selection([
        ('operating_hours', 'Operating Hours'),
        ('cycles', 'Cycles'),
        ('km', 'KM'),
        ('units_produced', 'Units Produced'),
        ('other', 'Other'),
    ], string='Usage Unit', readonly=True)
    payment_check_required = fields.Boolean(
        related='policy_id.payment_check_required', string='Payment Check Required')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                company = self.env['res.company'].browse(vals.get('company_id')) \
                    if vals.get('company_id') else self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(company) \
                    .next_by_code('warranty.card') or 'New'
        return super().create(vals_list)

    @api.depends('sale_order_line_ids.invoice_lines.move_id')
    def _compute_invoice_ids(self):
        for card in self:
            card.invoice_ids = card.sale_order_line_ids.invoice_lines.move_id.filtered(
                lambda move: move.move_type == 'out_invoice')

    def _compute_free_services(self):
        # Service entitlements are delivered in Part 2 of the Development Mapping.
        for card in self:
            card.free_services_used = 0
            card.free_services_balance = card.free_services_allowed - card.free_services_used

    def _compute_replacement_count(self):
        # Replacement records are delivered in Part 7 of the Development Mapping.
        self.replacement_count = 0

    def _compute_print_count(self):
        # Print history is delivered in a later part of the Development Mapping.
        self.print_count = 0

    @api.depends(*REQUIREMENT_DEPENDS)
    def _compute_state(self):
        for card in self:
            if card.state in (False, 'draft', 'ready'):
                card.state = 'draft' if card._get_missing_requirements() else 'ready'

    @api.depends('state', *REQUIREMENT_DEPENDS)
    def _compute_missing_requirements(self):
        for card in self:
            missing = card._get_missing_requirements() \
                if card.state in (False, 'draft', 'ready') else []
            card.missing_requirements = '\n'.join(missing) or False

    def _get_unit_number_prefix(self):
        """WC/00012 -> WN/00012 (unit numbers are WN/xxxxx-xx under the card number)."""
        self.ensure_one()
        return 'WN/%s' % self.name.split('/', 1)[-1]

    def _create_unit_warranty_numbers(self, specs):
        """Create one Unit Warranty Number per (sale order line, unit number) in specs."""
        self.ensure_one()
        prefix = self._get_unit_number_prefix()
        start = len(self.unit_warranty_ids)
        return self.env['warranty.unit'].create([{
            'name': '%s-%02d' % (prefix, start + index),
            'warranty_card_id': self.id,
            'sale_order_line_id': line.id,
            'product_id': line.product_id.id,
            'unit_number': unit_number,
        } for index, (line, unit_number) in enumerate(specs, start=1)])

    def _split_units_to_new_card(self, units, deliveries):
        """Per Delivery grouping: move units that were not delivered to a new Draft card."""
        self.ensure_one()
        new_card = self.copy({
            'sale_order_line_ids': [Command.set(units.sale_order_line_id.ids)],
            'delivery_ids': [Command.set(deliveries.ids)],
            'installation_date': False,
            'warranty_start_date': False,
            'warranty_end_date': False,
        })
        prefix = new_card._get_unit_number_prefix()
        for index, unit in enumerate(units, start=1):
            unit.write({'warranty_card_id': new_card.id, 'name': '%s-%02d' % (prefix, index)})
        return new_card

    def _get_posted_invoices(self):
        self.ensure_one()
        return self.sale_order_line_ids.invoice_lines.move_id.filtered(
            lambda move: move.move_type == 'out_invoice' and move.state == 'posted')

    def _get_done_deliveries(self):
        self.ensure_one()
        return self.delivery_ids.filtered(lambda picking: picking.state == 'done')

    def _get_missing_requirements(self):
        """Warranty confirmation requirements of the Part 1 workflow:
        resolved rule, product/quantity, unit warranty lines, required serials,
        start criterion, required dates, invoice/payment if configured,
        grouping compatibility and warranty basis."""
        self.ensure_one()
        missing = []
        if not self.policy_source:
            missing.append(_("Resolved warranty rule"))
        if not self.warranty_basis:
            missing.append(_("Warranty basis"))
        elif self.warranty_basis == 'period' and (
                self.warranty_duration <= 0 or not self.warranty_duration_unit):
            missing.append(_("Warranty duration and duration unit"))

        units = self.unit_warranty_ids
        if not units:
            missing.append(_("Unit warranty lines"))
        for unit in units:
            if not unit.product_id or not unit.sale_order_line_id:
                missing.append(_("Product / quantity on unit %s", unit.name))
                continue
            if unit.product_id.type == 'consu' and not unit.stock_move_line_id:
                missing.append(_("Delivery for unit %s", unit.name))
            if unit.product_id.tracking == 'serial' and not unit.serial_ids:
                missing.append(_("Serial number for unit %s", unit.name))

        if not self.start_criterion:
            missing.append(_("Start criterion"))
        elif self.start_criterion == 'installation' and not self.installation_date:
            missing.append(_("Installation / commissioning date"))
        elif self.start_criterion == 'delivery' and not self._get_done_deliveries():
            missing.append(_("Validated delivery"))
        elif self.start_criterion == 'invoice' and not self._get_posted_invoices().filtered(
                'invoice_date'):
            missing.append(_("Posted invoice"))
        elif self.start_criterion == 'custom':
            if not self.warranty_start_date or not self.warranty_end_date:
                missing.append(_("Custom warranty start and end dates"))
            elif self.warranty_end_date < self.warranty_start_date:
                missing.append(_("Custom warranty end date must not be before the start date"))

        if self.policy_id.payment_check_required and not self._get_posted_invoices().filtered(
                lambda move: move.payment_state in ('paid', 'in_payment')):
            missing.append(_("Invoice payment"))

        orders = units.sale_order_line_id.order_id
        if any(order.partner_id != self.partner_id or order.company_id != self.company_id
               for order in orders):
            missing.append(_("Grouping compatibility (customer / company)"))
        return missing

    def _get_warranty_start_date(self):
        self.ensure_one()
        if self.start_criterion == 'installation':
            return self.installation_date
        if self.start_criterion == 'delivery':
            last_done = max(self._get_done_deliveries().mapped('date_done'))
            return fields.Datetime.context_timestamp(self, last_done).date()
        if self.start_criterion == 'invoice':
            return min(self._get_posted_invoices().filtered('invoice_date').mapped('invoice_date'))
        return self.warranty_start_date

    def _get_warranty_end_date(self, start_date):
        self.ensure_one()
        if self.start_criterion == 'custom':
            return self.warranty_end_date
        if self.warranty_basis != 'period':
            return False
        duration = relativedelta(**{self.warranty_duration_unit: self.warranty_duration})
        return start_date + duration - relativedelta(days=1)

    def action_confirm_warranty(self):
        for card in self:
            if card.state != 'ready':
                raise UserError(_("Only warranty cards that are Ready to Confirm can be confirmed."))
            missing = card._get_missing_requirements()
            if missing:
                raise UserError(_(
                    "Warranty card %(card)s cannot be confirmed. Missing:\n%(missing)s",
                    card=card.name, missing='\n'.join(missing)))
            start_date = card._get_warranty_start_date()
            end_date = card._get_warranty_end_date(start_date)
            card.write({
                'warranty_start_date': start_date,
                'warranty_end_date': end_date,
                'state': 'confirmed',
            })
            card.unit_warranty_ids.write({
                'start_date': start_date,
                'end_date': end_date,
                'usage_limit': card.usage_limit,
                'usage_unit': card.usage_unit,
                'state': 'active',
            })
        self._generate_soft_copy()
        return True

    def _generate_soft_copy(self):
        report = self.env.ref('warranty_management.action_report_warranty_card')
        for card in self:
            pdf_content, __ = self.env['ir.actions.report']._render_qweb_pdf(report, card.ids)
            attachment = self.env['ir.attachment'].create({
                'name': '%s.pdf' % card.name.replace('/', '_'),
                'type': 'binary',
                'raw': pdf_content,
                'mimetype': 'application/pdf',
                'res_model': card._name,
                'res_id': card.id,
            })
            card.pdf_attachment_id = attachment
