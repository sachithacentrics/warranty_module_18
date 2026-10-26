from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WarrantyServiceDateExceptionWizard(models.TransientModel):
    """Request Late Service Exception (BA-approved F5, request groups G2): one or several free
    services (preselected from the case / job), one requested latest service date and reason;
    one request group with one exception per service."""
    _name = 'warranty.service.date.exception.wizard'
    _description = 'Request Late Service Exception'

    service_ids = fields.Many2many('warranty.service.entitlement',
                                   'warranty_late_service_wizard_service_rel', 'wizard_id',
                                   'entitlement_id', string='Offered Services')
    entitlement_ids = fields.Many2many('warranty.service.entitlement',
                                       'warranty_late_service_wizard_selected_rel', 'wizard_id',
                                       'entitlement_id', string='Free Services', required=True,
                                       domain="[('id', 'in', service_ids)]")
    case_id = fields.Many2one('warranty.case', string='Warranty Case', readonly=True)
    requested_date = fields.Date(string='Requested Latest Service Date', required=True)
    reason = fields.Text(string='Reason', required=True)

    @api.model
    def _warranty_offered(self, services):
        """Services of a Manager Approval policy, open, without an open request."""
        Exception_ = self.env['warranty.service.date.exception']
        requested = Exception_.search([('entitlement_id', 'in', services.ids),
                                       ('state', '=', 'requested')]).entitlement_id
        offered = services.filtered(
            lambda service: service.late_service_handling == 'approval'
            and service.warranty_card_id.early_service_rule
            and service.state not in ('completed', 'expired', 'cancelled')) - requested
        return offered, requested & services

    @api.model
    def _warranty_open(self, services, case=None, defaults=None):
        offered, requested = self._warranty_offered(services)
        if not offered:
            raise UserError(_("No free service here allows a late-service exception (policy Late "
                              "Service Handling: Manager Approval, open service, no open "
                              "request).%s", _(" Already requested: %s.", ', '.join(
                                  requested.mapped('name'))) if requested else ''))
        context = {'default_service_ids': [(6, 0, offered.ids)],
                   'default_entitlement_ids': [(6, 0, offered.ids)],
                   'default_case_id': case.id if case else False}
        context.update(defaults or {})
        return {
            'type': 'ir.actions.act_window',
            'name': _("Request Late Service Exception"),
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'new',
            'context': context,
        }

    def _warranty_group_values(self):
        return {'case_id': self.case_id.id}

    def action_request(self):
        self.ensure_one()
        if self.entitlement_ids - self.service_ids:
            raise UserError(_("Select the offered free services only."))
        self.env['warranty.service.date.exception.group']._warranty_request_group(
            self.entitlement_ids, self.requested_date, self.reason,
            values=self._warranty_group_values())
        return {'type': 'ir.actions.act_window_close'}


class WarrantyServiceDateExceptionRejectWizard(models.TransientModel):
    _name = 'warranty.service.date.exception.reject.wizard'
    _description = 'Reject Late Service Exception'

    exception_id = fields.Many2one('warranty.service.date.exception', readonly=True,
                                   ondelete='cascade')
    group_id = fields.Many2one('warranty.service.date.exception.group', string='Request',
                               readonly=True, ondelete='cascade')
    note = fields.Text(string='Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        (self.group_id or self.exception_id).action_reject(self.note)
        return {'type': 'ir.actions.act_window_close'}
