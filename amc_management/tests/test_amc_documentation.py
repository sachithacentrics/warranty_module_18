from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'amc')
class TestAmcDocumentation(HttpCase):
    """TC-110: Configuration > Documents > User Manual (HTML page for AMC users only)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.amc_user = new_test_user(cls.env, login='amc_doc_user', password='amc_doc_user',
                                     groups='base.group_user,amc_management.amc_management_group_user')
        cls.employee = new_test_user(cls.env, login='amc_doc_none', password='amc_doc_none',
                                     groups='base.group_user')

    def test_tc110_user_manual_access(self):
        url = '/amc_management/user_manual'
        response = self.url_open(url, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/web/login', response.headers.get('Location', ''))
        self.authenticate('amc_doc_none', 'amc_doc_none')
        self.assertEqual(self.url_open(url).status_code, 404)
        self.authenticate('amc_doc_user', 'amc_doc_user')
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers['Content-Type'])
        self.assertIn('AMC Management – User Manual', response.text)
        self.assertIn('id="toc"', response.text)
        menu = self.env.ref('amc_management.amc_management_menu_user_manual')
        self.assertEqual(menu.parent_id, self.env.ref('amc_management.amc_management_menu_documents'))
        self.assertEqual(menu.action.url, url)

    def test_tc112_technical_architecture_access(self):
        """TC-112: Configuration > Documents > Technical Architecture (HTML page, AMC users only)."""
        url = '/amc_management/technical_architecture'
        response = self.url_open(url, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.authenticate('amc_doc_none', 'amc_doc_none')
        self.assertEqual(self.url_open(url).status_code, 404)
        self.authenticate('amc_doc_user', 'amc_doc_user')
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('AMC Management – Technical Architecture', response.text)
        self.assertIn('id="toc"', response.text)
        self.assertEqual(response.text.count('<figure class="diagram">'), 10)
        menu = self.env.ref('amc_management.amc_management_menu_technical_architecture')
        self.assertEqual(menu.parent_id, self.env.ref('amc_management.amc_management_menu_documents'))
        self.assertEqual(menu.action.url, url)

    def test_tc111_process_video_access(self):
        """TC-111: Configuration > Documents > Process Recording: player page, seekable video
        stream (HTTP range) and poster for AMC users only."""
        page, video, poster = ('/amc_management/process_video', '/amc_management/process_video/file',
                               '/amc_management/process_video/poster')
        for url in (page, video, poster):
            response = self.url_open(url, allow_redirects=False)
            self.assertIn(response.status_code, (302, 303), url)
        self.authenticate('amc_doc_none', 'amc_doc_none')
        for url in (page, video, poster):
            self.assertEqual(self.url_open(url).status_code, 404, url)
        self.authenticate('amc_doc_user', 'amc_doc_user')
        response = self.url_open(page)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="chapters"', response.text)
        self.assertIn(video, response.text)
        response = self.url_open(video, headers={'Range': 'bytes=0-1023'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers['Content-Type'], 'video/mp4')
        self.assertEqual(len(response.content), 1024)
        self.assertEqual(self.url_open(poster).headers['Content-Type'], 'image/jpeg')
        menu = self.env.ref('amc_management.amc_management_menu_process_video')
        self.assertEqual(menu.parent_id, self.env.ref('amc_management.amc_management_menu_documents'))
        self.assertEqual(menu.action.url, page)
