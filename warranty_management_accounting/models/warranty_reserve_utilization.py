from collections import defaultdict
from datetime import timedelta

from markupsafe import Markup

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_amount

from .warranty_accounting_config import ACCOUNTING_READ_GROUPS, COMPANY_CONFIG_FIELDS

# Figure 7 / SRS 17 (doc/figure7_accounting_integration.md). Covered spare-part issue uses
# standard Odoo stock accounting: the cost is captured from stock valuation on the case and, with
# automated valuation, posted by Odoo itself to the Warranty Consumption location's stock
# valuation accounts (company policy: Warranty Expense or Warranty Provision / Reserve). Nothing
# is posted here at issue. Warranty-specific control: Finance applies the posted warranty cost of
# a completed case against the reserve with a DRAFT standard journal entry (Dr Provision /
# Cr Warranty Expense) that it reviews and posts.
GROUP_POSTER = 'account.group_account_user'
RESERVE_POLICY_FIELDS = ('warranty_reserve_subcontract_eligible',
                         'warranty_reserve_goodwill_eligible')
UTILIZATION_KINDS = [('utilization', 'Reserve Utilization')]
UTILIZATION_MOVE_FIELDS = {'warranty_b2_kind', 'warranty_b2_case_id', 'warranty_b2_eligible_amount',
                           'warranty_b2_available_amount'}
UTILIZATION_LINE_LOCKED = {'account_id', 'debit', 'credit', 'balance', 'amount_currency',
                           'currency_id', 'move_id', 'product_id', 'quantity'}
CASE_UTILIZATION_STATES = ('completed', 'closed')
# Same text as the setting's help and title in the view (the settings help test compares them).
RESERVE_HELP = ("Finance applies the posted warranty cost of a completed or closed case against "
                "the warranty reserve with a draft journal entry (Dr Warranty Provision / Reserve, "
                "Cr Warranty Expense) and posts it. Covered spare parts follow standard Odoo stock "
                "accounting; nothing is posted automatically.")


def _check_poster(env, text=None):
    """Bookkeeper or Administrator; the real user counts, also in sudo."""
    if env.uid != SUPERUSER_ID and not env.user.has_group(GROUP_POSTER):
        raise AccessError(text or _("Only Accounting Bookkeepers or Administrators can do this "
                                    "for warranty reserve entries."))


