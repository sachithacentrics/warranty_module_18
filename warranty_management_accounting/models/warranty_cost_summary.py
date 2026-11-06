from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_amount

from odoo.addons.warranty_management_mrf.models.material_purchase_requisition_approval import \
    RELEASED_STATES
from odoo.addons.warranty_management_mrf.models.material_purchase_requisition_cost import \
    COST_GROUPS, INACTIVE_REQUEST_STATES, WARRANTY_BUCKETS, _cost_totals
from odoo.addons.warranty_management_repair.models.warranty_replacement import OPEN_STATES

from .warranty_cost_line import COST_TYPES


def warranty_parts_figures(material_lines, include_inactive=False):
    """{estimated, approved, actual, unverified} of warranty-borne request lines: the Material
    Request figures themselves, never copied. Customer-paid parts stay out."""
    parts, _flags = _cost_totals(material_lines, include_inactive)
    bearing = WARRANTY_BUCKETS + ('pending',)
    return {
        'estimated': sum(parts[bucket]['estimated'] for bucket in bearing),
        'approved': sum(parts[bucket]['approved_net'] for bucket in bearing),
        'actual': sum(parts[bucket]['actual'] for bucket in WARRANTY_BUCKETS),
        'unverified': sum(parts[bucket]['unverified'] for bucket in WARRANTY_BUCKETS),
    }


def warranty_replacement_figures(replacements):
    """Part 8.2, SRS 11 step 8: the cost of Done replacements, read from their record. Without a
    stock valuation the cost is an estimate, so it is not counted as verified actual cost."""
    verified = replacements.filtered('replacement_cost_verified')
    total = sum(replacements.mapped('replacement_cost'))
    actual = sum(verified.mapped('replacement_cost'))
    return {'estimated': total, 'approved': total, 'actual': actual, 'unverified': total - actual}


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def _warranty_uncosted_timesheets(self):
        """Timesheet lines with hours and no cost: the employee had no hourly cost."""
        task = self.sudo()
        return task.timesheet_ids.filtered(
            lambda line: line.unit_amount and line.currency_id.is_zero(line.amount))

    def _warranty_visit_labour(self):
        """(hours, cost, hours without cost) of the visit's timesheets in company currency; read
        only."""
        self.ensure_one()
        task = self.sudo()
        currency = task.company_id.currency_id
        cost = 0.0
        for line in task.timesheet_ids:
            cost -= line.currency_id._convert(line.amount, currency, task.company_id, line.date)
        return (sum(task.timesheet_ids.mapped('unit_amount')), currency.round(cost),
                sum(task._warranty_uncosted_timesheets().mapped('unit_amount')))

    def _warranty_visit_labour_by_date(self):
        """{timesheet date: [hours, cost, hours without cost]} of the visit, for the cost report."""
        self.ensure_one()
        task = self.sudo()
        currency = task.company_id.currency_id
        uncosted = task._warranty_uncosted_timesheets()
        days = {}
        for line in task.timesheet_ids:
            day = days.setdefault(line.date, [0.0, 0.0, 0.0])
            day[0] += line.unit_amount
            day[1] -= line.currency_id._convert(line.amount, currency, task.company_id, line.date)
            day[2] += line.unit_amount if line in uncosted else 0.0
        return days

    def _warranty_shared_labour(self, job):
        """D7: (hours, cost, hours without cost) of `job` on this shared visit. An equal split
        across the visit's jobs that are not cancelled; the last job takes the rounding, so the
        shares add up to the visit total. Without any such job, all its jobs share it."""
        self.ensure_one()
        task = self.sudo()
        jobs = task.warranty_shared_job_ids.filtered(lambda other: other.state != 'cancelled') \
            or task.warranty_shared_job_ids
        jobs = jobs.sorted('id')
        if job not in jobs:
            return 0.0, 0.0, 0.0
        hours, cost, uncosted = task._warranty_visit_labour()
        share = task.company_id.currency_id.round(cost / len(jobs))
        if job == jobs[-1]:
            share = cost - share * (len(jobs) - 1)
        return hours / len(jobs), share, uncosted / len(jobs)


