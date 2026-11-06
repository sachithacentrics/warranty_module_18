from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.warranty_management_helpdesk.models.warranty_case import FAILURE_CATEGORIES
from odoo.addons.warranty_management_mrf.models.material_purchase_requisition_cost import \
    COST_GROUPS, WARRANTY_BUCKETS

from .warranty_cost_line import COST_TYPES
from .warranty_cost_summary import warranty_parts_figures

REPORT_COST_TYPES = [('parts', 'Parts'), *COST_TYPES, ('replacement', 'Replacement'),
                     ('recovery', 'Vendor Recovery')]
COST_SOURCES = [
    ('valuation', 'Stock Valuation'),
    ('timesheet', 'Timesheets'),
    ('manual', 'Manual Cost Line'),
    ('document', 'Purchase / Vendor Bill'),
    ('replacement', 'Replacement Record'),
    ('recovery', 'Posted Vendor Credit Notes'),
]
AMOUNT_KEYS = ('estimated', 'approved', 'actual', 'unverified', 'recovered', 'missing_hours')


def _fitted(movements, total, fallback_date):
    """{date: amount} of dated movements that add up exactly to `total`, the figure of the case or
    job: a rounding difference goes to the latest date, so a cost never moves in or out of the
    totals because of its dates."""
    days = {}
    for date, amount in movements:
        days[date] = days.get(date, 0.0) + amount
    difference = total - sum(days.values())
    if difference:
        date = max(days) if days else fallback_date
        days[date] = days.get(date, 0.0) + difference
    return days


