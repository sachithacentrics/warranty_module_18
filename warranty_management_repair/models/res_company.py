from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    # SRS 2.9: customer machines wait here; outside every warehouse (product.py counts all the
    # locations of a warehouse view), so they are never available to Sales.
    warranty_repair_intake_location_id = fields.Many2one(
        'stock.location', string='Warranty Repair Intake Location')
    # SRS 2.9 / 7: dedicated standard operations; their default locations are Backup Stock,
    # Service / Loan With Customer and Returned - Inspection.
    warranty_backup_issue_type_id = fields.Many2one(
        'stock.picking.type', string='Backup Issue Operation Type')
    warranty_backup_return_type_id = fields.Many2one(
        'stock.picking.type', string='Backup Return Operation Type')
    # SRS 2.9 / 17: the SRS names no approver for a backup assessment, so a company list.
    warranty_backup_approver_user_ids = fields.Many2many(
        'res.users', 'warranty_backup_approver_res_users_rel', 'company_id', 'user_id',
        string='Backup Damage / Loss Approvers')
    warranty_backup_charge_product_id = fields.Many2one(
        'product.product', string='Backup Damage / Loss Charge Product')
    # SRS 11, 14: standard transfers of a replacement, created after the approval.
    warranty_replacement_return_type_id = fields.Many2one(
        'stock.picking.type', string='Replacement Return Operation Type')
    warranty_replacement_delivery_type_id = fields.Many2one(
        'stock.picking.type', string='Replacement Delivery Operation Type')
    # SRS 11.2, 16: GM approves full product replacements, Manager / GM indoor and outdoor unit
    # replacements. A company list, like the claim approvers.
    warranty_replacement_gm_user_ids = fields.Many2many(
        'res.users', 'warranty_replacement_gm_res_users_rel', 'company_id', 'user_id',
        string='Replacement GM Approvers')
    warranty_replacement_finance_user_ids = fields.Many2many(
        'res.users', 'warranty_replacement_finance_res_users_rel', 'company_id', 'user_id',
        string='Replacement Finance Approvers')
    # Pending BA decisions: empty stops the request, no default is assumed. B1: SRS 16.1 asks for
    # Finance on a high-value replacement and does not define high value. B3: SRS 11.3 says only
    # "after replacement".
    warranty_replacement_full_finance = fields.Selection(
        [('required', 'Required on every Full Product replacement'),
         ('not_required', 'Not required')],
        string='Full Product: Finance Approval')
    warranty_replacement_extension_base = fields.Selection(
        [('original_end', 'Warranty end date before this replacement'),
         ('delivery', 'Replacement delivery date')],
        string='Fixed Extension Added To')

    @api.constrains('warranty_replacement_return_type_id', 'warranty_replacement_delivery_type_id')
    def _check_warranty_replacement_types(self):
        for company in self:
            back = company.warranty_replacement_return_type_id
            delivery = company.warranty_replacement_delivery_type_id
            if back:
                destination = back.default_location_dest_id
                if back.code != 'incoming' or back.company_id != company or not destination \
                        or not destination.scrap_location and (
                            destination.usage != 'internal' or destination.warehouse_id):
                    raise ValidationError(_(
                        "Operation Type %s must be a Receipt of this company whose default "
                        "destination is a scrap location or an internal location outside its "
                        "warehouses, so that old units are never available to Sales.",
                        back.display_name))
            if delivery and (delivery.code != 'outgoing' or delivery.company_id != company
                             or not delivery.default_location_src_id
                             or delivery.default_location_src_id.usage != 'internal'):
                raise ValidationError(_(
                    "Operation Type %s must be a Delivery of this company with an internal default "
                    "source location.", delivery.display_name))

    def _warranty_backup_charge_product_error(self):
        """A plain service line: no delivery, no warranty card, no task, invoiced as ordered."""
        self.ensure_one()
        product = self.warranty_backup_charge_product_id
        if product and (product.type != 'service' or not product.sale_ok
                        or product.invoice_policy != 'order' or product.warranty_applicable
                        or product.service_tracking != 'no'
                        or product.company_id not in (self, self.browse())):
            return _("The Backup Damage / Loss Charge Product %s must be a sellable service of "
                     "this company, invoiced on ordered quantities, not warranty applicable and "
                     "creating no task or project.", product.display_name)
        return False

    @api.constrains('warranty_backup_charge_product_id')
    def _check_warranty_backup_charge_product(self):
        for company in self:
            error = company._warranty_backup_charge_product_error()
            if error:
                raise ValidationError(error)

    @api.constrains('warranty_backup_issue_type_id', 'warranty_backup_return_type_id')
    def _check_warranty_backup_types(self):
        for company in self:
            issue = company.warranty_backup_issue_type_id
            back = company.warranty_backup_return_type_id
            for picking_type in issue | back:
                source = picking_type.default_location_src_id
                destination = picking_type.default_location_dest_id
                if picking_type.code != 'internal' or picking_type.company_id != company \
                        or not source or not destination or source == destination \
                        or any(location.usage != 'internal' or location.company_id != company
                               or location.warehouse_id for location in source | destination):
                    raise ValidationError(_(
                        "Operation Type %(type)s must be an Internal Transfer of %(company)s "
                        "between two internal locations outside its warehouses, so that backup "
                        "units are never available to Sales.", type=picking_type.display_name,
                        company=company.name))
            if issue and back and (
                    issue.default_location_dest_id != back.default_location_src_id
                    or back.default_location_dest_id == issue.default_location_src_id):
                raise ValidationError(_(
                    "The Backup Return Operation Type must receive from the location the issue "
                    "sends to, into a separate inspection location (not Backup Stock)."))

    @api.constrains('warranty_repair_intake_location_id')
    def _check_warranty_repair_intake_location(self):
        for company in self:
            location = company.warranty_repair_intake_location_id
            if location and (location.usage != 'internal' or location.company_id != company
                             or location.warehouse_id):
                raise ValidationError(_(
                    "The Warranty Repair Intake Location of %(company)s must be an internal "
                    "location of that company, outside its warehouses (for example under "
                    "Physical Locations).", company=company.name))
