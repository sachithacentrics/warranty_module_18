from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WarrantyPolicyServiceOffset(models.Model):
    """Fixed Offsets schedule lines. Lines with policy_id are the configuration;
    lines with warranty_card_id are the read-only snapshot taken at warranty confirmation."""
    _name = 'warranty.policy.service.offset'
    _description = 'Warranty Free Service Offset'
    _order = 'service_no, id'

    policy_id = fields.Many2one(
        'warranty.policy', string='Warranty Policy', ondelete='cascade', index=True)
    warranty_card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', ondelete='cascade', index=True, readonly=True)
    service_no = fields.Integer(string='Service No.', required=True)
    offset = fields.Integer(string='Offset', required=True)
    offset_unit = fields.Selection([
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string='Offset Unit', required=True)
    company_id = fields.Many2one(
        'res.company', string='Company', compute='_compute_company_id', store=True, index=True)

    _sql_constraints = [
        ('policy_or_card',
         'CHECK ((policy_id IS NULL) != (warranty_card_id IS NULL))',
         'A service offset belongs either to a warranty policy or to a warranty card snapshot.'),
        ('policy_service_no_unique', 'UNIQUE (policy_id, service_no)',
         'Each service number can only have one offset per warranty policy.'),
        ('card_service_no_unique', 'UNIQUE (warranty_card_id, service_no)',
         'Each service number can only have one offset per warranty card.'),
    ]

    @api.depends('policy_id.company_id', 'warranty_card_id.company_id')
    def _compute_company_id(self):
        for line in self:
            line.company_id = line.warranty_card_id.company_id or line.policy_id.company_id

    @api.constrains('service_no', 'offset')
    def _check_values(self):
        for line in self:
            if line.service_no < 1:
                raise ValidationError(_("Service numbers of service offsets start at 1."))
            if line.offset <= 0:
                raise ValidationError(_("The offset of service %s must be greater than zero.",
                                        line.service_no))
