"""Generate the web asset bundles of a freshly restored demo database before recording.
Odoo builds the JS / CSS bundles on their first request (several seconds of blank screen), which
would otherwise be recorded and make the first clicks miss. Logs in, opens the login page and the
backend, and downloads every bundle they reference.
Usage: warm_assets.py <base_url> <db> <login> <password>"""
import http.cookiejar
import json
import re
import sys
import urllib.request

BASE, DB, LOGIN, PASSWORD = sys.argv[1:5]
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(path):
    with opener.open(BASE + path, timeout=600) as response:
        return response.read().decode('utf-8', 'replace')


def bundles(page):
    return sorted(set(re.findall(r'(?:src|href)="(/web/assets/[^"]+)"', page)))


login_page = get('/web/login?db=%s' % DB)
request = urllib.request.Request(
    BASE + '/web/session/authenticate', headers={'Content-Type': 'application/json'},
    data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': DB, 'login': LOGIN, 'password': PASSWORD}}).encode())
with opener.open(request, timeout=120) as response:
    if 'error' in json.loads(response.read()):
        sys.exit('login failed')
for path in bundles(login_page) + bundles(get('/odoo')):
    get(path)
    print('BUNDLE', path)
