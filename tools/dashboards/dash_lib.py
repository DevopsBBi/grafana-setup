"""Outils communs pour générer les tableaux de bord Grafana (Loki, Prometheus et base Odoo)."""
import json

# Noms des sources de données dans Grafana
LOKI = "loki"
PROM = "prometheus-2"
BBI = "BBi"  # PostgreSQL : base Odoo

# ---------------------------------------------------------------- journaux Loki
ODOO_ALL = '{job="odoo"}'
ODOO_ERR = '{job="odoo", level=~"ERROR|CRITICAL"}'
ODOO_WARN = '{job="odoo", level="WARNING"}'
PG_ALL = '{job="postgresql"}'
PG_ERR = '{job="postgresql"} |~ " (ERROR|FATAL|PANIC):"'
NGINX = '{job="nginx", stream="access", status=~".+"}'
NGINX_RAW = '{job="nginx", stream="access"}'
NGINX_4XX = '{job="nginx", status=~"4.."}'
NGINX_5XX = '{job="nginx", status=~"5.."}'
JOURNAL_ERR = '{job="systemd-journal", level=~"err|crit|alert|emerg"}'

# Ligne d'accès Odoo : ... "GET /api/v1/products HTTP/1.0" 200 - 381 0.674 1.338
ACCESS = (r'"[A-Z]+ (?P<section>/[^/ ?"]*(?:/[^/ ?"]*)?)[^"]*" [0-9]{3} - '
          r'(?P<sql_count>[0-9]+) (?P<sql_time>[0-9.]+) (?P<total_time>[0-9.]+)$')
BASE = rf'{{job="odoo"}} |~ `HTTP/1\.[01]" [0-9]{{3}} - ` | regexp `{ACCESS}` | __error__=""'
NOSTATIC = f'{BASE} | section!="/web/static"'

# Ligne d'accès Nginx (format par défaut) : IP, méthode, chemin, code, octets
NGINX_RE = (r'^(?P<ip>[^ ]+) [^ ]+ [^ ]+ \[[^\]]+\] "(?P<method>[A-Z]+) (?P<path>[^ ?"]*)[^"]*" '
            r'(?P<code>[0-9]{3}) (?P<bytes>[0-9]+)')
NGINX_P = f'{NGINX_RAW} | regexp `{NGINX_RE}` | __error__=""'


def quant(q, field, rng="$__range"):
    return f'quantile_over_time({q}, {BASE} | unwrap {field} [{rng}]) by (job)'


def avg(field, rng="$__range"):
    return f'avg_over_time({BASE} | unwrap {field} [{rng}]) by (job)'


RPM = f'sum(count_over_time({BASE} [1m]))'
CLASSES = [
    ("Succès (2xx)", r'HTTP/1\.[01]" 2[0-9]{2} '),
    ("Redirection (3xx)", r'HTTP/1\.[01]" 3[0-9]{2} '),
    ("Erreur client (4xx)", r'HTTP/1\.[01]" 4[0-9]{2} '),
    ("Erreur serveur (5xx)", r'HTTP/1\.[01]" 5[0-9]{2} '),
]
CLASS_COLORS = {"Succès (2xx)": "green", "Redirection (3xx)": "blue",
                "Erreur client (4xx)": "yellow", "Erreur serveur (5xx)": "red"}
CLASS_RATE = [(name, f'sum(count_over_time({{job="odoo"}} |~ `{pat}` [1m]))') for name, pat in CLASSES]
SECTION_COUNT = f'sum by (section) (count_over_time({NOSTATIC} [$__range]))'
SECTION_AVG = {f: f'avg_over_time({NOSTATIC} | unwrap {f} [$__range]) by (section)'
               for f in ["sql_count", "sql_time", "total_time"]}

ERR_ODOO_TOTAL = f'sum(count_over_time({ODOO_ERR} [$__range]))'
ERR_PG_TOTAL = f'sum(count_over_time({PG_ERR} [$__range]))'
ERR_ODOO_RATE = (f'100 * sum(count_over_time({ODOO_ERR} [$__range])) '
                 f'/ sum(count_over_time({ODOO_ALL} [$__range]))')
