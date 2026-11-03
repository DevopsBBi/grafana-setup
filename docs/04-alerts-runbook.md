# What to do when an alert email arrives

Alerts are defined in `monitoring/grafana/provisioning/alerting/supervision-odoo.yaml.tmpl` and evaluated every minute by Grafana on n8nserver.
You get one email when an alert starts (`[FIRING]`), a reminder every 4 hours while it lasts, and one email when it ends (`[RESOLVED]`).
Recipients: `ALERT_EMAILS` in `inventory.env`. Each email has a link to the matching panel of the "Journaux et erreurs" dashboard.

| Alert | Fires when | Severity |
|---|---|---|
| Erreurs Odoo | at least one ERROR or CRITICAL line in the application log in the last hour | critical |
| Erreurs PostgreSQL | at least one ERROR, FATAL or PANIC line in the PostgreSQL log in the last hour | critical |
| Erreurs du site web (5xx) | at least one 5xx answer from Nginx in the last hour | critical |
| Odoo silencieux ou collecte coupée | no application log line for 30 minutes (or the query fails) | critical |
| Erreurs des services système | a service wrote an error in the journal in the last hour (internet SSH scanner noise is filtered) | warning, one email per service |

An error alert stays `[FIRING]` for one hour after the **last** error, because the rules look at the last hour.

## Erreurs Odoo
1. Open the link in the email, or Grafana > "Journaux et erreurs" > application errors, over the last hour.
2. Read the first ERROR line and its traceback (one log entry = the whole traceback).
3. Common causes: a module bug after an update, an access right error, a failed scheduled action (cron), a timeout on an external API.
4. On the VPS: `sudo journalctl -u odoo -n 100` (or the application log file) for the surrounding context.

## Erreurs PostgreSQL
1. Dashboard panel "PostgreSQL" errors. `FATAL: password authentication failed` = a wrong login (check who: the line shows the user/database).
2. `ERROR: deadlock detected` / `canceling statement due to statement timeout` = heavy concurrent work: note the time and look at the
   slow requests in "Activité et performances".
3. `PANIC` or `could not write` = disk or crash: check disk space immediately (`df -h` on the VPS).

## Erreurs du site web (5xx)
- `502 Bad Gateway`: Nginx cannot reach the application. On the VPS: `systemctl status odoo`, `ss -ltnp | grep -E '8069|8072'`.
- `504 Gateway Timeout`: requests too slow: look at the slowest requests and the busy workers in "Consommation du serveur".
- `500`: the application raised an error: see "Erreurs Odoo" at the same minute.

## Odoo silencieux ou collecte coupée
Nothing has been received from the application log for 30 minutes. Find which link is broken, in this order:
1. Is the application running? `systemctl status odoo` on the VPS. (If it is down, the website 5xx alert usually fires too.)
2. Is Alloy running and healthy? `bash scripts/check.sh vps` on the VPS.
3. Is Tailscale up on both sides? `tailscale status`.
4. Is Loki running? `bash scripts/check.sh monitoring` on n8nserver.

## Erreurs des services système
The email names the service (`unit`). On the VPS: `sudo journalctl -u <unit> -p err --since "-1h"`.
If it is harmless noise that repeats, add a filter to the rule's query (like the SSH scanner filter) in the alert template, then
`sudo bash monitoring/install.sh alerting`.

## The alert emails themselves stop arriving
1. On n8nserver: Grafana > Alerting > Contact points > Test. If it fails: `bash scripts/check.sh monitoring` (mail relay reachable?).
2. On the VPS: `sudo journalctl -u postfix@- --since "-1h" | grep status=`
   - `status=sent` = delivered to the recipient's server: check the spam folder.
   - `status=deferred` / `bounced` = the recipient's server refused it: read the reason in the line (often SPF: the sender domain
     should list the VPS IP 83.228.207.124 in its SPF record).
   - no line at all = Grafana did not reach Postfix: firewall rule on tailscale0, or Postfix not listening on the Tailscale address
     (it starts after Tailscale; `systemctl restart postfix`).
3. Known limit: the relay runs on the VPS. If the whole VPS is down, the "silent" alert cannot be emailed (see docs/06-improvements.md).

## Pause an alert during planned maintenance
Grafana > Alerting > Silences > New silence, matcher `alertname = <rule title>`, for the maintenance window.
