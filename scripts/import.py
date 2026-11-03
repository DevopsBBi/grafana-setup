#!/usr/bin/env python3
"""Import the archives made by scripts/collect-vps.sh and scripts/collect-monitoring.sh into this repository.

    python3 scripts/import.py _import/collect-vps-*.tgz _import/collect-monitoring-*.tgz

What it does (run it from anywhere, it works on the repository it belongs to):
  * live configuration files  -> their place in vps/ and monitoring/ (the live server is the truth)
  * live values (uids, paths, ports) -> inventory.env
  * snapshots (ports, firewall, versions, roles...) -> state/vps/ and state/monitoring/
Nothing is committed: review with "git status" and "git diff", then commit.
Only the Python standard library is used (works with the python3 of macOS).
"""
import datetime
import json
import os
import re
import shlex
import shutil
import sys
import tarfile
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.date.today().isoformat()
NOTES = []


def p(*parts):
    return os.path.join(REPO, *parts)


def note(msg):
    NOTES.append(msg)
    print("  ! " + msg)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = read(path) if os.path.exists(path) else None
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    rel = os.path.relpath(path, REPO)
    print(("  = " if old == text else ("  ~ " if old is not None else "  + ")) + rel)


# ---------------------------------------------------------------- inventory.env
def inventory():
    vals = {}
    for line in read(p("inventory.env")).splitlines():
        m = re.match(r'^([A-Z0-9_]+)="?([^"#]*)"?', line)
        if m:
            vals[m.group(1)] = m.group(2).strip()
    return vals


def set_inventory(name, value):
    text = read(p("inventory.env"))
    pat = re.compile(r'(?m)^(' + re.escape(name) + r')="[^"]*"')
    if pat.search(text):
        new = pat.sub(lambda m: f'{m.group(1)}="{value}"', text, count=1)
    else:
        new = text.rstrip("\n") + f'\n{name}="{value}"\n'
    if new != text:
        with open(p("inventory.env"), "w", encoding="utf-8") as f:
            f.write(new)
        print(f"  ~ inventory.env: {name}={value}")


def snapshot(src_dir, dest_dir, names):
    for n in names:
        s = os.path.join(src_dir, n)
        if os.path.isfile(s):
            write(p(dest_dir, n), read(s))


# ---------------------------------------------------------------- application server
def import_vps(d):
    print("\n== application server (VPS)")
    cfg = os.path.join(d, "config.alloy")
    if os.path.isfile(cfg):
        text = read(cfg)
        # the PostgreSQL password is not stored in git: Alloy reads the whole connection string from the environment
        text, n = re.subn(r'data_source_names\s*=\s*\[[^\]]*REDACTED[^\]]*\]',
                          'data_source_names = [sys.env("ALLOY_PG_DSN")]', text)
        if n:
            print(f"  > PostgreSQL connection string replaced by sys.env(\"ALLOY_PG_DSN\") ({n}x)")
        for i, line in enumerate(text.splitlines(), 1):
            if "REDACTED" in line:
                note(f"vps/alloy/config.alloy line {i} still holds a removed secret: move it to /etc/default/alloy with sys.env(...)")
        header = f"// Grafana Alloy configuration of the application server.\n// Imported from the live server on {TODAY} (scripts/import.py). Deployed by vps/install.sh.\n"
        text = re.sub(r"\A(// Grafana Alloy configuration of the application server\.\n// Imported .*\n)", "", text)
        write(p("vps", "alloy", "config.alloy"), header + text)
    else:
        note("config.alloy missing from the VPS archive")
    snapshot(d, os.path.join("state", "vps"), sorted(f for f in os.listdir(d) if f != "config.alloy"))


# ---------------------------------------------------------------- monitoring server
def docker_args(inspect):
    c = inspect[0]
    cfg, host = c.get("Config", {}), c.get("HostConfig", {})
    args = []
    for port, binds in sorted((host.get("PortBindings") or {}).items()):
        for b in binds or []:
            hip = b.get("HostIp") or ""
            pub = (f"{hip}:" if hip and hip not in ("0.0.0.0", "::") else "") + f"{b.get('HostPort')}:{port.split('/')[0]}"
            args += ["-p", pub]
    cfg_host = ""
    for m in c.get("Mounts", []):
        src = m.get("Name") if m.get("Type") == "volume" else m.get("Source")
        ro = "" if m.get("RW", True) else ":ro"
        args += ["-v", f"{src}:{m['Destination']}{ro}"]
        if m.get("Destination") == "/etc/prometheus/prometheus.yml":
            cfg_host = m.get("Source", "")
        elif m.get("Destination") == "/etc/prometheus" and m.get("Type") == "bind":
            cfg_host = os.path.join(m.get("Source", ""), "prometheus.yml")
    for e in cfg.get("Env") or []:
        k = e.split("=", 1)[0]
        if k in ("PATH",) or e.endswith("=REDACTED"):
            continue
        args += ["-e", e]
    net = host.get("NetworkMode")
    if net and net not in ("default", "bridge"):
        args += ["--network", net]
    if cfg.get("User"):
        args += ["--user", cfg["User"]]
    restart = (host.get("RestartPolicy") or {}).get("Name") or "unless-stopped"
    if restart == "no":
        restart = "unless-stopped"
    return cfg.get("Image", ""), restart, cfg_host, args, cfg.get("Cmd") or []