class WarrantyCostSummaryMixin(models.AbstractModel):
    """Estimated, approved and actual cost of a service job or warranty case (SRS 2.10). Parts come
    from the existing Material Request figures, labour from timesheets, the rest from cost lines;
    nothing is copied or stored."""
    _name = 'warranty.cost.summary.mixin'
    _description = 'Warranty Cost Summary'

    warranty_summary_currency_id = fields.Many2one('res.currency',
                                                   compute='_compute_warranty_cost_summary',
                                                   groups=COST_GROUPS)
    warranty_cost_line_count = fields.Integer(string='Cost Lines',
                                              compute='_compute_warranty_cost_summary',
                                              groups=COST_GROUPS)
    warranty_labour_hours = fields.Float(string='Timesheet Hours',
                                         compute='_compute_warranty_cost_summary',
                                         groups=COST_GROUPS)
    warranty_labour_cost = fields.Monetary(string='Timesheet Labour Cost',
                                           compute='_compute_warranty_cost_summary',
                                           currency_field='warranty_summary_currency_id',
                                           groups=COST_GROUPS)
    warranty_labour_missing_hours = fields.Float(string='Timesheet Hours Without Cost',
                                                 compute='_compute_warranty_cost_summary',
                                                 groups=COST_GROUPS)
    warranty_labour_incomplete = fields.Boolean(
        string='Labour Cost Incomplete', compute='_compute_warranty_cost_summary',
        groups=COST_GROUPS,
        help="Some timesheet hours have no cost because the employee had no hourly cost: labour "
             "and total actual cost are understated.")
    warranty_total_estimated = fields.Monetary(string='Total Estimated Cost',
                                               compute='_compute_warranty_cost_summary',
                                               currency_field='warranty_summary_currency_id',
                                               groups=COST_GROUPS)
    warranty_total_approved = fields.Monetary(string='Total Approved Cost',
                                              compute='_compute_warranty_cost_summary',
                                              currency_field='warranty_summary_currency_id',
                                              groups=COST_GROUPS)
    warranty_total_actual = fields.Monetary(string='Total Actual Cost',
                                            compute='_compute_warranty_cost_summary',
                                            currency_field='warranty_summary_currency_id',
                                            groups=COST_GROUPS)
    warranty_total_expected = fields.Monetary(string='Total Expected Cost',
                                              compute='_compute_warranty_cost_summary',
                                              currency_field='warranty_summary_currency_id',
                                              groups=COST_GROUPS)
    warranty_labour_manual_cost = fields.Monetary(
        string='Manual Labour Cost', compute='_compute_warranty_cost_summary',
        currency_field='warranty_summary_currency_id', groups=COST_GROUPS,
        help="Labour entered on approved workshop cost lines, not read from timesheets.")
    warranty_cost_unverified = fields.Monetary(
        string='Unverified Cost (Not Counted)', compute='_compute_warranty_cost_summary',
        currency_field='warranty_summary_currency_id', groups=COST_GROUPS,
        help="Parts and replacements without a stock valuation layer: an estimate, not part of "
             "Total Actual Cost.")
    warranty_net_cost = fields.Monetary(
        string='Net Warranty Cost', compute='_compute_warranty_cost_summary',
        currency_field='warranty_summary_currency_id', groups=COST_GROUPS,
        help="Total Actual Cost minus Vendor Recovered. Only posted, not reversed vendor credit "
             "notes count as recovered.")
    warranty_cost_overview = fields.Html(string='Cost Summary', sanitize=False,
                                         compute='_compute_warranty_cost_summary',
                                         groups=COST_GROUPS)

    def _warranty_scope_cost_lines(self):
        raise NotImplementedError

    def _warranty_scope_labour(self):
        raise NotImplementedError

    def _warranty_scope_visits(self):
        raise NotImplementedError

    def _warranty_scope_replacements(self):
        """Done replacements whose cost belongs to this record. None on a job: a replacement
        belongs to its case."""
        return self.env['warranty.replacement']

    def _warranty_open_replacements(self):
        return self.env['warranty.replacement']

    def _warranty_cost_figures(self):
        """{type: {estimated, approved, actual}}, plus the total expected cost. The labour actual
        is timesheets plus approved workshop lines; a labour line on a visit holds an estimate.
        The expected cost (D9 gate) is unchanged by the replacement figures."""
        self.ensure_one()
        lines = self._warranty_scope_cost_lines().filtered(
            lambda line: line.state not in ('rejected', 'reversed'))
        parts = warranty_parts_figures(self._warranty_cost_lines(),
                                       self._warranty_cost_include_inactive())
        figures = {'parts': {key: parts[key] for key in ('estimated', 'approved', 'actual')}}
        hours, labour, uncosted = self._warranty_scope_labour()
        for cost_type, _label in COST_TYPES:
            typed = lines.filtered(lambda line: line.cost_type == cost_type)
            figures[cost_type] = {
                'estimated': sum(typed.mapped('estimated_amount')),
                'approved': sum(typed.mapped('counted_approved_amount')),
                'actual': sum(typed.mapped('counted_actual_amount')),
            }
        figures['labour']['actual'] += labour
        replacement = warranty_replacement_figures(self._warranty_scope_replacements())
        figures['replacement'] = {key: replacement[key]
                                  for key in ('estimated', 'approved', 'actual')}
        # Expected: what the case may still cost, without counting a source twice.
        expected = self._warranty_expected_parts()
        typed = lines.filtered(lambda line: line.cost_type == 'labour' and not line.repair_id)
        expected += max(sum(typed.mapped('expected_amount')), labour)
        expected += sum((lines - typed).mapped('expected_amount'))
        return figures, hours, labour, expected, uncosted

    def _warranty_expected_parts(self):
        total = 0.0
        for line in self._warranty_cost_lines().sudo():
            mrf = line.requisition_id
            if not mrf.is_warranty_mrf or mrf.state in INACTIVE_REQUEST_STATES \
                    or line.cost_bucket == 'customer':
                continue
            base = line.approved_net_cost if line.approved_cost_recorded else line.routing_cost
            total += max(base, line.actual_cost)
        return total

    def _warranty_expected_cost(self):
        self.ensure_one()
        return self._warranty_cost_figures()[3]

    def _compute_warranty_cost_summary(self):
        labels = dict(COST_TYPES, parts=_("Parts"), replacement=_("Replacement"))
        for record in self:
            currency = record.sudo().company_id.currency_id or self.env.company.currency_id
            figures, hours, labour, expected, uncosted = record._warranty_cost_figures()
            totals = {key: sum(values[key] for values in figures.values())
                      for key in ('estimated', 'approved', 'actual')}
            mark = Markup(' <span class="badge text-bg-warning">%s</span>') % _("Incomplete") \
                if uncosted else Markup('')

            def money(amount):
                return escape(format_amount(self.env, amount, currency))

            rows = Markup('').join(
                Markup('<tr><th>%s</th><td class="text-end">%s</td><td class="text-end">%s</td>'
                       '<td class="text-end">%s%s</td></tr>') % (
                    labels[key], money(values['estimated']), money(values['approved']),
                    money(values['actual']), mark if key == 'labour' else Markup(''))
                for key, values in figures.items())
            total_row = Markup('<tr class="fw-bold"><th>%s</th><td class="text-end">%s</td>'
                               '<td class="text-end">%s</td><td class="text-end">%s%s</td></tr>') % (
                _("Total"), money(totals['estimated']), money(totals['approved']),
                money(totals['actual']), mark)
            recovered = record.sudo().vendor_recovered_amount
            net = totals['actual'] - recovered
            total_row += Markup('<tr><th>%s</th><td></td><td></td><td class="text-end">%s</td></tr>'
                                '<tr class="fw-bold"><th>%s</th><td></td><td></td>'
                                '<td class="text-end">%s</td></tr>') % (
                _("Vendor Recovered (posted credit notes)"), money(-recovered),
                _("Net Warranty Cost"), money(net))
            notes = []
            if uncosted:
                names = record._warranty_scope_visits()._warranty_uncosted_timesheets() \
                    .employee_id.mapped('name')
                notes.append(_(
                    "Labour cost is incomplete: %(hours)s hours have no cost because the employee "
                    "had no hourly cost (%(employees)s). Actual cost is understated.",
                    hours=round(uncosted, 2), employees=', '.join(sorted(set(names)))))
            unverified = warranty_parts_figures(
                record._warranty_cost_lines(), record._warranty_cost_include_inactive()
            )['unverified'] + warranty_replacement_figures(
                record._warranty_scope_replacements())['unverified']
            if not currency.is_zero(unverified):
                notes.append(_(
                    "%(amount)s of parts or replacement cost has no stock valuation: it is an "
                    "estimate and is not counted in actual cost.", amount=money(unverified)))
            waiting = record._warranty_open_replacements()
            if waiting:
                notes.append(_("Replacement %(names)s is not delivered yet: its cost counts once "
                               "it is Done.", names=', '.join(waiting.mapped('name'))))
            warning = Markup('').join(
                Markup('<div class="alert alert-warning" role="alert">%s</div>') % note
                for note in notes)
            manual = sum(record._warranty_scope_cost_lines().filtered(
                lambda line: line.cost_type == 'labour' and line.actual_is_manual
            ).mapped('counted_actual_amount'))
            if not currency.is_zero(manual):
                warning += Markup('<p class="text-muted">%s</p>') % _(
                    "Labour actual: %(timesheets)s from timesheets, %(manual)s entered manually on "
                    "workshop cost lines.", timesheets=money(labour), manual=money(manual))
            head = Markup('<thead><tr><th>%s</th><th class="text-end">%s</th>'
                          '<th class="text-end">%s</th><th class="text-end">%s</th></tr></thead>') % (
                _("Cost"), _("Estimated"), _("Approved"), _("Actual"))
            record.update({
                'warranty_summary_currency_id': currency.id,
                'warranty_cost_line_count': len(record._warranty_scope_cost_lines()),
                'warranty_labour_hours': hours,
                'warranty_labour_cost': labour,
                'warranty_labour_missing_hours': uncosted,
                'warranty_labour_incomplete': bool(uncosted),
                'warranty_total_estimated': totals['estimated'],
                'warranty_total_approved': totals['approved'],
                'warranty_total_actual': totals['actual'],
                'warranty_total_expected': expected,
                'warranty_labour_manual_cost': manual,
                'warranty_cost_unverified': unverified,
                'warranty_net_cost': net,
                'warranty_cost_overview': warning + Markup(
                    '<table class="table table-sm">%s<tbody>%s%s</tbody></table>') % (
                    head, rows, total_row),
            })

    def _warranty_cost_lines_action(self, context):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_accounting.action_warranty_cost_line')
        action['domain'] = [('id', 'in', self._warranty_scope_cost_lines().ids)]
        action['context'] = context
        return action


