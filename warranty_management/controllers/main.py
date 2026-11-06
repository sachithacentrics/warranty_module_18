from odoo import http
from odoo.http import content_disposition, request


class WarrantyCardPdfController(http.Controller):

    @http.route('/warranty/card/pdf/<string:token>', type='http', auth='user')
    def warranty_card_pdf(self, token, **kwargs):
        """Deliver the warranty card PDF for a single-use ticket of the current user and record
        the download (approved D1-D5). The PDF is rendered now with the current report; the stored
        attachment stays as it is. A failed rendering rolls the download record back."""
        attachment = request.env['warranty.card.download.ticket']._consume(token)
        card = request.env['warranty.card'].browse(attachment.res_id)
        pdf = card._warranty_render_pdf()
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', content_disposition(attachment.name)),
            ('Cache-Control', 'no-store'),
        ])
