from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.warranty_management_repair.tests.test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_cost')
class TestWarrantyCostReport(ReplacementCommon):
    """Part 8.2: replacement cost, vendor recovery, net cost, the report, access and companies."""

    def setUp(self):
        super().setUp()
        self.supplier = self.env['res.partner'].create({'name': 'Cost Manufacturer'})
        self.single.standard_price = 100.0
        self.single.product_tmpl_id.write({
            'warranty_vendor_claimable': True, 'warranty_claim_partner_id': self.supplier.id,
            'warranty_brand': 'GREE', 'warranty_model': 'GWH09'})
        self.recovery_account = self.env['account.account'].create({
            'name': 'Cost Recovery', 'code': 'WCR820', 'account_type': 'income_other',
            'company_ids': [(6, 0, self.company.ids)]})
        self.company.write({
            'warranty_vendor_claim_enabled': True,
            'warranty_claim_evidence_required': False,
            'warranty_replacement_gm_user_ids': [(6, 0, self.gm.ids)],
            'warranty_claim_approver_ids': [(6, 0, self.gm.ids)],
            'warranty_claim_recovery_account_id': self.recovery_account.id,
        })
        self.tech = self._user('cost_report_tech', 'industry_fsm.group_fsm_user')
        self.accountant = self._user('cost_report_accountant', 'account.group_account_invoice')
        self.reader = self._user('cost_report_reader', 'account.group_account_readonly')
        self.approver = self._user('cost_report_approver')
        self.company.warranty_cost_approver_ids = self.approver
        self.card = self._card(self.single)
        self.old = self.card.unit_warranty_ids.serial_ids
        self.case = self._eligible_case(self.old)
        self.assertEqual(self.case.eligibility_result, 'eligible', self.case.eligibility_reason)
        self._approved_state(self.case)
        self.case.sudo().failure_category = 'mechanical'

    def _done(self, kind='vendor'):
        replacement = self._request(self.case, kind, self._lot(self.single, 6))
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.assertEqual(replacement.state, 'done')
        self.case.invalidate_recordset()
        return replacement

    def _claim(self, replacement):
        action = replacement.action_warranty_replacement_create_vendor_claim()
        return self.env['warranty.vendor.claim'].browse(action['res_id'])

    def _rows(self, user=None, **context):
        report = self.env['warranty.cost.report'].with_user(user or self.coordinator).with_context(
            **context)
        report.action_open_warranty_cost_report()
        return report.search([])

    def _case_rows(self, case=None, user=None):
        return self._rows(user).filtered(lambda row: row.case_id == (case or self.case))

    def _assert_case_reconciles(self):
        rows = self._case_rows()
        case = self.case
        case.invalidate_recordset()
        for column, total in (('estimated_amount', case.warranty_total_estimated),
                              ('approved_amount', case.warranty_total_approved),
                              ('actual_amount', case.warranty_total_actual),
                              ('unverified_amount', case.warranty_cost_unverified),
                              ('recovered_amount', case.vendor_recovered_amount),
                              ('net_amount', case.warranty_net_cost)):
            self.assertAlmostEqual(sum(rows.mapped(column)), total, msg=column)
        return rows

    # ------------------------------------------------------------------ replacement
    def test_01_done_replacement_counts_once_and_the_gate_figure_stays(self):
        expected = self.case.warranty_total_expected
        before = self.case.warranty_total_actual
        self._done()
        self.assertEqual(self.case.warranty_total_actual, before + 100)
        self.assertEqual(self.case.warranty_total_approved, 100)
        self.assertEqual(self.case.warranty_total_estimated, 100)
        self.assertEqual(self.case.warranty_net_cost, before + 100)
        self.assertEqual(self.case.warranty_total_expected, expected, 'D9 stays as approved')
        self.assertIn('Replacement', self.case.warranty_cost_overview)
        self.assertIn('Net Warranty Cost', self.case.warranty_cost_overview)
        rows = self._assert_case_reconciles()
        row = rows.filtered(lambda line: line.cost_type == 'replacement')
        self.assertEqual((len(row), row.actual_amount, row.cost_source, row.job_id),
                         (1, 100, 'replacement', self.env['warranty.service.job']))

    def test_02_open_rejected_and_unverified_replacement(self):
        replacement = self._request(self.case, 'vendor', self._lot(self.single, 6))
        self.case.invalidate_recordset()
        self.assertEqual(self.case.warranty_total_actual, 0, 'not delivered')
        self.assertIn(replacement.name, self.case.warranty_cost_overview)
        self.assertFalse(self._case_rows().filtered(lambda row: row.cost_type == 'replacement'))
        replacement.action_warranty_replacement_submit()
        replacement.with_user(self.gm).action_warranty_replacement_approve()
        record = replacement.sudo()
        self._validate(record.return_picking_id)
        self._validate(record.delivery_picking_id)
        self.env.cr.execute("UPDATE warranty_replacement SET replacement_cost_verified = FALSE "
                            "WHERE id = %s", (replacement.id,))
        self.env.invalidate_all()
        self.assertEqual(self.case.warranty_total_actual, 0, 'an estimate is not a verified actual')
        self.assertEqual(self.case.warranty_cost_unverified, 100)
        self.assertIn('no stock valuation', self.case.warranty_cost_overview)
        rows = self._assert_case_reconciles()
        self.assertEqual(rows.filtered(lambda row: row.cost_type == 'replacement').unverified_amount,
                         100)

    def test_03_component_replacement_counts_through_its_material_request_only(self):
        """The two values are set directly: this checks the rule even if a Component replacement
        ever held a cost. The full Component flow is tested in warranty_management_repair."""
        part = self.env['product.product'].create({
            'name': 'Cost PCB', 'type': 'consu', 'is_storable': True, 'standard_price': 500})
        employee = self.env['hr.employee'].create({
            'name': 'Cost Employee', 'department_id': self.env['hr.department'].create(
                {'name': 'Cost Department'}).id})
        request = self.env['material.purchase.requisition'].create({
            'employee_id': employee.id, 'department_id': employee.department_id.id,
            'warranty_case_id': self.case.id,
            'requisition_line_ids': [(0, 0, {'product_id': part.id, 'description': part.name,
                                             'qty': 1, 'uom': part.uom_id.id})]})
        line = request.requisition_line_ids
        replacement = self.env['warranty.replacement'].with_user(self.coordinator).create({
            'warranty_case_id': self.case.id, 'replacement_type': 'component',
            'reason': 'pcb_failure', 'date_policy': 'continue_original',
            'component_line_ids': [(0, 0, {'product_id': part.id, 'qty': 1})]})
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_replacement SET state = 'done', replacement_cost = 500, "
                            "replacement_cost_verified = TRUE WHERE id = %s", (replacement.id,))
        self.env.cr.execute("UPDATE material_purchase_requisition_line SET actual_cost = 500, "
                            "cost_bucket = 'covered' WHERE id = %s", (line.id,))
        self.env.invalidate_all()
        self.assertEqual(self.case.warranty_total_actual, 500, 'parts only, not 1,000')
        rows = self._assert_case_reconciles()
        self.assertEqual(rows.filtered(lambda row: row.cost_type == 'parts').actual_amount, 500)
        self.assertFalse(rows.filtered(lambda row: row.cost_type == 'replacement'))

    # ------------------------------------------------------------------ recovery
    def test_04_recovery_counts_only_a_posted_credit_note(self):
        moves = self.env['account.move'].search_count([])
        material_net = self.case.net_warranty_material_cost
        replacement = self._done()
        layers = self.env['stock.valuation.layer'].search_count([])
        claim = self._claim(replacement)
        self.case.invalidate_recordset()
        self.assertEqual((self.case.vendor_claimed_amount, self.case.vendor_recovered_amount,
                          self.case.warranty_net_cost), (100, 0, 100), 'an unapproved claim')
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        claim.with_user(self.coordinator).action_submit()
        claim.with_user(self.gm).action_approve()
        claim.with_user(self.coordinator).action_mark_sent()
        claim.with_user(self.coordinator)._warranty_record_response(
            {claim.line_ids: (100, '')}, reference='V-82')
        action = claim.with_user(self.accountant).action_create_credit_note()
        move = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(self.env['account.move'].search_count([]), moves + 1,
                         'only the existing Create Draft Credit Note')
        self.assertEqual(move.state, 'draft')
        self.case.invalidate_recordset()
        self.assertEqual((self.case.vendor_recovered_amount, self.case.warranty_net_cost),
                         (0, 100), 'a draft credit note is not recovery')
        self._assert_case_reconciles()
        move.invoice_date = fields.Date.today()
        move.with_user(self.accountant).action_post()
        self.env.invalidate_all()
        self.assertEqual((self.case.vendor_recovered_amount, self.case.warranty_net_cost),
                         (100, 0), 'posted')
        self.assertEqual(self.case.net_warranty_material_cost, material_net,
                         'Net Warranty Material Cost keeps its approved behaviour')
        rows = self._assert_case_reconciles()
        row = rows.filtered(lambda line: line.cost_type == 'recovery')
        self.assertEqual((row.recovered_amount, row.net_amount), (100, -100))
        self.assertEqual(sum(rows.mapped('net_amount')), 0)
        move.with_user(self.accountant).button_draft()
        move.with_user(self.accountant).button_cancel()
        self.env.invalidate_all()
        self.assertEqual((self.case.vendor_recovered_amount, self.case.warranty_net_cost),
                         (0, 100), 'a cancelled credit note is no longer recovery')
        self._assert_case_reconciles()
        self.assertEqual(self.env['stock.valuation.layer'].search_count([]), layers)

    def _posted_credit_note(self, claim=None):
        claim = claim or self._claim(self._done())
        claim.with_user(self.coordinator).action_submit()
        claim.with_user(self.gm).action_approve()
        claim.with_user(self.coordinator).action_mark_sent()
        claim.with_user(self.coordinator)._warranty_record_response(
            {claim.line_ids: (100, '')}, reference='V-82')
        action = claim.with_user(self.accountant).action_create_credit_note()
        move = self.env['account.move'].browse(action['res_id'])
        move.invoice_date = fields.Date.today()
        move.with_user(self.accountant).action_post()
        self.env.invalidate_all()
        return claim, move

    def _partial_reversal(self, move, amount, date=None, post=True):
        """A reversal linked to the credit note, for part of its amount, as Accounting edits it."""
        reversal = move._reverse_moves([{'invoice_date': date or fields.Date.today(),
                                         'date': date or fields.Date.today()}])
        reversal.invoice_line_ids.write({'price_unit': amount})
        if post:
            reversal.action_post()
        self.env.invalidate_all()
        return reversal

    def _recovery_report_row(self, claim):
        report = self.env['warranty.vendor.claim.recovery.report']
        report.invalidate_model()
        return report.search([('claim_id', '=', claim.id), ('allocation_scope', '=', 'line')])

    def test_10_fully_reversed_credit_note_is_not_recovery(self):
        moves_before = self.env['account.move'].search_count([])
        claim, move = self._posted_credit_note()
        material_net = self.case.net_warranty_material_cost
        self.assertEqual((claim.recovered_amount, claim.outstanding_amount), (100, 0), 'posted')
        self.assertEqual(self._recovery_report_row(claim).recovered_amount, 100)
        reversal = move._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=True)
        self.assertEqual((reversal.state, reversal.reversed_entry_id), ('posted', move))
        self.env.invalidate_all()
        self.assertEqual(move.payment_state, 'paid', 'the payment state alone would miss this')
        self.assertEqual((claim.recovered_amount, claim.settled_amount, claim.outstanding_amount,
                          claim.recovery_status), (0, 0, 100, 'pending'))
        self.assertEqual((self.case.vendor_recovered_amount, self.case.warranty_net_cost),
                         (0, 100))
        self.assertEqual(self.case.net_warranty_material_cost, material_net,
                         'a replacement recovery never changes the material figure')
        report_row = self._recovery_report_row(claim)
        self.assertEqual((report_row.recovered_amount, report_row.settled_amount,
                          report_row.outstanding_amount), (0, 0, 100))
        rows = self._assert_case_reconciles()
        self.assertEqual(sum(rows.filtered(lambda r: r.cost_type == 'recovery').mapped(
            'recovered_amount')), 0)
        # History stays, nothing else is created, and the claim can recover again.
        self.assertEqual(claim.recovery_ids.filtered('active').move_id, move)
        self.assertEqual(self.env['account.move'].search_count([]), moves_before + 2,
                         'only the credit note and the reversal Accounting made')
        action = claim.with_user(self.accountant).action_create_credit_note()
        again = self.env['account.move'].browse(action['res_id'])
        self.assertEqual((again.state, again.amount_total), ('draft', 100))
        self.assertEqual(claim.recovered_amount, 0, 'a new draft is not recovery')

    def test_11_partial_reversal_reduces_recovery_in_proportion(self):
        claim, move = self._posted_credit_note()
        draft = self._partial_reversal(move, 30, post=False)
        self.assertEqual(claim.recovered_amount, 100, 'a draft reversal changes nothing')
        draft.action_post()
        self.env.invalidate_all()
        self.assertEqual((claim.recovered_amount, claim.outstanding_amount), (70, 30))
        self.assertEqual((self.case.vendor_recovered_amount, self.case.warranty_net_cost), (70, 30))
        self.assertEqual(self._recovery_report_row(claim).recovered_amount, 70)
        self.assertEqual(move._warranty_claim_available(), 0, 'nothing free on the note itself')
        rows = self._assert_case_reconciles()
        self.assertEqual(sum(rows.mapped('recovered_amount')), 70)
        # The reversal of the reversal restores it, in every figure.
        again = draft._reverse_moves([{'invoice_date': fields.Date.today()}], cancel=False)
        again.action_post()
        self.env.invalidate_all()
        self.assertEqual(claim.recovered_amount, 100)
        self.assertEqual(self._recovery_report_row(claim).recovered_amount, 100)

    def test_12_vendor_bill_offset_is_a_settlement_not_a_reversal(self):
        claim, move = self._posted_credit_note()
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.supplier.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {'name': 'Offset', 'quantity': 1, 'price_unit': 100,
                                         'tax_ids': [(5, 0, 0)],
                                         'account_id': self.recovery_account.id})]})
        bill.action_post()
        (move | bill).line_ids.filtered(
            lambda line: line.account_id.account_type == 'liability_payable').reconcile()
        self.env.invalidate_all()
        self.assertEqual((claim.recovered_amount, claim.settled_amount, claim.outstanding_amount),
                         (100, 100, 0), 'valid recovery stays')
        self.assertEqual(self._recovery_report_row(claim).settled_amount, 100)

    # ------------------------------------------------------------------ incurred dates
    def _set_case_old(self):
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_case SET create_date = '2026-01-15 08:00:00' "
                            "WHERE id = %s", (self.case.id,))
        self.env.invalidate_all()

    def test_13_replacement_and_recovery_on_their_own_dates(self):
        self._set_case_old()
        replacement = self._done()
        self.env.cr.execute("UPDATE warranty_replacement SET delivery_date = '2026-03-10' "
                            "WHERE id = %s", (replacement.id,))
        self.env.invalidate_all()
        claim, move = self._posted_credit_note(self._claim(replacement))
        reversal = self._partial_reversal(move, 40, date=fields.Date.to_date('2026-09-20'))
        self.assertEqual(reversal.date, fields.Date.to_date('2026-09-20'))
        rows = self._assert_case_reconciles()
        replacement_row = rows.filtered(lambda row: row.cost_type == 'replacement')
        self.assertEqual((replacement_row.cost_date, replacement_row.actual_amount),
                         (fields.Date.to_date('2026-03-10'), 100))
        self.assertEqual(replacement_row.case_date, fields.Date.to_date('2026-01-15'))
        recovery = rows.filtered(lambda row: row.cost_type == 'recovery')
        self.assertEqual({row.cost_date: row.recovered_amount for row in recovery},
                         {move.date: 100, reversal.date: -40})
        self.assertEqual(sum(recovery.mapped('recovered_amount')), 60)
        report = self.env['warranty.cost.report'].with_user(self.coordinator)
        march = report.search([('case_id', '=', self.case.id), ('cost_date', '>=', '2026-03-01'),
                               ('cost_date', '<', '2026-04-01')])
        self.assertEqual(sum(march.mapped('actual_amount')), 100)
        by_case = report.search([('case_id', '=', self.case.id), ('case_date', '=', '2026-01-15')])
        self.assertEqual(by_case, rows, 'the case date stays available as a separate filter')

    def test_14_brand_and_model_filters(self):
        self.single.product_tmpl_id.write({'warranty_brand': 'GREE', 'warranty_model': '9000 BTU'})
        self._done()
        report = self.env['warranty.cost.report'].with_user(self.coordinator)
        report.action_open_warranty_cost_report()
        mine = report.search([('case_id', '=', self.case.id)])
        self.assertTrue(mine)
        self.assertEqual(report.search([('brand', '=', 'GREE'), ('model', '=', '9000 BTU'),
                                        ('case_id', '=', self.case.id)]), mine)
        self.assertEqual(report.search([('brand', 'ilike', 'gre'), ('case_id', '=', self.case.id)]),
                         mine)
        self.assertFalse(report.search([('model', '=', '12000 BTU'),
                                        ('case_id', '=', self.case.id)]))
        self.single.product_tmpl_id.write({'warranty_brand': False, 'warranty_model': False})
        report.action_open_warranty_cost_report()
        empty = report.search([('case_id', '=', self.case.id)])
        self.assertTrue(empty, 'an empty brand and model cause no error')
        self.assertEqual((empty[0].brand, empty[0].model), (False, False))
        self.assertFalse(report.search([('brand', '=', 'GREE'), ('case_id', '=', self.case.id)]))
        arch = self.env['product.template'].get_view(
            self.env.ref('product.product_template_form_view').id, 'form')['arch']
        self.assertIn('warranty_brand', arch)

    def test_05_the_report_creates_no_accounting_or_stock_record(self):
        self._done()
        counts = lambda: tuple(self.env[model].search_count([]) for model in (
            'account.move', 'account.move.line', 'account.payment', 'stock.valuation.layer',
            'stock.move', 'warranty.replacement', 'warranty.vendor.claim',
            'material.purchase.requisition', 'warranty.cost.line'))
        before = counts()
        self._rows()
        self._rows()
        self.assertEqual(counts(), before)

    # ------------------------------------------------------------------ filters
    def test_06_filters(self):
        self._done()
        report = self.env['warranty.cost.report'].with_user(self.coordinator)
        report.action_open_warranty_cost_report()
        today = fields.Date.context_today(self.case)
        row_ids = report.search([('case_id', '=', self.case.id)]).ids
        self.assertTrue(row_ids)
        for domain in ([('product_id', '=', self.single.id)], [('brand', 'ilike', 'gree')],
                       [('model', '=', 'GWH09')], [('failure_category', '=', 'mechanical')],
                       [('cost_date', '>=', fields.Date.subtract(today, days=1)),
                        ('cost_date', '<=', fields.Date.add(today, days=1))],
                       [('case_date', '>=', fields.Date.subtract(today, days=1))]):
            self.assertEqual(report.search(domain + [('id', 'in', row_ids)]).ids, row_ids, domain)
        for domain in ([('brand', '=', 'OTHER')], [('failure_category', '=', 'misuse')],
                       [('technician_id', '=', self.tech.id)],
                       [('cost_date', '<', fields.Date.subtract(today, days=30))]):
            self.assertFalse(report.search(domain + [('id', 'in', row_ids)]), domain)
        groups = report.read_group([('id', 'in', row_ids)], ['actual_amount:sum'], ['cost_type'])
        self.assertEqual(sum(group['actual_amount'] for group in groups), 100)

    # ------------------------------------------------------------------ access
    def test_07_roles(self):
        self._done()
        Report = self.env['warranty.cost.report']
        for user in (self.coordinator, self.accountant, self.reader, self.approver):
            self.assertTrue(self._case_rows(user=user), user.login)
        group = self.env.ref('warranty_management_accounting.group_warranty_cost_report')
        self.assertIn(self.approver, group.users, 'named in the settings')
        self.assertTrue(Report.with_user(self.approver).check_access('read') is None)
        for user in (self.tech, self.outsider):
            with self.assertRaises(AccessError, msg=user.login):
                Report.with_user(user).action_open_warranty_cost_report()
            with self.assertRaises(AccessError, msg=user.login):
                Report.with_user(user).search([])
            with self.assertRaises(AccessError, msg=user.login):
                self.case.with_user(user).read(['warranty_net_cost'])
        self.company.warranty_cost_approver_ids = False
        self.assertNotIn(self.approver, group.users, 'follows the settings')
        with self.assertRaises(AccessError):
            Report.with_user(self.approver).action_open_warranty_cost_report()

    def test_08_read_only_and_own_rows(self):
        self._done()
        rows = self._case_rows(user=self.accountant)
        self.assertTrue(rows)
        with self.assertRaises(AccessError):
            rows.write({'actual_amount': 1})
        with self.assertRaises(AccessError):
            rows.unlink()
        with self.assertRaises(AccessError):
            self.env['warranty.cost.report'].with_user(self.accountant).create(
                {'case_id': self.case.id, 'company_id': self.company.id, 'cost_type': 'parts',
                 'cost_source': 'valuation'})
        other = self._rows(self.coordinator)
        self.assertFalse(other & rows.with_user(self.coordinator), "another user's rows are hidden")
        self.assertTrue(self.env['warranty.cost.report'].browse(rows.ids).exists(),
                        'opening the report keeps the rows of other users')
        action = rows[0].action_open_case()
        self.assertEqual((action['res_model'], action['res_id']), ('warranty.case', self.case.id))

    def test_09_company_isolation(self):
        self._done()
        other = self.env['res.company'].create({'name': 'Cost Company 2'})
        both = self._user('cost_report_both', 'account.group_account_readonly')
        both.company_ids = self.company | other
        approver_other = self._user('cost_report_approver2')
        approver_other.company_ids = self.company | other
        other.warranty_cost_approver_ids = approver_other
        self.env.flush_all()
        self.env.cr.execute("UPDATE warranty_case SET company_id = %s WHERE id = %s",
                            (other.id, self.case.id))
        self.env.cr.execute("UPDATE warranty_replacement SET company_id = %s "
                            "WHERE warranty_case_id = %s", (other.id, self.case.id))
        self.env.invalidate_all()
        rows = self._rows(self.accountant)
        self.assertFalse(rows.filtered(lambda row: row.case_id == self.case), 'another company')
        rows = self._rows(both, allowed_company_ids=self.company.ids)
        self.assertFalse(rows.filtered(lambda row: row.case_id == self.case), 'not selected')
        rows = self._rows(both, allowed_company_ids=(self.company | other).ids)
        self.assertEqual(rows.filtered(lambda row: row.case_id == self.case).company_id, other)
        self.assertFalse(
            rows.with_context(allowed_company_ids=self.company.ids).search(
                [('case_id', '=', self.case.id)]), 'rows of a company no longer selected')
        rows = self._rows(self.approver)
        self.assertFalse(rows.filtered(lambda row: row.case_id == self.case),
                         'an approver of Company 1 reads only Company 1')
        rows = self._rows(approver_other, allowed_company_ids=(self.company | other).ids)
        self.assertEqual(set(rows.mapped('company_id').ids), {other.id},
                         'an approver of Company 2 reads only Company 2')
        for row_case in rows.case_id:
            self.assertEqual(row_case.sudo().company_id, other)
