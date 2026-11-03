-- Role used by Grafana Alloy (prometheus.exporter.postgres) to read PostgreSQL statistics.
-- pg_monitor gives read access to statistics views only: no access to the application data.
-- Run: sudo -u postgres psql -v ON_ERROR_STOP=1 -v user=alloy_monitor -v pw='...' -f monitoring-role.sql
SELECT format('CREATE ROLE %I LOGIN', :'user')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'user') \gexec
ALTER ROLE :"user" WITH LOGIN PASSWORD :'pw';
GRANT pg_monitor TO :"user";
