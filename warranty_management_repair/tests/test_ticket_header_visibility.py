from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install', 'warranty_repair')
class TestTicketHeaderVisibility(TransactionCase):
    """Figure 6: Return / Repair (workshop intake) also show on a New warranty ticket once a
    warranty case exists; the other standard actions keep the New-stage rule."""

    def _invisible(self, button, **values):
        arch = etree.fromstring(self.env['helpdesk.ticket'].get_view(
            self.env.ref('helpdesk.helpdesk_ticket_view_form').id, 'form')['arch'])
        node = arch.xpath("//header//button[@name='%s']" % button)[0]
        context = {'is_warranty': True, 'stage_id': self.env.ref('helpdesk.stage_new').id,
                   'warranty_case_count': 0, 'has_partner_picking': True,
                   'use_product_returns': True, 'use_product_repairs': True}
        context.update(values)
        return bool(safe_eval(node.get('invisible'), context))

    def test_01_return_and_repair_with_case_in_new(self):
        other_stage = self.env['helpdesk.stage'].search(
            [('id', '!=', self.env.ref('helpdesk.stage_new').id)], limit=1).id
        for button in (str(self.env.ref('stock.act_stock_return_picking').id),
                       'action_repair_order_form'):
            self.assertTrue(self._invisible(button), 'New warranty ticket, no case')
            self.assertFalse(self._invisible(button, warranty_case_count=1), 'case exists')
            self.assertFalse(self._invisible(button, stage_id=other_stage), 'stage left New')
            self.assertFalse(self._invisible(button, is_warranty=False), 'not a warranty ticket')
        # Standard conditions are kept.
        self.assertTrue(self._invisible(str(self.env.ref('stock.act_stock_return_picking').id),
                                        warranty_case_count=1, use_product_returns=False))
        self.assertTrue(self._invisible('action_repair_order_form', warranty_case_count=1,
                                        use_product_repairs=False))

    def test_02_other_actions_keep_the_new_stage_rule(self):
        arch = etree.fromstring(self.env['helpdesk.ticket'].get_view(
            self.env.ref('helpdesk.helpdesk_ticket_view_form').id, 'form')['arch'])
        self.assertTrue(arch.xpath("//field[@name='warranty_case_count']"))
        for node in arch.xpath("//header//button[@name='action_generate_fsm_task']"):
            self.assertNotIn('warranty_case_count', node.get('invisible'))
