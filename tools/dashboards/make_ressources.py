import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(HERE, "..", "..", "monitoring", "grafana", "dashboards"))
sys.path.insert(0, HERE)
from dash_lib import *  # noqa: E402,F401,F403

b = Board()
b.text("**Consommation du serveur Odoo.** Processeur, mémoire, disque et réseau du serveur, puis la part "
       "de chaque composant (Odoo, PostgreSQL, Nginx et autres programmes), l'espace de la base de données "
       "(source BBi) et le volume envoyé par le serveur web. "
       "**À savoir :** tant que la source « prometheus-2 » est en erreur, les blocs processeur, mémoire, "
       "disque et réseau restent vides.", 2)

# ---------------------------------------------------------------- en ce moment
b.row("En ce moment")
b.gauge("Processeur (CPU)", CPU,
        "Part du temps où le processeur travaille. Jaune dès 70 %, rouge dès 90 %.")
b.gauge("Mémoire (RAM)", RAM,
        "Part de la mémoire vive utilisée. Jaune dès 70 %, rouge dès 90 %.")
b.gauge("Mémoire d'échange (swap)", SWAP,
        "Part du swap utilisée. Le serveur ralentit quand il s'en sert beaucoup. Jaune dès 30 %, rouge dès 70 %.",
        warn=30, bad=70)
b.gauge("Disque le plus plein", DISK_MAX,
        "Partition la plus remplie du serveur. Jaune dès 75 %, rouge dès 90 %.", warn=75, bad=90)
b.stat("Cœurs de processeur", 4, PROM, CORES,
       "Nombre de cœurs du serveur.", color="blue", nodata=None)
b.stat("Charge (1 min)", 4, PROM, LOAD1,
       "Nombre moyen de tâches en attente du processeur. Au-delà du nombre de cœurs, le serveur sature.",
       decimals=2, color="blue", nodata=None)
b.stat("Mémoire utilisée", 4, PROM, MEM_USED,
       "Mémoire vive utilisée en ce moment.", unit="bytes", decimals=1, color="blue", nodata=None)
b.stat("Mémoire totale", 4, PROM, MEM_TOTAL,
       "Mémoire vive installée sur le serveur.", unit="bytes", decimals=1, color="blue", nodata=None)
b.stat("Démarré depuis", 4, PROM, UPTIME,
       "Temps écoulé depuis le dernier redémarrage du serveur.", unit="s", decimals=0, color="blue",
       nodata=None)
b.stat("Services en échec", 4, PROM, FAILED_UNITS,
       "Services systemd arrêtés sur une erreur. Toute valeur au-dessus de 0 est rouge.",
       thresholds=ALERT, nodata=None)

# ---------------------------------------------------------------- par composant
b.row("Consommation par composant : Odoo, PostgreSQL, Nginx et autres")
for label, group in [("Odoo", "odoo"), ("PostgreSQL", "postgresql"), ("Nginx", "nginx")]:
    b.stat(f"{label} : processeur", 4, PROM, comp_cpu(group),
           f"Part du processeur du serveur utilisée par {label}. Jaune dès 50 %, rouge dès 80 %.",
           unit="percent", decimals=1, thresholds=warn_bad(50, 80), nodata=None)
    b.stat(f"{label} : mémoire", 4, PROM, comp_mem(group),
           f"Mémoire vive utilisée par tous les processus de {label}.",
           unit="bytes", decimals=1, color="blue", nodata=None)
b.ts("Processeur par composant (% du serveur)", PROM, [(PROC_CPU_TOP, "{{groupname}}")],
     "Les 8 programmes qui utilisent le plus le processeur, au cours du temps.",
     unit="percent", lo=0, decimals=1)
b.ts("Mémoire par composant", PROM, [(PROC_MEM_TOP, "{{groupname}}")],
     "Les 8 programmes qui utilisent le plus de mémoire vive, au cours du temps.",
     unit="bytes", lo=0)
b.table("Tous les composants : processeur, mémoire et nombre de processus", PROM,
        [(PROC_CPU_ALL, ""), (PROC_MEM_ALL, ""), (PROC_NUM, "")],
        {"groupname": "Composant", "Value #A": "Processeur (%)", "Value #B": "Mémoire",
         "Value #C": "Processus"},
        "Processeur (%)",
        "Chaque programme du serveur avec sa consommation actuelle.",
        w=24, h=10,
        overrides=[unit_override("Processeur (%)", "percent", 1),
                   unit_override("Mémoire", "bytes", 1),
                   unit_override("Processus", "short", 0)])

