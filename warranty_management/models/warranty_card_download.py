import secrets
from datetime import timedelta

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError

# Approved D3: a download ticket is single-use and valid for 10 minutes.
TICKET_VALIDITY = timedelta(minutes=10)


class WarrantyCardDownloadLog(models.Model):
    """Download History: one line per authorized warranty card PDF download (the PDF
    generated at warranty confirmation is not a download)."""
    _name = 'warranty.card.download.log'
    _description = 'Warranty Card PDF Download History'
    _order = 'download_date desc, id desc'

    warranty_card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', required=True, ondelete='cascade',
        index=True, readonly=True)
    company_id = fields.Many2one(
        related='warranty_card_id.company_id', string='Company', store=True, index=True)
    user_id = fields.Many2one('res.users', string='Downloaded By', required=True, readonly=True)
    download_date = fields.Datetime(string='Download Date', required=True, readonly=True)
    download_no = fields.Integer(string='Download Count', required=True, readonly=True)
    request_id = fields.Many2one(
        'warranty.card.download.request', string='Approval Request', readonly=True,
        ondelete='restrict')
    ticket_id = fields.Many2one(
        'warranty.card.download.ticket', string='Download Ticket', readonly=True,
        ondelete='set null')

    _sql_constraints = [
        # Prevents counting one ticket twice (e.g. two simultaneous calls of the link).
        ('ticket_unique', 'UNIQUE (ticket_id)', 'A download ticket can only be used once.'),
        ('card_download_no_unique', 'UNIQUE (warranty_card_id, download_no)',
         'Download numbers are unique per warranty card.'),
    ]


