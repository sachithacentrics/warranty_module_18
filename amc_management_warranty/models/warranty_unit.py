from odoo import _, fields, models


class WarrantyUnit(models.Model):
    _inherit = 'warranty.unit'

    # AMC-A06: unit -> AMC contracts covering it (the card has the same smart button).
    amc_contract_count = fields.Integer(string='AMC', compute='_compute_amc_contract_count')

    def _compute_amc_contract_count(self):
        # sudo: count only, as the card's AMC button; the contracts open with the user's rights.
        lines = self.env['amc.contract.line'].sudo().search(
            [('warranty_unit_id', 'in', self.ids)])
        for unit in self:
            unit.amc_contract_count = len(lines.filtered(
                lambda line: line.warranty_unit_id == unit).contract_id)

    def action_view_amc_contracts(self):
        self.ensure_one()
        contracts = self.env['amc.contract'].search([('line_ids.warranty_unit_id', '=', self.id)])
        action = {'type': 'ir.actions.act_window', 'name': _("AMC Contracts"),
                  'res_model': 'amc.contract', 'view_mode': 'list,form',
                  'domain': [('id', 'in', contracts.ids)]}
        if len(contracts) == 1:
            action.update({'view_mode': 'form', 'res_id': contracts.id})
        return action

    def _amc_serial(self):
        """The unit serial of the unit's own product (kits: the main serial), else none."""
        self.ensure_one()
        return self.serial_ids.filtered(lambda lot: lot.product_id == self.product_id)[:1]