class WarrantyCostReport(models.TransientModel):
    """SRS 15 Warranty Cost Report. One row per case, service job, cost type, source and date, see
    doc/part8_2_cost_report_design.md for the date of each source. The rows are rebuilt for the
    user when the report opens, from the same figures as the case and job totals, because labour
    shares and vendor bill figures are calculated and not stored. They hold no business data, and
    nothing is written back to any source record."""
    _name = 'warranty.cost.report'
    _description = 'Warranty Cost Report'
    _order = 'cost_date desc, case_id desc, job_id, cost_type'
    _rec_name = 'case_id'
    _transient_max_hours = 24.0

    case_id = fields.Many2one('warranty.case', string='Warranty Case', required=True, readonly=True,
                              ondelete='cascade', index=True)
    job_id = fields.Many2one('warranty.service.job', string='Service Job', readonly=True,
                             ondelete='cascade')
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='cascade',
                                 index=True)
    currency_id = fields.Many2one('res.currency', readonly=True, ondelete='cascade')
    cost_date = fields.Date(string='Cost Incurred Date', readonly=True,
                            help="The date the cost was incurred. A reversal or credit note shows "
                                 "as a negative amount on its own date.")
    case_date = fields.Date(string='Case Creation Date', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', readonly=True,
                                 ondelete='cascade')
    brand = fields.Char(readonly=True)
    model = fields.Char(readonly=True)
    technician_id = fields.Many2one('res.users', string='Main Technician', readonly=True,
                                    ondelete='cascade')
    failure_category = fields.Selection(FAILURE_CATEGORIES, string='Failure Category', readonly=True)
    case_state = fields.Char(string='Case Status', readonly=True)
    cost_type = fields.Selection(REPORT_COST_TYPES, string='Cost Type', required=True, readonly=True)
    cost_source = fields.Selection(COST_SOURCES, string='Source', required=True, readonly=True)
    estimated_amount = fields.Monetary(string='Estimated', readonly=True)
    approved_amount = fields.Monetary(string='Approved', readonly=True)
    actual_amount = fields.Monetary(string='Actual', readonly=True)
    unverified_amount = fields.Monetary(string='Unverified (Not Counted)', readonly=True)
    recovered_amount = fields.Monetary(string='Vendor Recovered', readonly=True)
    net_amount = fields.Monetary(string='Net Warranty Cost', readonly=True)
    labour_missing_hours = fields.Float(string='Hours Without Cost', readonly=True)
    is_incomplete = fields.Boolean(string='Incomplete Labour', readonly=True)
    is_manual = fields.Boolean(string='Manual Cost', readonly=True)

    @api.model
    def _warranty_report_companies(self):
        """Coordinators, requisition and accounting users read the cost of their selected
        companies; a named approver only that of the companies they approve for. Technicians are
        none of these (H-11)."""
        user = self.env.user
        if any(user.has_group(group) for group in COST_GROUPS.split(',')):
            return self.env.companies
        return self.env.companies.filtered(
            lambda company: user in (company.sudo().warranty_cost_approver_ids
                                     | company.sudo().warranty_cost_finance_approver_ids))

    @api.model
    def _warranty_report_case_rows(self, case):
        """The rows of one case, sudo: they add up to the totals of the case and of its jobs."""
        company = case.company_id
        currency = company.currency_id
        case_date = company._warranty_local_date(case.create_date)
        product = case.product_id or case.serial_id.product_id
        jobs = case.service_job_ids
        no_job = jobs.browse()
        figures = {}

        def add(job, cost_type, source, date, key, amount):
            row = figures.setdefault((job, cost_type, source, date or case_date),
                                     dict.fromkeys(AMOUNT_KEYS, 0.0))
            row[key] += amount

        def add_movements(job, cost_type, source, key, movements, total, fallback_date):
            for date, amount in _fitted(movements, total, fallback_date).items():
                add(job, cost_type, source, date, key, amount)

        # Parts: planned on the request date, actual on the stock move dates.
        for line in case._warranty_cost_lines():
            request = line.requisition_id
            job = request.warranty_service_job_id
            job = job if job in jobs else no_job
            values = warranty_parts_figures(line)
            planned = request.request_date or case_date
            add(job, 'parts', 'valuation', planned, 'estimated', values['estimated'])
            add(job, 'parts', 'valuation', planned, 'approved', values['approved'])
            if line.cost_bucket in WARRANTY_BUCKETS:
                movements = line._warranty_cost_movements()
                for key, verified in (('actual', True), ('unverified', False)):
                    add_movements(job, 'parts', 'valuation', key,
                                  [(date, amount) for date, amount, flag in movements
                                   if flag is verified], values[key], planned)

        # Labour of visits: on the timesheet dates. The dates add up to the job's figures.
        for job in jobs:
            days = job._warranty_labour_by_date()
            cost_total = job._warranty_scope_labour()[1]
            add_movements(job, 'labour', 'timesheet', 'actual',
                          [(date, day[1]) for date, day in days.items()], cost_total, case_date)
            for date, day in days.items():
                if day[2]:
                    add(job, 'labour', 'timesheet', date, 'missing_hours', day[2])

        # Cost lines: planned and actual on the line's date, documents on their accounting dates.
        for line in case.warranty_cost_entry_ids:
            source = 'manual' if line.actual_is_manual else (
                'document' if line.cost_type == 'subcontract' else 'timesheet')
            date = line._warranty_effective_date()
            if line.state not in ('rejected', 'reversed'):
                add(line.job_id, line.cost_type, source, date, 'estimated', line.estimated_amount)
                add(line.job_id, line.cost_type, source, date, 'approved',
                    line.counted_approved_amount)
            add_movements(line.job_id, line.cost_type, source, 'actual',
                          line._warranty_actual_movements(), line.counted_actual_amount, date)

        # Replacement: on the delivery date.
        for replacement in case._warranty_scope_replacements():
            date = replacement.delivery_date or company._warranty_local_date(
                replacement.delivery_picking_id.date_done)
            cost = replacement.replacement_cost
            add(no_job, 'replacement', 'replacement', date, 'estimated', cost)
            add(no_job, 'replacement', 'replacement', date, 'approved', cost)
            add(no_job, 'replacement', 'replacement', date,
                'actual' if replacement.replacement_cost_verified else 'unverified', cost)

        # Recovery: the credit notes on their accounting dates, reversals on their own dates.
        claims = case._warranty_vendor_claims().filtered(lambda claim: claim.state != 'cancel')
        for allocation in claims.recovery_ids.filtered('active'):
            add_movements(no_job, 'recovery', 'recovery', 'recovered',
                          allocation._warranty_recovery_movements(), allocation.recovered_amount,
                          allocation.move_id.date)

        base = {
            'case_id': case.id,
            'company_id': company.id,
            'currency_id': currency.id,
            'case_date': case_date,
            'partner_id': case.partner_id.id,
            'product_id': product.id,
            'brand': product.warranty_brand,
            'model': product.warranty_model,
            'failure_category': case.failure_category,
            'case_state': dict(case._fields['state']._description_selection(self.env)).get(
                case.state),
        }
        rows = []
        for (job, cost_type, source, date), row in figures.items():
            if all(currency.is_zero(row[key]) for key in AMOUNT_KEYS):
                continue
            rows.append(dict(
                base, job_id=job.id, technician_id=job.main_technician_id.id, cost_date=date,
                cost_type=cost_type, cost_source=source, estimated_amount=row['estimated'],
                approved_amount=row['approved'], actual_amount=row['actual'],
                unverified_amount=row['unverified'], recovered_amount=row['recovered'],
                net_amount=row['actual'] - row['recovered'],
                labour_missing_hours=row['missing_hours'], is_incomplete=bool(row['missing_hours']),
                is_manual=source == 'manual'))
        return rows

    @api.model
    def _warranty_report_rebuild(self):
        companies = self._warranty_report_companies()
        if not companies:
            raise AccessError(_("You cannot read warranty costs."))
        # sudo: the report is read only for users; only this method writes its rows.
        report = self.sudo()
        report.search([('create_uid', '=', self.env.uid)]).unlink()
        rows = []
        for case in self.env['warranty.case'].sudo().search([('company_id', 'in', companies.ids)]):
            rows += self._warranty_report_case_rows(case.with_company(case.company_id))
        report.create(rows)

    @api.model
    def action_open_warranty_cost_report(self):
        self._warranty_report_rebuild()
        return self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_accounting.action_warranty_cost_report')

    def action_open_case(self):
        """With the user's own access rights."""
        self.ensure_one()
        self.case_id.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': 'warranty.case',
                'res_id': self.case_id.id, 'view_mode': 'form', 'views': [(False, 'form')],
                'target': 'current'}
