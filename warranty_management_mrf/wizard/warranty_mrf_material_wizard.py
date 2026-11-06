from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

MATERIAL_MODES = [
    ('use', 'Confirm Material Usage'),
    ('full', 'Confirm Full Consumption'),
    ('return', 'Return Unused'),
    ('keep', 'Customer Keeps'),
    ('customer_return', 'Customer Return'),
    ('cancel', 'Cancel Remaining'),
]
# Authorisation checked by the request for each mode (and again by every action).
MODE_ACCESS = {'use': 'record', 'full': 'record', 'return': 'record', 'keep': 'commercial',
               'customer_return': 'commercial', 'cancel': 'cancel'}
REASON_MODES = ('keep', 'customer_return', 'cancel')


class WarrantyMrfMaterialWizard(models.TransientModel):
    """Phase 5.6 material actions on the lines of one or more warranty Material Requests of a
    service job / visit: the rows are the existing request lines; nothing is created on the
    request lines themselves (quantities, serials and checks by the request methods)."""
    _name = 'warranty.mrf.material.wizard'
    _description = 'Warranty Material Usage / Returns'

    mode = fields.Selection(MATERIAL_MODES, required=True, readonly=True)
    requisition_ids = fields.Many2many('material.purchase.requisition', string='Material Requests',
                                       readonly=True)
    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True)
    task_id = fields.Many2one('project.task', string='Visit', readonly=True)
    line_ids = fields.One2many('warranty.mrf.material.wizard.line', 'wizard_id', string='Lines')
    note = fields.Text(string='Notes / Reason')
    reason_required = fields.Boolean(compute='_compute_reason_required')
    confirm_full = fields.Boolean(string='I confirm that all listed parts were used / installed')

    @api.depends('mode')
    def _compute_reason_required(self):
        for wizard in self:
            wizard.reason_required = wizard.mode in REASON_MODES

    # ------------------------------------------------------------------ open
    @api.model
    def _warranty_open(self, mrf, mode, task=False):
        mrf._warranty_check_material_open()
        mrf._warranty_check_material_access(MODE_ACCESS[mode])
        return self._warranty_create(mrf, mode, job=mrf.warranty_service_job_id, task=task)

    @api.model
    def _warranty_open_for_job(self, job, mode, task=False):
        # sudo: the job's requests are listed for technicians / coordinators; every action
        # checks the user again.
        mrfs = job.sudo().material_request_ids.filtered(
            lambda mrf: not mrf._warranty_material_open_error())
        if not mrfs:
            raise UserError(_("Service job %s has no approved warranty Material Request with "
                              "material to record.", job.name))
        # Checked as the current user (superuser mode would always pass).
        mrfs = self.env['material.purchase.requisition'].browse(mrfs.ids).filtered(
            lambda mrf: mrf._warranty_has_material_access(MODE_ACCESS[mode]))
        if not mrfs:
            raise AccessError(_("Only the technicians of the service job, Service Coordinators "
                                "and Store users record used or returned material."))
        return self._warranty_create(mrfs, mode, job=job, task=task)

    @api.model
    def _warranty_rows(self, mrfs, mode):
        rows = []
        for mrf in mrfs.sudo():
            for line in mrf.requisition_line_ids.filtered(lambda line: not line.chargeable_declined):
                customer = line._warranty_is_customer_line()
                if mode == 'cancel':
                    limit = line._warranty_cancellable_qty()
                elif mode in ('keep', 'customer_return') and not customer:
                    continue
                elif mode == 'return' and customer:
                    continue
                else:
                    limit = line.to_reconcile_qty
                if limit <= 0:
                    continue
                balance = line._warranty_lot_balance() if line.product_id.tracking != 'none' \
                    else {}
                lots = self.env['stock.lot'].union(*balance) if balance else self.env['stock.lot']
                qty, default_lots = 0.0, self.env['stock.lot']
                if mode in ('full', 'return'):
                    qty = limit
                    if line.product_id.tracking == 'serial' and len(lots) == limit:
                        default_lots = lots
                    elif line.product_id.tracking == 'lot' and len(lots) == 1:
                        default_lots = lots
                rows.append({'line_id': line.id, 'max_qty': limit, 'qty': qty,
                             'available_lot_ids': [(6, 0, lots.ids)],
                             'lot_ids': [(6, 0, default_lots.ids)]})
        return rows

    @api.model
    def _warranty_create(self, mrfs, mode, job=False, task=False):
        rows = self._warranty_rows(mrfs, mode)
        if not rows:
            raise UserError(_("Nothing to process for %(action)s on %(mrfs)s.",
                              action=dict(MATERIAL_MODES)[mode],
                              mrfs=', '.join(mrfs.mapped('name'))))
        wizard = self.create({
            'mode': mode,
            'requisition_ids': [(6, 0, mrfs.ids)],
            'job_id': job.id if job else False,
            'task_id': task.id if task else False,
            'line_ids': [(0, 0, row) for row in rows],
        })
        action = {
            'type': 'ir.actions.act_window',
            'name': dict(MATERIAL_MODES)[mode],
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
        if mode == 'use':
            action['views'] = [(self.env.ref(
                'warranty_management_mrf.warranty_mrf_usage_wizard_view_form').id, 'form')]
        return action

    def action_all_used(self):
        """Shortcut of Confirm Material Usage: the existing Confirm Full Consumption step."""
        self.ensure_one()
        return self._warranty_create(self.requisition_ids, 'full', job=self.job_id,
                                     task=self.task_id)

    # ------------------------------------------------------------------ apply
    def action_apply(self):
        self.ensure_one()
        if self.mode in REASON_MODES and not (self.note or '').strip():
            raise UserError(_("A reason is required."))
        if self.mode == 'full' and not self.confirm_full:
            raise UserError(_("Tick the confirmation: all listed parts were used / installed."))
        done = False
        for mrf in self.requisition_ids:
            if self.mode == 'full':
                mrf._warranty_confirm_full_consumption(task=self.task_id, note=self.note)
                done = True
                continue
            rows = [(row.line_id, row.qty, row.lot_ids) for row in self.line_ids
                    if row.line_id.requisition_id == mrf and row.qty]
            if not rows:
                continue
            if self.mode == 'use':
                mrf._warranty_record_usage(rows, task=self.task_id, note=self.note)
            elif self.mode == 'return':
                mrf._warranty_return_unused(rows, note=self.note, task=self.task_id)
            elif self.mode == 'keep':
                mrf._warranty_customer_keep(rows, self.note)
            elif self.mode == 'customer_return':
                mrf._warranty_customer_return(rows, self.note)
            elif self.mode == 'cancel':
                mrf._warranty_cancel_remaining(rows, self.note)
            done = True
        if not done:
            raise UserError(_("Enter a quantity on at least one line."))
        return {'type': 'ir.actions.act_window_close'}


class WarrantyMrfMaterialWizardLine(models.TransientModel):
    _name = 'warranty.mrf.material.wizard.line'
    _description = 'Warranty Material Usage / Returns - Line'

    wizard_id = fields.Many2one('warranty.mrf.material.wizard', required=True,
                                ondelete='cascade')
    line_id = fields.Many2one('material.purchase.requisition.line', required=True,
                              readonly=True, ondelete='cascade')
    requisition_id = fields.Many2one(related='line_id.requisition_id', string='Material Request')
    product_id = fields.Many2one(related='line_id.product_id', string='Product')
    uom_id = fields.Many2one(related='line_id.uom', string='Unit of Measure')
    coverage_type = fields.Selection(related='line_id.coverage_type')
    tracking = fields.Selection(related='line_id.product_id.tracking')
    issued_qty = fields.Float(related='line_id.issued_qty', string='Issued / Delivered')
    max_qty = fields.Float(string='Available', readonly=True, digits='Product Unit of Measure')
    qty = fields.Float(string='Quantity', digits='Product Unit of Measure')
    requested_qty = fields.Float(related='line_id.qty', string='Requested')
    used_qty = fields.Float(related='line_id.used_qty', string='Already Used')
    returned_qty = fields.Float(related='line_id.returned_qty', string='Returned')
    left_unused_qty = fields.Float(string='Left Unused', compute='_compute_left_unused_qty',
                                   digits='Product Unit of Measure')
    available_lot_ids = fields.Many2many('stock.lot', 'warranty_mrf_material_wizard_avail_lot_rel',
                                         'row_id', 'lot_id', readonly=True)
    lot_ids = fields.Many2many('stock.lot', 'warranty_mrf_material_wizard_lot_rel', 'row_id',
                               'lot_id', string='Serial / Lot Numbers')

    @api.depends('max_qty', 'qty')
    def _compute_left_unused_qty(self):
        for row in self:
            row.left_unused_qty = max(row.max_qty - row.qty, 0.0)


class WarrantyMrfReverseWizard(models.TransientModel):
    _name = 'warranty.mrf.reverse.wizard'
    _description = 'Reverse Warranty Material Entry'

    consumption_id = fields.Many2one('warranty.mrf.consumption', string='Entry', required=True,
                                     readonly=True)
    reason = fields.Text(string='Reason', required=True)

    def action_reverse(self):
        self.ensure_one()
        self.consumption_id._warranty_reverse(self.reason)
        return {'type': 'ir.actions.act_window_close'}


class WarrantyMrfCancelWizard(models.TransientModel):
    _name = 'warranty.mrf.cancel.wizard'
    _description = 'Cancel Warranty Material Request'

    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     required=True, readonly=True)
    reason = fields.Text(string='Reason', required=True)

    def action_cancel(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to cancel a warranty Material Request."))
        self.requisition_id.with_context(warranty_cancel_reason=reason).action_cancel()
        return {'type': 'ir.actions.act_window_close'}