class WarrantyCase(models.Model):
    _name = 'warranty.case'
    _inherit = ['warranty.case', 'warranty.cost.summary.mixin']

    warranty_cost_entry_ids = fields.One2many('warranty.cost.line', 'case_id',
                                              string='Warranty Cost Lines', groups=COST_GROUPS)

    def _warranty_scope_cost_lines(self):
        return self.sudo().warranty_cost_entry_ids

    def _warranty_scope_labour(self):
        hours = cost = uncosted = 0.0
        for job in self.sudo().service_job_ids:
            job_hours, job_cost, job_uncosted = job._warranty_scope_labour()
            hours += job_hours
            cost += job_cost
            uncosted += job_uncosted
        return hours, cost, uncosted

    def _warranty_scope_visits(self):
        jobs = self.sudo().service_job_ids
        return jobs.visit_ids | jobs.shared_visit_ids

    def _warranty_scope_replacements(self):
        """A Component replacement issues its part through a Material Request: that cost counts
        as Parts only (mapping row 4), so it is never read here."""
        return self.sudo().warranty_replacement_ids.filtered(
            lambda replacement: replacement.state == 'done'
            and replacement.replacement_type != 'component')

    def _warranty_open_replacements(self):
        return self.sudo().warranty_replacement_ids.filtered(
            lambda replacement: replacement.state in OPEN_STATES
            and replacement.replacement_type != 'component')

    def action_view_warranty_cost_lines(self):
        return self._warranty_cost_lines_action({'default_case_id': self.id})

    def _warranty_expected_cost_error(self):
        """D9, SRS 2.10: above the threshold, nothing proceeds while a cost line or Material
        Request of the case is unapproved. Off by default; threshold 0 checks any expected cost.
        Approved records never block, so earlier approvals stay valid."""
        self.ensure_one()
        case = self.sudo()
        company = case.company_id
        if not company.warranty_cost_gate_enabled:
            return False
        expected = case._warranty_expected_cost()
        currency = company.currency_id
        if currency.compare_amounts(expected, company.warranty_cost_gate_threshold) <= 0:
            return False
        lines = case.warranty_cost_entry_ids.filtered(
            lambda line: line.state in ('draft', 'submitted')
            and not currency.is_zero(line.expected_amount))
        requests = case.material_request_ids.filtered(
            lambda mrf: mrf.is_warranty_mrf and mrf.state not in RELEASED_STATES
            and mrf.state not in INACTIVE_REQUEST_STATES and mrf.warranty_mrf_status != 'closed')
        pending = lines.mapped('name') + requests.mapped('name')
        if not pending:
            return False
        return _("Total expected cost %(expected)s of case %(case)s is above the threshold "
                 "%(threshold)s: waiting for approval of %(pending)s.",
                 expected=format_amount(self.env, expected, currency), case=case.name,
                 threshold=format_amount(self.env, company.warranty_cost_gate_threshold, currency),
                 pending=', '.join(pending))