class WarrantyCardDownloadRequest(models.Model):
    """Download Approval Request (approved D2 / D4): one approval authorizes exactly one
    download of the requester; the requester never approves their own request."""
    _name = 'warranty.card.download.request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Warranty Card PDF Download Approval Request'
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default='New')
    warranty_card_id = fields.Many2one(
        'warranty.card', string='Warranty Card', required=True, ondelete='cascade',
        index=True, readonly=True)
    company_id = fields.Many2one(
        related='warranty_card_id.company_id', string='Company', store=True, index=True)
    partner_id = fields.Many2one(related='warranty_card_id.partner_id', string='Customer')
    requested_by_id = fields.Many2one(
        'res.users', string='Requested By', required=True, readonly=True, index=True)
    request_date = fields.Datetime(string='Request Date', required=True, readonly=True)
    reason = fields.Text(string='Reason', required=True, readonly=True)
    state = fields.Selection([
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('used', 'Used'),
    ], string='Approval Status', default='to_approve', required=True, readonly=True,
        tracking=True, index=True)
    decided_by_id = fields.Many2one(
        'res.users', string='Approved / Rejected By', readonly=True, tracking=True)
    decision_date = fields.Datetime(string='Approval Date', readonly=True)
    decision_note = fields.Text(string='Approver Note')
    download_count_at_request = fields.Integer(
        string='Download Count at Request', readonly=True)
    download_log_id = fields.Many2one(
        'warranty.card.download.log', string='Download', readonly=True)
    download_no = fields.Integer(
        related='download_log_id.download_no', string='Download No.')
    can_decide = fields.Boolean(compute='_compute_can_decide')

    @api.depends_context('uid')
    @api.depends('state', 'requested_by_id', 'company_id.warranty_download_approver_ids')
    def _compute_can_decide(self):
        for request in self:
            request.can_decide = request.state == 'to_approve' and request._is_approver()

    def _is_approver(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        return user != self.requested_by_id \
            and user in self.company_id.warranty_download_approver_ids

    def write(self, vals):
        # Status changes only through the actions (sudo); users may only edit the note of a
        # request they can decide.
        if not self.env.su:
            if set(vals) - {'decision_note'} or not all(r.can_decide for r in self):
                raise AccessError(_(
                    "Download approval requests can only be changed with Approve / Reject by "
                    "an authorized approver."))
        return super().write(vals)

    @api.model
    def _submit(self, card, reason):
        """Create the request of the current user for `card` (approved D2: one pending
        request per user and card) and notify the approvers of the card company."""
        card.check_access('read')
        if not (reason or '').strip():
            raise UserError(_("A reason is required to request a download approval."))
        if not card._download_approval_needed():
            raise UserError(_("The PDF of %s can be downloaded without approval.", card.name))
        Request = self.sudo()
        if Request.search_count([('warranty_card_id', '=', card.id),
                                 ('requested_by_id', '=', self.env.uid),
                                 ('state', 'in', ('to_approve', 'approved'))]):
            raise UserError(_(
                "You already have an open download approval request for %s.", card.name))
        approvers = card.company_id.warranty_download_approver_ids - self.env.user
        if not approvers:
            raise UserError(_(
                "No Download Approval Responsible User other than you is configured for "
                "%s.", card.company_id.name))
        # sudo: requests are created by the system (users cannot create or edit them).
        request = Request.create({
            'name': self.env['ir.sequence'].with_company(card.company_id).next_by_code(
                'warranty.card.download.request') or 'New',
            'warranty_card_id': card.id,
            'requested_by_id': self.env.uid,
            'request_date': fields.Datetime.now(),
            'reason': reason.strip(),
            'download_count_at_request': card.print_count,
        })
        for approver in approvers:
            request.activity_schedule(
                'mail.mail_activity_data_todo', user_id=approver.id,
                summary=_("Approve warranty card PDF download %s", card.name),
                note=request.reason)
        return request

    def action_approve(self):
        return self._decide('approved')

    def action_reject(self):
        return self._decide('rejected')

    def _decide(self, state):
        for request in self:
            if request.state != 'to_approve':
                raise UserError(_("Request %s is not waiting for approval.", request.name))
            if self.env.user == request.requested_by_id:
                raise AccessError(_("You cannot approve or reject your own request."))
            if not request._is_approver():
                raise AccessError(_(
                    "Only the Download Approval Responsible Users of %s can approve or reject "
                    "request %s.", request.company_id.name, request.name))
            request = request.sudo()
            request.write({
                'state': state,
                'decided_by_id': self.env.uid,
                'decision_date': fields.Datetime.now(),
            })
            request.activity_ids.action_feedback(feedback=_(
                "Approved by %s", self.env.user.name) if state == 'approved'
                else _("Rejected by %s", self.env.user.name))
            request.message_post(
                body=_("Download request approved: you can download the PDF once.")
                if state == 'approved' else _("Download request rejected."),
                partner_ids=request.requested_by_id.partner_id.ids,
                subtype_xmlid='mail.mt_comment')
        return True


class WarrantyCardDownloadTicket(models.Model):
    """Single-use download ticket (approved D3): issued by Download PDF for the current
    user and card, valid 10 minutes; the download is counted when the file is sent."""
    _name = 'warranty.card.download.ticket'
    _description = 'Warranty Card PDF Download Ticket'

    token = fields.Char(required=True, readonly=True, index=True, copy=False)
    warranty_card_id = fields.Many2one(
        'warranty.card', required=True, ondelete='cascade', readonly=True)
    company_id = fields.Many2one(
        related='warranty_card_id.company_id', store=True, index=True)
    user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='cascade')
    request_id = fields.Many2one(
        'warranty.card.download.request', readonly=True, ondelete='cascade')
    expiry = fields.Datetime(required=True, readonly=True)
    used = fields.Boolean(readonly=True)

    _sql_constraints = [('token_unique', 'UNIQUE (token)', 'Download tokens are unique.')]

    @api.model
    def _issue(self, card, request):
        # sudo: tickets are system records (no user access).
        return self.sudo().create({
            'token': secrets.token_urlsafe(32),
            'warranty_card_id': card.id,
            'user_id': self.env.uid,
            'request_id': request.id,
            'expiry': fields.Datetime.now() + TICKET_VALIDITY,
        })

    @api.model
    def _consume(self, token):
        """Validate the ticket of the current user, record the download and return the
        protected PDF attachment (sudo). Every check is repeated here: the free downloads may
        have been used meanwhile, the request must still be approved."""
        ticket = self.sudo().search([('token', '=', token or '')], limit=1)
        if not ticket or ticket.user_id != self.env.user:
            raise AccessError(_("This download link is not valid for you."))
        card = ticket.warranty_card_id
        # Serialize the downloads of the card: no duplicate counting or numbering.
        self.env.cr.execute(
            "SELECT id FROM warranty_card WHERE id = %s FOR UPDATE", [card.id])
        self.env.cr.execute(
            "SELECT id FROM warranty_card_download_ticket WHERE id = %s FOR UPDATE", [ticket.id])
        ticket.invalidate_recordset(['used'])
        if ticket.used:
            raise AccessError(_("This download link has already been used."))
        if ticket.expiry < fields.Datetime.now():
            raise AccessError(_("This download link has expired; use Download PDF again."))
        card.with_user(self.env.user).check_access('read')
        card = card.with_user(self.env.user)
        card.invalidate_recordset(['print_count'])
        request = ticket.request_id
        if request:
            if request.state != 'approved' or request.requested_by_id != self.env.user:
                raise AccessError(_("The download approval %s is no longer valid.",
                                    request.name))
        elif card._download_approval_needed():
            raise AccessError(_("A download approval is required for %s.", card.name))
        attachment = card._get_pdf_attachment()
        log = self.env['warranty.card.download.log'].sudo().create({
            'warranty_card_id': card.id,
            'user_id': self.env.uid,
            'download_date': fields.Datetime.now(),
            'download_no': card.print_count + 1,
            'request_id': request.id,
            'ticket_id': ticket.id,
        })
        ticket.used = True
        if request:
            request.write({'state': 'used', 'download_log_id': log.id})
        return attachment

    @api.autovacuum
    def _gc_download_tickets(self):
        self.sudo().search([('expiry', '<', fields.Datetime.now() - timedelta(days=1))]).unlink()


