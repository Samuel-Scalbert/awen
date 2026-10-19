"""Séances au choix, suggestion PPL et double progression automatique."""
from datetime import datetime, timedelta

from sqlalchemy import func

from ..models import db
from .charges import label, snap

CYCLE = ["Pull", "Push", "Legs"]
# 3 séances par semaine : lundi, mercredi, vendredi. Ce sont les jours où le
# coach attend une séance, où l'accueil en propose une et où le rappel du
# soir se déclenche si rien n'a été noté.
TRAINING_WEEKDAYS = [0, 2, 4]

# Les focus hors PPL. Ils ne sont jamais dans CYCLE, ce qui suffit à les
# faire ignorer par la suggestion, mais PAS par les fonctions qui lisent
# l'historique, qui doivent les exclure explicitement.
REPRISE = "Reprise"
PLYO = "Plyo"

# L'écran de la salle propose les cinq séances dans cet ordre, toujours le
# même : c'est un geste que la main apprend. Aucune n'est imposée.
SEANCES = ["Push", "Pull", "Legs", PLYO, REPRISE]


def rotation():
    """Push, Pull et Legs, de la moins récemment faite à la plus récente.

    Depuis que la séance se choisit en arrivant à la salle, « la suivante
    dans le cycle » ne veut plus rien dire : après Legs puis Push, le cycle
    reproposait Legs. La séance la plus utile est celle qui attend depuis le
    plus longtemps. Une séance fermée sans aucune série ne compte pas :
    c'était le passage obligé de l'ancien écran, pas un entraînement.
    """
    from ..models import ExerciseSet, Workout
    rows = (db.session.query(Workout.focus, func.max(Workout.date))
            .join(ExerciseSet, ExerciseSet.workout_id == Workout.id)
            .filter(Workout.focus.in_(CYCLE))
            .group_by(Workout.focus).all())
    last = dict(rows)
    return sorted(CYCLE, key=lambda f: (f in last, last.get(f) or datetime.min,
                                        CYCLE.index(f)))


def upcoming(after_date, count=8, order=None):
    """Les prochaines séances suggérées, sur les jours d'entraînement.

    Renvoie [(date, focus), ...] strictement après after_date, en commençant
    par la séance qui attend depuis le plus longtemps. C'est une suggestion :
    l'écran de la salle laisse choisir.
    """
    order = order or rotation()
    sessions = []
    day = after_date
    while len(sessions) < count:
        day += timedelta(days=1)
        if day.weekday() in TRAINING_WEEKDAYS:
            sessions.append((day, order[len(sessions) % len(order)]))
    return sessions


# Marge de reps au-dessus du max qui déclenche un double incrément
OVERPERF_MARGIN = 3


def working_sets(sets, planned):
    """Les séries de travail retenues pour juger la progression.

    Les `planned` dernières séries saisies, dans l'ordre de saisie. On ignore
    donc ce qui a précédé (échauffement, série ratée en ouverture, essai à une
    autre charge) : ce qui compte est ce qui a réellement été tenu en fin
    d'exercice, comme le ferait un coach.
    """
    return sorted(sets, key=lambda s: s.id)[-planned:] if sets else []


def apply_progression(workout):
    """Double progression appliquée à la fin d'une séance.

    Jugée sur les séries de travail (voir working_sets) et à charge constante :
    toutes au rep_max → +increment ; toutes à rep_max+3 → double palier ;
    toutes sous rep_min → deload. Si ces séries ont été faites à des charges
    différentes, il n'y a pas de comparaison possible et rien ne bouge.
    La nouvelle charge tombe toujours sur un cran de la machine.
    Renvoie la liste des changements pour affichage.
    """
    by_exercise = {}
    for s in workout.sets:
        if s.program_exercise is not None:
            by_exercise.setdefault(s.program_exercise, []).append(s)

    changes = []
    for pe, sets in by_exercise.items():
        if not pe.increment_kg or len(sets) < pe.sets:
            continue
        recent = working_sets(sets, pe.sets)
        weights = {round(s.weight_kg or 0, 2) for s in recent}
        if len(weights) > 1:
            # Charges hétérogènes : comparer des reps à 70 et à 90 livres
            # n'a aucun sens, on préfère ne rien changer et le dire.
            changes.append(
                "{} : charges variables sur les séries de travail, "
                "progression en pause".format(pe.name))
            continue

        base = weights.pop()                  # charge réellement utilisée
        reps = [s.reps or 0 for s in recent]
        old = pe.weight_kg
        suffix = ""
        if all(r >= pe.rep_max + OVERPERF_MARGIN for r in reps):
            pe.weight_kg = snap(base + 2 * pe.increment_kg, pe)
            suffix = " (surperformance, double palier)"
        elif all(r >= pe.rep_max for r in reps):
            pe.weight_kg = snap(base + pe.increment_kg, pe)
        elif all(r < pe.rep_min for r in reps):
            pe.weight_kg = snap(base - pe.increment_kg, pe)
            suffix = " (deload, on corrige)"
        if pe.weight_kg != old:
            changes.append("{} : {} → {}{}".format(
                pe.name, label(old, pe), label(pe.weight_kg, pe), suffix))
    db.session.commit()
    return changes


def recompute_from_history():
    """Recale la charge de chaque exercice sur ce qui a réellement été soulevé.

    Utile quand le programme et la réalité ont divergé : saisie erronée,
    machine changée, ou charge modifiée à la main en salle sans que la
    progression ait suivi. On repart de la dernière séance terminée où
    l'exercice apparaît, et on retient la charge médiane de ses séries de
    travail, ramenée sur un cran de la machine — insensible à une série
    d'essai ou d'échauffement isolée.

    La plyométrie et les exercices au poids du corps sont ignorés : ils n'ont
    pas de charge à recaler.
    """
    from ..models import ExerciseSet, ProgramExercise, Workout

    # Les reprises sont exclues. On y fait ce qui tente, à l'intensité qui
    # vient : recaler le programme sur une séance de reprise remplacerait les
    # charges réelles par celles d'une remise en route. C'est précisément ce
    # que la séance de reprise promet de ne jamais faire.
    completed = {w.id: w.date for w in Workout.query.filter_by(completed=True)
                 if w.focus != REPRISE}
    changes = []

    for pe in ProgramExercise.query.filter(ProgramExercise.active.is_(True)):
        if pe.block == "plyo" or not pe.increment_kg:
            continue

        sets = [s for s in ExerciseSet.query
                .filter_by(program_exercise_id=pe.id).order_by(ExerciseSet.id)
                if s.workout_id in completed]
        if not sets:
            continue

        last_id = max(sets, key=lambda s: completed[s.workout_id]).workout_id
        last_sets = [s for s in sets if s.workout_id == last_id]
        weights = sorted((s.weight_kg or 0) for s in working_sets(last_sets, pe.sets))
        if not weights:
            continue

        actual = snap(weights[len(weights) // 2], pe)
        if actual and actual != pe.weight_kg:
            changes.append("{} : {} → {}".format(
                pe.name, label(pe.weight_kg, pe), label(actual, pe)))
            pe.weight_kg = actual

    db.session.commit()
    return changes
