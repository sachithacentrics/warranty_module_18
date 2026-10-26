from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .warranty_service_job import CLOSED_JOB_STATES, _COMPLETION_MARKER


class WarrantyCase(models.Model):
    """Phase 4.1 - From Part 3 Warranty Case Eligible / Approved -> Read Linked Service
    Entitlement(s) -> merge -> Create / Prepare Service Job (Part 4 diagram)."""
    _inherit = 'warranty.case'

    service_job_ids = fields.One2many('warranty.service.job', 'warranty_case_id',
                                      string='Service Jobs', readonly=True)
    service_job_count = fields.Integer(compute='_compute_service_job_count')
    open_service_job_id = fields.Many2one('warranty.service.job', string='Open Service Job',
                                          compute='_compute_service_job_count')
    # Phase 4.10 (approved C7 / C12): how the chargeable work ended (set by the job completion or
    # Customer Declined Repair; Closed comes with the accounting steps, Part 8).
    warranty_chargeable_outcome = fields.Selection([
        ('inspection_only', 'Inspection Only (no repair needed)'),
        ('repair_declined', 'Inspection Only (repair declined)'),
        ('repair_completed', 'Repair Completed'),
        ('service_completed', 'Chargeable Service Completed'),
    ], string='Chargeable Outcome', readonly=True, copy=False, tracking=True)

    @api.depends('service_job_ids.state')
    def _compute_service_job_count(self):
        for case in self:
            case.service_job_count = len(case.service_job_ids)
            case.open_service_job_id = case.service_job_ids.filtered(
                lambda job: job.state not in CLOSED_JOB_STATES)[:1]

    def write(self, vals):
        if 'warranty_chargeable_outcome' in vals and not self.env.su:
            raise UserError(_("The chargeable outcome is set by the job completion."))
        # Approved K6: a warranty case is completed by the completion of its service job only.
        if vals.get('state') == 'completed' \
                and self.env.context.get('warranty_completion_marker') is not _COMPLETION_MARKER:
            raise UserError(_("Warranty cases are completed with Complete Visit on their service "
                              "job's Field Service visit."))
        return super().write(vals)

    def _warranty_job_merge_problems(self, services):
        """Check Service Merge Compatibility (Part 4 diagram; G4 A as revised by the approved
        cross-card service merge, Option A / D3 / D6): same customer and company, same site,
        no conflicting status (3.1 availability rule), not on another open job or active case,
        each card checked, overlapping service windows."""
        self.ensure_one()
        available = self.env['warranty.service.entitlement']._warranty_pending_services(
            self.partner_id, self.company_id)
        # Approved Option A: services of several cards of the customer; each card is checked
        # (customer / company, confirmed, site D6, units D4, period) instead of "same card".
        card_problems = {card: self._warranty_service_card_problems(card)
                         for card in services.warranty_card_id}
        problems = []
        for service in services:
            card = service.warranty_card_id
            reasons = [reason for __, reason in card_problems[card]]
            if service not in available:
                reasons.append(_("conflicting status: no longer available (status, grace period "
                                 "or balance)"))
            other_jobs = service.service_job_ids.filtered(
                lambda job: job.state not in CLOSED_JOB_STATES)
            if other_jobs:
                reasons.append(_("already merged into the open service job %s",
                                 ', '.join(other_jobs.mapped('name'))))
            other_cases = service._warranty_active_cases(exclude=self)
            if other_cases:
                reasons.append(_("linked to the active warranty case %s",
                                 ', '.join(other_cases.mapped('name'))))
            if reasons:
                problems.append('%s (%s): %s' % (service.name, card.name, '; '.join(reasons)))
        # Approved D3: the service windows must overlap; BA-approved F3 / K7: service sequence.
        return problems + self._warranty_window_problems(services) + (
            services._warranty_sequence_problems())

    def action_prepare_service_job(self):
        """Create / Prepare Service Job (Draft) from an Approved, Eligible case (agreed status
        workflow); one open job per case (approved R2)."""
        self.ensure_one()
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can prepare service jobs."))
        if self.state == 'chargeable':
            return self._warranty_prepare_chargeable_job()
        if self.state != 'approved' or self.eligibility_result != 'eligible':
            raise UserError(_("Service jobs are prepared from Approved, Eligible warranty cases "
                              "(%s).", self.name))
        if self.open_service_job_id:
            raise UserError(_("%(case)s already has the open service job %(job)s.",
                              case=self.name, job=self.open_service_job_id.name))
        services = self.service_entitlement_ids
        if len(services) > 1 or services.warranty_card_id - self.warranty_card_id:
            problems = self._warranty_job_merge_problems(services)
            if problems:
                raise UserError(_("The free services cannot be merged into one service job:\n%s",
                                  '\n'.join(problems)))
        job = self.env['warranty.service.job'].create({
            'warranty_case_id': self.id,
            'entitlement_ids': [(6, 0, services.ids)],
        })
        if len(services) == 1:
            services.merge_status = 'selected'
            text = _("Single free service selected: %s.", services.name)
        elif services:
            services.write({'merge_status': 'merged'})
            text = _("Free services merged: %s.", ', '.join(services.mapped('name')))
        else:
            text = _("No free service linked: service job for the warranty claim only.")
        title = _("Service job %(job)s prepared (Draft) from %(case)s", job=job.name,
                  case=self.name)
        body = Markup('<p><b>%s</b></p><p>%s</p>') % (title, text)
        job._message_log(body=body)
        self._message_log(body=body)
        for service in services:
            service._message_log(body=Markup('<p>%s</p>') % _(
                "Linked to service job %(job)s (%(status)s).", job=job.name,
                status=dict(service._fields['merge_status']._description_selection(
                    self.env))[service.merge_status]))
        return self._warranty_open_service_job(job)

    def _warranty_open_service_job(self, job):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'warranty.service.job',
            'view_mode': 'form',
            'res_id': job.id,
        }

    def action_view_service_jobs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'warranty_management_fsm.action_warranty_service_job')
        action.update({'domain': [('warranty_case_id', '=', self.id)], 'context': {}})
        if len(self.service_job_ids) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')],
                           'res_id': self.service_job_ids.id})
        return action

    # ------------------------------------------------------------------ Phase 4.10
    def _warranty_trigger_met(self, order):
        """Approved C2: On Sales Order Confirmation = the chargeable order is confirmed (no
        invoice / payment needed); On Payment = it is fully invoiced and every posted invoice
        settled (Part 3.3 rule: Paid, or In Payment fully covered by registered payments); a paid
        advance invoice with an unpaid remainder does not trigger."""
        self.ensure_one()
        if order.state != 'sale' or not order.order_line.filtered(
                lambda line: not line.display_type and line.product_id):
            return False
        trigger = self.helpdesk_ticket_id.team_id.warranty_job_trigger or 'sale_confirmation'
        if trigger == 'sale_confirmation':
            return True
        if order.invoice_status != 'invoiced':
            return False
        invoices = order.invoice_ids.filtered(
            lambda move: move.move_type == 'out_invoice' and move.state == 'posted')
        if not invoices:
            return False
        uncovered = self.env['warranty.case']._warranty_uncovered_amounts(invoices)
        return all(invoice.currency_id.is_zero(uncovered[invoice.id]) for invoice in invoices)

    def _warranty_trigger_orders(self):
        """Confirmed chargeable orders of the case's current chargeable step that meet the
        team Job Trigger. sudo: orders are read for the check only."""
        self.ensure_one()
        if self.state != 'chargeable' or not self.chargeable_type:
            return self.env['sale.order']
        orders = self.env['sale.order'].sudo().search([
            ('warranty_case_id', '=', self.id), ('state', '=', 'sale'),
            ('warranty_chargeable_purpose', '=', self.chargeable_type)], order='id')
        return orders.filtered(self._warranty_trigger_met)

    def _warranty_chargeable_job(self, order):
        """The (not cancelled) chargeable job of an order: one per order (approved C3)."""
        return self.env['warranty.service.job'].sudo().search(
            [('chargeable_order_id', '=', order.id), ('state', '!=', 'cancelled')], limit=1)

    def _warranty_create_chargeable_job(self, order, origin):
        """Draft Chargeable Service Job of a triggering order (approved C3 / C5 / C6 / C11):
        never twice for an order, never while another job of the case is open; no free
        service. sudo: created by the sale / payment that met the trigger (the user may have
        no Helpdesk rights); company, ticket and case come from the case."""
        self.ensure_one()
        existing = self._warranty_chargeable_job(order)
        if existing or self.open_service_job_id:
            return existing
        job_types = {'inspection': 'chargeable_inspection', 'repair': 'chargeable_repair',
                     'excluded_items': 'chargeable_excluded'}
        job = self.env['warranty.service.job'].sudo().create({
            'warranty_case_id': self.id,
            'job_type': job_types[order.warranty_chargeable_purpose],
            'chargeable_order_id': order.id,
        })
        labels = dict(job._fields['job_type']._description_selection(self.env))
        body = Markup('<p><b>%s</b></p>') % _(
            "Draft service job %(job)s (%(type)s) created on %(origin)s of %(order)s (Job "
            "Trigger: %(trigger)s); no free service is used.", job=job.name,
            type=labels[job.job_type], origin=origin, order=order.name,
            trigger=dict(self.helpdesk_ticket_id.team_id._fields['warranty_job_trigger']
                         ._description_selection(self.env)).get(
                self.helpdesk_ticket_id.team_id.warranty_job_trigger or 'sale_confirmation'))
        job._message_log(body=body)
        self.sudo()._message_log(body=body)
        return job

    def _warranty_check_chargeable_trigger(self, origin):
        for case in self.filtered(lambda case: case.state == 'chargeable'):
            for order in case._warranty_trigger_orders():
                if case._warranty_create_chargeable_job(order, origin):
                    break

    def _warranty_prepare_chargeable_job(self):
        """Prepare Service Job on a Chargeable case (approved C3 fallback): only when the Job
        Trigger is met; opens the existing job instead of creating a second one."""
        self.ensure_one()
        if self.open_service_job_id:
            raise UserError(_("%(case)s already has the open service job %(job)s.",
                              case=self.name, job=self.open_service_job_id.name))
        orders = self._warranty_trigger_orders()
        if not orders:
            raise UserError(_(
                "The Job Trigger of %s is not met yet: the chargeable quotation must be confirmed "
                "(On Sales Order Confirmation) or fully invoiced and paid (On Payment).",
                self.name))
        job = self._warranty_create_chargeable_job(orders[:1], _("Prepare Service Job"))
        return self._warranty_open_service_job(job.with_env(self.env))

    def _warranty_send_todo(self, order):
        """Approved C10: no automatic customer email; Helpdesk To-Do to send the quotation
        (ticket's assigned user, else the case creator). sudo: activity on the case."""
        self.ensure_one()
        user = self.helpdesk_ticket_id.user_id or self.create_uid
        summary = _("Send quotation %s to the customer", order.name)
        if user and not self.activity_ids.filtered(lambda a: a.summary == summary):
            self.sudo().activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id, summary=summary,
                note=_("Send the chargeable quotation with its Send button (no automatic "
                       "customer notification)."))

    def _warranty_close_send_todo(self, order):
        self.ensure_one()
        summary = _("Send quotation %s to the customer", order.name)
        self.sudo().activity_ids.filtered(lambda a: a.summary == summary).action_feedback(
            feedback=_("Quotation sent."))

    def _warranty_convert_chargeable(self, chargeable_type):
        """Phase 4.10: the quotation created by Convert to Chargeable gets its purpose and the
        send To-Do."""
        # sudo: the case's quotations before / after the conversion are compared.
        Order = self.env['sale.order'].sudo()
        before = Order.search([('warranty_case_id', 'in', self.ids)])
        result = super()._warranty_convert_chargeable(chargeable_type)
        for order in Order.search([('warranty_case_id', 'in', self.ids)]) - before:
            if not order.warranty_chargeable_purpose:
                order.warranty_chargeable_purpose = chargeable_type
                self._warranty_send_todo(order)
        return result

    def action_open_decline_repair_wizard(self):
        self.ensure_one()
        self._warranty_check_decline_repair()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Customer Declined Repair"),
            'res_model': 'warranty.case.repair.decline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_case_id': self.id},
        }

    def _warranty_check_decline_repair(self):
        self.ensure_one()
        if not self.env.user.has_group('helpdesk.group_helpdesk_user'):
            raise AccessError(_("Only Helpdesk users can record a declined repair."))
        inspection = self.service_job_ids.filtered(
            lambda job: job.job_type == 'chargeable_inspection' and job.state == 'completed')
        confirmed = self.env['sale.order'].sudo().search_count([
            ('warranty_case_id', '=', self.id), ('warranty_chargeable_purpose', '=', 'repair'),
            ('state', '=', 'sale')])
        if self.state != 'chargeable' or self.chargeable_type != 'repair' or not inspection \
                or self.open_service_job_id or confirmed:
            raise UserError(_(
                "A declined repair is recorded on a Chargeable case waiting for its repair "
                "quotation, after a completed inspection, with no open job and no confirmed "
                "repair order (%s).", self.name))
        return inspection

    def _warranty_decline_repair(self, reason):
        """Customer rejects the repair (SRS 9.7 step 8, approved C7.6): inspection-only
        closure; the inspection history is kept; the draft / sent repair quotations are
        cancelled; the case is Completed (Closed after the accounting steps, Part 8)."""
        self.ensure_one()
        inspection = self._warranty_check_decline_repair()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required."))
        # sudo: only this case's open repair quotations are cancelled (Helpdesk users may have
        # no Sales rights); the case status is the checked decline.
        orders = self.env['sale.order'].sudo().search([
            ('warranty_case_id', '=', self.id), ('warranty_chargeable_purpose', '=', 'repair'),
            ('state', 'in', ('draft', 'sent'))])
        orders._action_cancel()
        for order in orders:
            self._warranty_close_send_todo(order)
        self.sudo().with_context(warranty_completion_marker=_COMPLETION_MARKER).write({
            'state': 'completed', 'warranty_chargeable_outcome': 'repair_declined'})
        self._message_log(body=Markup('<p><b>%s</b></p>') % _(
            "Customer declined the repair (recorded by %(user)s): inspection-only closure. "
            "Reason: %(reason)s. Inspection job %(job)s kept; repair quotations cancelled: "
            "%(orders)s. Closed after the accounting steps (Part 8).", user=self.env.user.name,
            reason=reason, job=', '.join(inspection.mapped('name')),
            orders=', '.join(orders.mapped('name')) or _("none")))
        return True
