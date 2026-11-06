from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..models.warranty_vendor_claim import PARTNER_SOURCES


class WarrantyVendorClaimWizard(models.TransientModel):
    """Create Vendor Claim (V-3 / V-5 / C1 / C2): eligible consumed lines of a case, job or
    request, the proposed partner and an auditable override."""
    _name = 'warranty.vendor.claim.wizard'
    _description = 'Create Warranty Vendor Claim'

    case_id = fields.Many2one('warranty.case', required=True, readonly=True)
    line_ids = fields.One2many('warranty.vendor.claim.wizard.line', 'wizard_id')
    partner_id = fields.Many2one('res.partner', string='Vendor / Manufacturer')
    proposed_partner_id = fields.Many2one('res.partner', string='Proposed Partner', readonly=True)
    partner_source = fields.Selection(PARTNER_SOURCES, string='Partner Basis', readonly=True)
    proposal_note = fields.Text(readonly=True)
    partner_override_reason = fields.Text(string='Override Reason')
    claim_type = fields.Selection([('vendor', 'Vendor'), ('manufacturer', 'Manufacturer')],
                                  default='vendor', required=True)
    failure_description = fields.Text(string='Failure Description')
    previous_claim_id = fields.Many2one('warranty.vendor.claim', string='Re-claim of',
                                        domain="[('case_id', '=', case_id)]")

    def _propose_partner(self):
        selected = self.line_ids.filtered('selected')
        proposals = [(row.mrf_line_id._warranty_claim_partner_proposal(), row)
                     for row in selected]
        partners = {partner for (partner, _source), _row in proposals if partner}
        partner, source = proposals[0][0] if proposals else (self.env['res.partner'], False)
        note = False
        if len(partners) > 1:
            note = _("The selected parts have different responsible partners (%s): one claim "
                     "per partner – deselect the parts of the other partners.",
                     ', '.join(sorted(p.display_name for p in partners)))
        self.write({'proposed_partner_id': partner.id, 'partner_source': source,
                    'partner_id': self.partner_id.id or partner.id, 'proposal_note': note,
                    'claim_type': 'manufacturer' if source == 'manufacturer' else 'vendor'})

    def action_refresh_proposal(self):
        self.partner_id = False
        self._propose_partner()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def action_apply(self):
        self.ensure_one()
        Claim = self.env['warranty.vendor.claim']
        rows = self.line_ids.filtered(lambda row: row.selected and row.qty > 0)
        if not rows:
            raise UserError(_("Select at least one part to claim."))
        if not self.partner_id:
            raise UserError(_("Select the responsible vendor / manufacturer."))
        proposals = {row.mrf_line_id._warranty_claim_partner_proposal()[0] for row in rows} - \
            {self.env['res.partner']}
        if (len(proposals) > 1 or (proposals and self.partner_id not in proposals)) \
                and not (self.partner_override_reason or '').strip():
            raise UserError(_("The selected partner differs from the proposed responsible "
                              "partner(s) %s; enter the override reason (audit).",
                              ', '.join(sorted(p.display_name for p in proposals))))
        if not Claim._is_coordinator():
            raise AccessError(_("Only Service Coordinators (Helpdesk users) and Requisition users "
                                "of the company create vendor claims."))
        source = self.partner_source if self.partner_id == self.proposed_partner_id \
            else 'manual'
        claim = Claim.sudo().create({
            'company_id': self.case_id.company_id.id,
            'case_id': self.case_id.id,
            'partner_id': self.partner_id.id,
            'claim_type': self.claim_type,
            'proposed_partner_id': self.proposed_partner_id.id,
            'partner_source': source,
            'partner_override_reason': self.partner_override_reason,
            'failure_description': self.failure_description,
            'previous_claim_id': self.previous_claim_id.id,
            'line_ids': [(0, 0, {'mrf_line_id': row.mrf_line_id.id, 'qty': row.qty,
                                 'lot_ids': [(6, 0, row.lot_ids.ids)]}) for row in rows],
        })
        claim.with_env(self.env)._check_creator()
        return {'type': 'ir.actions.act_window', 'res_model': claim._name, 'res_id': claim.id,
                'view_mode': 'form', 'views': [(False, 'form')]}


