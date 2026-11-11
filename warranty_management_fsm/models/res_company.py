from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Approved D5: project of the warranty Field Service tasks; empty = the company's standard
    # Field Service project. D5 revised: no longer shown in the Warranty Settings (kept for
    # compatibility).
    warranty_fsm_project_id = fields.Many2one(
        'project.project', string='Warranty Field Service Project',
        domain="[('is_fsm', '=', True), ('company_id', '=', id)]")
    # checks configurable before job completion).
    warranty_signoff_required = fields.Boolean(string='Customer Sign-off Required', default=True)
    # Optional Case Type (approved G2): worksheet of the inspection visit of an undetermined case.
    warranty_inspection_template_id = fields.Many2one(
        'worksheet.template', string='Inspection Worksheet Template',
        domain="[('res_model', 'in', ('project.task', 'warranty.job.worksheet'))]")
    warranty_worksheet_checklist_required = fields.Boolean(
        string='Worksheet Checklist Required', default=True)
    warranty_worksheet_attachment_required = fields.Boolean(
        string='Worksheet Attachment Required', default=False)
    # Phase 4.11 (approved E4 / E10): Helpdesk team of the automatic Draft Job from Service tickets
    # and the user who creates / checks the automatic tickets, cases and draft jobs.
    warranty_draft_job_team_id = fields.Many2one(
        'helpdesk.team', string='Draft Job Helpdesk Team', domain="[('company_id', '=', id)]")
    warranty_draft_job_user_id = fields.Many2one(
        'res.users', string='Draft Job Automation User',
        domain="[('share', '=', False), ('company_ids', 'in', id)]")

    @api.constrains('warranty_fsm_project_id')
    def _check_warranty_fsm_project(self):
        for company in self:
            project = company.warranty_fsm_project_id
            if project and (not project.is_fsm or project.company_id != company):
                raise ValidationError(_(
                    "The Warranty Field Service Project of %s must be a Field Service project of "
                    "that company.", company.name))

    @api.constrains('warranty_draft_job_team_id', 'warranty_draft_job_user_id')
    def _check_warranty_draft_job_settings(self):
        for company in self:
            problems = company._warranty_draft_job_config_problems(required=False)
            if problems:
                raise ValidationError('\n'.join(problems))

    def _warranty_draft_job_config_problems(self, required=True):
        """Approved E4 / E10: the Draft Job Helpdesk Team is a team of the company; the Draft
        Job Automation User an active internal Helpdesk user allowed in the company.
        `required`: missing values are problems too (at run time)."""
        self.ensure_one()
        problems = []
        team, user = self.warranty_draft_job_team_id, self.warranty_draft_job_user_id
        if not team:
            if required:
                problems.append(_("Draft Job Helpdesk Team is not configured for %s (Warranty "
                                  "Settings).", self.name))
        elif team.company_id != self:
            problems.append(_("The Draft Job Helpdesk Team %(team)s is not a team of %(company)s.",
                              team=team.name, company=self.name))
        if not user:
            if required:
                problems.append(_("Draft Job Automation User is not configured for %s (Warranty "
                                  "Settings).", self.name))
        elif not user.active or user.share or self not in user.company_ids \
                or not user.has_group('helpdesk.group_helpdesk_user'):
            problems.append(_("The Draft Job Automation User %(user)s of %(company)s must be an "
                              "active internal Helpdesk user allowed in the company.",
                              user=user.name, company=self.name))
        return problems

    def _warranty_fsm_project(self):
        """Approved D5: configured project, else the company's standard Field Service project."""
        self.ensure_one()
        project = self.warranty_fsm_project_id or self.env['project.project'].search(
            [('is_fsm', '=', True), ('company_id', '=', self.id)], order='id', limit=1)
        if not project:
            raise UserError(_("No Field Service project is available for %s: create the "
                              "company's standard Field Service project in Field Service.",
                              self.name))
        return project
