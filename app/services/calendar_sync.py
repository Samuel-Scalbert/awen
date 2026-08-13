"""Synchronisation du calendrier via flux ICS (Google, Samsung, Outlook…).

Deux principes ici :

1. **Accepter l'URL que l'utilisateur a sous la main.** Quand on copie un
   calendrier depuis Google, on récupère presque toujours le lien d'affichage
   (`.../calendar/u/0?cid=<base64>`), qui renvoie une page HTML et non un
   calendrier. On le convertit vers le flux ICS correspondant plutôt que de
   renvoyer une liste vide.
2. **Ne jamais échouer en silence.** L'ancienne version renvoyait `[]` sur
   n'importe quelle erreur, si bien qu'une URL invalide était indiscernable
   d'un agenda vide — la page affichait « configure SAMSUNG_CALENDAR_ICS_URL »
   alors que la variable *était* renseignée. On renvoie désormais un statut
   explicite pour que l'interface puisse dire ce qui ne va pas.
"""
import base64
import binascii
import urllib.parse
from datetime import datetime, timezone

import requests
from flask import current_app

try:
    from icalendar import Calendar
except ImportError:  # icalendar optionnel au démarrage
    Calendar = None


def normalize_ics_url(url):
    """Transforme un lien d'affichage Google en flux ICS ; sinon renvoie tel quel.

    `?cid=<base64>` encode l'identifiant du calendrier ; le flux public
    correspondant est `/calendar/ical/<id>/public/basic.ics`. Ne fonctionne
    que si le calendrier est public — un agenda privé exige son « adresse
    secrète au format iCal », que l'on ne peut pas deviner.
    """
    if not url:
        return url
    parsed = urllib.parse.urlparse(url)
    if "calendar.google.com" not in parsed.netloc or "/ical/" in parsed.path:
        return url
    cid = urllib.parse.parse_qs(parsed.query).get("cid", [None])[0]
    if not cid:
        return url
    try:
        # padding rétabli : Google tronque le remplissage base64
        cal_id = base64.b64decode(cid + "=" * (-len(cid) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return url
    return ("https://calendar.google.com/calendar/ical/{}/public/basic.ics"
            .format(urllib.parse.quote(cal_id, safe="")))


def fetch_events(limit=10):
    """Renvoie (events, status). status ∈ ok / not_configured / no_lib /
    unreachable / not_a_calendar / unreadable."""
    raw = current_app.config.get("SAMSUNG_CALENDAR_ICS_URL")
    if not raw:
        return [], "not_configured"
    if Calendar is None:
        return [], "no_lib"

    url = normalize_ics_url(raw)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        current_app.logger.warning("[calendrier] téléchargement échoué : %r", e)
        return [], "unreachable"

    if b"BEGIN:VCALENDAR" not in resp.content:
        # Cas le plus fréquent : une page HTML renvoyée à la place du flux.
        current_app.logger.warning(
            "[calendrier] la réponse n'est pas un ICS (Content-Type=%s)",
            resp.headers.get("Content-Type"))
        return [], "not_a_calendar"

    try:
        cal = Calendar.from_ical(resp.content)
    except Exception as e:
        current_app.logger.warning("[calendrier] ICS illisible : %r", e)
        return [], "unreadable"

    now = datetime.now(timezone.utc)
    events = []
    for comp in cal.walk("VEVENT"):
        start_prop = comp.get("DTSTART")
        if start_prop is None:
            continue
        start = start_prop.dt
        if isinstance(start, datetime):
            start_dt = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        else:  # évènement sur la journée entière
            start_dt = datetime.combine(start, datetime.min.time(), timezone.utc)
        if start_dt >= now:
            events.append({
                "title": str(comp.get("SUMMARY", "(sans titre)")),
                "start": start_dt,
            })

    events.sort(key=lambda e: e["start"])
    return events[:limit], "ok"


def get_upcoming_events(limit=10):
    """Compatibilité : uniquement les évènements (utilisé par l'API ESP32)."""
    events, _ = fetch_events(limit)
    return [{"title": e["title"], "start": e["start"].isoformat()} for e in events]
