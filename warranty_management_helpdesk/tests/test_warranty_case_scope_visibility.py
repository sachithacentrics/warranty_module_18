from odoo.tests import tagged

from .test_warranty_case import TestWarrantyCase


@tagged('post_install', '-at_install', 'warranty_helpdesk')
class TestWarrantyCaseScopeVisibility(TestWarrantyCase):
    """BA decision 2026-10-28: the free service UI on Helpdesk ticket, Create Warranty Case
    wizard and Warranty Case is no longer limited by the company Warranty Scope Mode."""

    def test_91_free_services_whatever_the_mode(self):
        """Company in Warranty Only (kept, unused field): the confirmed card gets its free
        services, the ticket lists them as pending and a case links them."""
        for model in ('helpdesk.ticket', 'warranty.case', 'warranty.case.create.wizard'):
            self.assertNotIn('warranty_free_services_enabled', self.env[model]._fields, model)
        self.company.warranty_scope_mode = 'warranty_only'
        card = self._card()
        services = card.service_entitlement_ids
        self.assertTrue(services)
        ticket = self._ticket(warranty_product_id=self.product.id)
        self.assertEqual(ticket.warranty_pending_service_ids & services, services)
        case = self._create_case(ticket, service_entitlement_ids=[(6, 0, services[:1].ids)])
        self.assertEqual(case.service_entitlement_ids, services[:1])

    def test_92_view_conditions_removed_and_links_kept(self):
        """No Scope Mode condition remains; the other conditions and links are kept."""
        def arch(model):
            return ' '.join(self.env[model].get_view(view_type='form')['arch'].split())
        ticket_arch = arch('helpdesk.ticket')
        self.assertIn('<separator string="Pending Services"/>', ticket_arch)
        self.assertIn('name="warranty_pending_service_ids" readonly="1">', ticket_arch)
        wizard_arch = arch('warranty.case.create.wizard')
        self.assertIn('<separator string="Pending Services"/>', wizard_arch)
        self.assertIn('name="merged_adhoc_request"/>', wizard_arch)
        self.assertIn('invisible="not merged_adhoc_request"', wizard_arch)
        case_arch = arch('warranty.case')
        self.assertIn('name="linked_services">', case_arch)
        self.assertIn('name="pending_services">', case_arch)
        self.assertIn('name="merged_adhoc_request"/>', case_arch)
        self.assertIn('name="case_type"', case_arch)
        for model in ('helpdesk.ticket', 'warranty.case.create.wizard', 'warranty.case'):
            self.assertNotIn('warranty_free_services_enabled', arch(model), model)
        self.assertIn('invisible="not warranty_pending_service_count"', ticket_arch)
        # Links are data, not UI: changing the kept company field keeps them.
        card = self._card()
        service = card.service_entitlement_ids[:1]
        case = self._create_case(self._ticket(warranty_product_id=self.product.id),
                                 service_entitlement_ids=[(6, 0, service.ids)])
        self.company.warranty_scope_mode = 'amc'
        self.assertEqual(case.service_entitlement_ids, service)
