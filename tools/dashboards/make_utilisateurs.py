import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(HERE, "..", "..", "monitoring", "grafana", "dashboards"))
sys.path.insert(0, HERE)
from dash_lib import *  # noqa: E402,F401,F403

b = Board()
b.text("**Activité des utilisateurs Odoo.** Qui s'est connecté, qui a écrit dans les fiches "
       "(messages et notes), et quelles valeurs ont été modifiées. Choisissez une période de 24 h ou de "
       "7 jours en haut à droite. **Limite :** les messages affichés à l'écran (erreurs, refus d'accès) "
       "ne sont pas enregistrés dans la base : cette page ne peut pas les montrer.", 3)

# ---------------------------------------------------------------- en un coup d'œil
b.row("En un coup d'œil")
b.sql_stat("Utilisateurs connectés (période)", 6,
           """SELECT COUNT(*) FROM res_users u
WHERE u.active AND $__timeFilter(u.login_date)""",
           "Utilisateurs dont la dernière connexion est dans la période affichée.", color="blue")
b.sql_stat("Personnes ayant agi (période)", 6,
           """SELECT COUNT(DISTINCT m.author_id) FROM mail_message m
WHERE m.author_id IS NOT NULL AND $__timeFilter(m.date)""",
           "Nombre de personnes différentes qui ont écrit dans une fiche sur la période.", color="blue")
b.sql_stat("Messages et notes (période)", 6,
           """SELECT COUNT(*) FROM mail_message m
WHERE m.author_id IS NOT NULL AND $__timeFilter(m.date)""",
           "Messages et notes écrits par les utilisateurs sur la période.", color="blue")
b.sql_stat("Valeurs modifiées (période)", 6,
           """SELECT COUNT(*) FROM mail_tracking_value tv
JOIN mail_message m ON m.id = tv.mail_message_id
WHERE $__timeFilter(m.date)""",
           "Modifications de champs suivis (statut, montant, étape…) sur la période.", color="blue")

# ---------------------------------------------------------------- qui fait quoi
b.row("Qui fait quoi")
b.sql_ts("Activité par heure",
         """SELECT $__timeGroup(m.date, '1h') AS time, COUNT(*) AS "Actions"
FROM mail_message m
WHERE m.author_id IS NOT NULL AND $__timeFilter(m.date)
GROUP BY 1
ORDER BY 1""",
         "Nombre de messages et de notes écrits par les utilisateurs, heure par heure.")
b.sql_table("Par utilisateur : dernière connexion et activité",
            """SELECT p.name AS "Utilisateur",
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
LIMIT 100""",
            "Une ligne par utilisateur actif : dernière connexion, nombre d'actions et dernière action sur la période.")

# ---------------------------------------------------------------- dernières actions
b.row("Dernières actions")
b.sql_table("Derniers messages et notes",
            """SELECT m.date AS "Date",
       p.name AS "Utilisateur",
       m.model AS "Type de fiche",
       m.res_id AS "N° fiche",
       LEFT(regexp_replace(COALESCE(m.body, ''), '<[^>]+>', ' ', 'g'), 150) AS "Message"
FROM mail_message m
JOIN res_partner p ON p.id = m.author_id
WHERE $__timeFilter(m.date)
ORDER BY m.date DESC
LIMIT 200""",
            "Qui a écrit quoi, sur quelle fiche, et le début du message (200 dernières lignes de la période).",
            w=24, h=10)
b.sql_table("Modifications de champs suivis",
            """SELECT m.date AS "Date",
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
LIMIT 200""",
            "Qui a changé quelle valeur, de quoi à quoi, sur quelle fiche (200 dernières lignes de la période).",
            w=24, h=10)

out = b.save(os.path.join(OUT_DIR, "supervision-odoo-4-activite-utilisateurs.json"),
             "Activité des utilisateurs Odoo", "odoo-users-activity",
             "Qui se connecte, qui écrit dans les fiches, et quelles valeurs changent. Source : base Odoo (BBi).",
             ["odoo", "utilisateurs", "activite"], "now-24h")
print("wrote", out, "| panels incl. nested:", b.count())
