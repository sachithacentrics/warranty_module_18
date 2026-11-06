"""Screen recording of the complete AMC process on the demo server (headless Chrome screencast).
Usage: record.py <base_url> <out_dir>   -> frames/*.jpg, frames.json, chapters.json
See README.md in this folder."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket

BASE, OUT = sys.argv[1], sys.argv[2]
FRAMES = os.path.join(OUT, 'frames')
os.makedirs(FRAMES, exist_ok=True)
for f in os.listdir(FRAMES):
    os.remove(os.path.join(FRAMES, f))
HERE = os.path.dirname(os.path.abspath(__file__))
# Environment overrides (defaults = the local Odoo 18 installation of this project).
ODOO_ROOT = os.environ.get('ODOO_ROOT', r'E:\odoo-env\odoo-v18-03022026')
ODOO_PY = os.environ.get('ODOO_PY', os.path.join(ODOO_ROOT, 'python', 'python.exe'))
ODOO_SERVER = os.path.join(ODOO_ROOT, 'server')
CONF = os.environ.get('ODOO_CONF', os.path.join(ODOO_SERVER, 'odoo.conf'))
CHROME = os.environ.get('CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
DB = os.environ.get('AMC_DEMO_DB', 'amc_demo')
RUNNER = os.path.join(HERE, 'run_with_conf.py')
HELPER = os.path.join(HERE, 'server_steps.py')

proc = subprocess.Popen([CHROME, '--headless=new',
                         '--remote-debugging-port=9336', '--user-data-dir=%s' % tempfile.mkdtemp(),
                         '--window-size=1440,900', '--hide-scrollbars', '--lang=en-US',
                         'about:blank'])
for _ in range(60):
    try:
        target = [t for t in json.load(urllib.request.urlopen('http://127.0.0.1:9336/json'))
                  if t['type'] == 'page'][0]
        break
    except Exception:
        time.sleep(0.3)
ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=120)
seq = [0]
frames = []
chapters = []
t0 = [None]


def handle(msg):
    if msg.get('method') == 'Page.screencastFrame':
        p = msg['params']
        ts = p['metadata']['timestamp']
        if t0[0] is None:
            t0[0] = ts
        name = 'f%05d.jpg' % len(frames)
        with open(os.path.join(FRAMES, name), 'wb') as handle_:
            handle_.write(base64.b64decode(p['data']))
        frames.append({'file': name, 't': ts})
        seq[0] += 1
        ws.send(json.dumps({'id': seq[0], 'method': 'Page.screencastFrameAck',
                            'params': {'sessionId': p['sessionId']}}))


def cdp(method, **params):
    seq[0] += 1
    my = seq[0]
    ws.send(json.dumps({'id': my, 'method': method, 'params': params}))
    while True:
        msg = json.loads(ws.recv())
        handle(msg)
        if msg.get('id') == my:
            if 'error' in msg:
                raise RuntimeError(msg['error'])
            return msg.get('result', {})


def pump(seconds):
    """Wait while processing screencast frames."""
    end = time.time() + seconds
    ws.settimeout(0.2)
    while time.time() < end:
        try:
            handle(json.loads(ws.recv()))
        except websocket.WebSocketTimeoutException:
            pass
    ws.settimeout(120)


def js(expr, await_promise=True):
    r = cdp('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=await_promise)
    if r.get('exceptionDetails'):
        print('JS EXCEPTION', r['exceptionDetails'].get('exception', {}).get('description', '')[:200])
    return r.get('result', {}).get('value')


OVERLAY = r"""
(() => {
  if (!document.getElementById('rec-style')) {
    const s = document.createElement('style'); s.id = 'rec-style';
    s.textContent = `
      #rec-cap{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:2147483646;
        background:rgba(30,22,34,.92);color:#fff;padding:12px 22px;border-radius:14px;
        font:500 17px/1.4 "Segoe UI",Arial,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.35);
        max-width:1100px;text-align:center;pointer-events:none;transition:opacity .3s}
      #rec-cap b{display:inline-block;background:#a26f97;color:#fff;border-radius:8px;padding:1px 9px;
        margin-right:10px;font-size:14px;vertical-align:1px}
      #rec-cur{position:fixed;z-index:2147483647;width:22px;height:22px;pointer-events:none;
        transition:left .7s ease, top .7s ease;left:720px;top:450px}
      #rec-cur svg{filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
      .rec-ring{position:fixed;z-index:2147483645;border:3px solid #ff9f1c;border-radius:12px;
        pointer-events:none;box-shadow:0 0 0 6px rgba(255,159,28,.25);animation:recpulse .9s ease-out}
      @keyframes recpulse{from{transform:scale(1.25);opacity:.2}to{transform:scale(1);opacity:1}}`;
    document.head.appendChild(s);
  }
  if (!document.getElementById('rec-cur')) {
    const c = document.createElement('div'); c.id = 'rec-cur';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M3 2l7 19 2.6-7.6L20 11z" fill="#fff" stroke="#111" stroke-width="1.5"/></svg>';
    c.style.left = (window.__recX || 720) + 'px'; c.style.top = (window.__recY || 450) + 'px';
    document.body.appendChild(c);
  }
})();
"""


def overlay():
    js(OVERLAY)


def caption(step, text, chapter=None):
    overlay()
    js("(() => {let c=document.getElementById('rec-cap'); if(!c){c=document.createElement('div');"
       "c.id='rec-cap';document.body.appendChild(c);} c.innerHTML=%s;})()"
       % json.dumps('<b>%s</b>%s' % (step, text) if step else text))
    if chapter:
        chapters.append({'title': chapter, 'wall': time.time()})


def point(selector, text=None, click=True, hold=0.9):
    """Move the cursor to the element, highlight it and click it."""
    found = None
    for _attempt in range(25):
        overlay()
        found = js("""(() => {const els=[...document.querySelectorAll(%s)].filter(e=>e.offsetParent!==null);
            const el=%s ? els.find(e=>e.textContent.trim().replace(/\\s+/g,' ').includes(%s)) : els[0];
            if(!el) return null; el.scrollIntoView({block:'center'}); const r=el.getBoundingClientRect();
            window.__recEl=el; return [r.x,r.y,r.width,r.height];})()""" % (
            json.dumps(selector), json.dumps(bool(text)), json.dumps(text or '')))
        if found:
            break
        pump(0.4)
    if not found:
        print('NOT FOUND', selector, text)
        return False
    x, y, w, h = found
    js("(() => {const c=document.getElementById('rec-cur'); window.__recX=%d; window.__recY=%d;"
       "c.style.left='%dpx'; c.style.top='%dpx'; const r=document.createElement('div');"
       "r.className='rec-ring'; Object.assign(r.style,{left:'%dpx',top:'%dpx',width:'%dpx',height:'%dpx'});"
       "document.body.appendChild(r); setTimeout(()=>r.remove(),%d);})()" % (
        x + w / 2, y + h / 2, x + w / 2, y + h / 2, x - 6, y - 6, w + 12, h + 12, int(hold * 1000) + 700))
    pump(hold)
    if click:
        js('window.__recEl.click()')
    return True


def type_into(selector, text, enter=False, delay=0.06):
    point(selector, hold=0.6)
    js('window.__recEl.focus(); if(window.__recEl.select) window.__recEl.select();')
    for ch in text:
        cdp('Input.insertText', text=ch)
        pump(delay)
    if enter:
        pump(1.4)
        for kind in ('rawKeyDown', 'keyUp'):
            cdp('Input.dispatchKeyEvent', type=kind, key='Enter', code='Enter',
                windowsVirtualKeyCode=13, nativeVirtualKeyCode=13)
    pump(0.6)


def goto(path, wait=3.0):
    cdp('Page.navigate', url=BASE + path if path.startswith('/') else path)
    pump(wait)
    overlay()


def idle(seconds=1.5):
    pump(seconds)


def rpc(model, method, args, kwargs=None):
    payload = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {
        'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {}}})
    res = json.loads(js("fetch('/web/dataset/call_kw',{method:'POST',headers:{'Content-Type':"
                        "'application/json'},body:%s}).then(r=>r.json()).then(r=>JSON.stringify(r))"
                        % json.dumps(payload)))
    if 'error' in res:
        raise RuntimeError(res['error']['data']['message'])
    return res['result']


def server_step(name, **params):
    env = dict(os.environ, AMC_STEP=name, AMC_PARAMS=json.dumps(params), TZ='UTC')
    out = subprocess.run([ODOO_PY, RUNNER, CONF, DB, HELPER], env=env,
                         capture_output=True, text=True, cwd=ODOO_SERVER)
    lines = [l for l in out.stdout.splitlines() if l.startswith('STEP')]
    print(name, lines or out.stderr[-600:])


def save():
    point('.o_form_button_save', hold=0.5)
    pump(1.5)


A = '/odoo/action-amc_management.'
cdp('Page.enable')
cdp('Runtime.enable')
cdp('Emulation.setDeviceMetricsOverride', width=1440, height=900, deviceScaleFactor=1, mobile=False)
cdp('Page.startScreencast', format='jpeg', quality=82, maxWidth=1440, maxHeight=900, everyNthFrame=1)

# ---------------------------------------------------------------- intro
cdp('Page.navigate', url='data:text/html;charset=utf-8,' + urllib.request.quote(
    '<html><body style="margin:0;height:100vh;display:grid;place-items:center;'
    'background:linear-gradient(135deg,#714b67,#3d2a39);font-family:Segoe UI,Arial;color:#fff">'
    '<div style="text-align:center"><div style="font-size:22px;opacity:.8;letter-spacing:2px">ODOO 18 · AMC MANAGEMENT</div>'
    '<div style="font-size:54px;font-weight:700;margin:14px 0">Annual Maintenance Contracts</div>'
    '<div style="font-size:24px;opacity:.9">Complete process walkthrough</div>'
    '<div style="margin-top:34px;font-size:17px;opacity:.75">Configure · Sell · Activate · Bill · Service · Renew · Report</div>'
    '</div></body></html>'))
chapters.append({'title': 'Introduction', 'wall': time.time()})
pump(4.5)

# ---------------------------------------------------------------- login
goto('/web/login?db=%s' % DB, 2)
caption('Start', 'Sign in to Odoo', chapter='Sign in')
type_into('input[name=login]', 'admin')
type_into('input[name=password]', 'admin')
point('button[type=submit]', hold=0.6)
pump(4)
overlay()
caption('Start', 'Open the AMC Management application')
point('.o_app[data-menu-xmlid="amc_management.amc_management_menu_root"], a.o_app', 'AMC Management', hold=1)
pump(3)

# ---------------------------------------------------------------- settings
# One caption per setting (<setting id> of res_config_settings_views.xml, both AMC modules).
SETTINGS = [
    ('amc_enabled', 'AMC Enabled – marks that this company works with Annual Maintenance '
     'Contracts. It is informational only: it does not hide or block the AMC menus'),
    ('amc_default_plan', 'Default AMC Plan – proposed on every new AMC opportunity, and used for '
     'the draft AMC created from a warranty card'),
    ('amc_default_pricelist', 'Default Pricelist – a fallback only: AMC prices use the customer\'s '
     'own pricelist, else the pricelist of its country group, else this one'),
    ('amc_currency', 'AMC Currency – contracts take the currency of that pricelist; without any '
     'pricelist this currency (read-only: fallback pricelist, else company) is used'),
    ('amc_default_billing_plan', 'Default Billing Plan – proposed for new AMC Plans: Upfront, '
     'Monthly, Quarterly, Half-yearly, Annual or Per Preventive Visit'),
    ('amc_default_start_rule', 'Default Start Criteria – proposed for new plans: coverage starts '
     'on the Activation Date, or on a Manual Start Date entered on the contract'),
    ('amc_default_renewal_rule', 'Default Renewal Rule – proposed for new plans: Manual, or Auto '
     'Offer (a renewal contract is prepared when the contract becomes Expiring)'),
    ('amc_activation_trigger', 'Activation Trigger – a contract becomes Active on Sales Order '
     'confirmation, or when the first invoice is paid. A plan can override it'),
    ('amc_product', 'AMC Service Product – the product on AMC quotation lines, a service invoiced '
     "on delivered quantities (empty: the module's AMC Contract Service)"),
    ('amc_default_alert_days', 'Default Alert Days – proposed for new plans: the alert activity '
     'is created this many days before a preventive visit is due'),
    ('amc_auto_create_mode', 'Warranty Integration · AMC Auto-create Mode – after a warranty card '
     'is confirmed: nothing, a draft AMC Opportunity or a draft AMC Contract (never active)'),
    ('amc_offer_on_warranty_expiry', 'Offer AMC on Warranty Expiry – when a warranty card '
     'expires, its warranty alert users get a to-do to offer an AMC'),
]
caption('1 · Configure', 'Configuration > Settings: the company-wide AMC settings (administrators)',
        chapter='1. Configuration – AMC settings')
if point('.o_menu_sections button, .o_menu_sections .dropdown-toggle', 'Configuration', hold=0.7):
    pump(1.2)
    point('.o-dropdown--menu .dropdown-item', 'Settings', hold=1.0)
    pump(4)
else:
    goto(A + 'res_config_settings_action', 4)
overlay()
idle(2.5)
# Shown instead when a setting is not visible (Default Pricelist needs Sales > Pricelists).
HIDDEN = {
    'amc_default_pricelist': ('amc_currency', 'Default Pricelist – appears here when Pricelists are '
                              "enabled (Sales > Settings): a fallback after the customer's and "
                              "its country group's pricelist"),
}
for setting_id, text in SETTINGS:
    visible = js("(() => {const e = document.getElementById(%s); return !!(e && e.offsetParent);})()"
                 % json.dumps(setting_id))
    if not visible:
        if setting_id not in HIDDEN:
            print('SETTING NOT VISIBLE', setting_id)
            continue
        setting_id, text = HIDDEN[setting_id]
    caption('1 · Configure', text)
    point('#%s' % setting_id, click=False, hold=1.2)
    idle(4.8)
caption('1 · Configure', 'The defaults are proposed for records created afterwards – existing plans '
        'and contracts keep their own values')
idle(3.5)

# ---------------------------------------------------------------- configuration
goto(A + 'amc_plan_action', 3)
caption('1 · Configure', 'AMC Plans define visits per year, free services, billing, duration and renewal rules',
        chapter='1. Configuration – AMC plans and pricing')
idle(2.5)
point('.o_data_row td.o_data_cell', 'Retail AMC', hold=0.8)
pump(3)
caption('1 · Configure', 'Retail AMC: 3 preventive visits per year + 1 free service per unit, alert 14 days before due')
idle(3.5)
point('.o_notebook .nav-link', 'Pricing Formulas', hold=0.6)
pump(1.5)
caption('1 · Configure', 'Each plan has versioned pricing formulas: Per Unit with minimum price and rounding')
point('.o_field_one2many .o_data_row td', 'Per Unit', hold=0.6)
pump(3)
idle(3)

# ---------------------------------------------------------------- new contract
goto(A + 'amc_contract_action', 3)
caption('2 · Sell', 'Create a new AMC contract', chapter='2. Create and price a contract')
idle(1.5)
point('.o_list_button_add, .o-kanban-button-new', hold=0.7)
pump(2.5)
overlay()
caption('2 · Sell', 'Customer, AMC plan and the covered equipment')
type_into('div[name=partner_id] input', 'Wood Corner', enter=True)
type_into('div[name=plan_id] input', 'Retail AMC', enter=True)
point('div[name=line_ids] .o_field_x2many_list_row_add a', hold=0.6)
pump(1.5)
type_into('.o_selected_row div[name=product_id] input', 'GREE 9000', enter=True)
type_into('.o_selected_row div[name=quantity] input', '2')
save()
caption('2 · Sell', 'Calculate Price – the formula in force today, with a full calculation breakdown')
point('button[name=action_compute_price]', hold=0.8)
pump(2.5)
point('.o_notebook .nav-link', 'Pricing', hold=0.6)
pump(1)
idle(3.5)
contract_id = int(js("location.pathname.split('/').pop()") or 0)
print('CONTRACT', contract_id)

# ---------------------------------------------------------------- quotation + activation
caption('3 · Activate', 'Create Quotation – a standard Sales quotation with locked AMC lines',
        chapter='3. Quotation, confirmation and activation')
point('button[name=action_create_quotation]', hold=0.8)
pump(3.5)
caption('3 · Activate', 'Confirm the Sales Order – the contract is activated (trigger: Sales Order confirmation)')
idle(1.5)
point('button[name=action_confirm]', 'Confirm', hold=0.9)
pump(3.5)
goto(A + 'amc_contract_action/%s' % contract_id, 3)
caption('3 · Activate', 'Active: preventive visits and free services are generated for every covered unit')
idle(2.5)
point('.o_notebook .nav-link', 'AMC Visits', hold=0.7)
pump(1)
idle(4)
caption('4 · Bill', 'Billing schedule: the upfront period is released for invoicing on the start date',
        chapter='4. Billing')
point('.o_notebook .nav-link', 'Billing Schedule', hold=0.7)
pump(1)
idle(3)
caption('4 · Bill', 'Create Invoice – a draft customer invoice of the released periods (standard Accounting)')
point('button[name=action_create_invoice]', hold=0.8)
pump(3.5)
idle(2.5)

# ---------------------------------------------------------------- visits + service request
goto(A + 'amc_contract_visit_action', 3)
caption('5 · Service', 'Services > AMC Visits: due dates, due indicator and status of every entitlement',
        chapter='5. Plan the service – AMC visits and service request')
idle(3)
point('.o_switch_view.o_kanban', hold=0.6)
pump(2.5)
point('.o_switch_view.o_calendar', hold=0.6)
pump(3)
point('.o_switch_view.o_list', hold=0.6)
pump(2.5)
caption('5 · Service', 'Select the first visits of both units of the new contract …')
visit_ids = rpc('amc.contract.visit', 'search', [[('contract_id', '=', contract_id),
                                                   ('visit_type', '=', 'preventive'),
                                                   ('sequence_no', '=', 1)]])
names = rpc('amc.contract.visit', 'read', [visit_ids, ['name']])
for rec in names:
    point('.o_data_row', rec['name'], click=False, hold=0.3)
    js("window.__recEl.querySelector('.o_list_record_selector input').click()")
    pump(0.6)
caption('5 · Service', '… and click Create Service Request (compatible visits are merged into one request)')
point('.o_control_panel button, .o_list_buttons button, .o_cp_buttons button', 'Create Service Request', hold=0.9)
pump(2.5)
overlay()
caption('5 · Service', 'A Helpdesk ticket and an AMC warranty case are created – mandatory Helpdesk-first chain')
point('.modal textarea, .modal div[name=description] textarea', hold=0.5)
js("window.__recEl.focus()")
for ch in 'First preventive maintenance – Wood Corner':
    cdp('Input.insertText', text=ch)
    pump(0.03)
pump(0.8)
point('.modal-footer button', 'Create Service Request', hold=0.9)
pump(3.5)
overlay()
case_id = rpc('warranty.case', 'search', [[('amc_contract_id', '=', contract_id)]], {'limit': 1, 'order': 'id desc'})[0]
goto('/odoo/action-warranty_management_helpdesk.action_warranty_case/%s' % case_id, 3)
print('CASE', case_id)

# ---------------------------------------------------------------- case, approval, job
caption('6 · Execute', 'Check Eligibility applies the AMC rules: active contract, coverage period, open visits',
        chapter='6. Helpdesk case, approval and Service Job')
point('button[name=action_check_eligibility]', hold=0.9)
pump(3)
idle(2)
server_step('approve', case_id=case_id)
goto('/odoo/action-warranty_management_helpdesk.action_warranty_case/%s' % case_id, 3)
caption('6 · Execute', 'The case was approved by the Service Manager (separation of duties)')
idle(2.5)
point('.o_notebook .nav-link', 'AMC', hold=0.6)
pump(1)
idle(3)
caption('6 · Execute', 'Prepare Service Job from the approved case')
point('button[name=action_prepare_service_job]', hold=0.9)
pump(3.5)
overlay()
job_id = rpc('warranty.service.job', 'search', [[('warranty_case_id', '=', case_id)]], {'limit': 1, 'order': 'id desc'})[0]
print('JOB', job_id)
server_step('plan_job', job_id=job_id)
goto('/odoo/action-warranty_management_fsm.action_warranty_service_job/%s' % job_id, 3)
caption('6 · Execute', 'Planned date and main technician are set – Prepare for Confirmation, then Confirm')
idle(2)
point('button[name=action_prepare_for_confirmation]', hold=0.8)
pump(2.5)
point('button[name=action_confirm_job]', hold=0.9)
pump(3.5)
overlay()
caption('6 · Execute', 'Confirmed: a Field Service visit and one worksheet per AMC visit; visits are In Progress')
point('.o_notebook .nav-link', 'AMC Visits', hold=0.6)
pump(1)
idle(4)

# ---------------------------------------------------------------- field service completion
server_step('complete_job', job_id=job_id)
goto('/odoo/action-warranty_management_fsm.action_warranty_service_job/%s' % job_id, 3)
caption('7 · Complete', 'The technician filled the worksheet, the customer signed and the visit was completed',
        chapter='7. Field Service completion and consumption')
idle(3.5)
point('.o_notebook .nav-link', 'AMC Visits', hold=0.6)
pump(1)
caption('7 · Complete', 'Both AMC visits are consumed once – with the job, visit and signature as evidence')
idle(4)
goto(A + 'amc_contract_action/%s' % contract_id, 3)
point('.o_notebook .nav-link', 'AMC Visits', hold=0.6)
pump(1)
caption('7 · Complete', 'On the contract: preventive visits completed / balance and the next due visit')
idle(4.5)

# ---------------------------------------------------------------- lifecycle
caption('8 · Lifecycle', 'Put On Hold (AMC Manager, with a reason) – no planning or alerts while on hold',
        chapter='8. Hold, expiry and renewal')
point('button[name=action_open_reason_wizard]', 'Put On Hold', hold=0.9)
pump(2)
overlay()
point('.modal div[name=reason] textarea', hold=0.5)
js("window.__recEl.focus()")
for ch in 'Customer site closed for renovation':
    cdp('Input.insertText', text=ch)
    pump(0.03)
pump(0.6)
point('.modal-footer button', 'Confirm', hold=0.8)
pump(3)
overlay()
idle(2)
caption('8 · Lifecycle', 'Resume returns the contract to Active')
point('button[name=action_resume]', hold=0.8)
pump(3)
goto(A + 'amc_contract_action_renewals', 3)
caption('8 · Lifecycle', 'Renewals: contracts inside the renewal notice become Expiring; Auto Offer prepares the renewal')
idle(3.5)
expiring = rpc('amc.contract', 'search', [[('state', '=', 'expiring')]], {'limit': 1})
goto(A + 'amc_contract_action/%s' % expiring[0], 3)
caption('8 · Lifecycle', 'An Expiring contract with its prepared renewal (Renewals smart button)')
idle(3)
point('button[name=action_view_renewals]', hold=0.8)
pump(3)
idle(2)

# ---------------------------------------------------------------- warranty
card = rpc('warranty.card', 'search', [[('state', 'in', ('confirmed', 'expired'))]], {'limit': 1, 'order': 'id'})
goto('/odoo/action-warranty_management.action_warranty_card/%s' % card[0], 3)
caption('9 · Warranty', 'From a warranty card: Convert to AMC creates a Draft AMC covering the card\'s units',
        chapter='9. Warranty to AMC')
idle(2)
point('button[name=action_convert_to_amc]', hold=0.9)
pump(3.5)
overlay()
caption('9 · Warranty', 'The new Draft contract is linked to the warranty card and its unit warranty numbers')
idle(4)

# ---------------------------------------------------------------- reports
goto(A + 'amc_contract_visit_action_schedule_report', 3.5)
caption('10 · Report', 'Reporting > AMC Visit Schedule: visits by AMC plan, month and status',
        chapter='10. Reports and documentation')
idle(3.5)
point('.o_switch_view.o_graph', hold=0.6)
pump(3.5)
goto(A + 'amc_contract_action', 3)
caption('10 · Report', 'Configuration > Documents > User Manual opens the illustrated user manual')
point('.o_menu_sections button, .o_menu_sections .dropdown-toggle', 'Configuration', hold=0.7)
pump(1.2)
point('.o-dropdown--menu .dropdown-item', 'User Manual', click=False, hold=1.6)
pump(1)
goto('/amc_management/user_manual', 3)
caption('', 'AMC Management – end of the walkthrough')
pump(4)

cdp('Page.stopScreencast')
pump(0.5)
json.dump(frames, open(os.path.join(OUT, 'frames.json'), 'w'))
start_wall = chapters[0]['wall']
json.dump([{'title': c['title'], 'start': round(c['wall'] - start_wall, 1)} for c in chapters],
          open(os.path.join(OUT, 'chapters.json'), 'w'), indent=1)
print('FRAMES', len(frames), 'DURATION', round(frames[-1]['t'] - frames[0]['t'], 1) if frames else 0)
ws.close()
proc.terminate()
