from datetime import date

from odoo.addons.warranty_management_helpdesk.tests.test_warranty_case_approval import \
    TestWarrantyCaseApproval


def manual_case(ticket, services, **vals):
    """Warranty Cases > New: Free Service case on the ticket with the services and the
    policies' Automatic Case Requested Items as Requested Items, then Check Eligibility."""
    case = services.env['warranty.case'].create(dict({
        'helpdesk_ticket_id': ticket.id, 'case_type': 'free_service',
        'service_entitlement_ids': [(6, 0, services.ids)],
        'requested_item_ids': [(6, 0, services.warranty_card_id.policy_id.auto_case_item_ids.ids)],
    }, **vals))
    case.action_check_eligibility()
    return case


def link_case(job, **kwargs):
    """Service-origin job: Create or Link Helpdesk Ticket, then its warranty case is created
    manually on the ticket (linked to the job)."""
    ticket = job._warranty_link_ticket(**kwargs)
    return manual_case(ticket, job.entitlement_ids)


class ServiceJobCommon(TestWarrantyCaseApproval):
    """Approved warranty cases (Part 3) as the starting point of Part 4."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fsm_user = cls._user('job_fsm_user', 'industry_fsm.group_fsm_user')

    def _approved(self, services=None, case_type=None, ticket=None):
        vals = {}
        if case_type:
            vals['case_type'] = case_type
        with self._today(date(2026, 11, 1)):
            if services:
                vals['service_entitlement_ids'] = [(6, 0, services.ids)]
            case = self._create_case(ticket or self.ticket, user=self.creator, **vals)
            self.assertEqual(self._result(case), 'eligible')
        case.with_user(self.approver_a).action_approve_case()
        self.assertEqual(case.state, 'approved')
        return case

    def _prepare(self, case, user=None):
        with self._today(date(2026, 11, 1)):
            action = case.with_user(user or self.helpdesk_user).action_prepare_service_job()
        return self.env['warranty.service.job'].browse(action['res_id'])
