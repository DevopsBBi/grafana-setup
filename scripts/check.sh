#!/usr/bin/env bash
# Health check of the monitoring stack. Read-only: changes nothing.
#
#   bash scripts/check.sh vps          # on the application server
#   bash scripts/check.sh monitoring   # on the monitoring server (n8nserver)
#
# Exit code 0 = everything OK, 1 = at least one problem.
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
set +e
load_env
ROLE=${1:-}
if [ -z "$ROLE" ]; then
  case "$(hostname -s)" in
    "$APP_HOST_NAME") ROLE=vps ;;
    "$MON_HOST_NAME") ROLE=monitoring ;;
    *) die "usage: check.sh vps|monitoring" ;;
  esac
fi
FAIL=0
bad() { warn "$*"; FAIL=1; }
svc() { local s; for s in "$@"; do if systemctl is-active -q "$s"; then ok "service $s running"; else bad "service $s is NOT running (journalctl -u $s -n 50)"; fi; done; }
http() { if curl -fsS -m 5 -o /dev/null "$1"; then ok "$2"; else bad "$2: no answer from $1"; fi; }
tcp() { if timeout 5 bash -c "</dev/tcp/$1/$2" 2>/dev/null; then ok "$3 ($1:$2)"; else bad "$3: $1:$2 not reachable"; fi; }
# json_get URL PYTHON_EXPRESSION_ON_d
json_get() { curl -fsS -m 10 "$1" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print($2)" 2>/dev/null; }

check_vps() {
  log "services"
  svc tailscaled alloy postfix
  log "Alloy"
  http "http://127.0.0.1:12345/-/ready" "Alloy ready"
  local unhealthy
  unhealthy="$(json_get http://127.0.0.1:12345/api/v0/web/components "', '.join(c['localID'] for c in d if c.get('health',{}).get('state')!='healthy')")"
  if [ -z "$unhealthy" ]; then ok "all Alloy components healthy"; else bad "unhealthy Alloy components: $unhealthy"; fi
  local m failed dropped
  m="$(curl -fsS -m 5 http://127.0.0.1:12345/metrics 2>/dev/null)"
  failed="$(echo "$m" | awk '/^prometheus_remote_storage_samples_failed_total/ {s+=$2} END {print s+0}')"
  dropped="$(echo "$m" | awk '/^loki_write_dropped_entries_total/ {s+=$2} END {print s+0}')"
  [ "${failed%.*}" = 0 ] && ok "metrics: 0 samples failed since Alloy started" || bad "metrics: $failed samples failed to reach Prometheus"
  [ "${dropped%.*}" = 0 ] && ok "logs: 0 lines dropped since Alloy started" || bad "logs: $dropped lines dropped (Loki rejected or unreachable)"
  log "network"
  tcp "$MON_TS_IP" "$LOKI_PORT" "Loki reachable through Tailscale"
  tcp "$MON_TS_IP" "$PROM_PORT" "Prometheus reachable through Tailscale"
  if ss -ltnH "sport = :25" | grep -q "$APP_TS_IP:25"; then ok "Postfix listens on $APP_TS_IP:25"; else bad "Postfix does not listen on $APP_TS_IP:25"; fi
  log "ports open to every network (0.0.0.0 / [::])"
  ss -tulpnH 2>/dev/null | awk '$5 ~ /^(0\.0\.0\.0|\*|\[::\]):/ {split($5,a,":"); print "    " $1 " " a[length(a)] "  " $7}' | sort -u
}

check_monitoring() {
  log "services"
  svc tailscaled loki grafana-server nginx avahi-daemon avahi-alias-dashboard
  if [ "$(docker inspect -f '{{.State.Running}}' "$PROM_CONTAINER" 2>/dev/null)" = true ]; then ok "container $PROM_CONTAINER running"; else bad "container $PROM_CONTAINER is NOT running (docker logs $PROM_CONTAINER)"; fi
  log "endpoints"
  http "http://127.0.0.1:$LOKI_PORT/ready" "Loki ready"
  http "http://127.0.0.1:$PROM_PORT/-/ready" "Prometheus ready"
  http "http://127.0.0.1:$GRAFANA_PORT/api/health" "Grafana healthy"
  log "data from the application server"
  local n age
  n="$(json_get "http://127.0.0.1:$LOKI_PORT/loki/api/v1/query?query=$(python3 -c "import urllib.parse; print(urllib.parse.quote('sum(count_over_time({host=\"$APP_HOST_LABEL\"}[5m]))'))")" "d['data']['result'][0]['value'][1] if d['data']['result'] else 0")"
  [ "${n:-0}" != 0 ] && ok "Loki: $n log lines received in the last 5 minutes" || bad "Loki: no log line from $APP_HOST_LABEL in the last 5 minutes"
  age="$(json_get "http://127.0.0.1:$PROM_PORT/api/v1/query?query=$(python3 -c "import urllib.parse; print(urllib.parse.quote('time() - max(timestamp(node_time_seconds{host=\"$APP_HOST_LABEL\"}))'))")" "int(float(d['data']['result'][0]['value'][1])) if d['data']['result'] else -1")"
  if [ "${age:--1}" -ge 0 ] && [ "${age:--1}" -le 120 ]; then ok "Prometheus: last measurement ${age}s ago"; else bad "Prometheus: no recent measurement from $APP_HOST_LABEL (age: ${age:-none})"; fi
  log "alerts and access"
  tcp "$APP_TS_IP" 25 "mail relay on the application server"
  if [ -f /etc/grafana/provisioning/alerting/supervision-odoo.yaml ]; then ok "alert rules file present"; else bad "alert rules file missing (monitoring/install.sh alerting)"; fi
  if journalctl -u grafana-server --since "-15min" --no-pager 2>/dev/null | grep -iE 'provision|alerting|smtp' | grep -qiE 'level=(error|crit)'; then bad "Grafana logged provisioning/alerting errors in the last 15 minutes"; else ok "no Grafana provisioning/alerting error in the last 15 minutes"; fi
  if avahi-resolve -4 -n "$DASHBOARD_NAME" >/dev/null 2>&1; then ok "$DASHBOARD_NAME resolves on the office network"; else bad "$DASHBOARD_NAME is not published (systemctl status avahi-alias-dashboard)"; fi
  local code; code="$(curl -s -o /dev/null -m 5 -w '%{http_code}' -H "Host: $DASHBOARD_NAME" http://127.0.0.1/)"
  case "$code" in 200|302) ok "http://$DASHBOARD_NAME answers ($code)";; *) bad "http://$DASHBOARD_NAME answers $code";; esac
}

case "$ROLE" in
  vps) check_vps ;;
  monitoring) check_monitoring ;;
  *) die "usage: check.sh vps|monitoring" ;;
esac
echo
if [ "$FAIL" = 0 ]; then echo "All checks passed."; else echo "Some checks FAILED (see WARN lines above)."; fi
exit "$FAIL"
