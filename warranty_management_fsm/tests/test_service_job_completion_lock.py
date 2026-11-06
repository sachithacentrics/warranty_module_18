from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ServiceJobCommon

LOCK = 'cannot be marked Done or Cancelled directly'


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobCompletionLock(ServiceJobCommon):
    """Approved completion lock (V6 / C1-C2): warranty visits are not closed directly."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('job_l_tech', 'industry_fsm.group_fsm_user')
        cls.tech.email = 'tech.lock@example.com'
        cls.env['hr.employee'].create({'name': 'Lock Tech', 'user_id': cls.tech.id,
                                       'company_id': cls.company.id})

    def setUp(self):
        super().setUp()
        case = self._approved()
        self.job = self._prepare(case)
        self.job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        self.job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        self.job.with_user(self.helpdesk_user).action_confirm_job()
        self.task = self.job.visit_ids
        self.task.with_user(self.tech).action_timer_start()
        self.assertEqual(self.job.state, 'in_progress')

    def _assert_open(self):
        self.task.invalidate_recordset()
        self.assertEqual((self.task.state in ('1_done', '1_canceled'), self.task.fsm_done),
                         (False, False))
        self.assertEqual(self.job.state, 'in_progress')
        self.assertEqual(self.job.worksheet_ids.state, 'in_progress', 'never Completed in 4.5')

    def _attempts(self, user):
        task = self.task.with_user(user)
        for vals in ({'state': '1_done'}, {'state': '1_canceled'}, {'fsm_done': True}):
            with self.assertRaisesRegex(UserError, LOCK):
                task.write(vals)
        with self.assertRaisesRegex(UserError, LOCK):
            task.action_fsm_validate()
        with self.assertRaisesRegex(UserError, LOCK):
            task.action_fsm_validate(stop_running_timers=True)
        self._assert_open()

    def test_61_field_service_user(self):
        """Form / kanban / status widget (state write), Task Done, Mark as done: refused."""
        self._attempts(self.tech)

    def test_62_helpdesk_user(self):
        """Helpdesk users: refused by the lock (checked before the task access rights)."""
        self._attempts(self.helpdesk_user)

    def test_63_api_import_context_and_sudo(self):
        """Import (load), a client context flag and a plain sudo() write do not pass."""
        result = self.env['project.task'].with_user(self.tech).load(
            ['.id', 'state'], [[str(self.task.id), '1_done']])
        self.assertFalse(result['ids'])
        self.assertIn(LOCK, ' '.join(m['message'] for m in result['messages']))
        for context in ({'warranty_close_marker': True}, {'warranty_close_marker': 'x'}):
            with self.assertRaisesRegex(UserError, LOCK):
                self.task.with_user(self.tech).with_context(**context).write({'state': '1_done'})
        with self.assertRaisesRegex(UserError, LOCK):
            self.task.sudo().write({'state': '1_canceled'})
        self._assert_open()

    def test_64_authorized_close_and_closed_tasks_unchanged(self):
        """The reserved Part 4.7 / 4.8 path closes; a closed visit stays editable
        (description) but cannot be reopened; nothing else is completed."""
        self.task.with_user(self.tech).action_timer_stop()
        # as the standard Mark as done: Task Done + Done (Part 4.7 / 4.8 flows)
        self.task._warranty_close_visits({'fsm_done': True, 'state': '1_done'})
        self.assertEqual((self.task.state, self.task.fsm_done), ('1_done', True))
        self.task.with_user(self.tech).write({'description': '<p>Checked</p>', 'state': '1_done'})
        self.assertEqual(self.job.worksheet_ids.state, 'in_progress')
        # Approved L3 / L10: a closed warranty visit is kept as history (no reopening).
        with self.assertRaisesRegex(UserError, 'kept as visit history'):
            self.task.with_user(self.tech).state = '01_in_progress'

    def test_65_other_tasks_standard(self):
        """Non-warranty Field Service tasks close as standard."""
        plain = self.env['project.task'].create({
            'name': 'Plain visit', 'project_id': self.company._warranty_fsm_project().id,
            'user_ids': [(4, self.tech.id)]})
        plain.with_user(self.tech).action_fsm_validate()
        self.assertEqual((plain.state, plain.fsm_done), ('1_done', True))
        other = plain.copy({'name': 'Plain visit 2'})
        other.with_user(self.tech).state = '1_canceled'
        self.assertEqual(other.state, '1_canceled')
