from datetime import date, datetime

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

from ..models import db, ExerciseNote, ExerciseSet, ProgramExercise, Workout
from ..services import agenda_google, charges
from ..services.progression import (PLYO, REPRISE, SEANCES, apply_progression,
                                    recompute_from_history)

bp = Blueprint("workout", __name__, url_prefix="/workouts")

# Ce que l'écran de la salle dit de chaque séance, sous son nom.
SEANCE_INFO = {
    "Push": "Pectoraux, épaules, triceps",
    "Pull": "Dos, biceps, avant-bras",
    "Legs": "Quadriceps, ischios, mollets",
    PLYO: "Détente pour le volley, à faire frais",
    REPRISE: "Tout le programme, sans toucher aux charges",
}


def _current_workout():
    return (Workout.query.filter_by(completed=False)
            .order_by(Workout.date.desc()).first())


def session_exercises(focus, block="force"):
    """Exercices actifs d'une séance, dans l'ordre choisi sur la page Programme.

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
    pliométrie reste en dehors : elle se fait frais, ce qu'on n'est
    précisément pas en rentrant de plusieurs semaines d'arrêt.
    """
    out = []
    for st in ("push", "pull", "legs"):
        out.extend(session_exercises(st, "force"))
    return out


def exercises_for(focus):
    """Les exercices d'une séance, quel que soit son type."""
    if focus == REPRISE:
        return reprise_exercises()
    if focus == PLYO:
        return session_exercises("plyo", "plyo")
    return session_exercises(focus)


def _mode(focus):
    return "reprise" if focus == REPRISE else "plyo" if focus == PLYO else "force"


def _depuis(jour, today):
    """Depuis quand la séance n'a pas été faite, dit en toutes lettres :
    « il y a 61 jours » seul ne disait pas de quoi il s'agissait."""
    if jour is None:
        return "jamais faite"
    n = (today - jour).days
    if n <= 0:
        return "faite aujourd'hui"
    if n == 1:
        return "faite hier"
    return "faite il y a {} jours".format(n)


def _close(workout):
    """Termine une séance restée ouverte. Renvoie les changements de charge.

    La progression s'applique comme si le bouton avait été touché : les
    séries sont réelles, seul le geste de fin a manqué. Une reprise et la
    plyométrie ne touchent jamais aux charges. Le rappel « termine ta
    séance » n'a plus lieu d'être : il sort de l'agenda.
    """
    agenda_google.retirer(workout)
    workout.completed = True
    if workout.focus in (REPRISE, PLYO):
        return []
    return apply_progression(workout)


@bp.route("/")
def list_workouts():
    """L'écran de la salle : la séance en cours, les cinq au choix, l'historique.

    Rien n'est imposé. L'ancien écran proposait LA séance suivante du cycle,
    et en sauter une obligeait à terminer une séance vide pour passer à la
    sienne ; l'historique en garde une douzaine.
    """
    today = date.today()
    workouts = Workout.query.order_by(Workout.date.desc(), Workout.id.desc()).all()
    current = _current_workout()
    # La plyo date d'avant l'écran de choix : ses exercices se faisaient au
    # sein de Push, Pull ou Legs. Sa dernière fois est donc le dernier jour
    # où l'un d'eux a été fait, quelle que soit la séance.
    plyo_ids = {pe.id for pe in ProgramExercise.query.filter_by(block="plyo")}
    derniere = {}
    for w in workouts:
        if not (w.completed and w.sets):        # la séance en cours n'est pas « faite »
            continue
        if w.focus not in derniere:
            derniere[w.focus] = w.date.date()
        if PLYO not in derniere and any(s.program_exercise_id in plyo_ids
                                        for s in w.sets):
            derniere[PLYO] = w.date.date()
    choix = [{"focus": f, "slug": f.lower(), "info": SEANCE_INFO[f],
              "exercices": len(exercises_for(f)),
              "depuis": _depuis(derniere.get(f), today)}
             for f in SEANCES]
    notes_by_workout = {}
    for n in ExerciseNote.query.all():
        notes_by_workout.setdefault(n.workout_id, {})[n.program_exercise_id] = n.text
    return render_template("workouts.html", workouts=workouts, current=current,
                           choix=choix, today=today,
                           notes_by_workout=notes_by_workout)


