import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(HERE, "..", "..", "monitoring", "grafana", "dashboards"))
sys.path.insert(0, HERE)
from dash_lib import *  # noqa: E402,F401,F403

b = Board()
b.text("**Activité et performances d'Odoo.** Trafic, temps de réponse, base de données et utilisateurs. "
       "Vert = normal, jaune = à surveiller, rouge = à traiter. Les pages « Journaux et erreurs » et "
       "« Consommation du serveur » s'ouvrent avec le lien en haut de page.", 2)

# ---------------------------------------------------------------- en un coup d'œil
b.row("En un coup d'œil")
b.stat("Requêtes par minute", 4, LOKI, RPM,
       "Requêtes traitées par Odoo pendant la dernière minute.", color="blue")
b.stat("Temps de réponse médian", 4, LOKI, quant(0.5, "total_time"),
       "La moitié des requêtes sont plus rapides que cette valeur. Jaune au-delà de 1 s, rouge au-delà de 2 s.",
       unit="s", decimals=2, thresholds=warn_bad(1, 2), nodata=None)
b.stat("Temps de réponse lent (95 %)", 4, LOKI, quant(0.95, "total_time"),
       "95 requêtes sur 100 sont plus rapides que cette valeur. Jaune au-delà de 1 s, rouge au-delà de 2 s.",
       unit="s", decimals=2, thresholds=warn_bad(1, 2), nodata=None)
b.stat("Requêtes en erreur", 4, LOKI, ODOO_5XX_RATE,
       "Part des requêtes Odoo terminées par une erreur serveur (5xx). Jaune au-delà de 1 %, rouge au-delà de 5 %.",
       unit="percent", decimals=2, thresholds=warn_bad(1, 5))
b.sql_stat("Utilisateurs connectés (période)", 4, SQL_USERS_CONNECTED,
           "Utilisateurs dont la dernière connexion est dans la période affichée.", color="blue")
b.sql_stat("Connexions à la base utilisées", 4, SQL_CONN_PCT,
           "Part des connexions possibles à la base déjà ouvertes, maintenant. Jaune dès 70 %, rouge dès 90 %.",
           unit="percent", decimals=1, thresholds=warn_bad(70, 90))

# ---------------------------------------------------------------- Odoo
b.row("Odoo : temps de réponse et trafic")
b.ts("Temps de réponse : typique et lent", LOKI,
     [(quant(0.5, "total_time", "5m"), "typique (médiane)"),
      (quant(0.95, "total_time", "5m"), "lent (95e centile)")],
     "Le trait vert est ce que vit la majorité des utilisateurs. L'orange est le cas lent.",
     unit="s", lo=0,
     overrides=[color_override("typique (médiane)", "green"),
                color_override("lent (95e centile)", "orange")])
b.ts("Requêtes par minute, selon le résultat", LOKI,
     [(expr, name) for name, expr in CLASS_RATE],
     "Chaque requête est un succès, une redirection ou une erreur. Le rouge doit rester proche de zéro.",
     lo=0, decimals=0,
     overrides=[color_override(name, CLASS_COLORS[name]) for name, _ in CLASSES])
b.table("Parties de l'application les plus utilisées", LOKI,
        [(SECTION_COUNT, ""), (SECTION_AVG["sql_count"], ""),
         (SECTION_AVG["sql_time"], ""), (SECTION_AVG["total_time"], "")],
        {"section": "Section", "Value #A": "Requêtes", "Value #B": "Requêtes SQL (moy.)",
         "Value #C": "Temps SQL moy. (s)", "Value #D": "Temps de réponse moy. (s)"},
        "Requêtes",
        "Quelles parties de l'application reçoivent le plus de trafic, et leur poids sur la base.",
        w=24, h=8,
        overrides=[unit_override("Requêtes", "short", 0),
                   unit_override("Requêtes SQL (moy.)", "short", 1),
                   unit_override("Temps SQL moy. (s)", "s", 3),
                   unit_override("Temps de réponse moy. (s)", "s", 2)])

# ---------------------------------------------------------------- base de données
b.row("Base de données : charge et requêtes")
b.stat("Requêtes SQL par page (moyenne)", 4, LOKI, avg("sql_count"),
       "Nombre moyen de requêtes SQL exécutées pour afficher une page Odoo.",
       decimals=1, color="blue", nodata=None)
b.stat("Temps SQL par page (moyenne)", 4, LOKI, avg("sql_time"),
       "Temps moyen passé à attendre la base pour une page Odoo.",
       unit="s", decimals=3, color="blue", nodata=None)
b.sql_stat("Requêtes en cours", 4, SQL_ACTIVE,
           "Requêtes que la base exécute en ce moment.", color="blue")
b.sql_stat("Requêtes bloquées", 4, SQL_BLOCKED,
           "Requêtes qui attendent qu'une autre libère un verrou. Jaune dès 1, rouge dès 5.",
           thresholds=warn_bad(1, 5))
