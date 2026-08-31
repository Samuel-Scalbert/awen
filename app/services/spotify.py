"""Lecture en cours et télécommande Spotify, côté serveur.

POURQUOI ICI ET PAS SUR L'ESP32

Le firmware précédent portait CLIENT_ID, CLIENT_SECRET et REFRESH_TOKEN sur
la carte. C'est ce qui a fuité : les versions compilées de ces fichiers de
configuration étaient suivies par git et publiées sur un dépôt public.

Un jeton de rafraîchissement ne s'expire pas tout seul et donne un accès
durable au compte. Sur un microcontrôleur il est en clair, lisible par
quiconque branche un câble, et impossible à révoquer sans reflasher. Sur le
serveur il vit dans un .env qui n'est pas versionné, derrière une machine
qu'on contrôle. L'afficheur n'est plus qu'une télécommande sans secret.

CE QUE SPOTIFY EXIGE

Les identifiants vont dans le .env du serveur :

    SPOTIFY_CLIENT_ID=...
    SPOTIFY_CLIENT_SECRET=...
    SPOTIFY_REFRESH_TOKEN=...

Le jeton de rafraîchissement doit avoir été obtenu avec les portées
`user-read-playback-state` ET `user-modify-playback-state`. La première suffit
à afficher ; la seconde est nécessaire pour la pause, les pistes et le volume.
Un jeton créé pour une intégration en lecture seule renverra 403 sur les
commandes, avec un message peu parlant.
"""
import base64
import io
import time

import requests
from flask import current_app

# La pochette est réduite ici et envoyée en pixels bruts. L'ESP32 ne sait pas
# décoder un JPEG, et lui faire faire le redimensionnement d'une image de
# 300 px prendrait des secondes pour un résultat pire.
COVER_SIZE = 64                 # 64 x 64 x 2 octets = 8 Ko, tenable en RAM

# Le panneau tourne avec _INVERT_COLORS = True dans st7789_min.py : le pilote
# inverse chaque couleur avant de l'envoyer, SAUF pour les images, dont il
# attend qu'elles arrivent déjà inversées. Sans ce XOR, la pochette sortirait
# en négatif — et le pilote n'a aucun moyen de deviner l'oubli.
_INVERT = True

_cover = {"url": None, "data": None}

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
TIMEOUT = 6           # secondes ; l'ESP32 attend, on ne le fait pas patienter

# Jeton d'accès mémorisé en mémoire. Il vaut une heure ; le redemander à
# chaque requête ajouterait un aller-retour réseau à chaque rafraîchissement
# de l'écran, soit toutes les cinq secondes.
_token = {"value": None, "expires_at": 0}


def configured():
    c = current_app.config
    return bool(c.get("SPOTIFY_CLIENT_ID") and c.get("SPOTIFY_CLIENT_SECRET")
                and c.get("SPOTIFY_REFRESH_TOKEN"))


def _access_token():
    """Le jeton courant, renouvelé seulement quand il expire."""
    now = time.time()
    if _token["value"] and now < _token["expires_at"]:
        return _token["value"]

    c = current_app.config
    basic = base64.b64encode("{}:{}".format(
        c["SPOTIFY_CLIENT_ID"], c["SPOTIFY_CLIENT_SECRET"]).encode()).decode()
    r = requests.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token",
              "refresh_token": c["SPOTIFY_REFRESH_TOKEN"]},
        headers={"Authorization": "Basic " + basic},
        timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    _token["value"] = data["access_token"]
    # 60 s de marge : un jeton qui expire pendant la requête suivante
    # produirait un 401 aléatoire, le pire genre de panne à diagnostiquer.
    _token["expires_at"] = now + data.get("expires_in", 3600) - 60
    return _token["value"]


def _headers():
    return {"Authorization": "Bearer " + _access_token()}


