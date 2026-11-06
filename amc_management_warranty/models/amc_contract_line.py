from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .amc_contract import AMC_UNIT_STATES


class AmcContractLine(models.Model):
    _inherit = 'amc.contract.line'

    warranty_unit_id = fields.Many2one(
        'warranty.unit', string='Warranty Unit', index='btree_not_null',
        domain="[('warranty_card_id.partner_id', 'child_of', parent.commercial_partner_id), "
               "('company_id', '=', parent.company_id), ('state', 'in', %s)]"
               % (list(AMC_UNIT_STATES),),
        help="Unit warranty number of the covered equipment (SRS 2.15 Equipment / Warranty "
             "Units).")

    @api.onchange('warranty_unit_id')
    def _onchange_warranty_unit_id(self):
        unit = self.warranty_unit_id
        if unit:
            self.product_id = unit.product_id
            self.quantity = 1.0
            self.serial_id = unit._amc_serial()

    @api.constrains('warranty_unit_id', 'contract_id')
    def _check_warranty_unit(self):
        for line in self.filtered('warranty_unit_id'):
            unit = line.warranty_unit_id
            contract = line.contract_id
            if unit.company_id != contract.company_id:
                raise ValidationError(_("Warranty unit %s belongs to another company.",
                                        unit.name))
            if unit.warranty_card_id.partner_id.commercial_partner_id \
                    != contract.commercial_partner_id:
                raise ValidationError(_("Warranty unit %(unit)s belongs to another customer than "
                                        "%(contract)s.", unit=unit.name, contract=contract.name))
            if unit.state not in AMC_UNIT_STATES:
                raise ValidationError(_("Warranty unit %(unit)s is %(state)s: it cannot be "
                                        "covered by an AMC.", unit=unit.name,
                                        state=unit.state))
            if line.quantity != 1:
                raise ValidationError(_("A line with warranty unit %s covers quantity 1.",
                                        unit.name))
            others = self.search([
                ('id', '!=', line.id), ('warranty_unit_id', '=', unit.id),
                ('contract_id.state', 'not in', ('cancelled', 'closed', 'renewed'))])
            others = others.filtered(
                lambda other: other.contract_id != contract.renewal_of_id
                and other.contract_id.renewal_of_id != contract
                and other.contract_id != contract)
            if others:
                raise ValidationError(_("Warranty unit %(unit)s is already covered by "
                                        "%(contracts)s.", unit=unit.name,
                                        contracts=', '.join(others.contract_id.mapped('name'))))

    def _amc_renewal_values(self):
        values = super()._amc_renewal_values()
        values['warranty_unit_id'] = self.warranty_unit_id.id or False
        return values
