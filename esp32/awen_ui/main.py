"""Point d'entrée de l'afficheur Awen.

Ce fichier ne déclare aucune broche d'écran. `tft_setup.py`, dans le dépôt
esp32-desk-display, est déjà « le seul endroit où vivent les numéros de
broches » — le dupliquer ici garantirait qu'un jour les deux divergent.

    Ecran   CS 5, DC 17, RST 21, retroeclairage 22, SCK 18, MOSI 23
    Boutons gauche 26, selection 27, droite 14   (buttons.py)
    Encodeur CLK 4 (D4), DT 19 (D19), poussoir 16 (marque RX2), commun GND
    LED      32 R, 33 V, 13 B   (+ commun, + 3 resistances 220R)
    DHT11    25 DATA (+ 10k vers VCC)

À copier sur la carte, à côté de st7789_min.py, tft_setup.py et wifi.py.
Copie awen_config.example.py en awen_config.py et renseigne-le : il contient
la clé d'API et le mot de passe wifi, il ne doit jamais partir sur GitHub.
"""
from tft_setup import tft

# Le wifi vient de wifi_config.py, deja sur la carte et deja utilise par
# wifi.py et spotify_screen.py. On ne redemande pas un mot de passe qui existe
# a un metre de la : un secret duplique est un secret qui finit desynchronise,
# ou publie.
from wifi_config import PASSWORD, SSID

import awen_config
from app import App

# Les numéros repris de buttons.py. On ne réutilise pas ses objets Pin :
# input.py a besoin de créer les siens pour gérer l'anti-rebond, les appuis
# longs et la répétition, dont buttons.py ne s'occupe pas.
BTN_LEFT, BTN_SELECT, BTN_RIGHT = 26, 27, 14

# ENCODEUR ROTATIF (Adafruit 377 ou EC11 equivalent)
#
# Cinq broches : trois d'un cote pour l'encodeur, deux de l'autre pour son
# poussoir.
#
#   les 3 :  celle du MILIEU est le commun -> GND
#            les deux exterieures -> ENC_CLK et ENC_DT
#   les 2 :  une -> ENC_PUSH, l'autre -> GND
#
# Aucune resistance : le tirage interne est active dans input.py. Si les
# crans comptent a l'envers, echange ENC_CLK et ENC_DT — c'est le seul
# effet du sens.
#
# L'Adafruit 377 fait un cycle de quadrature complet par cran, ce qui
# correspond au STEPS_PER_DETENT = 4 par defaut. Si un cran fait avancer de
# deux, c'est un modele different : ajuste cette valeur dans input.py.
# ATTENTION AUX ETIQUETTES DE LA CARTE
#
# La DevKit 30 broches melange deux conventions de serigraphie. GPIO 16 et
# GPIO 17 n'y sont PAS marques « D16 » et « D17 » : ils portent les noms de
# la deuxieme liaison serie.
#
#     GPIO 16  ->  broche marquee  RX2
#     GPIO 17  ->  broche marquee  TX2   (deja prise : DC de l'ecran)
#
# Ce sont des GPIO ordinaires : MicroPython n'ouvre pas UART2 tout seul.
ENC_CLK, ENC_DT, ENC_PUSH = 4, 19, 16

# Le poussoir de l'encodeur double le bouton B : tourner puis appuyer sans
# deplacer la main. Les trois boutons cables restent actifs.

# LED RGB a 4 broches : une patte par couleur, plus le commun.
#
# UNE RESISTANCE DE 220 OHMS SUR CHAQUE PATTE DE COULEUR. Sans elle la LED
# tire tout ce que le GPIO peut donner, et les deux se degradent.
#
# Le commun va au GND si la LED est a cathode commune (le cas courant), au
# 3V3 si elle est a anode commune — regle alors LED_COMMON sur "anode".
#
# PAS DE GPIO 12 ICI. C'est une broche de strapping (MTDI) : tiree au niveau
# haut au demarrage, l'ESP32 regle sa tension de flash a 1,8 V et refuse de
# demarrer — un symptome qui n'a rien a voir avec une LED.
LED_R, LED_G, LED_B = 32, 33, 13
LED_COMMON = "cathode"

# DHT11 NU (4 broches, sans platine). Face a la grille, pattes vers le bas :
#
#   1 VCC -> 3V3      2 DATA -> GPIO ci-dessous      3 rien      4 GND
#
# La broche 3 ne sert a rien, ne la relie pas.
#
# UNE RESISTANCE DE 10 kOhm ENTRE DATA ET VCC. Le module a platine que tu
# avais la portait deja ; un composant nu, non. Le tirage interne de l'ESP32
# est active en secours (voir sensor.py) et suffit souvent sur un fil court,
# mais des lectures qui echouent une fois sur trois designent ce tirage trop
# faible.
DHT_PIN = 25

app = App(tft, {
    "led": {"kind": "rgb", "pin_r": LED_R, "pin_g": LED_G,
            "pin_b": LED_B, "common": LED_COMMON},
    "sensor": {"kind": "dht11", "pin": DHT_PIN},
    "ssid": SSID,
    "password": PASSWORD,
    "base_url": awen_config.AWEN_URL,
    "api_key": awen_config.ESP32_API_KEY,
    "pins": {"pin_a": BTN_LEFT, "pin_b": BTN_SELECT, "pin_c": BTN_RIGHT,
             "clk": ENC_CLK, "dt": ENC_DT, "pin_push": ENC_PUSH},
})

app.run()
