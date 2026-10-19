from odoo import _, models
from odoo.exceptions import AccessError


class IrBinary(models.AbstractModel):
    _inherit = 'ir.binary'

    def _record_to_stream(self, record, field_name):
        # Approved D5: the protected warranty card PDF is never served by the standard web
        # download / preview / image links (also for administrators); only Download PDF
        # (/warranty/card/pdf/<ticket>) delivers it. Other attachments are unchanged.
        if record._name == 'warranty.card' and field_name == 'pdf_file':
            raise AccessError(_("Use Download PDF on the warranty card to get its PDF."))
        if record._name == 'ir.attachment':
            attachment = record.sudo()
            if attachment.res_model == 'warranty.card' and attachment.res_field == 'pdf_file':
                raise AccessError(_("Use Download PDF on the warranty card to get its PDF."))
        return super()._record_to_stream(record, field_name)
