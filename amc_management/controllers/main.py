from odoo import http
from odoo.http import request
from odoo.tools.misc import file_path

# Kept outside /static on purpose: static files are served without login.
MANUAL_PATH = 'amc_management/manual/amc_user_manual.html'


class AmcDocumentation(http.Controller):

    @http.route('/amc_management/user_manual', type='http', auth='user', methods=['GET'])
    def user_manual(self, **kwargs):
        """AMC User Manual (Configuration > Documents > User Manual): self-contained HTML page
        (screenshots embedded) for AMC users only."""
        if not request.env.user.has_group('amc_management.group_amc_user'):
            return request.not_found()
        with open(file_path(MANUAL_PATH), 'rb') as handle:
            content = handle.read()
        return request.make_response(content, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'private, max-age=3600'),
            ('X-Content-Type-Options', 'nosniff'),
        ])