class WarrantyVendorClaimWizardLine(models.TransientModel):
    _name = 'warranty.vendor.claim.wizard.line'
    _description = 'Create Warranty Vendor Claim Line'

    wizard_id = fields.Many2one('warranty.vendor.claim.wizard', required=True,
                                ondelete='cascade')
    mrf_line_id = fields.Many2one('material.purchase.requisition.line', required=True,
                                  readonly=True)
    requisition_id = fields.Many2one(related='mrf_line_id.requisition_id')
    product_id = fields.Many2one(related='mrf_line_id.product_id')
    tracking = fields.Selection(related='mrf_line_id.product_id.tracking')
    selected = fields.Boolean(string='Claim', default=True)
    qty = fields.Float(string='Quantity', digits='Product Unit of Measure')
    max_qty = fields.Float(string='Claimable', compute='_compute_info',
                           digits='Product Unit of Measure')
    currency_id = fields.Many2one(related='mrf_line_id.currency_id')
    unit_cost = fields.Monetary(string='Actual Unit Cost', compute='_compute_info')
    amount = fields.Monetary(string='Claim Amount', compute='_compute_info')
    bucket = fields.Char(string='Coverage', compute='_compute_info')
    proposal = fields.Char(string='Proposed Partner', compute='_compute_info')
    allowed_lot_ids = fields.Many2many('stock.lot', compute='_compute_info')
    lot_ids = fields.Many2many('stock.lot', string='Serial / Lot Numbers',
                               domain="[('id', 'in', allowed_lot_ids)]")

    @api.depends('mrf_line_id', 'qty')
    def _compute_info(self):
        sources = dict(PARTNER_SOURCES)
        for row in self:
            line = row.mrf_line_id.sudo()
            unit = line.actual_cost / line.used_qty if line.used_qty else 0.0
            partner, source = line._warranty_claim_partner_proposal()
            row.update({
                'max_qty': line._warranty_claimable_qty(),
                'unit_cost': unit,
                'amount': row.qty * unit,
                'bucket': dict(line._fields['cost_bucket'].selection).get(line.cost_bucket),
                'proposal': '%s (%s)' % (partner.display_name, sources.get(source))
                if partner else _("none – select manually"),
                'allowed_lot_ids': line._warranty_claimable_lots(),
            })


class WarrantyVendorClaimReasonWizard(models.TransientModel):
    _name = 'warranty.vendor.claim.reason.wizard'
    _description = 'Warranty Vendor Claim Reason'

    claim_id = fields.Many2one('warranty.vendor.claim', required=True)
    recovery_id = fields.Many2one('warranty.vendor.claim.recovery')
    action = fields.Selection([('reject', 'Reject'), ('reset', 'Reset to Draft'),
                               ('cancel', 'Cancel'), ('close', 'Close'),
                               ('remove', 'Remove Allocation')], required=True)
    outstanding_amount = fields.Monetary(related='claim_id.outstanding_amount')
    currency_id = fields.Many2one(related='claim_id.currency_id')
    reason = fields.Text(string='Reason')

    def action_apply(self):
        self.ensure_one()
        claim = self.claim_id
        if self.action == 'reject':
            claim._warranty_reject(self.reason)
        elif self.action == 'reset':
            claim._warranty_reset_draft(self.reason)
        elif self.action == 'cancel':
            claim._warranty_cancel(self.reason)
        elif self.action == 'close':
            claim._warranty_close(self.reason)
        else:
            self.recovery_id._warranty_remove(self.reason)
        return {'type': 'ir.actions.act_window_close'}


