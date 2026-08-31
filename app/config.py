"""Configuration de l'application Awen."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Charger le .env AVANT la définition de Config : ses attributs lisent
# os.getenv au moment de l'import du module.
load_dotenv(BASE_DIR / ".env")


class Config:
    BASE_DIR = BASE_DIR
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'awen.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SAMSUNG_CALENDAR_ICS_URL = os.getenv("SAMSUNG_CALENDAR_ICS_URL", "")
    ESP32_API_KEY = os.getenv("ESP32_API_KEY", "change-me")
    # Dossier du pipeline Claude cowork de recherche d'emploi
    JOB_SEARCH_DIR = os.getenv("JOB_SEARCH_DIR", "")
    # Spotify. Le jeton vit ici et pas sur l'ESP32 : sur une carte il serait
    # en clair, lisible en branchant un câble, et irrévocable sans reflasher.
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    SPOTIFY_REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN", "")
    # Météo : Open-Meteo, sans clé d'API. Paris par défaut.
    WEATHER_LAT = float(os.getenv("WEATHER_LAT", "48.8566"))
    WEATHER_LON = float(os.getenv("WEATHER_LON", "2.3522"))
