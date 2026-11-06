"""Warranty Start Date Automation – Installation basis (approved design
warranty_management/doc/start_date_design.md §7.3, D4–D8, Q6–Q9).

Installation Field Service tasks are identified positively (Warranty Installation Service
product, or Create Installation Task on the card), linked explicitly to the relevant
Installation-basis warranty cards, and their original completion time starts the warranty.
Part 4 service-job visits are never installation tasks; their completion logic is unchanged."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command

from odoo.addons.warranty_management.models.warranty_card import (
    DATE_CORRECTION_GROUP, OPEN_CARD_STATES)

# Purpose and completion time are set by system code only (SO line task creation, Create
# Installation Task, task completion). Python object: no client can send it in a context.
_INSTALLATION_MARKER = object()
TASK_SYSTEM_FIELDS = {'warranty_task_purpose', 'warranty_installation_done_at'}
TASK_PURPOSES = [('installation', 'Installation')]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    warranty_installation_service = fields.Boolean(
        string='Warranty Installation Service',
        help="The Field Service task created from this service on a Sales Order is a warranty "
             "installation task: its completion starts the warranty of the linked "
             "Installation-basis warranty cards.")
    warranty_installation_product_ids = fields.Many2many(
        'product.template', 'warranty_installation_product_rel', 'service_id', 'product_id',
        string='Installs Products', domain=[('warranty_applicable', '=', True)],
        help="Warranted products installed by this service: the installation task of a Sales "
             "Order is linked only to the Installation-basis warranty cards of these products. "
             "Empty: no automatic link.")

    @api.constrains('warranty_installation_service', 'type', 'service_tracking', 'project_id')
    def _check_warranty_installation_service(self):
        for template in self.filtered('warranty_installation_service'):
            if template.type != 'service' or template.service_tracking != 'task_global_project' \
                    or (template.project_id and not template.project_id.is_fsm):
                raise ValidationError(_(
                    "%s: a Warranty Installation Service must be a service that creates a task "
                    "in a Field Service project.", template.display_name))


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _timesheet_create_task_prepare_values(self, project):
        values = super()._timesheet_create_task_prepare_values(project)
        if self.product_id.warranty_installation_service and project.is_fsm:
            values['warranty_task_purpose'] = 'installation'
        return values

    def _timesheet_create_task(self, project):
        task = super(SaleOrderLine, self.with_context(
            warranty_installation_marker=_INSTALLATION_MARKER))._timesheet_create_task(project)
        task = task.with_env(self.env)
        if task.warranty_task_purpose == 'installation':
            task._warranty_link_relevant_cards()
        return task


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _warranty_create_draft_cards(self, grouping_mode):
        result = super()._warranty_create_draft_cards(grouping_mode)
        # Cards created after the installation task (Warranty Grouping after confirmation).
        # sudo: the salesperson may not read Field Service tasks; links by system rule only.
        tasks = self.env['project.task'].sudo().search([
            ('sale_line_id.order_id', 'in', self.ids),
            ('warranty_task_purpose', '=', 'installation'), ('state', '!=', '1_canceled')])
        tasks.with_env(self.env)._warranty_link_relevant_cards()
        return result


class ProjectTask(models.Model):
    _inherit = 'project.task'

    warranty_task_purpose = fields.Selection(
        TASK_PURPOSES, string='Warranty Task Purpose', readonly=True, copy=False,
        index='btree_not_null')
    warranty_installation_card_ids = fields.Many2many(
        'warranty.card', 'warranty_installation_task_card_rel', 'task_id', 'card_id',
        string='Installation Warranty Cards', copy=False,
        help="Installation-basis warranty cards started by the completion of this task.")
    warranty_installation_done_at = fields.Datetime(
        string='Installation Completed On', readonly=True, copy=False,
        help="Original completion time of the installation task; kept when the task is "
             "reopened or completed again (Q7).")

    @api.model_create_multi
    def create(self, vals_list):
        if not self._warranty_installation_marker_set() and any(
                TASK_SYSTEM_FIELDS & set(vals) or vals.get('warranty_installation_card_ids')
                for vals in vals_list):
            raise UserError(_("Warranty installation tasks are created from the Sales Order "
                              "or with Create Installation Task on the warranty card."))
        return super().create(vals_list)

    def write(self, vals):
        if not self._warranty_installation_marker_set():
            if TASK_SYSTEM_FIELDS & set(vals):
                raise UserError(_("The installation purpose and completion time are set by "
                                  "the system."))
            if 'warranty_installation_card_ids' in vals:
                self._warranty_check_link_change()
        installation = self.filtered(lambda task: task.warranty_task_purpose == 'installation')
        before = {task.id: task.state for task in installation}
        linked = installation.warranty_installation_card_ids
        result = super().write(vals)
        if installation:
            installation._warranty_installation_after_write(before, linked, vals)
        return result

    def _warranty_installation_marker_set(self):
        return self.env.context.get('warranty_installation_marker') is _INSTALLATION_MARKER

    def _warranty_system_write(self, vals):
        return self.with_context(warranty_installation_marker=_INSTALLATION_MARKER).write(vals)

    def _warranty_check_link_change(self):
        """Explicit (manual) card links: Warranty: Date Correction group, open tasks only."""
        if not self.env.su and not self.env.user.has_group(DATE_CORRECTION_GROUP):
            raise UserError(_("Only users of the group Warranty: Date Correction can change the "
                              "warranty cards of an installation task."))
        if self.filtered(lambda task: task.state in ('1_done', '1_canceled')):
            raise UserError(_("The warranty cards of a completed or cancelled installation task "
                              "cannot be changed."))

    @api.constrains('warranty_task_purpose', 'warranty_service_job_id',
                    'warranty_installation_card_ids')
    def _check_warranty_installation(self):
        for task in self:
            cards = task.warranty_installation_card_ids
            if task.warranty_task_purpose == 'installation' and task.warranty_service_job_id:
                raise ValidationError(_("Service job visit %s cannot be an installation task.",
                                        task.name))
            if not cards:
                continue
            if task.warranty_task_purpose != 'installation':
                raise ValidationError(_("Only installation tasks can be linked to warranty "
                                        "cards (%s).", task.name))
            if cards.filtered(lambda card: card.start_criterion != 'installation'):
                raise ValidationError(_("Installation task %s can only be linked to "
                                        "Installation-basis warranty cards.", task.name))
            orders = cards.sale_order_id
            if len(orders) > 1 or (task.sale_line_id and orders != task.sale_line_id.order_id):
                raise ValidationError(_("Installation task %s can only cover warranty cards of "
                                        "its own Sales Order.", task.name))
            if cards.company_id != task.company_id:
                raise ValidationError(_("Installation task %s and its warranty cards must "
                                        "belong to the same company.", task.name))

    def _warranty_link_relevant_cards(self):
        """Q8: link the open Installation-basis cards of the task's Sales Order that contain a
        product installed by the task's service (Installs Products); never unrelated cards."""
        for task in self.filtered(lambda t: t.warranty_task_purpose == 'installation'
                                  and t.state != '1_canceled'):
            line = task.sudo().sale_line_id
            products = line.product_id.product_tmpl_id.warranty_installation_product_ids
            if not line or not products:
                continue
            cards = line.order_id.warranty_card_ids.filtered(
                lambda card: card.start_criterion == 'installation'
                and card.state in OPEN_CARD_STATES
                and card.unit_warranty_ids.product_id.product_tmpl_id & products)
            new = cards - task.sudo().warranty_installation_card_ids
            if new:
                # sudo: system link rule; the user creating the task may lack FSM rights.
                task.sudo()._warranty_system_write(
                    {'warranty_installation_card_ids': [Command.link(card.id) for card in new]})
                for card in new:
                    card._warranty_log_date_event('source_change', _(
                        "Installation task %s linked (installs %s).", task.name,
                        ', '.join(products.mapped('name'))), task_reference=task.name)
                new._warranty_sync_installation()
                new._warranty_auto_confirm()

    def _warranty_installation_after_write(self, before, linked, vals):
        """Completion (D7, original time kept – Q7), reopening, cancellation and link changes."""
        now = fields.Datetime.now()
        for task in self:
            was, state = before.get(task.id), task.state
            cards = task.warranty_installation_card_ids
            if state == '1_done' and was != '1_done':
                if task.company_id.warranty_signoff_required and not task.worksheet_signature:
                    raise UserError(_(
                        "Installation task %s needs the customer sign-off (Sign Report) before "
                        "it is marked as done (Customer Sign-off Required).", task.name))
                if not task.warranty_installation_done_at:
                    task._warranty_system_write({'warranty_installation_done_at': now})
                    for card in cards.filtered(lambda c: c.start_date_source == 'exception'):
                        card._warranty_log_date_event('source_change', _(
                            "Installation task %(task)s completed on %(when)s; the authorized "
                            "exception date is kept.", task=task.name,
                            when=card._warranty_format_datetime(now)), task_reference=task.name)
                else:
                    for card in cards:
                        card._warranty_log_date_event('source_change', _(
                            "Installation task %(task)s completed again on %(when)s; the "
                            "original completion %(original)s is kept.", task=task.name,
                            when=card._warranty_format_datetime(now),
                            original=card._warranty_format_datetime(
                                task.warranty_installation_done_at)), task_reference=task.name)
            elif was == '1_done' and state != '1_done' or \
                    state == '1_canceled' and was != '1_canceled':
                event = 'task_cancelled' if state == '1_canceled' else 'task_reopened'
                for card in cards:
                    card._warranty_log_date_event(event, _(
                        "Installation task %(task)s %(action)s; %(effect)s", task=task.name,
                        action=_("cancelled") if state == '1_canceled' else _("reopened"),
                        effect=_("warranty dates unchanged.")
                        if card.state not in OPEN_CARD_STATES
                        else _("the warranty card waits for the installation.")),
                        task_reference=task.name)
        cards = self.warranty_installation_card_ids
        if 'warranty_installation_card_ids' in vals \
                and not self._warranty_installation_marker_set():
            changed = (cards - linked) | (linked - cards)
            if changed.filtered(lambda card: card.state not in OPEN_CARD_STATES):
                raise UserError(_("The installation tasks of a confirmed warranty card cannot be "
                                  "changed; use Correct Warranty Dates."))
            for card in changed:
                card._warranty_log_date_event('source_change', _(
                    "Installation tasks changed: %s.",
                    ', '.join(card.installation_task_ids.mapped('name')) or _("none")),
                    task_reference=', '.join(self.mapped('name')))
        cards |= linked
        cards._warranty_sync_installation()
        cards._warranty_auto_confirm()


