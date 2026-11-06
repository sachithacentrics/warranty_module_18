from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WarrantyMrfCloseWizard(models.TransientModel):
    """K-1 / K-6: close one request or the requests of a job / case – every request is listed
    with its validation result; only the selected eligible ones are closed (validated again)."""
    _name = 'warranty.mrf.close.wizard'
    _description = 'Close Warranty Material Requests'

    origin = fields.Char(readonly=True)
    line_ids = fields.One2many('warranty.mrf.close.wizard.line', 'wizard_id')
    eligible_count = fields.Integer(compute='_compute_counts')
    blocked_count = fields.Integer(compute='_compute_counts')

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for row in wizards.line_ids:
            row.selected = row.eligible
        return wizards

    @api.depends('line_ids.eligible')
    def _compute_counts(self):
        for wizard in self:
            wizard.eligible_count = len(wizard.line_ids.filtered('eligible'))
            wizard.blocked_count = len(wizard.line_ids) - wizard.eligible_count

    def action_apply(self):
        self.ensure_one()
        rows = self.line_ids.filtered('selected')
        if not rows:
            raise UserError(_("Select the Material Requests to close."))
        if rows.filtered(lambda row: not row.eligible):
            raise UserError(_("Only requests without blockers can be closed (%s).", ', '.join(
                rows.filtered(lambda row: not row.eligible).requisition_id.mapped('name'))))
        rows.requisition_id._warranty_close()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'type': 'success', 'title': _("Material Requests closed"),
            'message': ', '.join(rows.requisition_id.mapped('name')),
            'next': {'type': 'ir.actions.act_window_close'}}}


class WarrantyMrfCloseWizardLine(models.TransientModel):
    _name = 'warranty.mrf.close.wizard.line'
    _description = 'Close Warranty Material Request Line'

    wizard_id = fields.Many2one('warranty.mrf.close.wizard', required=True, ondelete='cascade')
    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     required=True, readonly=True)
    status = fields.Selection(related='requisition_id.warranty_mrf_status')
    problems = fields.Text(string='Blockers', compute='_compute_check')
    eligible = fields.Boolean(string='Can Be Closed', compute='_compute_check')
    selected = fields.Boolean(string='Close')

    @api.depends('requisition_id')
    def _compute_check(self):
        for row in self:
            mrf = row.requisition_id
            problems = mrf._warranty_close_problems()
            if not problems and not mrf._warranty_can_close_user():
                problems = [_("you are not allowed to close it")]
            row.problems = '\n'.join(problems) or False
            row.eligible = not problems


class WarrantyMrfReopenWizard(models.TransientModel):
    _name = 'warranty.mrf.reopen.wizard'
    _description = 'Reopen Warranty Material Request'

    requisition_id = fields.Many2one('material.purchase.requisition', required=True,
                                     readonly=True)
    closed_by_id = fields.Many2one(related='requisition_id.warranty_closed_by_id')
    closed_date = fields.Datetime(related='requisition_id.warranty_closed_date')
    reason = fields.Text(string='Reason')
    admin_exception = fields.Boolean(string='Administrator Exception',
                                     help="Recovery situations only (Settings administrators); "
                                          "logged as such.")
    is_admin = fields.Boolean(compute='_compute_is_admin')

    @api.depends_context('uid')
    def _compute_is_admin(self):
        for wizard in self:
            wizard.is_admin = self.env.user.has_group('base.group_system')

    def action_apply(self):
        self.ensure_one()
        self.requisition_id._warranty_reopen(self.reason, admin_exception=self.admin_exception)
        return {'type': 'ir.actions.act_window_close'}
