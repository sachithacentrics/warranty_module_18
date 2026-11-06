# Demo data for the AMC user manual screenshots (database amc_demo, run with run_with_conf.py).
# Every step is independent: a failure is printed and the script continues.
import traceback
from datetime import date, timedelta

from odoo import Command, fields

env = env  # noqa: F821
admin = env.ref('base.user_admin')
env = env(user=admin, context={'tz': 'Asia/Colombo', 'lang': 'en_US'})
company = env.company
today = fields.Date.context_today(env.user)
OUT = {}


def step(name):
    def wrap(func):
        try:
            with env.cr.savepoint():
                OUT[name] = func()
            print('OK', name, OUT[name])
        except Exception:
            print('FAILED', name)
            traceback.print_exc()
        return func
    return wrap


admin.groups_id |= (env.ref('amc_management.amc_management_group_manager') | env.ref('amc_management.amc_management_group_approver')
                    | env.ref('helpdesk.group_helpdesk_manager') | env.ref('industry_fsm.group_fsm_manager')
                    | env.ref('sales_team.group_sale_manager'))
admin.tz = 'Asia/Colombo'
company.write({'amc_activation_trigger': 'sale_confirmation', 'amc_offer_on_warranty_expiry': True,
               'amc_auto_create_mode': 'none', 'warranty_signoff_required': True,
               'warranty_worksheet_checklist_required': False,
               'warranty_worksheet_attachment_required': False})

category = env['product.category'].create({'name': 'Air Conditioners'})
ac = env['product.product'].create({'name': 'GREE 9000 BTU Wall Mounted A/C', 'type': 'consu',
                                     'categ_id': category.id, 'list_price': 185000})
ac24 = env['product.product'].create({'name': 'GREE 24000 BTU Cassette A/C', 'type': 'consu',
                                       'categ_id': category.id, 'list_price': 420000})
sheet = env['worksheet.template'].create({'name': 'A/C Preventive Maintenance Checklist',
                                          'res_model': 'warranty.job.worksheet'})
(ac | ac24).product_tmpl_id.write({'warranty_worksheet_template_id': sheet.id})
upfront = env.ref('amc_management.billing_plan_upfront')
quarterly = env.ref('amc_management.billing_plan_quarterly')

retail = env['amc.plan'].create({
    'name': 'Retail AMC', 'company_id': company.id, 'visit_count': 3, 'frequency_value': 3,
    'frequency_unit': 'year', 'included_free_services': 1, 'duration_value': 12,
    'billing_plan_id': upfront.id, 'pricing_method': 'per_unit', 'alert_days': 14,
    'grace_days': 15, 'auto_mark_missed': True, 'renewal_notice_days': 30,
    'renewal_rule': 'auto_offer', 'category_ids': [Command.set(category.ids)],
    'description': 'Three preventive visits per year and one on-demand service per unit.'})
project = env['amc.plan'].create({
    'name': 'Project AMC', 'company_id': company.id, 'visit_count': 2, 'frequency_value': 2,
    'frequency_unit': 'year', 'included_free_services': 0, 'duration_value': 12,
    'billing_plan_id': quarterly.id, 'pricing_method': 'tiered', 'alert_days': 21,
    'renewal_notice_days': 45, 'start_rule': 'manual', 'activation_trigger': 'payment'})
F = env['amc.pricing.formula']
f_retail = F.create({'plan_id': retail.id, 'method': 'per_unit', 'unit_rate': 12500,
                     'effective_from': date(2026, 1, 1), 'currency_id': company.currency_id.id,
                     'min_price': 25000, 'rounding_step': 100, 'sample_quantity': 3,
                     'factor_ids': [Command.create({'product_id': ac24.id, 'factor': 1.6})]})
f_retail.action_activate()
f_project = F.create({'plan_id': project.id, 'method': 'tiered', 'effective_from': date(2026, 1, 1),
                      'currency_id': company.currency_id.id, 'sample_quantity': 12,
                      'tier_ids': [Command.create({'from_value': 1, 'to_value': 10, 'rate': 5000}),
                                   Command.create({'from_value': 11, 'to_value': 25, 'rate': 4500}),
                                   Command.create({'from_value': 26, 'to_value': 0, 'rate': 4000})]})
f_project.action_activate()
draft_v2 = env['amc.pricing.formula'].browse(f_retail.action_new_version()['res_id'])
draft_v2.write({'unit_rate': 13500, 'effective_from': date(2027, 1, 1)})
company.amc_default_plan_id = retail

P = lambda xmlid: env.ref(xmlid)  # noqa: E731
gemini, azure, deco, lumber, ready = (P('base.res_partner_3'), P('base.res_partner_12'),
                                      P('base.res_partner_2'), P('base.res_partner_18'),
                                      P('base.res_partner_4'))
site = env['res.partner'].create({'name': 'Gemini Furniture - Colombo Showroom', 'type': 'delivery',
                                  'parent_id': gemini.id, 'street': 'No. 10, Galle Road'})


def contract(partner, plan, lines, **vals):
    return env['amc.contract'].create(dict({
        'partner_id': partner.id, 'company_id': company.id, 'plan_id': plan.id,
        'line_ids': [Command.create(line) for line in lines]}, **vals))


def sell(record):
    record.action_compute_price()
    record.action_create_quotation()
    record.sale_order_id.action_confirm()
    return record


@step('opportunity')
def _():
    opp = env['amc.opportunity'].create({'partner_id': ready.id, 'plan_id': retail.id,
                                         'expected_quantity': 8, 'expected_value': 100000,
                                         'description': '8 split units at the head office'})
    return opp.name


