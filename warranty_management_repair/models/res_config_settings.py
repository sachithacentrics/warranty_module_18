from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_repair_intake_location_id = fields.Many2one(
        related='company_id.warranty_repair_intake_location_id', readonly=False,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id), "
               "('warehouse_id', '=', False)]",
        help="Where customer machines are received for a workshop repair. It must be an internal "
             "location outside the warehouses, so that the machines are never available to Sales.")
    warranty_backup_issue_type_id = fields.Many2one(
        related='company_id.warranty_backup_issue_type_id', readonly=False,
        domain="[('code', '=', 'internal'), ('company_id', '=', company_id)]",
        help="The internal transfer that lends a backup unit to a customer. Its default locations "
             "are Backup Stock and Service / Loan With Customer, both outside the warehouses.")
    warranty_backup_return_type_id = fields.Many2one(
        related='company_id.warranty_backup_return_type_id', readonly=False,
        domain="[('code', '=', 'internal'), ('company_id', '=', company_id)]",
        help="The internal transfer that receives a backup unit back. Its default locations are "
             "Service / Loan With Customer and Returned - Inspection, both outside the warehouses.")
    warranty_backup_approver_user_ids = fields.Many2many(
        related='company_id.warranty_backup_approver_user_ids', readonly=False,
        help="Who approve damage and loss assessments of backup units. The user who submitted an "
             "assessment cannot approve it.")
    warranty_backup_charge_product_id = fields.Many2one(
        related='company_id.warranty_backup_charge_product_id', readonly=False,
        domain="[('type', '=', 'service'), ('sale_ok', '=', True), "
               "('invoice_policy', '=', 'order'), ('warranty_applicable', '=', False), "
               "('service_tracking', '=', 'no'), ('company_id', 'in', [company_id, False])]",
        help="Select the service product used to charge customers for damaged or lost backup units. "
             "The charge amount is based on the approved assessment.")
    warranty_replacement_return_type_id = fields.Many2one(
        related='company_id.warranty_replacement_return_type_id', readonly=False,
        domain="[('code', '=', 'incoming'), ('company_id', '=', company_id)]",
        help="The receipt that brings the old unit back from the customer. Its default destination "
             "must be outside the warehouses, so that the old unit is never available to Sales.")
    warranty_replacement_delivery_type_id = fields.Many2one(
        related='company_id.warranty_replacement_delivery_type_id', readonly=False,
        domain="[('code', '=', 'outgoing'), ('company_id', '=', company_id)]",
        help="The delivery that sends the new unit to the customer. New serials are taken from its "
             "default source location.")
    warranty_replacement_gm_user_ids = fields.Many2many(
        related='company_id.warranty_replacement_gm_user_ids', readonly=False,
        help="Who approve Full Product, Indoor Unit and Outdoor Unit replacements as Manager / "
             "General Manager. The user who submitted a request cannot approve it.")
    warranty_replacement_finance_user_ids = fields.Many2many(
        related='company_id.warranty_replacement_finance_user_ids', readonly=False,
        help="Who approve replacements for Finance when Finance approval is needed. One person "
             "cannot sign both levels of a request.")
    warranty_replacement_full_finance = fields.Selection(
        related='company_id.warranty_replacement_full_finance', readonly=False,
        help="Whether a Full Product replacement also needs Finance approval. No Full Product "
             "request can be submitted until this is set.")
    warranty_replacement_extension_base = fields.Selection(
        related='company_id.warranty_replacement_extension_base', readonly=False,
        help="What the Add Fixed Extension policy adds to. That policy cannot be used until "
             "this is set.")
