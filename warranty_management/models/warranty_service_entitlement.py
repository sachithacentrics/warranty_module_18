import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tools import float_round

from .warranty_card import PROTECTED_ENTITLEMENT_STATES

_logger = logging.getLogger(__name__)


OPEN_STATES = ('draft', 'pending', 'scheduled', 'in_progress', 'rescheduled', 'missed')
MONITORED_STATES = ('draft', 'pending', 'missed')


class WarrantyServiceEntitlement(models.Model):
    _name = 'warranty.service.entitlement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Warranty Service Entitlement'
    _order = 'warranty_card_id desc, service_no, id'

    name = fields.Char(
        string='Entitlement Reference', required=True, readonly=True, copy=False, default='New')
    warranty_card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', required=True, ondelete='cascade', index=True)
    # Assigned on creation when left empty (next free number on the card).
    service_no = fields.Integer(string='Service No.', copy=False)
    service_type = fields.Selection([
        ('free_preventive', 'Free Preventive Service'),
        ('warranty_complaint', 'Warranty Complaint'),
        ('amc_visit', 'AMC Visit'),
        ('chargeable_inspection', 'Chargeable Inspection'),
        ('chargeable_repair', 'Chargeable Repair'),
        ('installation', 'Installation'),
        ('replacement', 'Replacement'),
    ], string='Service Type', required=True, default='free_preventive')
    due_date = fields.Date(string='Due Date')
    due_date_conflict = fields.Boolean(
        string='Due After Warranty End', compute='_compute_due_date_conflict', store=True)
    usage_due = fields.Float(string='Usage Due', digits=(16, 2), readonly=True)
    usage_unit = fields.Selection([
        ('operating_hours', 'Operating Hours'),
        ('cycles', 'Cycles'),
        ('km', 'KM'),
        ('units_produced', 'Units Produced'),
        ('other', 'Other'),
    ], string='Usage Unit', readonly=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('missed', 'Missed'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
        ('rescheduled', 'Rescheduled'),
    ], string='Status', default='draft', required=True, readonly=True, copy=False, index=True,
        tracking=True)
    merge_status = fields.Selection([
        ('not_merged', 'Not Merged'),
        ('selected', 'Selected'),
        ('merged', 'Merged'),
        ('completed', 'Completed'),
    ], string='Merge Status', default='not_merged', required=True, readonly=True, copy=False)
    worksheet_template_id = fields.Many2one(
        'worksheet.template', string='Product Worksheet Template', readonly=True)

    grace_period_end_date = fields.Date(
        string='Grace Period End Date', compute='_compute_monitoring_dates', store=True,
        readonly=True)
    alert_date = fields.Date(
        string='Alert Date', compute='_compute_monitoring_dates', store=True, readonly=True)
    expiry_reminder_date = fields.Date(
        string='Expiry Reminder Date', compute='_compute_monitoring_dates', store=True,
        readonly=True)
    usage_threshold = fields.Float(
        string='Usage Threshold', compute='_compute_usage_threshold', store=True, readonly=True)
    due_status = fields.Selection([
        ('upcoming', 'Upcoming'),
        ('due', 'Due'),
        ('overdue', 'Overdue'),
    ], string='Due Indicator', readonly=True, copy=False, index=True)
    due_alert_sent = fields.Boolean(string='Due Alert Sent', readonly=True, copy=False)
    expiry_reminder_sent = fields.Boolean(
        string='Expiry Reminder Sent', readonly=True, copy=False)
    due_alert_activity_ids = fields.Many2many(
        'mail.activity', 'warranty_entitlement_due_activity_rel', 'entitlement_id',
        'activity_id', string='Due Alert Activities', readonly=True, copy=False,
        context={'active_test': False})
    expiry_reminder_activity_ids = fields.Many2many(
        'mail.activity', 'warranty_entitlement_expiry_activity_rel', 'entitlement_id',
        'activity_id', string='Expiry Reminder Activities', readonly=True, copy=False,
        context={'active_test': False})

    payment_eligibility = fields.Selection([
        ('not_required', 'Not Required'),
        ('pending', 'Pending'),
        ('passed', 'Passed'),
        ('failed', 'Failed'),
        ('waived', 'Waived'),
    ], string='Payment Eligibility', readonly=True)
    reschedule_count = fields.Integer(
        string='Reschedule Count', compute='_compute_reschedule_count')

    due_date_log_ids = fields.One2many(
        'warranty.service.entitlement.date.log', 'entitlement_id',
        string='Due Date History', readonly=True)
    partner_id = fields.Many2one(
        related='warranty_card_id.partner_id', string='Customer', store=True, index=True)
    company_id = fields.Many2one(
        related='warranty_card_id.company_id', string='Company', store=True, index=True)

    _sql_constraints = [
        ('card_service_no_unique', 'UNIQUE (warranty_card_id, service_no)',
         'Service numbers must be unique per warranty card.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        next_numbers = {}
        for vals in vals_list:
            card = self.env['warranty.card'].browse(vals.get('warranty_card_id'))
            if card and not vals.get('service_no'):
                if card.id not in next_numbers:
                    next_numbers[card.id] = max(
                        card.service_entitlement_ids.mapped('service_no'), default=0) + 1
                vals['service_no'] = next_numbers[card.id]
                next_numbers[card.id] += 1
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].with_company(
                    card.company_id or self.env.company,
                ).next_by_code('warranty.service.entitlement') or 'New'
        entitlements = super().create(vals_list)
        entitlements._schedule_free_service()
        entitlements._update_due_status()
        return entitlements

    def write(self, vals):
        if 'due_date' in vals and not self.env.context.get('warranty_due_date_audited'):
            raise UserError(_(
                "Use the Change Due Date action to change a due date; the previous date, "
                "the new date and the reason are recorded in the due date history."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_protected_states(self):
        if any(state in PROTECTED_ENTITLEMENT_STATES for state in self.mapped('state')):
            raise UserError(_(
                "Completed, Missed, Expired and Cancelled service entitlements cannot be "
                "deleted; they are kept for history."))

    @api.depends('due_date', 'warranty_card_id.warranty_end_date')
    def _compute_due_date_conflict(self):
        for entitlement in self:
            end_date = entitlement.warranty_card_id.warranty_end_date
            entitlement.due_date_conflict = bool(
                entitlement.due_date and end_date and entitlement.due_date > end_date)

    @api.depends('due_date', 'warranty_card_id.service_monitoring_active',
                 'warranty_card_id.grace_period_days', 'warranty_card_id.service_due_alert_days',
                 'warranty_card_id.expiry_reminder_days', 'warranty_card_id.auto_expire_services',
                 'warranty_card_id.carry_forward_allowed')
    def _compute_monitoring_dates(self):
        for entitlement in self:
            card = entitlement.warranty_card_id
            due = entitlement.due_date
            if not (card.service_monitoring_active and due):
                entitlement.grace_period_end_date = False
                entitlement.alert_date = False
                entitlement.expiry_reminder_date = False
                continue
            grace_end = due + timedelta(days=card.grace_period_days)
            entitlement.grace_period_end_date = grace_end
            entitlement.alert_date = due - timedelta(days=card.service_due_alert_days) \
                if card.service_due_alert_days > 0 else False
            # An expiry reminder only exists when the service can really expire.
            entitlement.expiry_reminder_date = \
                grace_end - timedelta(days=card.expiry_reminder_days) \
                if card.expiry_reminder_days > 0 and card.auto_expire_services \
                and not card.carry_forward_allowed else False

    @api.depends('usage_due', 'warranty_card_id.service_monitoring_active',
                 'warranty_card_id.usage_alert_percentage')
    def _compute_usage_threshold(self):
        # Display value only: usage readings are not available yet, nothing is monitored.
        for entitlement in self:
            card = entitlement.warranty_card_id
            entitlement.usage_threshold = float_round(
                entitlement.usage_due * card.usage_alert_percentage / 100, precision_digits=2) \
                if card.service_monitoring_active else 0.0

    def _compute_reschedule_count(self):
        # Rescheduling is delivered in a later part of the Development Mapping.
        self.reschedule_count = 0

    @api.constrains('warranty_card_id', 'service_no')
    def _check_warranty_card(self):
        for card in self.warranty_card_id:
            if card.state != 'confirmed':
                raise ValidationError(_(
                    "Service entitlements can only be created for confirmed warranty cards "
                    "(%s).", card.name))
            if not card._free_services_included():
                raise ValidationError(_(
                    "Warranty card %s does not include free services.", card.name))
            if card.schedule_method == 'amc_plan':
                raise ValidationError(_(
                    "Warranty card %s uses the AMC Plan schedule method; AMC schedules are "
                    "managed by the separate AMC module.", card.name))
            entitlements = card.service_entitlement_ids
            if len(entitlements) > card.free_services_allowed:
                raise ValidationError(_(
                    "Warranty card %(card)s allows %(allowed)s free service(s); no further "
                    "service entitlement can be created.",
                    card=card.name, allowed=card.free_services_allowed))
            if any(not 1 <= number <= card.free_services_allowed
                   for number in entitlements.mapped('service_no')):
                raise ValidationError(_(
                    "Service numbers on warranty card %(card)s must be between 1 and "
                    "%(allowed)s.", card=card.name, allowed=card.free_services_allowed))

    def _schedule_free_service(self):
        """Generate Free Service Schedule: fill the values of the approved schedule
        method for each entitlement's service number. Values entered by the user are kept."""
        for entitlement in self:
            card = entitlement.warranty_card_id
            values = card._get_free_service_due_values(entitlement.service_no)
            update = {}
            if not entitlement.due_date and values['due_date']:
                update['due_date'] = values['due_date']
            if not entitlement.usage_due and values['usage_due']:
                update['usage_due'] = values['usage_due']
                update['usage_unit'] = card.usage_unit
            # Multi-product cards keep no template: one product's template is never picked.
            products = card.unit_warranty_ids.product_id
            if not entitlement.worksheet_template_id and len(products) == 1 \
                    and products.warranty_worksheet_template_id:
                update['worksheet_template_id'] = products.warranty_worksheet_template_id.id
            if update:
                entitlement.with_context(warranty_due_date_audited=True).write(update)


    def _is_monitored(self):
        """Period-based services of confirmed cards with monitoring active and a due date.
        Usage-based monitoring needs usage readings, which are not available yet."""
        self.ensure_one()
        card = self.warranty_card_id
        return bool(card.state == 'confirmed' and card.service_monitoring_active
                    and card.warranty_basis == 'period' and self.due_date)

    def _is_expiry_blocked(self):
        """Entitlements selected or merged into an active service process are never moved to
        Missed or Expired automatically. Part 2 limitation: no Service Job exists yet, so
        only the Merge Status is checked; Part 3/4 extends this with the Service Job state."""
        self.ensure_one()
        return self.merge_status in ('selected', 'merged')

    def _get_due_status(self, today):
        self.ensure_one()
        if not self._is_monitored() or self.state not in OPEN_STATES:
            return False
        if today > self.due_date:
            return 'overdue'
        if today == self.due_date:
            return 'due'
        if self.alert_date and self.alert_date <= today:
            return 'upcoming'
        return False

    def _update_due_status(self, today=None):
        """Due indicator: never changes the lifecycle status. today defaults to the
        current date in the warranty timezone of each company."""
        for company, entitlements in self.grouped('company_id').items():
            company_today = today or company._warranty_today()
            for entitlement in entitlements:
                due_status = entitlement._get_due_status(company_today)
                if entitlement.due_status != due_status:
                    entitlement.due_status = due_status

    def _create_service_activities(self, today, kind):
        """Create the system activities of kind 'due_alert' or 'expiry_reminder': one per
        valid responsible user and entitlement. Invalid users are skipped. Without any valid
        responsible user nothing is created or marked as sent. Returns (entitlements without
        a valid user, skipped users) so the caller can log them."""
        if kind == 'due_alert':
            candidates = self.filtered(lambda e: (
                e.state in ('draft', 'pending') and e.merge_status == 'not_merged'
                and not e.due_alert_sent and e.alert_date
                and e.alert_date <= today <= e.due_date))
        else:
            candidates = self.filtered(lambda e: (
                e.state in MONITORED_STATES and not e.expiry_reminder_sent
                and e.expiry_reminder_date and not e._is_expiry_blocked()
                and e.expiry_reminder_date <= today <= e.grace_period_end_date))
        missing_user = self.browse()
        skipped_users = self.env['res.users']
        for entitlement in candidates:
            users, skipped = entitlement.warranty_card_id._resolve_service_alert_users()
            skipped_users |= skipped
            if not users:
                missing_user |= entitlement
                continue
            activities = self.env['mail.activity']
            for user in users:
                if kind == 'due_alert':
                    activities |= entitlement.activity_schedule(
                        'warranty_management.mail_activity_type_free_service_due',
                        date_deadline=entitlement.due_date,
                        summary=_("Free Service %(number)s due on %(date)s",
                                  number=entitlement.service_no, date=entitlement.due_date),
                        user_id=user.id)
                    entitlement._send_service_email(
                        user, 'warranty_management.mail_template_free_service_due_alert')
                else:
                    activities |= entitlement.activity_schedule(
                        'warranty_management.mail_activity_type_free_service_expiry',
                        date_deadline=entitlement.grace_period_end_date,
                        summary=_("Free Service %(number)s expires after %(date)s",
                                  number=entitlement.service_no,
                                  date=entitlement.grace_period_end_date),
                        user_id=user.id)
                    entitlement._send_service_email(
                        user, 'warranty_management.mail_template_free_service_expiry_reminder')
            if kind == 'due_alert':
                entitlement.write({'due_alert_sent': True,
                                   'due_alert_activity_ids': [Command.set(activities.ids)]})
            else:
                entitlement.write({'expiry_reminder_sent': True,
                                   'expiry_reminder_activity_ids': [Command.set(activities.ids)]})
        return missing_user, skipped_users

    def _send_service_email(self, user, template_xmlid):
        """Queue the dedicated email `template_xmlid` (due alert, expiry reminder or service
        expired) of this entitlement to `user`, whatever the user's notification preference
        (A4, section 6a). The email is only queued (sent by the mail queue) and kept after
        sending, so a delivery failure never blocks the activities / expiry and stays visible
        and retryable in Emails. One email per user and event: the callers run once per alert,
        reminder (Due Alert / Expiry Reminder Sent) or expiry (Expired is final)."""
        self.ensure_one()
        if not user.partner_id.email:
            _logger.warning(
                "Warranty email %s not sent for %s (warranty card %s): user %s (id %s) has no "
                "email address.", template_xmlid, self.name, self.warranty_card_id.name,
                user.login, user.id)
            return
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            _logger.warning("Warranty email template %s not found; no email sent for %s.",
                            template_xmlid, self.name)
            return
        # Sender: the card company's email, else the server default sender address.
        email_from = (self.warranty_card_id.company_id.email_formatted
                      or self.env['ir.mail_server']._get_default_from_address())
        email_values = {'recipient_ids': [Command.set(user.partner_id.ids)], 'auto_delete': False}
        if email_from:
            email_values.update(email_from=email_from, reply_to=email_from)
        try:
            # Own savepoint: an unexpected error only skips this email (logged); the
            # activities and the Due Alert Sent mark are kept.
            with self.env.cr.savepoint():
                template.with_context(lang=user.lang).send_mail(
                    self.id, force_send=False, email_values=email_values)
        except Exception:
            _logger.exception(
                "Warranty email %s could not be prepared for %s (warranty card %s), user %s "
                "(id %s).", template_xmlid, self.name, self.warranty_card_id.name, user.login,
                user.id)

    def _apply_expiry_rules(self, today):
        """T1-T4: Draft/Pending -> Missed after the due date; -> Expired after the grace
        period only when Auto-expire is on and Carry-forward is off."""
        to_miss = to_expire = self.browse()
        for entitlement in self.filtered(lambda e: e.state in MONITORED_STATES):
            if entitlement._is_expiry_blocked() or today <= entitlement.due_date:
                continue
            card = entitlement.warranty_card_id
            if today > entitlement.grace_period_end_date and card.auto_expire_services \
                    and not card.carry_forward_allowed:
                to_expire |= entitlement
            elif entitlement.state != 'missed':
                to_miss |= entitlement
        to_miss.write({'state': 'missed'})
        to_expire.write({'state': 'expired'})
        to_expire._close_system_activities()
        to_expire._send_service_expired_emails(today)

    def _send_service_expired_emails(self, today):
        """Service Expired email to each valid responsible user of the entitlements just
        expired (once: Expired is final). `today` is the Expired On date."""
        for entitlement in self:
            users, __ = entitlement.warranty_card_id._resolve_service_alert_users()
            if not users:
                _logger.warning(
                    "Warranty service expired email not sent for %s (warranty card %s): no "
                    "valid Service Alert Responsible User.",
                    entitlement.name, entitlement.warranty_card_id.name)
            for user in users:
                entitlement.with_context(warranty_expired_on=today)._send_service_email(
                    user, 'warranty_management.mail_template_free_service_expired')

    def _close_system_activities(self):
        """Close only the due alert / expiry reminder activities created by the system;
        their activity types keep done activities, so the history is preserved."""
        activities = (self.due_alert_activity_ids | self.expiry_reminder_activity_ids).filtered(
            'active')
        if activities:
            activities.action_feedback(feedback=_("Service expired"))

    def _reschedule_system_activities(self):
        """After a due date change: move the open system activities to the new dates; when
        all of them are already closed or deleted, allow one new set for the new dates."""
        for entitlement in self:
            due_activities = entitlement.due_alert_activity_ids.filtered('active')
            if due_activities:
                due_activities.write({
                    'date_deadline': entitlement.due_date,
                    'summary': _("Free Service %(number)s due on %(date)s",
                                 number=entitlement.service_no, date=entitlement.due_date),
                })
            elif entitlement.due_alert_sent:
                entitlement.write({'due_alert_sent': False,
                                   'due_alert_activity_ids': [Command.clear()]})

            expiry_activities = entitlement.expiry_reminder_activity_ids.filtered('active')
            if expiry_activities and entitlement.grace_period_end_date:
                expiry_activities.write({
                    'date_deadline': entitlement.grace_period_end_date,
                    'summary': _("Free Service %(number)s expires after %(date)s",
                                 number=entitlement.service_no,
                                 date=entitlement.grace_period_end_date),
                })
            elif entitlement.expiry_reminder_sent and not expiry_activities:
                entitlement.write({'expiry_reminder_sent': False,
                                   'expiry_reminder_activity_ids': [Command.clear()]})

    @api.model
    def _cron_monitor_free_services(self):
        """Daily free service due monitoring, per company in its warranty timezone:
        due indicator, due alerts, expiry reminders, then the Missed / Expired transitions.
        Completed, Cancelled and Expired entitlements are never changed."""
        monitored = self.search([
            ('warranty_card_id.state', '=', 'confirmed'),
            ('warranty_card_id.service_monitoring_active', '=', True),
            ('warranty_card_id.warranty_basis', '=', 'period'),
            ('due_date', '!=', False),
            ('state', 'in', OPEN_STATES),
        ])
        # Indicators left on entitlements that are no longer open or monitored are cleared.
        stale = self.search([('due_status', '!=', False), ('id', 'not in', monitored.ids)])
        stale.write({'due_status': False})

        for company, entitlements in monitored.grouped('company_id').items():
            today = company._warranty_today(log_missing_timezone=True)
            missing_user, skipped_users = entitlements._create_service_activities(
                today, 'due_alert')
            missing_reminder, skipped_reminder = entitlements._create_service_activities(
                today, 'expiry_reminder')
            missing_user |= missing_reminder
            skipped_users |= skipped_reminder
            if skipped_users:
                _logger.warning(
                    "Warranty service monitoring: Service Alert Responsible Users skipped for "
                    "company %s (id %s) because they are archived, not internal or not allowed "
                    "in the company: %s",
                    company.name, company.id, ', '.join(skipped_users.mapped('name')))
            if missing_user:
                _logger.warning(
                    "Warranty service monitoring: no valid Service Alert Responsible User for "
                    "company %s (id %s); due alerts / expiry reminders not created for: %s",
                    company.name, company.id, ', '.join(missing_user.mapped('name')))
            entitlements._apply_expiry_rules(today)
            entitlements._update_due_status(today)

    def action_open_due_date_wizard(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("The due date can only be changed while the entitlement is Draft."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Change Due Date"),
            'res_model': 'warranty.service.entitlement.due.date.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_entitlement_id': self.id},
        }


class WarrantyServiceEntitlementDateLog(models.Model):
    """Audit trail of manual due date changes (user, date, previous / new value, reason)."""
    _name = 'warranty.service.entitlement.date.log'
    _description = 'Service Entitlement Due Date History'
    _order = 'change_date desc, id desc'

    entitlement_id = fields.Many2one(
        'warranty.service.entitlement', string='Service Entitlement', required=True,
        ondelete='cascade', index=True)
    user_id = fields.Many2one(
        'res.users', string='Changed By', required=True, default=lambda self: self.env.user)
    change_date = fields.Datetime(
        string='Changed On', required=True, default=fields.Datetime.now)
    previous_due_date = fields.Date(string='Previous Due Date')
    new_due_date = fields.Date(string='New Due Date')
    reason = fields.Text(string='Reason', required=True)
    company_id = fields.Many2one(
        related='entitlement_id.company_id', string='Company', store=True, index=True)
