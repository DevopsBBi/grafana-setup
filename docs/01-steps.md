# Every step, with its commands

Generated from `tools/docs/build_steps.py` (same content as `docs/steps.json`). **recorded** = the command we ran; **equivalent** = the original command was not kept, this one does the same and is what the rebuild scripts use.

## A. Private network

### A1. Install Tailscale on both servers

**Where:** application server (VPS ov-ab27bf, user devops) and monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** equivalent

**Why:** Create a private, encrypted network between the cloud server and the office server, so monitoring data never travels on the open internet and no port has to be opened to the internet.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```
Downloads and runs Tailscale's official installer: it adds Tailscale's apt repository and installs the tailscale package and the tailscaled service.

```bash
sudo tailscale up
```
Joins this machine to your tailnet. It prints a login link: open it, sign in with the company account, approve the machine. The machine then gets a fixed private address in 100.64.0.0/10.

```bash
tailscale ip -4
```
Shows the machine's Tailscale address: 100.69.47.69 for the VPS (name 'vps'), 100.118.61.101 for n8nserver (name 'local-vm').

**Check:**

- `tailscale status` → Both machines are listed, the other one is not 'offline'.
- `tailscale ping 100.118.61.101   # from the VPS` → pong from local-vm ... via <direct path or DERP>

**In this repository:** inventory.env (APP_TS_IP, MON_TS_IP, APP_TS_NAME, MON_TS_NAME)

> Tailscale uses WireGuard. Traffic goes directly between the two machines (UDP 41641) or through Tailscale's relays, always encrypted end to end.

## B. Storage on the monitoring server

### B1. Loki: the logs database (port 3100)

**Where:** monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** equivalent

**Why:** Receive and store every log line sent by Alloy (application, database, website, system) and answer LogQL queries for Grafana.

```bash
sudo apt-get install -y loki   # from the Grafana apt repository
```
Installs Loki as the 'loki' systemd service with its configuration in /etc/loki/config.yml.

```bash
sudo nano /etc/loki/config.yml
```
Single-node configuration: storage on the local disk, HTTP port 3100, and the limits we set later (step D3).

```bash
sudo systemctl enable --now loki
```
Starts Loki now and at every boot.

**Check:**

- `curl -s http://127.0.0.1:3100/ready` → ready

**In this repository:** monitoring/loki/config.yaml (imported from the live server), inventory.env (LOKI_PORT, LOKI_CONFIG_PATH)

> The exact way Loki was installed is recorded by scripts/collect-monitoring.sh (state/monitoring/loki-unit.txt).

### B2. Prometheus in Docker: the metrics database (port 9091)

**Where:** monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** equivalent

**Why:** Store the measurements (CPU, memory, disk, network, database, programs) that Alloy pushes every 15 seconds.

```bash
docker run -d --name vps_prometheus --restart unless-stopped -p 9091:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml:ro -v vps_prom_data:/prometheus \
  prom/prometheus --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus --web.enable-remote-write-receiver
```
Runs Prometheus in a container named vps_prometheus. Port 9091 of the server goes to port 9090 of the container. --web.enable-remote-write-receiver lets Alloy PUSH metrics to /api/v1/write (Prometheus normally pulls). The data lives in a Docker volume, so recreating the container keeps the history.

**Check:**

- `curl -s http://127.0.0.1:9091/-/ready` → Prometheus Server is Ready.
- `docker ps --filter name=vps_prometheus` → Status 'Up ...'

**In this repository:** `monitoring/prometheus/prometheus.yml`, monitoring/prometheus/container.env (exact image, ports, volumes, arguments from docker inspect)

> A port published by Docker is reachable even if ufw does not allow it (Docker writes its own firewall rules). See docs/06-improvements.md.

### B3. Grafana (apt) on port 3001

**Where:** monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** equivalent

**Why:** Show the data as dashboards and send the email alerts. The older Grafana in Docker (mon_grafana, port 3000) was left as it was.

```bash
sudo apt-get install -y grafana
```
Installs Grafana from the Grafana apt repository (service grafana-server).