@bp.route("/commencer/<seance>", methods=["POST"])
def start(seance):
    """Ouvre la séance choisie sur l'écran de la salle.

    Ce qui était resté ouvert est rangé d'abord, sans rien demander quand il
    n'y a rien à perdre :
    - la même séance, ouverte aujourd'hui : on la reprend ;
    - une séance sans aucune série : supprimée, elle ne contenait rien ;
    - une séance d'un autre jour avec des séries : terminée, progression
      comprise, puisque l'oubli ne portait que sur le bouton de fin ;
    - une autre séance commencée aujourd'hui : on ne la termine qu'avec
      confirmation, car c'est peut-être celle qu'on est en train de faire.
    """
    focus = next((f for f in SEANCES if f.lower() == seance.lower()), None)
    if focus is None:
        abort(404)
    today = date.today()
    confirme = request.form.get("confirmer") == "1"

    ouvertes = (Workout.query.filter_by(completed=False)
                .order_by(Workout.date, Workout.id).all())
    for w in ouvertes:
        if w.focus == focus and w.date.date() == today:
            db.session.commit()
            return redirect(url_for("workout.session"))
    for w in ouvertes:
        if not w.sets:
            agenda_google.retirer(w)
            db.session.delete(w)
            continue
        if w.date.date() == today and not confirme:
            db.session.commit()
            flash("Ta séance {} est en cours ({} séries). Termine-la, ou "
                  "confirme pour passer à {}.".format(w.focus, len(w.sets), focus))
            return redirect(url_for("workout.list_workouts"))
        n = len(w.sets)
        changes = _close(w)
        flash("Séance {} du {} terminée : {} série{}.".format(
            w.focus, w.date.strftime("%d/%m"), n, "s" if n > 1 else ""))
        for c in changes:
            flash("Progression : {}".format(c))

    nouvelle = Workout(focus=focus, date=datetime.now())
    db.session.add(nouvelle)
    db.session.commit()
    # Le rappel du soir est posé dès le début ; terminer la séance le retire.
    agenda_google.planifier(nouvelle, url_for("workout.list_workouts", _external=True))
    return redirect(url_for("workout.session"))


def _previous(exercises, workout):
    """La dernière fois que chaque exercice a été fait, hors séance en cours.

    Une reprise compte : ses séries sont de vraies charges, et c'est souvent
    la seule trace récente d'un exercice. La note laissée ce jour-là sur
    l'exercice l'accompagne (« siège au cran 4 », « on monte à 4 séries »).
    """
    ids = [pe.id for pe in exercises]
    if not ids:
        return {}
    rows = (db.session.query(ExerciseSet, Workout)
            .join(Workout, ExerciseSet.workout_id == Workout.id)
            .filter(ExerciseSet.program_exercise_id.in_(ids),
                    Workout.id != workout.id)
            .order_by(Workout.date.desc(), Workout.id.desc(),
                      ExerciseSet.set_number, ExerciseSet.id).all())
    out = {}
    for s, w in rows:
        p = out.setdefault(s.program_exercise_id, {"workout": w, "sets": []})
        if p["workout"].id == w.id:
            p["sets"].append(s)
    for pe_id, p in out.items():
        note = ExerciseNote.query.filter_by(workout_id=p["workout"].id,
                                            program_exercise_id=pe_id).first()
        p["note"] = (note.text or "").strip() if note else ""
    return out


