from datetime import datetime

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, url_for)

from ..models import db, ExerciseSet, ProgramExercise, Workout
from ..services.progression import apply_progression, next_session_type

bp = Blueprint("workout", __name__, url_prefix="/workouts")


def _current_workout():
    return (Workout.query.filter_by(completed=False)
            .order_by(Workout.date.desc()).first())


def _last_focus(exclude_id=None):
    q = Workout.query.order_by(Workout.date.desc(), Workout.id.desc())
    for w in q:
        if w.id == exclude_id:
            continue
        if w.focus in ("Push", "Pull", "Legs"):
            return w.focus
    return None


@bp.route("/")
def list_workouts():
    workouts = Workout.query.order_by(Workout.date.desc()).all()
    current = _current_workout()
    if current:
        next_type = current.focus
    else:
        next_type = next_session_type(_last_focus())
    return render_template("workouts.html", workouts=workouts,
                           current=current, next_type=next_type)


@bp.route("/programme")
def programme():
    return render_template("programme.html")


@bp.route("/session")
def session():
    """Séance du jour : reprend la séance en cours ou en crée une."""
    workout = _current_workout()
    if workout is None:
        focus = next_session_type(_last_focus())
        workout = Workout(focus=focus, date=datetime.now())
        db.session.add(workout)
        db.session.commit()
    exercises = (ProgramExercise.query
                 .filter_by(session_type=workout.focus.lower())
                 .order_by(ProgramExercise.position).all())
    logged = {pe.id: sorted((s for s in workout.sets
                             if s.program_exercise_id == pe.id),
                            key=lambda s: s.set_number or 0)
              for pe in exercises}
    return render_template("session.html", workout=workout,
                           exercises=exercises, logged=logged)


@bp.route("/session/<int:workout_id>/log", methods=["POST"])
def log_set(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    pe = db.get_or_404(ProgramExercise, int(request.form["exercise_id"]))
    done = [s for s in workout.sets if s.program_exercise_id == pe.id]
    s = ExerciseSet(
        workout_id=workout.id,
        program_exercise_id=pe.id,
        exercise=pe.name,
        set_number=len(done) + 1,
        reps=int(request.form.get("reps") or 0),
        weight_kg=float((request.form.get("weight") or "0").replace(",", ".")),
    )
    db.session.add(s)
    db.session.commit()
    return jsonify(ok=True, set_number=s.set_number, reps=s.reps,
                   weight=s.weight_kg, total_sets=pe.sets,
                   rest_sec=pe.rest_sec)


@bp.route("/session/<int:workout_id>/finish", methods=["POST"])
def finish_session(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    workout.completed = True
    if request.form.get("notes"):
        workout.notes = request.form["notes"]
    changes = apply_progression(workout)
    db.session.commit()
    flash(f"Séance {workout.focus} terminée — {len(workout.sets)} séries. 💪")
    for c in changes:
        flash(f"Progression : {c}")
    return redirect(url_for("workout.list_workouts"))


@bp.route("/session/<int:workout_id>/delete", methods=["POST"])
def delete_session(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    db.session.delete(workout)
    db.session.commit()
    flash("Séance supprimée.")
    return redirect(url_for("workout.list_workouts"))
