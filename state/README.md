# Snapshots of the live servers

Written by `scripts/import.py` from the archives of `scripts/collect-vps.sh` and `scripts/collect-monitoring.sh`:
listening ports, firewall rules, versions, PostgreSQL roles, Docker containers, the redacted grafana.ini...
They are not deployed anywhere. They let you see in `git diff` what changed on a server between two imports.