```bash
sudo sed -i 's/^;\?http_port = .*/http_port = 3001/' /etc/grafana/grafana.ini
```
Port 3000 was already used by the old Docker Grafana, so this one listens on 3001.

```bash
sudo systemctl enable --now grafana-server
```
Starts Grafana now and at every boot.

**Check:**

- `curl -s http://127.0.0.1:3001/api/health` → "database": "ok"

**In this repository:** `monitoring/grafana/settings.ini`

### B4. Firewall: only the VPS may send data, only through Tailscale

**Where:** monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** equivalent

**Why:** Loki and Prometheus accept data only from the VPS's Tailscale address.

```bash
sudo ufw allow in on tailscale0 from 100.69.47.69 to any port 3100 proto tcp
```
Allows the VPS (Tailscale address) to reach Loki, only on the Tailscale interface.

```bash
sudo ufw allow in on tailscale0 from 100.69.47.69 to any port 9091 proto tcp
```
Same for Prometheus.

**Check:**

- `timeout 5 bash -c '</dev/tcp/100.118.61.101/3100' && echo open   # from the VPS` → open

**In this repository:** monitoring/install.sh (step firewall)

## C. Collection on the application server

### C1. Install Grafana Alloy

**Where:** application server (VPS ov-ab27bf, user devops)  ·  **Commands:** equivalent

**Why:** One agent that reads the logs and measures the server, then sends everything to the office through Tailscale.

```bash
sudo mkdir -p /etc/apt/keyrings
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg >/dev/null
echo 'deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main' | sudo tee /etc/apt/sources.list.d/grafana.list
```
Adds Grafana's signed apt repository (the key proves the packages really come from Grafana).

```bash
sudo apt-get update && sudo apt-get install -y alloy
```
Installs Alloy: service 'alloy', configuration /etc/alloy/config.alloy, settings /etc/default/alloy, local web UI on 127.0.0.1:12345.

**Check:**

- `systemctl is-active alloy && alloy --version` → active, then the version

**In this repository:** vps/install.sh (steps alloy_package)

### C2. Let Alloy read the logs

**Where:** application server (VPS ov-ab27bf, user devops)  ·  **Commands:** equivalent

**Why:** Alloy runs as the unprivileged user 'alloy'; it needs read access to the log files and the system journal.

```bash
sudo usermod -aG adm,systemd-journal alloy
```
Group adm can read /var/log/nginx and /var/log/postgresql; group systemd-journal can read the journal.

```bash
sudo -u alloy test -r /path/to/odoo.log && echo readable
```
Checks that the application log file is readable by Alloy (path as written in config.alloy).

```bash
sudo systemctl restart alloy
```
A new group membership is only seen by a restarted process.

**Check:**

- `id alloy` → groups=...adm...systemd-journal

**In this repository:** vps/install.sh (step alloy_permissions)

### C3. PostgreSQL role for statistics only

**Where:** application server (VPS ov-ab27bf, user devops)  ·  **Commands:** equivalent

**Why:** Let Alloy read PostgreSQL's statistics (connections, cache, locks, size) without any access to the application data.

```bash
sudo -u postgres psql -c "CREATE ROLE alloy_monitor LOGIN PASSWORD '...';" -c "GRANT pg_monitor TO alloy_monitor;"
```
pg_monitor is a built-in PostgreSQL role that can read statistics views only.

**Check:**

- `sudo -u postgres psql -Atc "select pg_has_role('alloy_monitor','pg_monitor','member')"` → t

**In this repository:** `vps/postgres/monitoring-role.sql`, secrets.env (PG_MONITOR_PASSWORD)

### C4. Alloy configuration: logs and metrics

**Where:** application server (VPS ov-ab27bf, user devops)  ·  **Commands:** recorded

**Why:** Describe, block by block, what Alloy reads and where it sends it. Full explanation of every block: docs/03-alloy-explained.md.

