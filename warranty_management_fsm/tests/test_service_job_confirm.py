from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobConfirm(ServiceJobCommon):
    """Phase 4.3 - Confirm Service Job and Field Service task (approved Q41, G1, G5, D5, D7,
    D8, D9, D13)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech_main = cls._user('job_c_tech_main', 'industry_fsm.group_fsm_user')
        cls.tech_support = cls._user('job_c_tech_support', 'industry_fsm.group_fsm_user')

    def _planned(self, case):
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech_main.id,
            'support_technician_ids': [(6, 0, self.tech_support.ids)]})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        return job

    def _confirm(self, job, user=None):
        return job.with_user(user or self.helpdesk_user).action_confirm_job()

    def test_31_confirm_warranty_only_job(self):
        """Warranty Only job: task in the company Field Service project, linked to case / job /
        ticket, planned date and technicians; job Confirmed, case Job Created."""
        case = self._approved()
        job = self._planned(case)
        self.assertTrue(self._confirm(job))
        task = job.visit_ids
        self.assertEqual(len(task), 1)
        self.assertEqual((task.project_id, task.project_id.is_fsm),
                         (self.company._warranty_fsm_project(), True))
        self.assertEqual((task.warranty_service_job_id, task.warranty_case_id,
                          task.helpdesk_ticket_id, task.warranty_visit_no),
                         (job, case, case.helpdesk_ticket_id, 1))
        self.assertEqual(task.planned_date_begin, job.planned_date)
        self.assertEqual(task.user_ids, self.tech_main | self.tech_support)
        self.assertEqual(task.partner_id, case.partner_id, 'no site: the customer (D9)')
        self.assertFalse(task.warranty_entitlement_ids)
        self.assertEqual((job.state, case.state, job.visit_count), ('confirmed', 'job_created', 1))
        self.assertIn('Field Service task', job.message_ids[:1].body)
        self.assertIn('confirmed', case.message_ids[:1].body)

    def test_32_free_services_job_created(self):
        """G1: free services of the job -> Job Created (previous status kept), Merge Status
        kept, balance unchanged, not deletable, not moved by the expiry monitoring."""
        s1 = self.card.service_entitlement_ids.sorted('service_no')[:1]
        case = self._approved(s1, case_type='free_service')
        job = self._planned(case)
        previous = s1.state
        balance = self.card.free_services_balance
        self._confirm(job)
        self.assertEqual((s1.state, s1.job_previous_state, s1.merge_status),
                         ('job_created', previous, 'selected'))
        self.assertEqual(job.visit_ids.warranty_entitlement_ids, s1)
        self.assertEqual(self.card.free_services_balance, balance)
        with self.assertRaises(UserError):
            s1.unlink()
        s1._apply_expiry_rules(s1.grace_period_end_date + timedelta(days=400))
        self.assertEqual(s1.state, 'job_created')

    def test_33_site_address(self):
        """D9: the task customer is the case site when set."""
        ticket = self._ticket(warranty_product_id=self.product.id,
                              warranty_site_id=self.customer.id)
        case = self._approved(ticket=ticket)
        case.sudo().site_id = self.site_a
        job = self._planned(case)
        self._confirm(job)
        self.assertEqual(job.visit_ids.partner_id, self.site_a)

    def test_34_blocks(self):
        """Not Planned / closed ticket (G5) / user without Helpdesk rights: refused."""
        case = self._approved()
        job = self._prepare(case)
        with self.assertRaisesRegex(UserError, 'must be Planned'):
            self._confirm(job)
        job.action_cancel()
        job = self._planned(case)
        with self.assertRaises(AccessError):
            self._confirm(job, user=self.internal_user)
        closed = self.env['helpdesk.stage'].create({'name': 'Closed Test', 'fold': True,
                                                    'team_ids': [(4, self.team.id)]})
        case.helpdesk_ticket_id.stage_id = closed
        with self.assertRaisesRegex(UserError, 'is closed'):
            self._confirm(job)
        self.assertEqual((job.state, job.visit_ids), ('planned', self.env['project.task']))

    def test_35_revalidation_failure(self):
        """Q41 / D7: revalidation fails -> not confirmed, no task, reasons logged on job and
        case, case status / result unchanged."""
        case = self._approved()
        job = self._planned(case)
        self.policy.write({'payment_check_required': True, 'overdue_claim_handling': 'hold'})
        action = self._confirm(job)
        self.assertEqual(action['params']['type'], 'warning')
        self.assertEqual((job.state, job.visit_ids), ('planned', self.env['project.task']))
        self.assertEqual((case.state, case.eligibility_result), ('approved', 'eligible'))
        self.assertIn('blocked by the eligibility revalidation', job.message_ids[:1].body)
        self.assertIn('blocked by the eligibility revalidation', case.message_ids[:1].body)

    def test_36_project_setting(self):
        """D5: configured Warranty Field Service Project, else the standard one; another
        company's / non Field Service project refused; none available -> error."""
        project = self.env['project.project'].create({
            'name': 'Warranty Visits', 'is_fsm': True, 'company_id': self.company.id})
        self.company.warranty_fsm_project_id = project
        job = self._planned(self._approved())
        self._confirm(job)
        self.assertEqual(job.visit_ids.project_id, project)
        with self.assertRaises(ValidationError):
            self.company.warranty_fsm_project_id = self.env['project.project'].create(
                {'name': 'Internal', 'company_id': self.company.id})
        self.company.warranty_fsm_project_id = False
        self.env['project.project'].search(
            [('is_fsm', '=', True), ('company_id', '=', self.company.id)]).active = False
        with self.assertRaisesRegex(UserError, 'No Field Service project'):
            self.company._warranty_fsm_project()

    def test_37_no_standalone_warranty_task(self):
        """D8 / SRS #27: Plan Intervention refused for tickets with warranty cases; no Field
        Service task of such a ticket without Service Job; other tickets unchanged."""
        case = self._approved()
        ticket = case.helpdesk_ticket_id
        with self.assertRaises(UserError):
            ticket.action_generate_fsm_task()
        project = self.company._warranty_fsm_project()
        with self.assertRaises(ValidationError):
            self.env['project.task'].create({'name': 'Bypass', 'project_id': project.id,
                                             'helpdesk_ticket_id': ticket.id})
        plain = self.env['helpdesk.ticket'].create({'name': 'No warranty', 'team_id': self.team.id,
                                                    'partner_id': self.customer.id})
        self.assertEqual(plain.action_generate_fsm_task()['res_model'],
                         'helpdesk.create.fsm.task')
        task = self.env['project.task'].create({'name': 'Plain visit', 'project_id': project.id,
                                                'helpdesk_ticket_id': plain.id})
        self.assertTrue(task)
        job = self._planned(case)
        self._confirm(job)
        with self.assertRaises(ValidationError):
            job.visit_ids.helpdesk_ticket_id = plain
