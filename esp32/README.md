# ESP32 — Afficheur Awen

L'ESP32 interroge périodiquement l'API du serveur Awer (PC gamer) et affiche
le résumé sur un écran (OLED SSD1306 / TFT).

## Endpoint

`GET http://<IP_SERVEUR>:5000/api/esp32/summary?key=<ESP32_API_KEY>`

Réponse JSON :
```json
{
  "time": "...",
  "last_workout": "Pecs/Triceps",
  "next_event": {"title": "...", "start": "..."},
  "favorite_recipes": 3
}
```

Voir `awen_display.ino` pour un squelette Arduino.
