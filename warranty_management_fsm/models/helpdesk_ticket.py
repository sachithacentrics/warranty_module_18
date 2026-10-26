from odoo import _, models
from odoo.exceptions import UserError


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    def action_generate_fsm_task(self):
        """Approved D8: the standard Plan Intervention must not bypass the Service Job for
        tickets with warranty cases; other tickets keep the standard behaviour."""
        if self.warranty_case_ids:
            raise UserError(_(
                "Ticket %s has warranty cases: plan the visit with Prepare Service Job / Confirm "
                "Service Job on the warranty case.", self.display_name))
        return super().action_generate_fsm_task()
