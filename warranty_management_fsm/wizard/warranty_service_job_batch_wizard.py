from odoo import _, fields, models


class WarrantyServiceJobBatchWizard(models.TransientModel):
    """Complete Selected Jobs (Phase 4.9, approved B1-B10, T1): 1. Check / Preview (Ready / Not
    Ready with every reason, nothing changed), 2. Complete Ready Jobs (revalidated, result per
    job)."""
    _name = 'warranty.service.job.batch.wizard'
    _description = 'Service Job Batch Completion'

    job_ids = fields.Many2many('warranty.service.job', string='Selected Service Jobs',
                               readonly=True)
    state = fields.Selection([('preview', 'Check'), ('done', 'Result')], default='preview',
                             readonly=True)
    line_ids = fields.One2many('warranty.service.job.batch.wizard.line', 'wizard_id',
                               readonly=True)
    ready_count = fields.Integer(compute='_compute_counts')
    not_ready_count = fields.Integer(compute='_compute_counts')
    completed_count = fields.Integer(compute='_compute_counts')
    skipped_count = fields.Integer(compute='_compute_counts')

    def _compute_counts(self):
        for wizard in self:
            results = wizard.line_ids.mapped('result')
            wizard.ready_count = results.count('ready')
            wizard.not_ready_count = results.count('not_ready')
            wizard.completed_count = results.count('completed')
            wizard.skipped_count = results.count('skipped')

    def _warranty_lines(self, rows):
        self.line_ids = [(5, 0, 0)] + [(0, 0, {
            'job_id': job.id, 'result': result,
            'reasons': '\n'.join('- %s' % problem for problem in problems)})
            for job, result, problems in rows]

    def _warranty_preview(self):
        self.ensure_one()
        self._warranty_lines([(job, 'not_ready' if problems else 'ready', problems)
                              for job, problems in self.job_ids._warranty_batch_preview()])

    def _warranty_action(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Complete Selected Jobs"),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_check(self):
        self._warranty_preview()
        return self._warranty_action()

    def action_complete(self):
        self.ensure_one()
        results = self.job_ids._warranty_batch_complete()
        self._warranty_lines([(job, 'completed' if completed else 'skipped', problems)
                              for job, completed, problems in results])
        self.state = 'done'
        return self._warranty_action()


class WarrantyServiceJobBatchWizardLine(models.TransientModel):
    _name = 'warranty.service.job.batch.wizard.line'
    _description = 'Service Job Batch Completion Line'
    _order = 'id'

    wizard_id = fields.Many2one('warranty.service.job.batch.wizard', required=True,
                                ondelete='cascade')
    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True)
    result = fields.Selection([
        ('ready', 'Ready'),
        ('not_ready', 'Not Ready'),
        ('completed', 'Completed'),
        ('skipped', 'Skipped'),
    ], string='Result', readonly=True)
    reasons = fields.Text(string='Reasons', readonly=True)
