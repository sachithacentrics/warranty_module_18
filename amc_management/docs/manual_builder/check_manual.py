"""Visual check of Configuration > Documents > User Manual on the demo server: menu, page,
sidebar navigation, topic search, image zoom and mobile layout (screenshots m1..m6 + console
errors). Usage: check_manual.py <base_url> <out_dir>   (login admin / admin)"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket

BASE, OUT = sys.argv[1], sys.argv[2]
DB = os.environ.get('AMC_DEMO_DB', 'amc_demo')
CHROME = os.environ.get('CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
os.makedirs(OUT, exist_ok=True)
proc = subprocess.Popen([CHROME, '--headless=new',
                         '--remote-debugging-port=9335', '--user-data-dir=%s' % tempfile.mkdtemp(),
                         '--window-size=1440,900', '--hide-scrollbars', 'about:blank'])
for _ in range(50):
    try:
        t = [x for x in json.load(urllib.request.urlopen('http://127.0.0.1:9335/json')) if x['type'] == 'page'][0]
        break
    except Exception:
        time.sleep(0.3)
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=60)
n = [0]
errors = []


def cdp(method, **params):
    n[0] += 1
    ws.send(json.dumps({'id': n[0], 'method': method, 'params': params}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get('method') == 'Runtime.exceptionThrown':
            errors.append(msg['params']['exceptionDetails'].get('text'))
        if msg.get('id') == n[0]:
            return msg.get('result', {})


def js(expr):
    return cdp('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)['result'].get('value')


def shot(name, w=1440, h=900):
    cdp('Emulation.setDeviceMetricsOverride', width=w, height=h, deviceScaleFactor=1, mobile=w < 600)
    time.sleep(0.6)
    open(os.path.join(OUT, name + '.png'), 'wb').write(base64.b64decode(
        cdp('Page.captureScreenshot', format='png')['data']))
    print('SHOT', name)


def go(url, wait=3):
    cdp('Page.navigate', url=url)
    time.sleep(wait)


cdp('Page.enable'); cdp('Runtime.enable')
go(BASE + '/web/login?db=%s' % DB)
js("document.querySelector('input[name=login]').value='admin';document.querySelector('input[name=password]').value='admin';document.querySelector('form').submit()")
time.sleep(4)
go(BASE + '/odoo/action-amc_management.amc_contract_action', 4)
js("[...document.querySelectorAll('.o_menu_sections button, .o_menu_sections .dropdown-toggle')].find(e=>e.textContent.trim()==='Configuration').click()")
time.sleep(1)
shot('m1_config_menu')
print('MENU ITEMS', js("[...document.querySelectorAll('.o-dropdown--menu .dropdown-item, .o-dropdown--menu .dropdown-header, .o_menu_sections .o-dropdown--menu *')].map(e=>e.textContent.trim()).filter(Boolean).filter((v,i,a)=>a.indexOf(v)===i).join(' | ')"))
go(BASE + '/amc_management/user_manual', 3)
print('TITLE', js('document.title'), 'TOC links', js("document.querySelectorAll('nav.toc a').length"),
      'figures', js("document.querySelectorAll('figure').length"))
shot('m2_manual_top')
js("document.querySelector('nav.toc a[href*=\"creating-a-service-request\"]').click()")
time.sleep(4)
shot('m3_manual_nav_section')
print('HEADING TOP', js("Math.round(document.getElementById('creating-a-service-request').getBoundingClientRect().top)"))
print('ACTIVE', js("[...document.querySelectorAll('nav.toc a.active')].map(a=>a.textContent).join(' / ')"))
js("document.querySelector('#toc-search').value='renew';document.querySelector('#toc-search').dispatchEvent(new Event('input'))")
time.sleep(0.5)
shot('m4_toc_search')
js("document.querySelector('#toc-search').value='';document.querySelector('#toc-search').dispatchEvent(new Event('input'))")
js("document.querySelector('figure .zoom').click()")
time.sleep(0.8)
shot('m5_lightbox')
js("document.getElementById('lightbox').click()")
shot('m6_mobile', 420, 860)
print('JS ERRORS', errors or 'none')
ws.close(); proc.terminate()
