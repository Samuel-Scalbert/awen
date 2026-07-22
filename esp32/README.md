# ESP32 — Afficheur Awen

Le firmware vit dans son propre dépôt :
**[esp32-desk-display](https://github.com/Samuel-Scalbert/esp32-desk-display)**
(MicroPython, écran ST7789 240×320, 3 boutons, mascotte animée, écrans
Awen home / gym / jobs + horloge + Spotify).

Ce dossier ne contient plus que l'ancien squelette Arduino (`awen_display.ino`),
conservé pour référence — il n'est pas utilisé.

## Endpoint consommé

`GET http://<IP_SERVEUR>:5000/api/esp32/summary?key=<ESP32_API_KEY>`

Réponse JSON (chaînes pré-formatées pour l'affichage) :

```json
{
  "ok": true,
  "time": "18:09",
  "date": "mer 22/07",
  "gym": {
    "today": "Push",
    "done": false,
    "live": false,
    "missed": 2,
    "next": "mer 22/07 Push",
    "next_focus": "Push",
    "last": "Legs ven 17/07"
  },
  "jobs": {
    "n": 1,
    "titles": ["Data Engineer Junior - Sancare"]
  }
}
```

- `gym.today` vaut `""` les jours de repos ; `missed` compte les jours
  d'entraînement (lun/mer/ven/sam) passés depuis la dernière séance.
- `jobs` reflète la veille du jour du pipeline Claude cowork (page Jobs).
- L'état up/down de l'app n'est pas dans le JSON : c'est le succès ou
  l'échec de la requête elle-même qui le donne.
