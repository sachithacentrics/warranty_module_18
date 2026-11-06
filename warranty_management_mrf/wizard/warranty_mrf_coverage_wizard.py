from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.material_purchase_requisition_coverage import COVERAGE_DECISIONS


class WarrantyMrfCoverageWizard(models.TransientModel):
    """Decide Coverage (mapping 5.2 / D7): a coverage reviewer marks lines of a warranty
    Material Request Covered, Covered (Goodwill) or Not Covered, with a reason. The wizard
    lists the existing lines of the request with a checkbox; lines are never created or
    edited here."""
    _name = 'warranty.mrf.coverage.wizard'
    _description = 'Decide Material Request Coverage'

    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     required=True, readonly=True)
    line_ids = fields.One2many('warranty.mrf.coverage.wizard.line', 'wizard_id', string='Lines')
    decision = fields.Selection(COVERAGE_DECISIONS, string='Decision', required=True)
    reason = fields.Text(string='Reason', required=True)

    @api.model
    def default_get(self, fields_list):
        """One row per line of the request; lines pending a coverage decision preselected."""
        values = super().default_get(fields_list)
        mrf = self.env['material.purchase.requisition'].browse(values.get('requisition_id'))
        if 'line_ids' in fields_list and mrf:
            values['line_ids'] = [(0, 0, {
                'requisition_line_id': line.id,
                'selected': line.coverage_type == 'pending',
            }) for line in mrf.requisition_line_ids]
        return values

    def action_apply(self):
        self.ensure_one()
        lines = self.line_ids.filtered('selected').requisition_line_id
        self.requisition_id._warranty_decide_coverage(lines, self.decision, self.reason)
        return {'type': 'ir.actions.act_window_close'}


class WarrantyMrfCoverageWizardLine(models.TransientModel):
    _name = 'warranty.mrf.coverage.wizard.line'
    _description = 'Decide Material Request Coverage - Line'

    wizard_id = fields.Many2one('warranty.mrf.coverage.wizard', required=True,
                                ondelete='cascade')
    requisition_line_id = fields.Many2one('material.purchase.requisition.line', required=True,
                                          readonly=True, ondelete='cascade')
    selected = fields.Boolean(string='Select')
    product_id = fields.Many2one(related='requisition_line_id.product_id', string='Product')
    qty = fields.Float(related='requisition_line_id.qty', string='Quantity')
    uom = fields.Many2one(related='requisition_line_id.uom', string='Unit of Measure')
    coverage_type = fields.Selection(related='requisition_line_id.coverage_type',
                                     string='Current Coverage Type')
    goodwill = fields.Boolean(related='requisition_line_id.goodwill')
    coverage_default_reason = fields.Char(related='requisition_line_id.coverage_default_reason',
                                          string='Coverage Basis')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_editable(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._check_editable(vals)
        return super().write(vals)

    @api.model
    def _check_editable(self, vals):
        """Only the selection is entered here: products, quantities and the coverage of the
        Material Request lines are never changed through the wizard."""
        if set(vals) - {'wizard_id', 'requisition_line_id', 'selected'}:
            raise UserError(_("Decide Coverage only selects lines; edit the Material Request "
                              "to change them."))
