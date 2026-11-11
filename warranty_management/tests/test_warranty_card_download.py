from datetime import date, timedelta
from unittest.mock import patch

from lxml import etree

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

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
        if action.get('tag') != 'warranty_card_download_pdf':
            return action
        token = action['params']['url'].rsplit('/', 1)[-1]
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
        self.assertEqual((action['type'], action['tag']),
                         ('ir.actions.client', 'warranty_card_download_pdf'))
        token = action['params']['url'].rsplit('/', 1)[-1]
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
        first = self.card.with_user(self.requester).action_download_pdf()['params']['url'].rsplit('/', 1)[-1]
        second = self.card.with_user(self.requester).action_download_pdf()['params']['url'].rsplit('/', 1)[-1]
        Ticket.with_user(self.requester)._consume(first)
        with self.assertRaises(AccessError):
            Ticket.with_user(self.requester)._consume(second)
        self.assertEqual(self.card.print_count, 1)

        request = self._request(self.requester)
        request.with_user(self.approver).action_approve()
        late = self.card.with_user(self.requester).action_download_pdf()['params']['url'].rsplit('/', 1)[-1]
        Ticket.sudo().search([('token', '=', late)]).expiry = \
            fields.Datetime.now() - timedelta(minutes=1)
        with self.assertRaises(AccessError):
            Ticket.with_user(self.requester)._consume(late)
        self.assertEqual(request.state, 'approved', 'still usable after an expired ticket')
        one = self.card.with_user(self.requester).action_download_pdf()['params']['url'].rsplit('/', 1)[-1]
        two = self.card.with_user(self.requester).action_download_pdf()['params']['url'].rsplit('/', 1)[-1]
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
        token = action['params']['url'].rsplit('/', 1)[-1]
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

    # ------------------------------------------------------------------ Send to Customer
    def _composer(self, user):
        action = self.card.with_user(user).action_send_warranty_card()
        self.assertEqual(action['res_model'], 'mail.compose.message')
        return self.env['mail.compose.message'].with_user(user).with_context(
            action['context']).create({})

    def test_17_send_to_customer_composer(self):
        """The standard composer: template, customer with an email as recipient, the stored
        soft copy attached (a protected copy); no download is recorded."""
        self.partner.email = 'customer@example.com'
        composer = self._composer(self.requester)
        self.assertEqual(composer.template_id,
                         self.env.ref('warranty_management.mail_template_warranty_card'))
        self.assertEqual(composer.partner_ids, self.partner)
        self.assertIn(self.card.name, composer.subject)
        attachment = composer.attachment_ids
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment.name, self._pdf(self.card).name)
        self.assertEqual(attachment.sudo().raw, self._pdf(self.card).raw)
        self.assertTrue(attachment.sudo().warranty_card_pdf_copy)
        composer.action_send_mail()
        message = self.card.message_ids.filtered(
            lambda m: m.message_type == 'comment' and m.attachment_ids)[:1]
        self.assertEqual(message.partner_ids, self.partner)
        self.assertEqual(message.attachment_ids, attachment)
        self.assertEqual(attachment.sudo().res_model, 'warranty.card')
        mail = self.env['mail.mail'].sudo().search([('mail_message_id', '=', message.id)])
        self.assertEqual(mail.attachment_ids, attachment)
        self.assertEqual((self.card.print_count, len(self.card.download_log_ids)), (0, 0))
        self.assertFalse(self.env['warranty.card.download.request'].search([
            ('warranty_card_id', '=', self.card.id)]))
        self.assertEqual(len(self._pdf(self.card)), 1, 'the stored soft copy stays as it is')

    def test_18_send_to_customer_without_email_and_after_downloads(self):
        """No email: no recipient is preselected. After the free download (approval needed
        for the next print) sending still needs no approval and counts nothing."""
        self.partner.email = False
        self.assertFalse(self._composer(self.requester).partner_ids)
        self._download(self.requester)
        self.partner.email = 'customer@example.com'
        composer = self._composer(self.requester)
        self.assertEqual(composer.partner_ids, self.partner)
        composer.action_send_mail()
        self.assertEqual((self.card.print_count, len(self.card.download_log_ids)), (1, 1))
        self.card.state = 'draft'
        with self.assertRaises(UserError):
            self.card.with_user(self.requester).action_send_warranty_card()

    def test_19_emailed_copy_content_administrators_only(self):
        """The emailed copy in the chatter: a user who can read the card sees it listed but
        cannot read its content; administrators and system code (email sending) can."""
        self.partner.email = 'customer@example.com'
        composer = self._composer(self.requester)
        attachment = composer.attachment_ids
        composer.action_send_mail()
        stored = self._pdf(self.card).raw
        listed = self.env['ir.attachment'].with_user(self.requester).browse(attachment.id)
        self.assertEqual(listed.read(['name', 'mimetype'])[0]['name'], attachment.sudo().name)
        for field in ('raw', 'datas'):
            listed.invalidate_recordset()
            with self.assertRaises(AccessError):
                listed.read([field])
        sysadmin = self._user('wdl_sysadmin')
        sysadmin.groups_id |= self.env.ref('base.group_system')
        self.assertEqual(attachment.with_user(sysadmin).raw, stored)
        self.assertEqual(attachment.sudo().raw, stored)

    # ------------------------------------------------------------------ list view
    def test_20_list_serial_numbers(self):
        """Warranty Cards list: Serial Number(s) next to Product, from the card's units in unit
        order; searchable by serial. No serial: empty."""
        arch = etree.fromstring(self.env['warranty.card'].get_view(view_type='list')['arch'])
        columns = [field.get('name') for field in arch.xpath('/list/field')]
        self.assertEqual(columns[columns.index('product_id') + 1], 'unit_serial_numbers')
        for name in ('name', 'partner_id', 'product_id', 'state'):
            self.assertIn(name, columns)
        self.assertFalse(self.card.unit_serial_numbers)

        tracked = self.env['product.product'].create({
            'name': 'Serial AC', 'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'warranty_applicable': True})
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': tracked.id, 'product_uom_qty': 2})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        units = card.unit_warranty_ids.sorted('unit_number')
        self.assertEqual(len(units), 2)
        lots = self.env['stock.lot'].create([{'name': name, 'product_id': tracked.id}
                                             for name in ('SN-LIST-B', 'SN-LIST-A')])
        units[0].serial_ids = lots[0]
        self.assertEqual(card.unit_serial_numbers, 'SN-LIST-B')
        units[1].serial_ids = lots[1]
        # Display only (not stored): the list computes it on each read.
        card.invalidate_recordset(['unit_serial_numbers'])
        self.assertEqual(card.unit_serial_numbers, 'SN-LIST-B, SN-LIST-A')
        self.assertEqual(self.env['warranty.card'].search(
            [('unit_warranty_ids.serial_ids.name', 'ilike', 'SN-LIST-A')]), card)

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
        # The emailed copy (Send to Customer): administrators only, also in a chatter zip.
        emailed = self.env['ir.attachment'].create({
            'name': attachment.name, 'raw': attachment.raw, 'res_model': 'warranty.card',
            'res_id': self.card.id, 'warranty_card_pdf_copy': True})
        sysadmin = self._user('wdl_sysadmin')
        sysadmin.groups_id |= self.env.ref('base.group_system')
        urls = ('/web/content/%s' % emailed.id, '/web/content/%s?download=true' % emailed.id)
        self.authenticate('wdl_requester', 'wdl_requester')
        for url in urls:
            response = self.url_open(url)
            self.assertNotEqual(response.status_code, 200, url)
            self.assertNotIn(attachment.raw[:20], response.content, url)
        response = self.url_open('/mail/attachment/zip', data={
            'file_ids': str(emailed.id), 'zip_name': 'cards.zip',
            'csrf_token': http.Request.csrf_token(self)})
        self.assertNotIn(attachment.raw[:20], response.content, 'zip')
        self.authenticate('wdl_sysadmin', 'wdl_sysadmin')
        for url in urls:
            response = self.url_open(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertEqual(response.content, attachment.raw, url)
        self.authenticate('wdl_requester', 'wdl_requester')

        action = self.card.with_user(self.requester).action_download_pdf()
        count, stored = self.card.print_count, attachment.raw
        response = self.url_open(action['params']['url'])
        self.assertEqual(response.status_code, 200)
        # Rendered now with the current report (HTML in test mode); nothing stored changes.
        self.assertIn(b'WARRANTY CERTIFICATE', response.content)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertIn(attachment.name, response.headers['Content-Disposition'])
        self.env.invalidate_all()
        self.assertEqual(attachment.raw, stored, 'the stored PDF stays as it is')
        self.assertEqual(self.card.print_count, count + 1, 'the download is recorded once')
        self.assertNotEqual(self.url_open(action['params']['url']).status_code, 200, 'single-use ticket')
        self.assertEqual(self.card.print_count, count + 1)
        self.assertIn('attachment', response.headers.get('Content-Disposition', ''))
        self.assertNotEqual(self.url_open(action['params']['url']).status_code, 200, 'single use')
        self.authenticate('wdl_outsider', 'wdl_outsider')
        action = self.card.with_user(self.outsider).action_download_pdf()
        self.assertEqual(action['res_model'], 'warranty.card.download.request.wizard')
        self.assertEqual(self.card.print_count, 1)

    def test_13_form_shows_the_download_without_refresh(self):
        """Download PDF in the web client: one ticket request, then the form shows the new
        Download Count and the chatter note without a browser refresh."""
        card = self._confirmed_card()
        # The form shows the order lines: a sales user opens it.
        self.requester.groups_id |= self.env.ref('sales_team.group_sale_salesman_all_leads')
        code = """(async () => {
            const wait = async (check, label) => {
                for (let i = 0; i < 300; i++) {
                    if (check()) { return; }
                    await new Promise((resolve) => setTimeout(resolve, 100));
                }
                throw new Error('timeout: ' + label + ' at ' + location.href + ': '
                                + document.body.innerText.slice(0, 300));
            };
            let requests = 0;
            const open = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function (method, url) {
                if (String(url).includes('/warranty/card/pdf/')) { requests++; }
                return open.apply(this, arguments);
            };
            const count = () => document.querySelector('div[name=print_count]')?.textContent.trim();
            const tab = () => document.querySelector('a[name=other_information]');
            await wait(() => document.querySelector('button[name=action_download_pdf]') && tab(), 'form');
            tab().click();
            await wait(() => count() === '0', 'Other Information');
            document.querySelector('button[name=action_download_pdf]').click();
            await wait(() => count() === '1', 'Download Count');
            await wait(() => [...document.querySelectorAll('.o-mail-Message')].some(
                (message) => message.textContent.includes('Download No. 1')), 'chatter');
            if (requests !== 1) { throw new Error('PDF requests: ' + requests); }
            console.log('test successful');
        })().catch((error) => console.error(error.message));"""
        self.browser_js('/odoo/warranty.card/%s' % card.id, code, login='wdl_requester',
                        timeout=90)
        self.assertEqual((card.print_count, len(card.download_log_ids)), (1, 1))

    # ------------------------------------------------------------------ Duplicate Copy (SRS 9.10)
    def _http_download(self, card):
        action = card.with_user(self.requester).action_download_pdf()
        response = self.url_open(action['params']['url'])
        self.env.invalidate_all()
        return response

    def _approved_request(self, card):
        action = card.with_user(self.requester).action_download_pdf()
        self.assertEqual(action.get('res_model'), 'warranty.card.download.request.wizard')
        self.env[action['res_model']].with_user(self.requester).with_context(
            action['context']).create({'reason': 'Customer lost the copy'}).action_submit()
        request = self.env['warranty.card.download.request'].search([
            ('warranty_card_id', '=', card.id)], order='id desc', limit=1)
        request.with_user(self.approver).action_approve()
        return request

    def test_14_duplicate_copy_from_print_no_2(self):
        """Print No. 1 has no label; the approved Print No. 2 is a Duplicate Copy; the stored
        soft copy stays without it; one count and one history line per download."""
        card = self._confirmed_card()
        stored = self._pdf(card).raw
        self.authenticate('wdl_requester', 'wdl_requester')
        first = self._http_download(card)
        self.assertEqual(first.status_code, 200)
        self.assertIn(b'WARRANTY CERTIFICATE', first.content)
        self.assertNotIn(b'DUPLICATE COPY', first.content)
        request = self._approved_request(card)
        second = self._http_download(card)
        self.assertEqual(second.status_code, 200)
        self.assertIn('DUPLICATE COPY – Print No. 2'.encode(), second.content)
        self.assertEqual((card.print_count, len(card.download_log_ids)), (2, 2))
        self.assertEqual((request.state, request.download_log_id.download_no), ('used', 2))
        self.assertEqual(self._pdf(card).raw, stored)
        self.assertNotIn(b'DUPLICATE COPY', stored)

    def test_15_duplicate_copy_without_approval(self):
        """The label follows the print sequence, also when the company needs no approval."""
        self.company.warranty_download_approval_required = False
        card = self._confirmed_card()
        self.authenticate('wdl_requester', 'wdl_requester')
        self.assertNotIn(b'DUPLICATE COPY', self._http_download(card).content)
        self.assertIn('DUPLICATE COPY – Print No. 2'.encode(), self._http_download(card).content)
        self.assertIn('DUPLICATE COPY – Print No. 3'.encode(), self._http_download(card).content)
        self.assertEqual((card.print_count, len(card.download_log_ids)), (3, 3))

    def test_16_failed_rendering_records_nothing(self):
        """A rendering failure rolls back the download: no count, no history, no chatter note,
        the approval is not used; the next download is Print No. 2."""
        card = self._confirmed_card()
        self.authenticate('wdl_requester', 'wdl_requester')
        self._http_download(card)
        request = self._approved_request(card)
        notes = len(card.message_ids)
        action = card.with_user(self.requester).action_download_pdf()
        with patch.object(type(self.env['warranty.card']), '_warranty_render_pdf',
                          side_effect=UserError('Rendering failed')), mute_logger('odoo.http'):
            response = self.url_open(action['params']['url'])
        self.env.invalidate_all()
        self.assertNotEqual(response.status_code, 200)
        self.assertEqual((card.print_count, len(card.download_log_ids), request.state),
                         (1, 1, 'approved'))
        self.assertEqual(len(card.message_ids), notes)
        retry = self._http_download(card)
        self.assertIn('DUPLICATE COPY – Print No. 2'.encode(), retry.content)
        self.assertEqual((card.print_count, request.state), (2, 'used'))
