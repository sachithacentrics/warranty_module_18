"""Upgrade of a database with amc_management < 18.0.1.2.0 (XML ids before the coding standards).

The records are kept and only their XML ids are renamed, so the groups (and their users), menus,
actions, rules and views are updated in place instead of being created a second time (a second
group "User" of the AMC category violates res_groups_name_uniq). Idempotent: an id is renamed
only when the old one exists and the new one does not.
"""
import logging

_logger = logging.getLogger(__name__)

RULES = ['amc_billing_line', 'amc_billing_plan', 'amc_contract', 'amc_contract_line',
         'amc_contract_visit', 'amc_opportunity', 'amc_plan', 'amc_price_override',
         'amc_pricing_factor', 'amc_pricing_formula', 'amc_pricing_rounding', 'amc_pricing_tier']

RENAMES = {
    # groups
    'group_amc_user': 'amc_management_group_user',
    'group_amc_coordinator': 'amc_management_group_coordinator',
    'group_amc_manager': 'amc_management_group_manager',
    'group_amc_approver': 'amc_management_group_approver',
    # record rules
    **{'%s_company_rule' % model: '%s_rule_company' % model for model in RULES},
    # actions
    'action_amc_billing_plan': 'amc_billing_plan_action',
    'action_amc_config_settings': 'res_config_settings_action',
    'action_amc_contract': 'amc_contract_action',
    'action_amc_contract_quotations': 'amc_contract_action_quotations',
    'action_amc_contract_renewals': 'amc_contract_action_renewals',
    'action_amc_contract_visit': 'amc_contract_visit_action',
    'action_amc_opportunity': 'amc_opportunity_action',
    'action_amc_plan': 'amc_plan_action',
    'action_amc_price_override': 'amc_price_override_action',
    'action_amc_pricing_formula': 'amc_pricing_formula_action',
    'action_amc_process_video': 'amc_management_action_process_video',
    'action_amc_technical_architecture': 'amc_management_action_technical_architecture',
    'action_amc_user_manual': 'amc_management_action_user_manual',
    'action_amc_visit_schedule_report': 'amc_contract_visit_action_schedule_report',
    'action_report_amc_visit_schedule': 'amc_contract_action_report_visit_schedule',
    # menus
    'menu_amc_root': 'amc_management_menu_root',
    'menu_amc_sales': 'amc_management_menu_sales',
    'menu_amc_services': 'amc_management_menu_services',
    'menu_amc_reporting': 'amc_management_menu_reporting',
    'menu_amc_configuration': 'amc_management_menu_configuration',
    'menu_amc_documents': 'amc_management_menu_documents',
    'menu_amc_user_manual': 'amc_management_menu_user_manual',
    'menu_amc_technical_architecture': 'amc_management_menu_technical_architecture',
    'menu_amc_process_video': 'amc_management_menu_process_video',
    'menu_amc_billing_plan': 'amc_billing_plan_menu',
    'menu_amc_contract': 'amc_contract_menu',
    'menu_amc_quotations': 'amc_contract_menu_quotations',
    'menu_amc_renewals': 'amc_contract_menu_renewals',
    'menu_amc_opportunity': 'amc_opportunity_menu',
    'menu_amc_plan': 'amc_plan_menu',
    'menu_amc_price_override': 'amc_price_override_menu',
    'menu_amc_pricing_formula': 'amc_pricing_formula_menu',
    'menu_amc_settings': 'res_config_settings_menu',
    'menu_amc_visits': 'amc_contract_visit_menu',
    'menu_amc_visit_schedule_report': 'amc_contract_visit_menu_schedule_report',
    # views
    'res_config_settings_view_form_amc': 'res_config_settings_view_form',
    'sale_order_view_form_amc': 'view_order_form',
    'amc_contract_cancel_wizard_view_form': 'amc_contract_cancel_view_form',
    'amc_contract_reason_wizard_view_form': 'amc_contract_reason_view_form',
    'amc_opportunity_lost_wizard_view_form': 'amc_opportunity_lost_view_form',
    'amc_price_override_reject_wizard_view_form': 'amc_price_override_reject_view_form',
    'amc_visit_action_wizard_view_form': 'amc_contract_visit_action_view_form',
    # access rights of the transient models (renamed without "wizard")
    'access_amc_contract_cancel_wizard_manager': 'access_amc_contract_cancel_manager',
    'access_amc_contract_reason_wizard_manager': 'access_amc_contract_reason_manager',
    'access_amc_opportunity_lost_wizard_user': 'access_amc_opportunity_lost_user',
    'access_amc_price_override_reject_wizard_approver':
        'access_amc_price_override_reject_approver',
    'access_amc_visit_action_wizard_coordinator': 'access_amc_contract_visit_action_coordinator',
}

# Inheriting views merged into their parent view: removed before the parent is updated (their
# xpath would no longer find its target).
OBSOLETE_VIEWS = ['amc_plan_view_form_pricing']


def rename_xmlids(cr, module, renames):
    for old, new in renames.items():
        cr.execute("""
            UPDATE ir_model_data SET name = %(new)s
             WHERE module = %(module)s AND name = %(old)s
               AND NOT EXISTS (SELECT 1 FROM ir_model_data
                                WHERE module = %(module)s AND name = %(new)s)
        """, {'module': module, 'old': old, 'new': new})
        if cr.rowcount:
            _logger.info("%s: XML id %s renamed to %s", module, old, new)


def remove_views(cr, module, names):
    for name in names:
        cr.execute("SELECT id, res_id FROM ir_model_data "
                   "WHERE module = %s AND name = %s AND model = 'ir.ui.view'", (module, name))
        for data_id, view_id in cr.fetchall():
            cr.execute("DELETE FROM ir_ui_view WHERE id = %s", (view_id,))
            cr.execute("DELETE FROM ir_model_data WHERE id = %s", (data_id,))
            _logger.info("%s: obsolete view %s removed", module, name)


def migrate(cr, version):
    if not version:
        return
    rename_xmlids(cr, 'amc_management', RENAMES)
    remove_views(cr, 'amc_management', OBSOLETE_VIEWS)
