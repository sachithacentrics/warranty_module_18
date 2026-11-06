"""Headless Chrome (DevTools protocol) screenshots of the AMC screens for the user manual.
Usage: python shots.py <base_url> <db> <login> <password> <out_dir>"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket

BASE, DB, LOGIN, PASSWORD, OUT = sys.argv[1:6]
CHROME = os.environ.get('CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
PORT = 9333
os.makedirs(OUT, exist_ok=True)
profile = tempfile.mkdtemp(prefix='amc_shots_')
proc = subprocess.Popen([CHROME, '--headless=new', '--remote-debugging-port=%s' % PORT,
                         '--user-data-dir=%s' % profile, '--window-size=1440,900',
                         '--hide-scrollbars', '--no-first-run', '--lang=en-US', 'about:blank'])
for _ in range(50):
    try:
        targets = json.load(urllib.request.urlopen('http://127.0.0.1:%s/json' % PORT))
        page = [t for t in targets if t['type'] == 'page'][0]
        break
    except Exception:
        time.sleep(0.3)
ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=60)
_id = [0]


def cdp(method, **params):
    _id[0] += 1
    ws.send(json.dumps({'id': _id[0], 'method': method, 'params': params}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get('id') == _id[0]:
            if 'error' in msg:
                raise RuntimeError(msg['error'])
            return msg.get('result', {})


def js(expression, await_promise=False):
    result = cdp('Runtime.evaluate', expression=expression, awaitPromise=await_promise,
                 returnByValue=True)
    return result.get('result', {}).get('value')


def wait_ready(extra=1.5, timeout=25):
    end = time.time() + timeout
    time.sleep(0.8)
    while time.time() < end:
        busy = js("!!document.querySelector('.o_loading_indicator, .o_blockUI') || "
                  "!document.querySelector('.o_action_manager, .o_home_menu, .o_login_main, form')")
        if not busy:
            break
        time.sleep(0.4)
    time.sleep(extra)


def goto(path):
    cdp('Page.navigate', url=BASE + path)
    wait_ready()


def rpc(model, method, args, kwargs=None):
    payload = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {
        'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {}}})
    expr = ("fetch('/web/dataset/call_kw', {method: 'POST', headers: {'Content-Type': "
            "'application/json'}, body: %s}).then(r => r.json()).then(r => JSON.stringify(r))"
            % json.dumps(payload))
    result = json.loads(js(expr, await_promise=True))
    if 'error' in result:
        raise RuntimeError(result['error']['data']['message'])
    return result['result']


def first(model, domain, order='id'):
    ids = rpc(model, 'search', [domain], {'limit': 1, 'order': order})
    return ids[0] if ids else None


def click(selector, text=None):
    script = """(() => { const els = [...document.querySelectorAll(%s)];
        const el = %s ? els.find(e => e.textContent.trim().includes(%s)) : els[0];
        if (!el) return false; el.click(); return true; })()""" % (
        json.dumps(selector), json.dumps(bool(text)), json.dumps(text or ''))
    done = js(script)
    wait_ready(1.2)
    return done


def tab(name):
    return click('.o_notebook .nav-link[name="%s"], .o_notebook a[name="%s"]' % (name, name)) \
        or click('.o_notebook .nav-link', name)


def shot(name, full=False):
    cdp('Emulation.setDeviceMetricsOverride', width=1440, height=900, deviceScaleFactor=1,
        mobile=False)
    data = cdp('Page.captureScreenshot', format='png', captureBeyondViewport=full)['data']
    with open(os.path.join(OUT, name + '.png'), 'wb') as handle:
        handle.write(base64.b64decode(data))
    print('SHOT', name)


cdp('Page.enable')
cdp('Runtime.enable')
goto('/web/login?db=%s' % DB)
js("document.querySelector('input[name=login]').value = %s;"
   "document.querySelector('input[name=password]').value = %s;"
   "document.querySelector('form').submit();" % (json.dumps(LOGIN), json.dumps(PASSWORD)))
wait_ready(3)

act = lambda xmlid, rid=None: '/odoo/action-%s%s' % (xmlid, '/%s' % rid if rid else '')  # noqa
A = 'amc_management.'
steps = []


def run(name, func):
    try:
        func()
    except Exception as error:  # keep going: report missing screenshots
        print('FAILED', name, error)


run('apps', lambda: (goto('/odoo'), shot('01_apps_menu')))
run('settings', lambda: (goto(act(A + 'action_amc_config_settings')), shot('02_settings')))
run('billing_plans', lambda: (goto(act(A + 'action_amc_billing_plan')), shot('03_billing_plans')))
plan = first('amc.plan', [('name', '=', 'Retail AMC')])
run('plan', lambda: (goto(act(A + 'action_amc_plan', plan)), shot('04_plan_form')))
run('plans', lambda: (goto(act(A + 'action_amc_plan')), shot('05_plan_list')))
formula = first('amc.pricing.formula', [('plan_id', '=', plan), ('state', '=', 'active')])
run('formula', lambda: (goto(act(A + 'action_amc_pricing_formula', formula)),
                        shot('06_formula_form')))
run('formulas', lambda: (goto(act(A + 'action_amc_pricing_formula')), shot('07_formula_list')))


def preview():
    goto(act(A + 'action_amc_plan', plan))
    click('button[name="action_open_pricing_preview"]')
    shot('08_price_preview')
run('preview', preview)
run('opportunities', lambda: (goto(act(A + 'action_amc_opportunity')), shot('09_opportunities')))
opp = first('amc.opportunity', [])
run('opportunity', lambda: (goto(act(A + 'action_amc_opportunity', opp)), shot('10_opportunity_form')))
run('contracts', lambda: (goto(act(A + 'action_amc_contract')), shot('11_contract_list')))
draft = first('amc.contract', [('state', '=', 'draft'), ('price_state', '=', 'calculated'),
                               ('override_ids', '=', False)])


def draft_contract():
    goto(act(A + 'action_amc_contract', draft))
    shot('12_contract_draft')
    tab('pricing')
    shot('13_contract_pricing')
run('draft', draft_contract)
override = first('amc.price.override', [])
run('override', lambda: (goto(act(A + 'action_amc_price_override', override)),
                         shot('14_override_request')))
active = first('amc.contract', [('state', '=', 'active'), ('sale_order_ids', '!=', False),
                                ('partner_id.name', 'ilike', 'Gemini')])


def active_contract():
    goto(act(A + 'action_amc_contract', active))
    shot('16_contract_active')
    tab('visits')
    shot('17_contract_visits')
    tab('billing')
    shot('18_contract_billing')
run('active', active_contract)
order = rpc('amc.contract', 'read', [[active], ['sale_order_id']])[0]['sale_order_id'][0]
run('quotation', lambda: (goto('/odoo/action-sale.action_quotations_with_onboarding/%s' % order),
                          shot('15_sales_order')))
run('visits', lambda: (goto(act(A + 'action_amc_contract_visit')), shot('19_visit_list')))


def visit_views():
    goto(act(A + 'action_amc_contract_visit'))
    click('.o_switch_view.o_kanban')
    shot('20_visit_kanban')
    click('.o_switch_view.o_calendar')
    shot('21_visit_calendar')
run('visit_views', visit_views)
pending = first('amc.contract.visit', [('contract_id', '=', active), ('state', '=', 'pending'),
                                       ('visit_type', '=', 'preventive')], order='due_date')


def visit_form():
    goto(act(A + 'action_amc_contract_visit', pending))
    shot('22_visit_form')
    click('button[name="action_open_service_request"]')
    shot('23_service_request_wizard')
run('visit_form', visit_form)
ticket = first('helpdesk.ticket', [('tag_ids.name', '=', 'AMC')])
case = first('warranty.case', [('case_type', '=', 'amc'), ('amc_contract_id', '!=', False)])
job = first('warranty.service.job', [('amc_contract_id', '!=', False)])


def ticket_form():
    goto('/odoo/action-helpdesk.helpdesk_ticket_action_main_tree/%s' % ticket)
    shot('24_helpdesk_ticket')
run('ticket', ticket_form)


def case_form():
    goto('/odoo/action-warranty_management_helpdesk.action_warranty_case/%s' % case)
    shot('25_warranty_case')
    tab('amc')
    shot('26_warranty_case_amc')
run('case', case_form)


def job_form():
    goto('/odoo/action-warranty_management_fsm.action_warranty_service_job/%s' % job)
    shot('27_service_job')
    tab('amc_visits')
    shot('28_service_job_amc_visits')
run('job', job_form)
other_ticket = first('helpdesk.ticket', [('name', '=', 'Noise from the cassette unit')])


def pending_ticket():
    goto('/odoo/action-helpdesk.helpdesk_ticket_action_main_tree/%s' % other_ticket)
    tab('amc_pending')
    shot('29_ticket_pending_amc')
run('pending', pending_ticket)
run('renewals', lambda: (goto(act(A + 'action_amc_contract_renewals')), shot('30_renewals')))
expiring = first('amc.contract', [('state', '=', 'expiring')])
run('expiring', lambda: (goto(act(A + 'action_amc_contract', expiring)), shot('31_contract_expiring')))
hold = first('amc.contract', [('state', '=', 'on_hold')])
run('hold', lambda: (goto(act(A + 'action_amc_contract', hold)), shot('32_contract_on_hold')))


def hold_wizard():
    goto(act(A + 'action_amc_contract', active))
    click('button[name="action_open_reason_wizard"]', 'Put On Hold')
    shot('33_hold_wizard')
run('hold_wizard', hold_wizard)
run('report', lambda: (goto(act(A + 'action_amc_visit_schedule_report')), shot('34_visit_schedule_report')))


def report_graph():
    goto(act(A + 'action_amc_visit_schedule_report'))
    click('.o_switch_view.o_graph')
    shot('35_visit_schedule_graph')
run('graph', report_graph)
card = first('warranty.card', [('state', '=', 'confirmed')], order='id desc')
run('card', lambda: (goto('/odoo/action-warranty_management.action_warranty_card/%s' % card),
                     shot('36_warranty_card_convert')))
run('quotations', lambda: (goto(act(A + 'action_amc_contract_quotations')), shot('37_quotations')))

ws.close()
proc.terminate()
