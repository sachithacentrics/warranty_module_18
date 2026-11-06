from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import ServiceJobCommon


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestServiceJobMerge(ServiceJobCommon):
    """Phase 4.1 - Read linked services, merge compatibility, Create / Prepare Service Job,
    cancellation before confirmation (Q42), interaction with Part 2 expiry protection."""

    def setUp(self):
        super().setUp()
        self.services = self.card.service_entitlement_ids.sorted('service_no')

    def test_11_no_free_service(self):
        """G2: Approved warranty claim without free service -> job without services."""
        case = self._approved()
        job = self._prepare(case)
        self.assertEqual((job.state, job.merge_type, job.warranty_case_id), ('draft', 'none',
                                                                             case))
        self.assertEqual((job.helpdesk_ticket_id, job.partner_id, job.warranty_card_id),
                         (case.helpdesk_ticket_id, case.partner_id, case.warranty_card_id))
        self.assertEqual(case.state, 'approved', 'case status unchanged until confirmation')
        self.assertIn('warranty claim only', job.message_ids[:1].body)

    def test_12_single_service_selected(self):
        """Use Single Service Entitlement -> Merge Status Selected, status unchanged."""
        s1 = self.services[:1]
        case = self._approved(s1, case_type='free_service')
        state = s1.state
        job = self._prepare(case)
        self.assertEqual((job.merge_type, job.entitlement_ids), ('single', s1))
        self.assertEqual((s1.merge_status, s1.state, s1.open_service_job_id),
                         ('selected', state, job))
        self.assertEqual(case.open_service_job_id, job)
        self.assertEqual(case.service_job_count, 1)

    def test_13_merged_services(self):
        """Several compatible services -> Merge Selected Services -> Merged."""
        s1, s2 = self.services[:2]
        case = self._approved(s1 | s2, case_type='free_service')
        job = self._prepare(case)
        self.assertEqual(job.merge_type, 'merged')
        self.assertEqual(set((s1 | s2).mapped('merge_status')), {'merged'})
        self.assertIn('Free services merged', case.message_ids[:1].body)

    def test_14_merge_validation_error(self):
        """Compatible? No -> Show Merge Validation Error: nothing is created or changed."""
        s1, s2 = self.services[:2]
        case = self._approved(s1 | s2, case_type='free_service')
        s2.sudo().state = 'expired'
        with self.assertRaisesRegex(UserError, 'cannot be merged') as error:
            self._prepare(case)
        self.assertIn(s2.name, str(error.exception))
        self.assertIn('conflicting status', str(error.exception))
        self.assertFalse(case.service_job_ids)
        self.assertEqual(set((s1 | s2).mapped('merge_status')), {'not_merged'})

    def test_15_merge_problems_detail(self):
        """Compatibility checks (cross-card merge: each card checked): other site, already
        on another open job."""
        s1, s2 = self.services[:2]
        case = self._approved(s1 | s2, case_type='free_service')
        other_card = self._card(site=self.site_b)
        other = other_card.service_entitlement_ids[:1]
        with self._today(date(2026, 11, 1)):
            problems = case._warranty_job_merge_problems(s1 | other)
        text = '\n'.join(problems)
        self.assertIn('%s (%s): ' % (other.name, other_card.name), text)
        self.assertIn('is not the case site', text)
        foreign_case = self._create_case(self._ticket())
        self.env['warranty.service.job'].create({'warranty_case_id': foreign_case.id,
                                                 'entitlement_ids': [(6, 0, s2.ids)]})
        with self._today(date(2026, 11, 1)):
            problems = case._warranty_job_merge_problems(s1 | s2)
        self.assertIn('already merged into the open service job', '\n'.join(problems))

    def test_16_rules_and_one_open_job(self):
        """Only Approved + Eligible cases, one open job per case (R2), Helpdesk users only."""
        not_approved = self._create_case(self.ticket)
        with self.assertRaises(UserError):
            not_approved.with_user(self.helpdesk_user).action_prepare_service_job()
        case = self._approved()
        with self.assertRaises(AccessError):
            case.with_user(self.internal_user).action_prepare_service_job()
        self._prepare(case)
        with self.assertRaisesRegex(UserError, 'already has the open service job'):
            self._prepare(case)

    def test_17_cancel_before_confirmation(self):
        """Q42: cancel -> case stays Approved, services Not Merged (not consumed), a new job
        can be prepared; confirmed jobs cannot be cancelled here."""
        s1, s2 = self.services[:2]
        case = self._approved(s1 | s2, case_type='free_service')
        job = self._prepare(case)
        balance = self.card.free_services_balance
        job.with_user(self.helpdesk_user).action_cancel()
        self.assertEqual((job.state, case.state), ('cancelled', 'approved'))
        self.assertEqual(set((s1 | s2).mapped('merge_status')), {'not_merged'})
        self.assertEqual(self.card.free_services_balance, balance)
        self.assertFalse(case.open_service_job_id)
        self.assertIn('cancelled before confirmation', case.message_ids[:1].body)
        new = self._prepare(case)
        self.assertEqual(new.entitlement_ids, s1 | s2)
        new.state = 'confirmed'
        with self.assertRaises(UserError):
            new.action_cancel()

    def test_18_expiry_protection_while_on_job(self):
        """Part 2 expiry protection: a Selected / Merged service is not moved to Missed /
        Expired by the daily monitoring; after cancellation the normal rules apply again."""
        s1 = self.services[:1]
        case = self._approved(s1, case_type='free_service')
        job = self._prepare(case)
        self.assertTrue(s1._is_expiry_blocked())
        after_grace = s1.grace_period_end_date.replace(year=s1.grace_period_end_date.year + 1)
        s1._apply_expiry_rules(after_grace)
        self.assertNotIn(s1.state, ('missed', 'expired'))
        job.action_cancel()
        self.assertFalse(s1._is_expiry_blocked())
        s1._apply_expiry_rules(after_grace)
        self.assertIn(s1.state, ('missed', 'expired'))

    def test_19_multi_company(self):
        case = self._approved()
        job = self._prepare(case)
        self.assertFalse(self.env['warranty.service.job'].with_user(self.foreign_user).search(
            [('id', '=', job.id)]))
        with self.assertRaises(AccessError):
            case.with_user(self.foreign_user).action_prepare_service_job()
