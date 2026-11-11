from odoo import _, api, models
from odoo.exceptions import UserError

# Phase 5.3 (design rev. 2, section 6 / D-L): pickings, moves, RFQs and PO lines may be linked
# to a warranty Material Request only when it is approved through the warranty workflow; moves
# and PO lines never belong to Not Covered lines (Figure 7 D2). Checked also in superuser mode:
# the vendor creates the RFQ lines with sudo().


def _check_requisitions(requisitions):
    requisitions.sudo()._warranty_check_release()


def _check_requisition_lines(lines):
    """Figure 7 D2: Covered lines are released by the request's own approval; Not Covered lines
    are never moved or bought through the request (only their parts quotation delivers them)."""
    _check_requisitions(lines.requisition_id)
    not_covered = lines.sudo().filtered(
        lambda line: line.is_warranty_mrf and line.coverage_type == 'not_covered')
    if not_covered:
        raise UserError(_("%(products)s of %(mrf)s: Not Covered materials are delivered by the "
                          "parts quotation only, never by a transfer or purchase order of the "
                          "Material Request.",
                          products=', '.join(not_covered.mapped('product_id.display_name')),
                          mrf=', '.join(not_covered.requisition_id.mapped('name'))))


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Phase 5.6: unused returns (Return Unused, also of pre-matrix requests whose parts were
    # issued) issue nothing; they are checked by their own rules (store validation, quantities,
    # serials) and are not subject to the release guard.
    def _warranty_guarded(self):
        return self.filtered(lambda picking: not picking.warranty_unused_return)

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        _check_requisitions(pickings._warranty_guarded().custom_requisition_id)
        return pickings

    def write(self, vals):
        result = super().write(vals)
        if vals.get('custom_requisition_id'):
            _check_requisitions(self._warranty_guarded().custom_requisition_id)
        return result

    def button_validate(self):
        requisitions = self._warranty_guarded().sudo().custom_requisition_id.filtered(
            'is_warranty_mrf')
        for mrf in requisitions:
            if mrf.state not in ('approve', 'stock', 'receive') or not mrf.approval_round:
                raise UserError(_("Picking of Material Request %s: the request is not approved "
                                  "through the warranty approval workflow.", mrf.name))
        return super().button_validate()


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        _check_requisition_lines(moves.custom_requisition_line_id)
        return moves

    def write(self, vals):
        result = super().write(vals)
        if vals.get('custom_requisition_line_id'):
            _check_requisition_lines(self.custom_requisition_line_id)
        return result


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        _check_requisitions(orders.custom_requisition_id)
        return orders

    def write(self, vals):
        result = super().write(vals)
        if vals.get('custom_requisition_id'):
            _check_requisitions(self.custom_requisition_id)
        return result


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        _check_requisition_lines(lines.custom_requisition_line_id)
        return lines

    def write(self, vals):
        result = super().write(vals)
        if vals.get('custom_requisition_line_id'):
            _check_requisition_lines(self.custom_requisition_line_id)
        return result
