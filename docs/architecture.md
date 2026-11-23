# Architecture Awen

> Mise à jour le 23/11/2026. Le détail de chaque choix est dans l'en-tête de son module (`app/services/*.py`).

## Vue d'ensemble
- **Serveur** : ancien PC gamer (2018) sous Debian 13, l'app Flask dans un conteneur Docker (gunicorn, un worker, huit threads).
- **Clients** : le navigateur du PC et du téléphone (sur le wifi, ou partout par Tailscale en HTTPS).
- **Données** : SQLite (`data/awen.db`, monté en volume, ignoré par git), sauvegardé chaque nuit.

## Flux
1. Samuel enregistre ses séances, ses tâches et ses lettres dans l'interface web.
2. Le calendrier Samsung est lu par un flux ICS ; les rappels et la dictée sont écrits dans un agenda Google « Awen ».
3. La veille d'offres (routine Claude) est poussée depuis le PC par `scripts/sync-jobs.ps1`.
4. Le serveur interroge GitHub toutes les cinq minutes et se reconstruit quand `main` a bougé (`scripts/deploy.sh`).

## Modules
- `workout`, `coach`, `stats` : séances, progression, conseils à règles.
- `meals` : recettes, plan nutrition, liste de courses.
- `calendar` : flux ICS, rappels de séance.
- `jobs` : veille, lettres de motivation, offres rattrapées, levées de fonds et mails de prospection.
- `todos`, `dictee` : tâches, dictée depuis le téléphone.
- `jarvis` : assistant local (Ollama) qui lit la base par des outils.

L'afficheur ESP32 a été retiré le 23/11/2026 : son code est dans le tag git `esp32-v1`.
