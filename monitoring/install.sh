#!/usr/bin/env bash
# Rebuild the MONITORING SERVER (office VM n8nserver) from this repository:
# Loki (logs), Prometheus in Docker (metrics), Grafana (dashboards + email alerts), dashboard.local.
#
#   sudo bash monitoring/install.sh             # every step, in order
#   sudo bash monitoring/install.sh dashboards  # only some steps
#   sudo RECREATE_PROMETHEUS=1 bash monitoring/install.sh prometheus   # recreate the container (data volume kept)
#
# Safe to run again: each step only changes what differs from the repository,
# and every replaced file is kept as <file>.bak-<date>.
# Needs: inventory.env, secrets.env (GRAFANA_PG_PASSWORD, optional GRAFANA_ADMIN_PASSWORD, TS_AUTHKEY).
# shellcheck source=../scripts/lib.sh
. "$(dirname "$0")/../scripts/lib.sh"
need_root
load_env

# shellcheck disable=SC2034  # used by run_steps in scripts/lib.sh
STEPS=(tailscale packages loki prometheus grafana dashboards alerting dashboard_local firewall check)

restart_grafana() {
  systemctl restart grafana-server
  wait_http "http://127.0.0.1:$GRAFANA_PORT/api/health" 90
}

# 1. Private network
step_tailscale() {
  tailscale_join "$MON_TS_NAME" "$MON_TS_IP"
}

# 2. Packages: Grafana (apt), Loki (apt, unless a loki service already exists), Docker, Nginx, Avahi
step_packages() {
  grafana_apt_repo
  local p
  for p in grafana nginx avahi-daemon avahi-utils; do
    if dpkg -s "$p" >/dev/null 2>&1; then ok "$p installed"; else apt-get install -y -qq "$p" >/dev/null; ok "$p installed now"; fi
  done
  if systemctl list-unit-files loki.service >/dev/null 2>&1 && systemctl cat loki >/dev/null 2>&1; then
    ok "loki service present"
  else
    apt-get install -y -qq loki >/dev/null; ok "loki installed now"
  fi
  if command -v docker >/dev/null; then ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"
  else apt-get install -y -qq docker.io >/dev/null; systemctl enable -q --now docker; ok "docker installed now"; fi
}

# 3. Loki: stores the log lines sent by Alloy (port 3100)
step_loki() {
  check_imported monitoring/loki/config.yaml
  local bin
  bin="$(command -v loki || true)"
  if [ -n "$bin" ]; then
    "$bin" -config.file="$REPO/monitoring/loki/config.yaml" -verify-config >/dev/null 2>&1 \
      && ok "Loki configuration is valid" || warn "Loki -verify-config did not accept monitoring/loki/config.yaml (check: $bin -config.file=... -verify-config)"
  fi
  install_file "$REPO/monitoring/loki/config.yaml" "$LOKI_CONFIG_PATH" 644 root:root
  systemctl enable -q loki
  if [ "$CHANGED" = 1 ] || ! systemctl is-active -q loki; then systemctl restart loki; ok "loki restarted"; fi
  wait_http "http://127.0.0.1:$LOKI_PORT/ready" 120
}

