#!/usr/bin/env bash
# Export the LIVE monitoring configuration of the APPLICATION SERVER, with secrets removed.
# Read-only: it copies files and command outputs, it changes nothing on the server.
#
#   sudo bash collect-vps.sh        ->  /tmp/collect-vps-<date>.tgz
#
# Then copy the archive into the repository (folder _import/) and run: python3 scripts/import.py _import/collect-vps-*.tgz
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo: sudo bash $0"; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
OUT="$WORK/vps"
mkdir -p "$OUT"
ARCHIVE="/tmp/collect-vps-$STAMP.tgz"

# Secrets are replaced by REDACTED: passwords inside connection URLs, and any "password/secret/token/key = ..." value
redact() {
  sed -E \
    -e 's#(postgres(ql)?://[^:/@" ]+:).*@([A-Za-z0-9._-]+(:[0-9]+)?/)#\1REDACTED@\3#g' \
    -e 's#^([[:space:]]*[A-Za-z0-9_.-]*(password|passwd|secret|token|api_key|apikey|authkey)[A-Za-z0-9_.-]*[[:space:]]*[=:][[:space:]]*).+$#\1"REDACTED"#I'
}
copy() {   # copy SRC NAME
  if [ -f "$1" ]; then redact < "$1" > "$OUT/$2"; echo "  + $2"; else echo "  - $1 (not found)"; fi
}
run() {    # run NAME COMMAND...
  local name=$1; shift
  { "$@" 2>&1 || true; } | redact > "$OUT/$name"; echo "  + $name"
}

echo "== Grafana Alloy"
copy /etc/alloy/config.alloy config.alloy
copy /etc/default/alloy alloy.default
run alloy-unit.txt systemctl cat alloy
run alloy-groups.txt id alloy
run alloy-components.txt bash -c "curl -fsS -m 5 http://127.0.0.1:12345/api/v0/web/components | python3 -c 'import json,sys; [print(c[\"localID\"], c.get(\"health\",{}).get(\"state\")) for c in json.load(sys.stdin)]'"
# files read by Alloy and their permissions
grep -oE '__path__ *= *"[^"]+"' /etc/alloy/config.alloy 2>/dev/null | sed -E 's/.*"([^"]+)"/\1/' | while read -r pat; do
  # shellcheck disable=SC2086
  ls -l $pat 2>&1
done > "$OUT/alloy-log-files.txt" || true
echo "  + alloy-log-files.txt"

echo "== Postfix (alert relay)"
run postfix-postconf-n.txt postconf -n
copy /etc/postfix/sender_canonical sender_canonical
copy "/etc/systemd/system/postfix@-.service.d/tailscale.conf" postfix-dropin-tailscale.conf

echo "== PostgreSQL roles (names only) and log settings"
run pg-roles.txt sudo -u postgres psql -XAtc "select rolname, pg_has_role(rolname,'pg_monitor','member') as pg_monitor from pg_roles where rolname !~ '^pg_' order by 1"
run pg-log-settings.txt sudo -u postgres psql -XAtc "select name, setting from pg_settings where name in ('logging_collector','log_directory','log_filename','log_line_prefix','log_min_duration_statement','log_destination') order by 1"

echo "== Nginx log format (used by the Alloy regex)"
run nginx-log-format.txt bash -c "grep -rhE 'log_format|access_log' /etc/nginx/ | sed 's/^[[:space:]]*//' | sort -u"

echo "== Network, firewall, versions"
run tailscale.txt bash -c "tailscale ip -4; tailscale status"
run ufw-status.txt ufw status verbose
run ports.txt ss -tulpn
run versions.txt bash -c "lsb_release -ds; uname -r; alloy --version | head -n1; dpkg-query -W -f='\${Package} \${Version}\n' alloy postfix tailscale nginx 'postgresql-1*' 2>/dev/null"

# last safety net: list the lines that mention a secret and were not redacted
LEFT="$(grep -rniE '(password|passwd|secret|token)[[:alnum:]_.-]*[[:space:]]*[=:]' "$OUT" | grep -v REDACTED || true)"
if [ -n "$LEFT" ]; then echo "!! Check these lines before sharing the archive:"; echo "$LEFT"; fi

tar czf "$ARCHIVE" -C "$WORK" vps
rm -rf "$WORK"
[ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER" "$ARCHIVE"
echo
echo "Archive: $ARCHIVE"
echo "From your Mac:  scp ${SUDO_USER:-devops}@<server>:$ARCHIVE ~/Desktop/Grafana/_import/"
