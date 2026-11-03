# The Alloy configuration, block by block

File: `vps/alloy/config.alloy` (deployed to `/etc/alloy/config.alloy` on the VPS). If this page and the file ever disagree, the file is right: update this page.
Alloy works like a pipeline: **sources** read data, **processors** transform it, **writers** send it.
Each block is `<component> "<name>" { ... }`, and blocks are wired together with `forward_to` / `targets`.

```text
LOGS     loki.source.file / loki.source.journal  ->  loki.process  ->  loki.write "central"  ->  Loki on n8nserver :3100
METRICS  prometheus.exporter.*  ->  prometheus.scrape  ->  prometheus.remote_write "central"  ->  Prometheus on n8nserver :9091
```

Every log line and every metric gets the label `host = "vps-web"`, so the dashboards can filter on this server.

## Logs

### `loki.source.file "odoo"` + `loki.process "odoo"` — the application log
- **source.file** follows the application log file (like `tail -F`) and remembers its position, so nothing is read twice after a restart.
- **stage.multiline**: a Python traceback spans many lines. A new entry starts only on a line beginning with a date
  (`2026-11-03 09:00:00,123 ...`), so the whole traceback stays in **one** log entry.
- **stage.regex**: extracts from each line the process id, the **level** (INFO, WARNING, ERROR, CRITICAL), the database and the logger.
- **stage.timestamp**: uses the time written in the line, not the time Alloy read it.
- **stage.labels**: turns `level` into a label, which makes "only the errors" queries fast: `{job="odoo", level=~"ERROR|CRITICAL"}`.

### PostgreSQL log (`job = "postgresql"`)
- Follows the PostgreSQL log file. Errors are found by text (`|~ " (ERROR|FATAL|PANIC):"`) because these lines have no level label.

### `loki.source.file "nginx"` + `loki.process "nginx"` — website access and errors
- Reads `/var/log/nginx/access.log` (`stream = "access"`) and `/var/log/nginx/error.log` (`stream = "error"`).
- **stage.regex** + **stage.labels**: extracts the HTTP **status** (200, 404, 502...) as a label: `{job="nginx", status=~"5.."}` = server errors.
  The regex must match the Nginx `log_format` (saved in `state/vps/nginx-log-format.txt`).

### `discovery.relabel "journal"` + `loki.source.journal "system"` — systemd journal
- Reads the journal of every service (up to 12 h back at first start).
- **relabel** copies the service name into the label `unit` and the priority (`err`, `warning`, `info`...) into `level`.
  The alert "Erreurs des services système" counts `level=~"err|crit|alert|emerg"` per `unit`.

### `loki.write "central"`
- Sends all log entries to `http://100.118.61.101:3100/loki/api/v1/push` (Loki on n8nserver, through Tailscale).
  If Loki is unreachable, Alloy keeps retrying (short outages lose nothing).

## Metrics

### `prometheus.exporter.unix "host"` + `prometheus.scrape "host"` — the server
- The built-in node exporter: CPU, memory, swap, disks (filesystems filtered to real disks), disk I/O, network, load.
- Extra collectors: `systemd` (state of every `.service`, so failed services are visible), `processes`, `tcpstat`.
- **scrape** reads it every 15 s and forwards to `prometheus.remote_write.central`.

### `prometheus.exporter.process "services"` + scrape — consumption per program
- Groups processes by name: **postgresql** (`postgres`), **nginx**, **odoo** (command line contains "odoo"), then every other program by its name.
- Gives CPU, memory, number of processes, open files and age per group: this is how the dashboard shows the **31 application workers**
  (busy, memory per worker, restarts).

### `prometheus.exporter.postgres "postgresql"` + scrape — the database
- Connects as `alloy_monitor` (role `pg_monitor`: statistics only). Connections, transactions, cache hit ratio, locks, database size.
- The connection string is **not in git**: `data_source_names = [sys.env("ALLOY_PG_DSN")]` reads it from `/etc/default/alloy`
  (root:alloy, mode 640), written by `vps/install.sh` from `secrets.env`.

### `prometheus.exporter.blackbox` + scrape — availability probes
- Tests the website from the server itself (HTTP answer code and response time).

### `prometheus.exporter.self "alloy"` + scrape — Alloy itself
- Alloy's own health: how many samples and log lines it sent, retries, failures. Used by `scripts/check.sh vps`.

### `prometheus.remote_write "central"`
- Pushes every metric to `http://100.118.61.101:9091/api/v1/write` (Prometheus on n8nserver, through Tailscale),
  with `external_labels = { host = "vps-web" }`. Prometheus must run with `--web.enable-remote-write-receiver`.

## Useful commands on the VPS

```bash
sudo alloy fmt /etc/alloy/config.alloy >/dev/null && echo syntax-ok      # check before restarting
sudo systemctl restart alloy && journalctl -u alloy -f                   # restart and follow its log
curl -s http://127.0.0.1:12345/-/ready                                    # ready?
curl -s http://127.0.0.1:12345/api/v0/web/components | python3 -m json.tool | grep -E '"localID"|"state"'   # each block healthy?
curl -s http://127.0.0.1:12345/metrics | grep -E 'remote_storage_samples_(total|failed_total)|loki_write_(sent|dropped)_entries_total'
```

The web UI (graph of all blocks) is on `127.0.0.1:12345` of the VPS only. To open it from your Mac:
`ssh -L 12345:127.0.0.1:12345 devops@83.228.207.124` then http://localhost:12345.