def bash_array(items):
    return "(" + " ".join(shlex.quote(x) for x in items) + ")"


def import_monitoring(d, inv):
    print("\n== monitoring server (n8nserver)")
    # Loki
    if os.path.isfile(os.path.join(d, "loki-config.yaml")):
        text = read(os.path.join(d, "loki-config.yaml"))
        if "REDACTED" in text:
            note("monitoring/loki/config.yaml contains a removed secret: put it back by hand on the server or use an environment variable")
        write(p("monitoring", "loki", "config.yaml"), f"# Loki configuration of the monitoring server. Imported on {TODAY} (scripts/import.py).\n" + re.sub(r"\A# Loki configuration.*\n", "", text))
        path = read(os.path.join(d, "loki-config-path.txt")).strip()
        if path.startswith("/"):
            set_inventory("LOKI_CONFIG_PATH", path)
    else:
        note("Loki configuration not found in the archive (is Loki installed as the 'loki' service?)")

    # Prometheus
    if os.path.isfile(os.path.join(d, "prometheus.yml")):
        write(p("monitoring", "prometheus", "prometheus.yml"), read(os.path.join(d, "prometheus.yml")))
    if os.path.isfile(os.path.join(d, "prometheus-inspect.json")):
        image, restart, cfg_host, args, cmd = docker_args(json.load(open(os.path.join(d, "prometheus-inspect.json"))))
        write(p("monitoring", "prometheus", "container.env"),
              "# How the Prometheus container is started (from \"docker inspect\" of the live container, "
              f"{TODAY}).\n# Used by monitoring/install.sh: docker run -d --name $PROM_CONTAINER --restart $PROM_RESTART "
              "${PROM_DOCKER_ARGS[@]} $PROM_IMAGE ${PROM_CMD[@]}\n"
              f"PROM_IMAGE={shlex.quote(image)}\nPROM_RESTART={shlex.quote(restart)}\n"
              f"PROM_CONFIG_HOST_PATH={shlex.quote(cfg_host)}\n"
              f"PROM_DOCKER_ARGS={bash_array(args)}\nPROM_CMD={bash_array(cmd)}\n")
        if "--web.enable-remote-write-receiver" not in " ".join(cmd) and "remote-write-receiver" not in " ".join(cmd):
            note("Prometheus is not started with --web.enable-remote-write-receiver: check how Alloy's metrics are received")
        if any(a.startswith("-p") for a in args) and not any(re.match(r"^\d+\.\d+\.\d+\.\d+:", a) for a in args):
            note("the Prometheus port is published on every interface: Docker bypasses ufw (see docs/06-improvements.md)")

    # Grafana data sources -> provisioning templates + uids in inventory.env
    dsf = os.path.join(d, "datasources.json")
    if os.path.isfile(dsf):
        dss = json.load(open(dsf, encoding="utf-8"))
        main, pg = [], None
        for ds in dss:
            item = {"name": ds["name"], "type": ds["type"], "uid": ds.get("uid"), "access": ds.get("access") or "proxy",
                    "url": ds.get("url") or "", "isDefault": bool(ds.get("is_default")), "editable": True}
            if ds.get("user"):
                item["user"] = ds["user"]
            if ds.get("database"):
                item["database"] = ds["database"]
            if isinstance(ds.get("json_data"), dict) and ds["json_data"]:
                item["jsonData"] = ds["json_data"]
            if ds.get("basic_auth"):
                note(f"data source {ds['name']} uses basic auth: its password must be added by hand")
            if ds["name"] == inv.get("DS_LOKI_NAME"):
                set_inventory("DS_LOKI_UID", ds.get("uid") or "")
            if ds["name"] == inv.get("DS_PROM_NAME"):
                set_inventory("DS_PROM_UID", ds.get("uid") or "")
            if ds["name"] == inv.get("DS_PG_NAME"):
                set_inventory("DS_PG_UID", ds.get("uid") or "")
                item["secureJsonData"] = {"password": "@@GRAFANA_PG_PASSWORD@@"}
                pg = item
            elif ds["type"] in ("postgres", "grafana-postgresql-datasource", "mysql", "mssql"):
                note(f"data source {ds['name']} ({ds['type']}) needs a password: not provisioned, kept as configured in Grafana")
            else:
                main.append(item)
        head = (f"# Grafana data sources, generated by scripts/import.py from the live Grafana ({TODAY}).\n"
                "# JSON is valid YAML. Rendered by monitoring/install.sh into /etc/grafana/provisioning/datasources/.\n")
        write(p("monitoring", "grafana", "provisioning", "datasources", "datasources.yaml.tmpl"),
              head + json.dumps({"apiVersion": 1, "datasources": main}, indent=2, ensure_ascii=False) + "\n")
        if pg:
            write(p("monitoring", "grafana", "provisioning", "datasources", "postgres.yaml.tmpl"),
                  head + "# The password comes from secrets.env (GRAFANA_PG_PASSWORD).\n"
                  + json.dumps({"apiVersion": 1, "datasources": [pg]}, indent=2, ensure_ascii=False) + "\n")

    # dashboards: the ones of the monitoring folder (plus the ones already in git) replace the repository copies
    idx = os.path.join(d, "dashboards-index.tsv")
    if os.path.isfile(idx):
        known = {}
        for f in sorted(os.listdir(p("monitoring", "grafana", "dashboards"))):
            if f.endswith(".json"):
                try:
                    known[json.load(open(p("monitoring", "grafana", "dashboards", f), encoding="utf-8")).get("uid")] = f
                except Exception:
                    pass
        others = ["uid\tfolder\ttitle"]
        for line in read(idx).splitlines()[1:]:
            uid, folder, title, fn = line.split("\t")
            if folder == inv.get("GRAFANA_FOLDER") or uid in known:
                data = json.load(open(os.path.join(d, "dashboards", fn), encoding="utf-8"))
                data.pop("id", None)
                data.pop("version", None)
                target = known.get(uid) or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") + ".json"
                write(p("monitoring", "grafana", "dashboards", target), json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            else:
                others.append(f"{uid}\t{folder}\t{title}")
        write(p("state", "monitoring", "other-dashboards.tsv"), "\n".join(others) + "\n")

    # dashboard.local: what Nginx forwards to
    ng = os.path.join(d, "nginx-dashboard.local.conf")
    if os.path.isfile(ng):
        m = re.search(r"proxy_pass\s+([^;]+);", read(ng))
        if m:
            set_inventory("DASHBOARD_UPSTREAM", m.group(1).strip())

    # Grafana port
    gi = os.path.join(d, "grafana.ini")
    if os.path.isfile(gi):
        m = re.search(r"(?m)^\s*http_port\s*=\s*(\d+)", read(gi))
        if m and m.group(1) != inv.get("GRAFANA_PORT"):
            set_inventory("GRAFANA_PORT", m.group(1))

    keep = sorted(f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)) and f not in
                  ("loki-config.yaml", "prometheus.yml", "datasources.json"))
    snapshot(d, os.path.join("state", "monitoring"), keep)
    prov = os.path.join(d, "grafana-provisioning")
    for root, _, files in os.walk(prov):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), prov)
            write(p("state", "monitoring", "grafana-provisioning", rel), read(os.path.join(root, f)))


def main(paths):
    if not paths:
        sys.exit(__doc__)
    inv = inventory()
    for path in paths:
        tmp = tempfile.mkdtemp()
        try:
            with tarfile.open(path) as t:
                for m in t.getmembers():   # refuse absolute paths and ".." in the archive
                    if m.name.startswith("/") or ".." in m.name.split("/") or not (m.isfile() or m.isdir()):
                        sys.exit(f"{path}: unsafe entry {m.name}")
                if hasattr(tarfile, "data_filter"):
                    t.extractall(tmp, filter="data")
                else:
                    t.extractall(tmp)
            if os.path.isdir(os.path.join(tmp, "vps")):
                import_vps(os.path.join(tmp, "vps"))
            if os.path.isdir(os.path.join(tmp, "monitoring")):
                import_monitoring(os.path.join(tmp, "monitoring"), inv)
                inv = inventory()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("\nDone. Review with:  git status && git diff")
    if NOTES:
        print("\nTo look at:")
        for n in NOTES:
            print("  - " + n)


if __name__ == "__main__":
    main(sys.argv[1:])
