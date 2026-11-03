#!/usr/bin/env bash
# Export the LIVE configuration of the MONITORING SERVER (n8nserver), with secrets removed:
# Loki, the Prometheus container, Grafana (settings, data sources, dashboards, alerting), dashboard.local.
# Read-only: it copies files and command outputs, it changes nothing on the server.
#
#   sudo bash collect-monitoring.sh        ->  /tmp/collect-monitoring-<date>.tgz
#
# Then copy the archive into the repository (folder _import/) and run: python3 scripts/import.py _import/collect-monitoring-*.tgz
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo: sudo bash $0"; exit 1; }

PROM_CONTAINER="${PROM_CONTAINER:-vps_prometheus}"
DASHBOARD_NAME="${DASHBOARD_NAME:-dashboard.local}"
GRAFANA_DB="${GRAFANA_DB:-/var/lib/grafana/grafana.db}"

STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
OUT="$WORK/monitoring"
mkdir -p "$OUT/grafana-provisioning" "$OUT/dashboards"
ARCHIVE="/tmp/collect-monitoring-$STAMP.tgz"

redact() {
  sed -E \
    -e 's#(postgres(ql)?://[^:/@" ]+:).*@([A-Za-z0-9._-]+(:[0-9]+)?/)#\1REDACTED@\3#g' \
    -e 's#^([[:space:]]*[A-Za-z0-9_.-]*(password|passwd|secret|token|api_key|apikey|authkey|secret_key)[A-Za-z0-9_.-]*[[:space:]]*[=:][[:space:]]*).+$#\1"REDACTED"#I'
}
copy() { if [ -f "$1" ]; then redact < "$1" > "$OUT/$2"; echo "  + $2"; else echo "  - $1 (not found)"; fi; }
run()  { local name=$1; shift; { "$@" 2>&1 || true; } | redact > "$OUT/$name"; echo "  + $name"; }

echo "== Loki"
run loki-unit.txt systemctl cat loki
LOKI_CFG="$(systemctl cat loki 2>/dev/null | grep -oE -- '-config\.file[= ][^ ]+' | head -n1 | sed -E 's/-config\.file[= ]//' || true)"
[ -z "$LOKI_CFG" ] && for f in /etc/loki/config.yml /etc/loki/config.yaml /etc/loki/loki.yaml /etc/loki/local-config.yaml; do [ -f "$f" ] && LOKI_CFG=$f && break; done
echo "${LOKI_CFG:-not found}" > "$OUT/loki-config-path.txt"
[ -n "$LOKI_CFG" ] && copy "$LOKI_CFG" loki-config.yaml
run loki-version.txt bash -c "loki --version 2>/dev/null | head -n1; dpkg-query -W -f='\${Package} \${Version}\n' loki 2>/dev/null"

echo "== Prometheus container"
if docker inspect "$PROM_CONTAINER" >/dev/null 2>&1; then
  # environment variables of the container can hold secrets: values are removed
  docker inspect "$PROM_CONTAINER" | python3 -c '
import json, re, sys
d = json.load(sys.stdin)
for c in d:
    env = c.get("Config", {}).get("Env") or []
    c["Config"]["Env"] = [e.split("=", 1)[0] + "=REDACTED" if re.search("(?i)pass|secret|token|key", e.split("=", 1)[0]) else e for e in env]
print(json.dumps(d, indent=2))' > "$OUT/prometheus-inspect.json"
  echo "  + prometheus-inspect.json"
  CFG_SRC="$(docker inspect "$PROM_CONTAINER" | python3 -c '
import json, sys, os
m = json.load(sys.stdin)[0].get("Mounts", [])
for x in m:
    if x.get("Destination") == "/etc/prometheus/prometheus.yml":
        print(x["Source"]); break
else:
    for x in m:
        if x.get("Destination") == "/etc/prometheus" and x.get("Type") == "bind":
            print(os.path.join(x["Source"], "prometheus.yml")); break')"
  if [ -n "$CFG_SRC" ] && [ -f "$CFG_SRC" ]; then copy "$CFG_SRC" prometheus.yml
  else docker exec "$PROM_CONTAINER" cat /etc/prometheus/prometheus.yml 2>/dev/null | redact > "$OUT/prometheus.yml" && echo "  + prometheus.yml (from inside the container)"; fi
  echo "${CFG_SRC:-}" > "$OUT/prometheus-config-host-path.txt"
