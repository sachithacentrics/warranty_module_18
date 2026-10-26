from odoo import fields, models


class HelpdeskTeam(models.Model):
    _inherit = 'helpdesk.team'

    # Phase 4.10 (SRS 2.6 / 10.4, approved C1): when the job of a chargeable case is created.
    warranty_job_trigger = fields.Selection([
        ('sale_confirmation', 'On Sales Order Confirmation'),
        ('payment', 'On Payment'),
    ], string='Chargeable Job Trigger', default='sale_confirmation',
        help="On Sales Order Confirmation: when the chargeable quotation of the case is confirmed. "
             "On Payment: when that order is fully invoiced and fully paid.")
