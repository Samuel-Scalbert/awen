import markdown as md
from flask import Blueprint, render_template

from ..services.job_watch import get_daily_reports

bp = Blueprint("jobs", __name__, url_prefix="/jobs")

MONTHS_FR = [None, "janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _date_fr(d):
    return f"{DAYS_FR[d.weekday()]} {d.day} {MONTHS_FR[d.month]} {d.year}"


def _render_md(text):
    return md.markdown(text, extensions=["tables"])


@bp.route("/")
def daily_jobs():
    reports = get_daily_reports(limit=14)
    if reports is not None:
        for r in reports:
            r["date_fr"] = _date_fr(r["date"]) if r["date"] else r["dirname"]
            for o in r["offers"]:
                o["body_html"] = _render_md(o["body"])
            r["conclusion_html"] = _render_md(r["conclusion"])
            r["raw_html"] = _render_md(r["raw"])
    return render_template("jobs.html", reports=reports)
