import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(HERE, "..", "..", "monitoring", "grafana", "dashboards"))
sys.path.insert(0, HERE)
from dash_lib import *  # noqa: E402,F401,F403

SERVICES = [("Odoo", "odoo"), ("PostgreSQL", "postgresql"), ("Nginx", "nginx"),
            ("Système", "systemd-journal")]
VARIABLES = [
    {"type": "custom", "name": "service", "label": "Service",
     "query": ",".join(f"{t} : {v}" for t, v in SERVICES),
     "current": {"selected": True, "text": "Odoo", "value": "odoo"},
     "options": [{"selected": v == "odoo", "text": t, "value": v} for t, v in SERVICES],
     "multi": False, "includeAll": False, "hide": 0},
    {"type": "textbox", "name": "recherche", "label": "Rechercher", "query": "",
     "current": {"selected": False, "text": "", "value": ""},
     "options": [{"selected": True, "text": "", "value": ""}], "hide": 0},
]
# Filtre texte appliqué aux journaux détaillés (vide = tout afficher)
F = ' |~ "(?i)$recherche"'

b = Board()
b.text("**Journaux et erreurs.** Les compteurs du haut couvrent la période choisie : un 0 est la situation "
       "normale. Pour lire un journal, choisissez le **Service** et tapez un mot dans **Rechercher** "
       "(nom de module, code d'erreur, référence…) : les listes se filtrent aussitôt.", 2)

# ---------------------------------------------------------------- résumé
b.row("Résumé des erreurs")
b.stat("Erreurs Odoo", 4, LOKI, ERR_ODOO_TOTAL,
       "Erreurs ERROR ou CRITICAL d'Odoo sur la période. Toute valeur au-dessus de 0 est rouge.",
       thresholds=ALERT)
b.stat("Erreurs PostgreSQL", 4, LOKI, ERR_PG_TOTAL,
       "Erreurs ERROR, FATAL ou PANIC de la base sur la période. Toute valeur au-dessus de 0 est rouge.",
       thresholds=ALERT)
b.stat("Erreurs web 5xx", 4, LOKI, SERVER_5XX,
       "Erreurs renvoyées aux visiteurs par le serveur web sur la période.",
       thresholds=ALERT)
b.stat("Requêtes refusées 4xx", 4, LOKI, CLIENT_4XX,
       "Pages introuvables ou accès refusés (403, 404…) sur la période. Jaune dès qu'il y en a une.",
       thresholds=WARN)
b.stat("Erreurs système", 4, LOKI, f'sum(count_over_time({JOURNAL_ERR} [$__range]))',
       "Erreurs des services et du noyau (journal systemd) sur la période.",
       thresholds=ALERT)
b.stat("Avertissements Odoo", 4, LOKI, f'sum(count_over_time({ODOO_WARN} [$__range]))',
       "Avertissements Odoo sur la période. Information seulement : souvent sans gravité.",
       color="blue")

# ---------------------------------------------------------------- contrôle de la collecte
b.row("Collecte des journaux (contrôle)")
for title, expr in [("Lignes Odoo reçues", 'sum(count_over_time({job="odoo"} [$__range]))'),
                    ("Lignes PostgreSQL reçues", PG_LINES_TOTAL),
                    ("Lignes Nginx reçues", f'sum(count_over_time({NGINX_RAW} [$__range]))'),
                    ("Lignes système reçues", 'sum(count_over_time({job="systemd-journal"} [$__range]))')]:
    b.stat(title, 6, LOKI, expr,
           "Contrôle du transfert. Rouge = aucune ligne reçue sur la période : vérifier Alloy sur le serveur.",
           thresholds=CHECK)

# ---------------------------------------------------------------- tendance
b.row("Tendance")
b.ts("Erreurs par minute, par source", LOKI,
     [(f'sum(count_over_time({ODOO_ERR} [1m]))', "Odoo"),
      (f'sum(count_over_time({PG_ERR} [1m]))', "PostgreSQL"),
      (f'sum(count_over_time({NGINX_5XX} [1m]))', "Web 5xx"),
      (f'sum(count_over_time({JOURNAL_ERR} [1m]))', "Système")],
     "Erreurs de chaque source au cours du temps. Un pic correspond à un incident.",
     lo=0, decimals=0,
     overrides=[color_override("Odoo", "orange"), color_override("PostgreSQL", "red"),
                color_override("Web 5xx", "purple"), color_override("Système", "blue")])
b.ts("Lignes de journal par minute, par service", LOKI,
     [(LINES_BY_JOB, "{{job}}")],
     "Volume de journaux reçus. Une courbe qui tombe à zéro signale un service ou un transfert arrêté.",
     lo=0, decimals=0,
     overrides=[rename_override(v, t) for t, v in SERVICES])

# ---------------------------------------------------------------- erreurs détaillées
b.row("Erreurs détaillées (filtrées par « Rechercher »)")
b.logs("Erreurs Odoo", LOKI, ODOO_ERR + F,
       "Chaque erreur Odoo (ERROR ou CRITICAL), la plus récente en haut.")
b.logs("Erreurs PostgreSQL", LOKI, PG_ERR + F,
       "Chaque erreur PostgreSQL (ERROR, FATAL ou PANIC), la plus récente en haut.")
b.logs("Erreurs système", LOKI, JOURNAL_ERR + F,
       "Erreurs des services et du noyau, la plus récente en haut.")
b.logs("Journal d'erreurs Nginx", LOKI, NGINX_ERR_LOG + F,
       "Erreurs et avertissements écrits par le serveur web.")

# ---------------------------------------------------------------- services système
b.row("Services système en erreur")
b.table("Services en erreur (période)", LOKI,
        [(SYS_TABLE, "")],
        {"unit": "Service", "Value #A": "Erreurs"},
        "Erreurs",
        "Services qui ont produit des erreurs sur la période affichée.")
b.ts("Erreurs système par minute (5 services les plus touchés)", LOKI,
     [(SYS_TOP5, "{{unit}}")],
     "Erreurs par minute pour les services les plus touchés.", lo=0, decimals=0)

# ---------------------------------------------------------------- explorateur
b.row("Explorer un journal (choisir « Service » et « Rechercher » en haut)")
b.logs("Journal du service choisi", LOKI, '{job="$service"}' + F,
       "Toutes les lignes du service choisi, filtrées par le texte recherché.", w=24, h=16)

# ---------------------------------------------------------------- avertissements (repliés)
b.begin_collapsed("Avertissements Odoo (cliquer pour afficher)")
b.logs("Avertissements Odoo", LOKI, ODOO_WARN + F,
       "Avertissements Odoo. Beaucoup viennent du démarrage des modules et se répètent "
       "pour chaque processus : à lire si une nouveauté apparaît.", w=24, h=14)
b.end_collapsed()

out = b.save(os.path.join(OUT_DIR, "supervision-odoo-2-journaux-erreurs.json"),
             "Supervision Odoo · Journaux et erreurs", "supervision-odoo-journaux",
             "Erreurs Odoo, PostgreSQL, Nginx et système, contrôle de la collecte et recherche dans les journaux.",
             [SUITE_TAG, "odoo", "journaux"], "now-6h", variables=VARIABLES, links=SUITE_LINKS)
print("wrote", out, "| panels incl. nested:", b.count())
