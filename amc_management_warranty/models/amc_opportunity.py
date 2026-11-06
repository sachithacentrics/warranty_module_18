from odoo import Command, fields, models

from odoo.addons.amc_management.models.amc_contract import _marked


class AmcOpportunity(models.Model):
    _inherit = 'amc.opportunity'

    warranty_card_id = fields.Many2one('warranty.card', string='Warranty Card', readonly=True,
                                       copy=False, index=True)

    def action_create_contract(self):
        """Won: the contract of an opportunity from a warranty card covers the card's units
        (AMC-A06) and keeps the source card (AMC-C07)."""
        action = super().action_create_contract()
        card = self.warranty_card_id
        contract = self.contract_ids.sorted('id')[-1:]
        if card and contract and not contract.line_ids:
            _marked(contract.sudo()).write({
                'source_warranty_card_id': card.id,
                'start_date': card._amc_contract_start(),
                'line_ids': [Command.create({
                    'product_id': unit.product_id.id,
                    'serial_id': unit._amc_serial().id or False,
                    'warranty_unit_id': unit.id, 'quantity': 1.0,
                    'site_id': unit.current_site_id.id or False,
                }) for unit in card._amc_units()],
            })
        return action