PG_LINES_TOTAL = f'sum(count_over_time({PG_ALL} [$__range]))'
NGINX_TOTAL = f'sum(count_over_time({NGINX} [$__range]))'
SERVER_5XX = f'sum(count_over_time({NGINX_5XX} [$__range]))'
CLIENT_4XX = f'sum(count_over_time({NGINX_4XX} [$__range]))'
WEB_ERR_RATE = (f'100 * sum(count_over_time({NGINX_5XX} [$__range])) '
                f'/ sum(count_over_time({NGINX} [$__range]))')
ODOO_5XX_RATE = (f'100 * sum(count_over_time({{job="odoo"}} |~ `{CLASSES[3][1]}` [$__range])) '
                 f'/ sum(count_over_time({BASE} [$__range]))')
BYTES_SENT = f'sum(sum_over_time({NGINX_P} | unwrap bytes [$__range]))'
BYTES_PER_MIN = f'sum(sum_over_time({NGINX_P} | unwrap bytes [1m]))'
NGINX_ERR_LOG = '{job="nginx", stream="error"}'
LINES_BY_JOB = 'sum by (job) (count_over_time({job=~".+"} [1m]))'
TOP_PAGES = f'topk(10, sum by (path) (count_over_time({NGINX_P} | path!~"/web/static.*" [$__range])))'
SYS_TABLE = f'sum by (unit) (count_over_time({JOURNAL_ERR} [$__range]))'
SYS_TOP5 = f'topk(5, sum by (unit) (count_over_time({JOURNAL_ERR} [5m])))'

# ---------------------------------------------------------------- métriques Prometheus (serveur)
CPU = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
RAM = '100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)'
FS = '{fstype!~"tmpfs|overlay|squashfs|vfat|devtmpfs"}'
DISK_USED = f'100 * (1 - node_filesystem_avail_bytes{FS} / node_filesystem_size_bytes{FS})'
DISK_MAX = f'max({DISK_USED})'
DISK_BY = f'max by (mountpoint) ({DISK_USED})'
CPU_BY_MODE = '100 * avg by (mode) (rate(node_cpu_seconds_total{mode=~"user|system|iowait"}[5m]))'
SWAP = '100 * (1 - node_memory_SwapFree_bytes / node_memory_SwapTotal_bytes)'
MEM_USED = 'node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes'
MEM_TOTAL = 'node_memory_MemTotal_bytes'
CORES = 'count(count by (cpu) (node_cpu_seconds_total))'
LOAD1 = 'node_load1'
LOAD5 = 'node_load5'
LOAD15 = 'node_load15'
UPTIME = 'time() - node_boot_time_seconds'
PROCS = 'node_procs_running'
DISK_READ = 'sum(rate(node_disk_read_bytes_total[5m]))'
DISK_WRITE = 'sum(rate(node_disk_written_bytes_total[5m]))'
NET_DEV = '{device!~"lo|docker.*|veth.*|br-.*"}'
NET_IN = f'sum(rate(node_network_receive_bytes_total{NET_DEV}[5m]))'
NET_OUT = f'sum(rate(node_network_transmit_bytes_total{NET_DEV}[5m]))'
FAILED_UNITS = 'sum(node_systemd_unit_state{state="failed"})'

# Consommation par composant (prometheus.exporter.process "services" dans Alloy)
NCPU = 'scalar(count(count by (cpu) (node_cpu_seconds_total)))'
PROC_CPU_ALL = f'100 * sum by (groupname) (rate(namedprocess_namegroup_cpu_seconds_total[5m])) / {NCPU}'
PROC_MEM_ALL = 'sum by (groupname) (namedprocess_namegroup_memory_bytes{memtype="resident"})'
PROC_NUM = 'sum by (groupname) (namedprocess_namegroup_num_procs)'
PROC_CPU_TOP = f'topk(8, {PROC_CPU_ALL})'
PROC_MEM_TOP = f'topk(8, {PROC_MEM_ALL})'


