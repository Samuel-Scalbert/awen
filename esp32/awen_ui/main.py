"""Point d'entrée de l'afficheur Awen.

Ce fichier ne déclare aucune broche d'écran. `tft_setup.py`, dans le dépôt
esp32-desk-display, est déjà « le seul endroit où vivent les numéros de
broches » — le dupliquer ici garantirait qu'un jour les deux divergent.

    Ecran   CS 5, DC 17, RST 21, retroeclairage 22, SCK 18, MOSI 23
    Boutons gauche 26, selection 27, droite 14   (buttons.py)
    Potard  34                                   (a cabler)

À copier sur la carte, à côté de st7789_min.py, tft_setup.py et wifi.py.
Copie awen_config.example.py en awen_config.py et renseigne-le : il contient
la clé d'API et le mot de passe wifi, il ne doit jamais partir sur GitHub.
"""
from tft_setup import tft

import awen_config
from app import App

# Les numéros repris de buttons.py. On ne réutilise pas ses objets Pin :
# input.py a besoin de créer les siens pour gérer l'anti-rebond, les appuis
# longs et la répétition, dont buttons.py ne s'occupe pas.
BTN_LEFT, BTN_SELECT, BTN_RIGHT = 26, 27, 14

# Le potard DOIT être sur ADC1 (GPIO 32-39) : ADC2 cesse de fonctionner dès
# que le wifi est actif. 34 est libre sur cette carte et en entrée seule,
# donc sans tirage interne parasite. Voir input.py.
POT = 34

app = App(tft, {
    "ssid": awen_config.WIFI_SSID,
    "password": awen_config.WIFI_PASSWORD,
    "base_url": awen_config.AWEN_URL,
    "api_key": awen_config.ESP32_API_KEY,
    "pins": {"pin_a": BTN_LEFT, "pin_b": BTN_SELECT,
             "pin_c": BTN_RIGHT, "pot": POT},
})

app.run()
