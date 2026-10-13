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
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app

try:
    from icalendar import Calendar
except ImportError:  # icalendar optionnel au démarrage
    Calendar = None

try:
    from dateutil.rrule import rrulestr
except ImportError:  # livré avec icalendar ; absent, les répétitions sautent
    rrulestr = None

# L'afficheur interroge le serveur toutes les trente secondes : sans cache,
# c'est autant de téléchargements du flux, chacun pouvant bloquer dix
# secondes. Un agenda ne change pas à cette cadence.
AGENDA_CACHE_S = 300

_cache = {"at": 0.0, "url": None, "cal": None}


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


def _load_calendar(max_age=0):
    """Télécharge et lit le flux. Renvoie (calendrier, statut).

    `max_age` en secondes réutilise un téléchargement récent, et sert de
    filet : si le flux ne répond plus, l'agenda d'il y a une heure vaut mieux
    qu'un écran vide. À zéro, on télécharge toujours : c'est ce que veut la
    page web, où l'on vient justement vérifier un évènement à peine saisi.
    """
    raw = current_app.config.get("SAMSUNG_CALENDAR_ICS_URL")
    if not raw:
        return None, "not_configured"
    if Calendar is None:
        return None, "no_lib"

    url = normalize_ics_url(raw)
    connu = _cache["cal"] if (max_age and _cache["url"] == url) else None
    if connu is not None and time.time() - _cache["at"] < max_age:
        return connu, "ok"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        current_app.logger.warning("[calendrier] téléchargement échoué : %r", e)
        return (connu, "ok") if connu is not None else (None, "unreachable")

    if b"BEGIN:VCALENDAR" not in resp.content:
        # Cas le plus fréquent : une page HTML renvoyée à la place du flux.
        current_app.logger.warning(
            "[calendrier] la réponse n'est pas un ICS (Content-Type=%s)",
            resp.headers.get("Content-Type"))
        return None, "not_a_calendar"

    try:
        cal = Calendar.from_ical(resp.content)
    except Exception as e:
        current_app.logger.warning("[calendrier] ICS illisible : %r", e)
        return None, "unreadable"

    _cache.update(at=time.time(), url=url, cal=cal)
    return cal, "ok"


def fetch_events(limit=10, include_past=False):
    """Renvoie (events, status). status ∈ ok / not_configured / no_lib /
    unreachable / not_a_calendar / unreadable.

    include_past=True conserve les évènements déjà passés : la grille
    mensuelle doit pouvoir remplir les jours du début de mois, alors que la
    liste « prochains évènements » ne veut que le futur.
    """
    cal, status = _load_calendar()
    if cal is None:
        return [], status

    now = datetime.now(timezone.utc)
    events = []
    for comp in cal.walk("VEVENT"):
        start_prop = comp.get("DTSTART")
        if start_prop is None:
            continue
        start = start_prop.dt
        if isinstance(start, datetime):
            start_dt = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
            all_day = False
        else:  # évènement sur la journée entière
            start_dt = datetime.combine(start, datetime.min.time(), timezone.utc)
            all_day = True
        if include_past or start_dt >= now:
            events.append({
                "title": str(comp.get("SUMMARY", "(sans titre)")),
                "start": start_dt,
                "all_day": all_day,
            })

    events.sort(key=lambda e: e["start"])
    return (events if limit is None else events[:limit]), "ok"


def get_upcoming_events(limit=10):
    """Compatibilité : uniquement les évènements (utilisé par l'API ESP32)."""
    events, _ = fetch_events(limit)
    return [{"title": e["title"], "start": e["start"].isoformat()} for e in events]


# --------------------------------------------------------------------------
# L'agenda jour par jour, pour l'afficheur
#
# fetch_events() ne lit que la première occurrence d'un évènement répété :
# suffisant pour une liste « à venir », faux pour un agenda du jour, où la
# séance du mardi doit revenir chaque mardi. occurrences() déplie les
# répétitions et rend des heures LOCALES, celles qu'on lit sur une montre.


