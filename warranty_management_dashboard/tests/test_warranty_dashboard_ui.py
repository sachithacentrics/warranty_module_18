from odoo import Command
from odoo.tests import HttpCase, new_test_user, tagged

CHECKS = """
    const fail = (message) => console.error('dashboard: ' + message);
    const wait = (predicate, then, tries = 100) => {
        if (predicate()) { then(); }
        else if (tries) { setTimeout(() => wait(predicate, then, tries - 1), 100); }
        else { fail('timeout'); }
    };
    const root = () => document.querySelector('.o_warranty_dashboard');
    const areas = () => [...document.querySelectorAll('.o_warranty_dashboard .o_wd_area')];
    const text = (el) => el.textContent.replace(/\\s+/g, ' ').trim();
    const rpc = async (method, args) => {
        const response = await fetch('/web/dataset/call_kw/warranty.dashboard/' + method, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {
                model: 'warranty.dashboard', method, args, kwargs: {}}}),
        });
        return (await response.json()).result;
    };
"""


@tagged('post_install', '-at_install', 'warranty_dashboard')
class TestWarrantyDashboardUi(HttpCase):
    """The dashboard renders in the browser: five areas in two rows (3 + 2), the Warranty
    Cards by Status chart with exactly the server's status counts, the filter fields and the
    four report shortcuts; a date range switches the captions and the chart scope."""

    def test_01_dashboard_renders(self):
        user = new_test_user(self.env, login='wd_ui_user', groups='base.group_user')
        user.groups_id = [Command.set(self.env.ref('base.user_admin').groups_id.ids)]
        code = CHECKS + """
            const chartMatches = async (filters) => {
                const data = await rpc('get_dashboard_data', [filters]);
                const bars = [...document.querySelectorAll('.o_wd_bar_row')].map(
                    (row) => [row.dataset.state, Number(text(row.querySelector('.o_wd_bar_value')))]);
                const expected = (data.warranty.by_status || []).map((line) => [line.key, line.value]);
                return JSON.stringify(bars) === JSON.stringify(expected);
            };
            wait(() => areas().length === 5, async () => {
                const titles = areas().map((a) => text(a.querySelector('h2')));
                if (titles.join('|') !== 'Warranty Status|Pending Services|Approvals|Replacements|Escalations') {
                    return fail('areas ' + titles.join('|'));
                }
                const rows = [...document.querySelectorAll('.o_wd_row')].map((row) => row.querySelectorAll('.o_wd_area').length);
                if (rows.join(',') !== '3,2') {
                    return fail('rows ' + rows.join(','));
                }
                const fields = [...document.querySelectorAll('.o_wd_field > span')].map(text);
                if (fields.join('|') !== 'Company|Branch|Product Category|Card Status|Date From|Date To') {
                    return fail('filters ' + fields.join('|'));
                }
                if (!document.querySelector('.o_wd_chart_panel') || root().querySelector('canvas')) {
                    return fail('chart panel');
                }
                if (!(await chartMatches({}))) {
                    return fail('chart bars differ from the status counts');
                }
                const links = [...document.querySelectorAll('.o_wd_link')].map(text);
                if (links.join('|') !== 'Active / Expiring Warranty|Free Service Due|Draft Warranty Review|Warranty Unit Numbers') {
                    return fail('report links ' + links.join('|'));
                }
                const caption = () => text(areas()[0].querySelector('.o_wd_caption'));
                if (caption() !== 'Active warranties today') {
                    return fail('caption ' + caption());
                }
                const input = document.querySelectorAll('.o_wd_field input[type=date]')[0];
                input.value = '2026-01-01';
                input.dispatchEvent(new Event('change', { bubbles: true }));
                wait(() => caption() === 'Warranties in force in the period', async () => {
                    if (!(await chartMatches({date_from: '2026-01-01'}))) {
                        return fail('chart bars differ in the period');
                    }
                    console.log('test successful');
                });
            });
        """
        self.browser_js('/odoo/action-warranty_management_dashboard.action_warranty_dashboard',
                        code, login='wd_ui_user', timeout=120)
