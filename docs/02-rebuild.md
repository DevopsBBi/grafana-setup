# Rebuild a server from this repository

Use this when a server is reinstalled, replaced, or when its monitoring configuration was broken by hand.
The install scripts are **idempotent**: running them on a healthy server changes nothing, and every file they
replace is kept next to it as `<file>.bak-<date>`.

## 0. Before the first rebuild: import the live configuration

The repository must contain the real configuration of the servers. Files that still wait for it start with
`@@NOT-IMPORTED@@`, and the install scripts refuse to deploy them.

On your Mac, in the repository folder:

```bash
mkdir -p _import
# 1. copy the export scripts to the servers
scp scripts/collect-vps.sh devops@83.228.207.124:/tmp/
scp scripts/collect-monitoring.sh devops01@192.168.15.14:/tmp/
# 2. run them (read-only, they ask for your sudo password)
ssh -t devops@83.228.207.124 'sudo bash /tmp/collect-vps.sh'
ssh -t devops01@192.168.15.14 'sudo bash /tmp/collect-monitoring.sh'
# 3. bring the archives back
scp 'devops@83.228.207.124:/tmp/collect-vps-*.tgz' _import/
scp 'devops01@192.168.15.14:/tmp/collect-monitoring-*.tgz' _import/
# 4. import, review, commit
python3 scripts/import.py _import/*.tgz
git status && git diff
git add -A && git commit -m "Import live configuration" && git push
```

`import.py` prints a "To look at" list at the end (for example a secret it could not move out of a file). Fix those first.

## 1. Get the repository on the server

```bash
sudo apt-get install -y git
git clone https://github.com/DevopsBBi/grafana-setup.git ~/grafana-setup
cd ~/grafana-setup
```

## 2. Secrets

```bash
cp secrets.env.example secrets.env
chmod 600 secrets.env
nano secrets.env
```

| Variable | Needed on | Used for |
|---|---|---|
| `PG_MONITOR_PASSWORD` | VPS | PostgreSQL role `alloy_monitor` + `/etc/default/alloy` (`ALLOY_PG_DSN`) |
| `GRAFANA_PG_PASSWORD` | n8nserver | the `BBi` data source (read-only access to the application database) |
| `GRAFANA_ADMIN_PASSWORD` | n8nserver | sets the Grafana `admin` password (leave empty to keep it) |
| `TS_AUTHKEY` | both, optional | joins Tailscale without the login link (create a one-off key in the Tailscale console) |

Delete `secrets.env` when you are done if the server is shared: `shred -u secrets.env`.

## 3. Rebuild order

The VPS sends data to n8nserver, so **rebuild the monitoring server first** when both are new.

### Monitoring server (n8nserver)

```bash
sudo bash monitoring/install.sh
```

| Step | What it does |
|---|---|
| `tailscale` | installs Tailscale and joins the tailnet; warns if the address differs from `inventory.env` |
| `packages` | Grafana apt repository, `grafana`, `nginx`, `avahi`, `loki` (if no `loki` service exists), Docker |
| `loki` | installs `monitoring/loki/config.yaml` at `LOKI_CONFIG_PATH`, restarts Loki if it changed, waits for `/ready` |
| `prometheus` | installs `prometheus.yml`, starts the `vps_prometheus` container exactly as recorded in `container.env` (reloads it with SIGHUP when the configuration changed) |
| `grafana` | writes `settings.ini` into `grafana.ini` (port, dashboard.local address, SMTP via the VPS), provisions the data sources, sets the admin password |
| `dashboards` | copies the dashboard JSON to `/var/lib/grafana/dashboards/supervision` and provisions the folder "Supervision Odoo" |
| `alerting` | contact point, notification policy and the 5 rules; checks that the mail relay answers |
| `dashboard_local` | Nginx site + mDNS announcement + firewall rules for the office network |
| `firewall` | Loki and Prometheus allowed only from the VPS, only on Tailscale |
| `check` | runs `scripts/check.sh monitoring` |

Run a single step: `sudo bash monitoring/install.sh alerting`.
Recreate the Prometheus container (the data volume is kept): `sudo RECREATE_PROMETHEUS=1 bash monitoring/install.sh prometheus`.

### Application server (VPS)

```bash
sudo bash vps/install.sh
```

| Step | What it does |
|---|---|
| `tailscale` | installs Tailscale, joins the tailnet, checks that Loki answers through it |
| `alloy_package` | Grafana apt repository + `alloy` |
| `alloy_permissions` | `alloy` user in groups `adm` and `systemd-journal`; checks every log file of the configuration is readable |
| `pg_role` | creates/updates the `alloy_monitor` role (member of `pg_monitor`) |
| `alloy_config` | checks the syntax (`alloy fmt`), installs `config.alloy` and `/etc/default/alloy` (with the PostgreSQL password), restarts Alloy, waits for `/-/ready` |
| `postfix` | installs/configures the alert relay (listens on localhost + Tailscale only) |
| `firewall` | port 25 only for n8nserver, only on Tailscale |
| `check` | runs `scripts/check.sh vps` |

## 4. After a rebuild

```bash
bash scripts/check.sh vps          # on the VPS
bash scripts/check.sh monitoring   # on n8nserver
```

Then in Grafana: **Alerting > Contact points > Équipe supervision > Test** and check that the email arrives.

If a Tailscale address changed, update `APP_TS_IP` / `MON_TS_IP` in `inventory.env`, search the old address in
`vps/alloy/config.alloy` and `monitoring/` (`git grep 100.118.61.101`), fix it, commit, and run both install scripts again.
