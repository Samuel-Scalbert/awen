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
- [Dépannage](#dépannage)
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
| `JOB_SEARCH_DIR`             | Dossier du pipeline Claude cowork de recherche d'emploi (page Jobs) |

## Endpoint ESP32

`GET /api/esp32/summary` — JSON compact (prochaine séance, prochain event calendrier, macros du jour) à afficher sur l'écran, authentifié via `ESP32_API_KEY`.

Le firmware de l'afficheur (squelette Arduino dans [esp32/](esp32/)) vit dans son propre dépôt : [esp32-desk-display](https://github.com/Samuel-Scalbert/esp32-desk-display).

## Déploiement serveur (Docker)

Sur le serveur Debian, une fois Docker installé :

```bash
git clone https://github.com/Samuel-Scalbert/awen.git
cd awen
cp .env.example .env && nano .env      # SECRET_KEY et ESP32_API_KEY réels
mkdir -p data
docker compose up -d --build
```

L'app écoute sur le port 5000. `docker compose logs -f` pour suivre,
`docker compose up -d --build` après un `git pull` pour mettre à jour.

### Mise à jour automatique

```bash
chmod +x scripts/*.sh
./scripts/install-updater.sh
```

Un timer systemd interroge GitHub toutes les 5 minutes et ne reconstruit que
si `origin/main` a bougé.

> Si les `git fetch` échouent par intermittence avec
> `expected flush after ref listing` / `could not read Username`, c'est HTTP/2
> qui déraille entre git et GitHub. Sur le serveur :
> `git config --global http.version HTTP/1.1`. Le serveur n'expose donc rien sur Internet : pas de
webhook, pas de port ouvert sur la box.

```bash
systemctl list-timers awen-update.timer     # prochain passage
journalctl -u awen-update.service -f        # journal des déploiements
./scripts/deploy.sh                         # déployer tout de suite
```

Depuis le poste de développement, pour ne pas attendre le prochain cycle :

```powershell
ssh awen "cd awen && ./scripts/deploy.sh"
```

### Sauvegarde automatique

```bash
./scripts/install-backup.sh
```

Sauvegarde quotidienne à 4h, les **7 dernières conservées** dans
`data/backups/`. La copie passe par `sqlite3 .backup`, qui reste cohérente
même si l'app écrit au même moment — contrairement à un `cp`. Le timer est
`Persistent` : si le serveur est éteint à 4h, la sauvegarde est rattrapée au
démarrage suivant.

```bash
ls -lt data/backups/                     # les sauvegardes
./scripts/backup.sh                      # sauvegarder maintenant
# restaurer :
docker compose down
cp data/backups/awen-2026-08-19-0400.db data/awen.db
docker compose up -d
```

Points à connaître :

- **La base vit dans `./data`**, monté en volume : reconstruire l'image ne
  touche pas à l'historique d'entraînement. Pour reprendre une base existante,
  copie `awen.db` dans ce dossier avant le premier démarrage.
- **`DATABASE_URL` est imposé par compose** (`/app/data/awen.db`) et prime sur
  le `.env` — le laisser commenté dans le `.env` est le bon réflexe.
- **Servi par gunicorn**, un seul worker et plusieurs threads : SQLite supporte
  mal plusieurs processus écrivains.
- **`JOB_SEARCH_DIR`** pointe vers le dossier du pipeline Claude cowork
  (voir ci-dessous). Sans lui, la page Jobs affiche simplement qu'aucun
  dossier n'est configuré : le reste de l'app fonctionne normalement.

### Veille emploi : du PC Windows vers le serveur

Le pipeline Claude cowork tourne à 9h sur le PC Windows, mais le serveur ne
voit pas ce disque. On lui **pousse** donc les données, plutôt que de monter un
partage réseau qui casserait dès que le PC dort.

Côté serveur, une fois :

```bash
sudo mkdir -p /srv/recherche-cdi
sudo chown "$USER:$USER" /srv/recherche-cdi
echo 'JOB_SEARCH_DIR=/srv/recherche-cdi' >> ~/awen/.env
```

Côté Windows, après chaque passage du pipeline :

```powershell
.\scripts\sync-jobs.ps1
```

Le script ne copie que `Veille quotidienne/` et `Lettres de motivation/` — les
deux seuls dossiers lus par `app/services/job_watch.py`. Les CV et notes
d'entretien restent sur le PC.

Pour l'automatiser à 9h30, une fois :

```powershell
schtasks /create /tn "Awen - sync veille emploi" /sc daily /st 09:30 ^
  /tr "powershell -NoProfile -ExecutionPolicy Bypass -File \"%USERPROFILE%\awen\scripts\sync-jobs.ps1\""
```

La tâche suppose un alias SSH `awen` dans `~/.ssh/config` :

```
Host awen
    HostName 192.168.1.32
    User sscalbert
    IdentityFile ~/.ssh/id_ed25519
```

## Dépannage

**`python` ne se lance pas / erreur `No pyvenv.cfg file`**
Sur Windows, `python` peut pointer vers l'alias Microsoft Store (`AppData\Local\Microsoft\WindowsApps\python.exe`), qui ne fonctionne pas comme un vrai interpréteur. Utilise le chemin complet de ta vraie installation Python pour créer le venv :

```powershell
& "C:\chemin\vers\ta\vraie\installation\python.exe" -m venv venv
.\venv\Scripts\activate
```

**`sqlalchemy.exc.OperationalError: unable to open database file` au rechargement à chaud**
Si `DATABASE_URL` est défini dans `.env` avec un chemin **relatif** (`sqlite:///data/awen.db`), le sous-processus de rechargement à chaud (`debug=True`) de Flask échoue à le résoudre sur Windows. Laisse `DATABASE_URL` commenté dans `.env` pour utiliser le chemin absolu par défaut (calculé dans [app/config.py](app/config.py)), ou renseigne toi-même un chemin absolu.

## Roadmap

- [x] Scaffold Flask + structure repo
- [x] Séances de muscu guidées (suivi par série, progression auto, photos)
- [x] Recettes / meal prep + liste de courses en portions
- [x] Calendrier (séances + planning + événements Samsung ICS)
- [x] Module recherche d'emploi (veille quotidienne du pipeline Claude cowork)
- [x] Statistiques (tableau de bord, page par exercice, graphiques SVG)
- [x] Déploiement Docker + auto-update et sauvegardes sur le serveur maison
- [x] Coach à base de règles (RIR, stagnation, deload, pesées, tests de détente)
- [x] Endpoint JSON ESP32
- [ ] Firmware de l'afficheur ([esp32-desk-display](https://github.com/Samuel-Scalbert/esp32-desk-display))
- [ ] Assistant vocal local sur le GPU du serveur

## Licence

MIT — voir [LICENSE](LICENSE).

Photos de démonstration des exercices : [free-exercise-db](https://github.com/yuhonas/free-exercise-db) (domaine public).
