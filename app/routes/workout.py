from datetime import datetime

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, url_for)

from ..models import db, ExerciseNote, ExerciseSet, ProgramExercise, Workout
from ..services.progression import (REPRISE, apply_progression,
                                    next_session_type, recompute_from_history)

bp = Blueprint("workout", __name__, url_prefix="/workouts")



def _current_workout():
    return (Workout.query.filter_by(completed=False)
            .order_by(Workout.date.desc()).first())


def session_exercises(focus, block="force"):
    """Exercices actifs d'une séance, dans l'ordre choisi sur la page Programme.

    La plyométrie a sa propre page : la séance ne contient plus que la force.
    Les exercices désactivés disparaissent d'ici mais gardent leur historique.
    """
    return (ProgramExercise.query
            .filter_by(session_type=focus.lower(), block=block)
            .filter(ProgramExercise.active.is_(True))
            .order_by(ProgramExercise.position, ProgramExercise.id).all())


def reprise_exercises():
    """Tous les exercices de force des trois séances, dans l'ordre du programme.

    Aucune sélection, aucun ordre imposé : une reprise sert à retrouver ce
    qu'on aime, et ce choix-là appartient au moment, pas au programme. La
    pliométrie reste en dehors — elle se fait frais, ce qu'on n'est
    précisément pas en rentrant de plusieurs semaines d'arrêt.
    """
    out = []
    for st in ("push", "pull", "legs"):
        out.extend(session_exercises(st, "force"))
    return out


def _last_focus(exclude_id=None):
    """Dernière séance PPL, pour continuer la rotation.

    Les reprises sont ignorées : elles n'appartiennent pas au cycle. Sans ça,
    une reprise le lundi décalerait tout le programme de la semaine.
    """
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
    notes_by_workout = {}
    for n in ExerciseNote.query.all():
        notes_by_workout.setdefault(n.workout_id, {})[n.program_exercise_id] = n.text
    return render_template("workouts.html", workouts=workouts,
                           current=current, next_type=next_type,
                           notes_by_workout=notes_by_workout)


@bp.route("/programme")
def programme():
    groups = [(st, session_exercises(st, "plyo"), session_exercises(st, "force"))
              for st in ("push", "pull", "legs")]
    return render_template("programme.html", groups=groups)


@bp.route("/programme/move/<int:pe_id>/<direction>", methods=["POST"])
def move_exercise(pe_id, direction):
    """Monte ou descend un exercice dans sa séance.

    On échange les positions avec le voisin plutôt que de renuméroter tout le
    bloc : c'est suffisant et ça ne touche à rien d'autre.
    """
    pe = db.get_or_404(ProgramExercise, pe_id)
    siblings = session_exercises(pe.session_type, pe.block)
    idx = next(i for i, x in enumerate(siblings) if x.id == pe.id)
    swap = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap < len(siblings):
        other = siblings[swap]
        pe.position, other.position = other.position, pe.position
        # Deux exercices peuvent partager une position après d'anciennes
        # migrations : on renumérote proprement pour que l'échange soit visible.
        for i, x in enumerate(session_exercises(pe.session_type, pe.block), 1):
            x.position = i
        db.session.commit()
    return redirect(url_for("workout.programme") + "#" + pe.session_type)


@bp.route("/programme/recompute", methods=["POST"])
def recompute_weights():
    """Recale les charges du programme sur ce qui a vraiment été soulevé."""
    changes = recompute_from_history()
    if changes:
        flash("Charges recalculées depuis l'historique :")
        for c in changes:
            flash(c)
    else:
        flash("Aucune charge à recaler : le programme correspond déjà à "
              "l'historique.")
    return redirect(url_for("workout.programme"))


@bp.route("/programme/update", methods=["POST"])
def update_programme():
    """Correction manuelle d'un exercice (charge, fourchette, séries)."""
    pe = db.get_or_404(ProgramExercise, int(request.form["id"]))
    pe.weight_kg = float((request.form.get("weight_kg") or "0").replace(",", "."))
    pe.rep_min = int(request.form.get("rep_min") or pe.rep_min)
    pe.rep_max = int(request.form.get("rep_max") or pe.rep_max)
    pe.sets = int(request.form.get("sets") or pe.sets)
    db.session.commit()
    flash(f"{pe.name} mis à jour : {pe.sets}×{pe.rep_min}-{pe.rep_max} "
          f"@ {pe.weight_kg:g} kg.")
    return redirect(url_for("workout.programme"))


@bp.route("/session")
def session():
    """Séance du jour : reprend la séance en cours ou en crée une."""
    workout = _current_workout()
    # Une reprise ouverte n'a pas d'exercices sous son focus : la rendre ici
    # afficherait une page vide au lieu de la séance qu'on est en train de
    # faire.
    if workout is not None and workout.focus == REPRISE:
        return redirect(url_for("workout.reprise"))
    if workout is None:
        focus = next_session_type(_last_focus())
        workout = Workout(focus=focus, date=datetime.now())
        db.session.add(workout)
        db.session.commit()
    exercises = session_exercises(workout.focus)
    logged = {pe.id: sorted((s for s in workout.sets
                             if s.program_exercise_id == pe.id),
                            key=lambda s: s.set_number or 0)
              for pe in exercises}
    notes = {n.program_exercise_id: n.text
             for n in workout.notes_by_exercise}
    return render_template("session.html", workout=workout, mode="force",
                           exercises=exercises, logged=logged, notes=notes)


