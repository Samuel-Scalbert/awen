# ESP32 : l'afficheur Awen

Un écran ST7789 240×320 posé sur le bureau, trois boutons, une molette. Trois
pages : **Accueil**, **Spotify**, **Calendrier**.

| Ici | Ce que c'est |
| --- | --- |
| [`awen_ui/`](awen_ui/) | le firmware MicroPython, et son [README](awen_ui/README.md) : câblage, boutons, veille |
| [`simulateur.py`](simulateur.py) | fait tourner ce firmware sur le PC, rend les pages et vérifie le redessin |
| `mockups/` | maquettes Lopaka et rendus du simulateur (non versionnés) |

Le pilote de l'écran et le wifi (`st7789_min.py`, `tft_setup.py`, `wifi.py`,
`wifi_config.py`) viennent d'un autre dépôt,
[esp32-desk-display](https://github.com/Samuel-Scalbert/esp32-desk-display),
et doivent déjà être sur la carte.

## Mettre une modification sur l'écran

Deux machines, deux gestes. **Le PC flashe, le serveur sert.**

| Ce qui a changé | Où | Comment |
| --- | --- | --- |
| le serveur (`app/`) | n'importe où | `git push` : le serveur se met à jour seul dans les cinq minutes |
| le firmware (`esp32/awen_ui/`) | le PC, carte branchée en USB | `.\upload.ps1` depuis `esp32\awen_ui` |

Si les deux ont changé, **le serveur d'abord** : un firmware qui interroge
une route que le serveur n'a pas encore affiche `HORS LIGNE`.

```powershell
python esp32\simulateur.py          # voir les pages et vérifier, sans carte
cd esp32\awen_ui
.\upload.ps1 -Console               # envoie, redémarre, montre ce que dit la carte
```

`Ctrl-]` quitte la console. La carte y écrit sa mémoire libre au démarrage,
et toute erreur de la boucle.

## Ce que le firmware demande au serveur

`GET http://<IP_SERVEUR>:5000/api/esp32/pages?key=<ESP32_API_KEY>`

```json
{
  "ok": true,
  "min": 581, "sec": 12,
  "jour": {"long": "Mardi 13 octobre", "semaine": 42},
  "meteo": {"ok": true, "now_c": 18, "min_c": 12, "max_c": 19,
            "rain_pct": 15, "court": "COUVERT"},
  "agenda": {
    "ok": true, "n": 4, "dans": "DANS 1 H 19",
    "jour": [["09:00", "Revue des offres", 0],
             ["11:00", "Entretien visio", 1]],
    "jours": [{"t": "AUJOURD'HUI", "d": "MAR 13",
               "ev": [["11:00", "Entretien visio", 1]]}],
    "semaine": [["L", 12, 0], ["M", 13, 1]],
    "auj": 1, "mois": "Octobre", "annee": 2026
  },
  "spotify": {"device": ""}
}
```

- `min` et `sec` : l'heure du serveur, en minutes depuis minuit. La carte
  n'a pas d'horloge ; elle fait avancer la minute elle-même entre deux appels.
- `agenda` vient du flux ICS d'Awen (`SAMSUNG_CALENDAR_ICS_URL`). Une ligne
  vaut `[heure, titre, état]` : heure vide pour une journée entière, état 0
  passé, 1 mis en avant, 2 à venir. `jour` sert l'accueil, `jours` le
  calendrier.
- `spotify` se réduit à `{"device": ""}` quand rien ne joue.
- L'état du serveur n'est pas dans le JSON : c'est le succès ou l'échec de la
  requête qui le donne, et la carte affiche alors `HORS LIGNE`.

Les autres routes : `GET /cover` (la pochette, en pixels bruts) et
`POST /spotify` (lecture, pause, piste, volume). `GET /summary` servait les
sept écrans d'avant ; il reste en place tant qu'une carte peut encore
l'appeler.
