from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

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
