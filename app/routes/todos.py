"""Page des tâches : ajouter, cocher, décocher."""
from datetime import date

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from ..services import todos as svc

bp = Blueprint("todos", __name__, url_prefix="/taches")


def _due(raw):
    """Une échéance mal saisie ne doit pas coûter la tâche."""
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


@bp.route("/")
def index():
    return render_template("todos.html",
                           pending=svc.pending(),
                           done=svc.done(),
                           counts=svc.counts(),
                           today=date.today())


@bp.route("/ajouter", methods=["POST"])
def add():
    entry = svc.add(request.form.get("text"),
                    _due(request.form.get("due")),
                    source="web")
    if entry is None:
        flash("Tâche vide, rien enregistré.")
    return redirect(url_for("todos.index"))


@bp.route("/<int:todo_id>/terminer", methods=["POST"])
def complete(todo_id):
    entry = svc.complete(todo_id, undo=request.form.get("undo") == "1")
    if entry is not None:
        flash("« {} » {}.".format(
            entry.text, "terminée" if entry.done else "remise à faire"))
    return redirect(url_for("todos.index"))
