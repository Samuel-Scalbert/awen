"""Pages de statistiques : vue d'ensemble et détail par exercice."""
from flask import Blueprint, render_template

from ..models import db, ExerciseNote, ProgramExercise
from ..services import charts
from ..services.stats import (FOCUS_COLORS, exercise_detail, exercise_rows,
                              overview)

bp = Blueprint("stats", __name__, url_prefix="/stats")

DAYS_FR = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def _kg(v):
    return f"{v / 1000:.1f} t".replace(".", ",") if v >= 1000 else f"{v:g} kg"


@bp.route("/")
def dashboard():
    o = overview()
    rows = exercise_rows()

    volume_chart = charts.line_chart(
        [(s["date"].strftime("%d/%m"), s["volume"]) for s in o["sessions"]],
        fmt=_kg)
    weekly_chart = charts.bar_chart(
        [(w["week"].strftime("%d/%m"), w["volume"], None) for w in o["weekly"]],
        fmt=_kg)
    weekday_chart = charts.bar_chart(
        [(DAYS_FR[i], n, None) for i, n in enumerate(o["weekdays"])],
        fmt=lambda v: f"{v:g}")
    focus_chart = charts.bar_chart(
        [(f, d["volume"], FOCUS_COLORS[f]) for f, d in o["by_focus"].items()],
        fmt=_kg)

    return render_template("stats.html", o=o, rows=rows, kg=_kg,
                           volume_chart=volume_chart, weekly_chart=weekly_chart,
                           weekday_chart=weekday_chart, focus_chart=focus_chart,
                           focus_colors=FOCUS_COLORS)


@bp.route("/exercice/<int:pe_id>")
def exercise_stats(pe_id):
    pe = db.get_or_404(ProgramExercise, pe_id)
    history = exercise_detail(pe)
    notes = {n.workout_id: n.text for n
             in ExerciseNote.query.filter_by(program_exercise_id=pe.id)
             if (n.text or "").strip()}

    weight_chart = charts.line_chart(
        [(h["date"].strftime("%d/%m"), h["weight"]) for h in history],
        fmt=lambda v: f"{v:g} kg")
    e1rm_chart = charts.line_chart(
        [(h["date"].strftime("%d/%m"), h["best_e1rm"] or 0) for h in history],
        fmt=lambda v: f"{v:g} kg")
    volume_chart = charts.bar_chart(
        [(h["date"].strftime("%d/%m"), h["volume"], None) for h in history],
        fmt=_kg)

    # Progression annoncée = de la première charge enregistrée à la charge
    # programmée aujourd'hui (celle qu'affiche la grande tuile), et non à
    # celle de la dernière séance : sinon le chiffre contredit le titre.
    first = history[0]["weight"] if history else 0
    gain = (pe.weight_kg or 0) - first
    gain_pct = round(100 * gain / first) if first else 0

    return render_template("stats_exercise.html", pe=pe, history=history,
                           notes=notes, kg=_kg, gain=gain, gain_pct=gain_pct,
                           weight_chart=weight_chart, e1rm_chart=e1rm_chart,
                           volume_chart=volume_chart)
