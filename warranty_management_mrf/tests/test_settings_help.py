from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'warranty_settings_help')
class TestWarrantySettingsHelp(TransactionCase):
    """Small Fix (2026-10-28): every visible setting of Settings > Warranty has a description
    and hover help; the Warranty Scope Mode is no longer shown (BA decision)."""

    def _settings(self):
        arch = etree.fromstring(self.env['res.config.settings'].get_view(
            view_type='form')['arch'])
        app = arch.xpath("//app[@name='warranty_management']")[0]
        return app, [setting for setting in app.iter('setting')
                     if setting.get('invisible') != '1']

    def test_01_every_visible_setting_has_help(self):
        app, settings = self._settings()
        self.assertEqual(len(settings), 63)  # + Inspection Worksheet Template (2026-10-29)
        self.assertNotIn('warranty_scope_mode', etree.tostring(app, encoding='unicode'))
        fields = self.env['res.config.settings']._fields
        for setting in settings:
            setting_id = setting.get('id')
            text = setting.get('help')
            self.assertTrue(text and len(text) >= 30, setting_id)
            first = next(iter(setting), None)
            if first is not None and first.tag == 'field':
                # The field label shows the field help as the hover "?" tooltip.
                self.assertEqual(fields[first.get('name')].help, text, setting_id)
            else:
                self.assertEqual(setting.get('title'), text, setting_id)

    def test_02_labelled_fields_have_hover_help(self):
        """Fields with their own label inside a setting (claim approvers) have help too."""
        fields = self.env['res.config.settings']._fields
        for name in ('warranty_claim_approver_ids', 'warranty_claim_finance_approver_ids',
                     'warranty_claim_finance_threshold', 'warranty_default_duration'):
            self.assertTrue(fields[name].help, name)

    def test_03_texts_match_behaviour(self):
        """Disabled Warranty Case Approval Required is a manual approval by Helpdesk users,
        never an automatic approval."""
        __, settings = self._settings()
        texts = {setting.get('id'): setting.get('help') for setting in settings}
        case = texts['warranty_case_approval_required']
        self.assertIn('any Helpdesk user', case)
        self.assertIn('manual step', case)
        self.assertNotIn('automatic', case.lower())
        self.assertEqual(texts['warranty_mrf_close_requires_invoice'], (
            "Enable this option to require customer-paid materials to be invoiced before "
            "closing a material request. If disabled, the request can be closed when all "
            "operational requirements are completed."))
        self.assertIn('vendor claims cannot be created', texts['warranty_vendor_claim_enabled'])
