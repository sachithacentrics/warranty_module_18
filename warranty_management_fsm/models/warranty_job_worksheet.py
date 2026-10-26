from ast import literal_eval

from lxml import etree
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import is_html_empty
from odoo.tools.safe_eval import safe_eval

from .warranty_service_job import _COMPLETION_MARKER

# Approved W6 (G7): worksheet instance status; 4.4 creates To Do, 4.5 / 4.7 set the others.
WORKSHEET_STATES = [
    ('todo', 'To Do'),
    ('in_progress', 'In Progress'),
    ('completed', 'Completed'),
]


class WarrantyJobWorksheet(models.Model):
    """Worksheet instance of a Service Job (SRS 10.5 "Worksheet Instances", 2.7; approved
    W1-W6): one per linked free service, or one for the case product (Warranty Only), under
    the job's Field Service task. The checklist is the standard worksheet template record
    (Studio model), opened from here."""
    _name = 'warranty.job.worksheet'
    _description = 'Service Job Worksheet Instance'
    _order = 'job_id, id'

    name = fields.Char(string='Worksheet', compute='_compute_name', store=True)
    job_id = fields.Many2one('warranty.service.job', string='Service Job', required=True,
                             readonly=True, ondelete='cascade', index=True)
    task_id = fields.Many2one('project.task', string='Field Service Task', required=True,
                              readonly=True, ondelete='cascade', index=True)
    warranty_case_id = fields.Many2one(related='job_id.warranty_case_id', store=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True, index=True)
    entitlement_id = fields.Many2one('warranty.service.entitlement', string='Free Service',
                                     readonly=True, ondelete='restrict')
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    template_id = fields.Many2one('worksheet.template', string='Worksheet Template',
                                  readonly=True)
    worksheet_model = fields.Char(readonly=True, copy=False)
    worksheet_res_id = fields.Integer(readonly=True, copy=False)
    state = fields.Selection(WORKSHEET_STATES, string='Status', default='todo', required=True,
                             readonly=True, copy=False)
    # Diagram "Enable Usage Fields -> Require Usage Value + Usage Unit"; the completion block
    # is Part 4.5 (approved G9).
    usage_required = fields.Boolean(string='Usage Reading Required', readonly=True)
    current_usage = fields.Float(string='Current Usage', digits=(16, 2))
    usage_unit = fields.Selection(
        selection=lambda self: self.env['warranty.card']._fields['usage_unit'].selection,
        string='Usage Unit')
    attachment_ids = fields.Many2many(
        'ir.attachment', 'warranty_job_worksheet_attachment_rel', 'worksheet_id',
        'attachment_id', string='Attachments',
        help="Scanned forms, external test reports, images and supporting documents.")
    notes = fields.Text(string='Notes')
    # Warranty unit of the reading (approved V4): the job's unit, else the only unit of the
    # card for this product; empty when it cannot be identified (no previous-reading check).
    warranty_unit_id = fields.Many2one('warranty.unit', string='Unit Warranty',
                                       compute='_compute_warranty_unit_id', store=True)
    # Cross-card service merge (approved D4): the unit and card of this worksheet, set at
    # creation (worksheets created before keep their computed unit).
    unit_id = fields.Many2one('warranty.unit', string='Serviced Unit', readonly=True, copy=False)
    warranty_card_id = fields.Many2one('warranty.card', string='Warranty Card',
                                       compute='_compute_warranty_card_id', store=True)
    serial_display = fields.Char(string='Serial No.', compute='_compute_warranty_card_id')

    @api.depends('unit_id', 'entitlement_id.warranty_card_id', 'job_id.warranty_card_id',
                 'warranty_unit_id')
    def _compute_warranty_card_id(self):
        for sheet in self:
            unit = sheet.unit_id or sheet.warranty_unit_id
            sheet.warranty_card_id = sheet.unit_id.warranty_card_id \
                or sheet.entitlement_id.warranty_card_id or sheet.job_id.warranty_card_id
            sheet.serial_display = ', '.join(unit.serial_ids.mapped('name')) or False

    @api.depends('unit_id', 'job_id.warranty_unit_id', 'job_id.warranty_card_id', 'product_id')
    def _compute_warranty_unit_id(self):
        for sheet in self:
            if sheet.unit_id:
                sheet.warranty_unit_id = sheet.unit_id
                continue
            unit = sheet.job_id.warranty_unit_id
            if not unit:
                units = sheet.job_id.warranty_card_id.unit_warranty_ids.filtered(
                    lambda u: u.product_id == sheet.product_id)
                unit = units if len(units) == 1 else units.browse()
            sheet.warranty_unit_id = unit

    def _previous_usage_reading(self):
        """Latest valid earlier reading of the same warranty unit (approved V4): readings of
        worksheets of other visits planned up to this job's date (not this worksheet nor the
        other worksheets of the same visit, not cancelled jobs) and eligibility readings of the
        unit's cases. Returns (value, source) or (0, False)."""
        self.ensure_one()
        unit = self.warranty_unit_id
        if not unit:
            return 0.0, False
        planned = self.job_id.planned_date or fields.Datetime.now()
        candidates = []
        # sudo: readings of earlier visits / cases of the unit, compared only.
        for sheet in self.sudo().search([
                ('warranty_unit_id', '=', unit.id), ('id', '!=', self.id),
                ('task_id', '!=', self.task_id.id), ('current_usage', '>', 0),
                ('job_id.state', '!=', 'cancelled'), ('job_id.planned_date', '<=', planned)]):
            candidates.append((sheet.job_id.planned_date, sheet.id, sheet.current_usage,
                               sheet.name))
        for case in self.env['warranty.case'].sudo().search([
                ('warranty_unit_id', '=', unit.id), ('current_usage', '>', 0),
                ('create_date', '<=', planned)]):
            candidates.append((case.create_date, 0, case.current_usage, case.name))
        if not candidates:
            return 0.0, False
        latest = max(candidates)
        return latest[2], latest[3]

    @api.constrains('current_usage', 'usage_unit')
    def _check_usage_reading(self):
        """Validate Usage Value (approved V4); mandatory before completion is Part 4.7."""
        for sheet in self:
            if sheet.current_usage < 0:
                raise ValidationError(_("The current usage of %s must be greater than zero.",
                                        sheet.name))
            if not sheet.usage_required or not sheet.current_usage:
                continue
            card_unit = sheet.warranty_card_id.usage_unit
            if card_unit and sheet.usage_unit != card_unit:
                raise ValidationError(_(
                    "The usage unit of %(sheet)s must be the usage unit of warranty card "
                    "%(card)s: %(unit)s.", sheet=sheet.name,
                    card=sheet.warranty_card_id.name,
                    unit=dict(sheet._fields['usage_unit']._description_selection(sheet.env))
                    [card_unit]))
            previous, source = sheet._previous_usage_reading()
            if sheet.current_usage < previous:
                raise ValidationError(_(
                    "The current usage %(usage)s of %(sheet)s is lower than the latest reading "
                    "%(previous)s of the unit (%(origin)s).", usage=sheet.current_usage,
                    sheet=sheet.name, previous=previous, origin=source))

    def write(self, vals):
        if 'state' in vals \
                and self.env.context.get('warranty_completion_marker') is not _COMPLETION_MARKER \
                and (vals['state'] == 'completed' or any(sheet.state == 'completed' for sheet in self)):
            raise UserError(_("Worksheet instances are completed only with Complete Visit."))
        # Approved L3 / L10: the worksheets of a closed visit are kept as attempt history.
        if {'current_usage', 'usage_unit', 'attachment_ids', 'notes'} & set(vals) and any(
                sheet.task_id.fsm_done or sheet.task_id.state in ('1_done', '1_canceled')
                for sheet in self.sudo()):
            raise UserError(_("The worksheets of a closed visit are kept as visit history and "
                              "cannot be changed."))
        result = super().write(vals)
        if 'current_usage' in vals:
            self._warranty_log_usage_over_limit()
        return result

    def _warranty_log_usage_over_limit(self):
        """Approved V5: a reading above the usage limit is logged on the job and the case
        (warning only; the eligibility decision is not changed)."""
        for sheet in self.filtered(lambda sheet: sheet.usage_required and sheet.current_usage):
            limit = sheet.warranty_unit_id.usage_limit or sheet.warranty_card_id.usage_limit
            if limit and sheet.current_usage > limit:
                body = Markup('<p>%s</p>') % _(
                    "Warning: current usage %(usage)s of %(sheet)s exceeds the usage limit "
                    "%(limit)s (no automatic decision).", usage=sheet.current_usage,
                    sheet=sheet.name, limit=limit)
                sheet.job_id._message_log(body=body)
                # sudo: technicians may not read the warranty case; audit note only.
                sheet.job_id.warranty_case_id.sudo()._message_log(body=body)

    @api.depends('job_id.name', 'entitlement_id.name', 'product_id.display_name', 'unit_id')
    def _compute_name(self):
        for sheet in self:
            sheet.name = ' - '.join(part for part in (
                sheet.job_id.name, sheet.entitlement_id.name, sheet.product_id.display_name,
                sheet.unit_id.name) if part)

    def _worksheet_record(self):
        """The standard worksheet record of this instance, created on first opening (the
        generated model only requires the task)."""
        self.ensure_one()
        if not self.template_id:
            return False
        model_name = self.template_id.sudo().model_id.model
        record = self._worksheet_existing_record()
        if not record:
            record = self.env[model_name].create(dict([self._worksheet_host()]))
        if (self.worksheet_model, self.worksheet_res_id) != (model_name, record.id):
            # sudo: the link fields are readonly for the technician.
            self.sudo().write({'worksheet_model': model_name, 'worksheet_res_id': record.id})
        return record

    def _worksheet_existing_record(self):
        """The standard worksheet record of this instance, if it was created (never created
        here)."""
        self.ensure_one()
        Model = self.env[self.template_id.sudo().model_id.model]
        if self.worksheet_model == Model._name and self.worksheet_res_id:
            record = Model.browse(self.worksheet_res_id).exists()
            if record:
                return record
        # Task template: one record per task (unique x_project_task_id), also the record of the
        # standard task Worksheet button (approved W4). Warranty Worksheet template: one record
        # per instance.
        field, value = self._worksheet_host()
        return Model.search([(field, '=', value)], limit=1)

    def _worksheet_is_instance_hosted(self):
        return self.template_id.sudo().res_model == self._name

    def _worksheet_host(self):
        """(host field, value) of this instance's checklist record."""
        self.ensure_one()
        if self._worksheet_is_instance_hosted():
            return 'x_warranty_job_worksheet_id', self.id
        return 'x_project_task_id', self.task_id.id

    # ------------------------------------------------------------------ Phase 4.7
    def _warranty_completion_problems(self):
        """Worksheet requirements of Complete Visit (approved K3 / K4, G9): valid usage reading
        when usage-based; checklist and attachment when the company requires them."""
        self.ensure_one()
        problems = []
        if self.usage_required:
            if self.current_usage <= 0 or not self.usage_unit:
                problems.append(_("%s: the current usage reading and its unit are required.",
                                  self.name))
            else:
                try:
                    self._check_usage_reading()
                except ValidationError as error:
                    problems.append(error.args[0])
        company = self.company_id
        if company.warranty_worksheet_checklist_required and self.template_id:
            problems += self._warranty_checklist_problems()
        if company.warranty_worksheet_attachment_required and not self.attachment_ids:
            problems.append(_("%s: at least one attachment is required.", self.name))
        return problems

    def _warranty_checklist_problems(self):
        """Worksheet Checklist Required (approved K3). Verified for 4.7: the template's required
        answers are only checked by the worksheet form in the browser (Studio "Required" is a
        view attribute), not on API writes, and not at all when the worksheet is never opened;
        they are checked here on the saved worksheet: the model's required fields and the
        visible fields required by its form view. A checklist without required answers needs at
        least one answer."""
        self.ensure_one()
        record = self._worksheet_existing_record()
        if not record:
            return [_("%s: the worksheet checklist has not been filled in.", self.name)]
        # sudo: the checklist record and its form view are only read.
        record = record.sudo()
        omitted = set(self.template_id.sudo()._get_qweb_arch_omitted_fields())
        missing = [record._fields[name].string for name in self._worksheet_required_fields(record)
                   if name not in omitted and not self._worksheet_answer_set(record, name, True)]
        if missing:
            return [_("%(sheet)s: required checklist answers missing: %(fields)s.",
                      sheet=self.name, fields=', '.join(sorted(missing)))]
        if not any(self._worksheet_answer_set(record, name, False)
                   for name, field in record._fields.items()
                   if name.startswith('x_') and name not in omitted
                   and not field.compute and not field.related):
            return [_("%s: the worksheet checklist has no answer.", self.name)]
        return []

    @api.model
    def _worksheet_required_fields(self, record):
        """Required fields of the checklist: model level, and top-level form view fields whose
        required expression is true and that are not invisible (as the web form). An expression
        that cannot be evaluated counts as required."""
        names = {name for name, field in record._fields.items()
                 if field.required and name not in models.MAGIC_COLUMNS}
        values = {'context': {}, 'uid': self.env.uid, 'id': record.id}
        for name, field in record._fields.items():
            value = record[name]
            if field.type == 'many2one':
                value = value.id
            elif field.type in ('one2many', 'many2many'):
                value = value.ids
            values[name] = value
        arch = etree.fromstring(record.get_view(view_type='form')['arch'])
        for node in arch.iter('field'):
            name = node.get('name')
            if name not in record._fields or not node.get('required') \
                    or any(parent.tag == 'field' for parent in node.iterancestors()):
                continue
            if any(self._worksheet_eval(element.get('invisible'), values, False)
                   for element in (node, *node.iterancestors())):
                continue
            if self._worksheet_eval(node.get('required'), values, True):
                names.add(name)
        return names

    @api.model
    def _worksheet_eval(self, expression, values, on_error):
        if not expression:
            return False
        try:
            return bool(safe_eval(expression, dict(values)))
        except (ValueError, SyntaxError, ZeroDivisionError):
            return on_error

    @api.model
    def _worksheet_answer_set(self, record, name, required):
        """As the web form: a required boolean / number is always set; for "at least one
        answer" only a checked box or a non-zero number counts."""
        field = record._fields[name]
        value = record[name]
        if field.type in ('boolean', 'integer', 'float', 'monetary'):
            return True if required else bool(value)
        if field.type == 'html':
            return not is_html_empty(value)
        return bool(value)

    @api.model
    def _warranty_report_checklists(self, tasks):
        """{task id: [(instance, checklist record)]} of the Warranty Worksheet (instance-hosted)
        checklists of the visits, for the Field Service report the customer signs (approved:
        sign-off across the worksheet instances). Task-hosted checklists are shown by the
        standard report."""
        result = {}
        # sudo: report / portal rendering of the visit's own checklists.
        for task in (tasks or self.env['project.task']).sudo():
            pairs = []
            for sheet in task.warranty_worksheet_ids:
                if sheet.template_id.report_view_id and sheet._worksheet_is_instance_hosted():
                    record = sheet._worksheet_existing_record()
                    if record:
                        pairs.append((sheet, record))
            if pairs:
                result[task.id] = pairs
        return result

    def action_open_worksheet(self):
        """Open the standard checklist form of this worksheet instance."""
        self.ensure_one()
        if not self.template_id:
            raise UserError(_("%s has no worksheet template: record the reading, notes and "
                              "attachments on the worksheet instance.", self.name))
        record = self._worksheet_record()
        action = self.template_id.action_id.sudo().read()[0]
        context = literal_eval(action.get('context') or '{}')
        action.update({
            'res_id': record.id,
            'views': [(False, 'form')],
            'context': {**context, 'edit': True,
                        'default_%s' % self._worksheet_host()[0]: self._worksheet_host()[1]},
        })
        return action
