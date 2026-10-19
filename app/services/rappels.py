"""Le rappel du soir : une séance commencée dans la journée et pas terminée.

Awen ne peut pas écrire dans l'agenda du téléphone, mais le téléphone peut
s'abonner à un agenda qu'Awen publie (/calendar/rappels.ics). Ce flux ne
porte qu'un rappel, et seulement si une séance a été commencée aujourd'hui
sans être terminée : c'est le bouton de fin qui applique la progression, et
l'oublier laisse le programme en l'état.

Le rappel sonne le soir (20 h par défaut, RAPPEL_SEANCE_HEURE). Une séance
commencée tard le reçoit une heure et demie après son début, avant minuit.
Il sort du flux dès que la séance est terminée, et l'agenda le retire à sa
synchronisation suivante.
"""
from datetime import date, datetime, time, timedelta, timezone

from flask import current_app
from icalendar import Alarm, Calendar, Event

from ..models import Workout

APRES = timedelta(minutes=90)     # délai minimal entre le début et le rappel
DERNIER = time(23, 45)            # jamais après : le rappel est pour aujourd'hui


def heure():
    """L'heure du rappel, réglée par RAPPEL_SEANCE_HEURE (« 20:00 »)."""
    raw = current_app.config.get("RAPPEL_SEANCE_HEURE") or "20:00"
    try:
        h, m = (int(x) for x in raw.strip().split(":"))
        return time(h, m)
    except (ValueError, TypeError):
        return time(20, 0)


def moment(commencee):
    """Quand rappeler une séance commencée à `commencee` : le soir même, à
    l'heure réglée, ou une heure et demie après le début si elle est tardive,
    jamais après 23 h 45."""
    jour = commencee.date()
    m = max(datetime.combine(jour, heure()), commencee + APRES)
    return min(m, datetime.combine(jour, DERNIER))


def titre(focus):
    return "Awen : termine ta séance {}".format(focus)


def rappels(today=None):
    """[(moment, titre, texte)] : le rappel du jour, s'il y a lieu."""
    today = today or date.today()
    debut = datetime.combine(today, time.min)
    ouverte = (Workout.query.filter(Workout.completed.is_(False),
                                    Workout.date >= debut,
                                    Workout.date < debut + timedelta(days=1))
               .order_by(Workout.date.desc()).first())
    if ouverte is None:
        return []
    n = len(ouverte.sets)
    commencee = ouverte.date.strftime("%Hh%M")
    if n:
        texte = ("Commencée à {}, {} série{} notée{}. Touche « Terminer la "
                 "séance » pour appliquer la progression.").format(
                     commencee, n, "s" if n > 1 else "", "s" if n > 1 else "")
    else:
        texte = ("Ouverte à {} sans aucune série notée. Enregistre ta séance, "
                 "ou annule-la si tu ne l'as pas faite.").format(commencee)
    return [(moment(ouverte.date), titre(ouverte.focus), texte)]


def flux(lien, today=None):
    """L'agenda des rappels, au format iCalendar.

    Les heures sont « flottantes » (sans fuseau) : le téléphone les lit à
    l'heure locale, ce qui évite de dépendre des fuseaux du serveur.
    """
    cal = Calendar()
    cal.add("prodid", "-//Awen//Rappels de séance//FR")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Awen")
    cal.add("x-wr-caldesc", "Rappel quand une séance commencée n'est pas terminée")
    # Indications de fraîcheur ; l'application d'abonnement garde le dernier mot.
    cal.add("refresh-interval", timedelta(minutes=30), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "PT30M")

    stamp = datetime.now(timezone.utc)
    for quand, intitule, texte in rappels(today):
        ev = Event()
        ev.add("uid", "rappel-seance-{}@awen".format(quand.date().isoformat()))
        ev.add("dtstamp", stamp)
        ev.add("dtstart", quand)
        ev.add("dtend", quand + timedelta(minutes=15))
        ev.add("summary", intitule)
        ev.add("description", "{}\n{}".format(texte, lien))
        ev.add("url", lien)
        alarme = Alarm()
        alarme.add("action", "DISPLAY")
        alarme.add("description", intitule)
        alarme.add("trigger", timedelta(0))
        ev.add_component(alarme)
        cal.add_component(ev)
    return cal.to_ical()