def _card(pe, done, prev, note):
    """Tout ce que la page et son script savent d'un exercice.

    Les charges arrivent en kilos, arrondies comme à l'écran, avec le cran
    exact de la machine : le script avance d'un cran à la fois, sans jamais
    proposer une charge qui n'existe pas sur la pile.
    """
    loaded = pe.block != "plyo"

    done_rows = [{"id": s.id, "v": charges.shown(s.weight_kg, pe),
                  "reps": s.reps or 0, "rir": s.rir} for s in done]
    prev_rows = [{"v": charges.shown(s.weight_kg, pe), "reps": s.reps or 0}
                 for s in (prev["sets"] if prev else [])]
    target = charges.shown(pe.weight_kg, pe) if loaded and pe.weight_kg else None
    # La charge proposée pour la série suivante : celle qu'on vient de
    # soulever, sinon celle du programme, sinon celle de la dernière fois.
    if not loaded:
        start = 0
    elif done_rows:
        start = done_rows[-1]["v"]
    elif target is not None:
        start = target
    elif prev_rows:
        start = prev_rows[0]["v"]
    else:
        start = 0
    return {
        "pe": pe,
        "done": done_rows,
        "prev": prev_rows,
        "prev_date": prev["workout"].date if prev else None,
        "prev_focus": prev["workout"].focus if prev else None,
        "prev_note": prev["note"] if prev else "",
        "note": note,
        "loaded": loaded,
        "target": target,
        "data": {
            "id": pe.id, "name": pe.name, "sets": pe.sets or 0,
            "repmin": pe.rep_min or 0, "repmax": pe.rep_max or 0,
            "kind": pe.unit or "reps", "block": pe.block, "rest": pe.rest_sec or 60,
            "loaded": loaded, **charges.stepper(pe),
            "inc": charges.increment_steps(pe),
            "start": start,
            "assist": (pe.increment_kg or 0) < 0,
            "done": done_rows,
            "prev": prev_rows,
        },
    }


def _render(workout):
    exercises = exercises_for(workout.focus)
    logged = {pe.id: [] for pe in exercises}
    for s in sorted(workout.sets, key=lambda s: (s.set_number or 0, s.id)):
        if s.program_exercise_id in logged:
            logged[s.program_exercise_id].append(s)
    notes = {n.program_exercise_id: n.text for n in workout.notes_by_exercise}
    previous = _previous(exercises, workout)
    cards = [_card(pe, logged[pe.id], previous.get(pe.id), notes.get(pe.id, ""))
             for pe in exercises]
    return render_template("session.html", workout=workout,
                           mode=_mode(workout.focus), cards=cards,
                           info=SEANCE_INFO.get(workout.focus, ""))


@bp.route("/session")
def session():
    """La séance en cours. Sans séance ouverte, retour à l'écran de la salle :
    lire une page ne crée jamais de séance, seul le choix le fait."""
    workout = _current_workout()
    if workout is None:
        return redirect(url_for("workout.list_workouts"))
    return _render(workout)


@bp.route("/plyo")
@bp.route("/reprise")
def ancienne_page():
    """Les anciennes adresses de la plyo et de la reprise, gardées pour les
    favoris : elles mènent à la séance en cours, ou à l'écran de choix."""
    return redirect(url_for("workout.session"))


@bp.route("/programme")
def programme():
    groups = [(st, session_exercises(st, "plyo" if st == "plyo" else "force"))
              for st in ("push", "pull", "legs", "plyo")]
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


def _nombre(raw, default=0.0):
    try:
        return float((raw or "").replace(",", "."))
    except ValueError:
        return default


