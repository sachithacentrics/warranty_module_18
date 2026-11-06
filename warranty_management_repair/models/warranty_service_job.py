from odoo import _, models

from .repair_order import INSPECTION_JOB_TYPES


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    def _warranty_completion_blockers(self):
        """SRS 2.5 / 13: no completion with an open repair. Job-controlled completion is otherwise
        unchanged; inspection jobs (Figure 4) are not blocked. Incomplete / Reschedule does not
        use this hook, so a pickup visit keeps the existing reason Workshop Repair Required."""
        problems = super()._warranty_completion_blockers()
        if self.job_type in INSPECTION_JOB_TYPES:
            return problems
        case = self.warranty_case_id
        repairs = case._warranty_active_repairs().filtered(
            lambda repair: not repair.warranty_equipment_returned
            and not case._warranty_replacement_covers(repair))
        if repairs:
            problems.append(_(
                "Repair Order %(repairs)s of the warranty case: the machine has not been returned "
                "to the customer.", repairs=', '.join(repairs.mapped('name'))))
        problems.extend(case._warranty_replacement_problems())
        return problems
