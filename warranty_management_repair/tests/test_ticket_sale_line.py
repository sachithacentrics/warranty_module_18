from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'warranty_repair', 'warranty_ticket_sale_line')
class TestWarrantyTicketSaleLine(TransactionCase):
    """helpdesk_sale_timesheet proposes the customer's latest prepaid service line as the ticket's
    Sales Order Item (UAT ticket #87: another case's inspection line). Warranty tickets get no
    proposal; every other behaviour stays standard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        hour = cls.env.ref('uom.product_uom_hour')
        cls.project = cls.env['project.project'].create({
            'name': 'SOL Helpdesk', 'allow_billable': True, 'allow_timesheets': True})
        cls.team = cls.env['helpdesk.team'].create({
            'name': 'SOL Team', 'use_helpdesk_timesheet': True, 'use_helpdesk_sale_timesheet': True,
            'project_id': cls.project.id})
        cls.other_team = cls.env['helpdesk.team'].create({
            'name': 'SOL Team 2', 'use_helpdesk_timesheet': True,
            'use_helpdesk_sale_timesheet': True, 'project_id': cls.project.id})
        # Like "UAT - AC Inspection Service": a timesheet service in hours, invoiced on order.
        cls.inspection = cls.env['product.product'].create({
            'name': 'SOL Inspection Service', 'type': 'service', 'service_type': 'timesheet',
            'invoice_policy': 'order', 'uom_id': hour.id, 'uom_po_id': hour.id})
        cls.customer = cls.env['res.partner'].create({'name': 'SOL Customer'})
        cls.customer_two = cls.env['res.partner'].create({'name': 'SOL Customer 2'})
        cls.line = cls._prepaid_line(cls.customer)
        cls.line_two = cls._prepaid_line(cls.customer_two)

    @classmethod
    def _prepaid_line(cls, partner):
        order = cls.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': cls.inspection.id, 'product_uom_qty': 1})]})
        order.action_confirm()
        return order.order_line

    def _ticket(self, **vals):
        return self.env['helpdesk.ticket'].create(dict({
            'name': 'SOL ticket', 'team_id': self.team.id, 'partner_id': self.customer.id}, **vals))

    def _saved(self, ticket, vals):
        ticket.write(vals)
        self.env.flush_all()
        ticket.invalidate_recordset(['sale_line_id', 'sale_order_id'])
        return ticket.sale_line_id

    def test_01_warranty_ticket_gets_no_proposal(self):
        ticket = self._ticket(is_warranty=True)
        self.assertFalse(ticket.sale_line_id)
        self.assertFalse(ticket.sale_order_id)

    def test_02_non_warranty_ticket_is_standard(self):
        ticket = self._ticket()
        self.assertEqual(ticket.sale_line_id, self.line)
        ticket.sale_line_id = False
        self.assertEqual(self._saved(ticket, {'partner_id': self.customer.id}), self.line,
                         'Standard: the empty field is proposed again.')

    def test_03_cleared_stays_empty_on_customer_team_project(self):
        ticket = self._ticket(is_warranty=True)
        for vals in ({'partner_id': self.customer.id}, {'team_id': self.team.id},
                     {'project_id': self.project.id}, {'team_id': self.other_team.id},
                     {'partner_id': self.customer_two.id}):
            with self.subTest(vals=vals):
                self.assertFalse(self._saved(ticket, vals))

    def test_04_manual_line_is_kept(self):
        ticket = self._ticket(is_warranty=True)
        ticket.sale_line_id = self.line
        for vals in ({'partner_id': self.customer.id}, {'team_id': self.other_team.id},
                     {'project_id': self.project.id}):
            with self.subTest(vals=vals):
                self.assertEqual(self._saved(ticket, vals), self.line)
        # Standard coherence rule unchanged: another customer drops the line.
        self.assertFalse(self._saved(ticket, {'partner_id': self.customer_two.id}))

    def test_05_fixed_price_project_line_is_kept(self):
        fixed = self.env['project.project'].create({
            'name': 'SOL Fixed', 'allow_billable': True, 'allow_timesheets': True,
            'partner_id': self.customer.id, 'sale_line_id': self.line.id})
        self.assertNotEqual(fixed.pricing_type, 'task_rate')
        team = self.env['helpdesk.team'].create({
            'name': 'SOL Fixed Team', 'use_helpdesk_timesheet': True,
            'use_helpdesk_sale_timesheet': True, 'project_id': fixed.id})
        ticket = self._ticket(is_warranty=True, team_id=team.id)
        self.assertEqual(ticket.sale_line_id, self.line)

    def test_06_warranty_flag_set_later(self):
        # No line proposed before the flag: none afterwards either.
        ticket = self._ticket(partner_id=self.env['res.partner'].create({'name': 'SOL New'}).id)
        self.assertFalse(ticket.sale_line_id)
        ticket.is_warranty = True
        self._prepaid_line(ticket.partner_id)
        self.assertFalse(self._saved(ticket, {'partner_id': ticket.partner_id.id}))
        # A line already on the ticket is not removed by the flag (it may be the user's choice);
        # once cleared it stays empty.
        ticket = self._ticket()
        self.assertEqual(ticket.sale_line_id, self.line)
        ticket.is_warranty = True
        self.assertEqual(self._saved(ticket, {'partner_id': self.customer.id}), self.line)
        ticket.sale_line_id = False
        self.assertFalse(self._saved(ticket, {'partner_id': self.customer.id}))

    def test_07_plan_intervention_inherits_no_line(self):
        fsm_project = self.env['project.project'].create({
            'name': 'SOL FSM', 'is_fsm': True, 'company_id': self.env.company.id})
        for is_warranty, expected in ((True, False), (False, self.line.id)):
            with self.subTest(is_warranty=is_warranty):
                ticket = self._ticket(is_warranty=is_warranty)
                wizard = self.env['helpdesk.create.fsm.task'].create({
                    'helpdesk_ticket_id': ticket.id, 'project_id': fsm_project.id,
                    'name': 'SOL intervention', 'partner_id': self.customer.id})
                self.assertEqual(wizard._generate_task_values().get('sale_line_id', False),
                                 expected)
