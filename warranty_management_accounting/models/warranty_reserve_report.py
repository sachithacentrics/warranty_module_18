from odoo import _, api, fields, models
from odoo.exceptions import AccessError

MOVEMENT_TYPES = [
    ('provision', 'Provision'),
    ('reversal', 'Provision Reversal'),
    ('utilization', 'Reserve Utilization'),
    ('release', 'Reserve Release'),
    ('other', 'Other Manual (Unclassified)'),
    ('actual_cost', 'Actual Warranty Cost (Operational)'),
]
ACCOUNTING_GROUPS = ('account.group_account_readonly', 'account.group_account_invoice')


class WarrantyReserveReport(models.TransientModel):
    """SRS 15 Provision / Reserve Utilization Report, mapping row 14. One row per journal item on
    the company's Warranty Provision account, plus the operational actual cost for comparison, which
    is never part of the reserve. Rows are rebuilt for the user when the report opens; nothing is
    written to any accounting or operational record, and no utilization is inferred."""
    _name = 'warranty.reserve.report'
    _description = 'Warranty Provision / Reserve Report'
    _order = 'date desc, id desc'
    _rec_name = 'move_id'
    _transient_max_hours = 24.0

    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='cascade',
                                 index=True)
    currency_id = fields.Many2one('res.currency', readonly=True, ondelete='cascade')
    date = fields.Date(readonly=True)
    movement_type = fields.Selection(MOVEMENT_TYPES, string='Movement', required=True, readonly=True)
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True,
                              ondelete='cascade')
    move_state = fields.Selection([('draft', 'Draft'), ('posted', 'Posted')], string='Entry Status',
                                  readonly=True)
    account_id = fields.Many2one('account.account', string='Reserve Account', readonly=True,
                                 ondelete='cascade')
    invoice_id = fields.Many2one('account.move', string='Source Invoice', readonly=True,
                                 ondelete='cascade')
    refund_id = fields.Many2one('account.move', string='Source Credit Note', readonly=True,
                                ondelete='cascade')
    case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True,
                              ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', readonly=True,
                                 ondelete='cascade')
    category_id = fields.Many2one('product.category', string='Product Category', readonly=True,
                                  ondelete='cascade')
    policy_id = fields.Many2one('warranty.policy', string='Warranty Policy', readonly=True,
                                ondelete='cascade')
    provision_amount = fields.Monetary(string='Provisions', readonly=True)
    reversal_amount = fields.Monetary(string='Reversals', readonly=True)
    utilization_amount = fields.Monetary(string='Utilization', readonly=True)
    release_amount = fields.Monetary(string='Releases', readonly=True)
    other_amount = fields.Monetary(string='Other Manual', readonly=True)
    reserve_amount = fields.Monetary(
        string='Outstanding Reserve', readonly=True,
        help="Posted journal items only: credits minus debits on the reserve account. The total "
             "equals the account's posted balance.")
    draft_amount = fields.Monetary(string='Draft (Not Counted)', readonly=True,
                                   help="Entries Finance has not posted yet.")
    actual_cost_amount = fields.Monetary(
        string='Actual Warranty Cost', readonly=True,
        help="Operational cost from the Warranty Cost Report, for comparison. It is not a journal "
             "entry and never changes the reserve.")

    @api.model
    def _warranty_reserve_accounts(self, company):
        """The configured account, and the accounts of earlier provisions if it was changed."""
        accounts = company.sudo().warranty_provision_account_id
        moves = self.env['account.move'].sudo().search([
            ('company_id', '=', company.id), ('warranty_provision_invoice_line_id', '!=', False)])
        return accounts | moves.line_ids.filtered('credit').account_id

    @api.model
    def _warranty_reserve_type(self, move):
        source = move.reversed_entry_id
        if source and (source.warranty_provision_invoice_id or move.warranty_provision_invoice_id):
            return 'reversal'
        if move.warranty_provision_invoice_id:
            return 'provision'
        return move.warranty_reserve_movement or 'other'

    @api.model
    def _warranty_reserve_rows(self, company):
        rows = []
        accounts = self._warranty_reserve_accounts(company)
        lines = self.env['account.move.line'].sudo().search([
            ('account_id', 'in', accounts.ids), ('company_id', '=', company.id),
            ('parent_state', 'in', ('draft', 'posted'))], order='date, id')
        columns = {'provision': 'provision_amount', 'reversal': 'reversal_amount',
                   'utilization': 'utilization_amount', 'release': 'release_amount',
                   'other': 'other_amount'}
        for line in lines:
            move = line.move_id
            movement = self._warranty_reserve_type(move)
            source = move.reversed_entry_id if movement == 'reversal' else move
            invoice_line = source.warranty_provision_invoice_line_id
            net = line.credit - line.debit
            row = {
                'company_id': company.id,
                'currency_id': company.currency_id.id,
                'date': line.date,
                'movement_type': movement,
                'move_id': move.id,
                'move_state': move.state,
                'account_id': line.account_id.id,
                'invoice_id': move.warranty_provision_invoice_id.id
                or source.warranty_provision_invoice_id.id,
                'refund_id': move.warranty_provision_refund_id.id,
                'partner_id': line.partner_id.id,
                'product_id': invoice_line.product_id.id,
                'category_id': invoice_line.product_id.categ_id.id,
                'policy_id': move.warranty_provision_policy_id.id
                or source.warranty_provision_policy_id.id,
            }
            if move.state == 'posted':
                row[columns[movement]] = abs(net)
                row['reserve_amount'] = net
            else:
                row['draft_amount'] = net
            rows.append(row)
        Report = self.env['warranty.cost.report']
        cases = self.env['warranty.case'].sudo().search([('company_id', '=', company.id)])
        for case in cases:
            product = case.product_id or case.serial_id.product_id
            for cost in Report._warranty_report_case_rows(case.with_company(company)):
                if company.currency_id.is_zero(cost['actual_amount']):
                    continue
                rows.append({
                    'company_id': company.id,
                    'currency_id': company.currency_id.id,
                    'date': cost['cost_date'],
                    'movement_type': 'actual_cost',
                    'case_id': case.id,
                    'partner_id': case.partner_id.id,
                    'product_id': product.id,
                    'category_id': product.categ_id.id,
                    'policy_id': case.warranty_card_id.policy_id.id,
                    'actual_cost_amount': cost['actual_amount'],
                })
        return rows

    @api.model
    def action_open_warranty_reserve_report(self):
        if not any(self.env.user.has_group(group) for group in ACCOUNTING_GROUPS):
            raise AccessError(_("Only Accounting users can read the warranty reserve."))
        # sudo: the report is read only for users; only this method writes its rows.
        report = self.sudo()
        report.search([('create_uid', '=', self.env.uid)]).unlink()
        rows = []
        for company in self.env.companies:
            rows += self._warranty_reserve_rows(company)
        report.create(rows)
        return self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_accounting.action_warranty_reserve_report')

    def action_open_source(self):
        """The journal entry or case of the row, with the user's own access rights."""
        self.ensure_one()
        record = self.move_id or self.case_id
        record.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': record._name, 'res_id': record.id,
                'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current'}
