"""AMC 18.0.1.1.0 (phases A4-A6) - data migration (docs/14_AMC_Data_Migration_Plan.md).

Contracts sold with 1.0.0 have no entitlements and no billing schedule:
* Awaiting Payment / Active contracts get their billing schedule from the confirmed Sales Order
  lines; periods already delivered on the order lines are marked released (no double
  delivery). Awaiting Payment: the first period is released so that it can be invoiced (its
  payment activates the contract, new 1.1.0 flow).
* Active contracts get their entitlements (visits from the start date) and billing dates; due
  periods are released by the next daily scheduler run, not here.
Re-runnable: contracts that already have visits / billing lines are skipped. No record is
deleted, no state or price is changed, no invoice is created.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True})
    from odoo.addons.amc_management.models.amc_contract import _marked

    contracts = env['amc.contract'].search([('state', 'in', ('awaiting_payment', 'active'))])
    for contract in contracts:
        with cr.savepoint():
            lines = contract.billing_line_ids
            if lines and (contract.state != 'active' or contract.visit_ids):
                continue  # already migrated (re-run)
            if not lines and contract.sale_order_id.state == 'sale':
                lines = contract._amc_generate_billing()
                delivered = {}
                for line in lines.sorted('sequence'):
                    sale_line = line.sale_line_id
                    done = delivered.get(sale_line.id, 0)
                    if done < sale_line.qty_delivered:
                        _marked(line).write({'state': 'released',
                                             'released_date': contract.activation_date})
                        delivered[sale_line.id] = done + 1
            if contract.state == 'awaiting_payment':
                if not lines.filtered(lambda line: line.state == 'released'):
                    lines.sorted('sequence')[:1]._amc_release()
            elif contract.state == 'active' and not contract.visit_ids:
                contract._amc_generate_visits()
                billing = contract.plan_id.billing_plan_id
                if lines.filtered(lambda line: not line.date):
                    # Dates only (no release here): the daily scheduler releases due periods.
                    contract._amc_schedule_billing(release=False)
                _logger.info("AMC migration: %s - %s visits, %s billing periods (%s).",
                             contract.name, len(contract.visit_ids), len(lines),
                             billing.name)
            contract._amc_log("Upgrade 18.0.1.1.0: AMC entitlements / billing schedule "
                              "generated for this contract sold with version 1.0.0.")
