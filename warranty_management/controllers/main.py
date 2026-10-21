from odoo import http
from odoo.http import request


class WarrantyCardPdfController(http.Controller):

    @http.route('/warranty/card/pdf/<string:token>', type='http', auth='user')
    def warranty_card_pdf(self, token, **kwargs):
        """Deliver the protected warranty card PDF for a single-use ticket of the current user
        and record the download (approved D1-D5)."""
        attachment = request.env['warranty.card.download.ticket']._consume(token)
        return attachment._to_http_stream().get_response(as_attachment=True, max_age=0)
