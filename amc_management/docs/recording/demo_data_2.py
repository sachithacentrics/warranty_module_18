# Second pass: service chain (separate approver) and warranty card (company defaults).
import traceback
from datetime import timedelta

from odoo import Command, fields

env = env  # noqa: F821
admin = env.ref('base.user_admin')
env = env(user=admin, context={'tz': 'Asia/Colombo', 'lang': 'en_US'})
company = env.company
today = fields.Date.context_today(env.user)

try:
    with env.cr.savepoint():
        contract = env['amc.contract'].search([('name', '=', 'AMC/00003')])
        case = env['warranty.case'].search([('amc_contract_id', '=', contract.id)], limit=1)
        ac = env['product.product'].search([('name', '=', 'GREE 9000 BTU Wall Mounted A/C')])
        team = env['helpdesk.team'].search([('company_id', '=', company.id)], limit=1)
        company.warranty_draft_job_team_id = team
        if not case:
            visits = contract.visit_ids.filtered(lambda v: v.visit_type == 'preventive'
                                                 and v.sequence_no == 1 and v.product_id == ac)
            wizard = env['amc.service.request'].create({
                'visit_ids': [Command.set(visits.ids)], 'team_id': team.id,
                'description': 'First preventive maintenance of the showroom units'})
            case = env['warranty.case'].browse(wizard.action_confirm()['res_id'])
        groups = [env.ref('base.group_user').id, env.ref('helpdesk.group_helpdesk_user').id,
                  env.ref('industry_fsm.group_fsm_user').id]
        tech = env.ref('base.user_demo')
        tech.groups_id = [Command.link(g) for g in groups]
        manager = env['res.users'].create({'name': 'Service Manager', 'login': 'service.manager',
                                           'password': 'service.manager',
                                           'groups_id': [Command.set(groups)]})
        if not env['hr.employee'].search([('user_id', '=', tech.id)]):
            env['hr.employee'].create({'name': tech.name, 'user_id': tech.id,
                                       'company_id': company.id})
        company.warranty_case_approver_ids = [Command.set(manager.ids)]
        case.with_user(tech).action_check_eligibility()
        print('ELIGIBILITY', case.eligibility_result)
        case.with_user(manager).action_approve_case()
        job = env['warranty.service.job'].browse(case.action_prepare_service_job()['res_id'])
        job.write({'planned_date': fields.Datetime.now() + timedelta(days=2),
                   'main_technician_id': tech.id})
        job.action_prepare_for_confirmation()
        job.action_confirm_job()
        env['helpdesk.ticket'].create({'name': 'Noise from the cassette unit', 'team_id': team.id,
                                       'partner_id': contract.partner_id.id})
        print('OK service_chain', case.name, case.state, job.name, job.state,
              contract.visit_ids.filtered(lambda v: v.state == 'in_progress').mapped('name'))
except Exception:
    print('FAILED service_chain')
    traceback.print_exc()

try:
    with env.cr.savepoint():
        from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation
        company.write({'default_warranty_basis': 'period', 'default_start_criterion': 'installation',
                       'default_card_grouping_mode': 'per_so', 'default_warranty_duration': 12})
        policy = env['warranty.policy'].create({'name': 'Retail A/C Warranty', 'warranty_duration': 12,
                                                'warranty_duration_unit': 'months',
                                                'free_service_count': 0})
        wcat = env['product.category'].create({'name': 'Warranty A/C', 'warranty_policy_id': policy.id})
        prod = env['product.product'].create({
            'name': 'GREE 12000 BTU Inverter A/C', 'type': 'service', 'categ_id': wcat.id,
            'warranty_applicable': True, 'warranty_start_criterion': 'installation',
            'default_warranty_period': 12, 'default_warranty_period_unit': 'months',
            'default_free_service_count': 0})
        order = env['sale.order'].create({'partner_id': env.ref('base.res_partner_4').id,
                                          'order_line': [Command.create({'product_id': prod.id,
                                                                         'product_uom_qty': 2})]})
        confirm_and_group(order)
        card = order.warranty_card_ids
        set_installation(card, today - timedelta(days=200))
        card.action_confirm_warranty()
        print('OK warranty_card', card.name, card.state)
except Exception:
    print('FAILED warranty_card')
    traceback.print_exc()

env.cr.commit()
