from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Phase 5.7 (H-5): approved cost snapshot of requests approved before 5.7, only where the
    current line costs still add up to the recorded Approved Amount; legacy requests and
    mismatches stay Not Recorded."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['material.purchase.requisition']._warranty_migrate_approved_cost()
