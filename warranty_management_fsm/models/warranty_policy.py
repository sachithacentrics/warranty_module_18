from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WarrantyPolicy(models.Model):
    _inherit = 'warranty.policy'

    # Phase 4.11 (approved Q24 resolution): Requested Items of the warranty cases created by
    # Draft Job from Service (no customer request); Covered Items of the policy only. Empty: the
    # automatic case goes to Manual Review "No Requested Items" (Q24).
    auto_case_item_ids = fields.Many2many(
        'warranty.coverage.item', 'warranty_policy_auto_case_item_rel', 'policy_id', 'item_id',
        string='Automatic Case Requested Items',
        help="Requested Items of the warranty cases created automatically by Draft Job from "
             "Service (Covered Items of this policy).")

    @api.constrains('auto_case_item_ids', 'covered_item_ids')
    def _check_auto_case_items(self):
        for policy in self:
            extra = policy.auto_case_item_ids - policy.covered_item_ids
            if extra:
                raise ValidationError(_(
                    "Automatic Case Requested Items of policy %(policy)s must be Covered Items: "
                    "%(items)s.", policy=policy.name, items=', '.join(extra.mapped('name'))))


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    # Phase 4.11 (approved E2): policy Draft Job from Service, kept at warranty confirmation.
    draft_job_from_service = fields.Boolean(
        string='Draft Job from Service', readonly=True, copy=False,
        help="Snapshot of the policy at warranty confirmation: when a free service reaches its "
             "Alert Date (Due Date without alert days), a Helpdesk ticket, warranty case and, "
             "after approval, a Draft Service Job are created.")

    def _snapshot_free_service_values(self):
        result = super()._snapshot_free_service_values()
        for card in self:
            card.draft_job_from_service = card.policy_id.draft_job_from_service
        return result
