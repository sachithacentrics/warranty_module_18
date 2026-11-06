from datetime import date, timedelta

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, HttpCase, TransactionCase, tagged

from ..models.warranty_card import PDF_PROTECTION_PARAM, SYSTEM_PDF_TOKEN
from .common import confirm_and_group, set_installation


class DownloadCommon:
    """Confirmed warranty card of the current company; download approval required after
    1 free download; approvers Approver One / Two."""

    @classmethod
    def _user(cls, login, company=None):
        company = company or cls.company
        return cls.env['res.users'].create({
            'name': login.replace('_', ' ').title(), 'login': login, 'password': login,
            'email': '%s@example.com' % login,
            'company_id': company.id, 'company_ids': [(6, 0, company.ids)],
            'groups_id': [(6, 0, cls.env.ref('base.group_user').ids)],
        })

    @classmethod
    def _setup_download(cls):
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Other Download Company'})
        cls.requester = cls._user('wdl_requester')
        cls.approver = cls._user('wdl_approver')
        cls.approver_two = cls._user('wdl_approver_two')
        cls.outsider = cls._user('wdl_outsider')
        cls.foreign_approver = cls._user('wdl_foreign_approver', cls.other_company)
        cls.company.write({
            'warranty_scope_mode': 'warranty_only',
            'default_warranty_policy_id': False,
            'default_card_grouping_mode': 'per_so',
            'default_warranty_basis': 'period',
            'default_start_criterion': 'installation',
            'default_warranty_duration': 12,
            'default_warranty_duration_unit': 'months',
            'warranty_download_approval_required': True,
            'warranty_free_download_count': 1,
            'warranty_download_approver_ids': [(6, 0, (cls.approver | cls.approver_two).ids)],
        })
        cls.other_company.write({
            'warranty_download_approval_required': True,
            'warranty_download_approver_ids': [(6, 0, cls.foreign_approver.ids)],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Download Customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'Download AC', 'type': 'service', 'warranty_applicable': True})

    @classmethod
    def _confirmed_card(cls):
        order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [(0, 0, {'product_id': cls.product.id, 'product_uom_qty': 1})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, date(2026, 7, 1))
        card.action_confirm_warranty()
        return card

    def _pdf(self, card):
        return self.env['ir.attachment'].search([
            ('res_model', '=', 'warranty.card'), ('res_id', '=', card.id),
            ('res_field', '=', 'pdf_file')])


