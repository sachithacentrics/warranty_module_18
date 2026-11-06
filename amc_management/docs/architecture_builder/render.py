"""Render the Mermaid diagrams (<dir>/diagrams.json, exported from diagrams.js) to <dir>/<name>.png
with headless Chrome (Mermaid 10.9.1 from cdn.jsdelivr.net: internet access needed).
Usage: render.py <dir>"""
import base64
import html
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket

DIR = sys.argv[1]
diagrams = json.load(open(os.path.join(DIR, 'diagrams.json'), encoding='utf-8'))
blocks = '\n'.join('<div class="d" id="%s"><pre class="mermaid">%s</pre></div>' % (
    name, html.escape(src)) for name, src in diagrams.items())
page = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;background:#fff;font-family:Arial} .d{display:inline-block;padding:16px;
background:#fff} </style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
</head><body>%s<script>
mermaid.initialize({startOnLoad:false, theme:'default', securityLevel:'loose',
  themeVariables:{fontSize:'15px'}, flowchart:{htmlLabels:true, useMaxWidth:false}, sequence:{useMaxWidth:false},
  er:{useMaxWidth:false}, state:{useMaxWidth:false}});
mermaid.run({querySelector:'.mermaid'}).then(()=>{window.done=true}).catch(e=>{window.err=String(e)});
</script></body></html>""" % blocks
path = os.path.join(DIR, 'diagrams.html')
open(path, 'w', encoding='utf-8').write(page)

PORT = 9334
CHROME = os.environ.get('CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
proc = subprocess.Popen([CHROME, '--headless=new',
                         '--remote-debugging-port=%s' % PORT,
                         '--user-data-dir=%s' % tempfile.mkdtemp(), '--window-size=1600,1200',
                         'about:blank'])
for _ in range(50):
    try:
        target = [t for t in json.load(urllib.request.urlopen('http://127.0.0.1:%s/json' % PORT))
                  if t['type'] == 'page'][0]
        break
    except Exception:
        time.sleep(0.3)
ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=60)
counter = [0]


def cdp(method, **params):
    counter[0] += 1
    ws.send(json.dumps({'id': counter[0], 'method': method, 'params': params}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get('id') == counter[0]:
            return msg.get('result', {})


def js(expr):
    return cdp('Runtime.evaluate', expression=expr, returnByValue=True)['result'].get('value')


cdp('Page.enable')
cdp('Emulation.setDeviceMetricsOverride', width=1600, height=1200, deviceScaleFactor=2, mobile=False)
cdp('Page.navigate', url='file:///' + path.replace('\\', '/'))
for _ in range(120):
    if js('window.done === true') or js('window.err'):
        break
    time.sleep(0.5)
print('render error:', js('window.err'))
for name in diagrams:
    box = js("(() => {const r = document.getElementById('%s').getBoundingClientRect();"
             "return [r.x + window.scrollX, r.y + window.scrollY, r.width, r.height];})()" % name)
    data = cdp('Page.captureScreenshot', format='png', captureBeyondViewport=True,
               clip={'x': box[0], 'y': box[1], 'width': box[2], 'height': box[3], 'scale': 1})
    open(os.path.join(DIR, name + '.png'), 'wb').write(base64.b64decode(data['data']))
    print('PNG', name, int(box[2]), int(box[3]))
ws.close()
proc.terminate()
