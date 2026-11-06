#!/bin/bash
# Restore the demo database from its snapshot (database + filestore) before a re-recording.
# Overridable: PGBIN, FILESTORE, PGUSER, PGPASSWORD, DB, BASE.
export PGPASSWORD=${PGPASSWORD:-odoo18}
P=${PGBIN:-/e/other-installations/PostgreSQL/bin}
FS=${FILESTORE:-E:/odoo-env/odoo-v18-03022026/sessions/filestore}
U=${PGUSER:-odoo18}
DB=${DB:-amc_demo}
BASE=${BASE:-amc_demo_base}
$P/psql -h localhost -U "$U" -d postgres -tAc "select pg_terminate_backend(pid) from pg_stat_activity where datname='$DB'" >/dev/null
$P/dropdb -h localhost -U "$U" "$DB" && $P/createdb -h localhost -U "$U" -T "$BASE" "$DB" && echo "db restored"
rm -rf "${FS:?}/$DB" && cp -r "$FS/$BASE" "$FS/$DB" && echo "filestore restored"
