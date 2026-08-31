"""Point d'entrée de l'afficheur Awen.

Ce fichier ne déclare aucune broche d'écran. `tft_setup.py`, dans le dépôt
esp32-desk-display, est déjà « le seul endroit où vivent les numéros de
broches » — le dupliquer ici garantirait qu'un jour les deux divergent.

    Ecran   CS 5, DC 17, RST 21, retroeclairage 22, SCK 18, MOSI 23
    Boutons gauche 26, selection 27, droite 14   (buttons.py)
    Potard  34    (ADC1 obligatoire)
    LED     32 R, 33 V, 13 B   (+ commun, + 3 resistances 220R)
    DHT11   25    (DATA)

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

# Le potard DOIT être sur ADC1 (GPIO 32-39) : ADC2 cesse de fonctionner dès
# que le wifi est actif. 34 est libre sur cette carte et en entrée seule,
# donc sans tirage interne parasite. Voir input.py.
POT = 34

# Pour passer à un encodeur rotatif, remplacer la ligne "pot" ci-dessous par
# ses deux broches. Le reste du firmware ne verra pas la différence : les deux
# produisent le même événement, et le rattrapage se désactive tout seul
# puisqu'un encodeur n'a aucune position à trahir.
#
#     "clk": 4, "dt": 19,         au lieu de       "pot": POT,
#
# Ses broches peuvent être n'importe où (ce sont des entrées numériques,
# ADC2 n'entre pas en jeu) sauf sur celles déjà prises par l'écran ou les
# boutons. Son propre bouton-poussoir se câble comme les trois autres.

# LED RGB a 4 broches : une patte par couleur, plus le commun.
#
# UNE RESISTANCE DE 220 OHMS SUR CHAQUE PATTE DE COULEUR. Sans elle la LED
# tire tout ce que le GPIO peut donner, et les deux se degradent.
#
# Le commun va au GND si la LED est a cathode commune (le cas courant), au
# 3V3 si elle est a anode commune — regle alors LED_COMMON sur "anode",
# sinon toutes les couleurs seront inversees. Voir led.py pour le test.
#
# PAS DE GPIO 12 ICI. C'est une broche de strapping (MTDI) : tiree au niveau
# haut au demarrage, l'ESP32 regle sa tension de flash a 1,8 V et refuse de
# demarrer — un symptome qui n'a rien a voir avec une LED.
LED_R, LED_G, LED_B = 32, 33, 13
LED_COMMON = "cathode"

# DHT11 : broche DATA ici, plus VCC (3V3 ou 5V selon ton module) et masse.
# La plupart des modules a trois broches ont deja leur resistance de tirage ;
# un composant nu sans module en demande une de 10 kOhm entre DATA et VCC.
DHT_PIN = 25

app = App(tft, {
    "led": {"kind": "rgb", "pin_r": LED_R, "pin_g": LED_G,
            "pin_b": LED_B, "common": LED_COMMON},
    "sensor": {"kind": "dht11", "pin": DHT_PIN},
    "ssid": SSID,
    "password": PASSWORD,
    "base_url": awen_config.AWEN_URL,
    "api_key": awen_config.ESP32_API_KEY,
    "pins": {"pin_a": BTN_LEFT, "pin_b": BTN_SELECT,
             "pin_c": BTN_RIGHT, "pot": POT},
})

app.run()
