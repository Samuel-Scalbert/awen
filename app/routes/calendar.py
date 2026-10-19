import calendar as pycal
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, Response, render_template, request, url_for

from ..models import Workout
from ..services import agenda_google, rappels
from ..services.calendar_sync import fetch_events
# Renommé : la fonction a déjà une variable « upcoming » (les évènements).
from ..services.progression import upcoming as suggestions

bp = Blueprint("calendar", __name__, url_prefix="/calendar")

MONTHS_FR = [None, "janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
DAYS_FR = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


@bp.route("/")
def view_calendar():
    today = date.today()
    year = request.args.get("y", default=today.year, type=int)
    month = request.args.get("m", default=today.month, type=int)
    if not 1 <= month <= 12:
        year, month = today.year, today.month

    workouts = Workout.query.order_by(Workout.date, Workout.id).all()
    done_by_day = {}
    for w in workouts:
        # Une séance fermée sans une seule série n'est pas un entraînement :
        # c'était le passage obligé de l'ancien écran pour changer de séance.
        if w.completed and not w.sets:
            continue
        done_by_day.setdefault(w.date.date(), []).append(w)

    # Suggestions sur les jours d'entraînement à venir : d'abord la séance
    # qui attend depuis le plus longtemps. Rien n'est imposé, le choix se
    # fait à la salle.
    fait_aujourdhui = any(w.sets for w in done_by_day.get(today, []))
    after = today if fait_aujourdhui else today - timedelta(days=1)
    planned = {d: focus for d, focus in suggestions(after, count=16)
               if d not in done_by_day}

    # Un seul téléchargement du flux : la grille a besoin du passé du mois
    # affiché, la liste du bas seulement du futur.
    all_events, cal_status = fetch_events(limit=None, include_past=True)
    events_by_day = {}
    for e in all_events:
        d = e["start"]
        events_by_day.setdefault(d.date(), []).append({
            "title": e["title"],
            "time": "" if e["all_day"] else "{:02d}h{:02d}".format(d.hour, d.minute),
        })

    weeks = []
    for wk in pycal.Calendar().monthdatescalendar(year, month):
        weeks.append([{
            "day": d.day,
            "in_month": d.month == month,
            "is_today": d == today,
            "done": done_by_day.get(d, []),
            "planned": planned.get(d),
            "events": events_by_day.get(d, []),
        } for d in wk])

    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)

    # Formatage en français ici : strftime('%a') suivrait la locale du
    # système, qui renvoie « Sat » sur cette machine.
    now = datetime.now(timezone.utc)
    upcoming = [e for e in all_events if e["start"] >= now][:10]
    for e in upcoming:
        d = e["start"]
        e["label"] = "{} {:02d}/{:02d} à {:02d}h{:02d}".format(
            DAYS_FR[d.weekday()], d.day, d.month, d.hour, d.minute)
    return render_template(
        "calendar.html", weeks=weeks, days=DAYS_FR,
        month_label=f"{MONTHS_FR[month]} {year}",
        prev_y=prev_y, prev_m=prev_m, next_y=next_y, next_m=next_m,
        events=upcoming, cal_status=cal_status,
        flux_rappels=url_for("calendar.reminders_feed", _external=True),
        agenda_google=agenda_google.actif(),
    )


@bp.route("/rappels.ics")
def reminders_feed():
    """Les rappels du soir, en agenda auquel le téléphone s'abonne."""
    lien = url_for("workout.list_workouts", _external=True)
    return Response(rappels.flux(lien), mimetype="text/calendar",
                    headers={"Cache-Control": "no-store",
                             "Content-Disposition": "inline; filename=awen-rappels.ics"})
