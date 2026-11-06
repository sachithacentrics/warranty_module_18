from odoo import api, fields, models

from odoo.addons.amc_management.models.amc_contract import PROTECTED_FIELDS, _marked

# The source card is set by the conversion / auto-create only (never by the UI or RPC).
PROTECTED_FIELDS.add('source_warranty_card_id')

# Unit states that can be brought under an AMC (Replaced / Cancelled units are gone).
AMC_UNIT_STATES = ('active', 'expired', 'suspended')


class AmcContract(models.Model):
    _inherit = 'amc.contract'

    # AMC-A06 / C07: source warranty card (Convert to AMC / auto-create) and all cards of the
    # covered warranty units.
    source_warranty_card_id = fields.Many2one(
        'warranty.card', string='Source Warranty Card', readonly=True, copy=False, index=True,
        help="Warranty card this AMC was created from (auto-create or Convert to AMC).")
    warranty_card_ids = fields.Many2many(
        'warranty.card', 'amc_contract_warranty_card_rel', 'contract_id', 'card_id',
        string='Warranty Cards', compute='_compute_warranty_card_ids', store=True)
    warranty_card_count = fields.Integer(compute='_compute_warranty_card_ids')

    @api.depends('source_warranty_card_id', 'line_ids.warranty_unit_id.warranty_card_id')
    def _compute_warranty_card_ids(self):
        for contract in self:
            cards = contract.source_warranty_card_id \
                | contract.line_ids.warranty_unit_id.warranty_card_id
            contract.warranty_card_ids = cards
            contract.warranty_card_count = len(cards)

    def action_view_warranty_cards(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management.action_warranty_card')
        action.update({'domain': [('id', 'in', self.warranty_card_ids.ids)], 'context': {}})
        if len(self.warranty_card_ids) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')],
                           'res_id': self.warranty_card_ids.id})
        return action

    def _amc_create_renewal(self):
        renewal = super()._amc_create_renewal()
        if self.source_warranty_card_id:
            _marked(renewal.sudo()).write(
                {'source_warranty_card_id': self.source_warranty_card_id.id})
        return renewal