def now_playing():
    """L'état de lecture, prêt pour l'écran. None si rien n'est configuré.

    Renvoie un dict vide plutôt que None quand Spotify répond « rien en
    cours » : l'écran sait afficher « aucun appareil », il ne sait pas
    distinguer une panne d'un silence.
    """
    if not configured():
        return None
    try:
        r = requests.get(API + "/me/player", headers=_headers(),
                         timeout=TIMEOUT)
        if r.status_code == 204 or not r.content:
            return {"device": ""}          # rien en cours de lecture
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        current_app.logger.warning("spotify: %s", e)
        return {"device": ""}

    item = d.get("item") or {}
    album = item.get("album") or {}
    device = d.get("device") or {}
    artists = ", ".join(a["name"] for a in item.get("artists", []))

    # La plus petite image proposée par Spotify : on la réduit encore, autant
    # partir de 64 px que de 640.
    images = album.get("images") or []
    art = images[-1]["url"] if images else ""

    return {
        "title": item.get("name", ""),
        "artist": artists,
        "album": album.get("name", ""),
        "position_s": (d.get("progress_ms") or 0) // 1000,
        "duration_s": (item.get("duration_ms") or 0) // 1000,
        "volume": device.get("volume_percent") or 0,
        "playing": bool(d.get("is_playing")),
        "device": device.get("name", ""),
        "art_url": art,
    }


def cover_rgb565(url):
    """La pochette réduite en pixels bruts, prête pour blit_buffer().

    Renvoie COVER_SIZE x COVER_SIZE pixels en RGB565 gros-boutiste, déjà
    inversés pour ce panneau. None si l'image est introuvable.

    Le résultat est gardé en mémoire tant que l'URL ne change pas : l'ESP32
    interroge le serveur toutes les cinq secondes sur cet écran, et
    retélécharger puis redimensionner la même pochette à chaque fois serait
    absurde.
    """
    if not url:
        return None
    if _cover["url"] == url and _cover["data"] is not None:
        return _cover["data"]

    try:
        from PIL import Image
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img = img.resize((COVER_SIZE, COVER_SIZE), Image.LANCZOS)
    except Exception as e:
        current_app.logger.warning("spotify cover: %s", e)
        return None

    out = bytearray(COVER_SIZE * COVER_SIZE * 2)
    i = 0
    for (red, green, blue) in img.getdata():
        px = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        if _INVERT:
            px ^= 0xFFFF
        out[i] = px >> 8
        out[i + 1] = px & 0xFF
        i += 2

    _cover["url"] = url
    _cover["data"] = bytes(out)
    return _cover["data"]


def command(action, value=None):
    """Télécommande : play, pause, toggle, next, previous, volume.

    `toggle` est résolu ici plutôt que sur l'ESP32 : l'afficheur ne connaît
    l'état de lecture qu'à cinq secondes près, et deux appuis rapides
    l'enverraient deux fois dans le même sens.
    """
    if not configured():
        return False, "spotify non configure"

    try:
        if action == "toggle":
            state = now_playing() or {}
            action = "pause" if state.get("playing") else "play"

        if action in ("play", "pause"):
            r = requests.put("{}/me/player/{}".format(API, action),
                             headers=_headers(), timeout=TIMEOUT)
        elif action in ("next", "previous"):
            r = requests.post("{}/me/player/{}".format(API, action),
                              headers=_headers(), timeout=TIMEOUT)
        elif action == "volume":
            pct = max(0, min(100, int(value or 0)))
            r = requests.put(API + "/me/player/volume",
                             headers=_headers(),
                             params={"volume_percent": pct}, timeout=TIMEOUT)
        else:
            return False, "action inconnue"
    except Exception as e:
        current_app.logger.warning("spotify %s: %s", action, e)
        return False, str(e)

    if r.status_code == 403:
        # Cas le plus fréquent après une rotation : le jeton n'a que la
        # portée de lecture. On le dit, parce que le message brut de Spotify
        # n'aide pas.
        return False, "jeton sans portee user-modify-playback-state"
    if r.status_code == 404:
        return False, "aucun appareil actif"
    return r.status_code in (200, 202, 204), r.status_code
