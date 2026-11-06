from odoo import http
from odoo.http import Stream, request
from odoo.tools.misc import file_path

# Kept outside /static on purpose: static files are served without login.
MANUAL_DIR = 'amc_management/manual/'
USER_MANUAL = MANUAL_DIR + 'amc_user_manual.html'
TECHNICAL_ARCHITECTURE = MANUAL_DIR + 'amc_technical_architecture.html'
VIDEO_PAGE = MANUAL_DIR + 'amc_process_video.html'
VIDEO_FILE = MANUAL_DIR + 'amc_process.mp4'
VIDEO_POSTER = MANUAL_DIR + 'amc_process_poster.jpg'
PAGE_HEADERS = [
    ('Content-Type', 'text/html; charset=utf-8'),
    ('Cache-Control', 'private, max-age=3600'),
    ('X-Content-Type-Options', 'nosniff'),
]


class AmcDocumentation(http.Controller):
    """Configuration > Documents: User Manual, Technical Architecture and Process Recording, for
    AMC users only."""

    def _amc_allowed(self):
        return request.env.user.has_group('amc_management.group_amc_user')

    def _amc_page(self, path):
        if not self._amc_allowed():
            return request.not_found()
        with open(file_path(path), 'rb') as handle:
            return request.make_response(handle.read(), headers=PAGE_HEADERS)

    def _amc_stream(self, path):
        """Private, conditional stream (HTTP range requests: the player can seek / jump to a
        chapter without downloading the whole video)."""
        if not self._amc_allowed():
            return request.not_found()
        stream = Stream.from_path(path, public=False)
        return stream.get_response(content_security_policy=None)

    @http.route('/amc_management/user_manual', type='http', auth='user', methods=['GET'])
    def user_manual(self, **kwargs):
        """Self-contained HTML user manual (screenshots embedded)."""
        return self._amc_page(USER_MANUAL)

    @http.route('/amc_management/technical_architecture', type='http', auth='user',
                methods=['GET'])
    def technical_architecture(self, **kwargs):
        """Self-contained HTML version of AMC_Technical_Architecture.docx (diagrams embedded)."""
        return self._amc_page(TECHNICAL_ARCHITECTURE)

    @http.route('/amc_management/process_video', type='http', auth='user', methods=['GET'])
    def process_video(self, **kwargs):
        """Player page of the complete AMC process recording, with chapters."""
        return self._amc_page(VIDEO_PAGE)

    @http.route('/amc_management/process_video/file', type='http', auth='user', methods=['GET'])
    def process_video_file(self, **kwargs):
        return self._amc_stream(VIDEO_FILE)

    @http.route('/amc_management/process_video/poster', type='http', auth='user', methods=['GET'])
    def process_video_poster(self, **kwargs):
        return self._amc_stream(VIDEO_POSTER)
