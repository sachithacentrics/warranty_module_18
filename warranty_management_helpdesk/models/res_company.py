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


    # Approved: company switch of the Warranty Case approval rules (S1-S5). True = only the
    # Warranty Case Approval Users, never the creator / latest checker; False = Helpdesk users
    # (incl. creator / checker), no approval activities. Approve Case is always manual.
    warranty_case_approval_required = fields.Boolean(
        string='Warranty Case Approval Required', default=True)
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

    # Late Service Exceptions (BA-approved enhancement F5 / K5): approvers of this company;
    # empty = all Helpdesk managers of the company. Never the requester or the Draft Job
    # Automation User.
    warranty_late_service_approver_ids = fields.Many2many(
        'res.users', 'warranty_company_late_service_approver_rel', 'company_id', 'user_id',
        string='Late Service Exception Approvers', domain=[('share', '=', False)],
        context={'active_test': False},
        help="Helpdesk managers who approve late-service exceptions (dates after the Grace "
             "Period End) of this company; empty: all Helpdesk managers of the company. Never "
             "their own requests.")

    @api.constrains('warranty_late_service_approver_ids')
    def _check_warranty_late_service_approvers(self):
        for company in self:
            users = company.warranty_late_service_approver_ids
            invalid = users - company._warranty_valid_late_service_approvers(users)
            if invalid:
                raise ValidationError(_(
                    "The Late Service Exception Approvers of %(company)s must be active internal "
                    "Helpdesk managers allowed in that company: %(users)s",
                    company=company.name, users=', '.join(invalid.mapped('name'))))

    def _warranty_valid_late_service_approvers(self, users):
        self.ensure_one()
        return get_valid_service_alert_users(users, self).filtered(
            lambda user: user.has_group('helpdesk.group_helpdesk_manager'))

    def _warranty_late_service_approvers(self):
        """Configured approvers, else all Helpdesk managers of the company (valid users only)."""
        self.ensure_one()
        users = self.warranty_late_service_approver_ids or self.env['res.users'].search([
            ('groups_id', 'in', self.env.ref('helpdesk.group_helpdesk_manager').ids),
            ('share', '=', False), ('company_ids', 'in', self.ids)])
        return self._warranty_valid_late_service_approvers(users)

    def _warranty_late_service_forbidden_approvers(self, requester):
        """Approved K5: the requester never decides a late-service exception (the Draft Job
        Automation User is added by warranty_management_fsm)."""
        self.ensure_one()
        return requester
