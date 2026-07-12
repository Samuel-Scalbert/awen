import markdown as md
from flask import Blueprint, abort, render_template, send_from_directory

from ..services.job_watch import (get_cover_letters, get_daily_reports,
                                  letters_dir, read_cover_letter)

bp = Blueprint("jobs", __name__, url_prefix="/jobs")

MONTHS_FR = [None, "janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _date_fr(d):
    return f"{DAYS_FR[d.weekday()]} {d.day} {MONTHS_FR[d.month]} {d.year}"


def _render_md(text):
    return md.markdown(text, extensions=["tables"])


@bp.route("/lettres")
def letters():
    return render_template("lettres.html", letters=get_cover_letters())


@bp.route("/lettres/lire/<path:filename>")
def read_letter(filename):
    text = read_cover_letter(filename)
    if text is None:
        abort(404)
    return render_template("lettre.html", filename=filename,
                           title=filename.rsplit(".", 1)[0],
                           content_html=_render_md(text))


@bp.route("/lettres/telecharger/<path:filename>")
def download_letter(filename):
    base = letters_dir()
    if base is None:
        abort(404)
    return send_from_directory(base, filename, as_attachment=True)


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
