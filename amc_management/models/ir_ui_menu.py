from odoo import api, models
from odoo.http import request


class IrUiMenu(models.Model):
    """AMC Enabled switch: the AMC application is hidden in a company where AMC is disabled."""
    _inherit = 'ir.ui.menu'

    @api.model
    def _amc_menu_company(self):
        """Active company of the web client: the context (RPC) or the company switcher cookie
        (the menu routes run without allowed_company_ids in their context)."""
        company = self.env.company
        if 'allowed_company_ids' not in self.env.context and request:
            cid = (request.cookies.get('cids') or '').replace(',', '-').split('-')[0]
            if cid.isdigit() and int(cid) in self.env.user.company_ids.ids:
                company = self.env['res.company'].browse(int(cid))
        return company

    @api.model
    def load_menus(self, debug):
        # The parent result is cached per user (not per company): never modify it in place.
        menus = super().load_menus(debug)
        root = self.env.ref('amc_management.amc_management_menu_root', raise_if_not_found=False)
        if not root or root.id not in menus or self._amc_menu_company().sudo().amc_enabled:
            return menus
        hidden, todo = set(), [root.id]
        while todo:
            menu_id = todo.pop()
            hidden.add(menu_id)
            todo.extend(menus.get(menu_id, {}).get('children', []))
        menus = {key: value for key, value in menus.items() if key not in hidden}
        menus['root'] = dict(menus['root'], children=[
            child for child in menus['root']['children'] if child not in hidden])
        return menus