b.sql_stat("Requête la plus longue", 4, SQL_LONGEST,
           "Durée de la requête en cours la plus ancienne. Jaune au-delà de 30 s, rouge au-delà de 2 min.",
           unit="s", decimals=1, thresholds=warn_bad(30, 120))
b.sql_stat("Lectures servies par le cache", 4, SQL_CACHE,
           "Part des lectures servies depuis la mémoire plutôt que le disque. Vert au-dessus de 99 %.",
           unit="percent", decimals=1, thresholds=CACHE_TH, nodata=None)
b.ts("Requêtes SQL par page", LOKI,
     [(avg("sql_count", "5m"), "moyenne"), (quant(0.95, "sql_count", "5m"), "95 %")],
     "Un saut brusque signale souvent une page lente ou une nouveauté.",
     lo=0, decimals=0,
     overrides=[color_override("moyenne", "blue"), color_override("95 %", "orange")])
b.ts("Temps passé dans la base par page (secondes)", LOKI,
     [(avg("sql_time", "5m"), "moyenne")],
     "Temps moyen passé à attendre la base de données, par page.",
     unit="s", lo=0)
b.sql_table("Connexions par état", SQL_BY_STATE,
            "Connexions ouvertes, par état (active = en train de travailler, idle = en attente).",
            w=8, h=8)
b.sql_table("Requêtes en cours les plus longues", SQL_LONG_QUERIES,
            "Requêtes encore en cours, de la plus ancienne à la plus récente.",
            w=16, h=8)

# ---------------------------------------------------------------- Nginx
b.row("Serveur web (Nginx)")
b.stat("Requêtes reçues (période)", 6, LOKI, NGINX_TOTAL,
       "Toutes les requêtes reçues par le serveur web sur la période.", color="blue")
b.stat("Requêtes refusées 4xx (période)", 6, LOKI, CLIENT_4XX,
       "Requêtes refusées ou introuvables (403, 404…). Jaune dès qu'il y en a une.",
       thresholds=WARN)
b.stat("Erreurs serveur 5xx (période)", 6, LOKI, SERVER_5XX,
       "Erreurs côté serveur sur la période. Toute valeur au-dessus de 0 est rouge.",
       thresholds=ALERT)
b.stat("Données envoyées (période)", 6, LOKI, BYTES_SENT,
       "Volume de données envoyé par le serveur web sur la période.",
       unit="decbytes", decimals=1, color="blue")
b.ts("Requêtes par minute, par code HTTP", LOKI,
     [(f'sum by (status) (count_over_time({NGINX} [1m]))', "{{status}}")],
     "Requêtes reçues par le serveur web, par code de réponse.", lo=0)
b.table("Pages les plus demandées (hors fichiers statiques)", LOKI,
        [(TOP_PAGES, "")],
        {"path": "Chemin", "Value #A": "Requêtes"},
        "Requêtes",
        "Les 10 chemins les plus demandés au serveur web sur la période.",
        overrides=[unit_override("Requêtes", "short", 0)])

# ---------------------------------------------------------------- utilisateurs
b.row("Utilisateurs : qui fait quoi")
b.sql_stat("Personnes ayant agi (période)", 8, SQL_ACTORS,
           "Personnes différentes qui ont écrit dans une fiche sur la période.", color="blue")
b.sql_stat("Messages et notes (période)", 8, SQL_MESSAGES,
           "Messages et notes écrits par les utilisateurs sur la période.", color="blue")
b.sql_stat("Valeurs modifiées (période)", 8, SQL_CHANGES,
           "Modifications de champs suivis (statut, montant, étape…) sur la période.", color="blue")
b.sql_ts("Activité par heure", SQL_ACTIVITY_TS,
         "Messages et notes écrits par les utilisateurs, heure par heure.")
b.sql_table("Par utilisateur : dernière connexion et activité", SQL_PER_USER,
            "Une ligne par utilisateur actif : dernière connexion, nombre d'actions et dernière action sur la période.")
b.sql_table("Derniers messages et notes", SQL_RECENT_MSG,
            "Qui a écrit quoi, sur quelle fiche, et le début du message (200 dernières lignes de la période).",
            w=24, h=10)
b.sql_table("Modifications de champs suivis", SQL_RECENT_CHANGES,
            "Qui a changé quelle valeur, de quoi à quoi, sur quelle fiche (200 dernières lignes de la période).",
            w=24, h=10)

out = b.save(os.path.join(OUT_DIR, "supervision-odoo-1-activite-performances.json"),
             "Supervision Odoo · Activité et performances", "supervision-odoo-activite",
             "Trafic, temps de réponse, base de données et activité des utilisateurs Odoo.",
             [SUITE_TAG, "odoo"], "now-6h", links=SUITE_LINKS)
print("wrote", out, "| panels incl. nested:", b.count())
