from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .repair_order import INSPECTION_JOB_TYPES

# SRS 2.15 / 9.13. Damaged and Lost stay open: their closure waits for BA decision D3
# (doc/part6_3_backup_billing_design.md), so their serials cannot be issued again.
BACKUP_STATES = [
    ('draft', 'Draft'),
    ('issued', 'Issued'),
    ('overdue', 'Overdue'),
    ('returned', 'Returned'),
    ('damaged', 'Damaged'),
    ('lost', 'Lost'),
    ('closed', 'Closed'),
]
AT_CUSTOMER_STATES = ('issued', 'overdue')
BACKUP_CONDITIONS = [
    ('good', 'Good'),
    ('minor_scratch', 'Minor Scratch'),
    ('damaged', 'Damaged'),
]
ASSESSMENT_TYPES = [
    ('damage', 'Damage'),
    ('loss', 'Loss'),
]
ASSESSMENT_STATES = [
    ('none', 'Not Submitted'),
    ('to_approve', 'Waiting Approval'),
    ('approved', 'Approved'),
]
# Where the serial physically is: read from stock, independent of the billing.
ASSET_STATUSES = [
    ('backup_stock', 'In Backup Stock'),
    ('with_customer', 'In Service / Loan With Customer'),
    ('inspection', 'In Returned - Inspection'),
    ('scrapped', 'Scrapped'),
    ('removed', 'Removed by Inventory Adjustment'),
    ('other', 'In Another Location'),
]
# What the customer was charged: read from Sales and Accounting, independent of the stock. A
# cancelled quotation stays Cancelled: only an approved assessment of zero means No Charge.
CHARGE_STATUSES = [
    ('none', 'Not Assessed'),
    ('no_charge', 'No Charge Approved'),
    ('quotation', 'Quotation'),
    ('to_invoice', 'To Invoice'),
    ('invoiced', 'Invoiced'),
    ('partial', 'Partially Paid'),
    ('paid', 'Paid'),
    ('credited', 'Credit Note Issued'),
    ('cancelled', 'Quotation Cancelled'),
]
# Written by the actions and the validated pickings only. Python object: no client can send it.
_BACKUP_MARKER = object()
SYSTEM_FIELDS = {'state', 'issue_date', 'actual_return_date', 'issue_picking_id',
                 'return_picking_id', 'restock_picking_id', 'assessment_type', 'assessment_state',
                 'assessment_submitted_by_id', 'assessment_submitted_date',
                 'assessment_approved_by_id', 'assessment_approved_date', 'charge_order_id',
                 'charge_product_id', 'restored_by_id', 'restored_date', 'found_by_id',
                 'found_date', 'disposal_type', 'disposal_move_line_id'}
ISSUE_FIELDS = {'ticket_id', 'warranty_case_id', 'repair_id', 'partner_id', 'site_id',
                'product_id', 'lot_id', 'issue_reason', 'issue_condition', 'issue_notes'}
RETURN_FIELDS = {'return_condition', 'return_notes'}
ASSESSMENT_FIELDS = {'assessment_notes', 'repair_scrap_cost', 'charge_amount'}
# Figure 6 C2: entered before Confirm Restored (B1) / Record Found (B5), then locked.
RESTORE_FIELDS = {'restored_condition', 'restored_note'}
FOUND_FIELDS = {'found_note'}
# Billing users have write access for the deposit invoice link only.
COORDINATOR_FIELDS = ISSUE_FIELDS | RETURN_FIELDS | ASSESSMENT_FIELDS | RESTORE_FIELDS \
    | FOUND_FIELDS | {'expected_return_date', 'deposit_amount'}
# Figure 6 C2: how the unit left the backup fleet or came back to it (set by Close).
DISPOSAL_TYPES = [
    ('stock', 'Back in Backup Stock'),
    ('restored', 'Restored to Backup Stock'),
    ('scrap', 'Scrapped'),
    ('missing', 'Missing (Inventory Adjustment)'),
]
WRITTEN_OFF = ('scrap', 'missing')


