# Awen 🌀

> *Awen* — le concept celtique de l'inspiration.

Assistant personnel auto-hébergé pour reprendre la muscu, gérer le meal prep de prise de masse, afficher des infos sur un écran ESP32, se synchroniser au calendrier Samsung et, à terme, aider à la recherche d'emploi.

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.x-black)

## Sommaire

- [Objectifs](#objectifs-juillet–août-pour-commencer)
- [Architecture](#architecture)
- [Structure du projet](#structure-du-projet)
- [Prérequis](#prérequis)
- [Démarrage rapide](#démarrage-rapide)
- [Configuration](#configuration)
- [Endpoint ESP32](#endpoint-esp32)
- [Roadmap](#roadmap)
- [Licence](#licence)

## Objectifs (juillet–août pour commencer)

- 🏋️ Reprendre la salle : suivi des séances et de la progression
- 🍚 Enregistrer les recettes de meal prep pour une vraie prise de masse
- 📟 Utiliser l'ESP32 + écran pour afficher infos et notifications
- 📅 Connecter le calendrier Samsung pour ne rien rater
- 💼 Automatiser une aide à la recherche de travail (plus tard)

## Architecture

Web app **Flask** hébergée sur l'ancien PC gamer (2018), qui :

- expose une API + interface web pour toutes les infos ;
- communique avec l'ESP32 via un endpoint JSON léger ;
- se met à jour à chaque commit (webhook / script de déploiement).

## Structure du projet

```
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
```

## Prérequis

- Python 3.10+
- pip

## Démarrage rapide

```bash
git clone https://github.com/Samuel-Scalbert/awen.git
cd awen

python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env            # renseigner les variables

python run.py
```

L'app tourne sur [http://localhost:5000](http://localhost:5000).

## Configuration

Variables définies dans `.env` (voir [.env.example](.env.example)) :

| Variable                    | Description                                  |
| ---------------------------- | --------------------------------------------- |
| `FLASK_ENV`                 | Environnement Flask (`development` / `production`) |
| `SECRET_KEY`                | Clé secrète Flask                            |
| `DATABASE_URL`               | URL de connexion SQLite                      |
| `SAMSUNG_CALENDAR_ICS_URL`   | URL d'export ICS du calendrier Samsung        |
| `ESP32_API_KEY`              | Clé partagée avec l'ESP32                    |

## Endpoint ESP32

`GET /api/esp32/summary` — JSON compact (prochaine séance, prochain event calendrier, macros du jour) à afficher sur l'écran, authentifié via `ESP32_API_KEY`.

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
