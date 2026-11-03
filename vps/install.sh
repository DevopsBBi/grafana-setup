#!/usr/bin/env bash
# Rebuild the monitoring part of the APPLICATION SERVER (VPS) from this repository.
#
#   sudo bash vps/install.sh            # every step, in order
#   sudo bash vps/install.sh postfix    # only some steps
#
# Safe to run again: each step only changes what differs from the repository,
# and every replaced file is kept as <file>.bak-<date>.
# Needs: inventory.env, secrets.env (PG_MONITOR_PASSWORD, optional TS_AUTHKEY).
# shellcheck source=../scripts/lib.sh
. "$(dirname "$0")/../scripts/lib.sh"
need_root
load_env

# shellcheck disable=SC2034  # used by run_steps in scripts/lib.sh
STEPS=(tailscale alloy_package alloy_permissions pg_role alloy_config postfix firewall check)

# 1. Private network: join the tailnet (the monitoring server is reached on its Tailscale address)
step_tailscale() {
  tailscale_join "$APP_TS_NAME" "$APP_TS_IP"
  if timeout 5 bash -c "</dev/tcp/$MON_TS_IP/$LOKI_PORT" 2>/dev/null; then ok "Loki reachable on $MON_TS_IP:$LOKI_PORT"
  else warn "Loki not reachable on $MON_TS_IP:$LOKI_PORT yet (rebuild the monitoring server first, or check its firewall)"; fi
}

# 2. Grafana Alloy from the Grafana apt repository
step_alloy_package() {
  grafana_apt_repo
  if dpkg -s alloy >/dev/null 2>&1; then ok "alloy $(dpkg-query -W -f='${Version}' alloy) installed"
  else apt-get install -y -qq alloy; ok "alloy installed"; fi
}

# 3. Alloy runs as the "alloy" user: it needs to read the logs
#    adm = /var/log/nginx and /var/log/postgresql, systemd-journal = the system journal
step_alloy_permissions() {
  usermod -aG adm,systemd-journal alloy
  ok "alloy is in groups: $(id -nG alloy)"
  local pat f
  # every file Alloy reads (__path__ = "...", wildcards allowed) must be readable by the alloy user
  for pat in $(grep -oE '__path__ *= *"[^"]+"' "$REPO/vps/alloy/config.alloy" | sed -E 's/.*"([^"]+)"/\1/'); do
    for f in $pat; do
      if [ -e "$f" ]; then
        if sudo -u alloy test -r "$f"; then ok "alloy can read $f"; else warn "alloy cannot read $f (fix its group/permissions)"; fi
      else
        warn "$f does not exist (yet)"
      fi
    done
  done
}

# 4. PostgreSQL role with read access to statistics only (pg_monitor)
step_pg_role() {
  if [ -z "${PG_MONITOR_PASSWORD:-}" ]; then
    warn "PG_MONITOR_PASSWORD is empty in secrets.env: role not changed"
    return 0
  fi
  sudo -u postgres psql -q -v ON_ERROR_STOP=1 -v user="$PG_MONITOR_USER" -v pw="$PG_MONITOR_PASSWORD" \
    -f "$REPO/vps/postgres/monitoring-role.sql" >/dev/null
  ok "role $PG_MONITOR_USER ready (member of pg_monitor)"
}

# 5. Alloy configuration (+ the PostgreSQL password, kept outside git in /etc/default/alloy)
step_alloy_config() {
  check_imported vps/alloy/config.alloy
  local tmp restart=0
  tmp="$(mktemp --suffix=.alloy)"
  cp "$REPO/vps/alloy/config.alloy" "$tmp"
  alloy fmt "$tmp" >/dev/null || die "vps/alloy/config.alloy has a syntax error (alloy fmt)"
  install_file "$tmp" /etc/alloy/config.alloy 644 root:root
  restart=$CHANGED; CHANGED=0

  if [ -n "${PG_MONITOR_PASSWORD:-}" ]; then
    local def; def="$(render_tmp "$REPO/vps/alloy/alloy.default.tmpl")"
    install_file "$def" /etc/default/alloy 640 root:alloy; rm -f "$def"
    [ "$CHANGED" = 1 ] && restart=1
  elif grep -q '^ALLOY_PG_DSN=' /etc/default/alloy 2>/dev/null; then
    ok "/etc/default/alloy already has ALLOY_PG_DSN (PG_MONITOR_PASSWORD empty: file kept)"
  elif grep -q 'sys.env("ALLOY_PG_DSN")' "$REPO/vps/alloy/config.alloy"; then
    die "set PG_MONITOR_PASSWORD in secrets.env: config.alloy reads it from ALLOY_PG_DSN"
  fi

  systemctl enable -q alloy
  if [ "$restart" = 1 ] || ! systemctl is-active -q alloy; then systemctl restart alloy; ok "alloy restarted"; fi
  wait_http "http://127.0.0.1:12345/-/ready" 60
}

# 6. Postfix: sends Grafana's alert emails straight to the recipients' mail servers.
#    Listens only on 127.0.0.1 and the Tailscale address, relays only for the monitoring server.
step_postfix() {
  if ! timeout 8 bash -c "</dev/tcp/gmail-smtp-in.l.google.com/25" 2>/dev/null; then
    warn "outgoing port 25 is blocked by the hosting provider: direct sending will not work (see docs/04-alerts-runbook.md)"
  fi
  # sender domain: reverse DNS name of the public IP, else the full host name, else the first Nginx server_name
  local ptr domain
  ptr="$(getent hosts "$APP_PUBLIC_IP" | awk '{print $2}' | head -n1 || true)"
  if echo "$ptr" | grep -q '\.'; then domain=$ptr
  elif hostname -f | grep -q '\.'; then domain=$(hostname -f)
  else
    domain=$(grep -rhoE 'server_name[^;]+' /etc/nginx/sites-enabled/ 2>/dev/null | tr ' ' '\n' | grep '\.' | grep -v '^server_name' | sed 's/^www\.//' | head -n1 || true)
    domain=${domain:-$(hostname)}
  fi
  export MAIL_DOMAIN=$domain MAILNAME=$domain ALERT_FROM="$ALERT_FROM_LOCAL@$domain"
  ok "alert sender: $ALERT_FROM"

  if ! dpkg -s postfix >/dev/null 2>&1; then
    echo "postfix postfix/main_mailer_type select Internet Site" | debconf-set-selections
    echo "postfix postfix/mailname string $MAILNAME" | debconf-set-selections
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postfix >/dev/null
    ok "postfix installed"
  fi
  local settings line
  settings="$(render_tmp "$REPO/vps/postfix/main.cf.settings")"
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    postconf -e "$line"
  done < "$settings"
  ok "main.cf settings applied"
  local canon; canon="$(render_tmp "$REPO/vps/postfix/sender_canonical.tmpl")"
  install_file "$canon" /etc/postfix/sender_canonical 644 root:root
  install_file "$REPO/vps/systemd/postfix@-.service.d/tailscale.conf" "/etc/systemd/system/postfix@-.service.d/tailscale.conf" 644 root:root
  systemctl daemon-reload
  systemctl enable -q postfix
  systemctl restart postfix
  sleep 2
  systemctl is-active -q postfix@- && ok "postfix running" || die "postfix does not start: journalctl -u postfix@- -n 30"
}

# 7. Firewall: port 25 open only for the monitoring server, only through Tailscale
step_firewall() {
  ufw_allow in on tailscale0 from "$MON_TS_IP" to any port 25 proto tcp
}

# 8. Checks
step_check() {
  bash "$REPO/scripts/check.sh" vps
}

run_steps "$@"