class WarrantyBackupUnit(models.Model):
    """Backup Unit Issue / Return (SRS 2.9, 2.15, 13): custody of a company-owned serial lent
    during a repair. The stock moves are standard internal transfers, validated on the standard
    screen: this record only creates them and follows their validation."""
    _name = 'warranty.backup.unit'
    _description = 'Backup Unit Issue / Return'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    state = fields.Selection(BACKUP_STATES, string='Status', default='draft', required=True,
                             readonly=True, copy=False, tracking=True, index=True)
    company_id = fields.Many2one(related='ticket_id.company_id', store=True, index=True)
    ticket_id = fields.Many2one(
        'helpdesk.ticket', string='Helpdesk Ticket', required=True, tracking=True, index=True,
        ondelete='restrict', domain="[('is_warranty', '=', True)]")
    warranty_case_id = fields.Many2one(
        'warranty.case', string='Warranty Case', tracking=True, ondelete='restrict',
        index='btree_not_null', domain="[('helpdesk_ticket_id', '=', ticket_id)]")
    repair_id = fields.Many2one(
        'repair.order', string='Repair Order', tracking=True, ondelete='restrict',
        index='btree_not_null', domain="[('ticket_id', '=', ticket_id), ('state', '!=', 'cancel')]")
    warranty_service_job_id = fields.Many2one(
        'warranty.service.job', string='Service Job', compute='_compute_warranty_service_job_id',
        store=True)
    warranty_card_id = fields.Many2one(related='warranty_case_id.warranty_card_id')
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True,
                                 compute='_compute_partner_site', store=True, readonly=False)
    site_id = fields.Many2one('res.partner', string='Site', tracking=True,
                              compute='_compute_partner_site', store=True, readonly=False)
    product_id = fields.Many2one(
        'product.product', string='Backup Product', required=True, tracking=True,
        ondelete='restrict', domain="[('id', 'in', available_product_ids)]")
    lot_id = fields.Many2one(
        'stock.lot', string='Backup Serial', required=True, tracking=True, index=True,
        ondelete='restrict', domain="[('id', 'in', available_lot_ids)]")
    available_product_ids = fields.Many2many('product.product',
                                             compute='_compute_backup_available')
    available_lot_ids = fields.Many2many('stock.lot', compute='_compute_backup_available')
    issue_reason = fields.Char(string='Issue Reason', tracking=True)
    issue_picking_id = fields.Many2one('stock.picking', string='Issue Transfer', readonly=True,
                                       copy=False)
    return_picking_id = fields.Many2one('stock.picking', string='Return Transfer', readonly=True,
                                        copy=False)
    # Figure 6: Returned-Inspection -> Backup Stock, standard Internal Transfers (D-R2).
    restock_picking_id = fields.Many2one('stock.picking', string='Return to Stock Transfer',
                                         readonly=True, copy=False)
    issue_date = fields.Datetime(string='Issue Date', readonly=True, copy=False, tracking=True,
                                 help="Set when the issue transfer is validated.")
    expected_return_date = fields.Date(string='Expected Return', required=True, tracking=True)
    actual_return_date = fields.Datetime(string='Actual Return', readonly=True, copy=False,
                                         tracking=True,
                                         help="Set when the return transfer is validated.")
    issue_condition = fields.Selection(BACKUP_CONDITIONS, string='Issue Condition', tracking=True)
    issue_notes = fields.Text(string='Issue Notes')
    return_condition = fields.Selection(BACKUP_CONDITIONS, string='Return Condition', copy=False,
                                        tracking=True)
    return_notes = fields.Text(string='Return Notes', copy=False)
    # SRS 2.9 / 17: one approved assessment per record; the return condition is never changed.
    assessment_type = fields.Selection(ASSESSMENT_TYPES, string='Assessment Type', readonly=True,
                                       copy=False, tracking=True)
    assessment_state = fields.Selection(ASSESSMENT_STATES, string='Assessment', default='none',
                                        required=True, readonly=True, copy=False, tracking=True,
                                        index=True)
    assessment_notes = fields.Text(string='Assessment Notes', copy=False,
                                   help="What was damaged, or how the unit was lost.")
    assessment_decision_note = fields.Text(string='Decision Note', copy=False,
                                           help="Written by the approver. Required to send the "
                                                "assessment back or to approve no charge.")
    assessment_submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True,
                                                 copy=False)
    assessment_submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    assessment_approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True,
                                                copy=False)
    assessment_approved_date = fields.Datetime(string='Approved On', readonly=True, copy=False)
    can_approve_assessment = fields.Boolean(compute='_compute_can_approve_assessment')
    currency_id = fields.Many2one(related='company_id.currency_id')
    repair_scrap_cost = fields.Monetary(
        string='Repair / Scrap Cost', copy=False, tracking=True,
        help="Entered manually and approved with the assessment. Not added to the warranty case "
             "cost; actual costs stay on the standard Repair and Scrap records (BA decision D9).")
    charge_amount = fields.Monetary(
        string='Customer Charge', copy=False, tracking=True,
        help="Entered manually: there is no charge formula. Zero asks the approver to approve no "
             "charge, with a decision note.")
    charge_product_id = fields.Many2one('product.product', string='Charge Product', readonly=True,
                                        copy=False, ondelete='restrict')
    charge_order_id = fields.Many2one('sale.order', string='Charge Quotation', readonly=True,
                                      copy=False, ondelete='restrict', index='btree_not_null')
    charge_invoice_ids = fields.Many2many('account.move', string='Charge Invoices',
                                          compute='_compute_charge_status')
    charge_status = fields.Selection(CHARGE_STATUSES, string='Financial Recovery',
                                     compute='_compute_charge_status')
    asset_status = fields.Selection(ASSET_STATUSES, string='Physical Asset',
                                    compute='_compute_asset_status')
    serial_location_id = fields.Many2one('stock.location', string='Current Serial Location',
                                         compute='_compute_asset_status')
    # SRS 2.15: recorded only. Collection, refund, offset and forfeiture: BA decision D4.
    commercial_partner_id = fields.Many2one(related='partner_id.commercial_partner_id')
    deposit_amount = fields.Monetary(string='Deposit', copy=False, tracking=True)
    deposit_invoice_id = fields.Many2one(
        'account.move', string='Deposit Invoice', copy=False, tracking=True, ondelete='restrict',
        domain="[('move_type', '=', 'out_invoice'), "
               "('commercial_partner_id', '=', commercial_partner_id)]")
    # Figure 6 C2 (B1): a damaged unit goes back into service only with a recorded restoration.
    restored_condition = fields.Selection([('good', 'Good'), ('minor_scratch', 'Minor Scratch')],
                                          string='Restored Condition', copy=False, tracking=True)
    restored_note = fields.Text(string='Restoration Note', copy=False)
    restored_by_id = fields.Many2one('res.users', string='Restored By', readonly=True, copy=False)
    restored_date = fields.Datetime(string='Restored On', readonly=True, copy=False)
    # Figure 6 C2 (B5): a Lost unit found again, before its record is closed.
    found_note = fields.Text(string='Found Note', copy=False,
                             help="Where and when the lost unit was found.")
    found_by_id = fields.Many2one('res.users', string='Found Recorded By', readonly=True,
                                  copy=False)
    found_date = fields.Datetime(string='Found On', readonly=True, copy=False, tracking=True)
    # Figure 6 C2 (B4): the verified standard stock operation behind the closure.
    disposal_type = fields.Selection(DISPOSAL_TYPES, string='Disposition', readonly=True,
                                     copy=False, tracking=True)
    disposal_move_line_id = fields.Many2one('stock.move.line', string='Disposition Move',
                                            readonly=True, copy=False)

    @api.depends_context('uid')
    @api.depends('assessment_state', 'assessment_submitted_by_id', 'company_id')
    def _compute_can_approve_assessment(self):
        for unit in self:
            unit.can_approve_assessment = unit.assessment_state == 'to_approve' \
                and unit._warranty_backup_is_approver()

    @api.depends('assessment_state', 'charge_amount', 'charge_order_id')
    def _compute_charge_status(self):
        """sudo: the status is shown to users without Sales or Accounting rights."""
        for unit in self:
            order = unit.sudo().charge_order_id
            moves = order.invoice_ids.filtered(lambda move: move.state == 'posted')
            invoices = moves.filtered(lambda move: move.move_type == 'out_invoice')
            unit.charge_invoice_ids = order.invoice_ids
            if unit.assessment_state != 'approved':
                status = 'none'
            elif not order:
                status = 'no_charge'
            elif order.state == 'cancel':
                status = 'cancelled'
            elif moves.filtered(lambda move: move.move_type == 'out_refund'):
                status = 'credited'
            elif invoices:
                uncovered = self.env['warranty.case']._warranty_uncovered_amounts(invoices)
                if not any(uncovered.values()):
                    status = 'paid'
                elif any(uncovered[invoice.id] < invoice.amount_total for invoice in invoices):
                    status = 'partial'
                else:
                    status = 'invoiced'
            else:
                status = 'to_invoice' if order.state == 'sale' else 'quotation'
            unit.charge_status = status

    @api.depends('lot_id', 'company_id', 'state')
    def _compute_asset_status(self):
        """sudo: read from stock for users without Inventory rights."""
        Quant = self.env['stock.quant'].sudo()
        for unit in self:
            quants = Quant.search([('lot_id', '=', unit.lot_id.id), ('quantity', '>', 0)]) \
                if unit.lot_id else Quant
            quant = quants.filtered(lambda q: q.location_id.usage == 'internal')[:1] or quants[:1]
            location = quant.location_id
            company = unit.sudo().company_id
            issue = company.warranty_backup_issue_type_id
            back = company.warranty_backup_return_type_id
            within = self._warranty_backup_location_within
            if not unit.lot_id:
                status = False
            elif not location or location.usage == 'inventory' and not location.scrap_location:
                status = 'removed'
            elif location.scrap_location:
                status = 'scrapped'
            elif issue and within(location, issue.default_location_src_id):
                status = 'backup_stock'
            elif issue and within(location, issue.default_location_dest_id):
                status = 'with_customer'
            elif back and within(location, back.default_location_dest_id):
                status = 'inspection'
            else:
                status = 'other'
            unit.asset_status = status
            unit.serial_location_id = location

    @api.depends('warranty_case_id.service_job_ids.state',
                 'warranty_case_id.service_job_ids.job_type')
    def _compute_warranty_service_job_id(self):
        for unit in self:
            jobs = unit.warranty_case_id.service_job_ids.filtered(
                lambda job: job.state != 'cancelled' and job.job_type not in INSPECTION_JOB_TYPES)
            unit.warranty_service_job_id = jobs.sorted('id')[-1:]

    @api.depends('ticket_id', 'warranty_case_id')
    def _compute_partner_site(self):
        for unit in self:
            unit.partner_id = unit.ticket_id.partner_id
            unit.site_id = unit.warranty_case_id.site_id or unit.ticket_id.warranty_site_id

    @api.depends('company_id', 'product_id')
    def _compute_backup_available(self):
        """Serials in Backup Stock without an open backup record. sudo: read for the selection."""
        Quant = self.env['stock.quant'].sudo()
        for unit in self:
            location = unit.company_id.warranty_backup_issue_type_id.default_location_src_id
            lots = Quant.search([('location_id', 'child_of', location.id),
                                 ('lot_id', '!=', False),
                                 ('quantity', '>', 0)]).lot_id if location else self.env['stock.lot']
            lots -= self.sudo().search([('state', '!=', 'closed'), ('lot_id', 'in', lots.ids),
                                        ('id', '!=', unit._origin.id or 0)]).lot_id
            lots -= self._warranty_backup_written_off_lots(lots)
            unit.available_product_ids = lots.product_id
            unit.available_lot_ids = lots.filtered(
                lambda lot: not unit.product_id or lot.product_id == unit.product_id)

    # A case / Repair Order still valid for the new ticket / case is kept (Issue Backup Machine
    # prefills all three; the first onchange runs on every default).
    @api.onchange('ticket_id')
    def _onchange_ticket_id(self):
        cases = self.ticket_id._warranty_active_cases() if self.ticket_id \
            else self.env['warranty.case']
        if self.warranty_case_id._origin not in cases:
            self.warranty_case_id = cases if len(cases) == 1 else False

    @api.onchange('warranty_case_id')
    def _onchange_warranty_case_id(self):
        repairs = self.warranty_case_id._warranty_active_repairs()
        if self.repair_id._origin not in repairs:
            self.repair_id = repairs.id if len(repairs) == 1 else False

    # ------------------------------------------------------------------ navigation (Figure 6)
    @api.model
    def _warranty_backup_counts(self, field, records):
        """{record id: number of backup units} for the Backup Units smart buttons."""
        groups = self._read_group([(field, 'in', records._origin.ids)], [field], ['__count'])
        return {record.id: count for record, count in groups}

    @api.model
    def _warranty_backup_action(self, domain):
        """Backup Units smart buttons: the linked records; created from Issue Backup Machine."""
        units = self.search(domain)
        action = {
            'type': 'ir.actions.act_window',
            'name': _("Backup Units"),
            'res_model': 'warranty.backup.unit',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', units.ids)],
            'context': {'create': False},
        }
        if len(units) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')], 'res_id': units.id})
        return action

    def _warranty_backup_next_step(self):
        """Repair Order Next Step, after the machine went back: the first backup unit still to
        receive, inspect or assess (existing buttons; Damaged / Lost after approval wait for BA
        decision D3)."""
        for unit in self.sorted('id'):
            if unit.assessment_state == 'to_approve':
                return _("Backup unit %s: the damage / loss assessment waits for approval.",
                         unit.name)
            if unit.state in AT_CUSTOMER_STATES:
                if self._warranty_backup_active(unit.return_picking_id):
                    return _("Backup unit %(unit)s: validate the return %(picking)s.",
                             unit=unit.name, picking=unit.sudo().return_picking_id.name)
                return _("Backup unit %s: receive the backup machine (Create Return Transfer).",
                         unit.name)
            if unit.state == 'returned':
                restock = unit.sudo().restock_picking_id
                if unit._warranty_backup_restock_open() and restock.state == 'done':
                    return _("Backup unit %s: Close.", unit.name)
                if unit._warranty_backup_restock_open() and self._warranty_backup_active(restock):
                    return _("Backup unit %(unit)s: validate the return to Backup Stock "
                             "%(picking)s, then Close.", unit=unit.name, picking=restock.name)
                return _("Backup unit %s: after the inspection, move the serial to Backup Stock, "
                         "then Close.", unit.name)
            if unit.state == 'damaged' and unit.assessment_state == 'none':
                return _("Backup unit %s: submit the damage assessment.", unit.name)
        return False

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.lot_id.product_id != self.product_id:
            self.lot_id = False

    @api.constrains('ticket_id', 'warranty_case_id', 'repair_id', 'product_id', 'lot_id')
    def _check_backup_links(self):
        """SRS 13: ticket and exact serial mandatory; every link belongs to the same ticket."""
        for unit in self.sudo():
            if unit.lot_id.product_id != unit.product_id:
                raise ValidationError(_("Serial %(serial)s belongs to product %(lot_product)s, "
                                        "not to %(product)s.", serial=unit.lot_id.name,
                                        lot_product=unit.lot_id.product_id.display_name,
                                        product=unit.product_id.display_name))
            if unit.product_id.tracking != 'serial':
                raise ValidationError(_("Backup product %s must be tracked by serial number.",
                                        unit.product_id.display_name))
            if unit.warranty_case_id and unit.warranty_case_id.helpdesk_ticket_id != unit.ticket_id:
                raise ValidationError(_("Warranty case %s belongs to another Helpdesk ticket.",
                                        unit.warranty_case_id.name))
            if unit.repair_id and unit.repair_id.ticket_id != unit.ticket_id:
                raise ValidationError(_("Repair Order %s belongs to another Helpdesk ticket.",
                                        unit.repair_id.name))
            if unit.repair_id.warranty_case_id and unit.warranty_case_id \
                    and unit.repair_id.warranty_case_id != unit.warranty_case_id:
                raise ValidationError(_("Repair Order %s belongs to another warranty case.",
                                        unit.repair_id.name))

    @api.model
    def _warranty_backup_written_off_lots(self, lots):
        """B5e: serials whose latest backup record was closed after a Scrap or a missing count.
        A manual stock correction never makes them issuable again (recovery of a closed record:
        Part 9)."""
        latest = {}
        for unit in self.sudo().search([('lot_id', 'in', lots.ids)], order='id'):
            latest[unit.lot_id] = unit
        return self.env['stock.lot'].union(*[
            lot for lot, unit in latest.items()
            if unit.state == 'closed' and unit.disposal_type in WRITTEN_OFF])

    @api.constrains('lot_id')
    def _check_backup_serial_open(self):
        """A backup serial has one open record at a time (no duplicate issue), and a written-off
        serial is not issued again (B5e)."""
        for unit in self.sudo():
            other = self.sudo().search([('lot_id', '=', unit.lot_id.id), ('id', '!=', unit.id),
                                        ('state', '!=', 'closed')], limit=1)
            if other:
                raise ValidationError(_("Backup serial %(serial)s is already on the open backup "
                                        "record %(other)s.", serial=unit.lot_id.name,
                                        other=other.name))
            previous = self.sudo().search([('lot_id', '=', unit.lot_id.id), ('id', '<', unit.id)],
                                          order='id desc', limit=1)
            if previous.state == 'closed' and previous.disposal_type in WRITTEN_OFF:
                raise ValidationError(_(
                    "Backup serial %(serial)s was written off with backup record %(other)s "
                    "(%(disposal)s): it cannot be issued again.", serial=unit.lot_id.name,
                    other=previous.name, disposal=dict(DISPOSAL_TYPES)[previous.disposal_type]))

    @api.constrains('deposit_amount', 'deposit_invoice_id', 'partner_id')
    def _check_backup_deposit(self):
        """SRS 2.15: a reference to an invoice of this customer; nothing is posted or settled."""
        for unit in self.sudo():
            if unit.deposit_amount < 0:
                raise ValidationError(_("The deposit of %s cannot be negative.", unit.name))
            invoice = unit.deposit_invoice_id
            if invoice and (invoice.move_type != 'out_invoice'
                            or invoice.company_id != unit.company_id
                            or invoice.commercial_partner_id != unit.commercial_partner_id):
                raise ValidationError(_("Deposit invoice %(invoice)s must be a customer invoice "
                                        "of %(customer)s in the same company.",
                                        invoice=invoice.display_name,
                                        customer=unit.partner_id.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        if any(SYSTEM_FIELDS & set(vals) for vals in vals_list) \
                and self.env.context.get('warranty_backup_marker') is not _BACKUP_MARKER:
            raise UserError(_("Status, dates and transfers of a backup unit are set by its "
                              "actions and validated transfers."))
        if any(vals.get('deposit_invoice_id') for vals in vals_list):
            self._warranty_backup_check_billing_user()
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                ticket = self.env['helpdesk.ticket'].browse(vals.get('ticket_id'))
                vals['name'] = self.env['ir.sequence'].with_company(
                    ticket.company_id or self.env.company).next_by_code(
                    'warranty.backup.unit') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('warranty_backup_marker') is not _BACKUP_MARKER:
            if SYSTEM_FIELDS & set(vals):
                raise UserError(_("Status, dates and transfers of a backup unit are set by its "
                                  "actions and validated transfers."))
            if COORDINATOR_FIELDS & set(vals) and not self.env.su:
                self._warranty_backup_check_coordinator()
            if 'deposit_invoice_id' in vals:
                self._warranty_backup_check_billing_user()
            if ASSESSMENT_FIELDS & set(vals) and any(not unit._warranty_backup_assessment_open()
                                                     for unit in self):
                raise UserError(_("The assessment can only be changed before it is submitted, on "
                                  "a backup unit that is not Draft or Closed."))
            if 'assessment_decision_note' in vals and any(not unit.can_approve_assessment
                                                          for unit in self):
                raise UserError(_("The decision note is written by an authorized approver while "
                                  "the assessment is waiting for approval."))
            if ISSUE_FIELDS & set(vals) and any(unit._warranty_backup_issue_locked()
                                                for unit in self):
                raise UserError(_("The issue details can only be changed while the backup unit is "
                                  "Draft, before its issue transfer exists."))
            if RETURN_FIELDS & set(vals) and any(not unit._warranty_backup_receivable()
                                                 for unit in self):
                raise UserError(_("The return details are recorded while the backup unit is with "
                                  "the customer."))
            if RESTORE_FIELDS & set(vals) and any(
                    unit.state != 'damaged' or unit.assessment_state != 'approved'
                    or unit.restored_date for unit in self):
                raise UserError(_("The restoration is recorded on a Damaged backup unit with an "
                                  "approved assessment, before Confirm Restored."))
            if FOUND_FIELDS & set(vals) and any(unit.state != 'lost' or unit.found_date
                                                for unit in self):
                raise UserError(_("The found note is recorded on a Lost backup unit, before Record "
                                  "Found."))
            if 'expected_return_date' in vals and any(
                    unit.state not in ('draft',) + AT_CUSTOMER_STATES for unit in self):
                raise UserError(_("The expected return can only be changed until the backup unit "
                                  "is returned."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_issued(self):
        if any(unit._warranty_backup_issue_locked() for unit in self):
            raise UserError(_("Only Draft backup units without an issue transfer can be deleted "
                              "(custody history)."))

    def _warranty_backup_marked(self):
        return self.with_context(warranty_backup_marker=_BACKUP_MARKER)

    def _warranty_backup_issue_locked(self):
        self.ensure_one()
        return self.state != 'draft' or self._warranty_backup_active(self.issue_picking_id)

    def _warranty_backup_receivable(self):
        """With the customer, or a Lost unit found again (B5): the Backup Return receives it."""
        self.ensure_one()
        return self.state in AT_CUSTOMER_STATES or (self.state == 'lost' and bool(self.found_date))

    @api.model
    def _warranty_backup_active(self, picking):
        return bool(picking) and picking.state != 'cancel'

    # ------------------------------------------------------------------ history and To-Dos
    def _warranty_backup_log(self, text):
        """Warranty history notes (SRS 2.13): backup record, ticket, case, card, job and repair.
        sudo: the warehouse user may not write to them; notes only."""
        self.ensure_one()
        unit = self.sudo()
        body = Markup('<p>%s</p>') % text
        for record in (unit, unit.ticket_id, unit.warranty_case_id, unit.warranty_card_id,
                       unit.warranty_service_job_id, unit.repair_id):
            if record:
                record._message_log(body=body)

    def _warranty_backup_todo(self, step, note, users=None):
        """The next step for the given users, else the ticket's assigned user, else the creator;
        the previous step is closed; no duplicate. sudo: To-Dos of other users."""
        self.ensure_one()
        unit = self.sudo()
        prefix = _("Backup Unit %s: ", self.name)
        summary = prefix + step
        activities = unit.activity_ids.filtered(lambda a: (a.summary or '').startswith(prefix))
        if activities.filtered(lambda a: a.summary == summary):
            return
        activities.action_feedback(feedback=_("Next step reached."))
        for user in users or unit.ticket_id.user_id or unit.create_uid:
            unit.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                   summary=summary, note=note)

    def _warranty_backup_close_todos(self):
        self.ensure_one()
        prefix = _("Backup Unit %s: ", self.name)
        self.sudo().activity_ids.filtered(
            lambda a: (a.summary or '').startswith(prefix)
        ).action_feedback(feedback=_("Next step reached."))

    @api.model
    def _warranty_backup_repair_returned(self, repair):
        """SRS 2.9: after the repaired machine is returned, the backup unit comes back."""
        for unit in self.sudo().search([('repair_id', '=', repair.id),
                                        ('state', 'in', AT_CUSTOMER_STATES),
                                        ('assessment_state', '=', 'none')]):
            unit._warranty_backup_todo(_("receive the backup unit"), _(
                "The repaired machine of %s was returned: receive the backup unit (Create Return "
                "Transfer).", repair.name))

    @api.model
    def _warranty_backup_replacement_done(self, case):
        """SRS 2.9, Figure 6: after the replacement unit is delivered, the backup unit comes back."""
        for unit in self.sudo().search([('warranty_case_id', '=', case.id),
                                        ('state', 'in', AT_CUSTOMER_STATES),
                                        ('assessment_state', '=', 'none')]):
            unit._warranty_backup_todo(_("receive the backup unit"), _(
                "The replacement unit of %s was delivered: receive the backup unit (Create Return "
                "Transfer).", case.name))

    # ------------------------------------------------------------------ transfers
    def _warranty_backup_check_user(self):
        if not self.env.user.has_group('stock.group_stock_user'):
            raise AccessError(_("Only Inventory users can create backup unit transfers."))

    def _warranty_backup_create_picking(self, picking_type, source=None, destination=None):
        """Standard internal transfer of exactly this serial, between the operation's default
        locations unless given. Odoo may reserve any serial on confirmation, so that reservation
        is released and this serial reserved."""
        self.ensure_one()
        source = source or picking_type.default_location_src_id
        destination = destination or picking_type.default_location_dest_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': source.id,
            'location_dest_id': destination.id,
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'move_ids': [(0, 0, {
                'name': self.name,
                'product_id': self.product_id.id,
                'product_uom': self.product_id.uom_id.id,
                'product_uom_qty': 1.0,
                'location_id': source.id,
                'location_dest_id': destination.id,
            })],
        })
        picking.action_confirm()
        move = picking.move_ids
        move._do_unreserve()
        if not move._update_reserved_quantity(1.0, move.location_id, lot_id=self.lot_id,
                                              strict=False):
            raise UserError(_("Serial %(serial)s of %(product)s is not available in "
                              "%(location)s.", serial=self.lot_id.name,
                              product=self.product_id.display_name,
                              location=move.location_id.display_name))
        move._recompute_state()
        return picking

    def _warranty_open_picking(self, picking):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'res_id': picking.id,
        }

    def action_warranty_backup_issue(self):
        """Create Issue Transfer: Backup Stock -> Service / Loan With Customer."""
        self.ensure_one()
        self._warranty_backup_check_user()
        if self.state != 'draft':
            raise UserError(_("Backup unit %s has already been issued.", self.name))
        if self._warranty_backup_active(self.issue_picking_id):
            return self._warranty_open_picking(self.issue_picking_id)
        picking_type = self.company_id.warranty_backup_issue_type_id
        problems = []
        if not picking_type:
            problems.append(_("Set the Backup Issue Operation Type in Settings > Warranty."))
        if not self.issue_condition:
            problems.append(_("Set the Issue Condition."))
        if self.expected_return_date and self.expected_return_date < self.company_id._warranty_today():
            problems.append(_("The Expected Return is in the past."))
        if problems:
            raise UserError('\n'.join('- %s' % problem for problem in problems))
        picking = self._warranty_backup_create_picking(picking_type)
        self._warranty_backup_marked().write({'issue_picking_id': picking.id})
        return self._warranty_open_picking(picking)

    def action_warranty_backup_return(self):
        """Create Return Transfer: the dedicated Backup Return operation (SRS 2.9)."""
        self.ensure_one()
        self._warranty_backup_check_user()
        if self.state == 'lost' and not self.found_date:
            raise UserError(_("Backup unit %s is Lost: an approver must first use Record Found.",
                              self.name))
        if not self._warranty_backup_receivable():
            raise UserError(_("Backup unit %s is not with the customer.", self.name))
        if self.assessment_state == 'to_approve':
            raise UserError(_("Backup unit %s has a loss report waiting for approval: the approver "
                              "must send it back before the unit can be received.", self.name))
        if self._warranty_backup_active(self.return_picking_id):
            return self._warranty_open_picking(self.return_picking_id)
        picking_type = self.company_id.warranty_backup_return_type_id
        if not picking_type:
            raise UserError(_("Set the Backup Return Operation Type in Settings > Warranty."))
        picking = self._warranty_backup_create_picking(picking_type)
        self._warranty_backup_marked().write({'return_picking_id': picking.id})
        return self._warranty_open_picking(picking)

    def _warranty_backup_restock_open(self):
        """Return to Backup Stock: a unit returned in Good or Minor Scratch condition (C3), without
        assessment, or recovered after Lost (B5); a Damaged unit with an approved assessment and
        a confirmed restoration (B1). A manual internal transfer, then Close, still works."""
        self.ensure_one()
        if self.state == 'returned':
            return self.return_condition in ('good', 'minor_scratch') and (
                self.assessment_state == 'none' or self._warranty_backup_recovered())
        return self.state == 'damaged' and self.assessment_state == 'approved' \
            and bool(self.restored_date)

    def _warranty_backup_recovered(self):
        """Received again after an approved loss (B5)."""
        self.ensure_one()
        return bool(self.found_date) and self.assessment_type == 'loss' \
            and self.assessment_state == 'approved'

    def _warranty_backup_restock_locations(self):
        """(Returned-Inspection, Backup Stock): the locations of the two backup operations."""
        company = self.company_id
        return (company.warranty_backup_return_type_id.default_location_dest_id,
                company.warranty_backup_issue_type_id.default_location_src_id)

    def _warranty_backup_restock_type(self):
        """The existing standard Internal Transfers of the Backup Issue operation's warehouse,
        else of the company's only warehouse (D-R2: no new operation type or setting)."""
        company = self.company_id
        warehouses = company.warranty_backup_issue_type_id.warehouse_id \
            or self.env['stock.warehouse'].search([('company_id', '=', company.id)])
        picking_type = warehouses.int_type_id if len(warehouses) == 1 \
            else self.env['stock.picking.type']
        if not picking_type.active or picking_type.code != 'internal' \
                or picking_type.company_id != company:
            raise UserError(_("No active standard Internal Transfers operation type was found for "
                              "%(company)s: activate it, or set the Warehouse of the Backup Issue "
                              "Operation Type.", company=company.name))
        return picking_type

    def _warranty_backup_pending_transfers(self):
        """Transfers not done yet, not linked to a backup unit, that hold this serial in
        Returned-Inspection: (those that move exactly this unit to Backup Stock, the others)."""
        self.ensure_one()
        source, destination = self._warranty_backup_restock_locations()
        within = self._warranty_backup_location_within
        lines = self.env['stock.move.line'].search([
            ('lot_id', '=', self.lot_id.id), ('picking_id', '!=', False),
            ('state', 'not in', ('done', 'cancel')), ('location_id', 'child_of', source.id)])
        linked = self._warranty_backup_units_of(lines.picking_id)
        pickings = lines.picking_id - linked.issue_picking_id - linked.return_picking_id \
            - linked.restock_picking_id
        matching = pickings.filtered(lambda picking: (
            picking.company_id == self.company_id
            and len(picking.move_ids) == 1 and len(picking.move_line_ids) == 1
            and picking.move_ids.product_id == self.product_id
            and picking.move_ids.product_uom_qty == 1
            and picking.move_line_ids.lot_id == self.lot_id
            and within(picking.location_id, source) and within(picking.location_dest_id, destination)
            and within(picking.move_line_ids.location_dest_id, destination)))
        return matching, pickings - matching

    def action_warranty_backup_restock(self):
        """Return to Backup Stock (Figure 6): a standard internal transfer of exactly this serial,
        Returned-Inspection -> Backup Stock, validated by the user on the standard screen. Close
        stays a separate step (D-R1). An unlinked transfer is opened, never linked."""
        self.ensure_one()
        self._warranty_backup_check_user()
        if not self._warranty_backup_restock_open():
            raise UserError(_("Return to Backup Stock is for a backup unit Returned in Good or "
                              "Minor Scratch condition, without assessment, or a restored "
                              "Damaged unit (%s).", self.name))
        restock = self.restock_picking_id
        if self._warranty_backup_active(restock):
            if restock.state != 'done':
                return self._warranty_open_picking(restock)
            raise UserError(_("Backup unit %(unit)s was returned to Backup Stock with %(picking)s: "
                              "use Close.", unit=self.name, picking=restock.name))
        source, destination = self._warranty_backup_restock_locations()
        if not source or not destination:
            raise UserError(_("Set the Backup Issue and Backup Return Operation Types in "
                              "Settings > Warranty."))
        if self.env['stock.quant'].sudo()._get_available_quantity(
                self.product_id, destination, lot_id=self.lot_id, strict=False):
            raise UserError(_("Serial %(serial)s is already in %(location)s: use Close.",
                              serial=self.lot_id.name, location=destination.display_name))
        matching, others = self._warranty_backup_pending_transfers()
        if len(matching) == 1 and not others:
            return self._warranty_open_picking(matching)
        if matching or others:
            raise UserError(_("Serial %(serial)s is already on transfers not validated yet: "
                              "%(pickings)s. Validate or cancel them in Inventory first.",
                              serial=self.lot_id.name,
                              pickings=', '.join((matching | others).mapped('name'))))
        picking = self._warranty_backup_create_picking(self._warranty_backup_restock_type(),
                                                       source, destination)
        self._warranty_backup_marked().write({'restock_picking_id': picking.id})
        self._warranty_backup_log(_("Backup unit %(unit)s: return to Backup Stock %(picking)s "
                                    "created by %(user)s for serial %(serial)s.", unit=self.name,
                                    picking=picking.name, user=self.env.user.name,
                                    serial=self.lot_id.name))
        return self._warranty_open_picking(picking)

    def action_warranty_backup_close(self):
        """Close a returned unit once it is back in Backup Stock (standard internal transfer);
        its serial can then be issued again. Damaged / Lost / recovered units (Figure 6 C2): an
        approved assessment, a settled charge and a verified standard stock operation (B1-B7).
        Nothing is moved, scrapped, adjusted, invoiced or posted here."""
        self.ensure_one()
        if self.state == 'returned' and self.assessment_state == 'none':
            location = self.company_id.warranty_backup_issue_type_id.default_location_src_id
            if not self.env['stock.quant'].sudo()._get_available_quantity(
                    self.product_id, location, lot_id=self.lot_id, strict=False):
                raise UserError(_("Serial %(serial)s is not back in %(location)s: transfer it "
                                  "with a standard internal transfer after the inspection.",
                                  serial=self.lot_id.name, location=location.display_name))
            self._warranty_backup_marked().write({'state': 'closed', 'disposal_type': 'stock'})
            self._warranty_backup_close_todos()
            self._warranty_backup_log(_("Backup unit %(unit)s closed by %(user)s: serial %(serial)s "
                                        "is back in Backup Stock.", unit=self.name,
                                        user=self.env.user.name, serial=self.lot_id.name))
            return True
        if self.state not in ('returned', 'damaged', 'lost'):
            raise UserError(_("Only Returned, Damaged or Lost backup units can be closed (%s).",
                              self.name))
        self._warranty_backup_check_user()  # B7: Close confirms the physical state
        problems, disposal, line = self._warranty_backup_close_check()
        if problems:
            raise UserError(_("Backup unit %(unit)s cannot be closed:\n%(problems)s",
                              unit=self.name,
                              problems='\n'.join('- %s' % problem for problem in problems)))
        self._warranty_backup_marked().write({'state': 'closed', 'disposal_type': disposal,
                                              'disposal_move_line_id': line.id})
        self._warranty_backup_close_todos()
        unit = self.sudo()
        self._warranty_backup_log(_(
            "Backup unit %(unit)s closed by %(user)s: %(type)s assessment approved by %(approver)s; "
            "Financial Recovery %(financial)s; Disposition %(disposal)s%(reference)s; serial "
            "%(serial)s.", unit=self.name, user=self.env.user.name,
            type=dict(ASSESSMENT_TYPES)[unit.assessment_type],
            approver=unit.assessment_approved_by_id.name,
            financial=dict(CHARGE_STATUSES)[unit.charge_status],
            disposal=dict(DISPOSAL_TYPES)[disposal],
            reference=' (%s, %s, %s)' % (line.reference, line.write_uid.name, line.date)
            if line else '', serial=unit.lot_id.name))
        return True

    # ------------------------------------------------------------------ Figure 6 C2 closure
    def _warranty_backup_close_check(self):
        """(problems, disposition, verified stock move line) of a Damaged / Lost / recovered
        unit; every problem listed at once."""
        self.ensure_one()
        unit = self.sudo()
        problems = []
        if unit.state == 'lost' and unit.found_date:
            return [_("The unit was found: receive it with Create Return Transfer first.")], \
                False, self.env['stock.move.line']
        if unit.assessment_state != 'approved':
            problems.append(_("The assessment must be approved."))
        financial = unit._warranty_backup_financial_problem()
        if financial:
            problems.append(financial)
        pending = self.env['stock.move.line'].sudo().search([
            ('lot_id', '=', unit.lot_id.id), ('state', 'not in', ('done', 'cancel'))])
        if pending:
            problems.append(_("Serial %(serial)s is on transfers not validated yet: %(pickings)s.",
                              serial=unit.lot_id.name, pickings=', '.join(
                                  pending.mapped('reference'))))
        disposal, line, physical = unit._warranty_backup_disposition()
        if physical:
            problems.append(physical)
        return problems, disposal, line

    def _warranty_backup_financial_problem(self):
        """B2 / B3 / B5c, read from the actual Sales and Accounting documents."""
        self.ensure_one()
        unit = self.sudo()
        status = unit.charge_status
        order = unit.charge_order_id
        if status == 'no_charge':
            return False
        if status == 'paid':
            if order.invoice_status != 'invoiced':
                return _("Charge order %s is not fully invoiced.", order.name)
            if order.invoice_ids.filtered(lambda move: move.state == 'draft'):
                return _("Charge order %s has a draft invoice or credit note.", order.name)
            return False
        if status == 'credited' and unit._warranty_backup_recovered():
            # B5c: the correction of a recovered loss is valid only when every posted invoice and
            # credit note of the charge is settled (reconciled with each other or paid) and none
            # is left in draft.
            moves = order.invoice_ids
            if moves.filtered(lambda move: move.state == 'draft'):
                return _("Charge order %s has a draft invoice or credit note.", order.name)
            open_moves = moves.filtered(lambda move: move.state == 'posted'
                                        and not move.currency_id.is_zero(move.amount_residual))
            if open_moves:
                return _("Credit note correction not settled: %s still open.",
                         ', '.join(open_moves.mapped('name')))
            return False
        return _("Financial Recovery is %s: the charge must be paid (or approved as no charge).",
                 dict(CHARGE_STATUSES)[status]) if status != 'credited' else _(
            "Financial Recovery is Credit Note Issued: closing needs a write-off rule (not "
            "defined).")

    def _warranty_backup_disposition(self):
        """(disposition, stock move line, problem) from the serial's actual stock records (B1 /
        B4): restored or recovered units back in Backup Stock; Damaged units scrapped from
        Returned-Inspection; Lost units scrapped or counted missing from Service / Loan."""
        self.ensure_one()
        Line = self.env['stock.move.line']
        company = self.company_id
        backup_stock = company.warranty_backup_issue_type_id.default_location_src_id
        inspection = company.warranty_backup_return_type_id.default_location_dest_id
        loan = company.warranty_backup_issue_type_id.default_location_dest_id
        within = self._warranty_backup_location_within
        if self.state == 'returned' or (self.state == 'damaged' and self.restored_date):
            if self.state == 'returned' and not self._warranty_backup_recovered():
                return False, Line, _("Only a recovered unit has an assessment in Returned.")
            if not self.env['stock.quant'].sudo()._get_available_quantity(
                    self.product_id, backup_stock, lot_id=self.lot_id, strict=False):
                return False, Line, _("Serial %(serial)s is not back in %(location)s: use Return "
                                      "to Backup Stock.", serial=self.lot_id.name,
                                      location=backup_stock.display_name)
            return ('stock' if self.state == 'returned' else 'restored'), Line, False
        source, allowed = (inspection, ('scrap',)) if self.state == 'damaged' \
            else (loan, ('scrap', 'missing'))
        if self.state == 'damaged':
            needed = _("Scrap serial %(serial)s (Inventory > Scrap) from %(location)s, or record "
                       "the restoration and use Confirm Restored.", serial=self.lot_id.name,
                       location=source.display_name)
        else:
            needed = _("Resolve serial %(serial)s in %(location)s with a standard Scrap, or count "
                       "it missing in Physical Inventory (Inventory Administrator).",
                       serial=self.lot_id.name, location=source.display_name)
        quants = self.env['stock.quant'].sudo().search([('lot_id', '=', self.lot_id.id),
                                                        ('quantity', '>', 0)])
        if quants.filtered(lambda quant: quant.location_id.usage in ('internal', 'transit')):
            return False, Line, needed
        line = Line.sudo().search([('lot_id', '=', self.lot_id.id), ('state', '=', 'done')],
                                  order='date desc, id desc', limit=1)
        kind = 'scrap' if line.move_id.scrap_id and line.location_dest_id.scrap_location else (
            'missing' if line.move_id.is_inventory and line.location_dest_id.usage == 'inventory'
            and not line.location_dest_id.scrap_location else False)
        if not line or kind not in allowed or line.company_id != company \
                or not within(line.location_id, source) \
                or (self.issue_date and line.date < self.issue_date):
            return False, Line, needed
        return kind, line, False

    def action_warranty_backup_confirm_restored(self):
        """B1: an Inventory user records that the damaged unit is fit for service again, in
        Returned-Inspection; Return to Backup Stock and Close follow."""
        self.ensure_one()
        self._warranty_backup_check_user()
        if self.state != 'damaged' or self.assessment_state != 'approved' or self.restored_date:
            raise UserError(_("Confirm Restored is for a Damaged backup unit with an approved "
                              "assessment, once (%s).", self.name))
        if not self.restored_condition or not (self.restored_note or '').strip():
            raise UserError(_("Enter the Restored Condition and the Restoration Note."))
        inspection = self.company_id.warranty_backup_return_type_id.default_location_dest_id
        if not self.env['stock.quant'].sudo()._get_available_quantity(
                self.product_id, inspection, lot_id=self.lot_id, strict=False):
            raise UserError(_("Serial %(serial)s is not in %(location)s.",
                              serial=self.lot_id.name, location=inspection.display_name))
        self._warranty_backup_marked().write({'restored_by_id': self.env.uid,
                                              'restored_date': fields.Datetime.now()})
        self._warranty_backup_log(_(
            "Backup unit %(unit)s: restoration confirmed by %(user)s, condition %(condition)s. "
            "Note: %(note)s", unit=self.name, user=self.env.user.name,
            condition=dict(self._fields['restored_condition']._description_selection(self.env))[
                self.restored_condition], note=self.restored_note))
        self._warranty_backup_todo(_("close"), _(
            "Use Return to Backup Stock, validate the transfer, then use Close."))
        return True

    def action_warranty_backup_record_found(self):
        """B5: a Backup Damage / Loss Approver records that the Lost unit was found. The serial
        must verifiably be in Service / Loan With Customer again (a written-off serial needs a
        standard stock correction by an Inventory Administrator first). The unit is then
        received with the Backup Return operation."""
        self.ensure_one()
        if self.env.user not in self.sudo().company_id.warranty_backup_approver_user_ids:
            raise AccessError(_("Only a Backup Damage / Loss Approver of the company can record a "
                                "lost unit as found."))
        if self.state != 'lost' or self.assessment_state != 'approved' or self.found_date:
            raise UserError(_("Record Found is for a Lost backup unit, once (%s).", self.name))
        if not (self.found_note or '').strip():
            raise UserError(_("Enter the Found Note (where and when the unit was found)."))
        unit = self.sudo()  # the approver may have no Inventory rights; read for the checks
        loan = unit.company_id.warranty_backup_issue_type_id.default_location_dest_id
        quants = self.env['stock.quant'].sudo().search([('lot_id', '=', unit.lot_id.id),
                                                        ('quantity', '>', 0)])
        written_off = quants.filtered(lambda quant: quant.location_id.usage == 'inventory')
        if written_off:
            raise UserError(_(
                "Serial %(serial)s was written off (%(locations)s): an Inventory Administrator "
                "must first correct the stock with a standard operation, back into %(loan)s.",
                serial=unit.lot_id.name, loan=loan.display_name,
                locations=', '.join(written_off.location_id.mapped('display_name'))))
        if len(quants) != 1 or quants.quantity != 1 or quants.company_id != unit.company_id \
                or not self._warranty_backup_location_within(quants.location_id, loan):
            raise UserError(_("Serial %(serial)s must be in %(loan)s exactly once to be received "
                              "(found in: %(locations)s).", serial=unit.lot_id.name,
                              loan=loan.display_name, locations=', '.join(
                                  quants.location_id.mapped('display_name')) or '-'))
        unit._warranty_backup_marked().write({'found_by_id': self.env.uid,
                                              'found_date': fields.Datetime.now()})
        self._warranty_backup_log(_(
            "Backup unit %(unit)s: lost serial %(serial)s recorded as found by %(user)s. Note: "
            "%(note)s. The loss assessment and its charge are unchanged; any financial correction "
            "is made by Accounting.", unit=self.name, serial=unit.lot_id.name,
            user=self.env.user.name, note=self.found_note))
        self._warranty_backup_todo(_("receive the backup unit"), _(
            "The lost unit was found: set the Return Condition, use Create Return Transfer and "
            "validate it."))
        return True

    # ------------------------------------------------------------------ damage / loss assessment
    def _warranty_backup_check_coordinator(self):
        user = self.env.user
        if not (user.has_group('stock.group_stock_user')
                or user.has_group('helpdesk.group_helpdesk_user')):
            raise AccessError(_("Only Inventory or Helpdesk users can change backup units."))

    def _warranty_backup_check_billing_user(self):
        if not self.env.su and not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(_("Only billing users can link the deposit invoice."))

    def _warranty_backup_assessment_open(self):
        self.ensure_one()
        return self.assessment_state == 'none' and self.state not in ('draft', 'closed', 'lost')

    def _warranty_backup_is_approver(self):
        """Separation of duties: an authorized approver of the company, never the submitter."""
        self.ensure_one()
        user = self.env.user
        return user in self.sudo().company_id.warranty_backup_approver_user_ids \
            and user != self.assessment_submitted_by_id

    def _warranty_backup_check_approver(self):
        self.ensure_one()
        if self.assessment_state != 'to_approve':
            raise UserError(_("The assessment of %s is not waiting for approval.", self.name))
        if not self._warranty_backup_is_approver():
            raise AccessError(_("Only a Backup Damage / Loss Approver of the company, other than "
                                "the submitter, can decide the assessment of %s.", self.name))

    def _warranty_backup_charge_error(self):
        """The charge product is needed only when the customer is charged."""
        self.ensure_one()
        if not self.charge_amount:
            return False
        company = self.sudo().company_id
        if not company.warranty_backup_charge_product_id:
            return _("Set the Backup Damage / Loss Charge Product in Settings > Warranty.")
        return company._warranty_backup_charge_product_error()

    def _warranty_backup_submit_assessment(self, assessment_type):
        self.ensure_one()
        self._warranty_backup_check_coordinator()
        if not self._warranty_backup_assessment_open():
            raise UserError(_("The assessment of %s cannot be submitted in this status.",
                              self.name))
        unit = self.sudo()  # names of the serial and the customer, whatever the user's rights
        approvers = unit.company_id.warranty_backup_approver_user_ids - self.env.user
        problems = []
        if not (self.assessment_notes or '').strip():
            problems.append(_("Enter the Assessment Notes."))
        if self.repair_scrap_cost < 0 or self.charge_amount < 0:
            problems.append(_("The cost and the charge cannot be negative."))
        if not approvers:
            problems.append(_("Set the Backup Damage / Loss Approvers in Settings > Warranty: at "
                              "least one user other than the submitter."))
        charge_error = self._warranty_backup_charge_error()
        if charge_error:
            problems.append(charge_error)
        if problems:
            raise UserError('\n'.join('- %s' % problem for problem in problems))
        vals = {'assessment_type': assessment_type, 'assessment_state': 'to_approve',
                'assessment_submitted_by_id': self.env.uid,
                'assessment_submitted_date': fields.Datetime.now(),
                'assessment_decision_note': False}
        if assessment_type == 'damage':
            vals['state'] = 'damaged'
        self._warranty_backup_marked().write(vals)
        self._warranty_backup_log(_(
            "%(type)s assessment of backup unit %(unit)s submitted by %(user)s: serial %(serial)s, "
            "customer %(customer)s, charge %(charge)s, repair / scrap cost %(cost)s. Return "
            "condition unchanged: %(condition)s.",
            type=dict(ASSESSMENT_TYPES)[assessment_type], unit=self.name, user=self.env.user.name,
            serial=unit.lot_id.name, customer=unit.partner_id.display_name,
            charge=self.charge_amount, cost=self.repair_scrap_cost,
            condition=dict(BACKUP_CONDITIONS).get(self.return_condition, '-')))
        self._warranty_backup_todo(_("approve the assessment"), _(
            "Review the damage / loss assessment, then use Approve Assessment or Send Back."),
            users=approvers - self.env.user)
        return True

    def action_warranty_backup_report_lost(self):
        """Report Lost: the unit stays with the customer until the loss is approved."""
        self.ensure_one()
        if self.state not in AT_CUSTOMER_STATES:
            raise UserError(_("Only a unit with the customer can be reported lost (%s).",
                              self.name))
        if self._warranty_backup_active(self.return_picking_id):
            raise UserError(_("Cancel the open return transfer %(picking)s of %(unit)s before "
                              "reporting the unit lost.",
                              picking=self.sudo().return_picking_id.name, unit=self.name))
        return self._warranty_backup_submit_assessment('loss')

    def action_warranty_backup_submit_assessment(self):
        """Damage found at the return or during the inspection (SRS 2.9, 17)."""
        self.ensure_one()
        if self.state not in ('returned', 'damaged'):
            raise UserError(_("Damage is assessed on a returned backup unit (%s).", self.name))
        return self._warranty_backup_submit_assessment('damage')

    def action_warranty_backup_approve_assessment(self):
        """SRS 17: after the approved assessment, one draft quotation when the customer is
        charged. Nothing is sent, invoiced, posted, scrapped or closed here."""
        self.ensure_one()
        self._warranty_backup_check_approver()
        if self.charge_amount <= 0 and not (self.assessment_decision_note or '').strip():
            raise UserError(_("Approving no charge needs a Decision Note."))
        charge_error = self._warranty_backup_charge_error()
        if charge_error:
            raise UserError(charge_error)
        vals = {'assessment_state': 'approved', 'assessment_approved_by_id': self.env.uid,
                'assessment_approved_date': fields.Datetime.now()}
        if self.assessment_type == 'loss':
            vals['state'] = 'lost'
        # sudo: the approver may have no write access to backup units or no Sales rights.
        self.sudo()._warranty_backup_marked().write(vals)
        order = self._warranty_backup_create_charge_order() if self.charge_amount > 0 else None
        self._warranty_backup_log(_(
            "%(type)s assessment of backup unit %(unit)s approved by %(user)s: %(result)s. Decision "
            "note: %(note)s", type=dict(ASSESSMENT_TYPES)[self.assessment_type], unit=self.name,
            user=self.env.user.name,
            result=_("draft quotation %s created", order.name) if order else _("no charge"),
            note=self.assessment_decision_note or '-'))
        if order:
            self._warranty_backup_todo(_("send the charge quotation"), _(
                "Send quotation %s to the customer; it is confirmed and invoiced with the standard "
                "Sales screens. Close needs it paid and the unit scrapped, counted missing or "
                "restored.", order.name))
        else:
            # Figure 6 C2: the next step is the physical disposition, then Close.
            self._warranty_backup_todo(_("dispose and close"), _(
                "Lost: Scrap the serial or count it missing in Physical Inventory. Damaged: Scrap "
                "it, or record the restoration and use Confirm Restored. Then use Close."))
        return True

    def action_warranty_backup_send_back(self):
        """The approver returns the assessment for correction. A loss was never confirmed: the
        unit is still with the customer."""
        self.ensure_one()
        self._warranty_backup_check_approver()
        note = (self.assessment_decision_note or '').strip()
        if not note:
            raise UserError(_("Sending the assessment back needs a Decision Note."))
        submitter = self.assessment_submitted_by_id
        self.sudo()._warranty_backup_marked().write({
            'assessment_state': 'none', 'assessment_type': False,
            'assessment_submitted_by_id': False, 'assessment_submitted_date': False})
        self._warranty_backup_log(_("Assessment of backup unit %(unit)s sent back by %(user)s: "
                                    "%(note)s", unit=self.name, user=self.env.user.name,
                                    note=note))
        self._warranty_backup_todo(_("correct the assessment"), note, users=submitter)
        return True

    def _warranty_backup_create_charge_order(self):
        """One draft quotation (duplicates: no second call reaches this; the link cannot be
        removed). No warranty_case_id: a case-linked order runs the chargeable job trigger. No
        pricelist: the approved amount is in the company currency. sudo after the approval check,
        as the approver may have no Sales rights; the approver stays the salesperson."""
        self.ensure_one()
        if self.charge_order_id:
            raise UserError(_("Backup unit %(unit)s already has quotation %(order)s.",
                              unit=self.name, order=self.sudo().charge_order_id.name))
        unit = self.sudo()
        product = unit.company_id.warranty_backup_charge_product_id
        commercial = unit.partner_id.commercial_partner_id
        references = [unit.name, unit.warranty_case_id.name, unit.repair_id.name]
        order = self.env['sale.order'].sudo().with_company(unit.company_id).create({
            'partner_id': commercial.id,
            'partner_shipping_id': (unit.site_id or commercial).id,
            'company_id': unit.company_id.id,
            'pricelist_id': False,
            'user_id': self.env.uid,
            'origin': ' / '.join(reference for reference in references if reference),
            'order_line': [(0, 0, {
                'product_id': product.id,
                'name': _("%(type)s of backup unit %(unit)s: %(product)s, serial %(serial)s",
                          type=dict(ASSESSMENT_TYPES)[self.assessment_type], unit=self.name,
                          product=unit.product_id.display_name, serial=unit.lot_id.name),
                'product_uom_qty': 1.0,
                'price_unit': self.charge_amount,
                'discount': 0.0,
            })],
        })
        self.sudo()._warranty_backup_marked().write({'charge_order_id': order.id,
                                                     'charge_product_id': product.id})
        return order

    # ------------------------------------------------------------------ picking validation
    @api.model
    def _warranty_backup_units_of(self, pickings):
        # sudo: the warehouse user may not read the record; read for the checks and status only.
        return self.sudo().search(['|', '|', ('issue_picking_id', 'in', pickings.ids),
                                   ('return_picking_id', 'in', pickings.ids),
                                   ('restock_picking_id', 'in', pickings.ids)])

    @api.model
    def _warranty_backup_location_within(self, location, parent):
        return (location.parent_path or '').startswith(parent.parent_path or ' ')

    @api.model
    def _warranty_backup_check_pickings(self, pickings):
        """Before any stock move (SRS 13): exactly this serial, from and to the operation's
        locations, once; a return needs its condition; a return to Backup Stock a Good unit."""
        for unit in self._warranty_backup_units_of(pickings):
            is_issue = unit.issue_picking_id in pickings
            is_restock = unit.restock_picking_id in pickings
            picking = unit.issue_picking_id if is_issue else \
                unit.restock_picking_id if is_restock else unit.return_picking_id
            if is_issue and unit.state != 'draft':
                raise UserError(_("Backup unit %s has already been issued.", unit.name))
            if is_restock:
                if not unit._warranty_backup_restock_open():
                    raise UserError(_("Backup unit %(unit)s is no longer Returned in Good or Minor "
                                      "Scratch condition without assessment: cancel %(picking)s.",
                                      unit=unit.name,
                                      picking=picking.name))
                source, destination = unit._warranty_backup_restock_locations()
            else:
                source = picking.picking_type_id.default_location_src_id
                destination = picking.picking_type_id.default_location_dest_id
            if not is_issue and not is_restock:
                if unit.state == 'lost' and not unit.found_date:
                    raise UserError(_("Backup unit %s is recorded as Lost: an approver must use "
                                      "Record Found before it is received.", unit.name))
                if not unit._warranty_backup_receivable():
                    raise UserError(_("Backup unit %s has already been returned.", unit.name))
                if unit.assessment_state == 'to_approve':
                    raise UserError(_("Backup unit %s has a loss report waiting for approval: the "
                                      "approver must send it back first.", unit.name))
                if not unit.return_condition:
                    raise UserError(_("Set the Return Condition on backup unit %s before "
                                      "validating the return.", unit.name))
            lines = picking.move_line_ids.filtered('quantity')
            line = lines if len(lines) == 1 else lines.browse()
            if not line or line.product_id != unit.product_id or line.lot_id != unit.lot_id \
                    or line.quantity_product_uom != 1 \
                    or not self._warranty_backup_location_within(line.location_id, source) \
                    or not self._warranty_backup_location_within(line.location_dest_id,
                                                                 destination):
                raise UserError(_(
                    "%(picking)s must move exactly one %(product)s, serial %(serial)s, from "
                    "%(origin)s to %(destination)s (backup unit %(unit)s).",
                    picking=picking.name, product=unit.product_id.display_name,
                    serial=unit.lot_id.name, origin=source.display_name,
                    destination=destination.display_name, unit=unit.name))

    @api.model
    def _warranty_backup_after_pickings(self, pickings):
        """After validation: status, actual dates and history come from the transfer."""
        for unit in self._warranty_backup_units_of(pickings):
            if unit.issue_picking_id in pickings and unit.state == 'draft':
                unit._warranty_backup_marked().write({
                    'state': 'issued', 'issue_date': unit.issue_picking_id.date_done})
                unit._warranty_backup_close_todos()
                unit._warranty_backup_log(_(
                    "Backup unit %(unit)s issued with %(picking)s: %(product)s, serial %(serial)s "
                    "to %(customer)s; expected return %(date)s.", unit=unit.name,
                    picking=unit.issue_picking_id.name, product=unit.product_id.display_name,
                    serial=unit.lot_id.name, customer=unit.partner_id.display_name,
                    date=unit.expected_return_date))
            elif unit.return_picking_id in pickings and unit._warranty_backup_receivable():
                damaged = unit.return_condition == 'damaged'
                recovered = unit.state == 'lost'
                unit._warranty_backup_marked().write({
                    'state': 'damaged' if damaged else 'returned',
                    'actual_return_date': unit.return_picking_id.date_done})
                unit._warranty_backup_log(_(
                    "Backup unit %(unit)s returned with %(picking)s: serial %(serial)s, condition "
                    "%(condition)s.", unit=unit.name, picking=unit.return_picking_id.name,
                    serial=unit.lot_id.name,
                    condition=dict(BACKUP_CONDITIONS)[unit.return_condition]))
                if recovered:
                    # B5d: the approved loss assessment stays the only financial decision.
                    unit._warranty_backup_log(_(
                        "Backup unit %(unit)s recovered after Lost: the approved loss assessment "
                        "and its charge stay unchanged; any financial correction (credit note) is "
                        "made by Accounting. A further damage charge needs a separate business "
                        "decision.", unit=unit.name))
                    unit._warranty_backup_todo(_("inspect and close"), _(
                        "Damaged: Scrap the serial, or record the restoration and use Confirm "
                        "Restored, then Return to Backup Stock and Close.") if damaged else _(
                        "After the inspection, use Return to Backup Stock and validate the "
                        "transfer, then use Close."))
                elif damaged:
                    unit._warranty_backup_todo(_("submit the damage assessment"), _(
                        "Enter the assessment notes, repair / scrap cost and customer charge, then "
                        "use Submit Assessment."))
                else:
                    unit._warranty_backup_todo(_("inspect and close"), _(
                        "After the inspection, use Return to Backup Stock and validate the "
                        "transfer, then use Close."))
            elif unit.restock_picking_id in pickings and unit.state in ('returned', 'damaged'):
                unit._warranty_backup_log(_(
                    "Backup unit %(unit)s: serial %(serial)s returned to Backup Stock with "
                    "%(picking)s.", unit=unit.name, serial=unit.lot_id.name,
                    picking=unit.restock_picking_id.name))
                unit._warranty_backup_todo(_("close"), _(
                    "Serial %s is back in Backup Stock: use Close.", unit.lot_id.name))

    # ------------------------------------------------------------------ overdue
    @api.model
    def _cron_warranty_backup_overdue(self):
        """SRS 9.13: Issued -> Overdue after the expected return, with one To-Do; a later
        expected return brings the unit back to Issued."""
        for company in self.env['res.company'].sudo().search([]):
            today = company._warranty_today()
            units = self.sudo().search([('company_id', '=', company.id),
                                        ('state', 'in', AT_CUSTOMER_STATES)])
            for unit in units:
                late = unit.expected_return_date < today
                if late and unit.state == 'issued':
                    unit._warranty_backup_marked().write({'state': 'overdue'})
                    unit._warranty_backup_log(_(
                        "Backup unit %(unit)s is overdue: expected return %(date)s, serial "
                        "%(serial)s with %(customer)s.", unit=unit.name,
                        date=unit.expected_return_date, serial=unit.lot_id.name,
                        customer=unit.partner_id.display_name))
                    # The approvers' To-Do of a pending loss report stays open.
                    if unit.assessment_state == 'none':
                        unit._warranty_backup_todo(_("overdue"), _(
                            "Expected return %s has passed: follow up with the customer.",
                            unit.expected_return_date))
                elif not late and unit.state == 'overdue':
                    unit._warranty_backup_marked().write({'state': 'issued'})
                    if unit.assessment_state == 'none':
                        unit._warranty_backup_close_todos()
