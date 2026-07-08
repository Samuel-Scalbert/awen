"""Configuration de l'application Awen."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'awen.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SAMSUNG_CALENDAR_ICS_URL = os.getenv("SAMSUNG_CALENDAR_ICS_URL", "")
    ESP32_API_KEY = os.getenv("ESP32_API_KEY", "change-me")