```bash
sudo nano /etc/alloy/config.alloy
```
Logs: application (multi-line, level and logger extracted), PostgreSQL, Nginx (HTTP status extracted), systemd journal -> loki.write to http://100.118.61.101:3100. Metrics: server (unix exporter), programs (process exporter), PostgreSQL (postgres exporter), availability probes (blackbox), Alloy itself -> prometheus.remote_write to http://100.118.61.101:9091.

```bash
sudo alloy fmt /etc/alloy/config.alloy >/dev/null && echo syntax-ok
```
Checks the syntax before restarting (a typo would stop the whole collection).

```bash
sudo systemctl restart alloy
```
Loads the new configuration.

**Check:**

- `curl -s http://127.0.0.1:12345/-/ready` → Alloy is ready.
- `curl -s http://127.0.0.1:12345/api/v0/web/components | python3 -c 'import json,sys; print({c["health"]["state"] for c in json.load(sys.stdin)})'` → {'healthy'}

**In this repository:** `vps/alloy/config.alloy`, `vps/alloy/alloy.default.tmpl`, `docs/03-alloy-explained.md`

> We added the blocks with a small Python script that replaces each block by its name (safe to run twice). The repository now holds the whole file.

### C5. Check that everything arrives

**Where:** application server (VPS ov-ab27bf, user devops) and monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** recorded

**Why:** Prove that logs and metrics really reach the office, with no loss.

```bash
curl -s http://127.0.0.1:12345/metrics | grep -E 'prometheus_remote_storage_samples_(total|failed_total)'
```
On the VPS: how many measurements Alloy sent, and how many failed. At our check: over 700,000 sent, 0 failed.

```bash
curl -sG http://127.0.0.1:3100/loki/api/v1/query --data-urlencode 'query=sum(count_over_time({host="vps-web"}[5m]))'
```
On n8nserver: number of log lines received in the last 5 minutes.

```bash
curl -sG http://127.0.0.1:9091/api/v1/query --data-urlencode 'query=count(node_cpu_seconds_total{host="vps-web"})'
```
On n8nserver: the server's CPU measurements are in Prometheus.

**Check:**

- `bash scripts/check.sh vps   # and: bash scripts/check.sh monitoring` → All checks passed.

**In this repository:** `scripts/check.sh`

## D. Dashboards

### D1. Grafana data sources

**Where:** monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** recorded

**Why:** Tell Grafana where the data is.

```bash
Grafana > Connections > Data sources > Add: Loki, URL http://127.0.0.1:3100, name 'loki'
```
The logs. Name 'loki' is used by the dashboards and the alert rules.

```bash
Add: Prometheus, URL http://127.0.0.1:9091, access 'proxy', name 'prometheus-2'
```
The metrics. We had to fix its URL and access mode (step D3).

```bash
Existing PostgreSQL data source 'BBi' (read-only access to the application database)
```
Used for the user activity panels (who is connected, what they do).

**Check:**

- `Grafana > Data sources > each one > 'Save & test'` → green 'Data source is working'

