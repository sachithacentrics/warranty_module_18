"""Run a script against a database with ONLY the given config (the Windows Odoo launcher also reads
the odoo.conf next to odoo-bin, which would add other addons paths).
Usage: python run_with_conf.py <conf> <db> <script.py>   (the script gets `env`, superuser)"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get('ODOO_ROOT', r'E:\odoo-env\odoo-v18-03022026'),
                                'server'))
import odoo  # noqa: E402
from odoo import api, SUPERUSER_ID  # noqa: E402

conf, db, script = sys.argv[1:4]
odoo.tools.config.parse_config(['-c', conf, '-d', db, '--log-level=warn', '--no-http'])
registry = odoo.modules.registry.Registry.new(db)
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    exec(open(script, encoding='utf-8').read(), {'env': env, '__name__': '__amc_script__'})
