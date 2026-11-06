from odoo import api, fields, models

COST_APPROVER_FIELDS = {'warranty_cost_approver_ids', 'warranty_cost_finance_approver_ids'}


class ResCompany(models.Model):
    _inherit = 'res.company'

    warranty_cost_approver_ids = fields.Many2many(
        'res.users', 'warranty_cost_approver_company_rel', 'company_id', 'user_id',
        string='Warranty Cost Approvers', domain=[('share', '=', False)])
    warranty_cost_finance_approver_ids = fields.Many2many(
        'res.users', 'warranty_cost_finance_company_rel', 'company_id', 'user_id',
        string='Warranty Cost Finance Approvers', domain=[('share', '=', False)])
    warranty_cost_finance_threshold = fields.Monetary(
        string='Cost Finance Approval Threshold', currency_field='currency_id',
        help="Cost lines also need a Finance approver when the total expected cost of the case "
             "reaches this amount. 0 = no additional Finance approval; the Cost Approver "
             "approval stays required.")
    warranty_cost_gate_enabled = fields.Boolean(string='Expected Cost Approval Gate')
    warranty_cost_gate_threshold = fields.Monetary(
        string='Expected Cost Gate Threshold', currency_field='currency_id',
        help="Above this total expected cost, a job or material issue waits for its pending "
             "approvals. 0 = any expected cost is checked.")

    def write(self, vals):
        result = super().write(vals)
        if COST_APPROVER_FIELDS & set(vals):
            self._warranty_cost_sync_report_group()
        return result

    @api.model
    def _warranty_cost_sync_report_group(self):
        """Named approvers reach the Warranty Cost Report through this group. It only shows the
        menu and allows reading the report; the companies are checked when the report opens."""
        companies = self.env['res.company'].sudo().with_context(active_test=False).search([])
        users = companies.warranty_cost_approver_ids | companies.warranty_cost_finance_approver_ids
        group = self.env.ref('warranty_management_accounting.group_warranty_cost_report')
        if group.sudo().users != users:
            group.sudo().write({'users': [(6, 0, users.ids)]})


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_cost_approver_ids = fields.Many2many(
        related='company_id.warranty_cost_approver_ids', readonly=False,
        help="They approve every warranty cost line. The requester cannot approve their own line.")
    warranty_cost_finance_approver_ids = fields.Many2many(
        related='company_id.warranty_cost_finance_approver_ids', readonly=False,
        help="They also approve cost lines when the total expected cost of the case reaches the "
             "Finance threshold.")
    warranty_cost_finance_threshold = fields.Monetary(
        related='company_id.warranty_cost_finance_threshold', readonly=False,
        currency_field='company_currency_id',
        help="Cost lines also need a Finance approver when the total expected cost of the case "
             "reaches this amount. 0 = no additional Finance approval; the Cost Approver "
             "approval stays required.")
    warranty_cost_gate_enabled = fields.Boolean(
        related='company_id.warranty_cost_gate_enabled', readonly=False,
        help="If enabled, job confirmation, next visit planning and material release wait for "
             "pending approvals when the total expected cost is above the threshold. If disabled, "
             "they do not check the total expected cost.")
    warranty_cost_gate_threshold = fields.Monetary(
        related='company_id.warranty_cost_gate_threshold', readonly=False,
        currency_field='company_currency_id',
        help="Above this total expected cost, a job or material issue waits for its pending "
             "approvals. 0 = any expected cost is checked.")
