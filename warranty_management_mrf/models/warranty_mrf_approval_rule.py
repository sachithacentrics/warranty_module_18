from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Phase 5.3 (design rev. 2): approval levels of the material approval matrix (SRS 16.1).
APPROVAL_LEVELS = [
    ('manager', 'Manager'),
    ('finance', 'Finance'),
    ('gm', 'GM'),
]
COVERAGE_CONDITIONS = [
    ('any', 'Any'),
    ('covered', 'Covered Lines Present'),
    ('not_covered', 'Not Covered Lines Present'),
    ('only_not_covered', 'Only Not Covered Lines'),
]
GOODWILL_CONDITIONS = [
    ('any', 'Any'),
    ('goodwill', 'Goodwill Lines Present'),
]


class WarrantyMrfApprovalRule(models.Model):
    """Material approval rule (design rev. 2, section 3.1): the matching rules of a warranty
    Material Request are combined at submission (strictest, D-C)."""
    _name = 'warranty.mrf.approval.rule'
    _description = 'Warranty Material Approval Rule'
    _order = 'company_id, sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    note = fields.Text()
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company,
        help="Company or branch of the rule; it also applies to the branches of that company.")
    currency_id = fields.Many2one(related='company_id.currency_id')
    min_amount = fields.Monetary(
        string='Minimum Amount', help="Routing amount from (inclusive).")
    max_amount = fields.Monetary(
        string='Maximum Amount', help="Routing amount up to (exclusive); 0 = no upper limit.")
    coverage_condition = fields.Selection(COVERAGE_CONDITIONS, string='Coverage Condition',
                                          default='any', required=True)
    goodwill_condition = fields.Selection(GOODWILL_CONDITIONS, string='Goodwill Condition',
                                          default='any', required=True)
    categ_ids = fields.Many2many(
        'product.category', 'warranty_mrf_approval_rule_categ_rel', 'rule_id', 'categ_id',
        string='Product Categories',
        help="At least one line product in these categories (child categories included).")
    product_ids = fields.Many2many(
        'product.product', 'warranty_mrf_approval_rule_product_rel', 'rule_id', 'product_id',
        string='Products', help="At least one line product among these products.")
    no_approval = fields.Boolean(
        string='No Approval Required',
        help="Explicit authorization to approve matching requests without approvers. Effective "
             "only when every matching rule is a No Approval Required rule.")
    manager_required = fields.Boolean(string='Manager Approval')
    manager_user_ids = fields.Many2many(
        'res.users', 'warranty_mrf_rule_manager_rel', 'rule_id', 'user_id',
        string='Manager Approvers', domain=[('share', '=', False)])
    finance_required = fields.Boolean(string='Finance Approval')
    finance_user_ids = fields.Many2many(
        'res.users', 'warranty_mrf_rule_finance_rel', 'rule_id', 'user_id',
        string='Finance Approvers', domain=[('share', '=', False)])
    gm_required = fields.Boolean(string='GM Approval')
    gm_user_ids = fields.Many2many(
        'res.users', 'warranty_mrf_rule_gm_rel', 'rule_id', 'user_id',
        string='GM Approvers', domain=[('share', '=', False)])

    @api.constrains('no_approval', 'manager_required', 'finance_required', 'gm_required',
                    'manager_user_ids', 'finance_user_ids', 'gm_user_ids', 'min_amount',
                    'max_amount', 'company_id')
    def _check_rule(self):
        for rule in self:
            levels = rule._required_levels()
            if rule.no_approval and levels:
                raise ValidationError(_("Rule %s: No Approval Required excludes approval levels.",
                                        rule.name))
            if not rule.no_approval and not levels:
                raise ValidationError(_("Rule %s needs at least one approval level or No Approval "
                                        "Required.", rule.name))
            for level in levels:
                users = rule._level_users(level)
                if not users:
                    raise ValidationError(_("Rule %(rule)s: the %(level)s level needs approvers.",
                                            rule=rule.name,
                                            level=dict(APPROVAL_LEVELS)[level]))
                if users.filtered(lambda user: user.share
                                  or rule.company_id not in user.company_ids):
                    raise ValidationError(_("Rule %(rule)s: approvers must be internal users "
                                            "allowed in %(company)s.", rule=rule.name,
                                            company=rule.company_id.name))
            if rule.min_amount < 0 or rule.max_amount < 0:
                raise ValidationError(_("Rule %s: amounts cannot be negative.", rule.name))
            if rule.max_amount and rule.max_amount <= rule.min_amount:
                raise ValidationError(_("Rule %s: the maximum amount must be above the minimum "
                                        "amount.", rule.name))

    def unlink(self):
        """Rules used in an approval history are archived, not deleted (audit)."""
        if self.env['warranty.mrf.approval'].sudo().search_count([('rule_ids', 'in', self.ids)]):
            raise UserError(_("Approval rules used by Material Request approvals cannot be "
                              "deleted; archive them instead."))
        return super().unlink()

    def _required_levels(self):
        self.ensure_one()
        return [level for level, _label in APPROVAL_LEVELS if self['%s_required' % level]]

    def _level_users(self, level):
        self.ensure_one()
        return self['%s_user_ids' % level]

    def _matches(self, amount, lines):
        """Amount range, coverage, goodwill and product / category conditions (section 3.3)."""
        self.ensure_one()
        if amount < self.min_amount or (self.max_amount and amount >= self.max_amount):
            return False
        types = set(lines.mapped('coverage_type'))
        if self.coverage_condition == 'covered' and 'covered' not in types:
            return False
        if self.coverage_condition == 'not_covered' and 'not_covered' not in types:
            return False
        if self.coverage_condition == 'only_not_covered' and types != {'not_covered'}:
            return False
        if self.goodwill_condition == 'goodwill' and not any(lines.mapped('goodwill')):
            return False
        if self.categ_ids or self.product_ids:
            products = lines.product_id
            categs = self.env['product.category'].search([('id', 'child_of', self.categ_ids.ids)]) \
                if self.categ_ids else self.env['product.category']
            if not (products & self.product_ids) and not (products.categ_id & categs):
                return False
        return True
