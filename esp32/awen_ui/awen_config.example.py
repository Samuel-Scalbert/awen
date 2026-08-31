"""Copie ce fichier en awen_config.py et renseigne-le.

Le wifi n'est PAS ici : il vient de wifi_config.py, déjà sur la carte et déjà
utilisé par wifi.py et spotify_screen.py. Dupliquer un mot de passe, c'est se
garantir qu'un jour les deux copies divergeront — ou qu'une des deux fuitera.

awen_config.py contient une clé d'API : il est dans le .gitignore, ne le
versionne jamais.
"""

# Sans slash final. Sur le réseau local ; via Tailscale, mets l'IP tailnet.
AWEN_URL = "http://192.168.1.32:5000"

# Doit correspondre exactement à ESP32_API_KEY du .env du serveur.
ESP32_API_KEY = "change-me"
