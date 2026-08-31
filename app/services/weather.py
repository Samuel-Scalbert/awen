"""Météo du jour, via Open-Meteo.

Open-Meteo plutôt qu'un autre : pas de clé d'API à gérer, pas de compte, pas
de quota à surveiller. Une dépendance qui ne demande aucun secret est une
dépendance qui ne peut pas fuiter.

Les coordonnées viennent du .env (WEATHER_LAT / WEATHER_LON), Paris par
défaut. La réponse est gardée une demi-heure : la météo ne change pas plus
vite, et l'ESP32 interroge le serveur toutes les 30 secondes.
"""
import time

import requests
from flask import current_app

URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 6
CACHE_S = 1800

_cache = {"at": 0, "data": None}

# Codes WMO regroupés en libellés courts, tenables sur 30 colonnes. Le
# détail (« bruine verglaçante légère ») n'apporte rien sur un afficheur qu'on
# regarde une seconde en passant.
_WMO = {
    0: ("CIEL CLAIR", "*"),
    1: ("PEU NUAGEUX", "*"),
    2: ("NUAGES EPARS", "~"),
    3: ("COUVERT", "="),
    45: ("BROUILLARD", "="), 48: ("BROUILLARD GIVRANT", "="),
    51: ("BRUINE", "'"), 53: ("BRUINE", "'"), 55: ("BRUINE FORTE", "'"),
    56: ("BRUINE VERGLACANTE", "'"), 57: ("BRUINE VERGLACANTE", "'"),
    61: ("PLUIE FAIBLE", "'"), 63: ("PLUIE", "'"), 65: ("PLUIE FORTE", "!"),
    66: ("PLUIE VERGLACANTE", "!"), 67: ("PLUIE VERGLACANTE", "!"),
    71: ("NEIGE FAIBLE", "*"), 73: ("NEIGE", "*"), 75: ("NEIGE FORTE", "!"),
    77: ("GRAINS DE NEIGE", "*"),
    80: ("AVERSES", "'"), 81: ("AVERSES", "'"), 82: ("AVERSES FORTES", "!"),
    85: ("AVERSES DE NEIGE", "*"), 86: ("AVERSES DE NEIGE", "!"),
    95: ("ORAGE", "!"), 96: ("ORAGE ET GRELE", "!"), 99: ("ORAGE ET GRELE", "!"),
}


def describe(code):
    return _WMO.get(code, ("", "?"))


def today():
    """Température actuelle, min/max du jour et libellé. None si indisponible.

    Un échec réseau renvoie la dernière réponse connue plutôt que rien : une
    météo d'il y a une heure reste plus utile qu'une ligne vide, et l'écran
    n'a aucun moyen d'afficher « je ne sais pas » qui vaille mieux.
    """
    now = time.time()
    if _cache["data"] is not None and now - _cache["at"] < CACHE_S:
        return _cache["data"]

    c = current_app.config
    try:
        r = requests.get(URL, timeout=TIMEOUT, params={
            "latitude": c.get("WEATHER_LAT", 48.8566),
            "longitude": c.get("WEATHER_LON", 2.3522),
            "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max",
            "timezone": "Europe/Paris",
            "forecast_days": 1,
        })
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        current_app.logger.warning("meteo: %s", e)
        return _cache["data"]

    cur = d.get("current") or {}
    day = d.get("daily") or {}

    def first(key, default=None):
        vals = day.get(key) or []
        return vals[0] if vals else default

    label, icon = describe(cur.get("weather_code"))
    _cache["data"] = {
        "now_c": round(cur.get("temperature_2m") or 0),
        "min_c": round(first("temperature_2m_min") or 0),
        "max_c": round(first("temperature_2m_max") or 0),
        "rain_pct": first("precipitation_probability_max") or 0,
        "label": label,
        "icon": icon,
    }
    _cache["at"] = now
    return _cache["data"]
