from flask import Blueprint, render_template
from ..services.calendar_sync import get_upcoming_events

bp = Blueprint("calendar", __name__, url_prefix="/calendar")


@bp.route("/")
def view_calendar():
    events = get_upcoming_events(limit=10)
    return render_template("calendar.html", events=events)
