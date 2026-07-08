from flask import Blueprint, render_template, request, redirect, url_for
from ..models import db, Workout

bp = Blueprint("workout", __name__, url_prefix="/workouts")


@bp.route("/")
def list_workouts():
    workouts = Workout.query.order_by(Workout.date.desc()).all()
    return render_template("workouts.html", workouts=workouts)


@bp.route("/programme")
def programme():
    return render_template("programme.html")


@bp.route("/add", methods=["POST"])
def add_workout():
    w = Workout(focus=request.form.get("focus"),
                notes=request.form.get("notes"))
    db.session.add(w)
    db.session.commit()
    return redirect(url_for("workout.list_workouts"))
