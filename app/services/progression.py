"""Rotation PPL continue et double progression automatique."""
from datetime import timedelta

from ..models import db

CYCLE = ["Push", "Pull", "Legs"]
TRAINING_WEEKDAYS = [0, 2, 4, 5]  # lundi, mercredi, vendredi, samedi


def next_session_type(last_focus):
    """Séance suivante dans la rotation continue Push → Pull → Legs."""
    if last_focus not in CYCLE:
        return CYCLE[0]
    return CYCLE[(CYCLE.index(last_focus) + 1) % len(CYCLE)]


def plan_upcoming(last_focus, after_date, count=8):
    """Projette les prochaines séances sur les jours d'entraînement.

    Renvoie [(date, focus), ...] strictement après after_date, en continuant
    la rotation depuis last_focus.
    """
    sessions = []
    focus = last_focus
    day = after_date
    while len(sessions) < count:
        day += timedelta(days=1)
        if day.weekday() in TRAINING_WEEKDAYS:
            focus = next_session_type(focus)
            sessions.append((day, focus))
    return sessions


def apply_progression(workout):
    """Double progression appliquée à la fin d'une séance.

    Toutes les séries au rep_max → charge +increment (repart au bas de la
    fourchette). Toutes les séries sous rep_min → charge -increment (deload).
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
        reps = [s.reps or 0 for s in sets]
        old = pe.weight_kg
        if all(r >= pe.rep_max for r in reps):
            pe.weight_kg = max(0, round(old + pe.increment_kg, 2))
        elif all(r < pe.rep_min for r in reps):
            pe.weight_kg = max(0, round(old - pe.increment_kg, 2))
        if pe.weight_kg != old:
            changes.append(f"{pe.name} : {old:g} → {pe.weight_kg:g} kg")
    db.session.commit()
    return changes
