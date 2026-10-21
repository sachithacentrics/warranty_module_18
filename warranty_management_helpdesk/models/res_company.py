from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.warranty_management.models.res_company import get_valid_service_alert_users


class ResCompany(models.Model):
    _inherit = 'res.company'

    warranty_overdue_approver_ids = fields.Many2many(
        'res.users', 'warranty_company_overdue_approver_rel', 'company_id', 'user_id',
        string='Overdue Claim Approval Users', domain=[('share', '=', False)],
        context={'active_test': False},
        help="Users who approve the payment exceptions of warranty cases of this company "
             "(Overdue Claim Handling = Approval Required); never their own requests.")


    warranty_escalation_user_ids = fields.Many2many(
        'res.users', 'warranty_company_escalation_user_rel', 'company_id', 'user_id',
        string='Repeated Failure Escalation Users', domain=[('share', '=', False)],
        context={'active_test': False},
        help="Manager / GM users who confirm the warranty of repeated failure cases of this "
             "company; never their own escalations.")


    warranty_case_approver_ids = fields.Many2many(
        'res.users', 'warranty_company_case_approver_rel', 'company_id', 'user_id',
        string='Warranty Case Approval Users', domain=[('share', '=', False)],
        context={'active_test': False},
        help="Users who approve the eligible warranty cases of this company; never a case they "
             "created or whose latest eligibility check they ran.")

    @api.constrains('warranty_case_approver_ids')
    def _check_warranty_case_approvers(self):
        for company in self:
            users = company.warranty_case_approver_ids
            invalid = users - get_valid_service_alert_users(users, company)
            if invalid:
                raise ValidationError(_(
                    "The Warranty Case Approval Users of %(company)s must be active internal "
                    "users allowed in that company: %(users)s",
                    company=company.name, users=', '.join(invalid.mapped('name'))))

    @api.constrains('warranty_escalation_user_ids')
    def _check_warranty_escalation_users(self):
        for company in self:
            users = company.warranty_escalation_user_ids
            invalid = users - get_valid_service_alert_users(users, company)
            if invalid:
                raise ValidationError(_(
                    "The Repeated Failure Escalation Users of %(company)s must be active "
                    "internal users allowed in that company: %(users)s",
                    company=company.name, users=', '.join(invalid.mapped('name'))))

    @api.constrains('warranty_overdue_approver_ids')
    def _check_warranty_overdue_approvers(self):
        for company in self:
            users = company.warranty_overdue_approver_ids
            invalid = users - get_valid_service_alert_users(users, company)
            if invalid:
                raise ValidationError(_(
                    "The Overdue Claim Approval Users of %(company)s must be active internal "
                    "users allowed in that company: %(users)s",
                    company=company.name, users=', '.join(invalid.mapped('name'))))