@bp.route("/plyo")
def plyo():
    """Bloc pliométrique, sur sa propre page.

    Il ne fait plus partie de la séance de force : c'est un bonus qu'on fait
    quand on est frais. Les séries sont rattachées à la séance en cours pour
    rester dans les statistiques, donc une séance doit être ouverte — le même
    gabarit sert les deux pages, seul le mode change.
    """
    workout = _current_workout()
    if workout is not None and workout.focus == REPRISE:
        return redirect(url_for("workout.reprise"))
    if workout is None:
        focus = next_session_type(_last_focus())
        workout = Workout(focus=focus, date=datetime.now())
        db.session.add(workout)
        db.session.commit()
    exercises = session_exercises(workout.focus, "plyo")
    logged = {pe.id: sorted((s for s in workout.sets
                             if s.program_exercise_id == pe.id),
                            key=lambda s: s.set_number or 0)
              for pe in exercises}
    notes = {n.program_exercise_id: n.text for n in workout.notes_by_exercise}
    return render_template("session.html", workout=workout, mode="plyo",
                           exercises=exercises, logged=logged, notes=notes)


@bp.route("/reprise")
def reprise():
    """Séance de reprise : tout le catalogue, et tu t'arrêtes quand tu veux.

    Elle se lance n'importe quand, en dehors du cycle PPL. Le but n'est pas
    d'en faire le maximum mais de retrouver les exercices qu'on aime après un
    arrêt : rien n'est imposé, rien n'est attendu, et la séance se termine sur
    décision — pas quand une liste est cochée.

    Les exercices sont affichés repliés, contrairement à une séance normale.
    Dix-huit blocs ouverts d'un coup transformeraient la page en mur ; ici on
    ouvre ce qui tente, et ce geste EST le choix.
    """
    workout = _current_workout()
    if workout is not None and workout.focus != REPRISE:
        flash(f"Termine ou annule ta séance {workout.focus} avant "
              "de lancer une reprise.")
        return redirect(url_for("workout.session"))
    if workout is None:
        workout = Workout(focus=REPRISE, date=datetime.now())
        db.session.add(workout)
        db.session.commit()

    exercises = reprise_exercises()
    logged = {pe.id: sorted((s for s in workout.sets
                             if s.program_exercise_id == pe.id),
                            key=lambda s: s.set_number or 0)
              for pe in exercises}
    notes = {n.program_exercise_id: n.text for n in workout.notes_by_exercise}
    return render_template("session.html", workout=workout, mode="reprise",
                           exercises=exercises, logged=logged, notes=notes)


@bp.route("/session/<int:workout_id>/note", methods=["POST"])
def save_note(workout_id):
    """Commentaire d'un exercice, ou de la séance si exercise_id est absent.

    Sauvegarde au fil de l'eau (appelé en AJAX pendant la séance) : on ne veut
    pas qu'un ressenti noté entre deux séries se perde si l'app est fermée.
    """
    workout = db.get_or_404(Workout, workout_id)
    text = (request.form.get("text") or "").strip()
    raw_id = request.form.get("exercise_id")

    if not raw_id:
        workout.notes = text
    else:
        pe = db.get_or_404(ProgramExercise, int(raw_id))
        note = ExerciseNote.query.filter_by(workout_id=workout.id,
                                            program_exercise_id=pe.id).first()
        if note is None:
            note = ExerciseNote(workout_id=workout.id, program_exercise_id=pe.id)
            db.session.add(note)
        note.text = text
    db.session.commit()
    return jsonify(ok=True, saved=bool(text))


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
        # Facultatif : saisi seulement si l'utilisateur a tapé le bouton RIR.
        rir=int(request.form["rir"]) if (request.form.get("rir") or "") != "" else None,
    )
    db.session.add(s)
    db.session.commit()
    return jsonify(ok=True, id=s.id, set_number=s.set_number, reps=s.reps,
                   weight=s.weight_kg, total_sets=pe.sets,
                   rest_sec=pe.rest_sec)


@bp.route("/set/<int:set_id>/delete", methods=["POST"])
def delete_set(set_id):
    """Supprime une série mal saisie et renumérote les suivantes."""
    s = db.get_or_404(ExerciseSet, set_id)
    workout_id, pe_id = s.workout_id, s.program_exercise_id
    db.session.delete(s)
    db.session.flush()
    remaining = (ExerciseSet.query
                 .filter_by(workout_id=workout_id, program_exercise_id=pe_id)
                 .order_by(ExerciseSet.id).all())
    for i, other in enumerate(remaining, start=1):
        other.set_number = i
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/session/<int:workout_id>/finish", methods=["POST"])
def finish_session(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    workout.completed = True
    if request.form.get("notes"):
        workout.notes = request.form["notes"]

    # UNE REPRISE NE TOUCHE PAS AUX CHARGES, ET C'EST LE POINT.
    #
    # On y fait ce qui tente, à l'intensité qui vient. Passer ça dans la
    # double progression ferait lire une série légère comme une régression et
    # déclencherait un deload sur un exercice qui n'a rien perdu — la reprise
    # abîmerait le programme qu'elle est censée redémarrer.
    changes = [] if workout.focus == REPRISE else apply_progression(workout)
    db.session.commit()

    if workout.focus == REPRISE:
        flash(f"Reprise terminée — {len(workout.sets)} séries. "
              "Les charges du programme n'ont pas bougé. 💪")
    else:
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