def comp_cpu(group):
    return (f'100 * sum(rate(namedprocess_namegroup_cpu_seconds_total{{groupname="{group}"}}[5m])) '
            f'/ {NCPU}')


def comp_mem(group):
    return f'sum(namedprocess_namegroup_memory_bytes{{groupname="{group}", memtype="resident"}})'


# ---------------------------------------------------------------- workers Odoo
# Prometheus (groupe "odoo" de prometheus.exporter.process)
ODOO_PROCS = 'sum(namedprocess_namegroup_num_procs{groupname="odoo"})'
ODOO_BUSY = 'sum(namedprocess_namegroup_states{groupname="odoo", state="Running"})'
ODOO_MEM_AVG = ('sum(namedprocess_namegroup_memory_bytes{groupname="odoo", memtype="resident"}) '
                '/ sum(namedprocess_namegroup_num_procs{groupname="odoo"})')
ODOO_UPTIME = 'time() - min(namedprocess_namegroup_oldest_start_time_seconds{groupname="odoo"})'
ODOO_FD = '100 * max(namedprocess_namegroup_worst_fd_ratio{groupname="odoo"})'
# Loki : le 3e champ d'une ligne Odoo est le PID du worker qui a traité la requête
PID_RE = r'^\S+ \S+ (?P<pid>[0-9]+) '
WBASE = f'{BASE} | regexp `{PID_RE}` | __error__=""'
WORKERS_SERVING_5M = f'count(sum by (pid) (count_over_time({WBASE} [5m])))'
WORKERS_SERVING_TS = f'count(sum by (pid) (count_over_time({WBASE} [1m])))'
REQ_BY_PID = f'sum by (pid) (count_over_time({WBASE} [$__range]))'
AVG_BY_PID = f'avg_over_time({WBASE} | unwrap total_time [$__range]) by (pid)'
WORKER_EVENTS = '{job="odoo"} |~ `odoo\\.service\\.server`'


def odoo_count(pattern):
    """Lignes du gestionnaire de workers Odoo (odoo.service.server) contenant le motif."""
    return f'sum(count_over_time({{job="odoo"}} |~ `(?i)odoo\\.service\\.server: .*{pattern}` [$__range]))'


SQL_ODOO_CONN = """SELECT COUNT(*) AS "Connexions"
FROM pg_stat_activity
WHERE datname = current_database() AND backend_type = 'client backend'"""

# ---------------------------------------------------------------- base Odoo en direct (SQL, source BBi)
CLIENTS = "backend_type = 'client backend'"
SQL_CONN_PCT = f"""SELECT ROUND(100.0 * COUNT(*) / current_setting('max_connections')::int, 1) AS "Connexions utilisées"
FROM pg_stat_activity
WHERE {CLIENTS}"""
SQL_ACTIVE = f"""SELECT COUNT(*) AS "Requêtes en cours"
FROM pg_stat_activity
WHERE {CLIENTS} AND state = 'active' AND pid <> pg_backend_pid()"""
SQL_BLOCKED = f"""SELECT COUNT(*) AS "Requêtes bloquées"
FROM pg_stat_activity
WHERE {CLIENTS} AND wait_event_type = 'Lock'"""
SQL_LONGEST = f"""SELECT COALESCE(MAX(EXTRACT(EPOCH FROM now() - query_start)), 0) AS "Durée"
FROM pg_stat_activity
WHERE {CLIENTS} AND state = 'active' AND pid <> pg_backend_pid()"""
SQL_DB_SIZE = """SELECT pg_database_size(current_database()) AS "Taille\""""
SQL_CACHE = """SELECT ROUND(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2) AS "Cache"
FROM pg_stat_database
WHERE datname = current_database()"""
SQL_BY_STATE = f"""SELECT COALESCE(state, 'inconnu') AS "État", COUNT(*) AS "Connexions"
FROM pg_stat_activity
WHERE {CLIENTS}
GROUP BY 1
ORDER BY 2 DESC"""
SQL_BIG_TABLES = """SELECT relname AS "Table", pg_total_relation_size(relid) AS "Taille"
FROM pg_stat_user_tables
ORDER BY 2 DESC
LIMIT 10"""
SQL_LONG_QUERIES = rf"""SELECT ROUND(EXTRACT(EPOCH FROM now() - query_start)::numeric, 1) AS "Durée (s)",
       state AS "État",
       COALESCE(wait_event_type, '') AS "Attente",
       LEFT(regexp_replace(query, '\s+', ' ', 'g'), 80) AS "Début de la requête"
FROM pg_stat_activity
WHERE {CLIENTS} AND state <> 'idle' AND pid <> pg_backend_pid()
ORDER BY query_start ASC NULLS LAST
LIMIT 10"""
SQL_TEMP = """SELECT temp_bytes AS "Fichiers temporaires"
FROM pg_stat_database
WHERE datname = current_database()"""