class WarrantyCard(models.Model):
    _inherit = 'warranty.card'

    installation_task_ids = fields.Many2many(
        'project.task', 'warranty_installation_task_card_rel', 'card_id', 'task_id',
        string='Installation Tasks', readonly=True, copy=False)
    installation_task_count = fields.Integer(compute='_compute_installation_task_count')
    source_task_id = fields.Many2one(
        'project.task', string='Source Installation Task', readonly=True, copy=False)

    @api.depends('installation_task_ids')
    def _compute_installation_task_count(self):
        for card in self:
            card.installation_task_count = len(card.installation_task_ids)

    def write(self, vals):
        if 'installation_task_ids' in vals and not self._warranty_date_write_allowed():
            raise UserError(_("Installation tasks are linked from the task (Warranty: Date "
                              "Correction) or by the system."))
        return super().write(vals)

    def _warranty_system_date_fields(self):
        return super()._warranty_system_date_fields() | {'source_task_id'}

    def _warranty_installation_missing(self):
        missing = super()._warranty_installation_missing()
        if not missing or self.start_date_source == 'exception':
            return missing
        tasks = self.installation_task_ids.filtered(lambda task: task.state != '1_canceled')
        if not tasks:
            return [_("Installation / commissioning completed: no installation Field Service "
                      "task is linked (Create Installation Task, or an authorized exception)")]
        waiting = tasks.filtered(lambda task: task.state != '1_done')
        return [_("Installation / commissioning completed: waiting for installation task(s) %s",
                  ', '.join(waiting.mapped('name')) or ', '.join(tasks.mapped('name')))]

    def _warranty_start_source(self):
        result = super()._warranty_start_source()
        if result['source'] == 'installation':
            result['task'] = self.source_task_id
        return result

    def _warranty_frozen_source(self):
        result = super()._warranty_frozen_source()
        result['task'] = self.source_task_id
        return result

    def _warranty_source_write_values(self, source):
        values = super()._warranty_source_write_values(source)
        if source.get('task'):
            values['source_task_id'] = source['task'].id
        return values

    def _warranty_source_description(self, source):
        if source.get('source') == 'installation' and source.get('task') \
                and source.get('datetime'):
            return _("Installation task %(task)s completed on %(when)s",
                     task=source['task'].name,
                     when=self._warranty_format_datetime(source['datetime']))
        return super()._warranty_source_description(source)

    def _split_units_to_new_card(self, units, deliveries):
        new_card = super()._split_units_to_new_card(units, deliveries)
        self.sudo().installation_task_ids.with_env(self.env)._warranty_link_relevant_cards()
        return new_card

    def _warranty_sync_installation(self):
        """Installation Date and source of open Installation-basis cards from their linked,
        non-cancelled installation tasks: all done -> local date of the latest original
        completion time; otherwise empty (Pending Installation). Exceptions are kept."""
        # sudo: system step; the technician completing the task may lack card rights.
        for card in self.sudo():
            if card.start_criterion != 'installation' or card.state not in OPEN_CARD_STATES \
                    or card.start_date_source == 'exception':
                continue
            tasks = card.installation_task_ids.filtered(lambda task: task.state != '1_canceled')
            done = bool(tasks) and all(task.state == '1_done' and task.warranty_installation_done_at
                                       for task in tasks)
            if done:
                last = max(tasks, key=lambda task: (task.warranty_installation_done_at, task.id))
                vals = {
                    'installation_date': card.company_id._warranty_local_date(
                        last.warranty_installation_done_at),
                    'start_date_source': 'installation',
                    'source_datetime': last.warranty_installation_done_at,
                    'source_verification': 'event',
                    'source_task_id': last.id,
                }
            else:
                vals = dict.fromkeys(('installation_date', 'start_date_source', 'source_datetime',
                                      'source_verification', 'source_task_id'), False)
            current = {name: card[name].id if name == 'source_task_id' else card[name]
                       for name in vals}
            if current != vals:
                card._warranty_system_write(vals)

    def action_create_installation_task(self):
        """Create Installation Task (D4, Q9): one task in the Warranty Field Service Project,
        linked to this card only."""
        self.ensure_one()
        if self.start_criterion != 'installation' or self.state not in OPEN_CARD_STATES:
            raise UserError(_("Installation tasks are created for Installation-basis warranty "
                              "cards that are not confirmed yet."))
        if not self.env.user.has_group('industry_fsm.group_fsm_user'):
            raise UserError(_("You need Field Service access to create an installation task."))
        project = self.company_id._warranty_fsm_project()
        task = self.env['project.task'].with_context(
            warranty_installation_marker=_INSTALLATION_MARKER).create({
                'name': _("Installation - %s", self.name),
                'project_id': project.id,
                'company_id': self.company_id.id,
                'partner_id': (self.sale_order_id.partner_shipping_id or self.partner_id).id,
                'warranty_task_purpose': 'installation',
                'warranty_installation_card_ids': [Command.link(self.id)],
            })
        self._warranty_log_date_event('source_change', _(
            "Installation task %s created.", task.name), task_reference=task.name)
        self._warranty_sync_installation()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'res_id': task.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }

    def action_view_installation_tasks(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Installation Tasks"),
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.installation_task_ids.ids)],
            'context': {'create': False},
        }
