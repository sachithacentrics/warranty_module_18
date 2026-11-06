from odoo import _, fields, models


class WarrantyServiceJob(models.Model):
    _inherit = 'warranty.service.job'

    amc_contract_id = fields.Many2one(related='warranty_case_id.amc_contract_id',
                                      string='AMC Contract', store=True)
    amc_visit_ids = fields.One2many(related='warranty_case_id.amc_visit_ids',
                                    string='AMC Visits')

    def _amc_open_visits(self):
        self.ensure_one()
        return self.amc_visit_ids.filtered(lambda v: v.state in ('scheduled', 'in_progress'))

    # ------------------------------------------------------------------ confirmation
    def action_confirm_job(self):
        """Confirmed with its Field Service task (AMC-F01): the AMC visits are In Progress and
        linked to the job and its visit."""
        result = super().action_confirm_job()
        for job in self.filtered(lambda j: j.amc_contract_id and j.state == 'confirmed'):
            visits = job._amc_open_visits()
            task = job.visit_ids.sorted('id')[-1:]
            visits._amc_marked().write({'state': 'in_progress', 'service_job_id': job.id,
                                        'task_id': task.id or False,
                                        'scheduled_date': job.planned_date})
            visits.sudo()._amc_log(_("Service job %(job)s confirmed (visit %(task)s).", job=job.name,
                              task=task.name or '-'))
        return result

    # ------------------------------------------------------------------ worksheets (F05)
    def _warranty_worksheet_lines(self, project=None):
        """One worksheet instance per AMC visit (product of the covered equipment); template:
        the product's Warranty Worksheet template, else the Field Service project default."""
        self.ensure_one()
        visits = self._amc_open_visits() if self.amc_contract_id else self.amc_visit_ids
        if not visits:
            return super()._warranty_worksheet_lines(project)
        project = project or self.company_id._warranty_fsm_project()
        default_template = project.sudo().worksheet_template_id
        Service = self.env['warranty.service.entitlement']
        Unit = self.env['warranty.unit']
        lines = []
        for visit in visits.sorted('id'):
            product = visit.product_id
            template = product.product_tmpl_id.warranty_worksheet_template_id or default_template
            lines.append((Service, Unit, product, template))
        return lines

    def _warranty_create_worksheets(self, task):
        sheets = super()._warranty_create_worksheets(task)
        if self.amc_contract_id and sheets:
            visits = self._amc_open_visits().sorted('id')
            for sheet, visit in zip(sheets.sorted('id'), visits):
                values = {}
                if visit.visit_type == 'preventive' and visit.usage_unit:
                    values.update(usage_required=True,
                                  usage_unit=visit._amc_worksheet_usage_unit(visit.usage_unit))
                if values:
                    sheet.sudo().write(values)
                visit._amc_marked().write({'worksheet_id': sheet.id, 'task_id': task.id})
        return sheets

    # ------------------------------------------------------------------ completion (E07)
    def _warranty_visit_completion_problems(self, task):
        problems = super()._warranty_visit_completion_problems(task)
        if self.amc_contract_id:
            today = self.company_id._warranty_today()
            for visit in self._amc_open_visits():
                usage = visit.worksheet_id.current_usage if visit.worksheet_id else 0.0
                problems += visit._amc_completion_problems(today, usage)
        return problems

    def _warranty_complete_case(self, inspection=None):
        """Inside the completion savepoint: the AMC visits are consumed once with the visit's
        customer sign-off as evidence (AMC-E07 / F06 / H04)."""
        result = super()._warranty_complete_case(inspection)
        if self.amc_contract_id:
            visits = self._amc_open_visits()
            today = self.company_id._warranty_today()
            task = self.visit_ids.filtered(lambda t: t.fsm_done).sorted('id')[-1:]
            for visit in visits:
                usage = visit.worksheet_id.current_usage if visit.worksheet_id else 0.0
                visit.sudo()._amc_consume(
                    today, usage_reading=usage,
                    source=_("Service job %(job)s / visit %(task)s (signed by %(signed)s)",
                             job=self.name, task=task.name or '-',
                             signed=task.worksheet_signed_by or _("no signature")))
            if visits:
                result = '%s %s' % (result or '', _("AMC visits consumed: %s.",
                                                    ', '.join(visits.mapped('name'))))
        return result

    # ------------------------------------------------------------------ cancellation (F07)
    def _warranty_cancel(self, reason):
        """Cancelled job: the AMC visits stay on the (Approved) case, not consumed."""
        result = super()._warranty_cancel(reason)
        for job in self.filtered('amc_contract_id'):
            visits = job.amc_visit_ids.filtered(lambda v: v.state == 'in_progress')
            visits._amc_marked().write({'state': 'scheduled', 'service_job_id': False,
                                        'task_id': False, 'worksheet_id': False})
            visits.sudo()._amc_log(_("Service job %(job)s cancelled: %(reason)s - not consumed.",
                              job=job.name, reason=reason))
        return result

    def action_view_amc_visits(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'amc_management.amc_contract_visit_action')
        action.update({'domain': [('warranty_case_id', '=', self.warranty_case_id.id)],
                       'context': {}})
        return action