# ---------------------------------------------------------------- utilisateurs Odoo (SQL, source BBi)
SQL_USERS_CONNECTED = """SELECT COUNT(*) FROM res_users u
WHERE u.active AND $__timeFilter(u.login_date)"""
SQL_ACTORS = """SELECT COUNT(DISTINCT m.author_id) FROM mail_message m
WHERE m.author_id IS NOT NULL AND $__timeFilter(m.date)"""
SQL_MESSAGES = """SELECT COUNT(*) FROM mail_message m
WHERE m.author_id IS NOT NULL AND $__timeFilter(m.date)"""
SQL_CHANGES = """SELECT COUNT(*) FROM mail_tracking_value tv
JOIN mail_message m ON m.id = tv.mail_message_id
WHERE $__timeFilter(m.date)"""
SQL_ACTIVITY_TS = """SELECT $__timeGroup(m.date, '1h') AS time, COUNT(*) AS "Actions"
FROM mail_message m
WHERE m.author_id IS NOT NULL AND $__timeFilter(m.date)
GROUP BY 1
ORDER BY 1"""
SQL_PER_USER = """SELECT p.name AS "Utilisateur",
       u.login_date AS "Dernière connexion",
       COALESCE(s.nb, 0) AS "Actions (période)",
       s.last_at AS "Dernière action"
FROM res_users u
JOIN res_partner p ON p.id = u.partner_id
LEFT JOIN (
    SELECT m.author_id, COUNT(*) AS nb, MAX(m.date) AS last_at
    FROM mail_message m
    WHERE m.author_id IS NOT NULL AND $__timeFilter(m.date)
    GROUP BY m.author_id
) s ON s.author_id = p.id
WHERE u.active
ORDER BY "Dernière connexion" DESC NULLS LAST
LIMIT 100"""
SQL_RECENT_MSG = """SELECT m.date AS "Date",
       p.name AS "Utilisateur",
       m.model AS "Type de fiche",
       m.res_id AS "N° fiche",
       LEFT(regexp_replace(COALESCE(m.body, ''), '<[^>]+>', ' ', 'g'), 150) AS "Message"
FROM mail_message m
JOIN res_partner p ON p.id = m.author_id
WHERE $__timeFilter(m.date)
ORDER BY m.date DESC
LIMIT 200"""
SQL_RECENT_CHANGES = """SELECT m.date AS "Date",
       p.name AS "Utilisateur",
       m.model AS "Type de fiche",
       m.res_id AS "N° fiche",
       f.name AS "Champ",
       tv.old_value_char AS "Avant",
       tv.new_value_char AS "Après"
FROM mail_tracking_value tv
JOIN mail_message m ON m.id = tv.mail_message_id
LEFT JOIN res_partner p ON p.id = m.author_id
LEFT JOIN ir_model_fields f ON f.id = tv.field_id
WHERE $__timeFilter(m.date)
ORDER BY m.date DESC
LIMIT 200"""

