from datetime import timedelta

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged
from odoo.tools.safe_eval import safe_eval

from .test_warranty_replacement import ReplacementCommon


@tagged('post_install', '-at_install', 'warranty_repair', 'warranty_figure6')
class TestFigure6Navigation(ReplacementCommon):
    """Figure 6 navigation (Phase 1): Workshop Intake / Repair Order from the service job, Issue
    Backup Machine and Return Machine to Customer on the Repair Order, Backup Units smart buttons
    and the Next Step. The actions open the existing wizards and forms; every rule stays theirs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coordinator.email = 'figure6.coordinator@example.com'
        cls.helpdesk_only = cls._user('f6_helpdesk', 'helpdesk.group_helpdesk_user')
        physical = cls.env.ref('stock.stock_location_locations')
        locations = {name: cls.env['stock.location'].create({
            'name': name, 'usage': 'internal', 'company_id': cls.company.id,
            'location_id': physical.id}) for name in ('F6 Intake', 'F6 Backup Stock', 'F6 Loan',
                                                       'F6 Inspection')}
        cls.backup_stock = locations['F6 Backup Stock']
        cls.inspection = locations['F6 Inspection']
        issue_type, return_type = (cls.env['stock.picking.type'].create({
            'name': name, 'code': 'internal', 'sequence_code': code, 'company_id': cls.company.id,
            'default_location_src_id': source.id, 'default_location_dest_id': destination.id,
        }) for name, code, source, destination in (
            ('F6 Backup Issue', 'F6BI', cls.backup_stock, locations['F6 Loan']),
            ('F6 Backup Return', 'F6BR', locations['F6 Loan'], cls.inspection)))
        cls.company.write({'warranty_repair_intake_location_id': locations['F6 Intake'].id,
                           'warranty_backup_issue_type_id': issue_type.id,
                           'warranty_backup_return_type_id': return_type.id})
        cls.team.write({'use_product_returns': True, 'use_product_repairs': True})
        cls.backup_product = cls.env['product.product'].create({
            'name': 'F6 Backup AC', 'type': 'consu', 'is_storable': True, 'tracking': 'serial'})
        cls.backup_lot = cls.env['stock.lot'].create({
            'name': 'F6-BK-01', 'product_id': cls.backup_product.id})
        cls.env['stock.quant']._update_available_quantity(
            cls.backup_product, cls.backup_stock, 1, lot_id=cls.backup_lot)

    def setUp(self):
        super().setUp()
        self.card = self._card(self.single)
        self.serial = self.card.unit_warranty_ids.serial_ids
        self.delivery = self.card.sale_order_id.picking_ids
        self.case = self._eligible_case(self.serial)
        self.assertEqual(self.case.eligibility_result, 'eligible', self.case.eligibility_reason)
        self._approved_state(self.case)
        self.ticket = self.case.helpdesk_ticket_id

    # ------------------------------------------------------------------ helpers
    def _job(self):
        return self.case.with_user(self.coordinator)._warranty_create_case_job()

    def _receive(self, picking, serial):
        """Validate a return from the customer: the serial is entered, as on the screen."""
        picking.action_assign()
        picking.move_line_ids.lot_id = serial
        picking.move_ids.picked = True
        result = picking.with_context(skip_backorder=True).button_validate()
        self.assertIs(result, True, result)

    def _return(self, action, quantity=1, product=None):
        """Fill and confirm a Return wizard opened by an action (the line of `product`, else the
        first one); the new return picking."""
        form = Form(self.env[action['res_model']].with_user(self.coordinator).with_context(
            action['context']))
        for index in range(len(form.product_return_moves)):
            with form.product_return_moves.edit(index) as line:
                if product and line.product_id != product:
                    continue
                line.quantity = quantity
                break
        wizard = form.save()
        return wizard, self.env['stock.picking'].browse(wizard.action_create_returns()['res_id'])

    def _intake(self):
        # The ticket's Return button (stock.act_stock_return_picking with this context).
        _wizard, picking = self._return({
            'res_model': 'stock.return.picking',
            'context': {'default_ticket_id': self.ticket.id, 'default_company_id': self.company.id}})
        self._receive(picking, self.serial)
        return picking

    def _repair(self, context):
        form = Form(self.env['repair.order'].with_user(self.coordinator).with_context(context))
        return form.save()

    def _ticket_repair(self):
        return self._repair(self.ticket.with_user(self.coordinator).action_repair_order_form()[
            'context'])

    def _issue_backup(self, repair):
        action = repair.with_user(self.coordinator).action_warranty_issue_backup()
        form = Form(self.env['warranty.backup.unit'].with_user(self.coordinator).with_context(
            action['context']))
        form.product_id = self.backup_product
        form.lot_id = self.backup_lot
        form.issue_condition = 'good'
        form.expected_return_date = fields.Date.today() + timedelta(days=7)
        unit = form.save()
        unit.action_warranty_backup_issue()
        self._validate(unit.issue_picking_id)
        self.assertEqual(unit.state, 'issued')
        return unit

    def _next(self, repair):
        repair.invalidate_recordset(['warranty_next_step', 'warranty_backup_unit_count',
                                     'warranty_backup_open'])
        return repair.with_user(self.coordinator).warranty_next_step or ''

    # ------------------------------------------------------------------ service job
    def test_01_job_workshop_intake_is_the_ticket_return(self):
        job = self._job()
        action = job.with_user(self.coordinator).action_warranty_workshop_intake()
        self.assertEqual(action['res_model'], 'stock.return.picking')
        self.assertEqual(action['context']['default_ticket_id'], self.ticket.id)
        wizard, intake = self._return(action)
        self.assertTrue(wizard.warranty_repair_intake)
        self.assertEqual(wizard.picking_id, self.delivery, "The machine's delivery is proposed.")
        self._receive(intake, self.serial)
        self.assertTrue(intake.warranty_repair_intake)
        self.assertEqual(intake.location_dest_id, self.company.warranty_repair_intake_location_id)
        self.assertEqual(self.card.sale_order_id.order_line.qty_delivered, 1,
                         'Sales Order quantities unchanged')
        # Rights, team option and closed job.
        for user in (self.outsider, self.helpdesk_only):
            with self.assertRaises(AccessError):
                job.with_user(user).action_warranty_workshop_intake()
        self.team.use_product_returns = False
        with self.assertRaisesRegex(UserError, 'Enable Returns'):
            job.with_user(self.coordinator).action_warranty_workshop_intake()
        self.team.use_product_returns = True
        job.with_user(self.coordinator).action_cancel()
        with self.assertRaisesRegex(UserError, 'closed'):
            job.with_user(self.coordinator).action_warranty_workshop_intake()

    def test_02_job_repair_order_create_then_open(self):
        job = self._job()
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        self.assertFalse(action.get('res_id'))
        self.assertEqual(action['context']['default_warranty_case_id'], self.case.id)
        self.assertEqual(action['context']['default_lot_id'], self.serial.id)
        intake = self._intake()
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        self.assertEqual(action['context']['default_repair_picking_id'], intake.id)
        repair = self._repair(action['context'])
        self.assertEqual((repair.warranty_case_id, repair.ticket_id, repair.lot_id, repair.picking_id),
                         (self.case, self.ticket, self.serial, intake))
        self.assertEqual((repair.warranty_card_id, repair.warranty_unit_id),
                         (self.card, self.card.unit_warranty_ids))
        # Opened, not created again.
        count = self.env['repair.order'].search_count([('warranty_case_id', '=', self.case.id)])
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        self.assertEqual((action['res_model'], action['res_id']), ('repair.order', repair.id))
        self.assertEqual(
            self.env['repair.order'].search_count([('warranty_case_id', '=', self.case.id)]), count)
        # Two Repair Orders still in the workshop: the list; a cancelled one is ignored.
        other = self._ticket_repair()
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        self.assertEqual(action['domain'], [('id', 'in', (repair | other).ids)])
        other.action_repair_cancel()
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        self.assertEqual(action['res_id'], repair.id)
        with self.assertRaises(AccessError):
            job.with_user(self.helpdesk_only).action_warranty_open_repair()

    # ------------------------------------------------------------------ backup units
    def test_03_issue_backup_is_prefilled_and_never_automatic(self):
        self._intake()
        repair = self._ticket_repair()
        before = self.env['warranty.backup.unit'].search_count([])
        action = repair.with_user(self.coordinator).action_warranty_issue_backup()
        self.assertEqual(self.env['warranty.backup.unit'].search_count([]), before,
                         'The button only opens the form.')
        form = Form(self.env['warranty.backup.unit'].with_user(self.coordinator).with_context(
            action['context']))
        self.assertEqual((form.ticket_id, form.warranty_case_id, form.repair_id, form.partner_id),
                         (self.ticket, self.case, repair, self.partner))
        self.assertEqual(form.warranty_card_id, self.card)
        form.product_id = self.backup_product
        form.lot_id = self.backup_lot
        form.issue_condition = 'good'
        form.expected_return_date = fields.Date.today() + timedelta(days=7)
        unit = form.save()
        self.assertEqual(unit.state, 'draft')
        self.assertFalse(unit.issue_picking_id, 'Nothing is issued until Create Issue Transfer.')
        # The draft unit is opened again, not a second one.
        action = repair.with_user(self.coordinator).action_warranty_issue_backup()
        self.assertEqual((action['res_model'], action.get('res_id')),
                         ('warranty.backup.unit', unit.id))
        with self.assertRaises(AccessError):
            repair.with_user(self.outsider).action_warranty_issue_backup()

    def test_04_prefilled_repair_kept_with_two_active_repairs(self):
        """Two active Repair Orders on the case: the form keeps the one of the button."""
        self._intake()
        first = self._ticket_repair()
        second = self._ticket_repair()
        action = second.with_user(self.coordinator).action_warranty_issue_backup()
        form = Form(self.env['warranty.backup.unit'].with_user(self.coordinator).with_context(
            action['context']))
        self.assertEqual(form.repair_id, second)
        self.assertNotEqual(form.repair_id, first)

    def test_05_backup_smart_buttons(self):
        job = self._job()
        self._intake()
        repair = self._ticket_repair()
        unit = self._issue_backup(repair)
        self.assertEqual(unit.warranty_service_job_id, job)
        for record in (self.ticket, self.case, job, repair):
            with self.subTest(model=record._name):
                record.invalidate_recordset(['warranty_backup_unit_count'])
                self.assertEqual(record.with_user(self.coordinator).warranty_backup_unit_count, 1)
                action = record.with_user(self.coordinator).action_view_warranty_backup_units()
                self.assertEqual((action['res_model'], action['res_id']),
                                 ('warranty.backup.unit', unit.id))
        # Helpdesk users without Inventory rights see the same counts.
        self.assertEqual(self.ticket.with_user(self.helpdesk_only).warranty_backup_unit_count, 1)
        self.assertEqual(self.case.with_user(self.helpdesk_only).warranty_backup_unit_count, 1)
        other = self._eligible_case(self.serial)
        self.assertEqual(other.helpdesk_ticket_id.warranty_backup_unit_count, 0)
        self.assertEqual(other.warranty_backup_unit_count, 0)

    # ------------------------------------------------------------------ return and next step
    def test_06_helpdesk_led_flow_next_step_and_return(self):
        intake = self._intake()
        repair = self._ticket_repair()
        self.assertEqual(self._next(repair),
                         'Confirm the Repair Order. Optional: Issue Backup Machine.')
        with self.assertRaisesRegex(UserError, 'not a finished warranty repair'):
            repair.with_user(self.coordinator).action_warranty_return_machine()
        repair.with_user(self.coordinator).action_validate()
        self.assertEqual(self._next(repair), 'Start Repair. Optional: Issue Backup Machine.')
        unit = self._issue_backup(repair)
        self.assertEqual(self._next(repair), 'Start Repair.')
        repair.with_user(self.coordinator).action_repair_start()
        self.assertEqual(self._next(repair), 'Set the Repair Result, then End Repair.')
        repair.warranty_repair_result = 'repaired'
        repair.with_user(self.coordinator).action_repair_done()
        self.assertEqual(repair.warranty_intake_state, 'repaired')
        self.assertEqual(self._next(repair), 'Return Machine to Customer.')
        # Return Machine to Customer: the standard Return of the intake receipt.
        action = repair.with_user(self.coordinator).action_warranty_return_machine()
        self.assertEqual(action['res_model'], 'stock.return.picking')
        self.assertEqual(action['context']['active_id'], intake.id)
        wizard, back = self._return(action)
        self.assertEqual(wizard.picking_id, intake)
        self.assertFalse(wizard.warranty_repair_intake)
        # A return not validated yet is opened, not a second wizard.
        action = repair.with_user(self.coordinator).action_warranty_return_machine()
        self.assertEqual((action['res_model'], action['res_id']), ('stock.picking', back.id))
        self._validate(back)
        self.assertEqual(back.move_line_ids.lot_id, self.serial)
        self.assertEqual(back.location_dest_id.usage, 'customer')
        self.assertTrue(repair.warranty_equipment_returned)
        self.assertEqual(self.card.sale_order_id.order_line.qty_delivered, 1)
        with self.assertRaisesRegex(UserError, 'already been returned'):
            repair.with_user(self.coordinator).action_warranty_return_machine()
        with self.assertRaisesRegex(UserError, 'no longer in the workshop'):
            repair.with_user(self.coordinator).action_warranty_issue_backup()
        # Backup return, inspection and closure: existing buttons.
        self.assertIn('receive the backup machine', self._next(repair))
        unit.return_condition = 'good'
        unit.with_user(self.coordinator).action_warranty_backup_return()
        self.assertIn('validate the return', self._next(repair))
        self._validate(unit.return_picking_id)
        self.assertEqual(unit.state, 'returned')
        self.assertIn('move the serial to Backup Stock', self._next(repair))
        Quant = self.env['stock.quant']
        Quant._update_available_quantity(self.backup_product, self.inspection, -1,
                                         lot_id=self.backup_lot)
        Quant._update_available_quantity(self.backup_product, self.backup_stock, 1,
                                         lot_id=self.backup_lot)
        unit.with_user(self.coordinator).action_warranty_backup_close()
        self.assertEqual(self._next(repair), 'Complete Warranty Case.')
        repair.with_user(self.coordinator).action_warranty_complete_case()
        self.assertEqual(self.case.state, 'completed')
        self.assertIn('accounting steps', self._next(repair))

    def test_07_next_step_follows_the_guards(self):
        """Missing intake, the inspection gate and an open service job: the Next Step names the
        problem the existing guard raises, and the guard still refuses."""
        repair = self._repair(self.ticket.with_user(self.coordinator).action_repair_order_form()[
            'context'])
        self.assertIn('Warranty Repair Intake', self._next(repair))
        with self.assertRaisesRegex(UserError, 'Warranty Repair Intake'):
            repair.with_user(self.coordinator).action_validate()
        intake = self._intake()
        repair.picking_id = intake
        repair.with_user(self.coordinator).action_validate()
        self.case.sudo().warranty_inspection_required = True
        self.assertIn('Inspection Trigger', self._next(repair))
        with self.assertRaisesRegex(UserError, 'Inspection Trigger'):
            repair.with_user(self.coordinator).action_repair_start()
        self.case.sudo().warranty_inspection_required = False
        job = self._job()
        repair.with_user(self.coordinator).action_repair_start()
        repair.warranty_repair_result = 'repaired'
        repair.with_user(self.coordinator).action_repair_done()
        _wizard, back = self._return(repair.with_user(self.coordinator)
                                     .action_warranty_return_machine())
        self._validate(back)
        self.assertIn(job.name, self._next(repair))
        self.assertIn('completed by that job', self._next(repair))
        with self.assertRaisesRegex(UserError, 'completed by that job'):
            repair.with_user(self.coordinator).action_warranty_complete_case()

    def test_08_view_buttons(self):
        """The buttons and smart buttons are in the forms with their visibility fields."""
        for view, names in (
                ('repair.view_repair_order_form', ('action_warranty_return_machine',
                                                   'action_warranty_issue_backup',
                                                   'action_view_warranty_backup_units')),
                ('warranty_management_fsm.warranty_service_job_view_form', (
                    'action_warranty_workshop_intake', 'action_warranty_open_repair',
                    'action_view_warranty_backup_units')),
                ('helpdesk.helpdesk_ticket_view_form', ('action_view_warranty_backup_units',)),
                ('warranty_management_helpdesk.warranty_case_view_form',
                 ('action_view_warranty_backup_units',))):
            model = self.env.ref(view).model
            arch = self.env[model].get_view(self.env.ref(view).id, 'form')['arch']
            for name in names:
                with self.subTest(view=view, button=name):
                    self.assertIn('name="%s"' % name, arch)

    # ------------------------------------------------------------------ edge cases (verification)
    def _invisible(self, view, button, **values):
        """Evaluated invisible modifier of a header button (as the web client does)."""
        arch = etree.fromstring(self.env[self.env.ref(view).model].get_view(
            self.env.ref(view).id, 'form')['arch'])
        node = arch.xpath("//header//button[@name='%s']" % button)[0]
        return bool(safe_eval(node.get('invisible'), values))

    def test_09_job_buttons_by_job_state(self):
        view = 'warranty_management_fsm.warranty_service_job_view_form'
        for state in ('draft', 'planned', 'confirmed', 'in_progress', 'workshop', 'awaiting_parts',
                      'incomplete', 'rescheduled', 'completed', 'cancelled'):
            for button in ('action_warranty_workshop_intake', 'action_warranty_open_repair'):
                with self.subTest(state=state, button=button):
                    # UX cleanup: not on a draft job.
                    self.assertEqual(
                        self._invisible(view, button, state=state, helpdesk_ticket_id=1,
                                        warranty_case_type='warranty_complaint',
                                        warranty_workshop_repair_count=0),
                        state in ('draft', 'completed', 'cancelled'))
                    # UX cleanup: not on an AMC / free service visit (Report Fault instead).
                    for case_type in ('amc', 'free_service'):
                        self.assertTrue(self._invisible(view, button, state=state,
                                                        helpdesk_ticket_id=1,
                                                        warranty_case_type=case_type,
                                                        warranty_workshop_repair_count=0))
        self.assertTrue(self._invisible(view, 'action_warranty_workshop_intake', state='workshop',
                                        helpdesk_ticket_id=False,
                                        warranty_case_type='warranty_complaint',
                                        warranty_workshop_repair_count=0))
        # UX: no second Workshop Intake once the case's Repair Order is in the workshop.
        self.assertTrue(self._invisible(view, 'action_warranty_workshop_intake', state='in_progress',
                                        helpdesk_ticket_id=1,
                                        warranty_case_type='warranty_complaint',
                                        warranty_workshop_repair_count=1))

    def test_10_repair_buttons_by_status(self):
        view = 'repair.view_repair_order_form'
        base = {'warranty_case_id': 1, 'ticket_id': 1, 'state': 'done',
                'warranty_intake_state': 'repaired', 'warranty_machine_replaced': False,
                'warranty_backup_open': False, 'warranty_case_state': 'approved'}
        ret = 'action_warranty_return_machine'
        self.assertFalse(self._invisible(view, ret, **base))
        for change in ({'warranty_intake_state': 'returned'}, {'warranty_machine_replaced': True},
                       {'state': 'under_repair', 'warranty_intake_state': 'under_repair'},
                       {'warranty_case_id': False}):
            with self.subTest(button=ret, **change):
                self.assertTrue(self._invisible(view, ret, **dict(base, **change)))
        issue = 'action_warranty_issue_backup'
        for state, intake in (('draft', 'received'), ('confirmed', 'received'),
                              ('under_repair', 'under_repair'), ('done', 'repaired')):
            with self.subTest(button=issue, state=state):
                self.assertFalse(self._invisible(view, issue, **dict(
                    base, state=state, warranty_intake_state=intake)))
        for change in ({'warranty_backup_open': True}, {'warranty_intake_state': 'returned'},
                       {'state': 'cancel', 'warranty_intake_state': 'cancelled'},
                       {'warranty_machine_replaced': True}, {'ticket_id': False}):
            with self.subTest(button=issue, **change):
                self.assertTrue(self._invisible(view, issue, **dict(base, **change)))

    def _second_case_on_ticket(self):
        other_card = self._card(self.single)
        other_serial = other_card.unit_warranty_ids.serial_ids
        other = self.env['warranty.case'].create({
            'helpdesk_ticket_id': self.ticket.id, 'partner_id': self.partner.id,
            'company_id': self.company.id, 'case_type': 'warranty_complaint',
            'serial_id': other_serial.id, 'requested_item_ids': [(6, 0, self.item.ids)]})
        other.action_check_eligibility()
        self._approved_state(other)
        return other, other_serial

    def test_11b_two_cases_repair_serial_default(self):
        """F1 fixed (C1, 18.0.1.7.0): with two active cases on the ticket, the job's Repair Order
        button proposes the job's case and its serial."""
        other, other_serial = self._second_case_on_ticket()
        job = other.with_user(self.coordinator)._warranty_create_case_job()
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        self.assertEqual(action['context']['default_warranty_case_id'], other.id)
        self.assertEqual(action['context']['default_lot_id'], other_serial.id)
        self.assertEqual(action['context']['default_product_id'], other_serial.product_id.id)

    def test_11_two_cases_on_one_ticket(self):
        """The job's buttons and the backup form work with the job's own case."""
        other, other_serial = self._second_case_on_ticket()
        self.assertEqual(len(self.ticket._warranty_active_cases()), 2)
        job = other.with_user(self.coordinator)._warranty_create_case_job()
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        self.assertEqual(action['context']['default_warranty_case_id'], other.id)
        # Serial entered by the user (see test_11b).
        repair = self._repair(dict(action['context'], default_lot_id=other_serial.id,
                                   default_product_id=self.single.id))
        self.assertEqual(repair.warranty_case_id, other)
        backup = Form(self.env['warranty.backup.unit'].with_user(self.coordinator).with_context(
            repair.with_user(self.coordinator).action_warranty_issue_backup()['context']))
        self.assertEqual((backup.warranty_case_id, backup.repair_id), (other, repair))
        self.assertEqual(job.with_user(self.coordinator).action_warranty_open_repair()['res_id'],
                         repair.id)
        self.assertEqual(self._job().with_user(self.coordinator).action_warranty_open_repair()[
            'context']['default_warranty_case_id'], self.case.id, 'the other case: no repair')

    def test_12_kit_indoor_serial(self):
        """Kit: the case serial is the Indoor Unit; only that component goes to the workshop
        and comes back; the Outdoor Unit stays with the customer."""
        card = self._card(self.kit)
        unit = card.unit_warranty_ids
        case = self._eligible_case(unit.indoor_serial_id)
        self.assertEqual(case.eligibility_result, 'eligible', case.eligibility_reason)
        self._approved_state(case)
        self.ticket = case.helpdesk_ticket_id
        job = case.with_user(self.coordinator)._warranty_create_case_job()
        delivery = card.sale_order_id.picking_ids
        wizard, intake = self._return(job.with_user(self.coordinator)
                                      .action_warranty_workshop_intake(), product=self.indoor)
        self.assertEqual(wizard.picking_id, delivery)
        self.assertEqual(intake.move_ids.product_id, self.indoor, 'Only the Indoor Unit comes in.')
        self._receive(intake, unit.indoor_serial_id)
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        self.assertEqual((action['context']['default_lot_id'],
                          action['context']['default_repair_picking_id']),
                         (unit.indoor_serial_id.id, intake.id))
        repair = self._repair(action['context'])
        self.assertEqual((repair.product_id, repair.lot_id), (self.indoor, unit.indoor_serial_id))
        repair.with_user(self.coordinator).action_validate()
        repair.with_user(self.coordinator).action_repair_start()
        repair.warranty_repair_result = 'repaired'
        repair.with_user(self.coordinator).action_repair_done()
        _wizard, back = self._return(repair.with_user(self.coordinator)
                                     .action_warranty_return_machine())
        self._validate(back)
        self.assertEqual(back.move_line_ids.lot_id, unit.indoor_serial_id)
        self.assertTrue(repair.warranty_equipment_returned)
        self.assertEqual(unit.outdoor_serial_id.quant_ids.filtered(
            lambda quant: quant.quantity > 0).location_id.usage, 'customer')

    def test_13_repeated_repair_and_second_backup_loan(self):
        """After the machine went back, the job creates a new Repair Order (not the old one) and
        the next intake proposes the delivery that returned it. A returned backup unit does not
        prevent a second loan while the machine is still in the workshop."""
        job = self._job()
        self._intake()
        repair = self._ticket_repair()
        unit = self._issue_backup(repair)
        unit.return_condition = 'good'
        unit.with_user(self.coordinator).action_warranty_backup_return()
        self._validate(unit.return_picking_id)
        self.assertEqual(unit.state, 'returned')
        action = repair.with_user(self.coordinator).action_warranty_issue_backup()
        self.assertFalse(action.get('res_id'), 'A returned unit is not reopened.')
        self.assertEqual(action['context']['default_repair_id'], repair.id)
        repair.with_user(self.coordinator).action_validate()
        repair.with_user(self.coordinator).action_repair_start()
        repair.warranty_repair_result = 'repaired'
        repair.with_user(self.coordinator).action_repair_done()
        _wizard, back = self._return(repair.with_user(self.coordinator)
                                     .action_warranty_return_machine())
        self._validate(back)
        action = job.with_user(self.coordinator).action_warranty_open_repair()
        self.assertFalse(action.get('res_id'), 'Repeated repair: a new Repair Order.')
        wizard, second = self._return(job.with_user(self.coordinator)
                                      .action_warranty_workshop_intake())
        self.assertEqual(wizard.picking_id, back, 'The latest delivery of the machine.')
        self._receive(second, self.serial)
        new = self._repair(job.with_user(self.coordinator).action_warranty_open_repair()['context'])
        self.assertEqual(new.picking_id, second)
        self.assertNotEqual(new, repair)

    def test_14_access_rights(self):
        self._intake()
        repair = self._ticket_repair()
        job = self._job()
        with self.assertRaises(AccessError):
            repair.with_user(self.helpdesk_only).action_warranty_return_machine()
        for method in ('action_warranty_workshop_intake', 'action_warranty_open_repair'):
            with self.subTest(method=method), self.assertRaises(AccessError):
                getattr(job.with_user(self.helpdesk_only), method)()
        # Repair Orders themselves need Inventory rights (standard), so the Repair Order buttons
        # are never reached by Helpdesk-only users; their backup smart buttons still work.
        self.assertFalse(self.env['repair.order'].with_user(self.helpdesk_only).has_access('read'))
        self.assertEqual(self.ticket.with_user(self.helpdesk_only).warranty_backup_unit_count, 0)
