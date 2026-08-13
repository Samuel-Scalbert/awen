"""Rotation PPL continue et double progression automatique."""
from datetime import timedelta

from ..models import db

CYCLE = ["Push", "Pull", "Legs"]
# 3 séances par semaine : lundi, mercredi, vendredi. Avec un cycle de 3 séances,
# chaque muscle passe une fois par semaine et tombe le même jour d'une semaine
# sur l'autre. La rotation reste continue (et non figée par jour) : si une
# séance saute, la suivante reprend là où le cycle s'était arrêté, plutôt que de
# sacrifier définitivement un groupe musculaire.
TRAINING_WEEKDAYS = [0, 2, 4]


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
            # Charges hétérogènes : comparer des reps à 18 kg et à 32,5 kg
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
            pe.weight_kg = max(0, round(base + 2 * pe.increment_kg, 2))
            suffix = " (surperformance, double palier)"
        elif all(r >= pe.rep_max for r in reps):
            pe.weight_kg = max(0, round(base + pe.increment_kg, 2))
        elif all(r < pe.rep_min for r in reps):
            pe.weight_kg = max(0, round(base - pe.increment_kg, 2))
            suffix = " (deload, on corrige)"
        if pe.weight_kg != old:
            changes.append(f"{pe.name} : {old:g} → {pe.weight_kg:g} kg{suffix}")
    db.session.commit()
    return changes
