"""Synchronisation du calendrier Samsung via export ICS.

Samsung Calendar peut exporter un flux .ics (Google/Outlook sync ou lien
d'abonnement). On le télécharge et on renvoie les prochains évènements.
"""
from datetime import datetime, timezone

import requests
from flask import current_app

try:
    from icalendar import Calendar
except ImportError:  # icalendar optionnel au démarrage
    Calendar = None


def get_upcoming_events(limit=10):
    url = current_app.config.get("SAMSUNG_CALENDAR_ICS_URL")
    if not url or Calendar is None:
        return []

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        cal = Calendar.from_ical(resp.content)
    except Exception:
        return []

    now = datetime.now(timezone.utc)
    events = []
    for comp in cal.walk("VEVENT"):
        start = comp.get("DTSTART").dt
        if isinstance(start, datetime):
            start_dt = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        else:  # date seule
            start_dt = datetime.combine(start, datetime.min.time(), timezone.utc)
        if start_dt >= now:
            events.append({
                "title": str(comp.get("SUMMARY", "")),
                "start": start_dt.isoformat(),
            })

    events.sort(key=lambda e: e["start"])
    return events[:limit]
