from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_mrf_source_location_id = fields.Many2one(
        related='company_id.warranty_mrf_source_location_id', readonly=False,
        domain="[('usage', '=', 'internal'), ('company_id', 'in', (company_id, False))]",
        help="The stock location that warranty material requests take parts from. If empty, "
             "the stock of the company's first warehouse is used.")
    warranty_mrf_dest_location_id = fields.Many2one(
        related='company_id.warranty_mrf_dest_location_id', readonly=False,
        domain="[('usage', '=', 'internal'), ('company_id', 'in', (company_id, False))]",
        help="Where requested parts are sent when the main technician has no destination "
             "location of their own.")
    warranty_mrf_picking_type_id = fields.Many2one(
        related='company_id.warranty_mrf_picking_type_id', readonly=False,
        domain="[('code', '=', 'internal'), ('company_id', '=', company_id)]",
        help="The internal transfer type used to move warranty parts. If empty, the internal "
             "transfers of the company's first warehouse are used.")
    warranty_mrf_approval_matrix = fields.Boolean(
        related='company_id.warranty_mrf_approval_matrix', readonly=False,
        help="If enabled, warranty material requests are approved by the approvers named in "
             "the Material Approval Rules. If disabled, the standard material requisition "
             "approval is used.")
    warranty_mrf_approval_deadline_days = fields.Integer(
        related='company_id.warranty_mrf_approval_deadline_days', readonly=False,
        help="The number of days approvers have to complete their material approval task.")
    warranty_mrf_release_trigger = fields.Selection(
        related='company_id.warranty_mrf_release_trigger', readonly=False,
        help="When customer-paid parts of a parts quotation can be delivered: as soon as the "
             "quotation is confirmed, or only after it is paid. Applies to new parts "
             "quotations.")
    warranty_mrf_release_exception_user_ids = fields.Many2many(
        related='company_id.warranty_mrf_release_exception_user_ids', readonly=False,
        help="Users who can release customer-paid parts before payment, giving a reason. "
             "Used when parts are released on payment.")
