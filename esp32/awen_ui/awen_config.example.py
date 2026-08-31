"""Copie ce fichier en awen_config.py et renseigne-le.

awen_config.py contient un mot de passe wifi et une clé d'API : il est dans
le .gitignore et ne doit jamais être versionné.
"""

WIFI_SSID = "TON_WIFI"
WIFI_PASSWORD = "TON_MOT_DE_PASSE"

# Sans slash final. Sur le réseau local ; via Tailscale, mets l'IP tailnet.
AWEN_URL = "http://192.168.1.32:5000"

# Doit correspondre exactement à ESP32_API_KEY du .env du serveur.
ESP32_API_KEY = "change-me"
