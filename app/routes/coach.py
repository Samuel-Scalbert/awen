"""Page du coach : observations, application des conseils, mesures."""
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..models import BodyWeight, CoachDecision, JumpTest, db
from ..services import attendance, charts, coach

bp = Blueprint("coach", __name__, url_prefix="/coach")


@bp.route("/")
def dashboard():
    advice = coach.analyse()
    recap = coach.weekly_recap()

    weights = BodyWeight.query.order_by(BodyWeight.date).all()
    jumps = JumpTest.query.order_by(JumpTest.date).all()
    weight_chart = charts.line_chart(
        [(w.date.strftime("%d/%m"), w.weight_kg) for w in weights],
        fmt=lambda v: f"{v:g} kg")
    jump_chart = charts.line_chart(
        [(j.date.strftime("%d/%m"), j.height_cm) for j in jumps],
        fmt=lambda v: f"{v:g} cm")

    return render_template(
        "coach.html", advice=advice, recap=recap,
        attendance=attendance.summary(),
        weights=weights[-8:], jumps=jumps[-8:],
        weight_chart=weight_chart, jump_chart=jump_chart,
        decisions=CoachDecision.query.order_by(
            CoachDecision.created_at.desc()).limit(15).all(),
        today=date.today().isoformat())


@bp.route("/appliquer", methods=["POST"])
def apply():
    pe = coach.apply_advice(
        int(request.form["exercise_id"]),
        float(request.form["new_weight"]),
        request.form.get("reason", ""))
    if pe:
        flash(f"{pe.name} : charge réglée à {pe.weight_kg:g} kg.")
    return redirect(url_for("coach.dashboard"))


@bp.route("/assiduite", methods=["POST"])
def qualify_missed():
    """Dit pourquoi une séance a été manquée : absent, ou ratée.

    C'est la seule chose que l'app ne peut pas déduire toute seule. Le trou
    dans le calendrier est identique dans les deux cas ; seul toi sais si tu
    pouvais y être.
    """
    day = date.fromisoformat(request.form["date"])
    kind = request.form["kind"]
    joli = day.strftime("%d/%m/%Y")
    if kind == "clear":
        attendance.unqualify(day)
        flash(f"{joli} : à qualifier de nouveau.")
    else:
        attendance.qualify(day, kind, request.form.get("note"))
        flash(f"{joli} : {'absence' if kind == 'absent' else 'séance ratée'} "
              "enregistrée.")
    return redirect(url_for("coach.dashboard", _anchor="assiduite"))


@bp.route("/poids", methods=["POST"])
def log_weight():
    """Une pesée par jour : on écrase celle du jour plutôt que d'empiler."""
    day = date.fromisoformat(request.form.get("date") or date.today().isoformat())
    value = float((request.form["weight_kg"] or "0").replace(",", "."))
    entry = BodyWeight.query.filter_by(date=day).first()
    if entry is None:
        entry = BodyWeight(date=day)
        db.session.add(entry)
    entry.weight_kg = value
    entry.note = request.form.get("note") or None
    db.session.commit()
    flash(f"Pesée enregistrée : {value:g} kg le {day.strftime('%d/%m/%Y')}.")
    return redirect(url_for("coach.dashboard"))


@bp.route("/detente", methods=["POST"])
def log_jump():
    day = date.fromisoformat(request.form.get("date") or date.today().isoformat())
    value = float((request.form["height_cm"] or "0").replace(",", "."))
    db.session.add(JumpTest(date=day, height_cm=value,
                            note=request.form.get("note") or None))
    db.session.commit()
    flash(f"Détente enregistrée : {value:g} cm.")
    return redirect(url_for("coach.dashboard"))