# 4. Prometheus (Docker container): receives the metrics pushed by Alloy (remote write, port 9091)
step_prometheus() {
  check_imported monitoring/prometheus/prometheus.yml monitoring/prometheus/container.env
  # shellcheck disable=SC1091
  . "$REPO/monitoring/prometheus/container.env"   # PROM_IMAGE PROM_RESTART PROM_CONFIG_HOST_PATH PROM_DOCKER_ARGS PROM_CMD
  if [ -n "${PROM_CONFIG_HOST_PATH:-}" ]; then
    install_file "$REPO/monitoring/prometheus/prometheus.yml" "$PROM_CONFIG_HOST_PATH" 644 root:root
  else
    warn "prometheus.yml is not mounted from the host: configuration not deployed"
  fi
  local changed=$CHANGED
  if docker inspect "$PROM_CONTAINER" >/dev/null 2>&1; then
    if [ "${RECREATE_PROMETHEUS:-0}" = 1 ]; then
      docker rm -f "$PROM_CONTAINER" >/dev/null; ok "old container removed (its data volume is kept)"
    else
      if [ "$(docker inspect -f '{{.State.Running}}' "$PROM_CONTAINER")" != true ]; then docker start "$PROM_CONTAINER" >/dev/null; ok "container started"; fi
      if [ "$changed" = 1 ]; then docker kill -s HUP "$PROM_CONTAINER" >/dev/null; ok "configuration reloaded (SIGHUP)"; fi
    fi
  fi
  if ! docker inspect "$PROM_CONTAINER" >/dev/null 2>&1; then
    docker run -d --name "$PROM_CONTAINER" --restart "$PROM_RESTART" "${PROM_DOCKER_ARGS[@]}" "$PROM_IMAGE" "${PROM_CMD[@]}" >/dev/null
    ok "container $PROM_CONTAINER created ($PROM_IMAGE)"
  fi
  wait_http "http://127.0.0.1:$PROM_PORT/-/ready" 90
}

# 5. Grafana: settings (port, dashboard.local address, SMTP through the VPS), data sources, admin password
step_grafana() {
  check_imported monitoring/grafana/provisioning/datasources/datasources.yaml.tmpl
  local settings before restart=0 ds pg
  settings="$(render_tmp "$REPO/monitoring/grafana/settings.ini")"
  before="$(mktemp)"; cp /etc/grafana/grafana.ini "$before"
  python3 "$REPO/scripts/ini_set.py" /etc/grafana/grafana.ini "$settings"
  if cmp -s "$before" /etc/grafana/grafana.ini; then ok "grafana.ini unchanged"
  else cp -a "$before" "/etc/grafana/grafana.ini.bak-$(date +%Y%m%d-%H%M%S)"; ok "grafana.ini updated"; restart=1; fi
  rm -f "$before" "$settings"

  ds="$(render_tmp "$REPO/monitoring/grafana/provisioning/datasources/datasources.yaml.tmpl")"
  install_file "$ds" /etc/grafana/provisioning/datasources/supervision.yaml 640 root:grafana; rm -f "$ds"
  [ "$CHANGED" = 1 ] && restart=1; CHANGED=0
  if [ -f "$REPO/monitoring/grafana/provisioning/datasources/postgres.yaml.tmpl" ]; then
    if [ -n "${GRAFANA_PG_PASSWORD:-}" ]; then
      pg="$(render_tmp "$REPO/monitoring/grafana/provisioning/datasources/postgres.yaml.tmpl")"
      install_file "$pg" /etc/grafana/provisioning/datasources/supervision-postgres.yaml 640 root:grafana; rm -f "$pg"
      [ "$CHANGED" = 1 ] && restart=1
    else
      warn "GRAFANA_PG_PASSWORD is empty: the $DS_PG_NAME data source is left as it is in Grafana"
    fi
  fi

  systemctl enable -q grafana-server
  if [ "$restart" = 1 ] || ! systemctl is-active -q grafana-server; then restart_grafana; else wait_http "http://127.0.0.1:$GRAFANA_PORT/api/health" 30; fi

  if [ -n "${GRAFANA_ADMIN_PASSWORD:-}" ]; then
    local cli=(grafana cli); command -v grafana >/dev/null || cli=(grafana-cli)
    printf '%s' "$GRAFANA_ADMIN_PASSWORD" | sudo -u grafana "${cli[@]}" --homepath /usr/share/grafana --config /etc/grafana/grafana.ini \
      admin reset-admin-password --password-from-stdin >/dev/null
    ok "admin password set from secrets.env"
  fi
}

