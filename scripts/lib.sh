#!/usr/bin/env bash
# Shared helpers for vps/install.sh, monitoring/install.sh and scripts/check.sh.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC2034  # read by the install scripts
CHANGED=0

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mOK\033[0m   %s\n' "$*"; }
warn() { printf '    \033[33mWARN\033[0m %s\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

need_root() { [ "$(id -u)" -eq 0 ] || die "run this script with sudo"; }

# inventory.env (committed) + secrets.env (never committed), exported for render.py
load_env() {
  set -a
  # shellcheck disable=SC1091
  . "$REPO/inventory.env"
  if [ -f "$REPO/secrets.env" ]; then
    # shellcheck disable=SC1091
    . "$REPO/secrets.env"
  fi
  set +a
}

# Refuse to deploy a file that still waits for scripts/import.py
check_imported() {
  local f
  for f in "$@"; do
    if grep -q '@@NOT-IMPORTED@@' "$REPO/$f"; then
      die "$f has not been imported from the live server yet (see docs/02-rebuild.md, step 'Import')"
    fi
  done
}

# render TEMPLATE -> temporary file (path printed)
render_tmp() {
  local out
  out="$(mktemp)"
  python3 "$REPO/scripts/render.py" "$1" "$out"
  echo "$out"
}

# install_file SRC DEST [MODE] [OWNER:GROUP]: copies only when the content changed,
# keeps a dated backup of the previous version and sets CHANGED=1.
install_file() {
  local src=$1 dst=$2 mode=${3:-644} own=${4:-root:root}
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    chmod "$mode" "$dst"; chown "$own" "$dst"
    ok "$dst unchanged"
    return 0
  fi
  if [ -f "$dst" ]; then cp -a "$dst" "$dst.bak-$(date +%Y%m%d-%H%M%S)"; fi
  install -D -m "$mode" -o "${own%%:*}" -g "${own##*:}" "$src" "$dst"
  ok "$dst installed"
  CHANGED=1
}

# Grafana's apt repository (alloy, grafana, loki packages)
grafana_apt_repo() {
  if grep -rqs "apt.grafana.com" /etc/apt/sources.list /etc/apt/sources.list.d/; then
    ok "Grafana apt repository already configured"
    return 0
  fi
  apt-get install -y -qq gpg wget >/dev/null
  mkdir -p /etc/apt/keyrings
  wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/grafana.gpg
  echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list
  apt-get update -qq
  ok "Grafana apt repository added"
}

# tailscale_join HOSTNAME EXPECTED_IP
tailscale_join() {
  local name=$1 expected=$2 ip
  if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
  if ! tailscale ip -4 >/dev/null 2>&1; then
    if [ -n "${TS_AUTHKEY:-}" ]; then
      tailscale up --authkey="$TS_AUTHKEY" --hostname="$name"
    else
      tailscale up --hostname="$name"     # prints a login link to open in a browser
    fi
  fi
  ip="$(tailscale ip -4 | head -n1)"
  if [ "$ip" = "$expected" ]; then
    ok "Tailscale address $ip"
  else
    warn "Tailscale address is $ip but inventory.env says $expected: update inventory.env and run the install again"
  fi
}

# ufw_allow RULE...: adds a rule only when ufw is active
ufw_allow() {
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "$@" >/dev/null
    ok "ufw allow $*"
  else
    warn "ufw is not active: rule not added ($*)"
  fi
}

# wait_http URL [SECONDS]
wait_http() {
  local url=$1 n=${2:-60} i
  for ((i = 0; i < n; i++)); do
    if curl -fsS -m 3 -o /dev/null "$url"; then ok "$url answers"; return 0; fi
    sleep 1
  done
  die "$url does not answer after ${n}s"
}

# run_steps [STEP...]: runs every step of $STEPS (or only the ones given) in order
run_steps() {
  local list=("$@") s
  if [ ${#list[@]} -eq 0 ]; then list=("${STEPS[@]}"); fi
  for s in "${list[@]}"; do
    declare -F "step_$s" >/dev/null || die "unknown step '$s' (steps: ${STEPS[*]})"
    log "$s"
    # shellcheck disable=SC2034  # read by the install scripts
    CHANGED=0
    "step_$s"
  done
  log "done"
}
