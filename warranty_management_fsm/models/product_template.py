from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Approved shared-worksheet fix: Field Service (task) or Warranty Worksheet (instance)
    # templates.
    warranty_worksheet_template_id = fields.Many2one(
        domain="[('res_model', 'in', ('project.task', 'warranty.job.worksheet')), "
               "'|', ('company_id', '=', False), ('company_id', '=', company_id)]")
