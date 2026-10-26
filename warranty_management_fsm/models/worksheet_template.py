from odoo import api, models

WARRANTY_WORKSHEET_HOST = 'warranty.job.worksheet'


class WorksheetTemplate(models.Model):
    """Warranty Worksheet templates (approved shared-worksheet fix): the standard worksheet
    framework hosted on the worksheet instance (like the Maintenance / Quality worksheets), so
    every instance has its own checklist record, also when several instances of one visit use
    the same template. Designed with Studio as the Field Service templates."""
    _inherit = 'worksheet.template'

    @api.model
    def _get_warranty_job_worksheet_manager_group(self):
        return self.env.ref('helpdesk.group_helpdesk_manager')

    @api.model
    def _get_warranty_job_worksheet_user_group(self):
        return self.env.ref('base.group_user')

    @api.model
    def _get_warranty_job_worksheet_access_all_groups(self):
        return self.env.ref('industry_fsm.group_fsm_user') \
            | self.env.ref('helpdesk.group_helpdesk_user') \
            | self.env.ref('helpdesk.group_helpdesk_manager')

    @api.model
    def _get_warranty_job_worksheet_module_name(self):
        return 'warranty_management_fsm'

    @api.model
    def _get_models_to_check_dict(self):
        res = super()._get_models_to_check_dict()
        # The instances keep their template snapshot (no company re-check needed).
        res[WARRANTY_WORKSHEET_HOST] = []
        return res

    def _generate_worksheet_model(self):
        result = super()._generate_worksheet_model()
        if self.res_model == WARRANTY_WORKSHEET_HOST:
            # Multi-company: the checklist records follow the company of their instance (the
            # generated rules of the framework have no company restriction).
            self.env['ir.rule'].sudo().create({
                'name': '%s_company' % self.model_id.model,
                'model_id': self.model_id.id,
                'domain_force': "[('x_warranty_job_worksheet_id.company_id', 'in', company_ids)]",
            })
        return result