class WarrantyVendorClaimResponseWizard(models.TransientModel):
    _name = 'warranty.vendor.claim.response.wizard'
    _description = 'Warranty Vendor Claim Response'

    claim_id = fields.Many2one('warranty.vendor.claim', required=True)
    currency_id = fields.Many2one(related='claim_id.currency_id')
    vendor_reference = fields.Char(string='Vendor Reference')
    response_date = fields.Date(default=fields.Date.context_today, required=True)
    correction = fields.Boolean(compute='_compute_correction')
    correction_reason = fields.Text(string='Correction Reason')
    line_ids = fields.One2many('warranty.vendor.claim.response.wizard.line', 'wizard_id')

    @api.depends('claim_id.state')
    def _compute_correction(self):
        for wizard in self:
            wizard.correction = wizard.claim_id.state == 'answered'

    def action_accept_all(self):
        for row in self.line_ids:
            row.accepted_amount = row.claimed_amount
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def action_reject_all(self):
        self.line_ids.accepted_amount = 0.0
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def action_apply(self):
        self.ensure_one()
        self.claim_id._warranty_record_response(
            {row.claim_line_id: (row.accepted_amount, row.vendor_reason) for row in self.line_ids},
            reference=self.vendor_reference, date=self.response_date,
            reason=self.correction_reason)
        return {'type': 'ir.actions.act_window_close'}


class WarrantyVendorClaimResponseWizardLine(models.TransientModel):
    _name = 'warranty.vendor.claim.response.wizard.line'
    _description = 'Warranty Vendor Claim Response Line'

    wizard_id = fields.Many2one('warranty.vendor.claim.response.wizard', required=True,
                                ondelete='cascade')
    claim_line_id = fields.Many2one('warranty.vendor.claim.line', required=True, readonly=True)
    product_id = fields.Many2one(related='claim_line_id.product_id')
    qty = fields.Float(related='claim_line_id.qty')
    currency_id = fields.Many2one(related='claim_line_id.currency_id')
    claimed_amount = fields.Monetary(related='claim_line_id.claimed_amount')
    accepted_amount = fields.Monetary(string='Accepted')
    vendor_reason = fields.Text(string='Vendor Comment / Reason')


class WarrantyVendorClaimAllocateWizard(models.TransientModel):
    _name = 'warranty.vendor.claim.allocate.wizard'
    _description = 'Allocate Vendor Credit Note to Claim'

    claim_id = fields.Many2one('warranty.vendor.claim', required=True)
    company_id = fields.Many2one(related='claim_id.company_id')
    currency_id = fields.Many2one(related='claim_id.currency_id')
    commercial_partner_id = fields.Many2one(related='claim_id.partner_id.commercial_partner_id')
    move_id = fields.Many2one(
        'account.move', string='Vendor Credit Note', required=True,
        domain="[('move_type', '=', 'in_refund'), ('state', '=', 'posted'), "
               "('company_id', '=', company_id), "
               "('commercial_partner_id', '=', commercial_partner_id)]")
    move_available = fields.Monetary(string='Available on Credit Note',
                                     compute='_compute_available')
    claim_available = fields.Monetary(string='Accepted, not yet Allocated',
                                      compute='_compute_available')
    claim_line_id = fields.Many2one('warranty.vendor.claim.line', string='Claim Line',
                                    required=True, domain="[('claim_id', '=', claim_id)]",
                                    default=lambda self: self._default_claim_line())
    line_available = fields.Monetary(string='Accepted, not yet Allocated (line)',
                                     compute='_compute_available')
    amount = fields.Monetary(string='Amount to Allocate', required=True)
    note = fields.Text()

    @api.model
    def _default_claim_line(self):
        claim = self.env['warranty.vendor.claim'].browse(self.env.context.get('default_claim_id'))
        return claim.line_ids.filtered(
            lambda line: line._available_to_allocate() > 0)[:1] or claim.line_ids[:1]

    @api.depends('move_id', 'claim_id', 'claim_line_id')
    def _compute_available(self):
        for wizard in self:
            wizard.move_available = wizard.move_id._warranty_claim_available() \
                if wizard.move_id else 0.0
            wizard.claim_available = wizard.claim_id._available_to_allocate()
            wizard.line_available = wizard.claim_line_id._available_to_allocate() \
                if wizard.claim_line_id else 0.0

    @api.onchange('move_id', 'claim_line_id')
    def _onchange_move_id(self):
        if self.move_id:
            self.amount = min(self.move_available, self.line_available)

    def action_apply(self):
        self.ensure_one()
        self.claim_id._warranty_allocate(self.move_id, self.amount, self.note,
                                         line=self.claim_line_id)
        return {'type': 'ir.actions.act_window_close'}
