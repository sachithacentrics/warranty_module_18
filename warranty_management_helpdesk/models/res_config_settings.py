from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_overdue_approver_ids = fields.Many2many(
        related='company_id.warranty_overdue_approver_ids',
        string='Overdue Claim Approval Users', readonly=False,
        help="Users who approve warranty cases of customers with overdue invoices, when the "
             "warranty policy's Overdue Claim Handling is Approval Required. A user never "
             "approves their own request.")
    warranty_escalation_user_ids = fields.Many2many(
        related='company_id.warranty_escalation_user_ids',
        string='Repeated Failure Escalation Users', readonly=False,
        help="Managers who confirm the warranty of products with repeated failures. A user "
             "never confirms their own escalation.")
    warranty_case_approval_required = fields.Boolean(
        related='company_id.warranty_case_approval_required', readonly=False,
        help="If enabled, only the Warranty Case Approval Users can approve or reject "
             "eligible warranty cases, and never a case they created or checked. If "
             "disabled, any Helpdesk user of the company can approve or reject them. In both "
             "cases approval is a manual step.")
    warranty_case_approver_ids = fields.Many2many(
        related='company_id.warranty_case_approver_ids',
        string='Warranty Case Approval Users', readonly=False,
        help="Users who approve or reject eligible warranty cases when approval is required. "
             "They cannot approve a case they created or whose eligibility they checked.")
    warranty_late_service_approver_ids = fields.Many2many(
        related='company_id.warranty_late_service_approver_ids',
        string='Late Service Exception Approvers', readonly=False,
        help="Helpdesk managers who can allow a free service after its grace period has "
             "ended. If empty, all Helpdesk managers of the company can approve. A user "
             "never approves their own request.")
