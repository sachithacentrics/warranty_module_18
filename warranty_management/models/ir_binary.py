from odoo import _, models
from odoo.exceptions import AccessError


class IrBinary(models.AbstractModel):
    _inherit = 'ir.binary'

    def _record_to_stream(self, record, field_name):
        if record._name == 'warranty.card' and field_name == 'pdf_file':
            raise AccessError(_("Use Download PDF on the warranty card to get its PDF."))
        if record._name == 'ir.attachment':
            attachment = record.sudo()
            if attachment.res_model == 'warranty.card' and attachment.res_field == 'pdf_file':
                raise AccessError(_("Use Download PDF on the warranty card to get its PDF."))
            # The emailed copy (Send to Customer): administrators only (user decision).
            if attachment.warranty_card_pdf_copy and not self.env.is_system():
                raise AccessError(_("Use Download PDF on the warranty card to get its PDF."))
        return super()._record_to_stream(record, field_name)