# Liens entre les trois pages (même étiquette)
SUITE_TAG = "supervision-odoo"
SUITE_LINKS = [{"title": "Autres pages de supervision", "type": "dashboards", "tags": [SUITE_TAG],
                "asDropdown": False, "keepTime": True, "includeVars": False,
                "targetBlank": False, "icon": "external link"}]


def rename_override(name, display):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "displayName", "value": display}]}

# ---------------------------------------------------------------- seuils et options
ALERT = [{"color": "green", "value": None}, {"color": "red", "value": 1}]
WARN = [{"color": "green", "value": None}, {"color": "yellow", "value": 1}]
CHECK = [{"color": "red", "value": None}, {"color": "green", "value": 1}]
CACHE_TH = [{"color": "red", "value": None}, {"color": "yellow", "value": 90},
            {"color": "green", "value": 99}]


def warn_bad(warn, bad):
    return [{"color": "green", "value": None},
            {"color": "yellow", "value": warn},
            {"color": "red", "value": bad}]


def color_override(name, color):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}


def unit_override(name, unit, decimals=None):
    props = [{"id": "unit", "value": unit}]
    if decimals is not None:
        props.append({"id": "decimals", "value": decimals})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


STAT_OPTS = {
    "colorMode": "background",
    "graphMode": "none",
    "textMode": "value",
    "justifyMode": "center",
    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
}
GAUGE_OPTS = {
    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    "showThresholdMarkers": True,
    "showThresholdLabels": False,
}
LINE = {"lineWidth": 2, "fillOpacity": 8, "showPoints": "never"}
LOG_OPTS = {
    "showTime": True,
    "showLabels": False,
    "showCommonLabels": False,
    "wrapLogMessage": True,
    "prettifyLogMessage": False,
    "enableLogDetails": True,
    "dedupStrategy": "none",
    "sortOrder": "Descending",
}


def _targets(ds, items, instant=False):
    out = []
    for i, (expr, legend) in enumerate(items):
        t = {"refId": chr(65 + i), "datasource": ds, "expr": expr, "legendFormat": legend}
        if ds == PROM:
            t["instant"] = instant
            t["range"] = not instant
        elif instant:
            t["queryType"] = "instant"
        out.append(t)
    return out


def _sql_targets(sql, fmt="table"):
    return [{"refId": "A", "datasource": BBI, "editorMode": "code", "format": fmt,
             "rawQuery": True, "rawSql": sql}]


def _stat_defaults(unit, decimals, thresholds, color, nodata):
    d = {"decimals": decimals}
    if unit:
        d["unit"] = unit
    if nodata is not None:
        d["noValue"] = nodata
    if color:
        d["color"] = {"mode": "fixed", "fixedColor": color}
    elif thresholds:
        d["thresholds"] = {"mode": "absolute", "steps": thresholds}
    return d


