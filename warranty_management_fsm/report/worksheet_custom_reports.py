from odoo import api, models


class TaskCustomReport(models.AbstractModel):
    _inherit = 'report.industry_fsm.worksheet_custom'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data)
        values['warranty_checklist_map'] = self.env['warranty.job.worksheet']\
            ._warranty_report_checklists(values.get('docs'))
        return values
