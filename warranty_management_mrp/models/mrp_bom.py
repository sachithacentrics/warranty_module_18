from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

# Warranty Component Role -> warranty.unit serial field (approved K2).
ROLE_FIELDS = {
    'indoor': 'indoor_serial_id',
    'outdoor': 'outdoor_serial_id',
}


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    def _warranty_role_lines(self):
        """{role: BoM line} of the Indoor / Outdoor Unit components of this Kit BoM."""
        self.ensure_one()
        if self.type != 'phantom':
            return {}
        return {line.warranty_component_role: line for line in self.bom_line_ids
                if line.warranty_component_role in ROLE_FIELDS}

    @api.constrains('type', 'product_qty', 'product_uom_id', 'bom_line_ids')
    def _check_warranty_component_roles(self):
        """Approved K2 rules: roles only on Kit BoMs; at most one Indoor and one Outdoor
        line; a serial-tracked component; exactly 1 unit per kit unit."""
        for bom in self:
            lines = bom.bom_line_ids.filtered(
                lambda line: line.warranty_component_role in ROLE_FIELDS)
            if not lines:
                continue
            if bom.type != 'phantom':
                raise ValidationError(_(
                    "Warranty Component Roles can only be used on Kit bills of materials "
                    "(%s).", bom.display_name))
            kit_qty = bom.product_uom_id._compute_quantity(
                bom.product_qty, bom.product_tmpl_id.uom_id)
            for role in ROLE_FIELDS:
                role_lines = lines.filtered(lambda line: line.warranty_component_role == role)
                if len(role_lines) > 1:
                    raise ValidationError(_(
                        "Kit %(bom)s can have only one %(role)s component.",
                        bom=bom.display_name,
                        role=dict(role_lines._fields['warranty_component_role']
                                  ._description_selection(self.env))[role]))
            for line in lines:
                if line.product_id.tracking != 'serial':
                    raise ValidationError(_(
                        "The %(role)s component %(product)s of kit %(bom)s must be tracked by "
                        "unique serial number.", role=line._warranty_role_label(),
                        product=line.product_id.display_name, bom=bom.display_name))
                qty = line.product_uom_id._compute_quantity(
                    line.product_qty, line.product_id.uom_id)
                if float_compare(qty, kit_qty, precision_digits=4) != 0:
                    raise ValidationError(_(
                        "The %(role)s component %(product)s of kit %(bom)s must have a "
                        "quantity of 1 per kit unit.", role=line._warranty_role_label(),
                        product=line.product_id.display_name, bom=bom.display_name))


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    warranty_component_role = fields.Selection([
        ('none', 'None'),
        ('indoor', 'Indoor Unit'),
        ('outdoor', 'Outdoor Unit'),
    ], string='Warranty Component Role', default='none',
        help="Kit BoM only: the delivered serial number of this component is the Indoor / "
             "Outdoor Serial No. of the warranty unit.")

    def _warranty_role_label(self):
        self.ensure_one()
        return dict(self._fields['warranty_component_role']._description_selection(
            self.env))[self.warranty_component_role]

    @api.constrains('warranty_component_role', 'product_id', 'product_qty', 'product_uom_id')
    def _check_warranty_component_role(self):
        self.bom_id._check_warranty_component_roles()
