import calendar as pycal
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, render_template, request

from ..models import Workout
from ..services.calendar_sync import fetch_events
from ..services.progression import CYCLE, plan_upcoming

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
        done_by_day.setdefault(w.date.date(), []).append(w)

    # Planning : rotation continue projetée sur les jours d'entraînement.
    last_focus, last_date = None, None
    for w in reversed(workouts):
        if w.focus in CYCLE:
            last_focus, last_date = w.focus, w.date.date()
            break
    after = max(filter(None, [last_date, today - timedelta(days=1)]))
    planned = {d: focus for d, focus in plan_upcoming(last_focus, after, count=16)
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
    )
