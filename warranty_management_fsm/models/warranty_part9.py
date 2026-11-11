from odoo import fields, models


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    def _warranty_open_work(self):
        work = super()._warranty_open_work()
        # sudo: names only, for the card's controlled actions.
        jobs = self.env['warranty.service.job'].sudo().search([
            '|', ('warranty_card_id', '=', self.id), ('warranty_card_ids', 'in', self.ids),
            ('state', 'not in', ('completed', 'cancelled'))])
        return work + jobs.mapped('name')


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    # SRS 12 #22: "linked to previous job".
    repeat_of_job_id = fields.Many2one(
        'warranty.service.job', string='Repeat of Job', copy=False, tracking=True,
        domain="[('warranty_case_id', '=', repeat_of_case_id)]",
        help="The job after which the issue came back.")

    def _warranty_repeat_defaults(self):
        defaults = super()._warranty_repeat_defaults()
        job = self.service_job_ids.filtered(lambda job: job.state == 'completed') \
            .sorted('id', reverse=True)[:1]
        return dict(defaults, default_repeat_of_job_id=job.id)


class WarrantyHistory(models.Model):
    _inherit = 'warranty.history'

    def _warranty_history_queries(self):
        return super()._warranty_history_queries() + [
            """SELECT r.card_id, NULL::integer, c.company_id, 'job', 'Job created',
                      j.create_date, j.create_uid, j.name, NULL::text, 'warranty.service.job', j.id
                 FROM warranty_service_job j
                 JOIN warranty_service_job_card_rel r ON r.job_id = j.id
                 JOIN warranty_card c ON c.id = r.card_id""",
            self._warranty_history_status_query(
                'warranty.service.job', 'job', 'Job',
                """warranty_service_job x
                   JOIN warranty_service_job_card_rel r ON r.job_id = x.id
                   JOIN warranty_card c ON c.id = r.card_id""", 'c.id'),
        ]