# ---------------------------------------------------------------- workers Odoo
b.row("Workers Odoo (configuration actuelle : 31 workers HTTP)")
b.stat("Processus Odoo", 4, PROM, ODOO_PROCS,
       "Tous les processus Odoo : le principal, les 31 workers HTTP, les workers des tâches planifiées "
       "et le processus temps réel.", color="blue", nodata=None)
b.stat("Workers ayant servi (5 min)", 4, LOKI, WORKERS_SERVING_5M,
       "Nombre de workers différents qui ont traité au moins une requête ces 5 dernières minutes. "
       "Proche de 31 = les workers sont presque tous sollicités.",
       thresholds=warn_bad(25, 30), nodata="0")
b.stat("Processus Odoo en calcul", 4, PROM, ODOO_BUSY,
       "Processus Odoo qui utilisent le processeur à cet instant (ceux qui attendent la base ne sont pas comptés).",
       color="blue", nodata=None)
b.stat("Mémoire moyenne par processus", 4, PROM, ODOO_MEM_AVG,
       "Mémoire vive moyenne d'un processus Odoo.", unit="bytes", decimals=1, color="blue", nodata=None)
b.stat("Odoo démarré depuis", 4, PROM, ODOO_UPTIME,
       "Temps écoulé depuis le dernier démarrage du service Odoo.", unit="s", color="blue", nodata=None)
b.sql_stat("Connexions à la base ouvertes", 4, SQL_ODOO_CONN,
           "Connexions ouvertes sur la base Odoo en ce moment (chaque worker garde ses propres connexions).",
           color="blue")
b.stat("Workers relancés (période)", 4, LOKI, odoo_count("alive"),
       "Nouveaux workers démarrés sur la période. Odoo en relance après chaque arrêt ou recyclage.",
       color="blue")
b.stat("Arrêtés : délai dépassé", 4, LOKI, odoo_count("timeout after"),
       "Workers arrêtés parce qu'une requête a dépassé le temps maximum (limit_time_real). Rouge dès 1.",
       thresholds=ALERT)
b.stat("Arrêtés : limite mémoire", 4, LOKI, odoo_count("memory limit"),
       "Workers recyclés parce qu'ils ont dépassé la mémoire autorisée (limit_memory_soft). Jaune dès 1.",
       thresholds=WARN)
b.stat("Arrêtés : limite processeur", 4, LOKI, odoo_count("CPU time limit"),
       "Workers arrêtés parce qu'une requête a utilisé trop de temps processeur (limit_time_cpu). Jaune dès 1.",
       thresholds=WARN)
b.stat("Recyclés : max de requêtes", 4, LOKI, odoo_count("max request"),
       "Recyclage normal d'un worker après un nombre fixe de requêtes (limit_request).",
       color="blue")
b.stat("Fichiers ouverts (pire processus)", 4, PROM, ODOO_FD,
       "Part de la limite de fichiers ouverts atteinte par le processus Odoo le plus chargé. Jaune dès 70 %, rouge dès 90 %.",
       unit="percent", decimals=1, thresholds=warn_bad(70, 90), nodata=None)
b.ts("Processus Odoo : total et en calcul", PROM,
     [(ODOO_PROCS, "Total"), (ODOO_BUSY, "En calcul")],
     "Nombre de processus Odoo au cours du temps, et combien utilisent le processeur.",
     lo=0, decimals=0,
     overrides=[color_override("Total", "blue"), color_override("En calcul", "orange")])
b.ts("Workers ayant servi des requêtes, par minute", LOKI,
     [(WORKERS_SERVING_TS, "Workers sollicités")],
     "Nombre de workers différents qui ont traité des requêtes chaque minute. "
     "S'il touche souvent 31, Odoo manque de workers aux heures de pointe.",
     lo=0, decimals=0, overrides=[color_override("Workers sollicités", "green")])
b.table("Requêtes par worker (période)", LOKI,
        [(REQ_BY_PID, ""), (AVG_BY_PID, "")],
        {"pid": "Worker (PID)", "Value #A": "Requêtes", "Value #B": "Temps moyen (s)"},
        "Requêtes",
        "Répartition des requêtes entre les workers, avec leur temps de réponse moyen.",
        overrides=[unit_override("Requêtes", "short", 0),
                   unit_override("Temps moyen (s)", "s", 3)])
b.logs("Événements des workers (démarrages, arrêts, limites)", LOKI, WORKER_EVENTS,
       "Messages du gestionnaire de workers Odoo, le plus récent en haut.", w=12, h=8)

