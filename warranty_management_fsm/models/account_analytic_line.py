from odoo import _, api, models
from odoo.exceptions import UserError

# Approved L3 / L10: the timesheets of a closed warranty visit are kept as visit history.
LOCKED_TIMESHEET_FIELDS = {'unit_amount', 'date', 'employee_id', 'user_id', 'task_id',
                           'project_id', 'name'}


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    @api.model
    def _warranty_closed_visits(self, tasks):
        # sudo: the visit status is read only.
        return tasks.sudo().filtered(lambda task: task.warranty_is_visit and (
            task.fsm_done or task.state in ('1_done', '1_canceled')))

    def _warranty_check_closed_visit(self, tasks):
        closed = self._warranty_closed_visits(tasks)
        if closed:
            raise UserError(_("The timesheets of closed warranty visit %s are kept as visit "
                              "history and cannot be changed.", ', '.join(closed.mapped('name'))))

    @api.model_create_multi
    def create(self, vals_list):
        self._warranty_check_closed_visit(self.env['project.task'].browse(
            [vals['task_id'] for vals in vals_list if vals.get('task_id')]))
        return super().create(vals_list)

    def write(self, vals):
        if LOCKED_TIMESHEET_FIELDS & set(vals):
            tasks = self.sudo().task_id
            if vals.get('task_id'):
                tasks |= self.env['project.task'].browse(vals['task_id'])
            self._warranty_check_closed_visit(tasks)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_closed_warranty_visit(self):
        self._warranty_check_closed_visit(self.sudo().task_id)