else
  echo "  - container $PROM_CONTAINER not found"
fi
run docker-ps.txt docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

echo "== Grafana"
copy /etc/grafana/grafana.ini grafana.ini
if [ -d /etc/grafana/provisioning ]; then
  (cd /etc/grafana/provisioning && find . -type f \( -name '*.yaml' -o -name '*.yml' -o -name '*.json' \)) | while read -r f; do
    mkdir -p "$OUT/grafana-provisioning/$(dirname "$f")"
    redact < "/etc/grafana/provisioning/$f" > "$OUT/grafana-provisioning/$f"
  done
  echo "  + grafana-provisioning/"
fi
run grafana-version.txt bash -c "grafana-server -v 2>/dev/null || grafana server -v 2>/dev/null; dpkg-query -W -f='\${Package} \${Version}\n' grafana 2>/dev/null"
# data sources and dashboards, read from Grafana's database in read-only mode (no password needed, secrets not exported)
python3 - "$GRAFANA_DB" "$OUT" << 'PY'
import json, os, re, sqlite3, sys
db, out = sys.argv[1], sys.argv[2]
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
cols = {r[1] for r in c.execute("pragma table_info(data_source)")}
want = [k for k in ("name", "type", "uid", "access", "url", "user", "database", "is_default",
                    "basic_auth", "basic_auth_user", "with_credentials", "json_data", "org_id") if k in cols]
ds = []
for r in c.execute(f"select {', '.join(want)} from data_source order by name"):
    d = dict(r)
    try:
        d["json_data"] = json.loads(d.get("json_data") or "{}")
    except Exception:
        pass
    ds.append(d)
json.dump(ds, open(os.path.join(out, "datasources.json"), "w"), indent=2, ensure_ascii=False)
print(f"  + datasources.json ({len(ds)} data sources, passwords not exported)")

dcols = {r[1] for r in c.execute("pragma table_info(dashboard)")}
join = "f.uid = d.folder_uid" if "folder_uid" in dcols else "f.id = d.folder_id"
rows = c.execute(f"""select d.uid, d.title, d.data, coalesce(f.title, 'General') as folder
                     from dashboard d left join dashboard f on {join} and f.is_folder = 1
                     where d.is_folder = 0 order by folder, d.title""").fetchall()
idx = []
for r in rows:
    data = json.loads(r["data"])
    data.pop("id", None)
    fn = re.sub(r"[^A-Za-z0-9_.-]+", "_", r["uid"]) + ".json"
    json.dump(data, open(os.path.join(out, "dashboards", fn), "w"), indent=2, ensure_ascii=False)
    idx.append(f"{r['uid']}\t{r['folder']}\t{r['title']}\t{fn}")
open(os.path.join(out, "dashboards-index.tsv"), "w").write("uid\tfolder\ttitle\tfile\n" + "\n".join(idx) + "\n")
print(f"  + dashboards/ ({len(rows)} dashboards)")
PY

echo "== dashboard.local (Nginx + Avahi)"
for f in "/etc/nginx/sites-available/$DASHBOARD_NAME" "/etc/nginx/conf.d/$DASHBOARD_NAME.conf"; do
  [ -f "$f" ] && copy "$f" nginx-dashboard.local.conf && break
done
copy /etc/systemd/system/avahi-alias-dashboard.service avahi-alias-dashboard.service

echo "== Network, firewall, versions"
run tailscale.txt bash -c "tailscale ip -4; tailscale status"
run ufw-status.txt ufw status verbose
run ports.txt ss -tulpn
run versions.txt bash -c "lsb_release -ds; uname -r; docker --version"

LEFT="$(grep -rniE '(password|passwd|secret|token)[[:alnum:]_.-]*"?[[:space:]]*[=:]' "$OUT" --include='*.txt' --include='*.ini' --include='*.yaml' --include='*.yml' | grep -v REDACTED || true)"
if [ -n "$LEFT" ]; then echo "!! Check these lines before sharing the archive:"; echo "$LEFT"; fi

tar czf "$ARCHIVE" -C "$WORK" monitoring
rm -rf "$WORK"
[ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER" "$ARCHIVE"
echo
echo "Archive: $ARCHIVE"
echo "From your Mac:  scp ${SUDO_USER:-devops01}@<server>:$ARCHIVE ~/Desktop/Grafana/_import/"