class ResCompany(models.Model):
    _inherit = 'res.company'
    _warranty_accounting_fields = COMPANY_CONFIG_FIELDS + RESERVE_POLICY_FIELDS

    warranty_reserve_subcontract_eligible = fields.Boolean(
        string='Subcontract Cost Uses the Reserve', tracking=True, copy=False,
        groups=ACCOUNTING_READ_GROUPS,
        help="Off by default (a Finance policy). When on, approved subcontract cost lines of the "
             "case whose vendor bill lines are posted to Warranty Expense count for reserve "
             "utilization.")
    warranty_reserve_goodwill_eligible = fields.Boolean(
        string='Goodwill Uses the Reserve', tracking=True, copy=False,
        groups=ACCOUNTING_READ_GROUPS,
        help="Off by default: goodwill parts stay in Warranty Expense, shown separately.")

    def _warranty_b2_locked(self, date):
        self.ensure_one()
        return self.sudo()._get_lock_date_violations(
            date, fiscalyear=True, sale=False, purchase=False, tax=False, hard=True)

    def _warranty_b2_open_date(self, date):
        """(accounting date, note): the date itself, or the first unlocked day after it."""
        self.ensure_one()
        locks = self._warranty_b2_locked(date)
        if not locks:
            return date, False
        first = max(lock[0] for lock in locks) + timedelta(days=1)
        return first, _("%(date)s is in a locked period: dated %(first)s, the first open day.",
                        date=date, first=first)

    # ------------------------------------------------------------------ configuration status
    def _warranty_parts_categories(self):
        """Categories of the storable products on covered or goodwill request lines."""
        self.ensure_one()
        lines = self.env['material.purchase.requisition.line'].sudo().search([
            ('requisition_id.company_id', '=', self.id), ('product_id.is_storable', '=', True),
            '|', ('coverage_type', '=', 'covered'), ('goodwill', '=', True)])
        return lines.product_id.categ_id.with_company(self)

    def _warranty_accounting_status(self):
        """Read-only status for Finance: what is missing for reserve utilization and how covered
        spare parts are accounted by standard Odoo (nothing here blocks the operations)."""
        self.ensure_one()
        company = self.sudo()
        lines = []
        missing = [label for value, label in (
            (company.warranty_accounting_journal_id, _("Warranty Accounting Journal")),
            (company.warranty_expense_account_id, _("Warranty Expense Account")),
            (company.warranty_provision_account_id, _("Warranty Provision / Reserve Account")),
        ) if not value]
        if missing:
            lines.append(_("Reserve utilization needs: %s.", ', '.join(missing)))
        else:
            lines.append(_("Reserve utilization: ready (Finance creates and posts it per case)."))
        if not company.warranty_claim_recovery_account_id:
            lines.append(_("Vendor recovery: the Vendor Recovery Account is not set (draft "
                           "vendor credit notes cannot be created from claims)."))
        categories = company._warranty_parts_categories()
        automated = categories.filtered(lambda categ: categ.property_valuation == 'real_time')
        manual = categories - automated
        if manual:
            lines.append(_("Manual valuation (%s): issuing parts creates no journal entry; the "
                           "actual cost from stock valuation is recorded on the case. Parts cost "
                           "is then not in Warranty Expense, so it does not count for reserve "
                           "utilization.", ', '.join(manual.mapped('complete_name'))))
        if automated:
            location = company.warranty_mrf_consumption_location_id
            incoming = location.valuation_in_account_id
            outgoing = location.valuation_out_account_id
            if incoming and outgoing:
                lines.append(_(
                    "Automated valuation (%(categories)s): Odoo posts each use Dr %(incoming)s / "
                    "Cr Stock Valuation, and each reversal Dr Stock Valuation / Cr %(outgoing)s.",
                    categories=', '.join(automated.mapped('complete_name')),
                    incoming=incoming.display_name, outgoing=outgoing.display_name))
            else:
                lines.append(_(
                    "Automated valuation (%(categories)s): the %(location)s location has no "
                    "Stock Valuation Accounts (Incoming / Outgoing), so Odoo posts parts used to "
                    "the category's Stock Output account. Set them to the account your policy "
                    "uses (Warranty Expense, or Warranty Provision / Reserve) in Inventory > "
                    "Configuration > Locations.",
                    categories=', '.join(automated.mapped('complete_name')),
                    location=location.display_name or _("Warranty Consumption")))
        if not categories:
            lines.append(_("No covered spare parts used yet."))
        return '\n'.join('- %s' % line for line in lines)

    # ------------------------------------------------------------------ reserve
    def _warranty_reserve_available(self, date=None, exclude=None):
        """Posted credits minus debits on the reserve account (now and at the date, the lower),
        minus every unposted utilization draft except `exclude`."""
        self.ensure_one()
        company = self.sudo()
        account = company.warranty_provision_account_id
        if not account:
            return 0.0
        Line = self.env['account.move.line'].sudo()
        base = [('account_id', '=', account.id), ('company_id', '=', company.id)]

        def balance(domain):
            lines = Line.search(base + domain)
            return sum(lines.mapped('credit')) - sum(lines.mapped('debit'))

        posted = balance([('parent_state', '=', 'posted')])
        if date:
            posted = min(posted, balance([('parent_state', '=', 'posted'), ('date', '<=', date)]))
        drafts = Line.search(base + [('parent_state', '=', 'draft'),
                                     ('move_id.warranty_reserve_movement', '=', 'utilization')])
        if exclude:
            drafts = drafts.filtered(lambda line: line.move_id not in exclude)
        pending = sum(drafts.mapped('debit')) - sum(drafts.mapped('credit'))
        return company.currency_id.round(posted - pending)


