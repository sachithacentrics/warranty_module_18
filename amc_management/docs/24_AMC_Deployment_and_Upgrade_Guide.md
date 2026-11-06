# 24 – AMC Deployment and Upgrade Guide

## 1. Modules

| Module | Version | Depends | Install |
|---|---|---|---|
| amc_management | 18.0.1.0.0 → **18.0.1.1.0** | mail, product, sale_management, stock | upgrade (`-u`) |
| amc_management_warranty | **18.0.1.0.0** (new) | amc_management, warranty_management | install (`-i`) – optional |
| amc_management_service | **18.0.1.0.0** (new) | amc_management, warranty_management_fsm | install (`-i`) – optional |
| warranty_meta_dependencies | 18.0.1.0.0 (depends list extended by the two bridges) | — | `-u` installs the bridges |

Neither bridge is `auto_install`; installing them changes nothing until configured
(Auto-create Mode defaults to *None*; the service chain only acts on AMC service requests). **Note:**
with `amc_management_service` installed, AMC visits can no longer be completed manually (they are
consumed by Service Job completion).

## 2. Steps

1. Backup: `pg_dump -Fc -h localhost -U odoo18 <db> > <db>_before_amc_110.dump` + filestore
   (`sessions/filestore/<db>`).
2. Trial: restore to `<db>_amc_check`; run
   `odoo-bin -c odoo.conf -d <db>_amc_check -u amc_management -i amc_management_warranty,amc_management_service --stop-after-init`;
   compare with the validation queries of `14_AMC_Data_Migration_Plan.md` §4.
3. Stop the server of the target database; run the same command on it; start the server.
4. Configuration: Settings > AMC (Activation Trigger, Warranty Integration), plans (planning mode,
   grace, renewal notice), Helpdesk SLA policy on tag **AMC** if needed, *Draft Job Helpdesk Team*
   (default team of AMC service requests), Warranty Worksheet template on products serviced in
   merged visits.
5. Check that the scheduled action **AMC: Daily Contract and Visit Scheduler** is active.

## 3. Post-deployment smoke tests

1. Open AMC Management > Contracts / Services / Reporting / Renewals.
2. Existing Active contracts: AMC Visits smart button shows the generated visits; billing tab dated.
3. Sell a test contract (SO confirmation trigger) → Active → visits generated.
4. Create a service request for one visit → ticket and AMC case created.
5. Warranty card: *Convert to AMC* visible on a confirmed card.

## 4. Rollback

Restore the backup dump + filestore and redeploy the 1.0.0 code (see 14 §6).
