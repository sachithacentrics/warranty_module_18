from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


CUSTOMER_DECISIONS = [
    ('quotation_required', 'Quotation Required'),
    ('waiting', 'Waiting Customer Approval'),
    ('approved', 'Customer Approved (Chargeable)'),
    ('declined', 'Customer Declined'),
]
DECIDED = ('approved', 'declined')


class WarrantyCaseExcludedItem(models.Model):
    """Excluded requested item of a warranty case (approved Part 3.6c Q53a-d, Q55-Q58): always
    chargeable; its customer decision comes from the linked quotation line (Approved = line on a
    confirmed order, quantity > 0) or from an explicit Customer Declined. Quantities only on
    the quotation (Q58 A)."""
    _name = 'warranty.case.excluded.item'
    _description = 'Warranty Case Excluded Item'
    _order = 'case_id, id'

    case_id = fields.Many2one('warranty.case', string='Warranty Case', required=True,
                              ondelete='cascade', index=True)
    company_id = fields.Many2one(related='case_id.company_id', store=True)
    coverage_item_id = fields.Many2one('warranty.coverage.item', string='Excluded Item',
                                       required=True, ondelete='restrict')
    product_id = fields.Many2one(related='coverage_item_id.product_id', string='Product')
    sale_line_ids = fields.One2many('sale.order.line', 'warranty_excluded_item_id',
                                    string='Quotation Lines', readonly=True)
    customer_decision = fields.Selection(CUSTOMER_DECISIONS, string='Customer Decision',
                                         compute='_compute_quotation_values')
    sale_order_id = fields.Many2one('sale.order', string='Quotation',
                                    compute='_compute_quotation_values')
    quoted_qty = fields.Float(string='Quoted Qty', digits='Product Unit of Measure',
                              compute='_compute_quotation_values')
    confirmed_qty = fields.Float(string='Confirmed Qty', digits='Product Unit of Measure',
                                 compute='_compute_quotation_values')
    declined = fields.Boolean(string='Declined', readonly=True, copy=False)
    decline_reason = fields.Text(string='Decline Reason', readonly=True, copy=False)
    decided_by_id = fields.Many2one('res.users', string='Declined By', readonly=True,
                                    copy=False)
    decided_date = fields.Datetime(string='Declined On', readonly=True, copy=False)

    _sql_constraints = [
        ('case_item_unique', 'unique(case_id, coverage_item_id)',
         'An excluded item is listed only once per warranty case.'),
    ]

    @api.depends('declined', 'sale_line_ids.order_id.state', 'sale_line_ids.product_uom_qty')
    def _compute_quotation_values(self):
        for item in self:
            # sudo: the decision is shown to Helpdesk users without sales rights (only the
            # state / quantities of the linked lines are read).
            lines = item.sudo().sale_line_ids.filtered(
                lambda line: line.order_id.state != 'cancel' and line.product_uom_qty > 0)
            confirmed = lines.filtered(lambda line: line.order_id.state == 'sale')
            item.sale_order_id = (confirmed or lines)[:1].order_id.id
            item.quoted_qty = sum(lines.mapped('product_uom_qty'))
            item.confirmed_qty = sum(confirmed.mapped('product_uom_qty'))
            if item.declined:
                item.customer_decision = 'declined'
            elif confirmed:
                item.customer_decision = 'approved'
            elif lines:
                item.customer_decision = 'waiting'
            else:
                item.customer_decision = 'quotation_required'

    def _active_sale_lines(self):
        return self.sudo().sale_line_ids.filtered(lambda line: line.order_id.state != 'cancel')

    def _check_decision_rights(self):
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can record customer decisions."))
        for item in self:
            if item.case_id.state not in ('eligibility_checked', 'chargeable'):
                raise UserError(_("Customer decisions of %s can no longer be changed (status %s).",
                                  item.case_id.name, item.case_id.state))

    def action_open_decline_wizard(self):
        self._check_decision_rights()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Customer Declined"),
            'res_model': 'warranty.case.decline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_excluded_item_ids': [(6, 0, self.ids)]},
        }

    def _warranty_decline(self, reason):
        """Customer Declined (Q55, clarification 1): explicit, reason required; the item's lines
        are removed from Draft / Sent quotations (never on a confirmed order); a quotation
        without other lines is cancelled."""
        self._check_decision_rights()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A decline reason is required."))
        for item in self:
            if item.declined:
                raise UserError(_("%s is already declined.", item.coverage_item_id.name))
            lines = item._active_sale_lines()
            if lines.filtered(lambda line: line.order_id.state == 'sale'):
                raise UserError(_("%(item)s is on the confirmed order %(order)s: the customer has "
                                  "already approved it.", item=item.coverage_item_id.name,
                                  order=', '.join(lines.order_id.mapped('name'))))
            orders = lines.order_id
            # sudo: an authorized Helpdesk user records the decline; only the item's own lines
            # of the case quotations (Draft / Sent) are removed.
            lines.sudo().unlink()
            for order in orders.sudo():
                if not order.order_line.filtered(lambda line: not line.display_type):
                    order.with_context(disable_cancel_warning=True).action_cancel()
            item.sudo().write({'declined': True, 'decline_reason': reason,
                               'decided_by_id': self.env.uid,
                               'decided_date': fields.Datetime.now()})
            item.case_id.sudo()._message_log(body=Markup('<p><b>%s</b></p><p>%s</p>') % (
                _("Customer declined %(item)s (recorded by %(user)s)",
                  item=item.coverage_item_id.name, user=self.env.user.name),
                reason + (_(" - removed from %s", ', '.join(orders.mapped('name')))
                          if orders else '')))
        return True

    def action_undo_decline(self):
        """Undo Decline (Q56): before the case is Approved; the item goes back to Quotation
        Required (never added to an existing order automatically)."""
        self._check_decision_rights()
        for item in self:
            if not item.declined:
                raise UserError(_("%s is not declined.", item.coverage_item_id.name))
            item.sudo().write({'declined': False, 'decline_reason': False,
                               'decided_by_id': False, 'decided_date': False})
            item.case_id.sudo()._message_log(body=Markup('<p><b>%s</b></p>') % _(
                "Customer decline of %(item)s undone by %(user)s: quotation required again.",
                item=item.coverage_item_id.name, user=self.env.user.name))
        return True
