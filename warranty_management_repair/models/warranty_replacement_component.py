from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from .warranty_replacement import _REPLACEMENT_MARKER

REQUEST_FIELDS = {'replacement_id', 'product_id', 'qty', 'old_lot_id', 'old_part_details',
                  'return_required', 'no_return_reason'}


class WarrantyReplacementComponentLine(models.Model):
    """A part of a Component replacement (SRS 11.1): old details and defective return here; the
    approval, issue, usage and cost of the new part stay on its Material Request line."""
    _name = 'warranty.replacement.component.line'
    _description = 'Warranty Replacement Component'
    _order = 'replacement_id, id'

    replacement_id = fields.Many2one('warranty.replacement', required=True, ondelete='cascade',
                                     index=True)
    company_id = fields.Many2one(related='replacement_id.company_id', store=True, index=True)
    product_id = fields.Many2one('product.product', string='Component', required=True,
                                 ondelete='restrict')
    tracking = fields.Selection(related='product_id.tracking')
    qty = fields.Float(string='Quantity', required=True, default=1.0,
                       digits='Product Unit of Measure')
    old_lot_id = fields.Many2one('stock.lot', string='Old Serial / Lot', ondelete='restrict',
                                 domain="[('product_id', '=', product_id)]")
    old_part_details = fields.Char(string='Old Part Details')
    return_required = fields.Boolean(
        string='Return Defective Part', default=True,
        help="A standard return of the defective part from the customer to the Old Unit Location.")
    no_return_reason = fields.Char(
        string='Reason for No Return',
        help="Needed when the defective part is not returned, for example a tracked part whose "
             "serial cannot be identified.")
    return_picking_id = fields.Many2one('stock.picking', string='Return Picking', readonly=True,
                                        copy=False, ondelete='restrict', index='btree_not_null')
    mrf_line_id = fields.Many2one(
        'material.purchase.requisition.line', string='Material Request Line', copy=False,
        ondelete='restrict', index='btree_not_null',
        help="The new part: its approval, issue, usage and cost stay on the Material Request.")
    used_qty = fields.Float(related='mrf_line_id.used_qty', string='Used',
                            digits='Product Unit of Measure')
    new_lot_ids = fields.Many2many('stock.lot', string='New Serial / Lot',
                                   compute='_compute_new_lots', compute_sudo=True)

    @api.depends('mrf_line_id.warranty_consumption_ids.lot_ids',
                 'mrf_line_id.warranty_consumption_ids.state')
    def _compute_new_lots(self):
        for line in self:
            line.new_lot_ids = line.mrf_line_id.warranty_consumption_ids.filtered(
                lambda entry: entry.kind in ('used', 'installed') and entry.state == 'done').lot_ids

    @api.constrains('product_id', 'old_lot_id', 'mrf_line_id')
    def _check_component_links(self):
        for line in self.sudo():
            if line.old_lot_id and line.old_lot_id.product_id != line.product_id:
                raise ValidationError(_("Old serial %(lot)s is not a serial of %(product)s.",
                                        lot=line.old_lot_id.name,
                                        product=line.product_id.display_name))
            mrf_line = line.mrf_line_id
            if not mrf_line:
                continue
            if mrf_line.product_id != line.product_id or mrf_line.requisition_id.warranty_case_id \
                    != line.replacement_id.warranty_case_id:
                raise ValidationError(_("The Material Request line must be of %(product)s and of "
                                        "warranty case %(case)s.",
                                        product=line.product_id.display_name,
                                        case=line.replacement_id.warranty_case_id.name))
            if self.search_count([('mrf_line_id', '=', mrf_line.id), ('id', '!=', line.id),
                                  ('replacement_id.state', '!=', 'rejected')]):
                raise ValidationError(_("This Material Request line is on another Component "
                                        "replacement."))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._warranty_component_check_write(REQUEST_FIELDS)
        return lines

    def write(self, vals):
        self._warranty_component_check_write(set(vals))
        return super().write(vals)

    def unlink(self):
        self._warranty_component_check_write(REQUEST_FIELDS)
        return super().unlink()

    def _warranty_component_check_write(self, names):
        """Request details while Draft; the Material Request link while Approved. The transfer is set
        by the replacement."""
        if self.env.context.get('warranty_replacement_marker') is _REPLACEMENT_MARKER:
            return
        if 'return_picking_id' in names:
            raise UserError(_("The return of a component is created by the replacement."))
        self.replacement_id._warranty_replacement_check_coordinator()
        if REQUEST_FIELDS & names and any(line.replacement_id.state != 'draft' for line in self):
            raise UserError(_("The components can only be changed while the request is Draft."))
        if 'mrf_line_id' in names and any(line.replacement_id.state != 'approved' for line in self):
            raise UserError(_("The Material Request line is linked while the replacement is "
                              "Approved."))

    def _warranty_component_request_problems(self):
        """Submit: what the return needs. Odoo cannot receive a tracked part without its serial."""
        problems = []
        for line in self:
            product = line.product_id.display_name
            if float_compare(line.qty, 0.0, precision_rounding=line.product_id.uom_id.rounding) <= 0:
                problems.append(_("%s: enter a positive quantity.", product))
            if line.return_required:
                if line.product_id.tracking != 'none' and not line.old_lot_id:
                    problems.append(_("%s: select the old serial / lot, or untick Return Defective "
                                      "Part and enter the reason.", product))
                if line.product_id.tracking == 'serial' and line.qty != 1:
                    problems.append(_("%s: one line per serial number.", product))
            elif not (line.no_return_reason or '').strip():
                problems.append(_("%s: enter the Reason for No Return.", product))
        return problems

    def _warranty_component_completion_problems(self):
        problems = []
        for line in self.sudo():
            product = line.product_id.display_name
            if not line.mrf_line_id:
                problems.append(_("%s: link its Material Request line.", product))
            elif float_compare(line.used_qty, line.qty,
                               precision_rounding=line.product_id.uom_id.rounding) < 0:
                problems.append(_("%(product)s: %(used)s of %(qty)s recorded as used on the Material "
                                  "Request.", product=product, used=line.used_qty, qty=line.qty))
            if line.return_required and line.return_picking_id.state != 'done':
                problems.append(_("%(product)s: validate the return %(picking)s.", product=product,
                                  picking=line.return_picking_id.name or '-'))
        return problems

    def _warranty_component_history_text(self):
        self.ensure_one()
        line = self.sudo()
        return _("%(product)s x %(qty)s: old %(old)s, new %(new)s", product=line.product_id.display_name,
                 qty=line.qty, old=line.old_lot_id.name or line.old_part_details or '-',
                 new=', '.join(line.new_lot_ids.mapped('name')) or '-')
