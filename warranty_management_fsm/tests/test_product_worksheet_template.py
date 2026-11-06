from datetime import timedelta

from lxml import etree

from odoo import fields
from odoo.tests import Form, tagged

from .common import ServiceJobCommon

# Product warranty values that stay read-only while a Warranty Policy applies.
POLICY_CONTROLLED = ('warranty_basis', 'default_warranty_period', 'default_warranty_period_unit',
                     'default_free_service_count', 'free_service_frequency',
                     'free_service_frequency_unit')


@tagged('post_install', '-at_install', 'warranty_fsm')
class TestProductWorksheetTemplate(ServiceJobCommon):
    """SRS 2.7 fix (approved): the product Worksheet Template is editable also when a Warranty
    Policy applies; Product -> Free Service -> Service Job resolution unchanged."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tech = cls._user('pwt_tech', 'industry_fsm.group_fsm_user')
        cls.template = cls.env['worksheet.template'].create({
            'name': 'Product AC Checklist', 'res_model': 'warranty.job.worksheet'})

    def _arch_fields(self):
        arch = etree.fromstring(self.env['product.template'].get_view(view_type='form')['arch'])
        return {node.get('name'): node for node in arch.iter('field')}

    def test_131_editable_with_policy_others_readonly(self):
        """With the category Warranty Policy applying, the Worksheet Template is selected and
        saved; the policy-controlled values stay read-only."""
        product = self.product.product_tmpl_id
        self.assertTrue(product.warranty_policy_applicable)
        nodes = self._arch_fields()
        self.assertFalse(nodes['warranty_worksheet_template_id'].get('readonly'))
        for name in POLICY_CONTROLLED:
            self.assertIn('warranty_policy_applicable', nodes[name].get('readonly') or '', name)
        with Form(product) as form:
            form.warranty_worksheet_template_id = self.template
            with self.assertRaises(AssertionError):  # policy value: read-only / hidden
                form.default_warranty_period = 99
        self.assertEqual(product.warranty_worksheet_template_id, self.template)
        self.assertEqual(product.warranty_applied_policy_id, self.policy)

    def test_132_new_free_services_inherit_existing_unchanged(self):
        """New free services take the product template (Part 2 snapshot); the snapshots of
        existing free services are not updated."""
        existing = self.card.service_entitlement_ids
        before = {service: service.worksheet_template_id for service in existing}
        self.product.product_tmpl_id.warranty_worksheet_template_id = self.template
        new_card = self._card()
        self.assertEqual(set(new_card.service_entitlement_ids.mapped('worksheet_template_id')),
                         {self.template})
        for service in existing:
            self.assertEqual(service.worksheet_template_id, before[service])

    def _confirmed(self, services=None, case_type=None):
        case = self._approved(services, case_type=case_type)
        job = self._prepare(case)
        job.with_user(self.helpdesk_user).write({
            'planned_date': fields.Datetime.now() + timedelta(days=1),
            'main_technician_id': self.tech.id})
        job.with_user(self.helpdesk_user).action_prepare_for_confirmation()
        job.with_user(self.helpdesk_user).action_confirm_job()
        self.assertEqual(job.state, 'confirmed')
        return job

    def test_133_warranty_only_job_instance(self):
        """A new Warranty Only job creates its worksheet instance with the product template."""
        self.product.product_tmpl_id.warranty_worksheet_template_id = self.template
        sheet = self._confirmed().worksheet_ids
        self.assertEqual((len(sheet), sheet.template_id, sheet.product_id),
                         (1, self.template, self.product))
        record = sheet.with_user(self.tech)._worksheet_record()
        self.assertEqual(record.x_warranty_job_worksheet_id, sheet)

    def test_134_free_service_job_instances(self):
        """A new free-service job: one instance per service with the resolved template (the
        service snapshot, else the product template) and independent checklist records."""
        self.product.product_tmpl_id.warranty_worksheet_template_id = self.template
        s1, s2 = self.card.service_entitlement_ids.sorted('service_no')[:2]
        job = self._confirmed(s1 | s2, case_type='free_service')
        sheets = job.worksheet_ids
        self.assertEqual(sheets.entitlement_id, s1 | s2)
        self.assertEqual(sheets.template_id, self.template)
        records = [sheet.with_user(self.tech)._worksheet_record() for sheet in sheets]
        self.assertEqual(len(set(records)), 2)