class WarrantyServiceJob(models.Model):
    _name = 'warranty.service.job'
    _inherit = ['warranty.service.job', 'warranty.cost.summary.mixin']

    warranty_cost_entry_ids = fields.One2many('warranty.cost.line', 'job_id',
                                              string='Warranty Cost Lines', groups=COST_GROUPS)

    def _warranty_scope_cost_lines(self):
        return self.sudo().warranty_cost_entry_ids

    def _warranty_scope_labour(self):
        self.ensure_one()
        job = self.sudo()
        hours = cost = uncosted = 0.0
        for task in job.visit_ids:
            task_hours, task_cost, task_uncosted = task._warranty_visit_labour()
            hours += task_hours
            cost += task_cost
            uncosted += task_uncosted
        for task in job.shared_visit_ids:
            task_hours, task_cost, task_uncosted = task._warranty_shared_labour(job)
            hours += task_hours
            cost += task_cost
            uncosted += task_uncosted
        return hours, cost, uncosted

    def _warranty_scope_visits(self):
        job = self.sudo()
        return job.visit_ids | job.shared_visit_ids

    def _warranty_labour_by_date(self):
        """{timesheet date: [hours, cost, hours without cost]} of this job: its visits in full, and
        its share of each shared visit. The dates add up to the job's labour figures."""
        self.ensure_one()
        job = self.sudo()
        days = {}

        def add(task, hours, cost, uncosted):
            visit = task._warranty_visit_labour_by_date()
            total = [sum(day[index] for day in visit.values()) for index in range(3)]
            for date, day in visit.items():
                entry = days.setdefault(date, [0.0, 0.0, 0.0])
                for index, share in enumerate((hours, cost, uncosted)):
                    if total[index]:
                        entry[index] += day[index] * share / total[index]

        for task in job.visit_ids:
            add(task, *task._warranty_visit_labour())
        for task in job.shared_visit_ids:
            add(task, *task._warranty_shared_labour(job))
        return days

    def action_view_warranty_cost_lines(self):
        return self._warranty_cost_lines_action({'default_case_id': self.warranty_case_id.id,
                                                 'default_job_id': self.id})

    def _warranty_confirm_problems(self):
        problems = super()._warranty_confirm_problems()
        error = self.warranty_case_id and self.warranty_case_id._warranty_expected_cost_error()
        if error:
            problems.append(error)
        return problems

    def _warranty_plan_next_visit(self, planned_date, main_technician, support_technicians=None):
        error = self.warranty_case_id and self.warranty_case_id._warranty_expected_cost_error()
        if error:
            raise UserError(error)
        return super()._warranty_plan_next_visit(planned_date, main_technician,
                                                 support_technicians)


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    def _warranty_cost_movements(self):
        """[(date, amount, verified)] behind the line's actual cost, for the cost report. The same
        moves as _warranty_cost_values: a usage counts on the date of its stock move, a reversal
        takes it back on the reversal date, so an earlier period keeps what happened in it."""
        self.ensure_one()
        line = self.sudo()
        company = line.requisition_id.company_id
        movements = []
        for entry in line.warranty_consumption_ids.filtered(lambda e: e.kind == 'used'):
            moves = entry.move_ids.filtered(
                lambda move: move.state == 'done'
                and move.location_id.usage in ('internal', 'transit')
                and move.location_dest_id.usage not in ('internal', 'transit'))
            for move in moves:
                amount, verified = self._warranty_move_value(move)
                date = company._warranty_local_date(move.date)
                movements.append((date, amount, verified))
                if entry.state != 'done':
                    movements.append((company._warranty_local_date(entry.reversed_date or move.date),
                                      -amount, verified))
        for move in line.sale_line_ids.move_ids.filtered(lambda move: move.state == 'done'):
            date = company._warranty_local_date(move.date)
            if move.location_dest_id.usage == 'customer' \
                    and move.location_id.usage != 'customer':
                amount, verified = self._warranty_move_value(move)
                movements.append((date, amount, verified))
            elif move.location_id.usage == 'customer' \
                    and move.location_dest_id.usage != 'customer':
                amount, verified = self._warranty_return_value(move)
                movements.append((date, -amount, verified))
        return movements


