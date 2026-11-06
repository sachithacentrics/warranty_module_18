from markupsafe import Markup

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError

# Part 9, SRS 12 control pattern. Void is not here: Q7 (separate Voided status) waits for approval.
ACTION_TYPES = [
    ('suspend', 'Suspend'),
    ('reactivate', 'Reactivate'),
    ('cancel', 'Return / Refund Cancellation'),
    ('correct_serial', 'Correct Serial'),
    ('correct_customer', 'Correct Customer'),
    ('correct_usage', 'Correct Usage Reading'),
    ('relocate', 'Relocate Unit'),
    ('transfer', 'Transfer Ownership'),
    ('extend', 'Extend Warranty'),
]
ACTION_STATES = [
    ('pending', 'Waiting for Approval'),
    ('done', 'Approved and Applied'),
    ('rejected', 'Rejected'),
]
# SRS page 59.
SUSPEND_REASONS = [
    ('unauthorized_repair', 'Unauthorized repair'),
    ('physical_damage', 'Physical damage'),
    ('tampering', 'Customer tampering'),
    ('incorrect_installation', 'Incorrect installation'),
    ('non_payment', 'Non-payment'),
    ('misuse', 'Misuse'),
    ('external_service', 'Service done by external party'),
    ('other', 'Other'),
]
EXTENSION_TYPES = [
    ('paid', 'Paid'),
    ('free', 'Free / Goodwill'),
]
LIVE_UNIT_EXCLUDED = ('replaced', 'cancelled')


