import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .amc_contract import RUNNING_STATES, _CONTRACT_MARKER, _marked
from .amc_plan import USAGE_UNITS

_logger = logging.getLogger(__name__)

# AMC-E03 (SRS 10.3 Service Entitlement Interface, 9.13): one record per AMC entitlement.
VISIT_TYPES = [
    ('preventive', 'Preventive Visit'),
    ('free_service', 'Included Free Service'),
]
VISIT_STATES = [
    ('pending', 'Pending'),
    ('scheduled', 'Scheduled'),
    ('in_progress', 'In Progress'),
    ('completed', 'Completed'),
    ('missed', 'Missed'),
    ('expired', 'Expired'),
    ('cancelled', 'Cancelled'),
]
# Entitlements that can still be serviced / consumed.
OPEN_VISIT_STATES = ('pending', 'scheduled', 'in_progress')
DUE_STATUSES = [
    ('upcoming', 'Upcoming'),
    ('due', 'Due'),
    ('overdue', 'Overdue'),
]
# Fields set only by the visit / contract actions (marker), never by the UI, import or RPC.
PROTECTED_VISIT_FIELDS = {
    'contract_id', 'line_id', 'visit_type', 'sequence_no', 'unit_no', 'due_date', 'usage_due',
    'usage_unit', 'state', 'due_status', 'completion_date', 'completed_by_id', 'usage_reading',
    'alert_sent', 'alert_activity_id', 'cancel_reason', 'consumption_source',
}
FREE_PREFIXES = ('message_', 'activity_', 'website_message')


