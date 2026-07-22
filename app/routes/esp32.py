"""API légère consommée par l'ESP32 pour l'affichage sur écran.

Payload volontairement compact et pré-formaté (chaînes prêtes à dessiner) :
l'ESP32 tourne en MicroPython interprété, tout ce qu'on calcule ici est
autant de travail qu'il n'a pas à faire.
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, current_app, jsonify, request

from ..models import Workout
from ..services.job_watch import get_daily_reports
from ..services.progression import (CYCLE, TRAINING_WEEKDAYS,
                                    next_session_type, plan_upcoming)

bp = Blueprint("esp32", __name__, url_prefix="/api/esp32")

DAYS_FR = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def _check_key():
    key = request.headers.get("X-API-Key") or request.args.get("key")
    if key != current_app.config["ESP32_API_KEY"]:
        abort(401)


def _short_date(d):
    return "{} {:02d}/{:02d}".format(DAYS_FR[d.weekday()], d.day, d.month)


@bp.route("/summary")
def summary():
    _check_key()
    today = date.today()
    now = datetime.now()

    workouts = Workout.query.order_by(Workout.date, Workout.id).all()
    last_focus, last_date = None, None
    for w in reversed(workouts):
        if w.focus in CYCLE:
            last_focus, last_date = w.focus, w.date.date()
            break

    after = max(filter(None, [last_date, today - timedelta(days=1)]))
    planned = plan_upcoming(last_focus, after, count=8)
    planned_today = next((f for d, f in planned if d == today), None)
    next_day, next_focus = planned[0] if planned else (None, None)

    today_workouts = [w for w in workouts if w.date.date() == today]
    done_today = any(w.completed for w in today_workouts)
    in_progress = any(not w.completed for w in today_workouts)

    # Séances ratées : jours d'entraînement passés depuis la dernière séance
    missed = 0
    if last_date:
        d = last_date + timedelta(days=1)
        while d < today:
            if d.weekday() in TRAINING_WEEKDAYS:
                missed += 1
            d += timedelta(days=1)
        missed = min(missed, 9)

    reports = get_daily_reports(limit=1) or []
    jobs_today, job_titles = 0, []
    if reports and reports[0]["date"] == today:
        offers = reports[0]["offers"]
        jobs_today = len(offers)
        job_titles = [o["title"][:36] for o in offers[:3]]

    return jsonify({
        "ok": True,
        "time": now.strftime("%H:%M"),
        "date": _short_date(today),
        "gym": {
            "today": planned_today or "",          # "" = repos aujourd'hui
            "done": done_today,
            "live": in_progress,
            "missed": missed,
            "next": "{} {}".format(_short_date(next_day), next_focus)
                    if next_day else "",
            "next_focus": next_focus or next_session_type(last_focus),
            "last": "{} {}".format(last_focus, _short_date(last_date))
                    if last_date else "",
        },
        "jobs": {
            "n": jobs_today,
            "titles": job_titles,
        },
    })