class WarrantyCardAction(models.Model):
    """One controlled exception on a warranty card (SRS 2.13, 12, 16): request, approval by another
    user, execution and before / after values. Written by system code only, never deleted."""
    _name = 'warranty.card.action'
    _description = 'Warranty Controlled Action'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _mail_post_access = 'read'
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False, default='New')
    action_type = fields.Selection(ACTION_TYPES, string='Action', required=True, readonly=True)
    state = fields.Selection(ACTION_STATES, string='Status', default='pending', required=True,
                             readonly=True, index=True, copy=False)
    card_id = fields.Many2one('warranty.card', string='Warranty Card', required=True, readonly=True,
                              ondelete='restrict', index=True)
    company_id = fields.Many2one(related='card_id.company_id', string='Company', store=True,
                                 index=True)
    unit_ids = fields.Many2many('warranty.unit', 'warranty_card_action_unit_rel', 'action_id',
                                'unit_id', string='Units', readonly=True)
    reason_code = fields.Selection(SUSPEND_REASONS, string='Suspension Reason', readonly=True)
    reason = fields.Text(string='Reason', required=True, readonly=True)
    effective_date = fields.Date(string='Effective Date', readonly=True)
    attachment_ids = fields.Many2many('ir.attachment', 'warranty_card_action_attachment_rel',
                                      'action_id', 'attachment_id', string='Evidence',
                                      readonly=True)
    requested_by_id = fields.Many2one('res.users', string='Requested By', required=True,
                                      readonly=True, default=lambda self: self.env.user)
    request_date = fields.Datetime(string='Requested On', required=True, readonly=True,
                                   default=fields.Datetime.now)
    decided_by_id = fields.Many2one('res.users', string='Decided By', readonly=True, copy=False)
    decision_date = fields.Datetime(string='Decided On', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False)
    old_value = fields.Text(string='Previous Value', readonly=True, copy=False)
    new_value = fields.Text(string='New Value', readonly=True, copy=False)
    open_work_note = fields.Text(
        string='Open Work on the Card', readonly=True, copy=False,
        help="Open cases, jobs and replacements when the action was requested. The action never "
             "changes them.")
    # What the action changes, by type.
    old_partner_id = fields.Many2one('res.partner', string='Previous Owner', readonly=True)
    new_partner_id = fields.Many2one('res.partner', string='New Owner', readonly=True)
    new_site_id = fields.Many2one('res.partner', string='New Site', readonly=True)
    old_serial_id = fields.Many2one('stock.lot', string='Wrong Serial', readonly=True)
    new_serial_id = fields.Many2one('stock.lot', string='Correct Serial', readonly=True)
    new_usage = fields.Float(string='Corrected Usage Reading', readonly=True)
    new_end_date = fields.Date(string='New End Date', readonly=True)
    extension_type = fields.Selection(EXTENSION_TYPES, string='Extension Type', readonly=True)
    source_picking_id = fields.Many2one('stock.picking', string='Return', readonly=True)
    source_move_id = fields.Many2one('account.move', string='Invoice / Credit Note', readonly=True)
    source_order_id = fields.Many2one('sale.order', string='Quotation / Sales Order', readonly=True)
    can_decide = fields.Boolean(compute='_compute_can_decide')

    def init(self):
        # One open action per card, also under concurrent requests.
        tools.create_unique_index(self.env.cr, 'warranty_card_action_one_pending',
                                  self._table, ['card_id', "(CASE WHEN state = 'pending' THEN 1 END)"])

    @api.depends_context('uid')
    @api.depends('state', 'requested_by_id')
    def _compute_can_decide(self):
        for action in self:
            action.can_decide = action.state == 'pending' \
                and action.requested_by_id != self.env.user \
                and self.env.user in action.sudo().company_id.warranty_exception_approver_ids

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('warranty.card.action') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if self.filtered(lambda action: action.state != 'pending') and any(
                not name.startswith(('message_', 'activity_')) for name in vals):
            raise UserError(_("A decided controlled action cannot be changed."))
        return super().write(vals)

    def unlink(self):
        raise UserError(_("Controlled actions are kept for audit and cannot be deleted."))

    # ------------------------------------------------------------------ decisions
    def _warranty_check_decider(self):
        self.ensure_one()
        if self.state != 'pending':
            raise UserError(_("%s has already been decided.", self.name))
        if self.requested_by_id == self.env.user:
            raise AccessError(_("You cannot decide your own request %s.", self.name))
        if self.env.user not in self.sudo().company_id.warranty_exception_approver_ids:
            raise AccessError(_("Only the Warranty Exception Approvers of %s can decide controlled "
                                "actions.", self.company_id.name))

    def action_approve(self):
        """Validations run again: the card may have changed since the request (SRS 12 step 3)."""
        for action in self:
            action._warranty_check_decider()
            # sudo: approvers need no write access; the checks above decide who may run this.
            record = action.sudo()
            record._warranty_raise_problems()
            old_value, new_value = getattr(record, '_warranty_execute_%s' % record.action_type)()
            record.write({'state': 'done', 'decided_by_id': self.env.uid,
                          'decision_date': fields.Datetime.now(),
                          'old_value': old_value, 'new_value': new_value})
            record._warranty_finish(_("approved by %s", self.env.user.name))
        return True

    def _warranty_reject(self, reason):
        self.ensure_one()
        self._warranty_check_decider()
        if not (reason or '').strip():
            raise UserError(_("Give the rejection reason."))
        record = self.sudo()
        record.write({'state': 'rejected', 'decided_by_id': self.env.uid,
                      'decision_date': fields.Datetime.now(), 'rejection_reason': reason})
        record._warranty_finish(_("rejected by %(user)s: %(reason)s", user=self.env.user.name,
                                  reason=reason))

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._warranty_check_decider()
        return {
            'type': 'ir.actions.act_window', 'name': _("Reject %s", self.name),
            'res_model': 'warranty.card.action.reject.wizard', 'view_mode': 'form',
            'target': 'new', 'context': {'default_action_id': self.id},
        }

    def _warranty_finish(self, decision):
        self.ensure_one()
        self.activity_unlink(['mail.mail_activity_data_todo'])
        label = dict(ACTION_TYPES)[self.action_type]
        changes = Markup('<br/>%s') % _("Before: %(old)s. After: %(new)s.", old=self.old_value,
                                        new=self.new_value) if self.state == 'done' else ''
        self.card_id._message_log(
            body=Markup('<p>%s%s<br/>%s</p>') % (
                _("%(action)s %(ref)s %(decision)s.", action=label, ref=self.name,
                  decision=decision), changes, _("Reason: %s", self.reason)),
            author_id=self.env.user.partner_id.id)

    # ------------------------------------------------------------------ validations
    def _warranty_raise_problems(self):
        self.ensure_one()
        problems = self._warranty_common_problems() + getattr(
            self, '_warranty_problems_%s' % self.action_type)()
        if problems:
            raise UserError(_("%(ref)s cannot be applied:\n%(problems)s", ref=self.card_id.name,
                              problems='\n'.join(problems)))

    def _warranty_common_problems(self):
        card = self.card_id
        problems = []
        if self.unit_ids.warranty_card_id - card:
            problems.append(_("Every unit must belong to warranty card %s.", card.name))
        if not self.unit_ids:
            problems.append(_("No unit is available for this action."))
        if not (self.reason or '').strip():
            problems.append(_("Give the reason."))
        return problems

    def _warranty_live_units_problem(self):
        dead = self.unit_ids.filtered(lambda unit: unit.state in LIVE_UNIT_EXCLUDED)
        return [_("Units %s are Replaced or Cancelled.", ', '.join(dead.mapped('name')))] if dead \
            else []

    def _warranty_open_work_problem(self):
        work = self.card_id._warranty_open_work()
        return [_("Finish the open work on this card first: %s.", ', '.join(work))] if work else []

    def _warranty_problems_suspend(self):
        problems = []
        if self.card_id.state != 'confirmed':
            problems.append(_("Only Confirmed warranty cards can be suspended."))
        wrong = self.unit_ids.filtered(lambda unit: unit.state != 'active')
        if wrong:
            problems.append(_("Only Active units can be suspended: %s.",
                              ', '.join(wrong.mapped('name'))))
        if not self.reason_code:
            problems.append(_("Select the suspension reason."))
        if self.company_id.warranty_exception_evidence_required and not self.attachment_ids:
            problems.append(_("Attach the evidence."))
        return problems

    def _warranty_problems_reactivate(self):
        wrong = self.unit_ids.filtered(lambda unit: unit.state != 'suspended')
        return [_("Only Suspended units can be reactivated: %s.",
                  ', '.join(wrong.mapped('name')))] if wrong else []

    def _warranty_problems_cancel(self):
        problems = self._warranty_live_units_problem()
        if self.card_id.state not in ('confirmed', 'suspended', 'expired'):
            problems.append(_("Only Confirmed, Suspended or Expired warranty cards can be "
                              "cancelled."))
        return problems + self._warranty_return_source_problems()

    def _warranty_return_source_problems(self):
        """SRS 12 #14: the cancellation follows a validated return or a posted credit note of these
        units; nothing else cancels a warranty."""
        picking, refund = self.source_picking_id, self.source_move_id
        if not picking and not refund:
            return [_("Select the validated return or the posted credit note.")]
        problems = []
        if picking:
            returned = picking.move_ids.filtered(
                lambda move: move.state == 'done').origin_returned_move_id
            wrong = self.unit_ids.filtered(
                lambda unit: unit.stock_move_line_id.move_id not in returned)
            if picking.state != 'done' or picking.picking_type_code != 'incoming' or wrong:
                problems.append(_("%s is not a validated return of these units.", picking.name))
        if refund:
            lines = refund.invoice_line_ids.sale_line_ids
            wrong = self.unit_ids.filtered(lambda unit: unit.sale_order_line_id not in lines)
            if refund.state != 'posted' or refund.move_type != 'out_refund' or wrong:
                problems.append(_("%s is not a posted credit note of these units.",
                                  refund.display_name))
        return problems

    def _warranty_problems_correct_serial(self):
        problems = self._warranty_live_units_problem() + self._warranty_open_work_problem()
        unit, old, new = self.unit_ids, self.old_serial_id, self.new_serial_id
        if len(unit) != 1 or self.card_id.state not in ('confirmed', 'suspended', 'expired'):
            return problems + [_("Select one unit of a Confirmed, Suspended or Expired card.")]
        if not old or not new or old not in unit.serial_ids or new in unit.serial_ids:
            return problems + [_("Select a serial of unit %s and a different correct serial.",
                                 unit.name)]
        if new.product_id != unit.product_id or new.company_id not in (self.company_id,
                                                                       self.env['res.company']):
            problems.append(_("Serial %(serial)s is not a serial of %(product)s in this company.",
                              serial=new.name, product=unit.product_id.display_name))
        other = unit._warranty_serial_holder(new)
        if other:
            problems.append(_("Serial %(serial)s is already on warranty unit %(unit)s.",
                              serial=new.name, unit=other[0].name))
        return problems

    def _warranty_owner_problems(self):
        partner = self.new_partner_id
        problems = self._warranty_open_work_problem()
        if not partner or partner.commercial_partner_id \
                == self.card_id.partner_id.commercial_partner_id:
            problems.append(_("Select a different customer."))
        elif self.new_site_id and self.new_site_id.commercial_partner_id \
                != partner.commercial_partner_id:
            problems.append(_("The site must be an address of %s.", partner.display_name))
        return problems

    def _warranty_problems_correct_customer(self):
        problems = self._warranty_owner_problems()
        if self.card_id.state not in ('confirmed', 'suspended', 'expired'):
            problems.append(_("Only Confirmed, Suspended or Expired warranty cards are corrected "
                              "here."))
        return problems

    def _warranty_problems_correct_usage(self):
        problems = self._warranty_live_units_problem()
        if self.card_id.warranty_basis != 'usage' or len(self.unit_ids) != 1:
            problems.append(_("Select one unit of a usage-based warranty."))
        if self.new_usage < 0:
            problems.append(_("The usage reading cannot be negative."))
        return problems

    def _warranty_problems_relocate(self):
        problems = self._warranty_live_units_problem()
        if not self.company_id.warranty_relocation_allowed:
            problems.append(_("Product relocation is not allowed in this company."))
        if self.card_id.state not in ('confirmed', 'suspended', 'expired'):
            problems.append(_("Only Confirmed, Suspended or Expired warranty cards can be "
                              "relocated."))
        site = self.new_site_id
        if not site or site.commercial_partner_id != self.card_id.partner_id.commercial_partner_id:
            problems.append(_("The new site must be an address of the warranty owner."))
        elif all(unit._warranty_service_address() == site for unit in self.unit_ids):
            problems.append(_("These units are already at %s.", site.display_name))
        return problems

    def _warranty_problems_transfer(self):
        problems = self._warranty_owner_problems()
        if not self.company_id.warranty_transfer_allowed:
            problems.append(_("Warranty ownership transfer is not allowed in this company."))
        if self.card_id.state != 'confirmed':
            problems.append(_("Only Confirmed warranty cards can be transferred."))
        # Q18 pending: the card is the ownership record, so the whole card moves.
        if self.unit_ids != self.card_id._warranty_live_units():
            problems.append(_("The whole warranty card is transferred: single-unit transfer is "
                              "waiting for a business decision."))
        if not self.effective_date:
            problems.append(_("Give the transfer date."))
        if not self.attachment_ids:
            problems.append(_("Attach the transfer document."))
        return problems

    def _warranty_problems_extend(self):
        problems = self._warranty_live_units_problem()
        card = self.card_id
        if card.state not in ('confirmed', 'expired') or card.warranty_basis != 'period':
            problems.append(_("Only period-based Confirmed or Expired warranty cards are extended."))
        if not self.new_end_date:
            return problems + [_("Give the new end date.")]
        late = self.unit_ids.filtered(lambda unit: not unit.end_date
                                      or unit.end_date >= self.new_end_date)
        if late:
            problems.append(_("The new end date must be after the current end date of %s.",
                              ', '.join(late.mapped('name'))))
        limit = self.company_id.warranty_extension_max_days
        ends = self.unit_ids.mapped('end_date')
        if limit and ends and all(ends) and (self.new_end_date - min(ends)).days > limit:
            problems.append(_("The extension is above the maximum of %s days.", limit))
        if not self.extension_type:
            problems.append(_("Select the extension type."))
        elif self.extension_type == 'paid':
            problems += self._warranty_paid_source_problems()
        return problems

    def _warranty_paid_source_problems(self):
        order, invoice = self.source_order_id, self.source_move_id
        if not order and not invoice:
            return [_("A paid extension needs its quotation or invoice.")]
        owner = self.card_id.partner_id.commercial_partner_id
        return [_("The quotation or invoice must belong to the warranty owner and company.")] \
            if any(doc.company_id != self.company_id
                   or doc.partner_id.commercial_partner_id != owner
                   for doc in (order, invoice) if doc) else []

    # ------------------------------------------------------------------ execution
    def _warranty_status_text(self):
        return ', '.join('%s %s' % (unit.name, unit.state) for unit in self.unit_ids)

    def _warranty_execute_suspend(self):
        old = self._warranty_status_text()
        self.unit_ids._warranty_system_write({'state': 'suspended'})
        self.card_id._warranty_sync_status()
        return old, self._warranty_status_text()

    def _warranty_execute_reactivate(self):
        old = self._warranty_status_text()
        self.unit_ids._warranty_system_write({'state': 'active'})
        self.card_id._warranty_sync_status()
        return old, self._warranty_status_text()

    def _warranty_execute_cancel(self):
        old = self._warranty_status_text()
        self.unit_ids._warranty_system_write({'state': 'cancelled'})
        self.card_id._warranty_sync_status()
        return old, self._warranty_status_text()

    def _warranty_execute_correct_serial(self):
        unit, old, new = self.unit_ids, self.old_serial_id, self.new_serial_id
        unit._warranty_system_write({'serial_ids': [(3, old.id), (4, new.id)]})
        self.card_id._regenerate_soft_copy()
        return old.name, new.name

    def _warranty_change_owner(self):
        card, partner = self.card_id, self.new_partner_id
        old = card.partner_id
        self.old_partner_id = old
        card._warranty_system_write({'partner_id': partner.id})
        # The delivery address of the sale belongs to the previous customer.
        card._warranty_live_units()._warranty_system_write(
            {'current_site_id': (self.new_site_id or partner).id})
        card._regenerate_soft_copy()
        return old.display_name, partner.display_name

    def _warranty_execute_correct_customer(self):
        return self._warranty_change_owner()

    def _warranty_execute_transfer(self):
        # Warranty dates do not change. Free services stay with the card (Q19 "no" is pending).
        return self._warranty_change_owner()

    def _warranty_execute_correct_usage(self):
        unit = self.unit_ids
        old = unit.usage_correction_reading
        unit._warranty_system_write({'usage_correction_reading': self.new_usage,
                                     'usage_correction_date': fields.Datetime.now()})
        return str(old), str(self.new_usage)

    def _warranty_execute_relocate(self):
        old = ', '.join(sorted(set(self.unit_ids._warranty_addresses().mapped('display_name'))))
        self.unit_ids._warranty_system_write({'current_site_id': self.new_site_id.id})
        return old or '-', self.new_site_id.display_name

    def _warranty_execute_extend(self):
        card, new_end = self.card_id, self.new_end_date
        old_end = min(self.unit_ids.mapped('end_date'))
        for unit in self.unit_ids:
            unit._warranty_system_write({
                'end_date': new_end,
                'original_end_date': unit.original_end_date or unit.end_date})
        card_end = max(card._warranty_live_units().mapped('end_date'))
        old_card_end = card.warranty_end_date
        card._warranty_system_write({
            'warranty_end_date': card_end,
            'warranty_original_end_date': card.warranty_original_end_date or old_card_end})
        card._warranty_log_date_event(
            'extension', _("Warranty extended (%(type)s) to %(end)s by %(ref)s, units %(units)s.",
                           type=dict(EXTENSION_TYPES)[self.extension_type], end=new_end,
                           ref=self.name, units=', '.join(self.unit_ids.mapped('name'))),
            old_start=card.warranty_start_date, new_start=card.warranty_start_date,
            old_end=old_card_end, new_end=card_end, reason=self.reason)
        card._warranty_restore_from_expiry(_("warranty extension"))
        card._regenerate_soft_copy()
        return str(old_end), str(new_end)


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    action_ids = fields.One2many('warranty.card.action', 'card_id', string='Controlled Actions',
                                 readonly=True)
    action_count = fields.Integer(compute='_compute_action_count')
    history_count = fields.Integer(compute='_compute_history_count')
    warranty_original_end_date = fields.Date(
        string='Original End Date', readonly=True, copy=False,
        help="The end date before the first warranty extension.")

    def _compute_action_count(self):
        for card in self:
            card.action_count = len(card.action_ids)

    def _compute_history_count(self):
        History = self.env['warranty.history']
        for card in self:
            card.history_count = History.search_count([('card_id', '=', card.id)])

    def _warranty_live_units(self):
        self.ensure_one()
        return self.unit_warranty_ids.filtered(lambda unit: unit.state not in LIVE_UNIT_EXCLUDED)

    def _warranty_open_work(self):
        """Names of the open work on this card (extended by the Helpdesk, Field Service and Repair
        modules). Controlled actions never change it."""
        self.ensure_one()
        return []

    def _warranty_sync_status(self):
        """The card follows its units (SRS 9.13): Cancelled when none is left, Suspended when no
        unit is Active. Dates do not change."""
        self.ensure_one()
        live = self._warranty_live_units()
        states = set(live.mapped('state'))
        if not live:
            status = 'cancelled' if 'cancelled' in self.unit_warranty_ids.mapped('state') \
                else self.state
        elif 'active' in states or 'draft' in states:
            status = 'confirmed'
        elif 'suspended' in states:
            status = 'suspended'
        else:
            status = 'expired'
        if status != self.state:
            self._warranty_system_write({'state': status})

    def _warranty_request_action(self, action_type, units=None, **values):
        """Creates the waiting action and asks the approvers. sudo: users have no create access;
        only this method and the wizard create actions."""
        self.ensure_one()
        self.check_access('read')
        approvers = self.sudo().company_id.warranty_exception_approver_ids - self.env.user
        if not approvers:
            raise UserError(_("No other Warranty Exception Approver is configured for %s (Settings "
                              "> Warranty).", self.company_id.name))
        if self.action_ids.filtered(lambda action: action.state == 'pending'):
            raise UserError(_("%s already has a warranty change request waiting for approval.", self.name))
        attachments = values.pop('attachment_ids', self.env['ir.attachment'])
        # Attachments move to the action with sudo: only the requester's own fresh uploads.
        if attachments.sudo().filtered(lambda attachment: attachment.create_uid != self.env.user
                                       or attachment.res_id):
            raise UserError(_("Upload the evidence with this request."))
        action = self.env['warranty.card.action'].sudo().create(dict(
            values, action_type=action_type, card_id=self.id,
            requested_by_id=self.env.uid, unit_ids=[(6, 0, (units or self.env['warranty.unit']).ids)],
            open_work_note=', '.join(self._warranty_open_work()) or False,
            attachment_ids=[(6, 0, attachments.ids)]))
        if attachments:
            attachments.sudo().write({'res_model': action._name, 'res_id': action.id})
        action._warranty_raise_problems()
        label = dict(ACTION_TYPES)[action_type]
        for approver in approvers:
            action.activity_schedule('mail.mail_activity_data_todo', user_id=approver.id,
                                     summary=_("Approve: %(action)s on %(card)s", action=label,
                                               card=self.name), note=action.reason)
        self.sudo()._message_log(
            body=Markup('<p>%s<br/>%s</p>') % (
                _("%(action)s %(ref)s requested by %(user)s.", action=label, ref=action.name,
                  user=self.env.user.name), _("Reason: %s", action.reason)),
            author_id=self.env.user.partner_id.id)
        return action

    def action_open_controlled_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _("Warranty Change Request: %s", self.name),
            'res_model': 'warranty.card.action.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_card_id': self.id},
        }

    def action_view_controlled_actions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _("Controlled Actions: %s", self.name),
            'res_model': 'warranty.card.action', 'view_mode': 'list,form',
            'domain': [('card_id', '=', self.id)],
        }

    def action_view_warranty_history(self):
        return self.env['warranty.history']._warranty_open([('card_id', 'in', self.ids)])
