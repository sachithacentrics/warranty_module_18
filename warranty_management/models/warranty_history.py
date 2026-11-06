from odoo import _, fields, models, tools

HISTORY_ENTITIES = [
    ('card', 'Warranty Card'),
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

    def _warranty_history_queries(self):
        """SELECTs of: card_id, unit_id, company_id, entity, event_type, event_date, user_id,
        reference, summary."""
        return [
            """SELECT c.id, NULL::integer, c.company_id, 'card', 'Card created', c.create_date,
                      c.create_uid, c.name, NULL::text
                 FROM warranty_card c""",
            """SELECT a.card_id, r.unit_id, c.company_id, 'action',
                      initcap(replace(a.action_type, '_', ' ')) || ': ' || initcap(a.state),
                      COALESCE(a.decision_date, a.request_date),
                      COALESCE(a.decided_by_id, a.requested_by_id), a.name,
                      concat_ws(E'\n', a.reason, a.rejection_reason,
                                CASE WHEN a.old_value IS NOT NULL
                                     THEN a.old_value || ' -> ' || a.new_value END)
                 FROM warranty_card_action a
                 JOIN warranty_card c ON c.id = a.card_id
                 LEFT JOIN warranty_card_action_unit_rel r ON r.action_id = a.id""",
            """SELECT l.card_id, NULL::integer, c.company_id, 'date',
                      initcap(replace(l.event, '_', ' ')), l.log_datetime, l.user_id, c.name,
                      concat_ws(' ', l.old_start::text, l.old_end::text,
                                CASE WHEN l.new_start IS NOT NULL OR l.new_end IS NOT NULL
                                     THEN '->' END, l.new_start::text, l.new_end::text, l.reason)
                 FROM warranty_card_date_log l
                 JOIN warranty_card c ON c.id = l.card_id""",
            """SELECT e.warranty_card_id, NULL::integer, c.company_id, 'service',
                      'Service due date changed', l.change_date, l.user_id, e.name,
                      concat_ws(' ', l.previous_due_date::text, '->', l.new_due_date::text, l.reason)
                 FROM warranty_service_entitlement_date_log l
                 JOIN warranty_service_entitlement e ON e.id = l.entitlement_id
                 JOIN warranty_card c ON c.id = e.warranty_card_id""",
            """SELECT e.warranty_card_id, NULL::integer, c.company_id, 'service',
                      'Service ' || l.action, l.change_date, l.user_id, e.name,
                      concat_ws(' ', l.previous_scheduled_date::text, '->',
                                l.scheduled_date::text, l.reason)
                 FROM warranty_service_entitlement_schedule_log l
                 JOIN warranty_service_entitlement e ON e.id = l.entitlement_id
                 JOIN warranty_card c ON c.id = e.warranty_card_id""",
            """SELECT l.warranty_card_id, NULL::integer, c.company_id, 'download', 'PDF downloaded',
                      l.download_date, l.user_id, c.name, 'Download ' || l.download_no
                 FROM warranty_card_download_log l
                 JOIN warranty_card c ON c.id = l.warranty_card_id""",
            """SELECT DISTINCT u.warranty_card_id, u.id, c.company_id, 'invoice',
                      CASE m.move_type WHEN 'out_invoice' THEN 'Customer invoice'
                                       WHEN 'out_refund' THEN 'Customer credit note'
                                       ELSE initcap(replace(m.move_type, '_', ' ')) END
                      || ': ' || initcap(m.state), m.create_date,
                      m.create_uid, COALESCE(m.name, '/'), m.invoice_origin::text
                 FROM warranty_unit u
                 JOIN warranty_card c ON c.id = u.warranty_card_id
                 JOIN sale_order_line_invoice_rel rel ON rel.order_line_id = u.sale_order_line_id
                 JOIN account_move_line ml ON ml.id = rel.invoice_line_id
                 JOIN account_move m ON m.id = ml.move_id""",
        ]

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        union = '\nUNION ALL\n'.join(self._warranty_history_queries())
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS
            SELECT row_number() OVER (ORDER BY event_date, card_id, reference) AS id, h.*
              FROM ({union}) AS h (card_id, unit_id, company_id, entity, event_type, event_date,
                                   user_id, reference, summary)
        """)

    def _warranty_open(self, domain, name=None):
        return {
            'type': 'ir.actions.act_window', 'name': name or _("Warranty History"),
            'res_model': self._name, 'view_mode': 'list', 'domain': domain,
        }
