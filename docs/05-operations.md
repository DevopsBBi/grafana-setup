# Day-to-day operations

## Check that everything works

```bash
bash scripts/check.sh vps          # on the VPS
bash scripts/check.sh monitoring   # on n8nserver
```
Both end with "All checks passed." Each WARN line says what is wrong and which command shows more.

## Change something, the right way

| You want to... | Do it in | Then |
|---|---|---|
| change a dashboard | Grafana (or `tools/dashboards/*.py`) | collect + import + commit (below) |
| add or remove an alert recipient | `ALERT_EMAILS` in `inventory.env` | commit, then on n8nserver: `sudo bash monitoring/install.sh alerting` |
| change an alert rule | `monitoring/grafana/provisioning/alerting/supervision-odoo.yaml.tmpl` | commit, then `sudo bash monitoring/install.sh alerting` |
| collect a new log file or metric | `vps/alloy/config.alloy` | commit, then on the VPS: `sudo bash vps/install.sh alloy_permissions alloy_config` |
| change Loki / Prometheus settings | `monitoring/loki/config.yaml`, `monitoring/prometheus/prometheus.yml` | commit, then `sudo bash monitoring/install.sh loki` / `prometheus` |

On the servers, update the repository first: `cd ~/grafana-setup && git pull`.

### Save changes made directly on a server or in Grafana

```bash
# on your Mac, in the repository
scp scripts/collect-monitoring.sh devops01@192.168.15.14:/tmp/ && ssh -t devops01@192.168.15.14 'sudo bash /tmp/collect-monitoring.sh'
scp 'devops01@192.168.15.14:/tmp/collect-monitoring-*.tgz' _import/
python3 scripts/import.py _import/collect-monitoring-*.tgz
git diff                      # read what changed
git add -A && git commit -m "Grafana: <what you changed>" && git push
rm _import/*.tgz              # the archives are not needed any more
```
Same with `collect-vps.sh` for the VPS.

### Regenerate the dashboards from code

```bash
python3 tools/dashboards/make_activite.py
python3 tools/dashboards/make_journaux.py
python3 tools/dashboards/make_ressources.py
python3 tools/dashboards/make_utilisateurs.py
git diff monitoring/grafana/dashboards/
```
They write into `monitoring/grafana/dashboards/`. Deploy with `sudo bash monitoring/install.sh dashboards`.

### Update the step-by-step documentation

Edit `tools/docs/build_steps.py`, then `python3 tools/docs/build_steps.py` (rewrites `docs/steps.json` and `docs/01-steps.md`).

## Where to look

| What | Command |
|---|---|
| Alloy log | `journalctl -u alloy -f` (VPS) |
| Postfix log | `journalctl -u postfix@- -f` (VPS) |
| Loki log | `journalctl -u loki -f` (n8nserver) |
| Prometheus log | `docker logs -f vps_prometheus` (n8nserver) |
| Grafana log | `journalctl -u grafana-server -f` (n8nserver) |
| Ports in use | `sudo ss -tulpn` |
| Firewall | `sudo ufw status numbered` |
| Tailscale | `tailscale status` |

## Upgrades

```bash
sudo apt-get update && sudo apt-get install --only-upgrade alloy            # VPS
sudo apt-get update && sudo apt-get install --only-upgrade grafana loki     # n8nserver
docker pull <image in monitoring/prometheus/container.env> && sudo RECREATE_PROMETHEUS=1 bash monitoring/install.sh prometheus
```
After an upgrade: `scripts/check.sh` on the server, then collect + import to record the new versions in `state/`.

## Git basics for this repository

```bash
git status                 # what changed
git diff                   # the exact changes
git log --oneline -20      # history
git add -A && git commit -m "message"   # record
git push                   # send to the remote
git pull                   # get the latest (on the servers)
git checkout -- <file>     # undo an uncommitted change to a file
git revert <commit>        # undo a committed change, keeping history
```