@step('draft')
def _():
    c = contract(azure, retail, [{'product_id': ac.id, 'quantity': 2, 'original_value': 370000},
                                 {'product_id': ac24.id, 'quantity': 1, 'original_value': 420000}])
    c.action_compute_price()
    return c.name


@step('override')
def _():
    c = contract(deco, retail, [{'product_id': ac.id, 'quantity': 4}])
    c.action_compute_price()
    req = env['amc.price.override'].create({'contract_id': c.id, 'override_type': 'price',
                                            'requested_price': 45000,
                                            'reason': 'Long-standing customer: 10% loyalty discount'})
    return req.name


@step('active')
def _():
    c = contract(gemini, retail, [{'product_id': ac.id, 'quantity': 3, 'site_id': site.id},
                                  {'product_id': ac24.id, 'quantity': 1, 'site_id': site.id}],
                 site_id=site.id)
    sell(c)
    c.action_create_invoice()
    OUT['active_id'] = c.id
    return c.name


@step('project_awaiting')
def _():
    c = contract(lumber, project, [{'product_id': ac.id, 'quantity': 12}],
                 start_date=today + timedelta(days=7))
    sell(c)
    return c.name, c.state


@step('expiring')
def _():
    manual = env['amc.plan'].create({
        'name': 'Retail AMC (Manual Start)', 'company_id': company.id, 'visit_count': 3,
        'frequency_value': 3, 'billing_plan_id': upfront.id, 'start_rule': 'manual',
        'renewal_rule': 'auto_offer', 'renewal_notice_days': 30, 'pricing_method': 'fixed'})
    F.create({'plan_id': manual.id, 'method': 'fixed', 'fixed_amount': 30000,
              'effective_from': date(2025, 1, 1), 'currency_id': company.currency_id.id}).action_activate()
    c = contract(deco, manual, [{'product_id': ac.id, 'quantity': 1}],
                 start_date=today - timedelta(days=345))
    sell(c)
    env['amc.contract']._cron_amc_daily()
    done = c.visit_ids.filtered(lambda v: v.state == 'pending' and v.due_date and v.due_date < today)
    for visit in done.sorted('due_date')[:2]:
        visit._amc_consume(visit.due_date, source='Service job (earlier visit)')
    return c.name, c.state, c.renewal_ids.name


@step('on_hold')
def _():
    c = contract(azure, project, [{'product_id': ac24.id, 'quantity': 4}],
                 start_date=today - timedelta(days=60))
    c.action_compute_price()
    c.action_create_quotation()
    c.sale_order_id.action_confirm()
    c._amc_activate('demo')
    c._amc_hold('Customer site under renovation until next month')
    return c.name, c.state


@step('service_chain')
def _():
    c = env['amc.contract'].browse(OUT['active_id'])
    team = env['helpdesk.team'].search([('company_id', '=', company.id)], limit=1)
    company.warranty_draft_job_team_id = team
    visits = c.visit_ids.filtered(lambda v: v.visit_type == 'preventive' and v.sequence_no == 1
                                  and v.product_id == ac)
    wizard = env['amc.service.request'].create({
        'visit_ids': [Command.set(visits.ids)], 'team_id': team.id,
        'description': 'First preventive maintenance of the showroom units'})
    case = env['warranty.case'].browse(wizard.action_confirm()['res_id'])
    OUT['case_id'] = case.id
    OUT['ticket_id'] = case.helpdesk_ticket_id.id
    checker = env.ref('base.user_demo')
    checker.groups_id |= env.ref('helpdesk.group_helpdesk_user') | env.ref('industry_fsm.group_fsm_user')
    company.warranty_case_approver_ids = [Command.set(admin.ids)]
    case.with_user(checker).action_check_eligibility()
    case.action_approve_case()
    job = env['warranty.service.job'].browse(case.action_prepare_service_job()['res_id'])
    if not env['hr.employee'].search([('user_id', '=', checker.id)]):
        env['hr.employee'].create({'name': checker.name, 'user_id': checker.id,
                                   'company_id': company.id})
    job.write({'planned_date': fields.Datetime.now() + timedelta(days=2),
               'main_technician_id': checker.id})
    job.action_prepare_for_confirmation()
    job.action_confirm_job()
    OUT['job_id'] = job.id
    other = env['helpdesk.ticket'].create({'name': 'Noise from the cassette unit',
                                           'team_id': team.id, 'partner_id': gemini.id})
    OUT['pending_ticket_id'] = other.id
    return case.name, case.state, job.name, job.state


@step('warranty_card')
def _():
    from odoo.addons.warranty_management.tests.common import confirm_and_group, set_installation
    policy = env['warranty.policy'].create({'name': 'Retail A/C Warranty', 'warranty_duration': 12,
                                            'warranty_duration_unit': 'months',
                                            'free_service_count': 0})
    wcat = env['product.category'].create({'name': 'Warranty A/C', 'warranty_policy_id': policy.id})
    prod = env['product.product'].create({
        'name': 'GREE 12000 BTU Inverter A/C', 'type': 'service', 'categ_id': wcat.id,
        'warranty_applicable': True, 'warranty_start_criterion': 'installation',
        'default_warranty_period': 12, 'default_warranty_period_unit': 'months',
        'default_free_service_count': 0})
    order = env['sale.order'].create({'partner_id': ready.id, 'order_line': [
        Command.create({'product_id': prod.id, 'product_uom_qty': 2})]})
    confirm_and_group(order)
    card = order.warranty_card_ids
    set_installation(card, today - timedelta(days=200))
    card.action_confirm_warranty()
    OUT['card_id'] = card.id
    return card.name, card.state


env.cr.commit()
print('RESULT', OUT)
