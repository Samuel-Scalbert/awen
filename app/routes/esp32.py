"""API légère consommée par l'ESP32 pour l'affichage sur écran."""
from datetime import datetime
from flask import Blueprint, jsonify, current_app, request, abort

from ..models import Workout, Recipe
from ..services.calendar_sync import get_upcoming_events

bp = Blueprint("esp32", __name__, url_prefix="/api/esp32")


def _check_key():
    key = request.headers.get("X-API-Key") or request.args.get("key")
    if key != current_app.config["ESP32_API_KEY"]:
        abort(401)


@bp.route("/summary")
def summary():
    _check_key()
    last = Workout.query.order_by(Workout.date.desc()).first()
    events = get_upcoming_events(limit=1)
    next_event = events[0] if events else None
    return jsonify({
        "time": datetime.utcnow().isoformat(),
        "last_workout": last.focus if last else None,
        "next_event": next_event,
        "favorite_recipes": Recipe.query.filter_by(is_favorite=True).count(),
    })
