from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _invoice_paid_hook(self):
        """AMC-A05 / G03 (approved B4b): the payment of an invoice of an AMC Sales Order
        activates its contract when the plan's trigger is On Payment of the First Invoice.
        Scoped to invoices with lines of AMC orders; other invoices are untouched."""
        result = super()._invoice_paid_hook()
        for invoice in self.filtered(lambda move: move.move_type == 'out_invoice'):
            orders = invoice.invoice_line_ids.sale_line_ids.order_id.filtered('amc_contract_id')
            for order in orders:
                contract = order.amc_contract_id
                if contract.sale_order_id == order:
                    contract.sudo()._amc_on_invoice_paid(invoice)
        return result
