import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Phase 5.9 (K-1 / K-7, report B).

    * The computed end status of 5.6 is now *Reconciled*; requests are only *Closed* by the
      formal Close. Existing requests are recomputed: those computed Closed before become
      Reconciled - no closing user or date is invented, nothing is reopened.
    * Credit note allocations of single-line claims get that claim line (exact, not a
      distribution); allocations of multi-line claims stay claim-level (reported as Unassigned).
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Mrf = env['material.purchase.requisition']
    requests = Mrf.with_context(active_test=False).search([('is_warranty_mrf', '=', True)])
    env.add_to_compute(Mrf._fields['warranty_mrf_status'], requests)
    requests.flush_recordset(['warranty_mrf_status'])
    cr.execute("""
        UPDATE warranty_vendor_claim_recovery rec
           SET claim_line_id = single.line_id
          FROM (SELECT claim_id, MIN(id) AS line_id FROM warranty_vendor_claim_line
                 GROUP BY claim_id HAVING COUNT(*) = 1) single
         WHERE rec.claim_id = single.claim_id AND rec.claim_line_id IS NULL
    """)
    _logger.info("Phase 5.9 upgrade: %s warranty requests recomputed, %s claim allocations "
                 "assigned to their claim line.", len(requests), cr.rowcount)