class Board:
    """Disposition simple : les panneaux se rangent de gauche à droite, ligne par ligne."""

    def __init__(self):
        self.panels = []
        self.target = self.panels
        self.x = 0
        self.y = 0
        self.rowh = 0
        self.n = 0

    def _id(self):
        self.n += 1
        return self.n

    def _flush(self):
        self.y += self.rowh
        self.x = 0
        self.rowh = 0

    def _place(self, w, h):
        if self.x + w > 24:
            self.x = 0
            self.y += self.rowh
            self.rowh = 0
        x, y = self.x, self.y
        self.x += w
        self.rowh = max(self.rowh, h)
        return x, y

    def _add(self, panel_type, title, w, h, desc="", **fields):
        x, y = self._place(w, h)
        p = {"id": self._id(), "type": panel_type, "title": title, "description": desc,
             "gridPos": {"h": h, "w": w, "x": x, "y": y}}
        p.update(fields)
        self.target.append(p)

    # ------------------------------------------------ lignes et texte
    def row(self, title):
        self._flush()
        self.target = self.panels
        self.panels.append({"id": self._id(), "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []})
        self.y += 1

    def begin_collapsed(self, title):
        self._flush()
        self.target = self.panels
        row = {"id": self._id(), "type": "row", "title": title, "collapsed": True,
               "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []}
        self.panels.append(row)
        self.target = row["panels"]
        self.y += 1

    def end_collapsed(self):
        self._flush()
        self.target = self.panels

    def text(self, content, h):
        self._add("text", "", 24, h, options={"mode": "markdown", "content": content})

    # ------------------------------------------------ Loki et Prometheus
    def stat(self, title, w, ds, expr, desc, unit=None, decimals=0, thresholds=None,
             color=None, nodata="0"):
        self._add("stat", title, w, 4, desc, datasource=ds,
                  fieldConfig={"defaults": _stat_defaults(unit, decimals, thresholds, color, nodata),
                               "overrides": []},
                  targets=_targets(ds, [(expr, "")], instant=True), options=STAT_OPTS)

    def gauge(self, title, expr, desc, w=6, warn=70, bad=90):
        d = {"unit": "percent", "min": 0, "max": 100, "decimals": 0,
             "thresholds": {"mode": "absolute", "steps": warn_bad(warn, bad)}}
        self._add("gauge", title, w, 6, desc, datasource=PROM,
                  fieldConfig={"defaults": d, "overrides": []},
                  targets=_targets(PROM, [(expr, "")], instant=True), options=GAUGE_OPTS)

    def ts(self, title, ds, items, desc, w=12, h=8, unit=None, lo=None, decimals=None,
           overrides=None):
        d = {"custom": LINE}
        if unit:
            d["unit"] = unit
        if lo is not None:
            d["min"] = lo
        if decimals is not None:
            d["decimals"] = decimals
        self._add("timeseries", title, w, h, desc, datasource=ds,
                  fieldConfig={"defaults": d, "overrides": overrides or []},
                  targets=_targets(ds, items))

    def table(self, title, ds, items, renames, sort_by, desc, w=12, h=8, unit=None,
              overrides=None):
        d = {"custom": {"align": "auto"}}
        if unit:
            d["unit"] = unit
        self._add("table", title, w, h, desc, datasource=ds,
                  fieldConfig={"defaults": d, "overrides": overrides or []},
                  targets=_targets(ds, items, instant=True),
                  transformations=[
                      {"id": "merge", "options": {}},
                      {"id": "organize", "options": {
                          "excludeByName": {"Time": True},
                          "renameByName": renames}},
                  ],
                  options={"sortBy": [{"displayName": sort_by, "desc": True}],
                           "showHeader": True})

    def logs(self, title, ds, expr, desc, w=12, h=12):
        self._add("logs", title, w, h, desc, datasource=ds,
                  targets=_targets(ds, [(expr, "")]), options=LOG_OPTS)

    # ------------------------------------------------ base Odoo (SQL, source BBi)
    def sql_stat(self, title, w, sql, desc, unit=None, decimals=0, thresholds=None,
                 color=None, nodata="0"):
        self._add("stat", title, w, 4, desc, datasource=BBI,
                  fieldConfig={"defaults": _stat_defaults(unit, decimals, thresholds, color, nodata),
                               "overrides": []},
                  targets=_sql_targets(sql), options=STAT_OPTS)

    def sql_ts(self, title, sql, desc, w=12, h=8):
        self._add("timeseries", title, w, h, desc, datasource=BBI,
                  fieldConfig={"defaults": {"min": 0, "decimals": 0, "custom": LINE},
                               "overrides": []},
                  targets=_sql_targets(sql, "time_series"))

    def sql_table(self, title, sql, desc, w=12, h=8, overrides=None):
        self._add("table", title, w, h, desc, datasource=BBI,
                  fieldConfig={"defaults": {"custom": {"align": "auto"}},
                               "overrides": overrides or []},
                  targets=_sql_targets(sql), options={"showHeader": True})

    # ------------------------------------------------ sortie
    def count(self):
        n = 0
        for p in self.panels:
            n += 1 + len(p.get("panels", []))
        return n

    def save(self, path, title, uid, desc, tags, time_from, variables=None, links=None):
        dash = {
            "title": title,
            "uid": uid,
            "description": desc,
            "tags": tags,
            "links": links or [],
            "timezone": "browser",
            "editable": True,
            "graphTooltip": 1,
            "schemaVersion": 27,
            "version": 1,
            "refresh": "30s",
            "time": {"from": time_from, "to": "now"},
            "templating": {"list": variables or []},
            "panels": self.panels,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dash, f, indent=2, ensure_ascii=False)
        return path


# ---------------------------------------------------------------- sections communes
def database_section(b, compact=False):
    """Base Odoo en direct, lue avec la source BBi (fonctionne sans Prometheus)."""
    b.row("Base de données PostgreSQL (en direct)")
    w = 8 if compact else 4
    b.sql_stat("Connexions utilisées", w, SQL_CONN_PCT,
               "Part des connexions possibles déjà ouvertes, maintenant. Jaune dès 70 %, rouge dès 90 %.",
               unit="percent", decimals=1, thresholds=warn_bad(70, 90))
    if not compact:
        b.sql_stat("Requêtes en cours", w, SQL_ACTIVE,
                   "Requêtes que la base exécute en ce moment.", color="blue")
    b.sql_stat("Requêtes bloquées", w, SQL_BLOCKED,
               "Requêtes qui attendent qu'une autre libère un verrou. Jaune dès 1, rouge dès 5.",
               thresholds=warn_bad(1, 5))
    b.sql_stat("Requête la plus longue", w, SQL_LONGEST,
               "Durée de la requête en cours la plus ancienne. Jaune au-delà de 30 s, rouge au-delà de 2 min.",
               unit="s", decimals=1, thresholds=warn_bad(30, 120))
    if compact:
        return
    b.sql_stat("Taille de la base", w, SQL_DB_SIZE,
               "Espace disque occupé par la base Odoo.",
               unit="bytes", decimals=1, color="blue", nodata=None)
    b.sql_stat("Lectures servies par le cache", w, SQL_CACHE,
               "Part des lectures servies depuis la mémoire plutôt que le disque. Vert au-dessus de 99 %.",
               unit="percent", decimals=1, thresholds=CACHE_TH, nodata=None)
    b.sql_table("Connexions par état", SQL_BY_STATE,
                "Connexions ouvertes, par état (active = en train de travailler, idle = en attente).",
                w=8, h=8)
    b.sql_table("Plus grosses tables", SQL_BIG_TABLES,
                "Les 10 tables qui occupent le plus de place.",
                w=8, h=8, overrides=[unit_override("Taille", "bytes", 1)])
    b.sql_table("Requêtes en cours les plus longues", SQL_LONG_QUERIES,
                "Requêtes encore en cours, de la plus ancienne à la plus récente.",
                w=8, h=8)


def server_section(b):
    """Santé du serveur : CPU, mémoire, disque (Prometheus), repliée."""
    b.begin_collapsed("Serveur : processeur, mémoire, disque (cliquer pour afficher)")
    b.gauge("Processeur (CPU)", CPU,
            "Part du temps où le processeur travaille. Jaune dès 70 %, rouge dès 90 %.", w=8)
    b.gauge("Mémoire (RAM)", RAM,
            "Part de la mémoire vive utilisée. Jaune dès 70 %, rouge dès 90 %.", w=8)
    b.gauge("Disque le plus plein", DISK_MAX,
            "Partition la plus remplie du serveur. Jaune dès 70 %, rouge dès 90 %.", w=8)
    b.ts("Processeur et mémoire au cours du temps", PROM,
         [(CPU, "Processeur"), (RAM, "Mémoire")],
         "Évolution du processeur et de la mémoire, en pourcentage.",
         unit="percent", lo=0, decimals=0)
    b.table("Disques : espace utilisé par partition", PROM,
            [(DISK_BY, "")],
            {"mountpoint": "Partition", "Value": "Utilisé (%)", "Value #A": "Utilisé (%)"},
            "Utilisé (%)", "Espace utilisé sur chaque partition.", unit="percent")
    b.end_collapsed()
