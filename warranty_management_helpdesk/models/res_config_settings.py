from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_overdue_approver_ids = fields.Many2many(
        related='company_id.warranty_overdue_approver_ids',
        string='Overdue Claim Approval Users', readonly=False)
    warranty_escalation_user_ids = fields.Many2many(
        related='company_id.warranty_escalation_user_ids',
        string='Repeated Failure Escalation Users', readonly=False)
    warranty_case_approver_ids = fields.Many2many(
        related='company_id.warranty_case_approver_ids',
        string='Warranty Case Approval Users', readonly=False)
