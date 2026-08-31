"""Point d'entrée : câblage du matériel, puis on passe la main à App.

C'est le seul fichier à retoucher pour changer de carte ou de pilote. Tout le
reste du dossier ignore délibérément quel écran est branché.

Copie awen_config.example.py en awen_config.py et renseigne-le : ce fichier-là
contient la clé d'API et le mot de passe wifi, il ne doit jamais partir sur
GitHub.
"""
from machine import Pin, SPI
import st7789
import vga1_8x16 as font
import vga1_bold_16x32 as bigfont

import awen_config
from app import App

# ---- écran ---------------------------------------------------------------
# Broches d'une carte ESP32 + ST7789 240x320 courante. Vérifie-les contre ta
# propre carte : c'est la première chose qui casse d'un modèle à l'autre.
SPI_ID = 1
PIN_SCK, PIN_MOSI = 14, 13
PIN_DC, PIN_CS, PIN_RST, PIN_BL = 2, 15, 4, 21

# baudrate au maximum supporté : le redessin partiel économise déjà beaucoup,
# mais un SPI lent se voit malgré tout sur les grandes zones.
spi = SPI(SPI_ID, baudrate=40000000, polarity=1,
          sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI))

display = st7789.ST7789(
    spi, 240, 320,
    reset=Pin(PIN_RST, Pin.OUT),
    cs=Pin(PIN_CS, Pin.OUT),
    dc=Pin(PIN_DC, Pin.OUT),
    backlight=Pin(PIN_BL, Pin.OUT),
    rotation=0)
display.init()

# ---- application ---------------------------------------------------------
app = App(display, font, bigfont, {
    "ssid": awen_config.WIFI_SSID,
    "password": awen_config.WIFI_PASSWORD,
    "base_url": awen_config.AWEN_URL,
    "api_key": awen_config.ESP32_API_KEY,
    # Le potard DOIT être sur ADC1 (GPIO 32-39) : ADC2 est inutilisable dès
    # que le wifi est actif. Voir input.py.
    "pins": {"pin_a": 32, "pin_b": 33, "pin_c": 25, "pot": 34},
})

app.run()
