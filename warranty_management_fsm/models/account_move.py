from odoo import _, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _invoice_paid_hook(self):
        result = super()._invoice_paid_hook()
        # Approved C2 / C3: On Payment trigger. sudo: the accountant may have no Helpdesk
        # rights; only the warranty cases of these invoices' sales orders are checked.
        orders = self.sudo().invoice_line_ids.sale_line_ids.order_id
        orders.warranty_case_id._warranty_check_chargeable_trigger(_("payment"))
        return result


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_post(self):
        result = super().action_post()
        # A payment registered without journal entry (In Payment, Part 3.3 Q15 rev. B) does
        # not reconcile, so the paid hook is not called: check its invoices too.
        orders = self.sudo().invoice_ids.invoice_line_ids.sale_line_ids.order_id
        orders.warranty_case_id._warranty_check_chargeable_trigger(_("payment"))
        return result
