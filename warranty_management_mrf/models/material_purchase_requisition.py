from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.warranty_management_fsm.models.warranty_service_job import CONFIRMED_JOB_STATES

# Phase 5.1 (mapping D22): where a Material Request may be created / linked.
MRF_CASE_STATES = ('approved', 'job_created', 'in_progress', 'chargeable')
MRF_JOB_STATES = CONFIRMED_JOB_STATES
CLOSED_TASK_STATES = ('1_done', '1_canceled')
# Vendor sequence code (material_purchase_requisitions) and the warranty one (mapping D5).
VENDOR_SEQUENCE_CODE = 'purchase.requisition.seq'
WARRANTY_SEQUENCE_CODE = 'warranty.material.request'


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    warranty_case_id = fields.Many2one(
        'warranty.case', string='Warranty Case', readonly=True, copy=False, index=True,
        ondelete='restrict', tracking=True)
    warranty_service_job_id = fields.Many2one(
        'warranty.service.job', string='Service Job', readonly=True, copy=False, index=True,
        ondelete='restrict', tracking=True)
    warranty_task_id = fields.Many2one(
        'project.task', string='Field Service Task', readonly=True, copy=False, index=True,
        ondelete='restrict', tracking=True)
    is_warranty_mrf = fields.Boolean(
        string='Warranty Material Request', compute='_compute_is_warranty_mrf', store=True)
    warranty_helpdesk_ticket_id = fields.Many2one(
        related='warranty_case_id.helpdesk_ticket_id', string='Helpdesk Ticket', store=True)
    warranty_partner_id = fields.Many2one(
        related='warranty_case_id.partner_id', string='Customer', store=True)
    warranty_site_id = fields.Many2one(related='warranty_case_id.site_id', string='Site')
    warranty_card_id = fields.Many2one(related='warranty_case_id.warranty_card_id')
    warranty_unit_id = fields.Many2one(related='warranty_case_id.warranty_unit_id')
    warranty_serial_id = fields.Many2one(related='warranty_case_id.serial_id', string='Serial No.')
    warranty_product_id = fields.Many2one(related='warranty_case_id.product_id',
                                          string='Serviced Product')
    currency_id = fields.Many2one(related='company_id.currency_id')
    estimated_cost = fields.Monetary(
        string='Total Estimated Cost', compute='_compute_estimated_cost', store=True)

    @api.depends('warranty_case_id')
    def _compute_is_warranty_mrf(self):
        for mrf in self:
            mrf.is_warranty_mrf = bool(mrf.warranty_case_id)

    @api.depends('requisition_line_ids.estimated_cost')
    def _compute_estimated_cost(self):
        for mrf in self:
            mrf.estimated_cost = sum(mrf.requisition_line_ids.mapped('estimated_cost'))

    # ------------------------------------------------------------------ numbering
    @api.model_create_multi
    def create(self, vals_list):
        """Warranty requisitions take the MRF/ sequence (mapping D5); the vendor create assigns
        the number, so it runs with a context that redirects its sequence code. Standalone
        requisitions keep the vendor EPR sequence; neither sequence gets gaps."""
        default_case = self.env.context.get('default_warranty_case_id')
        is_warranty = [bool(vals.get('warranty_case_id', default_case)) for vals in vals_list]
        if len(set(is_warranty)) > 1:
            return self.browse().union(*(self.create([vals]) for vals in vals_list))
        if is_warranty[0]:
            self = self.with_context(warranty_mrf_number=True)
        records = super().create(vals_list)
        warranty_records = records.filtered('warranty_case_id')
        warranty_records._warranty_check_source()
        warranty_records._warranty_post_link_notes(_("created"))
        return records

    # ------------------------------------------------------------------ links
    @api.constrains('warranty_case_id', 'warranty_service_job_id', 'warranty_task_id', 'company_id')
    def _check_warranty_links(self):
        for mrf in self:
            case, job, task = mrf.warranty_case_id, mrf.warranty_service_job_id, mrf.warranty_task_id
            if (job or task) and not case:
                raise ValidationError(_("A Material Request linked to a service job or task needs "
                                        "its warranty case."))
            if job and job.warranty_case_id != case:
                raise ValidationError(_("Service job %(job)s does not belong to warranty case "
                                        "%(case)s.", job=job.name, case=case.name))
            # Shared Field Service visit (approved v1): the MRF keeps its own service job.
            if task and job not in (task.warranty_service_job_id | task.warranty_shared_job_ids):
                raise ValidationError(_("Field Service task %(task)s is not a visit of the linked "
                                        "service job.", task=task.display_name))
            if case and case.company_id != mrf.company_id:
                raise ValidationError(_("Material Request %(mrf)s and warranty case %(case)s "
                                        "belong to different companies.",
                                        mrf=mrf.name, case=case.name))

    def write(self, vals):
        if any(field in vals for field in ('warranty_case_id', 'warranty_service_job_id',
                                           'warranty_task_id')) \
                and not self.env.context.get('warranty_mrf_link') \
                and any(mrf.warranty_case_id for mrf in self):
            raise UserError(_("The warranty links of a Material Request cannot be changed."))
        return super().write(vals)

    def _warranty_check_source(self):
        """Mapping D22: the case / job / task must still accept material requests."""
        for mrf in self:
            mrf.warranty_case_id._warranty_mrf_check_allowed()
            if mrf.warranty_service_job_id:
                mrf.warranty_service_job_id._warranty_mrf_check_allowed()
            if mrf.warranty_task_id:
                mrf.warranty_task_id._warranty_mrf_check_allowed()

    @api.model
    def _warranty_mrf_requester(self, company):
        """Mapping D4: the requester is the current user's employee in the company; the vendor
        requires an employee and a department."""
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid), ('company_id', '=', company.id)], limit=1)
        if not employee:
            raise UserError(_("You need an employee linked to your user in %(company)s to request "
                              "materials (Employees app).", company=company.name))
        if not employee.department_id:
            raise UserError(_("Employee %(employee)s has no department; Material Requests need "
                              "the requester's department.", employee=employee.name))
        return employee

    @api.model
    def _warranty_mrf_default_vals(self, case, job=False, task=False):
        """Values of a new warranty Material Request (header auto-fill, mapping 5.1 / D10)."""
        company = case.company_id
        employee = self._warranty_mrf_requester(company)
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
        technician = job and job.main_technician_id
        tech_employee = technician and self.env['hr.employee'].sudo().search(
            [('user_id', '=', technician.id), ('company_id', '=', company.id)], limit=1)
        employee_sudo = employee.sudo()
        dest = (tech_employee and tech_employee.dest_location_id
                or company.warranty_mrf_dest_location_id
                or employee_sudo.dest_location_id or employee_sudo.department_id.dest_location_id)
        reference = ' / '.join(name for name in (case.name, job and job.name,
                                                 task and task.display_name) if name)
        return {
            'warranty_case_id': case.id,
            'warranty_service_job_id': job and job.id or False,
            'warranty_task_id': task and task.id or False,
            'company_id': company.id,
            'employee_id': employee.id,
            'department_id': employee.department_id.id,
            'location_id': (company.warranty_mrf_source_location_id
                            or warehouse.lot_stock_id).id,
            'dest_location_id': dest.id if dest else False,
            'custom_picking_type_id': (company.warranty_mrf_picking_type_id
                                       or warehouse.int_type_id).id,
            'reason': _("Parts for %(reference)s", reference=reference),
        }

    @api.model
    def _warranty_mrf_form_action(self, case, job=False, task=False):
        """Create Material Request: a new form with the warranty values as defaults."""
        case._warranty_mrf_check_allowed()
        if job:
            job._warranty_mrf_check_allowed()
        if task:
            task._warranty_mrf_check_allowed()
        defaults = self._warranty_mrf_default_vals(case, job, task)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Material Request"),
            'res_model': 'material.purchase.requisition',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {'default_%s' % key: value for key, value in defaults.items()},
        }

    def _warranty_link(self, case, job=False, task=False):
        """Link Existing MRF (mapping T1.5): a Draft standalone requisition of the company."""
        self.ensure_one()
        if self.warranty_case_id:
            raise UserError(_("Material Request %(mrf)s is already linked to warranty case "
                              "%(case)s.", mrf=self.name, case=self.warranty_case_id.name))
        if self.state != 'draft':
            raise UserError(_("Only Material Requests in status New can be linked."))
        self.with_context(warranty_mrf_link=True).write({
            'warranty_case_id': case.id,
            'warranty_service_job_id': job and job.id or False,
            'warranty_task_id': task and task.id or False,
        })
        self._warranty_check_source()
        self._warranty_post_link_notes(_("linked"))

    def _warranty_post_link_notes(self, verb):
        """History notes on the case and job (Parts 3 / 4 pattern: logged notes)."""
        for mrf in self:
            body = _("Material Request %(mrf)s %(verb)s by %(user)s.",
                     mrf=mrf.name, verb=verb, user=self.env.user.name)
            for record in (mrf.warranty_case_id, mrf.warranty_service_job_id):
                if record:
                    record.sudo()._message_log(body=body)
            mrf._message_log(body=_("Warranty links: %(links)s.", links=' / '.join(
                name for name in (mrf.warranty_case_id.name, mrf.warranty_service_job_id.name,
                                  mrf.warranty_task_id.display_name) if name)))

    def _warranty_action_view(self):
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_mrf.action_warranty_material_request')
        action['domain'] = [('id', 'in', self.ids)]
        action['context'] = {'create': False}
        if len(self) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')], 'res_id': self.id})
        return action


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'
    # The vendor line has no name field: show and search lines by request and product.
    _rec_names_search = ['product_id', 'requisition_id']

    currency_id = fields.Many2one(related='requisition_id.company_id.currency_id')
    estimated_unit_cost = fields.Monetary(
        string='Estimated Unit Cost', compute='_compute_estimated_unit_cost', store=True,
        readonly=False, help="Product cost in the line's unit of measure (mapping D20).")
    estimated_cost = fields.Monetary(
        string='Estimated Cost', compute='_compute_estimated_cost', store=True)
    lot_ids = fields.Many2many(
        'stock.lot', string='Serial / Lot Numbers', domain="[('product_id', '=', product_id)]",
        help="Optional serial / lot numbers requested (mapping D19).")

    @api.depends('requisition_id.name', 'product_id', 'qty', 'uom')
    def _compute_display_name(self):
        for line in self:
            product = line.product_id.display_name or line.description or _("Line")
            name = _("%(product)s (%(qty)s %(uom)s)", product=product, qty='%g' % line.qty,
                     uom=line.uom.name or '') if line.uom else product
            line.display_name = '%s: %s' % (line.requisition_id.name, name) \
                if line.requisition_id.name else name

    @api.depends('product_id', 'uom')
    def _compute_estimated_unit_cost(self):
        for line in self:
            line.estimated_unit_cost = line._warranty_product_unit_cost()

    def _warranty_product_unit_cost(self):
        """Product cost of the request company in the line's unit of measure."""
        self.ensure_one()
        product = self.product_id.with_company(self.requisition_id.company_id or self.env.company)
        cost = product.standard_price
        if self.uom and product.uom_id and self.uom != product.uom_id:
            cost = product.uom_id._compute_price(cost, self.uom)
        return cost

    @api.depends('qty', 'estimated_unit_cost')
    def _compute_estimated_cost(self):
        for line in self:
            line.estimated_cost = line.qty * line.estimated_unit_cost

    @api.constrains('lot_ids', 'product_id')
    def _check_lot_product(self):
        for line in self:
            # sudo: requesters (Helpdesk / Field Service users) may not read lots.
            if line.sudo().lot_ids.filtered(lambda lot: lot.product_id != line.product_id):
                raise ValidationError(_("The serial / lot numbers of a line must belong to its "
                                        "product."))
