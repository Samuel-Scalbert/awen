# Architecture Awen

## Vue d'ensemble
- **Serveur** : ancien PC gamer (2018), Linux ou Windows, héberge l'app Flask.
- **Clients** : navigateur (interface web) + ESP32 (écran de notifications).
- **Données** : SQLite local (`data/awen.db`).

## Flux
1. L'utilisateur enregistre séances / recettes via l'interface web.
2. Le calendrier Samsung est synchronisé via un flux ICS.
3. L'ESP32 interroge `/api/esp32/summary` toutes les 60s.
4. À chaque `git push`, `scripts/deploy.sh` met à jour et redémarre le service.

## Modules
- `workout` : séances et progression.
- `meals` : recettes meal prep + macros.
- `calendar` : sync ICS Samsung.
- `esp32` : API JSON compacte.
- (futur) `jobs` : aide à la recherche d'emploi automatisée.
