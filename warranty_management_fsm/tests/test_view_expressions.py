import os
import re

from lxml import etree

from odoo.tests import TransactionCase, tagged

# Functions the Odoo 18 web client cannot evaluate in view conditions (invisible, readonly,
# required, column_invisible).
FORBIDDEN = re.compile(r'\b(len|sum|min|max|any|all|sorted)\s*\(')
ATTRIBUTES = ('invisible', 'readonly', 'required', 'column_invisible')


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestViewExpressions(TransactionCase):
    """Regression: view conditions of the warranty modules use only expressions the web
    client evaluates (a len() condition crashed the Service Job form)."""

    def test_no_unsupported_functions_in_view_conditions(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        found = []
        for module in ('warranty_management', 'warranty_management_mrp',
                       'warranty_management_helpdesk', 'warranty_management_fsm'):
            for folder, __, files in os.walk(os.path.join(root, module)):
                for name in files:
                    if not name.endswith('.xml'):
                        continue
                    path = os.path.join(folder, name)
                    for node in etree.parse(path).iter():
                        for attribute in ATTRIBUTES:
                            value = node.get(attribute) if isinstance(node.tag, str) else None
                            if value and FORBIDDEN.search(value):
                                found.append('%s: %s="%s"' % (path, attribute, value))
        self.assertFalse(found, '\n'.join(found))
