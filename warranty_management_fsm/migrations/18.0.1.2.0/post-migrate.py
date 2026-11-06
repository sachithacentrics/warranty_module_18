"""18.0.1.2.0 - SRS service flow alignment: every existing service job comes from its warranty
case (Origin = Warranty Case). The customer / company / site / ticket / card values of the jobs
are unchanged (now stored computed fields taken from the same case). No other data changed."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("UPDATE warranty_service_job SET job_origin = 'case' WHERE job_origin IS NULL")
    _logger.info("Service job origin set to Warranty Case on %s job(s) without origin.",
                 cr.rowcount)
