from lxml import etree

from odoo.tools.safe_eval import safe_eval


def _filter_domain(model, name):
    """Domain of the search view filter `name`, as the web client applies it."""
    arch = etree.fromstring(model.get_view(view_type='search')['arch'])
    return safe_eval(arch.xpath(f"//filter[@name='{name}']")[0].get('domain'))
