from odoo import _, models
from odoo.exceptions import AccessError

from .warranty_card import SYSTEM_PDF_TOKEN

WARRANTY_CARD_REPORT = 'warranty_management.report_warranty_card'


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_html(self, report_ref, docids, data=None):
        if self._get_report(report_ref).report_name == WARRANTY_CARD_REPORT \
                and self.env.context.get('warranty_card_pdf_token') is not SYSTEM_PDF_TOKEN:
            raise AccessError(_("Use Download PDF on the warranty card to get its PDF."))
        return super()._render_qweb_html(report_ref, docids, data=data)
