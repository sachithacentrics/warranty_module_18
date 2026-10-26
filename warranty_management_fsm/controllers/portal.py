from odoo.http import request

from odoo.addons.industry_fsm_report.controllers.portal import CustomerFsmPortal


class WarrantyFsmPortal(CustomerFsmPortal):

    def _get_worksheet_data(self, task_sudo):
        data = super()._get_worksheet_data(task_sudo)
        data['warranty_checklist_map'] = request.env['warranty.job.worksheet']\
            ._warranty_report_checklists(task_sudo)
        return data