**In this repository:** monitoring/grafana/provisioning/datasources/*.tmpl (generated from the live Grafana by scripts/import.py)

### D2. The four dashboards (generated as code)

**Where:** your Mac (generation) and monitoring server (office VM n8nserver, user devops01) (import)  ·  **Commands:** recorded

**Why:** Three dashboards for three questions (is it fast, what went wrong, is the server strong enough) plus user activity.

```bash
python3 tools/dashboards/make_activite.py      # 1. Activité et performances
python3 tools/dashboards/make_journaux.py      # 2. Journaux et erreurs
python3 tools/dashboards/make_ressources.py    # 3. Consommation du serveur (incl. the 31 application workers)
python3 tools/dashboards/make_utilisateurs.py  # 4. Activité des utilisateurs
```
Each script builds a dashboard JSON (panels, LogQL / PromQL / SQL queries, thresholds green/yellow/red) with the shared library dash_lib.py, into monitoring/grafana/dashboards/.

```bash
Grafana > Dashboards > New > Import > upload the JSON
```
How we loaded them at first. Now monitoring/install.sh loads them automatically (file provisioning).

**Check:**

- `Open each dashboard over the last hour` → No panel shows 'No data' or a red error triangle.

**In this repository:** `tools/dashboards/`, `monitoring/grafana/dashboards/*.json`, `monitoring/grafana/provisioning/dashboards/supervision.yaml.tmpl`

### D3. Fixes made along the way

**Where:** monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** recorded

**Why:** Problems we met and how we solved them.

```bash
limits_config:
  max_line_size: 256KB
  max_line_size_truncate: true
```
In the Loki configuration: very long application log lines (tracebacks) were rejected; now they are kept, cut at 256 KB.

```bash
PUT /api/datasources/uid/<uid> with url=http://127.0.0.1:9091 and access=proxy
```
The 'prometheus-2' data source pointed to a wrong address: CPU, memory and disk panels showed 'No data'.

```bash
{job="postgresql"} |~ " (ERROR|FATAL|PANIC):"
```
The PostgreSQL error panels used a 'level' label that PostgreSQL logs do not have: replaced by a text filter.

**Check:**

- `Dashboards over the last hour` → All panels have data.

**In this repository:** `monitoring/loki/config.yaml`

## E. Access from the office

### E1. http://dashboard.local on the office network

**Where:** monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** recorded

**Why:** An easy address that works from any computer or phone of the office network, and nowhere else.

```bash
sudo apt-get install -y nginx avahi-daemon avahi-utils
```
Nginx = web server in front of Grafana; Avahi = announces names on the local network (mDNS, the '.local' names).

```bash
/etc/nginx/sites-available/dashboard.local  (proxy_pass to Grafana) + ln -s into sites-enabled
```
Nginx answers on port 80 for the name dashboard.local and forwards to Grafana (including websockets for live updates).

```bash
/etc/systemd/system/avahi-alias-dashboard.service: avahi-publish -a -R dashboard.local 192.168.15.14
```
A small service that keeps announcing 'dashboard.local = 192.168.15.14' on the office network.

```bash
sudo ufw allow from 192.168.15.0/24 to any port 80 proto tcp
sudo ufw allow from 192.168.15.0/24 to any port 5353 proto udp
```
Port 80 and the mDNS announcements, for the office network only. Missing port 80 rule = the 'timed out' error we saw.

**Check:**

- `avahi-resolve -4 -n dashboard.local` → dashboard.local 192.168.15.14
- `curl -s -o /dev/null -w '%{http_code}' -H 'Host: dashboard.local' http://127.0.0.1/` → 200 or 302 (a 502 means Nginx cannot reach Grafana: wrong upstream address, which we fixed)

**In this repository:** `monitoring/nginx/dashboard.local.conf.tmpl`, `monitoring/systemd/avahi-alias-dashboard.service.tmpl`, inventory.env (DASHBOARD_UPSTREAM)

## F. Email alerts

### F1. Mail relay (Postfix) on the VPS

**Where:** application server (VPS ov-ab27bf, user devops)  ·  **Commands:** recorded

**Why:** Send the alert emails directly to the recipients' mail servers, without any external SMTP account.

```bash
timeout 8 bash -c '</dev/tcp/gmail-smtp-in.l.google.com/25' && echo open
```
Checks that the hosting provider does not block outgoing port 25 (needed to deliver mail directly).

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y postfix
```
Installs Postfix without questions ('Internet Site' preset).

```bash
sudo postconf -e 'inet_interfaces = 127.0.0.1, 100.69.47.69' 'mynetworks = 127.0.0.0/8 100.118.61.101/32' ...
```
Listens only on localhost and the Tailscale address; relays only for n8nserver; every alert leaves with one sender address (sender_canonical).

```bash
/etc/systemd/system/postfix@-.service.d/tailscale.conf (After=tailscaled, Restart=on-failure)
```
Postfix waits for the Tailscale address at boot, and retries if it is not ready.

```bash
sudo ufw allow in on tailscale0 from 100.118.61.101 to any port 25 proto tcp
```
Only n8nserver can hand mail to this relay.

**Check:**

- `printf 'Subject: test\n\ntest\n' | sendmail -f alertes@<domain> devops01@brothersbusinessintelligence.com; sudo journalctl -u postfix@- -n 20 | grep status=` → status=sent (250 ...)

**In this repository:** `vps/postfix/main.cf.settings`, `vps/postfix/sender_canonical.tmpl`, `vps/systemd/postfix@-.service.d/tailscale.conf`

### F2. Grafana alert rules and email contact point

**Where:** monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** recorded

**Why:** An email within about a minute when something goes wrong, a reminder every 4 hours, and a 'resolved' email.

```bash
[smtp] enabled = true, host = 100.69.47.69:25, startTLS_policy = NoStartTLS   (in /etc/grafana/grafana.ini)
```
Grafana hands its emails to the Postfix relay through Tailscale (private link, no password).

```bash
/etc/grafana/provisioning/alerting/supervision-odoo.yaml
```
Alerting as code: contact point 'Équipe supervision' (the recipients), the notification policy (group, wait 30 s, repeat 4 h) and 5 rules: application errors, PostgreSQL errors, website 5xx, application silent for 30 min, system service errors.

```bash
sudo systemctl restart grafana-server
```
Grafana reads provisioning files at start.

**Check:**

- `Grafana > Alerting > Contact points > Équipe supervision > Test` → the test email arrives (check spam the first time)

**In this repository:** `monitoring/grafana/settings.ini`, `monitoring/grafana/provisioning/alerting/supervision-odoo.yaml.tmpl`, `docs/04-alerts-runbook.md`

## G. Security review

### G1. Open ports review

**Where:** application server (VPS ov-ab27bf, user devops)  ·  **Commands:** recorded

**Why:** Make sure only the necessary doors are open to the internet.

```bash
sudo ss -tulpn
```
Every listening port and its program. 0.0.0.0 / [::] = every network; 127.0.0.1 = local only; 100.x = Tailscale only.

```bash
sudo ufw status numbered
```
What the firewall lets in.

```bash
nmap -Pn 83.228.207.124   # from another machine
```
The real view from outside.

**Check:**

- `sudo ss -tulpn` → Public: 22 (SSH), 80/443 (website), UDP 41641 (Tailscale). Database, application, Alloy, Postfix: local or Tailscale only.

**In this repository:** `state/vps/ports.txt`, `state/vps/ufw-status.txt`, `docs/06-improvements.md`

> Found: avahi-daemon running on the VPS (not needed there) and an old ufw rule for 5432 (PostgreSQL listens on 127.0.0.1 anyway).

## H. Configuration in Git

### H1. This repository

**Where:** your Mac, application server (VPS ov-ab27bf, user devops), monitoring server (office VM n8nserver, user devops01)  ·  **Commands:** recorded

**Why:** Everything needed to understand, check and rebuild the monitoring stack, in one versioned place.

```bash
scp scripts/collect-vps.sh devops@83.228.207.124:/tmp/ && ssh -t devops@83.228.207.124 sudo bash /tmp/collect-vps.sh
```
Exports the live VPS configuration with secrets removed into /tmp/collect-vps-<date>.tgz (changes nothing).

```bash
scp scripts/collect-monitoring.sh devops01@192.168.15.14:/tmp/ && ssh -t devops01@192.168.15.14 sudo bash /tmp/collect-monitoring.sh
```
Same for n8nserver (Loki, Prometheus container, Grafana data sources and dashboards, dashboard.local).

```bash
scp 'devops@83.228.207.124:/tmp/collect-vps-*.tgz' _import/
scp 'devops01@192.168.15.14:/tmp/collect-monitoring-*.tgz' _import/
```
Brings both archives into the repository's _import/ folder (ignored by git).

```bash
python3 scripts/import.py _import/*.tgz && git diff
```
Puts each live file in its place in the repository and fills the live values (uids, paths) in inventory.env.

```bash
git add -A && git commit -m 'Import live configuration' && git push
```
Records this state in the history and sends it to the private remote repository.

**Check:**

- `git status` → nothing to commit, working tree clean

**In this repository:** `scripts/collect-vps.sh`, `scripts/collect-monitoring.sh`, `scripts/import.py`, `docs/02-rebuild.md`
