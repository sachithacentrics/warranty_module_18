from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_fsm_project_id = fields.Many2one(
        related='company_id.warranty_fsm_project_id', readonly=False)
    warranty_signoff_required = fields.Boolean(
        related='company_id.warranty_signoff_required', readonly=False)
    warranty_worksheet_checklist_required = fields.Boolean(
        related='company_id.warranty_worksheet_checklist_required', readonly=False)
    warranty_worksheet_attachment_required = fields.Boolean(
        related='company_id.warranty_worksheet_attachment_required', readonly=False)
    # Phase 4.11 (approved E4 / E10).
    warranty_draft_job_team_id = fields.Many2one(
        related='company_id.warranty_draft_job_team_id', readonly=False,
        domain="[('company_id', '=', company_id)]")
    warranty_draft_job_user_id = fields.Many2one(
        related='company_id.warranty_draft_job_user_id', readonly=False,
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]")
