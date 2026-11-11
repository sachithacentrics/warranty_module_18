from odoo import _, fields, models
from odoo.exceptions import AccessError


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    # Send to Customer: the copy of the soft copy attached to the email. The customer receives
    # it; in the chatter only administrators can open it (user decision), also in ir.binary.
    warranty_card_pdf_copy = fields.Boolean(string='Warranty Card PDF Copy', readonly=True,
                                            copy=False)

    def _warranty_check_pdf_copy_content(self):
        """The file content of an emailed warranty card PDF: system code (sending the email)
        and administrators only; other users use Download PDF on the card."""
        if self.env.su or self.env.is_system():
            return
        if any(self.sudo().mapped('warranty_card_pdf_copy')):
            raise AccessError(_("Use Download PDF on the warranty card to get its PDF."))

    def _compute_raw(self):
        self._warranty_check_pdf_copy_content()
        return super()._compute_raw()

    def _compute_datas(self):
        self._warranty_check_pdf_copy_content()
        return super()._compute_datas()
