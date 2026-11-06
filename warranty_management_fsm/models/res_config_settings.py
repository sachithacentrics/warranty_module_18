from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_fsm_project_id = fields.Many2one(
        related='company_id.warranty_fsm_project_id', readonly=False,
        help="The Field Service project that receives the warranty visits. If empty, the "
             "company's standard Field Service project is used.")
    warranty_inspection_template_id = fields.Many2one(
        related='company_id.warranty_inspection_template_id', readonly=False,
        help="Worksheet used by the inspection visit of a warranty case whose Case Type is not "
             "known yet. If empty, the product's or the project's worksheet is used.")
    warranty_signoff_required = fields.Boolean(
        related='company_id.warranty_signoff_required', readonly=False,
        help="If enabled, a warranty visit or a warranty installation task can only be "
             "completed after the customer signs the report. If disabled, they can be "
             "completed without a signature.")
    warranty_worksheet_checklist_required = fields.Boolean(
        related='company_id.warranty_worksheet_checklist_required', readonly=False,
        help="If enabled, every worksheet checklist must be fully answered before the visit "
             "is completed. If disabled, the checklist can be left incomplete.")
    warranty_worksheet_attachment_required = fields.Boolean(
        related='company_id.warranty_worksheet_attachment_required', readonly=False,
        help="If enabled, every worksheet needs at least one attachment, such as a photo, "
             "before the visit is completed. If disabled, attachments are optional.")
    # Phase 4.11 (approved E4 / E10).
    warranty_draft_job_team_id = fields.Many2one(
        related='company_id.warranty_draft_job_team_id', readonly=False,
        domain="[('company_id', '=', company_id)]",
        help="The Helpdesk team that receives the tickets created automatically for due free "
             "services (warranty policies with Draft Job from Service). Required for these "
             "automatic jobs.")
    warranty_draft_job_user_id = fields.Many2one(
        related='company_id.warranty_draft_job_user_id', readonly=False,
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        help="The user who creates and checks the automatic tickets, warranty cases and "
             "draft service jobs for due free services. This user never approves them. "
             "Required for these automatic jobs.")
