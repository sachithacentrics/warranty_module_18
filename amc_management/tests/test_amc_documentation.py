from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'amc')
class TestAmcDocumentation(HttpCase):
    """TC-110: Configuration > Documents > User Manual (HTML page for AMC users only)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.amc_user = new_test_user(cls.env, login='amc_doc_user', password='amc_doc_user',
                                     groups='base.group_user,amc_management.group_amc_user')
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
        menu = self.env.ref('amc_management.menu_amc_user_manual')
        self.assertEqual(menu.parent_id, self.env.ref('amc_management.menu_amc_documents'))
        self.assertEqual(menu.action.url, url)
