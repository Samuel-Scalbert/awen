# Awen 🌀

> *Awen* — le concept celtique de l'inspiration.

Assistant personnel auto-hébergé pour reprendre la muscu, gérer le meal prep de prise de masse, afficher les infos sur un ESP32, se synchroniser au calendrier Samsung et (à terme) aider à la recherche d'emploi.

## Objectifs (juillet–août pour commencer)

- 🏋️ Reprendre la salle : suivi des séances et de la progression
- 🍚 Enregistrer les recettes de meal prep pour une vraie prise de masse
- 📟 Utiliser l'ESP32 + écran pour afficher infos et notifications
- 📅 Connecter le calendrier Samsung pour ne rien rater
- 💼 Automatiser une aide à la recherche de travail (plus tard)

## Architecture

Web app **Flask** hébergée sur l'ancien PC gamer (2018), qui :
- expose une API + interface web pour toutes les infos ;
- communique avec l'ESP32 (endpoint JSON léger) ;
- se met à jour à chaque commit (webhook / script de déploiement).

\`\`\`
awen/
├── app/                # Application Flask
│   ├── __init__.py     # Factory create_app()
│   ├── config.py       # Config (env vars)
│   ├── routes/         # Blueprints (main, workout, meals, calendar, esp32)
│   ├── models/         # Modèles de données
│   ├── services/       # Logique métier (calendrier, sync…)
│   ├── templates/      # Vues Jinja2
│   └── static/         # CSS / JS
├── esp32/              # Firmware / notes ESP32
├── data/               # SQLite (ignoré par git)
├── scripts/            # Déploiement, auto-update
├── docs/               # Notes de conception
├── run.py              # Point d'entrée
├── requirements.txt
└── .env.example
\`\`\`

## Démarrage rapide

\`\`\`bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # renseigner les variables
python run.py
\`\`\`

L'app tourne sur http://localhost:5000

## Endpoint ESP32

\`GET /api/esp32/summary\` — JSON compact (prochaine séance, prochain event calendrier, macros du jour) à afficher sur l'écran.

## Roadmap

- [x] Scaffold Flask + structure repo
- [ ] Modèle & pages séances de muscu
- [ ] Modèle & pages recettes / meal prep + calcul macros
- [ ] Endpoint JSON ESP32 + firmware
- [ ] Sync calendrier Samsung
- [ ] Script auto-update sur commit (webhook Git)
- [ ] Module recherche d'emploi

## Licence

MIT — voir [LICENSE](LICENSE).
# awen