@tagged('post_install', '-at_install', 'warranty_download')
class TestWarrantyCardDownload(DownloadCommon, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_download()

    def setUp(self):
        super().setUp()
        self.card = self._confirmed_card()

    def _download(self, user, card=None):
        """Download PDF as `user`: the attachment delivered, or the action returned when no
        file is delivered (request dialog)."""
        card = card or self.card
        action = card.with_user(user).action_download_pdf()
        if action.get('type') != 'ir.actions.act_url':
            return action
        token = action['url'].rsplit('/', 1)[-1]
        return self.env['warranty.card.download.ticket'].with_user(user)._consume(token)

    def _request(self, user, reason='Customer lost the copy', card=None):
        action = self._download(user, card)
        self.assertEqual(action.get('res_model'), 'warranty.card.download.request.wizard')
        wizard = self.env[action['res_model']].with_user(user).with_context(
            action['context']).create({'reason': reason})
        wizard.action_submit()
        return self.env['warranty.card.download.request'].search([
            ('warranty_card_id', '=', (card or self.card).id),
            ('requested_by_id', '=', user.id)], order='id desc', limit=1)

    # ------------------------------------------------------------------ generation
    def test_01_confirmation_generates_protected_pdf(self):
        """Confirmation generates the PDF in the protected storage; Download Count 0; no
        history; not listed / readable as a normal attachment for internal users."""
        attachment = self._pdf(self.card)
        self.assertEqual(len(attachment), 1)
        self.assertEqual((attachment.mimetype, attachment.name),
                         ('application/pdf', '%s.pdf' % self.card.name.replace('/', '_')))
        self.assertEqual(self.card.pdf_attachment_id, attachment)
        self.assertEqual((self.card.print_count, len(self.card.download_log_ids)), (0, 0))
        Attachment = self.env['ir.attachment'].with_user(self.requester)
        self.assertFalse(Attachment.search([('res_model', '=', 'warranty.card'),
                                            ('res_id', '=', self.card.id)]))
        with self.assertRaises(AccessError):
            Attachment.browse(attachment.id).read(['raw'])
        with self.assertRaises(AccessError):
            self.card.with_user(self.requester).read(['pdf_file'])
        self.assertEqual(self.card.with_user(self.requester).read(['print_count'])[0]['print_count'], 0)

    # ------------------------------------------------------------------ workflow
    def test_02_first_download_free_and_ticket_single_use(self):
        """First download without approval: the stored PDF, Download Count 1, one history
        line; the ticket cannot be used again or by another user."""
        action = self.card.with_user(self.requester).action_download_pdf()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        token = action['url'].rsplit('/', 1)[-1]
        Ticket = self.env['warranty.card.download.ticket']
        with self.assertRaises(AccessError):
            Ticket.with_user(self.outsider)._consume(token)
        attachment = Ticket.with_user(self.requester)._consume(token)
        self.assertEqual(attachment.raw, self._pdf(self.card).raw)
        self.assertEqual(self.card.print_count, 1)
        log = self.card.download_log_ids
        self.assertEqual((log.download_no, log.user_id, log.request_id),
                         (1, self.requester, self.env['warranty.card.download.request']))
        with self.assertRaises(AccessError):
            Ticket.with_user(self.requester)._consume(token)
        self.assertEqual(self.card.print_count, 1, 'no duplicate counting')

    def test_03_second_download_needs_one_approval(self):
        """Second download: request with reason, approvers notified (activities); one pending
        request per user and card; one approval = one download; then a new request."""
        self._download(self.requester)
        request = self._request(self.requester)
        self.assertEqual((request.state, request.download_count_at_request, request.reason),
                         ('to_approve', 1, 'Customer lost the copy'))
        self.assertRegex(request.name, r'^WDR/\d{5}$')
        self.assertEqual(request.activity_ids.user_id, self.approver | self.approver_two)
        with self.assertRaises(UserError):
            self._download(self.requester)  # pending request
        with self.assertRaises(UserError):
            self.env['warranty.card.download.request'].with_user(self.requester)._submit(
                self.card, 'Again')
        with self.assertRaises(AccessError):
            request.with_user(self.requester).write({'state': 'approved'})

        request.with_user(self.approver).action_approve()
        self.assertEqual((request.state, request.decided_by_id), ('approved', self.approver))
        self.assertFalse(request.activity_ids, 'approver activities closed')
        attachment = self._download(self.requester)
        self.assertEqual(attachment._name, 'ir.attachment')
        self.assertEqual((self.card.print_count, request.state, request.download_no),
                         (2, 'used', 2))
        self.assertEqual(self.card.download_log_ids.sorted('download_no')[-1].request_id, request)
        # Every further download needs a new approval.
        action = self._download(self.requester)
        self.assertEqual(action['res_model'], 'warranty.card.download.request.wizard')

    def test_04_rejected(self):
        """Rejected: no download; a new request is possible."""
        self._download(self.requester)
        request = self._request(self.requester)
        request.with_user(self.approver_two).action_reject()
        self.assertEqual((request.state, request.decided_by_id), ('rejected', self.approver_two))
        self.assertEqual(self._download(self.requester)['res_model'],
                         'warranty.card.download.request.wizard')
        self.assertEqual(self.card.print_count, 1)
        second = self._request(self.requester, 'Second try')
        self.assertNotEqual(second, request)

    def test_05_who_can_decide(self):
        """Only the company's approvers, never the requester (also when configured as
        approver); other company approvers cannot see the request."""
        self.company.warranty_download_approver_ids = [(4, self.requester.id)]
        self._download(self.requester)
        request = self._request(self.requester)
        self.assertNotIn(self.requester, request.activity_ids.user_id)
        for user in (self.requester, self.outsider):
            with self.assertRaises(AccessError):
                request.with_user(user).action_approve()
        self.assertFalse(request.with_user(self.requester).can_decide)
        self.assertTrue(request.with_user(self.approver).can_decide)
        self.assertFalse(self.env['warranty.card.download.request'].with_user(
            self.foreign_approver).search([('id', '=', request.id)]))
        with self.assertRaises(AccessError):
            request.with_user(self.foreign_approver).action_approve()
        request.with_user(self.approver).write({'decision_note': 'Checked'})
        with self.assertRaises(AccessError):
            request.with_user(self.outsider).write({'decision_note': 'Me too'})
        self.assertEqual(request.state, 'to_approve')

    def test_06_ticket_rules(self):
        """Expired tickets are refused; two free tickets issued before the first download:
        the second is refused at download time; an approval is used once."""
        Ticket = self.env['warranty.card.download.ticket']
        first = self.card.with_user(self.requester).action_download_pdf()['url'].rsplit('/', 1)[-1]
        second = self.card.with_user(self.requester).action_download_pdf()['url'].rsplit('/', 1)[-1]
        Ticket.with_user(self.requester)._consume(first)
        with self.assertRaises(AccessError):
            Ticket.with_user(self.requester)._consume(second)
        self.assertEqual(self.card.print_count, 1)

        request = self._request(self.requester)
        request.with_user(self.approver).action_approve()
        late = self.card.with_user(self.requester).action_download_pdf()['url'].rsplit('/', 1)[-1]
        Ticket.sudo().search([('token', '=', late)]).expiry = \
            fields.Datetime.now() - timedelta(minutes=1)
        with self.assertRaises(AccessError):
            Ticket.with_user(self.requester)._consume(late)
        self.assertEqual(request.state, 'approved', 'still usable after an expired ticket')
        one = self.card.with_user(self.requester).action_download_pdf()['url'].rsplit('/', 1)[-1]
        two = self.card.with_user(self.requester).action_download_pdf()['url'].rsplit('/', 1)[-1]
        Ticket.with_user(self.requester)._consume(one)
        with self.assertRaises(AccessError):
            Ticket.with_user(self.requester)._consume(two)
        self.assertEqual((self.card.print_count, request.state), (2, 'used'))

    def test_07_approval_not_required_and_free_count(self):
        """Approval not required: every download allowed and recorded. Free count 2: two
        downloads without approval."""
        self.company.warranty_download_approval_required = False
        for __ in range(3):
            self._download(self.outsider)
        self.assertEqual(self.card.print_count, 3)
        self.company.write({'warranty_download_approval_required': True,
                            'warranty_free_download_count': 5})
        self._download(self.requester)
        self._download(self.requester)
        self.assertEqual(self._download(self.requester)['res_model'],
                         'warranty.card.download.request.wizard')
        self.assertEqual(sorted(self.card.download_log_ids.mapped('download_no')), [1, 2, 3, 4, 5])

    def test_08_settings(self):
        """Company settings: free count at least 1; approvers internal and allowed in the
        company; shown in the Warranty Settings block."""
        with self.assertRaises(ValidationError):
            self.company.warranty_free_download_count = 0
        with self.assertRaises(ValidationError):
            self.company.warranty_download_approver_ids = [(4, self.foreign_approver.id)]
        settings = Form(self.env['res.config.settings'])
        self.assertTrue(settings.warranty_download_approval_required)
        self.assertEqual(settings.warranty_free_download_count, 1)

    # ------------------------------------------------------------------ protection
    def test_09_report_and_file_links_protected(self):
        """The report cannot be rendered outside the system generation (also with a fake
        context value); the protected attachment / field is refused by the standard file
        links, also for administrators; normal attachments of the card are unchanged."""
        report = self.env.ref('warranty_management.action_report_warranty_card')
        Report = self.env['ir.actions.report']
        with self.assertRaises(AccessError):
            Report._render_qweb_pdf(report, self.card.ids)
        with self.assertRaises(AccessError):
            Report.with_context(warranty_card_pdf_token=True)._render_qweb_html(
                report, self.card.ids)
        Report.with_context(warranty_card_pdf_token=SYSTEM_PDF_TOKEN)._render_qweb_pdf(
            report, self.card.ids)

        Binary = self.env['ir.binary']
        with self.assertRaises(AccessError):
            Binary._record_to_stream(self._pdf(self.card), 'raw')
        with self.assertRaises(AccessError):
            Binary._record_to_stream(self.card, 'pdf_file')
        normal = self.env['ir.attachment'].create({
            'name': 'note.txt', 'raw': b'normal', 'res_model': 'warranty.card',
            'res_id': self.card.id})
        self.assertIn(normal, self.env['ir.attachment'].with_user(self.requester).search([
            ('res_model', '=', 'warranty.card'), ('res_id', '=', self.card.id)]))

    def test_10_existing_pdfs_protected_once(self):
        """D1: an existing PDF soft copy (normal attachment) is moved into the protected
        storage once: same record and content; other attachments unchanged; no download."""
        card = self._confirmed_card()
        self._pdf(card).unlink()
        legacy = self.env['ir.attachment'].create({
            'name': 'legacy.pdf', 'raw': b'%PDF legacy', 'mimetype': 'application/pdf',
            'res_model': 'warranty.card', 'res_id': card.id})
        other = self.env['ir.attachment'].create({
            'name': 'photo.png', 'raw': b'png', 'res_model': 'warranty.card', 'res_id': card.id})
        card.pdf_attachment_id = legacy
        self.env['ir.config_parameter'].sudo().set_param(PDF_PROTECTION_PARAM, False)
        self.env['warranty.card']._migrate_protect_card_pdfs()
        self.assertEqual((legacy.res_field, legacy.raw, legacy.res_id), ('pdf_file', b'%PDF legacy', card.id))
        self.assertFalse(other.res_field)
        self.assertEqual(card.print_count, 0)
        self.assertEqual(self._pdf(card), legacy)
        legacy.res_field = False
        self.env['warranty.card']._migrate_protect_card_pdfs()
        self.assertFalse(legacy.res_field, 'runs once')

    def test_11_multi_company(self):
        """History and requests of another company are not visible."""
        self._download(self.requester)
        self._request(self.requester)
        for model in ('warranty.card.download.log', 'warranty.card.download.request'):
            self.assertFalse(self.env[model].with_user(self.foreign_approver).search(
                [('warranty_card_id', '=', self.card.id)]), model)
            self.assertTrue(self.env[model].with_user(self.approver).search(
                [('warranty_card_id', '=', self.card.id)]), model)


    def test_13_single_download_history(self):
        """One Download History on the card: downloads with their approval request, and the
        requests without download yet; no separate requests section / buttons on the card;
        the request records are kept."""
        def history():
            self.card.invalidate_recordset(['download_history_ids'])
            return sorted((h.entry_type, h.download_no, h.request_state or '')
                          for h in self.card.with_user(self.requester).download_history_ids)

        self._download(self.requester)
        self.assertEqual(history(), [('download', 1, '')])
        request = self._request(self.requester, 'Lost')
        self.assertEqual(history(), [('download', 1, ''), ('request', 0, 'to_approve')])
        request.with_user(self.approver).action_approve()
        self.assertIn(('request', 0, 'approved'), history())
        self._download(self.requester)
        self.assertEqual(history(), [('download', 1, ''), ('download', 2, 'used')])
        row = self.card.download_history_ids.filtered(lambda h: h.download_no == 2)
        self.assertEqual((row.downloaded_by_id, row.requested_by_id, row.decided_by_id,
                          row.reason, row.request_id), (self.requester, self.requester,
                                                        self.approver, 'Lost', request))
        rejected = self._request(self.requester, 'Again')
        rejected.with_user(self.approver_two).action_reject()
        self.assertIn(('request', 0, 'rejected'), history())
        self.assertFalse(self.env['warranty.card.download.history'].with_user(
            self.foreign_approver).search([('warranty_card_id', '=', self.card.id)]))
        self.assertEqual(len(self.card.download_request_ids), 2, 'requests kept')

        # Approved simplification: no Download History tab on the card form (the history
        # records are kept); downloads are logged in the card chatter instead.
        arch = etree.fromstring(self.env.ref('warranty_management.warranty_card_view_form').arch)
        for name in ('download_history_ids', 'download_request_ids', 'download_log_ids'):
            self.assertFalse(arch.xpath("//field[@name='%s']" % name), name)
        self.assertFalse(arch.xpath("//page[@name='pdf_downloads']"))
        self.assertTrue(arch.xpath("//chatter"))
        self.assertFalse(arch.xpath("//button[@name='action_approve']"))

    def _download_notes(self):
        return self.card.message_ids.filtered(
            lambda m: 'Warranty card PDF downloaded' in (m.body or ''))

    def test_14_download_logged_in_chatter(self):
        """One internal note per successful download: number, user, date / time in the
        downloader's timezone (UTC without one); no email; Download Count unchanged."""
        # Start Date Automation (D11): only the start date notes (exception / activation).
        self.assertFalse(self.card.message_ids.filtered(
            lambda m: 'Warranty activated' not in (m.body or '')
            and 'start date exception' not in (m.body or '')), 'no creation note')
        self.assertFalse(self.card.message_follower_ids, 'no automatic followers')
        mails = self.env['mail.mail'].search_count([])
        self.requester.tz = False
        self._download(self.requester)
        note = self._download_notes()
        self.assertEqual(len(note), 1)
        log = self.card.download_log_ids
        self.assertIn('Download No. 1 by Wdl Requester', note.body)
        self.assertIn('(UTC)', note.body)
        self.assertIn(log.download_date.strftime('%H:%M'), note.body)
        self.assertEqual((note.author_id, note.message_type, note.subtype_id),
                         (self.requester.partner_id, 'notification',
                          self.env.ref('mail.mt_note')))
        self.assertEqual(self.env['mail.mail'].search_count([]), mails, 'no email')
        self.assertEqual(self.card.print_count, 1)

    def test_15_download_note_timezone(self):
        """The time is written in the downloading user's timezone."""
        import pytz
        self.requester.tz = 'Asia/Colombo'
        self._download(self.requester)
        log = self.card.download_log_ids
        local = pytz.utc.localize(log.download_date).astimezone(pytz.timezone('Asia/Colombo'))
        body = self._download_notes().body
        self.assertIn('at %s (Asia/Colombo)' % local.strftime('%H:%M'), body)

    def test_16_no_note_on_retry_or_refusal(self):
        """A retried link and a refused download log nothing; the next approved download
        gets its own note (No. 2)."""
        action = self.card.with_user(self.requester).action_download_pdf()
        token = action['url'].rsplit('/', 1)[-1]
        Ticket = self.env['warranty.card.download.ticket'].with_user(self.requester)
        Ticket._consume(token)
        with self.assertRaises(AccessError):
            Ticket._consume(token)
        self.assertEqual((len(self._download_notes()), self.card.print_count), (1, 1))
        # Free downloads used: the next click opens the request dialog, no download.
        self.assertEqual(self._download(self.requester).get('res_model'),
                         'warranty.card.download.request.wizard')
        self.assertEqual(len(self._download_notes()), 1)
        request = self._request(self.requester)
        request.with_user(self.approver).action_approve()
        self._download(self.requester)
        notes = self._download_notes()
        self.assertEqual(len(notes), 2)
        self.assertIn('Download No. 2', notes[0].body)
        self.assertEqual(self.card.print_count, 2)

@tagged('post_install', '-at_install', 'warranty_download')
class TestWarrantyCardDownloadHttp(DownloadCommon, HttpCase):
    """URL level: standard file links and report URLs refuse the protected PDF; the ticket
    link delivers it once; normal attachments still download."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_download()
        cls.card = cls._confirmed_card()

    def test_12_urls(self):
        attachment = self._pdf(self.card)
        normal = self.env['ir.attachment'].create({
            'name': 'note.txt', 'raw': b'normal file', 'res_model': 'warranty.card',
            'res_id': self.card.id})
        for login in ('wdl_requester', 'admin'):
            self.authenticate(login, login)
            for url in ('/web/content/%s' % attachment.id,
                        '/web/content/%s?download=true' % attachment.id,
                        '/web/content?model=ir.attachment&id=%s&field=raw' % attachment.id,
                        '/web/content?model=warranty.card&id=%s&field=pdf_file' % self.card.id,
                        '/report/pdf/warranty_management.report_warranty_card/%s' % self.card.id,
                        '/report/html/warranty_management.report_warranty_card/%s' % self.card.id):
                response = self.url_open(url)
                self.assertNotEqual(response.status_code, 200, (login, url))
                self.assertNotIn(attachment.raw[:20], response.content, (login, url))
        self.authenticate('wdl_requester', 'wdl_requester')
        self.assertEqual(self.url_open('/web/content/%s' % normal.id).content, b'normal file')

        action = self.card.with_user(self.requester).action_download_pdf()
        count, stored = self.card.print_count, attachment.raw
        response = self.url_open(action['url'])
        self.assertEqual(response.status_code, 200)
        # Rendered now with the current report (HTML in test mode); nothing stored changes.
        self.assertIn(b'WARRANTY CERTIFICATE', response.content)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertIn(attachment.name, response.headers['Content-Disposition'])
        self.env.invalidate_all()
        self.assertEqual(attachment.raw, stored, 'the stored PDF stays as it is')
        self.assertEqual(self.card.print_count, count + 1, 'the download is recorded once')
        self.assertNotEqual(self.url_open(action['url']).status_code, 200, 'single-use ticket')
        self.assertEqual(self.card.print_count, count + 1)
        self.assertIn('attachment', response.headers.get('Content-Disposition', ''))
        self.assertNotEqual(self.url_open(action['url']).status_code, 200, 'single use')
        self.authenticate('wdl_outsider', 'wdl_outsider')
        action = self.card.with_user(self.outsider).action_download_pdf()
        self.assertEqual(action['res_model'], 'warranty.card.download.request.wizard')
        self.assertEqual(self.card.print_count, 1)
