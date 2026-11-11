from odoo import _, fields, models, tools

HISTORY_ENTITIES = [
    ('card', 'Warranty Card'),
    ('unit', 'Unit Warranty'),
    ('action', 'Controlled Action'),
    ('date', 'Warranty Dates'),
    ('service', 'Free Service'),
    ('download', 'PDF Download'),
    ('invoice', 'Invoice / Credit Note'),
    ('case', 'Warranty Case'),
    ('job', 'Service Job'),
    ('material', 'Material Request'),
    ('repair', 'Repair'),
    ('replacement', 'Replacement'),
    ('backup', 'Backup Unit'),
    ('claim', 'Vendor Claim'),
    ('cost', 'Warranty Cost'),
    ('accounting', 'Journal Entry'),
]


class WarrantyHistory(models.Model):
    """Warranty History (SRS 2.13, 15; Part 5 D17): read-only view over the records that already
    keep the facts. Nothing is copied, so it cannot differ from them. Each module adds its own
    records with _warranty_history_queries()."""
    _name = 'warranty.history'
    _description = 'Warranty History'
    _auto = False
    _order = 'event_date desc, id desc'

    card_id = fields.Many2one('warranty.card', string='Warranty Card', readonly=True)
    unit_id = fields.Many2one('warranty.unit', string='Unit Warranty', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    entity = fields.Selection(HISTORY_ENTITIES, string='Entity', readonly=True)
    event_type = fields.Char(string='Event', readonly=True)
    event_date = fields.Datetime(string='Date', readonly=True)
    user_id = fields.Many2one('res.users', string='User', readonly=True)
    reference = fields.Char(string='Reference', readonly=True)
    summary = fields.Text(string='Details', readonly=True)
    # The record the row comes from, opened from the report.
    res_model = fields.Char(string='Source Model', readonly=True)
    res_id = fields.Integer(string='Source ID', readonly=True)

    def _warranty_history_queries(self):
        """SELECTs of: card_id, unit_id, company_id, entity, event_type, event_date, user_id,
        reference, summary, res_model, res_id."""
        return [
            """SELECT c.id, NULL::integer, c.company_id, 'card', 'Card created', c.create_date,
                      c.create_uid, c.name, NULL::text, 'warranty.card', c.id
                 FROM warranty_card c""",
            """SELECT u.warranty_card_id, u.id, c.company_id, 'unit', 'Unit warranty created',
                      u.create_date, u.create_uid, u.name, NULL::text, 'warranty.unit', u.id
                 FROM warranty_unit u
                 JOIN warranty_card c ON c.id = u.warranty_card_id""",
            """SELECT a.card_id, r.unit_id, c.company_id, 'action',
                      initcap(replace(a.action_type, '_', ' ')) || ': ' || initcap(a.state),
                      COALESCE(a.decision_date, a.request_date),
                      COALESCE(a.decided_by_id, a.requested_by_id), a.name,
                      concat_ws(E'\n', a.reason, a.rejection_reason,
                                CASE WHEN a.old_value IS NOT NULL
                                     THEN a.old_value || ' -> ' || a.new_value END),
                      'warranty.card.action', a.id
                 FROM warranty_card_action a
                 JOIN warranty_card c ON c.id = a.card_id
                 LEFT JOIN warranty_card_action_unit_rel r ON r.action_id = a.id""",
            """SELECT l.card_id, NULL::integer, c.company_id, 'date',
                      initcap(replace(l.event, '_', ' ')), l.log_datetime, l.user_id, c.name,
                      concat_ws(' ', l.old_start::text, l.old_end::text,
                                CASE WHEN l.new_start IS NOT NULL OR l.new_end IS NOT NULL
                                     THEN '->' END, l.new_start::text, l.new_end::text, l.reason),
                      'warranty.card', c.id
                 FROM warranty_card_date_log l
                 JOIN warranty_card c ON c.id = l.card_id""",
            """SELECT e.warranty_card_id, NULL::integer, c.company_id, 'service',
                      'Service due date changed', l.change_date, l.user_id, e.name,
                      concat_ws(' ', l.previous_due_date::text, '->', l.new_due_date::text, l.reason),
                      'warranty.service.entitlement', e.id
                 FROM warranty_service_entitlement_date_log l
                 JOIN warranty_service_entitlement e ON e.id = l.entitlement_id
                 JOIN warranty_card c ON c.id = e.warranty_card_id""",
            """SELECT e.warranty_card_id, NULL::integer, c.company_id, 'service',
                      'Service ' || l.action, l.change_date, l.user_id, e.name,
                      concat_ws(' ', l.previous_scheduled_date::text, '->',
                                l.scheduled_date::text, l.reason),
                      'warranty.service.entitlement', e.id
                 FROM warranty_service_entitlement_schedule_log l
                 JOIN warranty_service_entitlement e ON e.id = l.entitlement_id
                 JOIN warranty_card c ON c.id = e.warranty_card_id""",
            self._warranty_history_status_query(
                'warranty.service.entitlement', 'service', 'Service',
                """warranty_service_entitlement x
                   JOIN warranty_card c ON c.id = x.warranty_card_id""", 'c.id'),
            """SELECT l.warranty_card_id, NULL::integer, c.company_id, 'download', 'PDF downloaded',
                      l.download_date, l.user_id, c.name, 'Download ' || l.download_no,
                      'warranty.card', c.id
                 FROM warranty_card_download_log l
                 JOIN warranty_card c ON c.id = l.warranty_card_id""",
            """SELECT DISTINCT u.warranty_card_id, u.id, c.company_id, 'invoice',
                      CASE m.move_type WHEN 'out_invoice' THEN 'Customer invoice'
                                       WHEN 'out_refund' THEN 'Customer credit note'
                                       ELSE initcap(replace(m.move_type, '_', ' ')) END
                      || ' created', m.create_date,
                      m.create_uid, COALESCE(m.name, '/'), m.invoice_origin::text,
                      'account.move', m.id
                 FROM warranty_unit u
                 JOIN warranty_card c ON c.id = u.warranty_card_id
                 JOIN sale_order_line_invoice_rel rel ON rel.order_line_id = u.sale_order_line_id
                 JOIN account_move_line ml ON ml.id = rel.invoice_line_id
                 JOIN account_move m ON m.id = ml.move_id""",
            # Append-only posting history of the same invoices / credit notes.
            """SELECT DISTINCT u.warranty_card_id, u.id, c.company_id, 'invoice',
                      CASE m.move_type WHEN 'out_invoice' THEN 'Customer invoice'
                                       WHEN 'out_refund' THEN 'Customer credit note'
                                       ELSE initcap(replace(m.move_type, '_', ' ')) END
                      || ' ' || replace(p.event, '_', ' '), p.event_datetime, p.user_id,
                      COALESCE(m.name, '/'), m.invoice_origin::text, 'account.move', m.id
                 FROM warranty_invoice_posting_event p
                 JOIN account_move m ON m.id = p.move_id
                 JOIN account_move_line ml ON ml.move_id = m.id
                 JOIN sale_order_line_invoice_rel rel ON rel.invoice_line_id = ml.id
                 JOIN warranty_unit u ON u.sale_order_line_id = rel.order_line_id
                 JOIN warranty_card c ON c.id = u.warranty_card_id""",
        ]

    def _warranty_history_status_query(self, model, entity, label, source, card,
                                       unit='NULL::integer'):
        """Status changes of `model` from its chatter tracking of the `state` field. `source`
        is the FROM clause with the record as x and its card as c."""
        return f"""SELECT {card}, {unit}, c.company_id, '{entity}',
                          '{label} status: ' || COALESCE(tv.old_value_char, '') || ' -> '
                              || COALESCE(tv.new_value_char, ''),
                          m.date, m.create_uid, x.name::text, NULL::text, '{model}', x.id
                     FROM mail_tracking_value tv
                     JOIN mail_message m ON m.id = tv.mail_message_id AND m.model = '{model}'
                     JOIN ir_model_fields f ON f.id = tv.field_id AND f.name = 'state'
                     JOIN {source} ON x.id = m.res_id"""

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        union = '\nUNION ALL\n'.join(self._warranty_history_queries())
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS
            SELECT row_number() OVER (ORDER BY event_date, card_id, unit_id, entity, event_type,
                                               reference, res_model, res_id, user_id) AS id, h.*
              FROM ({union}) AS h (card_id, unit_id, company_id, entity, event_type, event_date,
                                   user_id, reference, summary, res_model, res_id)
        """)

    def _warranty_open(self, domain, name=None):
        return {
            'type': 'ir.actions.act_window', 'name': name or _("Warranty History"),
            'res_model': self._name, 'view_mode': 'list', 'domain': domain,
        }

    def action_open_source(self):
        """Open the record the event comes from, with the user's own access rights."""
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id)
        record.check_access('read')
        return {
            'type': 'ir.actions.act_window', 'res_model': self.res_model, 'res_id': self.res_id,
            'view_mode': 'form', 'views': [(False, 'form')],
        }
