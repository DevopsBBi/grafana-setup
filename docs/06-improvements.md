# Known weaknesses and next improvements

Ordered by importance. Each item says why it matters and what to do.

## 1. Alerts have a single path through the VPS
The alert emails leave through Postfix **on the VPS**. If the whole VPS is down, the "application silent" alert fires but cannot be sent.
- Add a second sender on n8nserver (direct delivery if the office line allows outgoing port 25, otherwise the company's SMTP server),
  as a second Grafana contact point for the "silent" rule.
- Add an outside check (a probe from another network) for the website.

## 2. Monitoring has a single server
Loki, Prometheus and Grafana all run on one office VM. If it stops, there is no monitoring and no alert.
- Back up `/var/lib/grafana/grafana.db`, the Loki data directory and the Prometheus volume (at least weekly).
- Alert on the monitoring server itself (Grafana down = nobody is told today).

## 3. Security hardening
- Grafana `admin` password: set a strong one (`GRAFANA_ADMIN_PASSWORD` + `monitoring/install.sh grafana`), give the manager a **Viewer** account.
- Docker ports bypass ufw: the Prometheus port 9091 (and the old Grafana on 3000) are reachable from the whole office network.
  Publish them only where needed: `-p 127.0.0.1:9091:9090 -p 100.118.61.101:9091:9090` in `container.env`, then recreate the container.
- VPS: disable `avahi-daemon` (not needed on a cloud server): `sudo systemctl disable --now avahi-daemon.socket avahi-daemon.service`.
- VPS: remove old ufw rules for 5432/8069 (both listen on 127.0.0.1 only); SSH with keys only (`PasswordAuthentication no`).
- Remove the old Docker Grafana (`mon_grafana`, port 3000) once nothing uses it.

## 4. Data retention and disk space
- Set an explicit retention in Loki (`limits_config.retention_period` + compactor) and Prometheus (`--storage.tsdb.retention.time`),
  and alert when the monitoring disk is above 80 %.

## 5. Alert quality
- Today every single error alerts. After a few weeks, raise thresholds where errors are known and harmless
  (for example "more than 5 errors in 15 minutes"), and add alerts on real impact: slow responses, disk > 85 %, failed services.
- Keep `docs/04-alerts-runbook.md` up to date with what you learn from each incident.

## 6. GDPR
The "Activité des utilisateurs" dashboard shows what each person does in the application.
Inform the staff, limit who can open this dashboard (Grafana folder permissions), and ask your DPO whether a privacy impact assessment is needed.

## 7. Automation
- Run `scripts/check.sh` from a systemd timer and alert on failure.
- Later: replace the install scripts with Ansible, and deploy from the repository automatically after each merge.
