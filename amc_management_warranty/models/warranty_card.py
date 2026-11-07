import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import Command, _, fields, models
from odoo.exceptions import UserError

from odoo.addons.amc_management.models.amc_contract import _marked

from .amc_contract import AMC_UNIT_STATES

_logger = logging.getLogger(__name__)

# Cards whose owner may buy an AMC (Convert to AMC, AMC-A07).
CONVERTIBLE_CARD_STATES = ('confirmed', 'expired')


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    amc_contract_ids = fields.One2many('amc.contract', 'source_warranty_card_id',
                                       string='AMC Contracts', readonly=True)
    amc_opportunity_ids = fields.One2many('amc.opportunity', 'warranty_card_id',
                                          string='AMC Opportunities', readonly=True)
    amc_count = fields.Integer(string='AMC', compute='_compute_amc_count')
    amc_enabled = fields.Boolean(related='company_id.amc_enabled')

    def _compute_amc_count(self):
        contracts = self.env['amc.contract'].sudo()
        for card in self:
            linked = contracts.search([('warranty_card_ids', 'in', card.ids)])
            card.amc_count = len(linked | card.sudo().amc_contract_ids) \
                + len(card.sudo().amc_opportunity_ids)

    # ------------------------------------------------------------------ AMC-A03 / A04
    def action_confirm_warranty(self):
        result = super().action_confirm_warranty()
        for card in self.filtered(lambda c: c.state == 'confirmed'):
            card._amc_auto_create()
        return result

    def _amc_auto_create(self):
        """Optional draft AMC record after confirmation (SRS 2.12 / 7 / 14): never activated
        here, never twice for a card, and never blocking the warranty confirmation."""
        self.ensure_one()
        mode = self.company_id.amc_auto_create_mode
        if not self.company_id.amc_enabled or mode == 'none' or self.sudo().amc_contract_ids or self.sudo().amc_opportunity_ids:
            return False
        try:
            with self.env.cr.savepoint():
                # sudo: the warranty user may have no AMC role; the draft is reviewed in AMC.
                if mode == 'opportunity':
                    record = self.sudo()._amc_create_opportunity()
                else:
                    record = self.sudo()._amc_create_contract(origin=_("warranty confirmation"))
        except Exception as error:  # the warranty confirmation must not fail because of AMC
            _logger.warning("AMC auto-create failed for warranty card %s: %s", self.name, error)
            self._message_log(body=Markup('<p>%s</p>') % _(
                "AMC auto-create (%(mode)s) failed: %(error)s", mode=mode, error=error))
            return False
        self._message_log(body=Markup('<p>%s</p>') % _(
            "Draft AMC %(record)s created after warranty confirmation (not active: the AMC "
            "needs its own quotation / payment).", record=record.name))
        return record

    def _amc_units(self):
        self.ensure_one()
        return self.unit_warranty_ids.filtered(lambda unit: unit.state in AMC_UNIT_STATES)

    def _amc_create_opportunity(self):
        self.ensure_one()
        return self.env['amc.opportunity'].create({
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'warranty_card_id': self.id,
            'expected_quantity': len(self._amc_units()) or 1.0,
            'description': _("From warranty card %(card)s (%(units)s).", card=self.name,
                             units=', '.join(self._amc_units().mapped('name'))),
        })

    def _amc_contract_start(self):
        """Continuity (AMC-C07): the AMC starts the day after the warranty end when that day is
        still ahead; otherwise the activation date of the AMC is used."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.warranty_end_date and self.warranty_end_date + timedelta(days=1) >= today:
            return self.warranty_end_date + timedelta(days=1)
        return False

    def _amc_create_contract(self, origin, plan=None):
        self.ensure_one()
        units = self._amc_units()
        if not units:
            raise UserError(_("Warranty card %s has no unit that can be covered by an AMC.",
                              self.name))
        plan = plan or self.company_id.amc_default_plan_id
        contract = _marked(self.env['amc.contract']).create({
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'plan_id': plan.id or False,
            'start_date': self._amc_contract_start(),
            'source_warranty_card_id': self.id,
            'line_ids': [Command.create({
                'product_id': unit.product_id.id,
                'serial_id': unit._amc_serial().id or False,
                'warranty_unit_id': unit.id,
                'quantity': 1.0,
                'site_id': unit.current_site_id.id or False,
            }) for unit in units],
        }).with_env(self.env)
        contract._amc_log(_("Draft AMC created from warranty card %(card)s (%(origin)s).",
                            card=self.name, origin=origin))
        return contract

    def action_convert_to_amc(self):
        """Convert to AMC (SRS 12 #12, AMC-A07): a Draft AMC contract linked to this card and its
        units; AMC eligibility applies after the warranty (A08). An open AMC of the card is
        opened instead of creating a second one."""
        self.ensure_one()
        if not self.env.user.has_group('amc_management.amc_management_group_user'):
            raise UserError(_("Only AMC users can convert warranty cards to AMC."))
        if self.state not in CONVERTIBLE_CARD_STATES:
            raise UserError(_("Only Confirmed or Expired warranty cards can be converted to AMC."))
        self.company_id._amc_check_enabled()
        open_contracts = self.amc_contract_ids.filtered(
            lambda c: c.state not in ('cancelled', 'closed', 'renewed'))
        if open_contracts:
            return open_contracts[:1]._amc_open()
        contract = self.sudo()._amc_create_contract(origin=_("Convert to AMC by %s",
                                                             self.env.user.name))
        self._message_log(body=Markup('<p>%s</p>') % _("Converted to AMC: %s (Draft).",
                                                       contract.name))
        return contract.with_env(self.env)._amc_open()

    def action_view_amc(self):
        self.ensure_one()
        contracts = self.env['amc.contract'].search(
            ['|', ('source_warranty_card_id', '=', self.id),
             ('warranty_card_ids', 'in', self.ids)])
        if not contracts and self.amc_opportunity_ids:
            return {'type': 'ir.actions.act_window', 'name': _("AMC Opportunities"),
                    'res_model': 'amc.opportunity', 'view_mode': 'list,form',
                    'domain': [('warranty_card_id', '=', self.id)]}
        action = {'type': 'ir.actions.act_window', 'name': _("AMC Contracts"),
                  'res_model': 'amc.contract', 'view_mode': 'list,form',
                  'domain': [('id', 'in', contracts.ids)]}
        if len(contracts) == 1:
            action.update({'view_mode': 'form', 'res_id': contracts.id})
        return action

    # ------------------------------------------------------------------ SRS 14 expiry offer
    def _warranty_apply_expiry(self, today):
        was_expired = self.state == 'expired'
        result = super()._warranty_apply_expiry(today)
        company = self.company_id
        if not was_expired and self.state == 'expired' and company.amc_enabled \
                and company.amc_offer_on_warranty_expiry and not self.sudo().amc_contract_ids:
            # Same recipients as the other warranty review activities of the card.
            for user in self._get_service_alert_users() or self.env.user:
                self.sudo().activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=_("Offer an AMC: warranty %s expired", self.name),
                    note=_("The warranty of %(customer)s expired: offer an AMC (Convert to "
                           "AMC).", customer=self.partner_id.display_name))
        return result
