from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class WarrantyVendorClaim(models.Model):
    _inherit = 'warranty.vendor.claim'

    def _lock_and_check_lines(self):
        """Claims of a replacement have no Material Request line to lock: their lines lock the
        replacement in _check_line."""
        lines = self.line_ids
        if lines and not lines.mrf_line_id:
            self.env.flush_all()
            lines._check_line()
            return
        super()._lock_and_check_lines()


class WarrantyVendorClaimLine(models.Model):
    """SRS 11.1, 12 #15: a claim line of a Material Request line, or of a Done Vendor replacement.
    The claim workflow is the same; Material Request lines take the existing code."""
    _inherit = 'warranty.vendor.claim.line'

    mrf_line_id = fields.Many2one(required=False)
    replacement_id = fields.Many2one('warranty.replacement', string='Replacement', readonly=True,
                                     ondelete='restrict', index='btree_not_null')
    product_id = fields.Many2one('product.product', related=None, compute='_compute_claimed_product',
                                 store=True, readonly=True)
    uom_id = fields.Many2one('uom.uom', related=None, compute='_compute_claimed_details')
    tracking = fields.Selection(
        [('serial', 'By Unique Serial Number'), ('lot', 'By Lots'), ('none', 'By Quantity')],
        related=None, compute='_compute_claimed_details')

    @api.depends('mrf_line_id.product_id', 'replacement_id.product_id')
    def _compute_claimed_product(self):
        for line in self:
            source = line.sudo()
            line.product_id = source.mrf_line_id.product_id or source.replacement_id.product_id

    @api.depends('mrf_line_id.uom', 'product_id')
    def _compute_claimed_details(self):
        for line in self:
            source = line.sudo()
            product = source.product_id
            line.uom_id = source.mrf_line_id.uom if source.mrf_line_id else product.uom_id
            line.tracking = product.tracking

    @api.constrains('mrf_line_id', 'replacement_id')
    def _check_claim_source(self):
        for line in self:
            if bool(line.mrf_line_id) == bool(line.replacement_id):
                raise ValidationError(_("A claim line belongs to one Material Request line or to "
                                        "one replacement."))

    @api.depends('mrf_line_id', 'claim_id.state', 'replacement_id')
    def _compute_allowed_lot_ids(self):
        replacement_lines = self.filtered('replacement_id')
        super(WarrantyVendorClaimLine, self - replacement_lines)._compute_allowed_lot_ids()
        for line in replacement_lines:
            line.allowed_lot_ids = line.sudo().replacement_id.old_serial_id

    @api.model_create_multi
    def create(self, vals_list):
        """A line entered on the form claims the one replaced unit, as Create Vendor Claim does.
        Every check runs in the claim workflow."""
        for vals in vals_list:
            if vals.get('replacement_id'):
                replacement = self.env['warranty.replacement'].sudo().browse(vals['replacement_id'])
                vals['qty'] = vals.get('qty') or 1.0
                if not vals.get('lot_ids'):
                    vals['lot_ids'] = [(6, 0, replacement.old_serial_id.ids)]
        lines = super().create(vals_list)
        if not self.env.su:
            for line in lines.filtered('replacement_id'):
                replacement = line.sudo().replacement_id
                replacement._warranty_replacement_log(
                    _("Vendor claim %(claim)s created for replacement %(ref)s.",
                      claim=line.claim_id.name, ref=replacement.name))
        return lines

    @api.onchange('replacement_id')
    def _onchange_replacement_id(self):
        if self.replacement_id:
            self.qty = 1.0
            self.lot_ids = self.replacement_id.sudo().old_serial_id

    def _warranty_claim_partner_proposal(self):
        self.ensure_one()
        if self.replacement_id:
            return self.replacement_id.sudo()._warranty_replacement_claim_partner()
        return super()._warranty_claim_partner_proposal()

    def write(self, vals):
        if 'replacement_id' in vals and not self.env.su:
            raise UserError(_("The replacement of a claim line is set by the claim workflow."))
        return super().write(vals)

    def _set_cost_basis(self):
        """The cost of the replacement delivery (one unit), not a Material Request cost."""
        replacement_lines = self.filtered('replacement_id')
        super(WarrantyVendorClaimLine, self - replacement_lines)._set_cost_basis()
        for line in replacement_lines:
            unit = line.sudo().replacement_id.replacement_cost
            vals = {'unit_cost': unit, 'goodwill': False}
            if not line.claimed_amount:
                vals['claimed_amount'] = line.claim_id.currency_id.round(line.qty * unit)
            line.sudo().with_context(warranty_claim_no_check=True).write(vals)

    def _check_line(self):
        replacement_lines = self.filtered('replacement_id')
        super(WarrantyVendorClaimLine, self - replacement_lines)._check_line()
        replacement_lines._warranty_check_replacement_line()

    def _warranty_check_replacement_line(self):
        """The same checks as a Material Request line: eligibility, amount, serial, no duplicate."""
        for line in self.filtered('active_claim'):
            claim = line.claim_id
            if claim.state in ('cancel', 'closed', 'answered', 'sent'):
                continue
            replacement = line.sudo().replacement_id
            replacement._warranty_replacement_lock()
            problem = replacement._warranty_replacement_claim_problem(exclude=line)
            if problem:
                raise UserError(_("%(claim)s / %(ref)s: %(problem)s", claim=claim.name,
                                  ref=replacement.name, problem=problem))
            if replacement.warranty_case_id != claim.case_id \
                    or replacement.company_id != claim.company_id:
                raise UserError(_("Replacement %s belongs to another warranty case or company.",
                                  replacement.name))
            if line.qty != 1:
                raise UserError(_("Replacement %s: a claim covers the one replaced unit.",
                                  replacement.name))
            currency = claim.currency_id
            if currency.compare_amounts(line.claimed_amount, 0.0) <= 0 or currency.compare_amounts(
                    line.claimed_amount, replacement.replacement_cost) > 0:
                raise UserError(_("Replacement %(ref)s: the claimed amount must be positive and not "
                                  "above the verified cost %(limit)s.", ref=replacement.name,
                                  limit=claim._money(replacement.replacement_cost)))
            if line.lot_ids - replacement.old_serial_id:
                raise UserError(_("Replacement %(ref)s: the claim serial is the old serial "
                                  "%(serial)s.", ref=replacement.name,
                                  serial=replacement.old_serial_id.name))
