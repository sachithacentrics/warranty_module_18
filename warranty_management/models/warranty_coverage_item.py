from odoo import fields, models


class WarrantyCoverageItem(models.Model):
    _name = 'warranty.coverage.item'
    _description = 'Warranty Coverage Item'
    _order = 'name'

    name = fields.Char(string='Coverage Item', required=True, translate=True)
    active = fields.Boolean(string='Active', default=True)