# 6. Dashboards: JSON files from git, loaded by Grafana's file provider into the "Supervision Odoo" folder
step_dashboards() {
  local dir=/var/lib/grafana/dashboards/supervision f prov restart=0
  install -d -m 755 -o grafana -g grafana "$dir"
  for f in "$REPO"/monitoring/grafana/dashboards/*.json; do
    python3 -m json.tool "$f" >/dev/null || die "$f is not valid JSON"
    install_file "$f" "$dir/$(basename "$f")" 644 grafana:grafana
  done
  CHANGED=0
  prov="$(render_tmp "$REPO/monitoring/grafana/provisioning/dashboards/supervision.yaml.tmpl")"
  install_file "$prov" /etc/grafana/provisioning/dashboards/supervision.yaml 640 root:grafana; rm -f "$prov"
  [ "$CHANGED" = 1 ] && restart=1
  if [ "$restart" = 1 ]; then restart_grafana; else ok "Grafana re-reads the dashboard files within 60 s"; fi
}

# 7. Email alerts: contact point, notification policy and the 5 rules (Loki queries)
step_alerting() {
  [ -n "$DS_LOKI_UID" ] || die "DS_LOKI_UID is empty in inventory.env (run scripts/import.py with the monitoring export)"
  local f
  f="$(render_tmp "$REPO/monitoring/grafana/provisioning/alerting/supervision-odoo.yaml.tmpl")"
  python3 -m json.tool "$f" >/dev/null || die "rendered alert file is not valid JSON"
  install_file "$f" /etc/grafana/provisioning/alerting/supervision-odoo.yaml 640 root:grafana; rm -f "$f"
  if [ "$CHANGED" = 1 ]; then restart_grafana; fi
  if timeout 5 bash -c "</dev/tcp/$APP_TS_IP/25" 2>/dev/null; then ok "mail relay reachable on $APP_TS_IP:25"
  else warn "mail relay $APP_TS_IP:25 not reachable: run vps/install.sh postfix firewall on the application server"; fi
}

# 8. http://dashboard.local on the office network: Nginx in front of Grafana + mDNS name published by Avahi
step_dashboard_local() {
  local site=/etc/nginx/sites-available/$DASHBOARD_NAME f
  f="$(render_tmp "$REPO/monitoring/nginx/dashboard.local.conf.tmpl")"
  install_file "$f" "$site" 644 root:root; rm -f "$f"
  ln -sfn "$site" "/etc/nginx/sites-enabled/$DASHBOARD_NAME"
  nginx -t >/dev/null 2>&1 || { nginx -t; die "nginx rejects the configuration"; }
  systemctl enable -q nginx; systemctl reload nginx || systemctl restart nginx
  ok "nginx serves http://$DASHBOARD_NAME -> $DASHBOARD_UPSTREAM"
  CHANGED=0
  f="$(render_tmp "$REPO/monitoring/systemd/avahi-alias-dashboard.service.tmpl")"
  install_file "$f" /etc/systemd/system/avahi-alias-dashboard.service 644 root:root; rm -f "$f"
  systemctl daemon-reload
  systemctl enable -q --now avahi-daemon avahi-alias-dashboard
  [ "$CHANGED" = 1 ] && systemctl restart avahi-alias-dashboard
  ufw_allow from "$MON_LAN_CIDR" to any port 80 proto tcp
  ufw_allow from "$MON_LAN_CIDR" to any port 5353 proto udp
}

# 9. Firewall: Loki and Prometheus only for the application server, only through Tailscale
step_firewall() {
  ufw_allow in on tailscale0 from "$APP_TS_IP" to any port "$LOKI_PORT" proto tcp
  ufw_allow in on tailscale0 from "$APP_TS_IP" to any port "$PROM_PORT" proto tcp
  warn "Docker-published ports bypass ufw: see docs/06-improvements.md (bind $PROM_PORT to 127.0.0.1 and $MON_TS_IP)"
}

# 10. Checks
step_check() {
  bash "$REPO/scripts/check.sh" monitoring
}

run_steps "$@"