@bp.route("/programme/update", methods=["POST"])
def update_programme():
    """Correction manuelle d'un exercice (machine, charge, fourchette, séries).

    La charge se saisit en kilos, telle qu'elle s'affiche (31,8) ; elle
    retombe sur le cran exact de la machine.
    """
    pe = db.get_or_404(ProgramExercise, int(request.form["id"]))
    if request.form.get("load_unit") in charges.UNITS:
        charges.set_machine(pe, request.form["load_unit"],
                            _nombre(request.form.get("load_step")))
    if "weight" in request.form:
        pe.weight_kg = charges.from_display(_nombre(request.form.get("weight")), pe)
    pe.rep_min = int(request.form.get("rep_min") or pe.rep_min)
    pe.rep_max = int(request.form.get("rep_max") or pe.rep_max)
    pe.sets = int(request.form.get("sets") or pe.sets)
    db.session.commit()
    detail = "{}×{}-{}".format(pe.sets, pe.rep_min, pe.rep_max)
    if pe.block != "plyo":
        detail += " à {}".format(charges.label(pe.weight_kg, pe))
    flash("{} mis à jour : {}.".format(pe.name, detail))
    return redirect(url_for("workout.programme") + "#" + pe.session_type)


@bp.route("/programme/<int:pe_id>/machine", methods=["POST"])
def machine(pe_id):
    """Graduation de la pile d'une machine, réglée depuis la séance (AJAX)."""
    pe = db.get_or_404(ProgramExercise, pe_id)
    unit = request.form.get("load_unit")
    if unit not in charges.UNITS:
        return jsonify(ok=False, erreur="Unité inconnue."), 400
    extra = request.form.get("load_extra")
    charges.set_machine(pe, unit, _nombre(request.form.get("load_step")),
                        _nombre(extra) if extra is not None else None)
    db.session.commit()
    return jsonify(ok=True, machine=charges.machine_label(pe),
                   charge=charges.label(pe.weight_kg, pe))


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
    """Enregistre une série. La charge arrive en kilos, telle qu'affichée."""
    workout = db.get_or_404(Workout, workout_id)
    pe = db.get_or_404(ProgramExercise, int(request.form["exercise_id"]))
    done = [s for s in workout.sets if s.program_exercise_id == pe.id]
    s = ExerciseSet(
        workout_id=workout.id,
        program_exercise_id=pe.id,
        exercise=pe.name,
        set_number=len(done) + 1,
        reps=int(request.form.get("reps") or 0),
        weight_kg=charges.from_display(_nombre(request.form.get("weight")), pe),
        # Facultatif : saisi seulement si l'utilisateur a tapé le bouton RIR.
        rir=int(request.form["rir"]) if (request.form.get("rir") or "") != "" else None,
    )
    db.session.add(s)
    db.session.commit()
    return jsonify(ok=True, id=s.id, set_number=s.set_number, reps=s.reps,
                   weight=charges.shown(s.weight_kg, pe), rir=s.rir,
                   total_sets=pe.sets,
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
    if request.form.get("notes"):
        workout.notes = request.form["notes"]

    # UNE REPRISE NE TOUCHE PAS AUX CHARGES, ET C'EST LE POINT.
    #
    # On y fait ce qui tente, à l'intensité qui vient. Passer ça dans la
    # double progression ferait lire une série légère comme une régression et
    # déclencherait un deload sur un exercice qui n'a rien perdu : la reprise
    # abîmerait le programme qu'elle est censée redémarrer. La plyométrie
    # non plus : elle progresse en hauteur, jamais en charge.
    changes = _close(workout)
    db.session.commit()

    n = len(workout.sets)
    if workout.focus == REPRISE:
        flash(f"Reprise terminée : {n} séries. "
              "Les charges du programme n'ont pas bougé. 💪")
    else:
        flash(f"Séance {workout.focus} terminée : {n} séries. 💪")
    for c in changes:
        flash(f"Progression : {c}")
    return redirect(url_for("workout.list_workouts"))


@bp.route("/session/<int:workout_id>/delete", methods=["POST"])
def delete_session(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    agenda_google.retirer(workout)
    db.session.delete(workout)
    db.session.commit()
    flash("Séance annulée.")
    return redirect(url_for("workout.list_workouts"))