class AmcContractVisit(models.Model):
    """AMC service entitlement (SRS 2.12 / 9.9 / 10.3; AMC-E01 .. E10, B06, C03): one
    preventive visit or one included free service of one covered unit of a contract line.
    Generated only when the contract becomes Active; consumed once, on a valid completion."""
    _name = 'amc.contract.visit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'AMC Visit / Service Entitlement'
    _order = 'due_date, contract_id, line_id, unit_no, sequence_no, id'
    _rec_names_search = ['name', 'contract_id', 'partner_id']

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default='New')
    contract_id = fields.Many2one('amc.contract', string='AMC Contract', required=True,
                                  readonly=True, ondelete='cascade', index=True)
    line_id = fields.Many2one('amc.contract.line', string='Covered Equipment', required=True,
                              readonly=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    partner_id = fields.Many2one(related='contract_id.partner_id', string='Customer',
                                 store=True, index=True)
    commercial_partner_id = fields.Many2one(related='contract_id.commercial_partner_id',
                                            store=True, index=True)
    site_id = fields.Many2one('res.partner', string='Site', compute='_compute_site_id',
                              store=True, index=True)
    plan_id = fields.Many2one(related='contract_id.plan_id', string='AMC Plan', store=True,
                              index=True)
    contract_state = fields.Selection(related='contract_id.state', string='Contract Status',
                                      store=True)
    user_id = fields.Many2one(related='contract_id.user_id', string='Responsible')
    product_id = fields.Many2one(related='line_id.product_id', store=True, index=True)
    serial_id = fields.Many2one(related='line_id.serial_id', store=True, index=True)
    visit_type = fields.Selection(VISIT_TYPES, string='Entitlement Type', required=True,
                                  readonly=True, index=True)
    sequence_no = fields.Integer(string='Service No.', readonly=True)
    sequence_total = fields.Integer(string='Of', readonly=True)
    unit_no = fields.Integer(string='Unit', readonly=True, default=1,
                             help="Covered unit of the equipment line (quantity > 1).")
    label = fields.Char(string='Service', compute='_compute_label')
    due_date = fields.Date(string='Due Date', readonly=True, index=True)
    usage_due = fields.Float(string='Usage Due', digits=(16, 2), readonly=True)
    usage_unit = fields.Selection(USAGE_UNITS, string='Usage Unit', readonly=True)
    alert_date = fields.Date(string='Alert Date', compute='_compute_monitoring_dates',
                             store=True)
    grace_end_date = fields.Date(string='Grace Period End', compute='_compute_monitoring_dates',
                                 store=True)
    scheduled_date = fields.Datetime(
        string='Planned Date', tracking=True, copy=False,
        help="Planned service date. Set manually (Pending -> Scheduled) or by the service job.")
    state = fields.Selection(VISIT_STATES, string='Status', default='pending', required=True,
                             readonly=True, tracking=True, index=True, copy=False)
    due_status = fields.Selection(DUE_STATUSES, string='Due Indicator', readonly=True,
                                  index=True, copy=False)
    alert_sent = fields.Boolean(string='Alert Sent', readonly=True, copy=False)
    alert_activity_id = fields.Many2one('mail.activity', string='Alert Activity', readonly=True,
                                        copy=False, ondelete='set null')
    completion_date = fields.Date(string='Completion Date', readonly=True, copy=False)
    completed_by_id = fields.Many2one('res.users', string='Completed By', readonly=True,
                                      copy=False)
    usage_reading = fields.Float(string='Usage Reading', digits=(16, 2), readonly=True,
                                 copy=False)
    consumption_source = fields.Char(string='Consumed By', readonly=True, copy=False,
                                     help="Document that consumed the entitlement.")
    cancel_reason = fields.Text(string='Cancellation Reason', readonly=True, copy=False)
    note = fields.Text(string='Notes')

    _sql_constraints = [
        ('entitlement_unique',
         'UNIQUE (contract_id, line_id, visit_type, unit_no, sequence_no)',
         'An AMC entitlement exists only once per contract line, unit, type and number.'),
    ]

    @api.depends('line_id.site_id', 'contract_id.site_id', 'contract_id.partner_id')
    def _compute_site_id(self):
        for visit in self:
            visit.site_id = visit.line_id.site_id or visit.contract_id.site_id \
                or visit.contract_id.partner_id

    @api.depends('visit_type', 'sequence_no', 'sequence_total')
    def _compute_label(self):
        labels = dict(VISIT_TYPES)
        for visit in self:
            visit.label = _("%(type)s %(no)s of %(total)s", type=labels.get(visit.visit_type, ''),
                            no=visit.sequence_no, total=visit.sequence_total)

    @api.depends('due_date', 'plan_id.alert_days', 'plan_id.grace_days',
                 'plan_id.visit_planning_mode')
    def _compute_monitoring_dates(self):
        for visit in self:
            plan = visit.plan_id
            if not visit.due_date:
                visit.alert_date = visit.grace_end_date = False
                continue
            visit.alert_date = visit.due_date - timedelta(days=plan.alert_days) \
                if plan.visit_planning_mode == 'alert' else False
            visit.grace_end_date = visit.due_date + timedelta(days=plan.grace_days)

    # ------------------------------------------------------------------ ORM guards
    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('amc_contract_marker') is not _CONTRACT_MARKER:
            raise UserError(_("AMC entitlements are generated by the contract activation."))
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                contract = self.env['amc.contract'].browse(vals.get('contract_id'))
                vals['name'] = self.env['ir.sequence'].with_company(
                    contract.company_id).next_by_code('amc.contract.visit') or 'New'
        visits = super().create(vals_list)
        visits._amc_refresh_due_status()
        return visits

    def write(self, vals):
        if self.env.context.get('amc_contract_marker') is not _CONTRACT_MARKER:
            protected = PROTECTED_VISIT_FIELDS & set(vals)
            if protected:
                raise UserError(_("The status and dates of AMC entitlements are set by their "
                                  "actions (%s).", ', '.join(sorted(protected))))
            if 'scheduled_date' in vals:
                closed = self.filtered(lambda visit: visit.state not in OPEN_VISIT_STATES)
                if closed:
                    raise UserError(_("Only open AMC entitlements can be planned (%s).",
                                      ', '.join(closed.mapped('name'))))
                self._amc_check_planning_allowed()
        result = super().write(vals)
        if 'scheduled_date' in vals and self.env.context.get('amc_contract_marker') \
                is not _CONTRACT_MARKER:
            # Manual planning (core): Pending <-> Scheduled follows the planned date.
            for visit in self:
                state = 'scheduled' if visit.scheduled_date else 'pending'
                if visit.state in ('pending', 'scheduled') and visit.state != state:
                    _marked(visit).write({'state': state})
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_except_generated(self):
        if self.env.context.get('amc_contract_marker') is not _CONTRACT_MARKER:
            raise UserError(_("AMC entitlements are kept for the service history (cancel them "
                              "instead)."))

    # ------------------------------------------------------------------ helpers
    def _amc_check_planning_allowed(self):
        """Planning needs a running, not-held contract (AMC-C03 / C04)."""
        for visit in self:
            if visit.contract_id.state not in ('active', 'expiring'):
                raise UserError(_("AMC entitlement %(visit)s cannot be planned: contract "
                                  "%(contract)s is %(state)s.", visit=visit.name,
                                  contract=visit.contract_id.name,
                                  state=visit.contract_id._amc_state_label()))

    def _amc_log(self, text):
        body = Markup('<p>%s</p>') % text
        for visit in self:
            visit._message_log(body=body)

    def _amc_refresh_due_status(self, today=None):
        """Due indicator of the open preventive visits (AMC-E08; SRS 10.3 "Due" / overdue):
        Upcoming before the alert date, Due from the alert / due date, Overdue after it."""
        today = today or fields.Date.context_today(self)
        for visit in self:
            if visit.state not in OPEN_VISIT_STATES + ('missed',) or not visit.due_date:
                status = False
            elif today > visit.due_date:
                status = 'overdue'
            elif today >= (visit.alert_date or visit.due_date):
                status = 'due'
            else:
                status = 'upcoming'
            if visit.due_status != status:
                _marked(visit).write({'due_status': status})

    def _amc_manual_completion_allowed(self):
        """Extension point: the service bridge consumes AMC entitlements only through the
        Helpdesk -> Service Job -> Field Service chain (AMC-F01) and returns False."""
        return True

    def _amc_completion_problems(self, completion_date, usage_reading=0.0):
        """AMC-E07 / E10: an open entitlement of a running contract, inside the coverage
        period; usage-based visits need a usage reading that does not decrease."""
        self.ensure_one()
        problems = []
        contract = self.contract_id
        if self.state not in OPEN_VISIT_STATES:
            problems.append(_("%(visit)s is %(state)s", visit=self.name,
                              state=dict(VISIT_STATES)[self.state]))
        if contract.state not in RUNNING_STATES:
            problems.append(_("contract %(contract)s is %(state)s", contract=contract.name,
                              state=contract._amc_state_label()))
        if completion_date and contract.start_date and completion_date < contract.start_date:
            problems.append(_("the completion date is before the contract start %s",
                              contract.start_date))
        if completion_date and contract.end_date and completion_date > contract.end_date:
            problems.append(_("the completion date is after the contract end %s",
                              contract.end_date))
        if self.visit_type == 'preventive' and self.usage_unit:
            if usage_reading <= 0:
                problems.append(_("usage-based visit %s needs the usage reading", self.name))
            last = self._amc_last_usage_reading()
            if usage_reading and last and usage_reading < last:
                problems.append(_("the usage reading %(new)s is lower than the last reading "
                                  "%(last)s of this equipment", new=usage_reading, last=last))
        return problems

    def _amc_last_usage_reading(self):
        self.ensure_one()
        previous = self.search([
            ('line_id', '=', self.line_id.id), ('unit_no', '=', self.unit_no),
            ('state', '=', 'completed'), ('usage_reading', '>', 0), ('id', '!=', self.id)],
            order='completion_date desc, id desc', limit=1)
        return previous.usage_reading

    def _amc_consume(self, completion_date=None, usage_reading=0.0, note=None, source=None):
        """Consume the entitlements once (AMC-E06 / E07 / E09). Called by the manual completion
        and by the service bridge (job completion with customer sign-off). Returns the visits
        that were consumed."""
        completion_date = completion_date or fields.Date.context_today(self)
        for visit in self:
            problems = visit._amc_completion_problems(completion_date, usage_reading)
            if problems:
                raise UserError(_("AMC entitlement %(visit)s cannot be completed: %(problems)s.",
                                  visit=visit.name, problems='; '.join(problems)))
        for visit in self:
            _marked(visit).write({
                'state': 'completed', 'completion_date': completion_date,
                'completed_by_id': self.env.uid, 'usage_reading': usage_reading or 0.0,
                'due_status': False, 'consumption_source': source or _("Manual completion"),
                'note': '\n'.join(filter(None, [visit.note, note])) or False,
            })
            if visit.alert_activity_id:
                visit.alert_activity_id.sudo().action_feedback(feedback=_("Visit completed"))
            text = _("%(visit)s (%(label)s, %(product)s) completed on %(date)s by %(user)s "
                     "- %(origin)s.", visit=visit.name, label=visit.label,
                     product=visit.product_id.display_name, date=completion_date,
                     user=self.env.user.name, origin=visit.consumption_source)
            visit._amc_log(text)
            visit.contract_id._amc_log(text)
        self.contract_id._amc_on_visits_completed(self)
        return self

    # ------------------------------------------------------------------ actions
    def action_open_complete_wizard(self):
        self._amc_check_coordinator()
        if not self._amc_manual_completion_allowed():
            raise UserError(_("AMC visits are completed through their Service Job (Helpdesk "
                              "-> Service Job -> Field Service); manual completion is "
                              "disabled."))
        return self._amc_open_wizard('complete')

    def action_open_cancel_wizard(self):
        self._amc_check_manager()
        return self._amc_open_wizard('cancel')

    def _amc_open_wizard(self, action):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Complete AMC Visit") if action == 'complete' else _("Cancel AMC Visit"),
            'res_model': 'amc.contract.visit.action',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visit_ids': [(6, 0, self.ids)], 'default_action': action},
        }

    def _amc_cancel(self, reason):
        """Cancel (AMC Manager, reason): the entitlement is not consumed and not serviced."""
        self._amc_check_manager()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A cancellation reason is required."))
        for visit in self:
            if visit.state not in ('pending', 'scheduled', 'missed'):
                raise UserError(_("Only Pending, Scheduled or Missed AMC entitlements can be "
                                  "cancelled (%s).", visit.name))
            visit._amc_check_not_in_service()
            _marked(visit).write({'state': 'cancelled', 'cancel_reason': reason,
                                  'due_status': False, 'scheduled_date': False})
            visit._amc_log(_("Cancelled by %(user)s: %(reason)s", user=self.env.user.name,
                             reason=reason))
        return True

    def _amc_check_not_in_service(self):
        """Extension point: the service bridge refuses visits linked to an open case / job."""
        return True

    def action_reopen(self):
        """Carry-forward of a Missed visit (SRS 12 #6 / #23 "carry-forward configurable"): an
        AMC Manager reopens it while the contract is running."""
        self._amc_check_manager()
        for visit in self:
            if visit.state != 'missed':
                raise UserError(_("Only Missed AMC visits can be reopened (%s).", visit.name))
            if visit.contract_id.state not in ('active', 'expiring'):
                raise UserError(_("Contract %s is not running: its visits cannot be reopened.",
                                  visit.contract_id.name))
            _marked(visit).write({'state': 'pending'})
            visit._amc_refresh_due_status()
            visit._amc_log(_("Reopened (carried forward) by %s.", self.env.user.name))
        return True

    def _amc_check_coordinator(self):
        if not self.env.user.has_group('amc_management.amc_management_group_coordinator'):
            raise AccessError(_("Only AMC Coordinators can plan or complete AMC visits."))

    def _amc_check_manager(self):
        if not self.env.user.has_group('amc_management.amc_management_group_manager'):
            raise AccessError(_("Only AMC Managers can cancel or reopen AMC visits."))

    def action_view_contract(self):
        self.ensure_one()
        return self.contract_id._amc_open()

    # ------------------------------------------------------------------ scheduler
    @api.model
    def _cron_amc_visits(self, today=None):
        """Daily (AMC-E04 / E08): due indicator, alert activities X days before the due date
        (Alert-Driven plans, contract Active / Expiring, once per visit) and Missed after the
        grace period where the plan says so. Idempotent: repeated runs change nothing."""
        today = today or fields.Date.context_today(self)
        open_visits = self.search([('state', 'in', OPEN_VISIT_STATES + ('missed',)),
                                   ('due_date', '!=', False)])
        open_visits._amc_refresh_due_status(today)
        to_alert = self.search([
            ('state', 'in', ('pending',)), ('visit_type', '=', 'preventive'),
            ('alert_sent', '=', False), ('alert_date', '!=', False), ('alert_date', '<=', today),
            ('contract_state', 'in', ('active', 'expiring')),
            ('plan_id.visit_planning_mode', '=', 'alert')])
        for visit in to_alert:
            visit._amc_create_alert()
        to_miss = self.search([
            ('state', '=', 'pending'), ('visit_type', '=', 'preventive'),
            ('grace_end_date', '!=', False), ('grace_end_date', '<', today),
            ('plan_id.auto_mark_missed', '=', True),
            ('contract_state', 'in', RUNNING_STATES)])
        for visit in to_miss:
            _marked(visit).write({'state': 'missed'})
            visit._amc_log(_("Missed: the grace period ended on %s without service (not "
                             "consumed).", visit.grace_end_date))
        return True

    def _amc_create_alert(self):
        self.ensure_one()
        user = self.contract_id.user_id or self.env.user
        activity = self.sudo().activity_schedule(
            'mail.mail_activity_data_todo', date_deadline=self.due_date, user_id=user.id,
            summary=_("AMC visit due: %s", self.label),
            note=_("%(visit)s of %(contract)s (%(customer)s, %(product)s) is due on %(date)s: "
                   "plan the service.", visit=self.name, contract=self.contract_id.name,
                   customer=self.partner_id.display_name, product=self.product_id.display_name,
                   date=self.due_date))
        _marked(self).write({'alert_sent': True, 'alert_activity_id': activity.id})
        return activity

    @api.constrains('scheduled_date')
    def _check_scheduled_date(self):
        for visit in self:
            if not visit.scheduled_date or not visit.contract_id.start_date:
                continue
            day = fields.Date.to_date(fields.Datetime.context_timestamp(
                visit, visit.scheduled_date))
            if day < visit.contract_id.start_date or (
                    visit.contract_id.end_date and day > visit.contract_id.end_date):
                raise ValidationError(_("The planned date of %(visit)s must be inside the "
                                        "contract period %(start)s - %(end)s.", visit=visit.name,
                                        start=visit.contract_id.start_date,
                                        end=visit.contract_id.end_date))
