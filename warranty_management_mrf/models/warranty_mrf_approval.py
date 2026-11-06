from odoo import fields, models

from .warranty_mrf_approval_rule import APPROVAL_LEVELS

APPROVAL_LINE_STATES = [
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('skipped', 'Skipped'),
    ('withdrawn', 'Withdrawn'),
    ('superseded', 'Superseded'),
]


class WarrantyMrfApproval(models.Model):
    """Approval history of a warranty Material Request (design rev. 2, section 5): one line per
    required level per submission round, written by the bridge only and never deleted."""
    _name = 'warranty.mrf.approval'
    _description = 'Warranty Material Request Approval'
    _order = 'requisition_id, round desc, sequence, id'

    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     required=True, ondelete='restrict', index=True, readonly=True)
    company_id = fields.Many2one(related='requisition_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    round = fields.Integer(string='Round', readonly=True)
    sequence = fields.Integer(readonly=True)
    level = fields.Selection(APPROVAL_LEVELS + [('none', 'No Approval Required')],
                             string='Level', required=True, readonly=True)
    rule_ids = fields.Many2many('warranty.mrf.approval.rule', 'warranty_mrf_approval_rule_rel',
                                'approval_id', 'rule_id', string='Rules', readonly=True,
                                context={'active_test': False})
    allowed_user_ids = fields.Many2many('res.users', 'warranty_mrf_approval_user_rel',
                                        'approval_id', 'user_id', string='Allowed Approvers',
                                        readonly=True)
    state = fields.Selection(APPROVAL_LINE_STATES, string='Status', default='pending',
                             required=True, readonly=True)
    user_id = fields.Many2one('res.users', string='Decided By', readonly=True)
    decision_date = fields.Datetime(string='Decision Date', readonly=True)
    reason = fields.Text(string='Reason / Comment', readonly=True)
    routing_amount = fields.Monetary(string='Routing Amount', readonly=True)
    covered_amount = fields.Monetary(string='Covered', readonly=True)
    not_covered_amount = fields.Monetary(string='Not Covered', readonly=True)
    goodwill_amount = fields.Monetary(string='Goodwill', readonly=True)
    activity_ids = fields.Many2many('mail.activity', 'warranty_mrf_approval_activity_rel',
                                    'approval_id', 'activity_id', string='Activities',
                                    readonly=True, context={'active_test': False})