class WarrantyCardDownloadHistory(models.Model):
    """Download History of the warranty card (read-only report): every download with its
    approval request, and the requests that did not lead to a download yet (to approve,
    approved, rejected). Built on the download log and the requests, which keep all the
    records for audit; nothing is stored here."""
    _name = 'warranty.card.download.history'
    _description = 'Warranty Card PDF Download History'
    _auto = False
    _order = 'event_date desc, id desc'

    warranty_card_id = fields.Many2one('warranty.card', string='Warranty Card', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    entry_type = fields.Selection([
        ('download', 'Download'),
        ('request', 'Approval Request'),
    ], string='Entry', readonly=True)
    event_date = fields.Datetime(string='Date', readonly=True)
    download_no = fields.Integer(string='Download Count', readonly=True)
    downloaded_by_id = fields.Many2one('res.users', string='Downloaded By', readonly=True)
    download_date = fields.Datetime(string='Download Date', readonly=True)
    request_id = fields.Many2one(
        'warranty.card.download.request', string='Approval Request', readonly=True)
    request_state = fields.Selection([
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('used', 'Used'),
    ], string='Approval Status', readonly=True)
    requested_by_id = fields.Many2one('res.users', string='Requested By', readonly=True)
    request_date = fields.Datetime(string='Request Date', readonly=True)
    reason = fields.Text(string='Reason', readonly=True)
    decided_by_id = fields.Many2one('res.users', string='Approved / Rejected By', readonly=True)
    decision_date = fields.Datetime(string='Approval Date', readonly=True)

    @api.model
    def _search(self, domain, *args, **kwargs):
        # The SQL view reads the log / request tables: write their pending changes first.
        self.env['warranty.card.download.log'].flush_model()
        self.env['warranty.card.download.request'].flush_model()
        return super()._search(domain, *args, **kwargs)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT log.id * 2 AS id, log.warranty_card_id, log.company_id,
                       'download' AS entry_type, log.download_date AS event_date,
                       log.download_no, log.user_id AS downloaded_by_id, log.download_date,
                       log.request_id, req.state AS request_state, req.requested_by_id,
                       req.request_date, req.reason, req.decided_by_id, req.decision_date
                  FROM warranty_card_download_log log
             LEFT JOIN warranty_card_download_request req ON req.id = log.request_id
                 UNION ALL
                SELECT req.id * 2 + 1 AS id, req.warranty_card_id, req.company_id,
                       'request' AS entry_type, req.request_date AS event_date,
                       NULL AS download_no, NULL AS downloaded_by_id, NULL AS download_date,
                       req.id AS request_id, req.state AS request_state, req.requested_by_id,
                       req.request_date, req.reason, req.decided_by_id, req.decision_date
                  FROM warranty_card_download_request req
                 WHERE req.download_log_id IS NULL
            )""")