# ---------------------------------------------------------------- processeur et mémoire
b.row("Processeur et mémoire au cours du temps")
b.ts("Processeur par usage (%)", PROM, [(CPU_BY_MODE, "{{mode}}")],
     "Applications = Odoo, PostgreSQL… ; Système = noyau ; Attente du disque = le processeur attend le disque.",
     unit="percent", lo=0, decimals=0,
     overrides=[rename_override("user", "Applications"), rename_override("system", "Système"),
                rename_override("iowait", "Attente du disque")])
b.ts("Mémoire utilisée et totale", PROM, [(MEM_USED, "Utilisée"), (MEM_TOTAL, "Totale")],
     "Mémoire vive utilisée par rapport à la mémoire installée.",
     unit="bytes", lo=0,
     overrides=[color_override("Utilisée", "orange"), color_override("Totale", "green")])
b.ts("Charge du processeur", PROM,
     [(LOAD1, "1 min"), (LOAD5, "5 min"), (LOAD15, "15 min"), (CORES, "Nombre de cœurs")],
     "Tâches en attente du processeur. Tant que les courbes restent sous « Nombre de cœurs », tout va bien.",
     lo=0, decimals=1, overrides=[color_override("Nombre de cœurs", "red")])
b.ts("Mémoire d'échange utilisée (%)", PROM, [(SWAP, "Swap")],
     "Part du swap utilisée au cours du temps.", unit="percent", lo=0, decimals=0)

# ---------------------------------------------------------------- disque et réseau
b.row("Disque et réseau")
b.table("Espace utilisé par partition", PROM, [(DISK_BY, "")],
        {"mountpoint": "Partition", "Value": "Utilisé (%)", "Value #A": "Utilisé (%)"},
        "Utilisé (%)", "Espace utilisé sur chaque partition.", w=8, unit="percent")
b.ts("Lectures et écritures disque", PROM, [(DISK_READ, "Lecture"), (DISK_WRITE, "Écriture")],
     "Volume lu et écrit sur les disques, par seconde.", w=8, unit="Bps", lo=0)
b.ts("Trafic réseau", PROM, [(NET_IN, "Reçu"), (NET_OUT, "Envoyé")],
     "Données reçues et envoyées par le serveur, par seconde.", w=8, unit="Bps", lo=0)

# ---------------------------------------------------------------- base de données
b.row("Base de données : espace et mémoire")
b.sql_stat("Taille de la base", 6, SQL_DB_SIZE,
           "Espace disque occupé par la base Odoo.", unit="bytes", decimals=1, color="blue", nodata=None)
b.sql_stat("Connexions utilisées", 6, SQL_CONN_PCT,
           "Part des connexions possibles déjà ouvertes, maintenant. Jaune dès 70 %, rouge dès 90 %.",
           unit="percent", decimals=1, thresholds=warn_bad(70, 90))
b.sql_stat("Lectures servies par le cache", 6, SQL_CACHE,
           "Part des lectures servies depuis la mémoire plutôt que le disque. Vert au-dessus de 99 %.",
           unit="percent", decimals=1, thresholds=CACHE_TH, nodata=None)
b.sql_stat("Fichiers temporaires écrits", 6, SQL_TEMP,
           "Données écrites sur disque faute de mémoire pour trier ou regrouper, depuis le démarrage de PostgreSQL.",
           unit="bytes", decimals=1, color="blue", nodata=None)
b.sql_table("Plus grosses tables", SQL_BIG_TABLES,
            "Les 10 tables qui occupent le plus de place.", w=12, h=8,
            overrides=[unit_override("Taille", "bytes", 1)])
b.sql_table("Connexions par état", SQL_BY_STATE,
            "Connexions ouvertes, par état (active = en train de travailler, idle = en attente).",
            w=12, h=8)

# ---------------------------------------------------------------- serveur web
b.row("Serveur web : volume envoyé")
b.stat("Données envoyées (période)", 6, LOKI, BYTES_SENT,
       "Volume de données envoyé par le serveur web sur la période.",
       unit="decbytes", decimals=1, color="blue")
b.ts("Données envoyées par minute", LOKI, [(BYTES_PER_MIN, "envoyé")],
     "Volume envoyé par le serveur web, minute par minute.", w=18, unit="decbytes", lo=0)

out = b.save(os.path.join(OUT_DIR, "supervision-odoo-3-consommation-serveur.json"),
             "Supervision Odoo · Consommation du serveur", "supervision-odoo-ressources",
             "Processeur, mémoire, disque, réseau, base de données et volume web du serveur Odoo.",
             [SUITE_TAG, "serveur", "ressources"], "now-6h", links=SUITE_LINKS)
print("wrote", out, "| panels incl. nested:", b.count())
