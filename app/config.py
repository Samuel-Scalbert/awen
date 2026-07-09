"""Configuration de l'application Awen."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Charger le .env AVANT la définition de Config : ses attributs lisent
# os.getenv au moment de l'import du module.
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'awen.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SAMSUNG_CALENDAR_ICS_URL = os.getenv("SAMSUNG_CALENDAR_ICS_URL", "")
    ESP32_API_KEY = os.getenv("ESP32_API_KEY", "change-me")
    # Dossier du pipeline Claude cowork de recherche d'emploi
    JOB_SEARCH_DIR = os.getenv("JOB_SEARCH_DIR", "")
