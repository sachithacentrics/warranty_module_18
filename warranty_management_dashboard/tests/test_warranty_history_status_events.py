from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.addons.warranty_management_fsm.tests.common import ServiceJobCommon

from .report_common import _filter_domain


@tagged('post_install', '-at_install', 'warranty_dashboard')
class TestWarrantyHistoryStatusEvents(ServiceJobCommon):
    """Warranty History Report: case / job status changes from their tracking, cost lines and
    journal entries for the users allowed to see them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('report_hist_tech', 'industry_fsm.group_fsm_user')
        cls.env['hr.employee'].create({'name': cls.tech.name, 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})
        cls.account_user = cls._user('report_hist_account', 'account.group_account_invoice')

    def _commit_tracking(self):
        """What a request commit does: write the chatter tracking (pre-commit) and the pending
        fields, which the SQL view reads; the next request starts with an empty cache (the
        history ids are row numbers, which change when new events are added)."""
        self.env.flush_all()
        self.env.cr.precommit.run()
        self.env.flush_all()
        self.env.invalidate_all()

    def test_03_status_events_and_access(self):
        """Job / case status changes with their user, newest first; cost line rows for
        coordinators, journal entry rows for accounting users only; no amounts."""
        # each step in its own request, as in the UI (no tracking within the creating one)
        case = self._approved()
        self._commit_tracking()
        job = self._prepare(case)
        self._commit_tracking()
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        History = self.env['warranty.history']
        card_domain = [('card_id', '=', case.warranty_card_id.id)]
        self._commit_tracking()

        # job: created + one row per tracked status change, with its user
        job_rows = History.search(card_domain + [('entity', '=', 'job')])
        self.assertEqual(job_rows.filtered(lambda r: r.event_type == 'Job created').reference,
                         job.name)
        tracked = self.env['mail.tracking.value'].search([
            ('mail_message_id.model', '=', 'warranty.service.job'),
            ('mail_message_id.res_id', '=', job.id), ('field_id.name', '=', 'state')])
        status_rows = job_rows.filtered(lambda r: r.event_type.startswith('Job status: '))
        self.assertEqual(len(status_rows), len(tracked))
        self.assertTrue(status_rows)
        self.assertTrue(status_rows[0].event_type.endswith(
            dict(job._fields['state']._description_selection(self.env))[job.state]))
        self.assertEqual(status_rows[0].user_id, self.helpdesk_user)
        self.assertEqual(status_rows[0].action_open_source()['res_id'], job.id)
        dates = job_rows.mapped('event_date')
        self.assertEqual(dates, sorted(dates, reverse=True))
        # case: created + status change when its job was prepared
        case_rows = History.search(card_domain + [('reference', '=', case.name)])
        self.assertIn('Case created', case_rows.mapped('event_type'))
        labels = dict(case._fields['state']._description_selection(self.env))
        changed = case_rows.filtered(
            lambda r: r.event_type == 'Case status: %s -> %s' % (labels['approved'],
                                                                  labels['job_created']))
        self.assertEqual(changed.user_id, self.helpdesk_user)
        self.assertEqual(changed.action_open_source()['res_id'], case.id)
        self.assertTrue(History.search(card_domain + _filter_domain(History, 'filter_status')))

        # cost line and journal entry rows: only for the users who may see them
        line = self.env['warranty.cost.line'].create({
            'case_id': case.id, 'cost_type': 'travel', 'reason': 'Site travel',
            'estimated_amount': 25.0})
        move = self.env['account.move'].create({
            'move_type': 'out_refund', 'partner_id': case.partner_id.id,
            'warranty_inspection_case_id': case.id})
        self._commit_tracking()
        rows = History.search(card_domain)
        self.assertIn(('cost', line.name), [(r.entity, r.reference) for r in rows])
        self.assertIn(('accounting', 'Inspection fee credit note created'),
                      [(r.entity, r.event_type) for r in rows])
        texts = filter(None, rows.mapped('summary') + rows.mapped('event_type'))
        self.assertNotIn('25.0', ' '.join(texts), 'no amounts in the history')
        entities = {
            user: set(History.with_user(user).search(card_domain).mapped('entity'))
            for user in (self.internal_user, self.helpdesk_user, self.account_user)}
        self.assertFalse(entities[self.internal_user] & {'cost', 'accounting'})
        self.assertIn('cost', entities[self.helpdesk_user])
        self.assertNotIn('accounting', entities[self.helpdesk_user])
        self.assertTrue({'cost', 'accounting'} <= entities[self.account_user])
        self.assertFalse(History.with_user(self.foreign_user).search(card_domain))
        # the report reads only
        self.assertEqual((job.state, case.state, move.state, line.state),
                         ('confirmed', 'job_created', 'draft', 'draft'))