def _local(value):
    """Une date ou un instant du flux, en heure murale locale sans fuseau.

    Un instant sans fuseau est une heure « flottante » : la norme la définit
    comme l'heure locale de qui la lit, on la garde donc telle quelle.
    """
    if not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _duration(comp, start, all_day):
    end = comp.get("DTEND")
    if end is not None:
        try:
            return max(_local(end.dt) - _local(start), timedelta(0))
        except TypeError:
            pass
    length = comp.get("DURATION")
    if length is not None:
        return max(length.dt, timedelta(0))
    return timedelta(days=1) if all_day else timedelta(0)


def _starts(comp, start, lo, hi):
    """Les débuts d'un évènement entre deux instants locaux, EXDATE retirés."""
    rule = comp.get("RRULE")
    if rule is None or rrulestr is None:
        return [start]

    first = start if isinstance(start, datetime) else _local(start)
    text = rule.to_ical().decode()
    naive = first.tzinfo is None
    try:
        series = rrulestr(text, dtstart=first)
    except ValueError:
        # UNTIL et DTSTART ne s'accordent pas sur le fuseau. La norme
        # l'interdit, des agendas le produisent quand même : on raisonne
        # alors en heure murale plutôt que de perdre toute la série.
        try:
            series = rrulestr(text, dtstart=first.replace(tzinfo=None),
                              ignoretz=True)
            naive = True
        except ValueError as e:
            current_app.logger.warning("[calendrier] RRULE ignorée : %r", e)
            return [start]

    marge = timedelta(days=1)       # couvre l'écart entre fuseaux
    a, b = lo - marge, hi + marge
    if not naive:
        a, b = a.astimezone(first.tzinfo), b.astimezone(first.tzinfo)
    found = series.between(a, b, inc=True)
    if naive and first.tzinfo is not None:
        found = [d.replace(tzinfo=first.tzinfo) for d in found]

    removed = set()
    exdates = comp.get("EXDATE")
    for group in (exdates if isinstance(exdates, list) else [exdates]):
        for item in getattr(group, "dts", ()):
            removed.add(_local(item.dt))
    return [d for d in found if _local(d) not in removed]


def occurrences(first, last, max_age=AGENDA_CACHE_S):
    """Renvoie (évènements, statut) du jour `first` au jour `last` inclus.

    Chaque évènement : title, start et end (heure locale sans fuseau),
    all_day. Un évènement de plusieurs journées entières compte une fois par
    jour ; un évènement horaire qui passe minuit ne compte que le jour où il
    commence.
    """
    cal, status = _load_calendar(max_age)
    if cal is None:
        return [], status

    lo = datetime(first.year, first.month, first.day)
    hi = datetime(last.year, last.month, last.day) + timedelta(days=1)
    comps = [c for c in cal.walk("VEVENT") if c.get("DTSTART") is not None]

    # Une occurrence déplacée a son propre VEVENT, qui porte la date qu'elle
    # remplace : sans ce relevé, la série la produirait une seconde fois.
    moved = set()
    for c in comps:
        rid = c.get("RECURRENCE-ID")
        if rid is not None:
            moved.add((str(c.get("UID", "")), _local(rid.dt)))

    out = []
    for c in comps:
        if str(c.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start = c["DTSTART"].dt
        all_day = not isinstance(start, datetime)
        length = _duration(c, start, all_day)
        uid = str(c.get("UID", ""))
        title = str(c.get("SUMMARY", "")).strip() or "(sans titre)"
        repeated = c.get("RRULE") is not None

        for s in _starts(c, start, lo - length, hi):
            begin = _local(s)
            if repeated and (uid, begin) in moved:
                continue
            if all_day:
                for k in range(max(1, length.days)):
                    day = begin + timedelta(days=k)
                    if lo <= day < hi:
                        out.append({"title": title, "start": day,
                                    "end": day + timedelta(days=1),
                                    "all_day": True})
            elif lo <= begin < hi:
                out.append({"title": title, "start": begin,
                            "end": begin + length, "all_day": False})

    out.sort(key=lambda e: (e["start"], e["title"]))
    return out, "ok"