class WarrantyVendorClaimRecovery(models.Model):
    _inherit = 'warranty.vendor.claim.recovery'

    def _warranty_recovery_movements(self):
        """[(date, amount)] behind the recovered amount, for the cost report: the credit note on
        its accounting date, and each posted reversal, in proportion, on its own date."""
        self.ensure_one()
        move = self.move_id.sudo()
        total = abs(move.amount_total_signed)
        if not self.active or move.state != 'posted':
            return []
        eligible = self._warranty_recovery_eligible_amount()
        movements = [(move.date, eligible)]

        def walk(parent, sign):
            for reversal in parent.reversal_move_ids.filtered(lambda r: r.state == 'posted'):
                if total:
                    movements.append((reversal.date, -sign * eligible
                                      * abs(reversal.amount_total_signed) / total))
                walk(reversal, -sign)

        walk(move, 1)
        return movements


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    def _warranty_release_error(self):
        error = super()._warranty_release_error()
        if error or not self.warranty_case_id:
            return error
        return self.warranty_case_id._warranty_expected_cost_error()


class RepairOrder(models.Model):
    _inherit = 'repair.order'

    warranty_cost_entry_ids = fields.One2many('warranty.cost.line', 'repair_id',
                                              string='Warranty Cost Lines', groups=COST_GROUPS)
    warranty_cost_line_count = fields.Integer(string='Cost Lines', groups=COST_GROUPS,
                                              compute='_compute_warranty_cost_line_count')

    def _compute_warranty_cost_line_count(self):
        for repair in self:
            repair.warranty_cost_line_count = len(repair.sudo().warranty_cost_entry_ids)

    def action_view_warranty_cost_lines(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_accounting.action_warranty_cost_line')
        action['domain'] = [('repair_id', '=', self.id)]
        action['context'] = {'default_case_id': self.warranty_case_id.id,
                             'default_repair_id': self.id, 'default_cost_type': 'labour'}
        return action
