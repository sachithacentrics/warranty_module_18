from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_amount

from ..models.warranty_mrf_approval_rule import APPROVAL_LEVELS


class WarrantyMrfRoutePreviewWizard(models.TransientModel):
    """Check Approval Route (Phase 5.3): read-only preview of the route Submit would save for
    a New warranty Material Request. Nothing is written on the request: no approval records,
    no To-Dos, no messages, no status change."""
    _name = 'warranty.mrf.route.preview.wizard'
    _description = 'Check Material Request Approval Route'

    requisition_id = fields.Many2one('material.purchase.requisition', string='Material Request',
                                     required=True, readonly=True)
    can_submit = fields.Boolean(readonly=True)
    preview_html = fields.Html(string='Approval Route', readonly=True, sanitize=False)


class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    def action_warranty_check_route(self):
        self.ensure_one()
        if not self.is_warranty_mrf or self.state != 'draft':
            raise UserError(_("The approval route can be checked for New warranty Material "
                              "Requests only."))
        can_submit, html = self._warranty_route_preview()
        wizard = self.env['warranty.mrf.route.preview.wizard'].create({
            'requisition_id': self.id, 'can_submit': can_submit, 'preview_html': html})
        return {
            'type': 'ir.actions.act_window',
            'name': _("Check Approval Route"),
            'res_model': wizard._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _warranty_route_preview(self):
        """(can be submitted, HTML) for the current user as submitter; reads only."""
        self.ensure_one()
        errors = []
        if not self.requisition_line_ids:
            errors.append(_("Add the requested materials to %s before submitting.", self.name))
        try:
            self._warranty_check_coverage_decided()
        except UserError as error:
            errors.append(error.args[0])
        parts = [Markup('<p>%s</p>') % _(
            "Preview for %(user)s as submitter. Nothing is saved: Submit validates and saves "
            "the route.", user=self.env.user.name)]
        if not self.company_id.warranty_mrf_approval_matrix:
            parts.append(Markup('<p><b>%s</b></p>') % _(
                "The Material Approval Matrix of %s is off: Submit starts the Requisition "
                "workflow (Department Approve, then Approve).", self.company_id.name))
            return self._warranty_preview_result(parts, errors)
        analysis = self._warranty_route_analysis()
        currency = analysis['currency']
        amounts = analysis['amounts']

        def money(value):
            return format_amount(self.env, value, currency)
        parts.append(Markup('<p><b>%s</b> %s &#183; %s %s &#183; %s %s &#183; %s %s</p>') % (
            _("Routing amount:"), money(amounts['routing']), _("Covered:"),
            money(amounts['covered']), _("Not Covered:"), money(amounts['not_covered']),
            _("Goodwill:"), money(amounts['goodwill'])))
        yes, no, goodwill = _("Yes"), _("No"), _("(goodwill)")
        rows = Markup('').join(
            Markup('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>') % (
                rule.name, summary, rule.company_id.name,
                yes if rule in analysis['matched'] else no)
            for rule, summary in [(rule, self._warranty_rule_summary(rule, money))
                                  for rule in analysis['rules']])
        parts.append(Markup(
            '<h5>%s</h5><table class="table table-sm"><thead><tr><th>%s</th><th>%s</th>'
            '<th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table>') % (
            _("Approval rules"), _("Rule"), _("Condition / levels"), _("Company"),
            _("Matches"), rows or Markup('<tr><td colspan="4">%s</td></tr>') % _(
                "No active approval rule for %s.", self.company_id.name)))
        if analysis['matched'] and not analysis['levels']:
            parts.append(Markup('<p><b>%s</b></p>') % _(
                "No approval required (rule %s): the request is approved at submission.",
                ', '.join(analysis['matched'].mapped('name'))))
        if analysis['levels']:
            rows = Markup('').join(
                Markup('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>') % (
                    info['label'],
                    ', '.join(info['rules'].mapped('name'))
                    + (' ' + goodwill if info['forced'] else ''),
                    ', '.join(info['eligible'].mapped('name')) or '-',
                    '; '.join('%s (%s)' % (user.name, ', '.join(reasons))
                              for user, reasons in info['excluded']) or '-')
                for info in analysis['levels'])
            parts.append(Markup(
                '<h5>%s</h5><table class="table table-sm"><thead><tr><th>%s</th><th>%s</th>'
                '<th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table>') % (
                _("Required approval levels"), _("Level"), _("Required by"),
                _("Eligible approvers"), _("Excluded approvers (reason)"), rows))
            skipped = [label for level, label in APPROVAL_LEVELS
                       if level not in [info['level'] for info in analysis['levels']]]
            if skipped:
                parts.append(Markup('<p>%s</p>') % _("Not required: %s.", ', '.join(skipped)))
        return self._warranty_preview_result(parts, errors + analysis['errors'])

    def _warranty_preview_result(self, parts, errors):
        if errors:
            parts.insert(0, Markup('<div class="alert alert-danger" role="alert"><b>%s</b>'
                                   '<ul>%s</ul></div>') % (
                _("This request cannot be submitted:"),
                Markup('').join(Markup('<li>%s</li>') % error for error in errors)))
        else:
            parts.insert(0, Markup('<div class="alert alert-success" role="alert">%s</div>')
                         % _("The request can be submitted with this route."))
        return not errors, Markup('').join(parts)

    def _warranty_rule_summary(self, rule, money):
        conditions = []
        if rule.min_amount:
            conditions.append(_("from %s", money(rule.min_amount)))
        if rule.max_amount:
            conditions.append(_("below %s", money(rule.max_amount)))
        if rule.coverage_condition and rule.coverage_condition != 'any':
            conditions.append(dict(rule._fields['coverage_condition']._description_selection(
                rule.env))[rule.coverage_condition])
        if rule.goodwill_condition == 'goodwill':
            conditions.append(_("goodwill lines"))
        if rule.product_ids:
            conditions.append(_("products: %s",
                                ', '.join(rule.product_ids.mapped('display_name'))))
        if rule.categ_ids:
            conditions.append(_("categories: %s",
                                ', '.join(rule.categ_ids.mapped('display_name'))))
        levels = _("No Approval Required") if rule.no_approval else ', '.join(
            '%s (%s)' % (label, ', '.join(rule[level + '_user_ids'].mapped('name')))
            for level, label in APPROVAL_LEVELS if rule[level + '_required'])
        return '%s: %s' % (', '.join(conditions) or _("any amount"), levels)
