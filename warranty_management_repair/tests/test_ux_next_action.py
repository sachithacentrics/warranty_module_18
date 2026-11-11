import re

from lxml import etree

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .test_warranty_replacement import ReplacementCommon

KEYWORDS = {'and', 'or', 'not', 'in', 'True', 'False', 'None', 'parent'}


@tagged('post_install', '-at_install', 'warranty_repair', 'warranty_ux')
class TestUxNextAction(ReplacementCommon):
    """UX cleanup: one primary next action per step on the case, job and visit headers, the case
    as hub for the existing Return / Repair Order / Backup / Field Service records, AMC visits
    without the workshop actions. Views only call the existing actions: their checks stay."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.team.write({'use_product_returns': True, 'use_product_repairs': True})
        cls.helpdesk_only = cls._user('ux_helpdesk', 'helpdesk.group_helpdesk_user')

    def setUp(self):
        super().setUp()
        self.card = self._card(self.single)
        self.case = self._eligible_case(self.card.unit_warranty_ids.serial_ids)
        self._approved_state(self.case)

    # ------------------------------------------------------------------ helpers
    def _header(self, model, user=None):
        env = self.env(user=user) if user else self.env
        return etree.fromstring(env[model].get_view(view_type='form')['arch']).xpath('//header')[0]

    def _visible(self, model, values, user=None):
        """(name, string, primary) of the header buttons the web client shows for these values;
        every other field used by a modifier is False."""
        header = self._header(model, user)
        shown = []
        for button in header.xpath('.//button'):
            expr = button.get('invisible') or 'False'
            names = set(re.findall(r'\b[a-zA-Z_]\w*\b', expr)) - KEYWORDS
            context = dict.fromkeys(names, False)
            context.update(values)
            if not safe_eval(expr, context):
                shown.append((button.get('name'), button.get('string'),
                              'btn-primary' in (button.get('class') or '')))
        return shown

    def _primary(self, model, values, user=None):
        return [name for name, _string, primary in self._visible(model, values, user) if primary]

    # ------------------------------------------------------------------ case header
    def test_01_case_one_primary_per_step(self):
        case = 'warranty.case'
        base = {'id': 1, 'case_type': 'warranty_complaint', 'helpdesk_ticket_id': 1,
                'warranty_ticket_returns': True, 'warranty_ticket_repairs': True}
        steps = [
            ({'state': 'new'}, ['action_check_eligibility']),
            # Approved Option C: Approve and Reject Case are both primary.
            ({'state': 'eligibility_checked', 'eligibility_result': 'eligible',
              'can_approve_case': True, 'can_reject_case': True},
             ['action_approve_case', 'action_open_reject_wizard']),
            ({'state': 'approved', 'eligibility_result': 'eligible',
              'warranty_service_mode': 'onsite'}, ['action_prepare_service_job']),
            ({'state': 'approved', 'eligibility_result': 'eligible',
              'warranty_service_mode': 'workshop'}, ['action_warranty_case_workshop_intake']),
            ({'state': 'approved', 'eligibility_result': 'eligible',
              'warranty_service_mode': 'workshop', 'warranty_return_count': 1},
             ['action_warranty_case_open_repair']),
            # Inspection Required: the step Prepare Service Job would run (Figure 9 UAT).
            ({'state': 'approved', 'eligibility_result': 'eligible',
              'warranty_service_mode': 'onsite', 'warranty_inspection_required': True,
              'warranty_inspection_step': 'quotation'}, ['action_prepare_service_job']),
            ({'state': 'approved', 'eligibility_result': 'eligible',
              'warranty_service_mode': 'onsite', 'warranty_inspection_required': True,
              'warranty_inspection_step': 'waiting'}, ['action_open_inspection_quotation']),
            ({'state': 'approved', 'eligibility_result': 'eligible',
              'warranty_service_mode': 'onsite', 'warranty_inspection_required': True,
              'warranty_inspection_step': 'job'}, ['action_prepare_service_job']),
            ({'state': 'job_created', 'eligibility_result': 'eligible', 'open_service_job_id': 1},
             ['action_open_service_job']),
            ({'state': 'completed', 'eligibility_result': 'eligible'}, ['action_warranty_close_case']),
        ]
        for values, primary in steps:
            with self.subTest(**values):
                self.assertEqual(self._primary(case, dict(base, **values)), primary)

    def test_01b_case_inspection_labels(self):
        """Inspection Required: Create Inspection Quotation, then Open Inspection Quotation; no
        button that would create a second quotation; Workshop mode keeps one primary."""
        case = 'warranty.case'
        base = {'id': 1, 'case_type': 'warranty_complaint', 'helpdesk_ticket_id': 1,
                'state': 'approved', 'eligibility_result': 'eligible',
                'warranty_inspection_required': True, 'warranty_service_mode': 'onsite',
                'warranty_ticket_returns': True, 'warranty_ticket_repairs': True}
        shown = self._visible(case, dict(base, warranty_inspection_step='quotation'))
        self.assertIn(('action_prepare_service_job', 'Create Inspection Quotation', True), shown)
        self.assertNotIn('Prepare Service Job', [string for _n, string, _p in shown])
        shown = self._visible(case, dict(base, warranty_inspection_step='waiting'))
        self.assertNotIn('action_prepare_service_job', [name for name, _s, _p in shown])
        self.assertIn(('action_open_inspection_quotation', 'Open Inspection Quotation', True),
                      shown)
        shown = self._visible(case, dict(base, warranty_inspection_step='job'))
        self.assertIn(('action_prepare_service_job', 'Prepare Service Job', True), shown)
        for step, primary in (('quotation', ['action_prepare_service_job']),
                              ('waiting', ['action_open_inspection_quotation'])):
            with self.subTest(step=step):
                self.assertEqual(self._primary(case, dict(
                    base, warranty_service_mode='workshop', warranty_inspection_step=step)),
                    primary)
        # Workshop mode with an open (inspection) job: the workshop step stays the primary.
        values = dict(base, state='job_created', open_service_job_id=1,
                      warranty_service_mode='workshop')
        self.assertEqual(self._primary(case, values), ['action_warranty_case_workshop_intake'])
        self.assertIn(('action_open_service_job', 'Open Service Job', False),
                      self._visible(case, values))

    def test_01c_inspection_flow_and_without_inspection(self):
        """The buttons follow the real records: one inspection quotation, reopened (never a
        second one); confirmation creates the job (existing trigger); Open Service Job opens it.
        Without inspection, Prepare Service Job creates the job directly."""
        product = self.env['product.product'].create({
            'name': 'UX Inspection Fee', 'type': 'service', 'list_price': 1500.0,
            'invoice_policy': 'order'})
        self.team.write({'warranty_inspection_product_id': product.id,
                         'warranty_inspection_amount': 1500.0})
        self.coordinator.groups_id |= self.env.ref('sales_team.group_sale_salesman_all_leads')
        self.case.sudo().write({'warranty_inspection_required': True,
                                'warranty_inspection_trigger': 'sale_confirmation'})
        case = self.case.with_user(self.coordinator)

        def step():
            case.invalidate_recordset(['warranty_inspection_step', 'open_service_job_id'])
            return case.warranty_inspection_step

        self.assertEqual(step(), 'quotation')
        case.action_prepare_service_job()
        order = self.case._warranty_inspection_orders()
        self.assertEqual((len(order), order.amount_untaxed, step()), (1, 1500.0, 'waiting'))
        self.assertEqual(case.action_open_inspection_quotation()['res_id'], order.id)
        case.action_prepare_service_job()   # existing notice: no second quotation
        self.assertEqual(self.case._warranty_inspection_orders(), order)
        self.assertFalse(case.open_service_job_id)
        order.with_user(self.coordinator).action_confirm()
        job = case.open_service_job_id
        self.assertTrue(job, 'the existing trigger creates the job on confirmation')
        self.assertFalse(step())
        self.assertEqual(case.action_open_service_job()['res_id'], job.id)

        other = self._eligible_case(self._card(self.single).unit_warranty_ids.serial_ids)
        self._approved_state(other)
        self.assertFalse(other.warranty_inspection_required)
        self.assertFalse(other.warranty_inspection_step)
        result = other.with_user(self.coordinator).action_prepare_service_job()
        self.assertEqual(result['res_model'], 'warranty.service.job')
        self.assertFalse(other._warranty_inspection_orders())

    def test_02_case_workshop_entry_points_by_type(self):
        case = 'warranty.case'
        values = {'id': 1, 'state': 'approved', 'eligibility_result': 'eligible',
                  'helpdesk_ticket_id': 1, 'warranty_ticket_returns': True,
                  'warranty_ticket_repairs': True, 'warranty_workshop_repair_count': 1}
        workshop = {'action_warranty_case_workshop_intake', 'action_warranty_case_open_repair',
                    'action_warranty_case_issue_backup'}
        names = {name for name, _s, _p in self._visible(case, dict(values, case_type='warranty_complaint'))}
        self.assertTrue({'action_warranty_case_open_repair', 'action_warranty_case_issue_backup'} <= names)
        self.assertNotIn('action_warranty_case_workshop_intake', names,
                         'the machine is already in the workshop')
        for case_type in ('amc', 'free_service'):
            names = {name for name, _s, _p in self._visible(case, dict(values, case_type=case_type))}
            self.assertFalse({'action_warranty_case_workshop_intake',
                              'action_warranty_case_open_repair'} & names, case_type)
        # AMC: no workshop action at all; a free-service case keeps Issue Backup Unit for a
        # Repair Order already in the workshop.
        names = {name for name, _s, _p in self._visible(case, dict(values, case_type='amc'))}
        self.assertFalse(workshop & names)
        # No Material Request while the Case Type is still to be determined (it would refuse).
        names = {name for name, _s, _p in self._visible(case, dict(values, case_type=False))}
        self.assertNotIn('action_create_material_request', names)

    def test_03_case_roles(self):
        """The workshop actions are Inventory actions; a Helpdesk-only user does not get them."""
        header = self._header('warranty.case', self.helpdesk_only)
        for name in ('action_warranty_case_workshop_intake', 'action_warranty_case_open_repair'):
            self.assertFalse(header.xpath(".//button[@name='%s']" % name), name)
        with self.assertRaises(AccessError):
            self.case.with_user(self.helpdesk_only).action_warranty_case_workshop_intake()

    def test_04_case_actions_reuse_the_job_actions(self):
        job = self.case.with_user(self.coordinator)._warranty_create_case_job()
        coordinator_case = self.case.with_user(self.coordinator)
        coordinator_job = job.with_user(self.coordinator)
        intake = coordinator_case.action_warranty_case_workshop_intake()
        self.assertEqual(intake, coordinator_job.action_warranty_workshop_intake())
        self.assertEqual(intake['res_model'], 'stock.return.picking')
        self.assertEqual(intake['context']['default_ticket_id'], self.case.helpdesk_ticket_id.id)
        repair = coordinator_case.action_warranty_case_open_repair()
        self.assertEqual(repair, coordinator_job.action_warranty_open_repair())
        self.assertEqual(repair['context']['default_warranty_case_id'], self.case.id)
        # Hub smart buttons open the existing records.
        self.assertEqual(self.case.action_warranty_view_ticket()['res_id'],
                         self.case.helpdesk_ticket_id.id)
        self.assertEqual(self.case.action_warranty_view_returns()['res_model'], 'stock.picking')
        self.assertEqual(self.case.warranty_visit_count, len(job.visit_ids))

    def test_05_case_without_job_workshop_mode(self):
        """Workshop Repair has no on-site job: the case opens the ticket Return itself."""
        self.case.with_user(self.coordinator).warranty_service_mode = 'workshop'
        self.assertFalse(self.case.open_service_job_id)
        action = self.case.with_user(self.coordinator).action_warranty_case_workshop_intake()
        self.assertEqual(action['res_model'], 'stock.return.picking')

    # ------------------------------------------------------------------ job header
    def test_06_job_next_action_and_amc(self):
        job = 'warranty.service.job'
        base = {'id': 1, 'helpdesk_ticket_id': 1, 'warranty_case_id': 1, 'visit_count': 1,
                'warranty_case_type': 'warranty_complaint'}
        for state, primary in (('draft', ['action_prepare_for_confirmation']),
                               ('planned', ['action_confirm_job']),
                               ('confirmed', ['action_open_current_visit']),
                               ('in_progress', ['action_open_current_visit']),
                               ('workshop', ['action_open_hold_wizard']),
                               ('incomplete', ['action_open_plan_wizard']),
                               ('completed', []), ('cancelled', [])):
            with self.subTest(state=state):
                self.assertEqual(self._primary(job, dict(base, state=state)), primary)
        workshop = {'action_warranty_workshop_intake', 'action_warranty_open_repair'}
        names = {name for name, _s, _p in self._visible(job, dict(base, state='confirmed'))}
        self.assertEqual(workshop & names, workshop)
        for case_type in ('amc', 'free_service'):
            names = {name for name, _s, _p in self._visible(
                job, dict(base, state='confirmed', warranty_case_type=case_type))}
            self.assertFalse(workshop & names, case_type)

    # ------------------------------------------------------------------ visit header
    def test_07_visit_next_action(self):
        task = 'project.task'
        base = {'id': 1, 'warranty_service_job_id': 1, 'warranty_is_visit': True,
                'state': '01_in_progress', 'warranty_worksheet_count': 1,
                'warranty_signoff_required': True, 'total_hours_spent': 1.0}
        ours = {'action_view_warranty_worksheets', 'action_preview_worksheet',
                'action_warranty_complete_visit'}
        steps = [
            ({'warranty_worksheets_ready': False}, ['action_view_warranty_worksheets']),
            ({'warranty_worksheets_ready': True}, ['action_preview_worksheet']),
            ({'warranty_worksheets_ready': True, 'worksheet_signature': True},
             ['action_warranty_complete_visit']),
            ({'warranty_worksheets_ready': True, 'warranty_signoff_required': False},
             ['action_warranty_complete_visit']),
            ({'warranty_worksheets_ready': True, 'worksheet_signature': True, 'timer_start': True},
             []),
        ]
        for values, primary in steps:
            with self.subTest(**values):
                self.assertEqual([name for name in self._primary(task, dict(base, **values))
                                  if name in ours], primary)
        # Complete Visit stays reachable (secondary) before the signature: its checks decide.
        shown = self._visible(task, dict(base, warranty_worksheets_ready=True))
        self.assertIn(('action_warranty_complete_visit', 'Complete Visit', False), shown)
        # No duplicate Sign Report: the standard one is hidden on these visits.
        self.assertEqual(sum(1 for name, _s, _p in shown if name == 'action_preview_worksheet'), 1)

    # ------------------------------------------------------------------ final corrections
    def test_08_job_in_progress_header(self):
        """In progress: Open Field Service is the only primary; the buttons that would only be
        refused by their own checks are hidden (late exception, vendor claim, closing, intake
        after the Repair Order)."""
        job = 'warranty.service.job'
        base = {'id': 1, 'state': 'in_progress', 'helpdesk_ticket_id': 1, 'warranty_case_id': 1,
                'visit_count': 1, 'warranty_case_type': 'warranty_complaint', 'job_type': 'warranty',
                'entitlement_ids': [1], 'material_request_count': 1,
                'warranty_has_open_requests': True}
        names = [name for name, _s, _p in self._visible(job, base)]
        self.assertEqual(self._primary(job, base), ['action_open_current_visit'])
        for hidden in ('action_open_late_service_wizard', 'action_create_vendor_claim',
                       'action_warranty_close_requests', 'action_warranty_record_usage'):
            self.assertNotIn(hidden, names)
        for kept in ('action_open_hold_wizard', 'action_open_cancel_wizard',
                     'action_warranty_workshop_intake', 'action_warranty_open_repair',
                     'action_create_material_request', 'action_open_fault_wizard'):
            self.assertIn(kept, names)
        # Each one comes back when its own check passes.
        names = [name for name, _s, _p in self._visible(job, dict(
            base, warranty_late_exception_available=True, can_warranty_vendor_claim=True,
            can_warranty_record_usage=True))]
        for shown in ('action_open_late_service_wizard', 'action_create_vendor_claim',
                      'action_warranty_record_usage'):
            self.assertIn(shown, names)
        names = [name for name, _s, _p in self._visible(job, dict(base, state='completed'))]
        self.assertIn('action_warranty_close_requests', names)
        names = [name for name, _s, _p in self._visible(
            job, dict(base, warranty_workshop_repair_count=1))]
        self.assertNotIn('action_warranty_workshop_intake', names)
        self.assertIn('action_warranty_open_repair', names)

    def test_09_job_flags_follow_the_actions(self):
        """The display flags use the actions' own rules (no Manager Approval policy, no consumed
        claimable part on a new job)."""
        job = self.case.with_user(self.coordinator)._warranty_create_case_job()
        self.assertFalse(job.warranty_late_exception_available)
        self.assertFalse(job.can_warranty_vendor_claim)
        self.assertFalse(self.case.can_warranty_vendor_claim)
        self.assertEqual(job.warranty_workshop_repair_count,
                         self.case.warranty_workshop_repair_count)

    def test_10_material_request_one_primary(self):
        """Material Request (warranty): one primary per stage for a user with every role."""
        mrf = 'material.purchase.requisition'
        user = self._user('ux_mrf', 'material_purchase_requisitions.group_purchase_requisition_user',
                          'stock.group_stock_user', 'helpdesk.group_helpdesk_user',
                          'industry_fsm.group_fsm_user')
        base = {'id': 1, 'is_warranty_mrf': True}
        steps = [
            ({'state': 'draft'}, ['requisition_confirm']),
            ({'state': 'draft', 'coverage_pending_count': 1},
             ['action_request_coverage_decision']),
            ({'state': 'draft', 'coverage_pending_count': 1, 'can_decide_coverage': True},
             ['action_decide_coverage']),
            ({'state': 'draft', 'can_decide_coverage': True}, ['requisition_confirm']),
            ({'state': 'dept_confirm', 'can_warranty_approve': True}, ['action_warranty_approve']),
            ({'state': 'approve', 'can_create_parts_quotation': True}, ['request_stock']),
            ({'state': 'stock', 'can_warranty_fulfil': True, 'can_warranty_record_usage': True,
              'can_create_parts_quotation': True}, ['action_warranty_fulfil']),
            ({'state': 'stock', 'can_warranty_record_usage': True},
             ['action_warranty_record_usage']),
            ({'state': 'stock'}, ['action_received']),
            ({'state': 'receive', 'can_warranty_record_usage': True,
              'can_create_parts_quotation': True}, ['action_warranty_record_usage']),
            ({'state': 'receive', 'can_create_parts_quotation': True},
             ['action_create_parts_quotation']),
        ]
        for values, primary in steps:
            with self.subTest(**values):
                self.assertEqual(self._primary(mrf, dict(base, **values), user), primary)
        # The alternatives stay available as secondary buttons.
        shown = self._visible(mrf, dict(base, state='stock', can_warranty_fulfil=True,
                                        can_warranty_record_usage=True,
                                        can_create_parts_quotation=True), user)
        secondary = [name for name, _s, primary in shown if not primary]
        for name in ('action_warranty_record_usage', 'action_received',
                     'action_create_parts_quotation'):
            self.assertIn(name, secondary)
        # Submit is refused while coverage is pending: not shown then.
        names = [name for name, _s, _p in self._visible(
            mrf, dict(base, state='draft', coverage_pending_count=1), user)]
        self.assertNotIn('requisition_confirm', names)
        # Standalone requests keep the vendor buttons.
        self.assertEqual(self._primary(mrf, {'id': 1, 'state': 'stock'}, user), ['action_received'])
        self.assertEqual(self._primary(mrf, {'id': 1, 'state': 'draft'}, user),
                         ['requisition_confirm'])

    def test_11_card_free_services_tab(self):
        """The card's Free Services tab follows the card's own free services (BA 2026-10-28:
        never the kept company Scope Mode)."""
        arch = etree.fromstring(self.env['warranty.card'].get_view(view_type='form')['arch'])
        expr = arch.xpath("//page[@name='free_services']")[0].get('invisible')
        self.assertTrue(safe_eval(expr, {'free_services_allowed': 0, 'service_entitlement_ids': []}))
        self.assertFalse(safe_eval(expr, {'free_services_allowed': 2, 'service_entitlement_ids': []}))
        self.assertFalse(safe_eval(expr, {'free_services_allowed': 0, 'service_entitlement_ids': [1]}))
        # Warranty Only company card without free services: no tab, no smart button.
        self.assertEqual(self.company.warranty_scope_mode, 'warranty_only')
        if not self.card.free_services_allowed:
            self.assertFalse(self.card.service_entitlement_ids)
            self.assertTrue(safe_eval(expr, {'free_services_allowed': 0,
                                             'service_entitlement_ids': []}))
            self.assertEqual(self.card.service_entitlement_count, 0)
