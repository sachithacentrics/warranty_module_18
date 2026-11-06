from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    # AMC-A08 / F01: an AMC case is linked to its AMC contract and the AMC visits it executes.
    amc_contract_id = fields.Many2one('amc.contract', string='AMC Contract', readonly=True,
                                      copy=False, index=True)
    amc_visit_ids = fields.One2many('amc.contract.visit', 'warranty_case_id',
                                    string='AMC Visits', readonly=True)

    @api.constrains('amc_contract_id', 'case_type', 'helpdesk_ticket_id')
    def _check_amc_contract(self):
        for case in self.filtered('amc_contract_id'):
            contract = case.amc_contract_id
            if case.case_type != 'amc':
                raise ValidationError(_("Warranty case %s is linked to an AMC contract: its Case "
                                        "Type must be AMC.", case.name))
            if contract.company_id != case.company_id \
                    or contract.commercial_partner_id != case.partner_id.commercial_partner_id:
                raise ValidationError(_("AMC contract %(contract)s belongs to another customer or "
                                        "company than warranty case %(case)s.",
                                        contract=contract.name, case=case.name))

    def _warranty_run_checks(self):
        """AMC eligibility (SRS 9.5 "linked AMC entitlement valid", AMC-A08) instead of the
        warranty card / policy checks for AMC cases with a contract; other cases unchanged."""
        self.ensure_one()
        if self.case_type != 'amc' or not self.amc_contract_id:
            return super()._warranty_run_checks()
        return self._amc_run_checks()

    def _amc_run_checks(self):
        self.ensure_one()
        steps = []
        contract = self.amc_contract_id.sudo()
        visits = self.amc_visit_ids.sudo()
        payment_vals = {'payment_eligibility': 'not_required', 'payment_hold': False}
        failure_vals = {'escalation_pending': False}
        # Service date of the warranty checks (approved Q10): the ticket creation date.
        today = self._warranty_check_date()
        if contract.state not in ('active', 'expiring'):
            steps.append((False, _("AMC contract %(contract)s is %(state)s: no AMC service.",
                                   contract=contract.name, state=contract._amc_state_label())))
            return 'not_eligible', steps, payment_vals, failure_vals
        steps.append((True, _("AMC contract %(contract)s is %(state)s (%(start)s - %(end)s).",
                              contract=contract.name, state=contract._amc_state_label(),
                              start=contract.start_date, end=contract.end_date)))
        if contract.start_date and today < contract.start_date \
                or contract.end_date and today > contract.end_date:
            steps.append((False, _("The service date %s is outside the AMC coverage period.",
                                   today)))
            return 'not_eligible', steps, payment_vals, failure_vals
        if not visits:
            steps.append((False, _("No AMC visit is linked to the case: manual review.")))
            return 'manual_review', steps, payment_vals, failure_vals
        wrong = visits.filtered(lambda v: v.contract_id != contract)
        consumed = visits.filtered(lambda v: v.state not in ('scheduled', 'in_progress'))
        if wrong or consumed:
            steps.append((False, _("AMC visits not available: %s.",
                                   ', '.join((wrong | consumed).mapped('name')))))
            return 'not_eligible', steps, payment_vals, failure_vals
        steps.append((True, _("AMC entitlements available: %s.",
                              ', '.join('%s (%s)' % (v.name, v.label) for v in visits))))
        warning = self.overdue_warning
        if warning:
            steps.append((True, _("Overdue Warning (information only): %s", warning)))
        steps.append((True, _("AMC eligibility passed (contract, coverage period, entitlement "
                              "balance).")))
        return 'eligible', steps, payment_vals, failure_vals

    def write(self, vals):
        result = super().write(vals)
        if vals.get('state') in ('rejected', 'closed'):
            for case in self.filtered('amc_visit_ids'):
                case.amc_visit_ids._amc_release(_("warranty case %(case)s %(state)s",
                                                  case=case.name, state=vals['state']))
        return result