class AccountMove(models.Model):
    _inherit = 'account.move'

    warranty_b2_kind = fields.Selection(UTILIZATION_KINDS, string='Warranty Entry Type',
                                        readonly=True, copy=False, index='btree_not_null')
    warranty_b2_case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True,
                                          copy=False, index='btree_not_null', ondelete='restrict')
    warranty_b2_eligible_amount = fields.Monetary(
        string='Eligible Cost at Creation', readonly=True, copy=False,
        currency_field='company_currency_id')
    warranty_b2_available_amount = fields.Monetary(
        string='Available Reserve at Creation', readonly=True, copy=False,
        currency_field='company_currency_id')

    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS account_move_warranty_b2_utilization_draft_uniq
                ON account_move (warranty_b2_case_id)
             WHERE warranty_b2_kind = 'utilization' AND state = 'draft' AND state != 'cancel'""")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(UTILIZATION_MOVE_FIELDS & set(vals) for vals in vals_list):
            raise UserError(_("Warranty reserve entries are created from the warranty case."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if UTILIZATION_MOVE_FIELDS & set(vals):
                raise UserError(_("The warranty links of a journal entry cannot be changed."))
            if 'line_ids' in vals and self.filtered('warranty_b2_kind'):
                raise UserError(_("The lines of a warranty reserve entry cannot be changed: "
                                  "cancel it instead."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self.filtered('warranty_b2_kind'):
            raise UserError(_("Warranty reserve entries are cancelled, never deleted."))
        return super().unlink()

    def _warranty_utilization_check_post(self):
        """Rights, lock dates, and the utilization (or its standard reversal) within its limits,
        recalculated when Finance posts."""
        moves = self.sudo().filtered(
            lambda move: move.warranty_b2_kind or move.reversed_entry_id.warranty_b2_kind)
        if not moves:
            return
        _check_poster(self.env, _("Only Accounting Bookkeepers or Administrators can post "
                                  "warranty reserve entries."))
        moves._check_fiscal_lock_dates()
        for move in moves:
            currency = move.company_id.currency_id
            source = move.reversed_entry_id
            if source.warranty_b2_kind:
                if source.state != 'posted':
                    raise UserError(_("Post %s before its reversal.", source.display_name))
                done = sum(source.reversal_move_ids.filtered(
                    lambda other: other.state == 'posted' and other != move
                ).mapped('amount_total'))
                if currency.compare_amounts(move.amount_total, source.amount_total - done) > 0:
                    raise UserError(_("The reversal of %(entry)s is above what remains of it "
                                      "(%(remaining)s).", entry=source.display_name,
                                      remaining=source.amount_total - done))
            if move.warranty_b2_kind == 'utilization':
                figures = move.warranty_b2_case_id._warranty_reserve_figures(exclude=move)
                available = move.company_id._warranty_reserve_available(move.date, exclude=move)
                if currency.compare_amounts(move.amount_total, figures['eligible']) > 0:
                    raise UserError(_(
                        "%(entry)s is above the eligible posted warranty cost of the case "
                        "(%(eligible)s). Cancel it and create it again.",
                        entry=move.display_name, eligible=figures['eligible']))
                if currency.compare_amounts(move.amount_total, available) > 0:
                    raise UserError(_(
                        "%(entry)s is above the available posted reserve (%(available)s). Cancel "
                        "it and create it again.", entry=move.display_name, available=available))

    def _post(self, soft=True):
        self._warranty_utilization_check_post()
        return super()._post(soft=soft)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _warranty_check_utilization_locked(self, moves):
        if not self.env.su and moves.filtered('warranty_b2_kind'):
            raise UserError(_("The lines of a warranty reserve entry cannot be changed: "
                              "cancel it instead."))

    @api.model_create_multi
    def create(self, vals_list):
        moves = self.env['account.move'].browse(
            {vals['move_id'] for vals in vals_list if vals.get('move_id')})
        self._warranty_check_utilization_locked(moves)
        return super().create(vals_list)

    def write(self, vals):
        if UTILIZATION_LINE_LOCKED & set(vals):
            self._warranty_check_utilization_locked(self.move_id)
        return super().write(vals)

    def unlink(self):
        self._warranty_check_utilization_locked(self.move_id)
        return super().unlink()


class WarrantyCase(models.Model):
    _inherit = 'warranty.case'

    warranty_b2_move_ids = fields.One2many('account.move', 'warranty_b2_case_id',
                                           string='Warranty Reserve Entries', readonly=True,
                                           groups=ACCOUNTING_READ_GROUPS)
    warranty_b2_currency_id = fields.Many2one(related='company_id.currency_id',
                                              string='Accounting Currency')
    warranty_b2_move_count = fields.Integer(string='Warranty Reserve Entry Count',
                                            compute='_compute_warranty_reserve_figures',
                                            compute_sudo=True, groups=ACCOUNTING_READ_GROUPS)
    warranty_reserve_parts_amount = fields.Monetary(
        string='Covered Parts Posted to Warranty Expense',
        compute='_compute_warranty_reserve_figures', compute_sudo=True,
        currency_field='warranty_b2_currency_id', groups=ACCOUNTING_READ_GROUPS,
        help="Posted stock accounting entries of the case's covered parts on the Warranty Expense "
             "account (automated valuation), uses minus reversals, goodwill included.")
    warranty_reserve_goodwill_amount = fields.Monetary(
        string='Of Which Goodwill', compute='_compute_warranty_reserve_figures',
        compute_sudo=True, currency_field='warranty_b2_currency_id',
        groups=ACCOUNTING_READ_GROUPS)
    warranty_reserve_recovered_amount = fields.Monetary(
        string='Posted Vendor Recovery (Parts)', compute='_compute_warranty_reserve_figures',
        compute_sudo=True, currency_field='warranty_b2_currency_id', groups=ACCOUNTING_READ_GROUPS)
    warranty_reserve_subcontract_amount = fields.Monetary(
        string='Eligible Subcontract Cost', compute='_compute_warranty_reserve_figures',
        compute_sudo=True, currency_field='warranty_b2_currency_id', groups=ACCOUNTING_READ_GROUPS)
    warranty_reserve_utilized_amount = fields.Monetary(
        string='Reserve Utilized (Draft and Posted)', compute='_compute_warranty_reserve_figures',
        compute_sudo=True, currency_field='warranty_b2_currency_id', groups=ACCOUNTING_READ_GROUPS)
    warranty_reserve_eligible_amount = fields.Monetary(
        string='Eligible for Utilization', compute='_compute_warranty_reserve_figures',
        compute_sudo=True, currency_field='warranty_b2_currency_id', groups=ACCOUNTING_READ_GROUPS)
    warranty_reserve_available_amount = fields.Monetary(
        string='Available Posted Reserve (Company)', compute='_compute_warranty_reserve_figures',
        compute_sudo=True, currency_field='warranty_b2_currency_id', groups=ACCOUNTING_READ_GROUPS)

    def _compute_warranty_reserve_figures(self):
        for case in self:
            if not case.id:
                case.update({name: 0 for name in (
                    'warranty_b2_move_count', 'warranty_reserve_parts_amount',
                    'warranty_reserve_goodwill_amount', 'warranty_reserve_recovered_amount',
                    'warranty_reserve_subcontract_amount', 'warranty_reserve_utilized_amount',
                    'warranty_reserve_eligible_amount', 'warranty_reserve_available_amount')})
                continue
            figures = case._warranty_reserve_figures()
            case.update({
                'warranty_b2_move_count': len(case.warranty_b2_move_ids),
                'warranty_reserve_parts_amount': figures['parts'],
                'warranty_reserve_goodwill_amount': figures['goodwill'],
                'warranty_reserve_recovered_amount': figures['recovered'],
                'warranty_reserve_subcontract_amount': figures['subcontract'],
                'warranty_reserve_utilized_amount': figures['utilized'],
                'warranty_reserve_eligible_amount': figures['eligible'],
                'warranty_reserve_available_amount':
                    case.company_id._warranty_reserve_available(),
            })

    def _warranty_reserve_stock_cost(self):
        """{request line: amount} posted to Warranty Expense by Odoo's own stock accounting for
        the case's covered / goodwill usage (use Dr, reversal Cr); manual valuation gives none."""
        self.ensure_one()
        case = self.sudo()
        expense = case.company_id.warranty_expense_account_id
        posted = defaultdict(float)
        if not expense:
            return posted
        usages = self.env['warranty.mrf.consumption'].sudo().search(
            [('case_id', '=', case.id), ('kind', '=', 'used')])
        for usage in usages:
            line = usage.line_id
            if line.coverage_type != 'covered' and not line.goodwill:
                continue
            moves = usage.move_ids.filtered(lambda move: move.state == 'done')
            entries = moves.stock_valuation_layer_ids.account_move_id.filtered(
                lambda move: move.state == 'posted')
            posted[line] += sum(entries.line_ids.filtered(
                lambda aml: aml.account_id == expense).mapped('balance'))
        return posted

    def _warranty_reserve_subcontract(self):
        """Approved subcontract cost lines of the case: their posted vendor bill lines on the
        Warranty Expense account only, net of posted credit notes (unposted or other accounts
        never count)."""
        self.ensure_one()
        case = self.sudo()
        expense = case.company_id.warranty_expense_account_id
        total = 0.0
        for cost in case.warranty_cost_entry_ids.filtered(
                lambda cost: cost.cost_type == 'subcontract' and cost.state == 'approved'):
            bill = cost.bill_line_id
            if bill:
                if bill.account_id == expense and bill.parent_state == 'posted':
                    total += cost.source_amount
            elif cost.purchase_line_id:
                total += sum(aml.balance for aml in cost.purchase_line_id.invoice_lines
                             if aml.parent_state == 'posted' and aml.account_id == expense)
        return case.company_id.currency_id.round(total)

    def _warranty_reserve_figures(self, exclude=None):
        """Covered parts cost posted to Warranty Expense by standard stock accounting, by request
        line net of posted vendor recovery of that line; goodwill only when the company allows
        it; subcontract when the policy is on; minus utilization already made (draft or posted)."""
        self.ensure_one()
        case = self.sudo()
        company = case.company_id
        currency = company.currency_id
        posted = case._warranty_reserve_stock_cost()
        claim_lines = self.env['warranty.vendor.claim.line'].sudo().search(
            [('mrf_line_id', 'in', [line.id for line in posted])])
        parts = goodwill = recovered = 0.0
        for line, amount in posted.items():
            amount = max(amount, 0.0)
            back = min(sum(claim_lines.filtered(
                lambda claim: claim.mrf_line_id == line).mapped('recovered_amount')), amount)
            recovered += back
            if line.goodwill:
                goodwill += amount - back
            else:
                parts += amount - back
        subcontract = case._warranty_reserve_subcontract() \
            if company.warranty_reserve_subcontract_eligible else 0.0
        utilized = 0.0
        for move in case.warranty_b2_move_ids.filtered(
                lambda move: move.warranty_b2_kind == 'utilization' and move.state != 'cancel'
                and move not in (exclude or ())):
            back = sum(move.reversal_move_ids.filtered(
                lambda reversal: reversal.state == 'posted').mapped('amount_total'))
            utilized += move.amount_total - back
        gross = parts + subcontract + (goodwill if company.warranty_reserve_goodwill_eligible
                                       else 0.0)
        return {
            'parts': currency.round(sum(max(amount, 0.0) for amount in posted.values())),
            'goodwill': currency.round(sum(max(amount, 0.0) for line, amount in posted.items()
                                           if line.goodwill)),
            'recovered': currency.round(recovered),
            'subcontract': subcontract,
            'utilized': currency.round(utilized),
            'eligible': max(currency.round(gross - utilized), 0.0),
        }

    def action_warranty_reserve_utilization(self):
        """Create Reserve Utilization Draft: Finance only, never automatic."""
        self.ensure_one()
        _check_poster(self.env, _("Only Accounting Bookkeepers or Administrators can create a "
                                  "reserve utilization."))
        self.check_access('read')
        self.env.cr.execute("SELECT id FROM warranty_case WHERE id = %s FOR UPDATE", (self.id,))
        self.env.invalidate_all()
        case = self.sudo()
        company = case.company_id
        if case.state not in CASE_UTILIZATION_STATES:
            raise UserError(_("Reserve utilization is created for a completed or closed case."))
        missing = [label for value, label in (
            (company.warranty_accounting_journal_id, _("Warranty Accounting Journal")),
            (company.warranty_expense_account_id, _("Warranty Expense Account")),
            (company.warranty_provision_account_id, _("Warranty Provision / Reserve Account")),
        ) if not value]
        if missing:
            raise UserError(_("Warranty accounting is not configured: %s.", ', '.join(missing)))
        if case.warranty_b2_move_ids.filtered(
                lambda move: move.warranty_b2_kind == 'utilization' and move.state == 'draft'):
            raise UserError(_("%s already has a draft reserve utilization: post or cancel it "
                              "first.", case.name))
        figures = case._warranty_reserve_figures()
        date, note = company._warranty_b2_open_date(fields.Date.context_today(self))
        available = company._warranty_reserve_available(date)
        currency = company.currency_id
        eligible = figures['eligible']
        amount = currency.round(min(eligible, available))
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_(
                "Nothing to utilize for %(case)s: eligible posted warranty cost %(eligible)s, "
                "available posted reserve %(available)s. Only cost posted to Warranty Expense "
                "counts (standard stock accounting with automated valuation, or approved "
                "subcontract bills when the policy allows it).", case=case.name,
                eligible=format_amount(self.env, eligible, currency),
                available=format_amount(self.env, available, currency)))
        name = _("Warranty reserve utilization: %s", case.name)
        move = self.env['account.move'].sudo().with_company(company).create({
            'move_type': 'entry',
            'company_id': company.id,
            'journal_id': company.warranty_accounting_journal_id.id,
            'date': date,
            'ref': name,
            'narration': note or False,
            'currency_id': currency.id,
            'warranty_reserve_movement': 'utilization',
            'warranty_b2_kind': 'utilization',
            'warranty_b2_case_id': case.id,
            'warranty_b2_eligible_amount': eligible,
            'warranty_b2_available_amount': available,
            'line_ids': [
                (0, 0, {'name': name, 'partner_id': case.partner_id.id, 'debit': amount,
                        'credit': 0.0, 'account_id': company.warranty_provision_account_id.id}),
                (0, 0, {'name': name, 'partner_id': case.partner_id.id, 'debit': 0.0,
                        'credit': amount, 'account_id': company.warranty_expense_account_id.id}),
            ],
        })
        text = _("Draft reserve utilization %(entry)s created by %(user)s: %(amount)s (eligible "
                 "%(eligible)s, available %(available)s). Finance posts it.",
                 entry=move.display_name, user=self.env.user.name,
                 amount=format_amount(self.env, amount, currency),
                 eligible=format_amount(self.env, eligible, currency),
                 available=format_amount(self.env, available, currency))
        if currency.compare_amounts(eligible, available) > 0:
            shortfall = format_amount(self.env, eligible - amount, currency)
            text += ' ' + _("Shortfall %s stays in Warranty Expense.", shortfall)
            case.activity_schedule('mail.mail_activity_data_todo', user_id=self.env.uid,
                                   summary=_("Warranty reserve shortfall"),
                                   note=_("%(case)s: %(shortfall)s of eligible cost is not "
                                          "covered by the posted reserve.", case=case.name,
                                          shortfall=shortfall))
        case._message_log(body=Markup('<p>%s</p>') % text)
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id,
                'view_mode': 'form', 'views': [(False, 'form')]}

    def action_open_warranty_b2_moves(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _("Warranty Reserve Entries"),
                'res_model': 'account.move', 'view_mode': 'list,form',
                'domain': [('warranty_b2_case_id', '=', self.id)],
                'context': {'create': False}}


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    warranty_reserve_subcontract_eligible = fields.Boolean(
        string='Subcontract Cost Uses the Reserve')
    warranty_reserve_goodwill_eligible = fields.Boolean(string='Goodwill Uses the Reserve')
    warranty_b2_readiness = fields.Text(string='Accounting Configuration Status',
                                        compute='_compute_warranty_b2_readiness')

    @api.depends('company_id')
    def _compute_warranty_b2_readiness(self):
        for settings in self:
            settings.warranty_b2_readiness = \
                settings.company_id.sudo()._warranty_accounting_status()

    @api.model
    def get_values(self):
        values = super().get_values()
        company = self.env.company.sudo()
        for name in RESERVE_POLICY_FIELDS:
            values[name] = company[name]
        return values

    def set_values(self):
        super().set_values()
        for settings in self:
            company = settings.company_id.sudo()
            vals = {name: settings[name] for name in RESERVE_POLICY_FIELDS}
            if company._warranty_accounting_changed(vals):
                company.write(vals)
