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
    # Jarvis. Ollama tourne sur l'hote, pas dans le conteneur : lui
    # passer le GPU demanderait nvidia-container-toolkit pour un gain
    # nul, puisqu'il expose deja une API HTTP.
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    # "30m" garde le modele chaud entre deux questions ; "0" le decharge
    # aussitot. Sur 7,7 Go de RAM partages avec deux conteneurs, c'est le
    # reglage a mesurer en premier si la machine se met a ramer.
    OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
    # Nombre de couches confiees au GPU. "0" force le processeur.
    # Le serveur redemarre spontanement des que la carte calcule — sept
    # coupures le 16/09, pstore vide a chaque fois, donc electrique et non
    # logiciel. Tant que ce n'est pas regle, mieux vaut un assistant lent
    # qu'une machine qui tombe. Vide = laisser Ollama decider.
    OLLAMA_NUM_GPU = os.getenv("OLLAMA_NUM_GPU", "")
    # Voix Piper (.onnx). Vide : le navigateur parle a sa place.
    PIPER_MODEL = os.getenv("PIPER_MODEL", "")
